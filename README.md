# App Store Release CLI (`app-store-release-cli`)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-iOS%20%7C%20iPadOS%20%7C%20macOS-blue.svg)]()
[![Zero Dependencies](https://img.shields.io/badge/Dependencies-Zero%20pip%20deps-brightgreen.svg)]()
[![Release](https://img.shields.io/github/v/release/vitoksmile/app-store-release-cli?color=brightgreen)](https://github.com/vitoksmile/app-store-release-cli/releases/latest)

A lightweight, framework-agnostic command-line tool to automate **App Store Connect release management**:
- 🔨 Automatically build release binaries (`--build`) with auto-detection for Flutter or custom commands.
- 📦 Upload IPA to TestFlight (`--upload`) using native Apple `xcrun altool` (zero extra tools needed).
- 🌐 Synchronize localized store metadata from a single CSV across any number of languages.
- 🔗 Automatically link the latest uploaded **TestFlight** build to your App Store version.
- 🚀 Submit the release for **App Store Review** (`--submit`).
- 🛠️ Works with **Flutter**, **React Native**, **Native iOS (Swift / SwiftUI)**, or any cross-platform technology.
- 🔒 **Zero pip/gem dependencies**: Uses standard Python 3 and macOS/Linux system `openssl` for ES256 JWT signing.

---

## ⚡ Quick Start

### 1-Line Global Installation

Install directly on macOS / Linux into `/usr/local/bin/asc-release`:

```bash
curl -fsSL https://raw.githubusercontent.com/vitoksmile/app-store-release-cli/main/install.sh | bash
```

*Or install manually via Git:*
```bash
git clone https://github.com/vitoksmile/app-store-release-cli.git ~/tools/app-store-release-cli
sudo ln -sf ~/tools/app-store-release-cli/release.sh /usr/local/bin/asc-release
```

---

### App Store Connect API Credentials (One-time Setup)

Create an App Store Connect API Key in [App Store Connect](https://appstoreconnect.apple.com/):
1. Go to **Users and Access** → **Integrations** → **App Store Connect API**.
2. Note your **Issuer ID** (UUID at the top).
3. Create a Key with **App Manager** or **Admin** role, note the **Key ID**, and download the `AuthKey_XXXXXXXXXX.p8` private key file.

Configure your credentials by copying the template:
```bash
cp env.example .env
```
Edit `.env`:
```ini
ASC_KEY_ID="XXXXXXXXXX"
ASC_ISSUER_ID="57246542-96fe-1a63-e053-0824d011072a"
ASC_KEY_FILE="AuthKey_XXXXXXXXXX.p8"
```
> **Tip:** You can place your `.p8` key in `~/.appstoreconnect/private_keys/` — the CLI will automatically discover it across all projects!

---

### Metadata CSV (`app_store_metadata.csv`)

Each app defines its own supported languages in a CSV file. See [`app_store_metadata.csv.example`](app_store_metadata.csv.example) for a template.

#### Supported Columns:
- `Language`: Language name or locale code (e.g. `English`, `en-US`, `French`, `fr-FR`, `German`, `Spanish`, `Ukrainian`, `Japanese`, `Korean`, `pt-BR`, `zh-Hans`, etc.).
- `Name`: App name (max 30 characters).
- `Subtitle`: Subtitle (max 30 characters).
- `Promotional Text`: Promo copy (max 170 characters, editable anytime without review).
- `What's New`: Release notes (max 4,000 characters).
- `Description`: Full store description (max 4,000 characters).
- `Keywords`: Search keywords separated by commas (max 100 characters, no spaces after commas).

The CLI automatically matches language names to whatever locales are enabled on your App Store app record (e.g. `English` automatically maps to `en-GB`, `en-US`, or `en` depending on which primary locale your app uses).

---

## 📲 Integrating Into Existing Projects

### Option 1: Global CLI (Recommended)

Once installed via `curl ... | bash`:
1. Put `app_store_metadata.csv` and `.env` in your project folder.
2. Put your `AuthKey_*.p8` in `~/.appstoreconnect/private_keys/`.
3. Run from anywhere:
   ```bash
   asc-release --bundle-id com.example.myapp --dry-run
   ```

---

### Option 2: Flutter Projects

#### Step 1: Add as a Git Submodule
In your Flutter project root:
```bash
git submodule add https://github.com/vitoksmile/app-store-release-cli.git scripts/release
```

#### Step 2: Create App Metadata CSV
Copy the example template to your Flutter `ios/` folder:
```bash
cp scripts/release/app_store_metadata.csv.example ios/app_store_metadata.csv
```
Fill in your localized titles, descriptions, and keywords for each language your app supports.

#### Step 3: Configure Environment
Create `scripts/release/.env` (or root `.env`):
```ini
ASC_KEY_ID="XXXXXXXXXX"
ASC_ISSUER_ID="XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX"
ASC_KEY_FILE="AuthKey_XXXXXXXXXX.p8"
APP_BUNDLE_ID="com.yourcompany.flutterapp"
APP_METADATA_CSV="ios/app_store_metadata.csv"
```
*(Make sure `scripts/release/.env` and `*.p8` are in your `.gitignore`)*

#### Step 4: Run from Flutter
```bash
# 1. Build iOS app archive
flutter build ipa --release
# Upload to App Store Connect via Xcode Organizer or xcrun altool

# 2. Dry-run metadata verification
./scripts/release/release.sh --dry-run

# 3. Attach uploaded TestFlight build & sync metadata:
./scripts/release/release.sh

# 4. Submit for review:
./scripts/release/release.sh --submit
```

---

### Option 3: Native iOS Projects (Xcode / SwiftUI / UIKit)

1. In Xcode: **Product → Archive** → **Distribute App** → **App Store Connect**.
2. Test build in **TestFlight**.
3. Once validated, sync metadata and submit for review:
   ```bash
   asc-release --submit
   ```

---

### Option 4: CI/CD Pipelines (GitHub Actions, Bitrise, Xcode Cloud)

Export credentials as environment secrets and run directly in your workflow:

```yaml
# Example GitHub Actions step
- name: Sync Store Metadata & Submit
  env:
    ASC_KEY_ID: ${{ secrets.ASC_KEY_ID }}
    ASC_ISSUER_ID: ${{ secrets.ASC_ISSUER_ID }}
    ASC_KEY_FILE: ${{ steps.save_p8.outputs.path }}
    APP_BUNDLE_ID: "com.yourcompany.app"
  run: |
    ./scripts/release/release.sh --csv ios/app_store_metadata.csv --submit
```

---

## 🛠️ CLI Options Reference

| Flag | Description | Default |
| :--- | :--- | :--- |
| `--bundle-id <id>` | Target bundle identifier (required) | `APP_BUNDLE_ID` in `.env` |
| `--csv <path>` | Path to localized metadata CSV | `app_store_metadata.csv` |
| `--dry-run` | Validates limits and tests connection without mutating | `false` |
| `--submit` | Submits the version for App Store review | `false` |
| `--version <ver>` | Explicitly target a version (e.g. `1.0.0`) | Active editable version |
| `--create-version <ver>` | Creates new App Store version if needed | `None` |
| `--build [cmd]` | Build release IPA (auto-detects Flutter or runs custom command) | `None` |
| `--upload [ipa]` | Upload IPA to TestFlight via `xcrun altool` (auto-detects .ipa if omitted) | `None` |
| `--no-attach-build` | Skip linking the latest TestFlight build | `false` |
| `--key-id <id>` | App Store Connect API Key ID | `ASC_KEY_ID` in `.env` |
| `--issuer-id <uuid>` | App Store Connect Issuer UUID | `ASC_ISSUER_ID` in `.env` |
| `--key-file <path>` | Path to `.p8` private key file | `ASC_KEY_FILE` in `.env` |

---

## 📄 License
MIT © [Victor Mykhailiv](LICENSE)
