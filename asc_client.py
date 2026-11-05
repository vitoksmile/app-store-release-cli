#!/usr/bin/env python3
"""
App Store Connect API CLI:
- Auto-build release artifacts (Flutter, Xcode, or custom commands)
- IPA upload to TestFlight via xcrun altool
- Multi-language localized metadata synchronization from CSV
- Build linking to App Store release version
- App Store review submission
- Zero pip dependencies (pure standard Python 3 + system openssl)
"""

import sys
import os
import json
import time
import base64
import subprocess
import urllib.request
import urllib.parse
import urllib.error
import csv
import argparse
import glob
from pathlib import Path

# ==============================================================================
# 1. JWT & Cryptography (Zero Dependencies using system `openssl`)
# ==============================================================================

def base64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode('utf-8').rstrip('=')

def der_to_raw_p1363(der: bytes) -> bytes:
    """Convert ASN.1 DER ECDSA signature to IEEE P1363 raw (r || s) for ES256 JWT."""
    if der[0] != 0x30:
        raise ValueError("Invalid DER sequence")
    idx = 2
    if der[1] & 0x80:
        idx += (der[1] & 0x7F)
    
    # Read r
    if der[idx] != 0x02:
        raise ValueError("Expected integer for r")
    r_len = der[idx + 1]
    idx += 2
    r_bytes = der[idx:idx + r_len]
    idx += r_len
    
    # Read s
    if der[idx] != 0x02:
        raise ValueError("Expected integer for s")
    s_len = der[idx + 1]
    idx += 2
    s_bytes = der[idx:idx + s_len]
    
    # Strip leading zero padding if 33 bytes
    r_bytes = r_bytes[-32:].rjust(32, b'\x00')
    s_bytes = s_bytes[-32:].rjust(32, b'\x00')
    
    return r_bytes + s_bytes

