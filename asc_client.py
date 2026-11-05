#!/usr/bin/env python3
"""
app-store-release-cli: Generic App Store Connect Release & Metadata Synchronization Tool.
Works with iOS (Native Swift), Flutter, React Native, or any framework.
Zero external pip dependencies: uses macOS/Linux system openssl for ES256 JWT signing.
"""

import sys
import os
import csv
import json
import time
import argparse
import base64
import subprocess
import urllib.request
import urllib.parse
import urllib.error

# Universal mapping from common language names/codes to App Store Connect locale identifiers
LOCALE_MAP = {
    # English variants
    'english': ['en-US', 'en-GB', 'en-CA', 'en-AU', 'en'],
    'en': ['en-US', 'en-GB', 'en-CA', 'en-AU'],
    'en-us': ['en-US'],
    'en-gb': ['en-GB'],
    'en-ca': ['en-CA'],
    'en-au': ['en-AU'],
    # French
    'french': ['fr-FR', 'fr-CA', 'fr'],
    'fr': ['fr-FR', 'fr-CA'],
    'fr-fr': ['fr-FR'],
    'fr-ca': ['fr-CA'],
    # German
    'german': ['de-DE', 'de'],
    'de': ['de-DE'],
    'de-de': ['de-DE'],
    # Spanish
    'spanish': ['es-ES', 'es-MX', 'es'],
    'es': ['es-ES', 'es-MX'],
    'es-es': ['es-ES'],
    'es-mx': ['es-MX'],
    # Portuguese
    'portuguese': ['pt-BR', 'pt-PT', 'pt'],
    'portuguese (br)': ['pt-BR', 'pt'],
    'portuguese (brazil)': ['pt-BR', 'pt'],
    'portuguese (portugal)': ['pt-PT', 'pt'],
    'pt': ['pt-BR', 'pt-PT'],
    'pt-br': ['pt-BR'],
    'pt-pt': ['pt-PT'],
    # Italian
    'italian': ['it'],
    'it': ['it'],
    # Dutch
    'dutch': ['nl-NL', 'nl'],
    'nl': ['nl-NL'],
    # Ukrainian
    'ukrainian': ['uk'],
    'uk': ['uk'],
    # Japanese
    'japanese': ['ja'],
    'ja': ['ja'],
    # Korean
    'korean': ['ko'],
    'ko': ['ko'],
    # Chinese
    'chinese (simplified)': ['zh-Hans'],
    'chinese (traditional)': ['zh-Hant'],
    'zh-hans': ['zh-Hans'],
    'zh-hant': ['zh-Hant'],
    'zh-cn': ['zh-Hans'],
    'zh-tw': ['zh-Hant'],
    # Other common languages
    'arabic': ['ar-SA', 'ar'],
    'ar': ['ar-SA'],
    'turkish': ['tr'],
    'tr': ['tr'],
    'polish': ['pl'],
    'pl': ['pl'],
    'swedish': ['sv'],
    'sv': ['sv'],
    'danish': ['da'],
    'da': ['da'],
    'finnish': ['fi'],
    'fi': ['fi'],
    'norwegian': ['no'],
    'no': ['no'],
    'czech': ['cs'],
    'cs': ['cs'],
    'hungarian': ['hu'],
    'hu': ['hu'],
    'greek': ['el'],
    'el': ['el'],
    'hebrew': ['he'],
    'he': ['he'],
    'hindi': ['hi'],
    'hi': ['hi'],
    'indonesian': ['id'],
    'id': ['id'],
    'malay': ['ms'],
    'ms': ['ms'],
    'thai': ['th'],
    'th': ['th'],
    'vietnamese': ['vi'],
    'vi': ['vi'],
    'croatian': ['hr'],
    'hr': ['hr'],
    'slovak': ['sk'],
    'sk': ['sk'],
    'romanian': ['ro'],
    'ro': ['ro'],
}