def generate_jwt(key_id: str, issuer_id: str, key_path: str, expiration_seconds: int = 900) -> str:
    """Generate an ES256 JWT token using system OpenSSL."""
    now = int(time.time())
    header = {"alg": "ES256", "kid": key_id, "typ": "JWT"}
    payload = {
        "iss": issuer_id,
        "exp": now + expiration_seconds,
        "aud": "appstoreconnect-v1"
    }
    
    hdr_b64 = base64url_encode(json.dumps(header, separators=(',', ':')).encode('utf-8'))
    pay_b64 = base64url_encode(json.dumps(payload, separators=(',', ':')).encode('utf-8'))
    signing_input = f"{hdr_b64}.{pay_b64}".encode('utf-8')
    
    # Sign using openssl dgst -sha256 -sign <key_path>
    proc = subprocess.Popen(
        ['openssl', 'dgst', '-sha256', '-sign', key_path],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    der_sig, err = proc.communicate(input=signing_input)
    if proc.returncode != 0:
        raise RuntimeError(f"OpenSSL signing failed: {err.decode('utf-8')}")
    
    raw_sig = der_to_raw_p1363(der_sig)
    sig_b64 = base64url_encode(raw_sig)
    return f"{hdr_b64}.{pay_b64}.{sig_b64}"

# ==============================================================================
# 2. Locale Matching & Aliases
# ==============================================================================

LOCALE_MAP = {
    'english': ['en-US', 'en-GB', 'en-AU', 'en-CA'],
    'en': ['en-US', 'en-GB', 'en-AU', 'en-CA'],
    'en-us': ['en-US'],
    'en-gb': ['en-GB'],
    'french': ['fr-FR', 'fr-CA'],
    'fr': ['fr-FR', 'fr-CA'],
    'german': ['de-DE'],
    'de': ['de-DE'],
    'spanish': ['es-ES', 'es-MX'],
    'es': ['es-ES', 'es-MX'],
    'portuguese': ['pt-BR', 'pt-PT'],
    'portuguese (br)': ['pt-BR'],
    'portuguese (pt)': ['pt-PT'],
    'pt': ['pt-BR', 'pt-PT'],
    'pt-br': ['pt-BR'],
    'korean': ['ko'],
    'ko': ['ko'],
    'japanese': ['ja'],
    'ja': ['ja'],
    'ukrainian': ['uk'],
    'uk': ['uk'],
    'italian': ['it'],
    'it': ['it'],
    'dutch': ['nl-NL'],
    'nl': ['nl-NL'],
    'polish': ['pl'],
    'pl': ['pl'],
    'turkish': ['tr'],
    'tr': ['tr'],
    'arabic': ['ar-SA'],
    'ar': ['ar-SA'],
    'chinese (simplified)': ['zh-Hans'],
    'chinese (traditional)': ['zh-Hant'],
    'zh-hans': ['zh-Hans'],
    'zh-hant': ['zh-Hant'],
    'zh': ['zh-Hans', 'zh-Hant'],
    'czech': ['cs'],
    'cs': ['cs'],
    'croatian': ['hr'],
    'hr': ['hr'],
    'hindi': ['hi'],
    'hi': ['hi']
}

# Character Limits
LIMITS = {
    'Name': 30,
    'Subtitle': 30,
    'Promotional Text': 170,
    'Keywords': 100,
    'What\'s New': 4000,
    'Description': 4000
}

def read_metadata_csv(csv_path: str) -> list:
    """Reads metadata CSV and strips BOM/whitespace."""
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"Metadata CSV not found at: {csv_path}")
    
    entries = []
    with open(csv_path, mode='r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            clean_row = {k.strip(): (v.strip() if v else "") for k, v in row.items() if k}
            if clean_row.get('Language'):
                entries.append(clean_row)
    return entries

def validate_entries(entries: list):
    """Enforces App Store Connect character limits."""
    errors = []
    for entry in entries:
        lang = entry.get('Language', 'Unknown')
        for field, max_len in LIMITS.items():
            val = entry.get(field, "")
            if len(val) > max_len:
                errors.append(f"[{lang}] '{field}' exceeds {max_len} chars (length: {len(val)})")
    if errors:
        raise ValueError("Metadata validation failed:\n" + "\n".join(errors))

def match_locale(lang_name: str, available_locales: list) -> str:
    """Matches a language name or locale code to existing or supported ASC locales."""
    cleaned = lang_name.lower().strip()
    
    # Direct match (e.g. en-US, uk, fr-FR)
    for loc in available_locales:
        if loc.lower() == cleaned:
            return loc
            
    # Lookup in LOCALE_MAP
    candidates = LOCALE_MAP.get(cleaned, [cleaned])
    for candidate in candidates:
        for loc in available_locales:
            if loc.lower() == candidate.lower():
                return loc
                
    # Fallback to first candidate
    return candidates[0]

# ==============================================================================
# 3. Build & Upload Helpers
# ==============================================================================

def auto_detect_xcode_build_command(cwd: str) -> str:
    """Auto-detects native Xcode workspace/project, scheme, and generates archive & export commands."""
    workspaces = glob.glob(os.path.join(cwd, '*.xcworkspace'))
    projects = glob.glob(os.path.join(cwd, '*.xcodeproj'))
    
    # Exclude internal project.xcworkspace inside .xcodeproj
    workspaces = [w for w in workspaces if not w.endswith('.xcodeproj/project.xcworkspace')]
    
    container_arg = ""
    container_name = ""
    if workspaces:
        container_name = os.path.basename(workspaces[0])
        container_arg = f'-workspace "{container_name}"'
    elif projects:
        container_name = os.path.basename(projects[0])
        container_arg = f'-project "{container_name}"'
    else:
        return None
        
    # Query available schemes
    schemes = []
    try:
        cmd = f"xcodebuild {container_arg} -list -json"
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=cwd)
        if res.returncode == 0:
            data = json.loads(res.stdout)
            if 'workspace' in data:
                schemes = data['workspace'].get('schemes', [])
            elif 'project' in data:
                schemes = data['project'].get('schemes', [])
    except Exception:
        pass
        
    # Heuristic to choose primary release scheme
    chosen_scheme = os.getenv('XCODE_SCHEME') or os.getenv('APP_SCHEME')
    if not chosen_scheme and schemes:
        # Filter out tests, simulators, third-party libraries, widgets/extensions
        ignored_patterns = ['test', 'simulator', 'extension', 'widget', 'pods', 'framework']
        filtered = [
            s for s in schemes
            if not any(ign in s.lower() for ign in ignored_patterns)
        ]
        
        # Match project base name if possible
        base_name = os.path.splitext(container_name)[0].lower()
        exact_matches = [s for s in (filtered or schemes) if s.lower() == base_name]
        
        if exact_matches:
            chosen_scheme = exact_matches[0]
        elif filtered:
            chosen_scheme = filtered[0]
        else:
            chosen_scheme = schemes[0]
            
    if not chosen_scheme:
        chosen_scheme = os.path.splitext(container_name)[0]

    # Clean, create export options plist, archive, and export ipa
    plist_path = "build/exportOptions.plist"
    archive_path = f"build/{chosen_scheme}.xcarchive"
    export_path = "build/ipa"
    
    cmd = (
        f"mkdir -p build/ipa && "
        f"printf '<?xml version=\"1.0\" encoding=\"UTF-8\"?>\\n"
        f"<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">\\n"
        f"<plist version=\"1.0\">\\n"
        f"<dict>\\n"
        f"    <key>method</key>\\n"
        f"    <string>app-store</string>\\n"
        f"    <key>signingStyle</key>\\n"
        f"    <string>automatic</string>\\n"
        f"    <key>uploadBitcode</key>\\n"
        f"    <false/>\\n"
        f"    <key>compileBitcode</key>\\n"
        f"    <false/>\\n"
        f"</dict>\\n"
        f"</plist>\\n' > {plist_path} && "
        f"xcodebuild archive {container_arg} -scheme \"{chosen_scheme}\" "
        f"-destination \"generic/platform=iOS\" -archivePath \"{archive_path}\" && "
        f"xcodebuild -exportArchive -archivePath \"{archive_path}\" "
        f"-exportOptionsPlist {plist_path} -exportPath {export_path} -allowProvisioningUpdates"
    )
    return cmd

def auto_detect_build_command(cwd: str) -> str:
    """Determines the appropriate release build command based on project files."""
    # Check for Flutter
    if os.path.exists(os.path.join(cwd, 'pubspec.yaml')):
        return "flutter build ipa --release"
        
    # Check for Native Xcode project or workspace
    xcode_cmd = auto_detect_xcode_build_command(cwd)
    if xcode_cmd:
        return xcode_cmd
    
    # Check for custom env command
    env_cmd = os.getenv('APP_BUILD_CMD')
    if env_cmd:
        return env_cmd
        
    return None

def auto_detect_ipa(search_dirs: list) -> str:
    """Finds the most recently modified .ipa file in candidate directories."""
    candidates = []
    for d in search_dirs:
        if os.path.exists(d):
            candidates.extend(Path(d).glob("**/*.ipa"))
    if not candidates:
        return None
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return str(candidates[0])

def run_build(build_cmd: str, dry_run: bool = False):
    """Runs the release build command."""
    print(f"\n🔨 Building Release Artifact...")
    print(f"  Command: {build_cmd}")
    if dry_run:
        print("  ℹ️ [Dry-Run] Skipping actual build execution.")
        return True
        
    res = subprocess.run(build_cmd, shell=True)
    if res.returncode != 0:
        raise RuntimeError(f"Build command failed with exit code {res.returncode}")
    print("  ✅ Build completed successfully!")
    return True

# ==============================================================================
# 4. App Store Connect API Client
# ==============================================================================