EXAMPLE_ISSUER_ID = "57246542-96fe-1a63-e053-0824d011072a"

def base64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode('utf-8').rstrip('=')

def der_to_raw_p1363(der: bytes) -> bytes:
    """Convert ASN.1 DER ECDSA signature to IEEE P1363 raw (r, s) format (64 bytes)."""
    idx = 2
    if der[1] & 0x80:
        idx += (der[1] & 0x7F)
    assert der[idx] == 0x02, "Invalid DER signature format"
    idx += 1
    r_len = der[idx]
    idx += 1
    r = int.from_bytes(der[idx:idx+r_len], 'big')
    idx += r_len
    assert der[idx] == 0x02, "Invalid DER signature format"
    idx += 1
    s_len = der[idx]
    idx += 1
    s = int.from_bytes(der[idx:idx+s_len], 'big')
    return r.to_bytes(32, 'big') + s.to_bytes(32, 'big')

def generate_jwt(key_id: str, issuer_id: str, key_path: str, expiration_seconds: int = 900) -> str:
    """Generate ES256 JWT for App Store Connect API using system openssl."""
    now = int(time.time())
    header = {"alg": "ES256", "kid": key_id, "typ": "JWT"}
    payload = {
        "iss": issuer_id,
        "iat": now - 30, # 30s buffer for clock drift
        "exp": now + expiration_seconds,
        "aud": "appstoreconnect-v1"
    }
    
    header_b64 = base64url_encode(json.dumps(header, separators=(',', ':')).encode('utf-8'))
    payload_b64 = base64url_encode(json.dumps(payload, separators=(',', ':')).encode('utf-8'))
    signing_input = f"{header_b64}.{payload_b64}".encode('utf-8')
    
    proc = subprocess.Popen(
        ['openssl', 'dgst', '-sha256', '-sign', key_path],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    der_sig, err = proc.communicate(input=signing_input)
    if proc.returncode != 0:
        raise RuntimeError(f"OpenSSL signing failed: {err.decode('utf-8', errors='ignore')}")
    
    raw_sig = der_to_raw_p1363(der_sig)
    sig_b64 = base64url_encode(raw_sig)
    return f"{header_b64}.{payload_b64}.{sig_b64}"

class AppStoreConnectClient:
    BASE_URL = "https://api.appstoreconnect.apple.com/v1"
    
    def __init__(self, key_id: str, issuer_id: str, key_path: str):
        self.key_id = key_id
        self.issuer_id = issuer_id
        self.key_path = key_path
        self._token = None
        self._token_time = 0
        
    def get_token(self) -> str:
        # Refresh token every 12 minutes
        if not self._token or (time.time() - self._token_time) > 720:
            self._token = generate_jwt(self.key_id, self.issuer_id, self.key_path)
            self._token_time = time.time()
        return self._token

    def request(self, method: str, path: str, payload: dict = None) -> dict:
        url = f"{self.BASE_URL}{path}" if path.startswith('/') else path
        headers = {
            "Authorization": f"Bearer {self.get_token()}",
            "Content-Type": "application/json"
        }
        data = json.dumps(payload).encode('utf-8') if payload else None
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        
        try:
            with urllib.request.urlopen(req) as resp:
                status = resp.status
                if status == 204:
                    return {}
                body = resp.read().decode('utf-8')
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as e:
            err_body = e.read().decode('utf-8', errors='ignore')
            raise RuntimeError(f"App Store Connect API error ({e.code}) on {method} {url}: {err_body}")

def read_metadata_csv(csv_path: str) -> list:
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"Metadata CSV not found at: {csv_path}")
        
    entries = []
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            lang = row.get('Language') or row.get('language') or row.get('Locale') or row.get('locale') or ''
            name = row.get('Name') or row.get('name') or row.get('App Name') or ''
            subtitle = row.get('Subtitle') or row.get('subtitle') or ''
            promo = row.get('Promotional Text') or row.get('promotional text') or row.get('Promo') or ''
            whats_new = row.get("What's New") or row.get("whats_new") or row.get("What’s New") or row.get("Release Notes") or ''
            desc = row.get('Description') or row.get('description') or ''
            keywords = row.get('Keywords') or row.get('keywords') or ''
            
            if lang.strip():
                entries.append({
                    'language': lang.strip(),
                    'name': name.strip(),
                    'subtitle': subtitle.strip(),
                    'promotional_text': promo.strip(),
                    'whats_new': whats_new.strip(),
                    'description': desc.strip(),
                    'keywords': keywords.strip(),
                })
    return entries