class AppStoreConnectAPI:
    BASE_URL = "https://api.appstoreconnect.apple.com/v1"
    
    def __init__(self, key_id: str, issuer_id: str, key_path: str):
        self.key_id = key_id
        self.issuer_id = issuer_id
        self.key_path = key_path
        self._token = None
        self._token_expires_at = 0
        
    def get_token(self) -> str:
        now = int(time.time())
        if not self._token or now >= self._token_expires_at - 60:
            self._token = generate_jwt(self.key_id, self.issuer_id, self.key_path)
            self._token_expires_at = now + 900
        return self._token

    def request(self, method: str, path: str, body: dict = None) -> dict:
        url = f"{self.BASE_URL}{path}"
        headers = {
            "Authorization": f"Bearer {self.get_token()}",
            "Content-Type": "application/json"
        }
        data = json.dumps(body).encode('utf-8') if body else None
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req) as resp:
                if resp.status == 204:
                    return {}
                return json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            err_msg = e.read().decode('utf-8')
            try:
                err_json = json.loads(err_msg)
                details = [err.get('detail', err.get('title', 'Unknown error')) for err in err_json.get('errors', [])]
                full_msg = f"HTTP {e.code}: " + "; ".join(details)
            except Exception:
                full_msg = f"HTTP {e.code}: {err_msg}"
            raise RuntimeError(full_msg)

    def upload_ipa(self, ipa_path: str) -> bool:
        """Uploads IPA to App Store Connect / TestFlight using xcrun altool."""
        print(f"\n📦 Uploading IPA to TestFlight via xcrun altool: {ipa_path}")
        if not os.path.exists(ipa_path):
            raise FileNotFoundError(f"IPA file not found: {ipa_path}")
            
        cmd = [
            "xcrun", "altool", "--upload-package", ipa_path,
            "--type", "ios",
            "--api-key", self.key_id,
            "--api-issuer", self.issuer_id
        ]
        
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in proc.stdout:
            print(f"  {line.rstrip()}")
        proc.wait()
        
        if proc.returncode != 0:
            raise RuntimeError(f"altool upload failed with exit code {proc.returncode}")
        print("  ✅ Upload succeeded!")
        return True

# ==============================================================================
# 5. CLI Execution Flow
# ==============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Generic App Store Connect Release, Metadata Sync & Review Submission CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Validate CSV and test connection (dry run):
  asc-release --dry-run

  # Build release IPA and upload to TestFlight:
  asc-release --build --upload

  # Build, upload, sync metadata, and submit for review:
  asc-release --build --upload --submit

  # Upload build (.ipa) and sync metadata:
  asc-release --upload build/ios/ipa/myapp.ipa

  # Auto-detect latest .ipa and upload:
  asc-release --upload

  # Sync metadata & link latest TestFlight build:
  asc-release

  # Create a brand new App Store version if no editable version exists:
  asc-release --create-version 1.4.1 --submit
        """
    )
    parser.add_argument('--bundle-id', default=os.getenv('APP_BUNDLE_ID'), help="Bundle identifier (e.g. com.example.app). Required.")
    parser.add_argument('--csv', default=os.getenv('APP_METADATA_CSV', 'app_store_metadata.csv'), help="Path to metadata CSV file (default: app_store_metadata.csv)")
    parser.add_argument('--version', default=None, help="App Store version to target (e.g. 1.4.0). Defaults to active editable version.")
    parser.add_argument('--create-version', default=None, help="Create a new App Store version if needed (e.g. 1.4.1)")
    parser.add_argument('--build', nargs='?', const='__AUTO__', default=None, help="Build release IPA (auto-detects Flutter or runs provided command)")
    parser.add_argument('--upload', nargs='?', const='__AUTO__', default=None, help="Upload IPA to TestFlight (pass file path or leave empty to auto-detect)")
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
        
    # 2. Check and read metadata CSV
    if not os.path.exists(args.csv):
        print(f"\n❌ Error: Metadata CSV file not found: {args.csv}")
        print("Specify the CSV via --csv <path> or APP_METADATA_CSV in .env.")
        sys.exit(1)
        
    entries = read_metadata_csv(args.csv)
    print(f"📖 Loaded {len(entries)} language entries from: {args.csv}")
    
    # 3. Validate character limits
    print("🔍 Validating metadata character limits...")
    try:
        validate_entries(entries)
        print("  ✅ All metadata fields within App Store Connect limits.")
    except ValueError as e:
        print(f"\n❌ Validation Error:\n{e}")
        sys.exit(1)
        
    # 4. Check API credentials
    if not args.key_id or not args.issuer_id or not args.key_file:
        print("\n❌ Error: Missing App Store Connect API credentials!")
        print("Please set ASC_KEY_ID, ASC_ISSUER_ID, and ASC_KEY_FILE in .env or pass flags.")
        sys.exit(1)
        
    expanded_key_path = os.path.expanduser(args.key_file)
    if not os.path.exists(expanded_key_path):
        print(f"\n❌ Error: Private key file not found: {expanded_key_path}")
        sys.exit(1)
        
    api = AppStoreConnectAPI(args.key_id, args.issuer_id, expanded_key_path)

    # 4a. Handle Build if requested
    if args.build:
        build_cmd = args.build
        if build_cmd == '__AUTO__':
            build_cmd = auto_detect_build_command(os.getcwd())
            if not build_cmd:
                print("\n❌ Error: Could not auto-detect build command (e.g. no pubspec.yaml found).")
                print("Please provide build command explicitly: --build 'flutter build ipa --release'")
                sys.exit(1)
            print(f"🔍 Auto-detected build command: {build_cmd}")
            
        run_build(build_cmd, dry_run=args.dry_run)

    # 4b. Handle IPA Upload if requested
    if args.upload:
        ipa_path = args.upload
        if ipa_path == '__AUTO__':
            search_paths = [
                os.getcwd(),
                os.path.join(os.getcwd(), 'build'),
                os.path.join(os.getcwd(), 'build/ipa'),
                os.path.join(os.getcwd(), 'build/ios/ipa'),
                os.path.join(os.getcwd(), 'ios/build')
            ]
            ipa_path = auto_detect_ipa(search_paths)
            if not ipa_path:
                if args.dry_run:
                    ipa_path = "build/ios/ipa/*.ipa (auto-detected placeholder)"
                else:
                    print("\n❌ Error: No .ipa file found automatically in build directories!")
                    print("Please specify path explicitly: --upload path/to/app.ipa")
                    sys.exit(1)
            if not args.dry_run or not ipa_path.endswith("(auto-detected placeholder)"):
                print(f"🔍 Auto-detected latest IPA: {ipa_path}")
        
        if args.dry_run:
            print(f"ℹ️ [Dry-Run] Would upload IPA to TestFlight: {ipa_path}")
        else:
            api.upload_ipa(ipa_path)

    # 5. Find App by Bundle ID
    print(f"\n📱 Finding app with Bundle ID: {args.bundle_id}...")
    apps_data = api.request("GET", f"/apps?filter[bundleId]={args.bundle_id}")
    apps = apps_data.get("data", [])
    if not apps:
        print(f"❌ Error: App with bundle ID '{args.bundle_id}' not found.")
        sys.exit(1)
    app = apps[0]
    app_id = app["id"]
    app_name = app["attributes"]["name"]
    print(f"  ✅ Found App: '{app_name}' (ID: {app_id})")
    
    # 6. Resolve App Store Version
    print("\n🔍 Finding App Store version...")
    versions_data = api.request("GET", f"/apps/{app_id}/appStoreVersions")
    versions = versions_data.get("data", [])
    
    target_version = None
    if args.create_version:
        print(f"  Creating new App Store Version '{args.create_version}'...")
        if args.dry_run:
            print(f"  ℹ️ [Dry-Run] Would create new version: {args.create_version}")
            target_version = {
                "id": "dry-run-version-id",
                "attributes": {
                    "versionString": args.create_version,
                    "appStoreState": "PREPARE_FOR_SUBMISSION"
                }
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
                        "app": {"data": {"type": "apps", "id": app_id}}
                    }
                }
            }
            res = api.request("POST", "/appStoreVersions", create_payload)
            target_version = res["data"]
            print(f"  ✅ Created Version: {args.create_version} (ID: {target_version['id']})")
    elif args.version:
        for v in versions:
            if v["attributes"]["versionString"] == args.version:
                target_version = v
                break
        if not target_version:
            print(f"❌ Error: Version '{args.version}' not found for this app.")
            sys.exit(1)
    else:
        editable_states = ['PREPARE_FOR_SUBMISSION', 'DEVELOPER_REJECTED', 'REJECTED', 'METADATA_REJECTED']
        for v in versions:
            if v["attributes"]["appStoreState"] in editable_states:
                target_version = v
                break
                
    if not target_version:
        found_versions_summary = ", ".join([f"{v['attributes']['versionString']} ({v['attributes']['appStoreState']})" for v in versions])
        print(f"❌ Target version not found or not in editable state. Found: {found_versions_summary}")
        print("💡 Tip: To target an existing version, pass --version <ver> (e.g. --version 1.4.0)")
        print("💡 Tip: To create a new version, pass --create-version <ver> (e.g. --create-version 1.4.1)")
        sys.exit(1)
        
    version_id = target_version["id"]
    version_str = target_version["attributes"]["versionString"]
    version_state = target_version["attributes"]["appStoreState"]
    print(f"  ✅ Target Version: {version_str} (State: {version_state}, ID: {version_id})")

    # 7. Get Version Localizations
    print("\n🌐 Fetching existing localizations for version...")
    if version_id == "dry-run-version-id":
        existing_version_locs = {}
        available_locales = ['en-US', 'fr-FR', 'de-DE', 'es-ES', 'pt-BR', 'ko', 'ja', 'uk']
    else:
        ver_locs_data = api.request("GET", f"/appStoreVersions/{version_id}/appStoreVersionLocalizations")
        existing_version_locs = {loc["attributes"]["locale"]: loc for loc in ver_locs_data.get("data", [])}
        available_locales = list(existing_version_locs.keys())
    print(f"  Found existing locales: {', '.join(available_locales) if available_locales else 'None'}")
    
    # 8. Get App Info Localizations (Name, Subtitle)
    app_infos_data = api.request("GET", f"/apps/{app_id}/appInfos")
    app_infos = app_infos_data.get("data", [])
    
    # Pick the editable AppInfo (PREPARE_FOR_SUBMISSION, etc.), fallback to first
    app_info_id = None
    editable_states = ['PREPARE_FOR_SUBMISSION', 'DEVELOPER_REJECTED', 'REJECTED', 'METADATA_REJECTED']
    for info in app_infos:
        if info.get("attributes", {}).get("appStoreState") in editable_states:
            app_info_id = info["id"]
            break
    if not app_info_id and app_infos:
        app_info_id = app_infos[0]["id"]
    
    existing_info_locs = {}
    if app_info_id:
        info_locs_data = api.request("GET", f"/appInfos/{app_info_id}/appInfoLocalizations")
        existing_info_locs = {loc["attributes"]["locale"]: loc for loc in info_locs_data.get("data", [])}

    # 9. Sync or Dry Run Metadata
    if args.dry_run:
        print("\n🔍 DRY-RUN MODE: Showing matching plan without updating:")
        for entry in entries:
            lang = entry['Language']
            matched = match_locale(lang, available_locales)
            exists = matched in existing_version_locs or version_id == "dry-run-version-id"
            print(f"  • {lang} -> locale: {matched} (exists: {exists})")
            if entry.get('Name'):
                print(f"    - Name: {entry['Name']}")
            if entry.get('Subtitle'):
                print(f"    - Subtitle: {entry['Subtitle']}")
            if entry.get('Promotional Text'):
                print(f"    - Promotional Text: {entry['Promotional Text'][:50]}... ({len(entry['Promotional Text'])} chars)")
            if entry.get("What's New"):
                wn_text = entry.get("What's New", '')
                print(f"    - What's New: {wn_text} ({len(wn_text)} chars)")
            if entry.get('Keywords'):
                print(f"    - Keywords: {entry['Keywords'][:50]}... ({len(entry['Keywords'])} chars)")
        print("\n✅ Dry run complete. Everything looks good!")
        return

    # Real sync execution
    print("\n📝 Updating App Store Version Localizations...")
    for entry in entries:
        lang = entry['Language']
        matched = match_locale(lang, available_locales)
        print(f"  Updating [{lang}] -> locale '{matched}'...")
        
        # Build version localization attributes
        ver_attrs = {}
        if entry.get('Promotional Text'):
            ver_attrs['promotionalText'] = entry['Promotional Text']
        if entry.get("What's New"):
            ver_attrs['whatsNew'] = entry.get("What's New")
        if entry.get('Description'):
            ver_attrs['description'] = entry['Description']
        if entry.get('Keywords'):
            ver_attrs['keywords'] = entry['Keywords']
            
        if matched in existing_version_locs:
            loc_id = existing_version_locs[matched]["id"]
            if ver_attrs:
                api.request("PATCH", f"/appStoreVersionLocalizations/{loc_id}", {
                    "data": {
                        "type": "appStoreVersionLocalizations",
                        "id": loc_id,
                        "attributes": ver_attrs
                    }
                })
                print(f"    ✅ Updated version localization ({matched})")
        else:
            if ver_attrs:
                ver_attrs['locale'] = matched
                api.request("POST", "/appStoreVersionLocalizations", {
                    "data": {
                        "type": "appStoreVersionLocalizations",
                        "attributes": ver_attrs,
                        "relationships": {
                            "appStoreVersion": {"data": {"type": "appStoreVersions", "id": version_id}}
                        }
                    }
                })
                print(f"    ✅ Created new version localization ({matched})")
                
        # App Info Localizations (Name, Subtitle)
        info_attrs = {}
        if entry.get('Name'):
            info_attrs['name'] = entry['Name']
        if entry.get('Subtitle'):
            info_attrs['subtitle'] = entry['Subtitle']
            
        if info_attrs and app_info_id:
            if matched in existing_info_locs:
                current_loc = existing_info_locs[matched]
                info_loc_id = current_loc["id"]
                cur_attrs = current_loc.get("attributes", {})
                
                # Filter out attributes that haven't changed to avoid unnecessary PATCH
                diff_attrs = {k: v for k, v in info_attrs.items() if cur_attrs.get(k) != v}
                if diff_attrs:
                    try:
                        api.request("PATCH", f"/appInfoLocalizations/{info_loc_id}", {
                            "data": {
                                "type": "appInfoLocalizations",
                                "id": info_loc_id,
                                "attributes": diff_attrs
                            }
                        })
                        print(f"    ✅ Updated App Name/Subtitle ({matched})")
                    except Exception as e:
                        print(f"    ⚠️ Could not update Name/Subtitle for {matched}: {e}")
                else:
                    print(f"    ℹ️ App Name/Subtitle already up-to-date ({matched})")
            else:
                info_attrs['locale'] = matched
                try:
                    api.request("POST", "/appInfoLocalizations", {
                        "data": {
                            "type": "appInfoLocalizations",
                            "attributes": info_attrs,
                            "relationships": {
                                "appInfo": {"data": {"type": "appInfos", "id": app_info_id}}
                            }
                        }
                    })
                    print(f"    ✅ Created App Name/Subtitle ({matched})")
                except Exception as e:
                    print(f"    ⚠️ Could not set Name/Subtitle for {matched}: {e}")

    # 10. Link Latest Build (if not skipped)
    if not args.no_attach_build:
        print("\n📦 Finding latest uploaded build...")
        builds_data = api.request("GET", f"/builds?filter[app]={app_id}&sort=-uploadedDate&limit=1")
        builds = builds_data.get("data", [])
        if builds:
            latest_build = builds[0]
            build_id = latest_build["id"]
            build_ver = latest_build["attributes"].get("version")
            print(f"  Attaching build {build_ver} (ID: {build_id}) to version {version_str}...")
            api.request("PATCH", f"/appStoreVersions/{version_id}/relationships/build", {
                "data": {"type": "builds", "id": build_id}
            })
            print(f"  ✅ Successfully linked build {build_ver} to release version {version_str}!")
        else:
            print("  ⚠️ No builds found for this app yet.")
            
    # 11. Submit for Review
    if args.submit:
        print("\n🚀 Submitting App Store Version for review...")
        submission_payload = {
            "data": {
                "type": "appStoreVersionSubmissions",
                "relationships": {
                    "appStoreVersion": {"data": {"type": "appStoreVersions", "id": version_id}}
                }
            }
        }
        api.request("POST", "/appStoreVersionSubmissions", submission_payload)
        print("  🎉 App version successfully submitted for App Store review!")

    print("\n🏁 Done! All operations completed successfully.")

if __name__ == "__main__":
    main()