def validate_entries(entries: list):
    print("🔍 Validating metadata character limits...")
    has_errors = False
    for item in entries:
        lang = item['language']
        checks = [
            ('Name', item['name'], 30),
            ('Subtitle', item['subtitle'], 30),
            ('Promotional Text', item['promotional_text'], 170),
            ('Keywords', item['keywords'], 100),
            ("What's New", item['whats_new'], 4000),
            ('Description', item['description'], 4000),
        ]
        for field, val, max_len in checks:
            if len(val) > max_len:
                print(f"  ❌ [{lang}] {field} exceeds limit: {len(val)} > {max_len}")
                has_errors = True
    if has_errors:
        raise ValueError("Metadata validation failed due to character limits.")
    print("  ✅ All metadata fields within App Store Connect limits.")

def match_locale(lang_name: str, available_locales: list) -> str:
    norm = lang_name.lower().strip()
    # Check exact match in available locales
    for avail in available_locales:
        if norm == avail.lower():
            return avail
            
    # Check candidates from map
    candidates = LOCALE_MAP.get(norm, [norm])
    for cand in candidates:
        for avail in available_locales:
            if cand.lower() == avail.lower():
                return avail
                
    # Prefix match (e.g. 'de' matches 'de-DE')
    for avail in available_locales:
        if avail.lower().startswith(norm[:2]):
            return avail
            
    return candidates[0]

def main():
    parser = argparse.ArgumentParser(
        description="Generic App Store Connect Release, Metadata Sync & Review Submission CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Validate CSV and test connection (dry run):
  ./release.sh --bundle-id com.example.myapp --dry-run

  # Sync metadata & link latest TestFlight build:
  ./release.sh --bundle-id com.example.myapp

  # Sync metadata, link build, and submit for review:
  ./release.sh --bundle-id com.example.myapp --submit

  # Create a brand new App Store version if no editable version exists:
  ./release.sh --bundle-id com.example.myapp --create-version 1.0.1 --submit
        """
    )
    parser.add_argument('--bundle-id', default=os.getenv('APP_BUNDLE_ID'), help="Bundle identifier (e.g. com.example.app). Required.")
    parser.add_argument('--csv', default=os.getenv('APP_METADATA_CSV', 'app_store_metadata.csv'), help="Path to metadata CSV file (default: app_store_metadata.csv)")
    parser.add_argument('--version', default=None, help="App Store version to target (e.g. 1.4.0). Defaults to active editable version.")
    parser.add_argument('--create-version', default=None, help="Create a new App Store version if needed (e.g. 1.4.1)")
    parser.add_argument('--key-id', default=os.getenv('ASC_KEY_ID'), help="App Store Connect API Key ID")
    parser.add_argument('--issuer-id', default=os.getenv('ASC_ISSUER_ID'), help="App Store Connect Issuer ID")
    parser.add_argument('--key-file', default=os.getenv('ASC_KEY_FILE'), help="Path to AuthKey_*.p8 private key file")
    parser.add_argument('--no-attach-build', action='store_true', help="Skip automatically attaching the latest uploaded build")
    parser.add_argument('--submit', action='store_true', help="Submit the release for App Store review")
    parser.add_argument('--dry-run', action='store_true', help="Validate CSV and test connection without modifying anything")
    
    args = parser.parse_args()
    
    print("==================================================")
    print("🚀 App Store Connect Release & Metadata Sync")
    print("==================================================")
    
    # 1. Check bundle ID
    if not args.bundle_id:
        print("\n❌ Error: Bundle ID is required!")
        print("Please provide --bundle-id <your.bundle.id> or set APP_BUNDLE_ID in .env.")
        sys.exit(1)
        
    # 2. Read & validate CSV
    entries = read_metadata_csv(args.csv)
    print(f"📖 Loaded {len(entries)} language entries from: {args.csv}")
    validate_entries(entries)
    
    # 3. Check credentials
    if not (args.key_id and args.issuer_id and args.key_file):
        print("\n⚠️  Missing App Store Connect API Credentials!")
        print("Please provide via arguments or environment variables in .env:")
        print("  - ASC_KEY_ID (e.g. 2X9R4HXF34)")
        print("  - ASC_ISSUER_ID (e.g. 57246542-96fe-1a63-e053-0824d011072a)")
        print("  - ASC_KEY_FILE (path to AuthKey_XXXXXX.p8)")
        if args.dry_run:
            print("\n[Dry-run completed successfully for CSV validation.]")
            sys.exit(0)
        sys.exit(1)
        
    if args.issuer_id.strip() == EXAMPLE_ISSUER_ID:
        print(f"\n⚠️  ASC_ISSUER_ID is still set to the example template UUID ({EXAMPLE_ISSUER_ID}).")
        print("Please copy your real Issuer ID from App Store Connect:")
        print("  1. Go to App Store Connect -> Users and Access -> Integrations")
        print("  2. Select 'App Store Connect API' on the left")
        print("  3. Copy the 'Issuer ID' displayed at the top above the keys table")
        print("  4. Update ASC_ISSUER_ID in .env")
        if args.dry_run:
            print("\n[Dry-run completed for CSV validation. Update Issuer ID to test live connection.]")
            sys.exit(0)
        sys.exit(1)
        
    if not os.path.exists(args.key_file):
        print(f"\n⚠️  Private key file not found: {args.key_file}")
        if args.dry_run:
            print("[Dry-run completed successfully for CSV validation. Set real key file to test live connection.]")
            sys.exit(0)
        sys.exit(1)
        
    client = AppStoreConnectClient(args.key_id, args.issuer_id, args.key_file)
    
    # 4. Locate App
    print(f"\n📱 Finding app with Bundle ID: {args.bundle_id}...")
    try:
        apps_resp = client.request("GET", f"/apps?filter[bundleId]={args.bundle_id}")
    except RuntimeError as e:
        if "401" in str(e):
            print("\n❌ 401 Unauthorized from App Store Connect.")
            print("Please double check that:")
            print(f"  • Key ID ({args.key_id}) matches the key file name.")
            print(f"  • Issuer ID ({args.issuer_id}) matches the Issuer ID in Users & Access -> Integrations.")
            print(f"  • Key file ({args.key_file}) is the original uncorrupted .p8 file downloaded from Apple.")
            if args.dry_run:
                print("\n[Dry-run stopped at authentication check]")
                sys.exit(1)
        raise
        
    apps_data = apps_resp.get('data', [])
    if not apps_data:
        print(f"❌ No app found in App Store Connect with Bundle ID '{args.bundle_id}'")
        sys.exit(1)
    app_id = apps_data[0]['id']
    app_name = apps_data[0]['attributes'].get('name', 'Unknown')
    print(f"  ✅ Found App: '{app_name}' (ID: {app_id})")
    
    # 5. Locate App Store Version
    print("\n🔍 Finding App Store version...")
    versions_resp = client.request("GET", f"/apps/{app_id}/appStoreVersions")
    versions = versions_resp.get('data', [])
    
    target_version = None
    if args.version:
        for v in versions:
            if v['attributes'].get('versionString') == args.version:
                target_version = v
                break
    else:
        for v in versions:
            state = v['attributes'].get('appStoreState')
            if state in ('PREPARE_FOR_SUBMISSION', 'DEVELOPER_REJECTED', 'REJECTED'):
                target_version = v
                break
                
    if not target_version:
        if args.create_version:
            print(f"  Creating new App Store Version '{args.create_version}'...")
            if args.dry_run:
                print(f"  ℹ️ [Dry-Run] Would create new version: {args.create_version}")
                version_id = "dry-run-version-id"
                version_str = args.create_version
                version_state = "PREPARE_FOR_SUBMISSION"
                target_version = {
                    'id': version_id,
                    'attributes': {'versionString': version_str, 'appStoreState': version_state}
                }
            else:
                create_payload = {
                    "data": {
                        "type": "appStoreVersions",
                        "attributes": {
                            "platform": "IOS",
                            "versionString": args.create_version
                        },
                        "relationships": {
                            "app": {
                                "data": {
                                    "type": "apps",
                                    "id": app_id
                                }
                            }
                        }
                    }
                }
                new_ver_resp = client.request("POST", "/appStoreVersions", create_payload)
                target_version = new_ver_resp['data']
                print(f"  ✅ Created new version: {args.create_version}")
        else:
            avail_versions = [f"{v['attributes'].get('versionString')} ({v['attributes'].get('appStoreState')})" for v in versions]
            print(f"❌ Target version not found or not in editable state. Found: {', '.join(avail_versions)}")
            print("💡 Tip: To target an existing version, pass --version <ver> (e.g. --version 1.4.0)")
            print("💡 Tip: To create a new version, pass --create-version <ver> (e.g. --create-version 1.4.1)")
            sys.exit(1)
        
    version_id = target_version['id']
    version_str = target_version['attributes'].get('versionString')
    version_state = target_version['attributes'].get('appStoreState')
    print(f"  ✅ Target Version: {version_str} (State: {version_state}, ID: {version_id})")
    
    # 6. Fetch existing version localizations
    print("\n🌐 Fetching existing localizations for version...")
    if version_id == "dry-run-version-id":
        available_locales = [match_locale(item['language'], ['en-US', 'en-GB']) for item in entries]
        existing_locs = {loc: {'id': f'mock-{loc}'} for loc in available_locales}
    else:
        loc_resp = client.request("GET", f"/appStoreVersions/{version_id}/appStoreVersionLocalizations")
        existing_locs = {loc['attributes']['locale']: loc for loc in loc_resp.get('data', [])}
        available_locales = list(existing_locs.keys())
    print(f"  Found existing locales: {', '.join(available_locales)}")
    
    if args.dry_run:
        print("\n🔍 DRY-RUN MODE: Showing matching plan without updating:")
        for item in entries:
            target_locale = match_locale(item['language'], available_locales)
            print(f"  • {item['language']} -> locale: {target_locale} (exists: {target_locale in existing_locs})")
            if item.get('promotional_text'):
                print(f"    - Promotional Text: {item['promotional_text'][:50]}... ({len(item['promotional_text'])} chars)")
            if item.get('whats_new'):
                print(f"    - What's New: {item['whats_new'].splitlines()[0]} ({len(item['whats_new'])} chars)")
            if item.get('keywords'):
                print(f"    - Keywords: {item['keywords'][:50]}... ({len(item['keywords'])} chars)")
        print("\n✅ Dry run complete. Everything looks good!")
        sys.exit(0)
        
    # 7. Apply version localizations
    print("\n📝 Updating App Store Version localizations...")
    for item in entries:
        locale_code = match_locale(item['language'], available_locales)
        print(f"  ➡️ Processing {item['language']} ({locale_code})...")
        
        loc_attributes = {}
        if item.get('whats_new'):
            loc_attributes['whatsNew'] = item['whats_new']
        if item.get('description'):
            loc_attributes['description'] = item['description']
        if item.get('keywords'):
            loc_attributes['keywords'] = item['keywords']
        if item.get('promotional_text'):
            loc_attributes['promotionalText'] = item['promotional_text']
            
        if locale_code in existing_locs:
            loc_id = existing_locs[locale_code]['id']
            payload = {
                "data": {
                    "type": "appStoreVersionLocalizations",
                    "id": loc_id,
                    "attributes": loc_attributes
                }
            }
            client.request("PATCH", f"/appStoreVersionLocalizations/{loc_id}", payload)
            print(f"    ✅ Updated localization {locale_code}")
        else:
            payload = {
                "data": {
                    "type": "appStoreVersionLocalizations",
                    "attributes": {
                        "locale": locale_code,
                        **loc_attributes
                    },
                    "relationships": {
                        "appStoreVersion": {
                            "data": {
                                "type": "appStoreVersions",
                                "id": version_id
                            }
                        }
                    }
                }
            }
            client.request("POST", "/appStoreVersionLocalizations", payload)
            print(f"    ✅ Created new localization {locale_code}")
            
    # 8. Check/Attach Build if requested
    if not args.no_attach_build:
        print("\n📦 Checking uploaded build...")
        builds_resp = client.request("GET", f"/builds?filter[app]={app_id}&limit=10")
        builds = builds_resp.get('data', [])
            
        if builds:
            latest_build = builds[0]
            build_id = latest_build['id']
            build_num = latest_build['attributes'].get('version', 'Unknown')
            build_state = latest_build['attributes'].get('processingState', 'Unknown')
            print(f"  Found latest build: Build {build_num} (State: {build_state}, ID: {build_id})")
            
            attach_payload = {
                "data": {
                    "type": "appStoreVersions",
                    "id": version_id,
                    "relationships": {
                        "build": {
                            "data": {
                                "type": "builds",
                                "id": build_id
                            }
                        }
                    }
                }
            }
            try:
                client.request("PATCH", f"/appStoreVersions/{version_id}", attach_payload)
                print(f"  ✅ Attached Build {build_num} to Version {version_str}")
            except Exception as e:
                print(f"  ℹ️  Build attach status: {e}")
        else:
            print("  ⚠️  No builds found for this version in App Store Connect yet.")

    # 9. Submit for review if requested
    if args.submit:
        print("\n🚀 Submitting version for review...")
        try:
            sub_payload = {
                "data": {
                    "type": "reviewSubmissions",
                    "attributes": {
                        "platform": "IOS"
                    },
                    "relationships": {
                        "app": {
                            "data": {
                                "type": "apps",
                                "id": app_id
                            }
                        }
                    }
                }
            }
            sub_resp = client.request("POST", "/reviewSubmissions", sub_payload)
            submission_id = sub_resp['data']['id']
            
            item_payload = {
                "data": {
                    "type": "reviewSubmissionItems",
                    "relationships": {
                        "reviewSubmission": {
                            "data": {
                                "type": "reviewSubmissions",
                                "id": submission_id
                            }
                        },
                        "appStoreVersion": {
                            "data": {
                                "type": "appStoreVersions",
                                "id": version_id
                            }
                        }
                    }
                }
            }
            client.request("POST", "/reviewSubmissionItems", item_payload)
            
            submit_payload = {
                "data": {
                    "type": "reviewSubmissions",
                    "id": submission_id,
                    "attributes": {
                        "submitted": True
                    }
                }
            }
            client.request("PATCH", f"/reviewSubmissions/{submission_id}", submit_payload)
            print("  🎉 Successfully submitted for App Store review!")
        except Exception as e:
            print(f"  ⚠️  Review submission note: {e}")
            print("  (You can also click 'Submit for Review' directly in App Store Connect)")
    else:
        print("\n💡 Metadata and build updated in App Store Connect.")
        print("To submit for review directly from this script next time, pass `--submit`.")
        
    print("\n✨ Done!")

if __name__ == '__main__':
    main()
