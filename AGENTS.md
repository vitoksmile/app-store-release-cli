# Instructions for AI Agents (AGENTS.md)

Welcome! This repository contains **`app-store-release-cli`**, a lightweight, framework-agnostic command-line tool designed to automate App Store Connect release management and localized metadata synchronization.

---

## 🎯 Role & Capabilities

AI agents working in projects that integrate `app-store-release-cli` can use this tool to:
1. **Validate store copy** for character limit compliance across multiple languages.
2. **Synchronize localized metadata** (Name, Subtitle, Promotional Text, What's New, Description, Keywords) with App Store Connect without navigating the web portal.
3. **Attach TestFlight builds** automatically to store versions.
4. **Trigger review submission** on behalf of the developer once QA passes.

---

## 📲 Integrating `app-store-release-cli` Into an Existing App (For Agents)

When an agent is asked to integrate App Store release automation into an existing project (e.g. Flutter, React Native, or Native iOS), perform these concrete steps:

### Step 1: Add Script to Project
Depending on project setup:
- **Submodule**:
  ```bash
  git submodule add https://github.com/vitoksmile/app-store-release-cli.git scripts/release
  ```
- **Or Standalone Copy**: Place `release.sh`, `asc_client.py`, and `app_store_metadata.csv.example` into `scripts/release/`.

### Step 2: Establish Metadata File
1. Create `app_store_metadata.csv` (in `scripts/release/` or `ios/`).
2. Collect or translate rows for each language the app supports.
3. Validate lengths using `--dry-run`.

### Step 3: Configure Environment
1. Check if `~/.appstoreconnect/private_keys/` already has `AuthKey_*.p8`.
2. Create `scripts/release/.env` with `ASC_KEY_ID`, `ASC_ISSUER_ID`, `ASC_KEY_FILE`, `APP_BUNDLE_ID`, and `APP_METADATA_CSV`.
3. **Ensure `.gitignore` contains:**
   ```gitignore
   .env
   env
   *.p8
   ```

---

## 📐 Strict App Store Connect Character Limits

When generating, translating, or editing metadata in the CSV file, **always** enforce these limits:

| Field | Max Length (Characters) | Critical Rules for Agents |
| :--- | :---: | :--- |
| **Name** | **30** | Brand/App title. Must not exceed 30 UTF-8 characters. |
| **Subtitle** | **30** | Brief value proposition. Strict 30-char limit. |
| **Promotional Text** | **170** | Highlighting sales or events. Editable anytime without review. |
| **Keywords** | **100** | Strict 100-char limit. **Omit spaces after commas** (e.g. `foo,bar,baz`) to maximize keyword count. |
| **What's New** | **4,000** | Version release notes. |
| **Description** | **4,000** | Comprehensive store description and feature list. |

> [!WARNING]
> App Store Connect API will reject any update if any single field exceeds these exact character counts.

---

## 🚀 Standard Agent Execution Workflow

When tasked with preparing or executing a release, follow these steps:

### 1. Dry-Run Verification (Safe Mode)
**Always run a dry-run first** to ensure the CSV is valid and the API credentials work:
```bash
./release.sh --bundle-id <BUNDLE_ID> --csv <CSV_PATH> --dry-run
```
If targeting an existing release version:
```bash
./release.sh --bundle-id <BUNDLE_ID> --csv <CSV_PATH> --version <VERSION> --dry-run
```
If preparing a new store version (e.g., `1.2.0`):
```bash
./release.sh --bundle-id <BUNDLE_ID> --csv <CSV_PATH> --create-version <VERSION> --dry-run
```

### 2. Live Synchronization (Link Build & Sync Metadata)
Once dry-run confirms zero limit violations:
```bash
./release.sh --bundle-id <BUNDLE_ID> --csv <CSV_PATH>
```
*(If `--create-version` is needed: `./release.sh --bundle-id <BUNDLE_ID> --csv <CSV_PATH> --create-version <VERSION>`)*

### 3. Submission for Review (Only when user explicitly asks)
```bash
./release.sh --bundle-id <BUNDLE_ID> --csv <CSV_PATH> --submit
```

---

## 🔑 Credential Discovery Rules

The tool resolves credentials automatically using the following hierarchy:
1. Arguments passed directly (`--key-id`, `--issuer-id`, `--key-file`).
2. `.env` or `env` in the current working directory.
3. `.env` or `env` alongside `release.sh`.
4. Private key files (`AuthKey_*.p8`) placed in:
   - Current directory
   - Alongside `release.sh`
   - `~/.appstoreconnect/private_keys/` (Standard Apple path)

> [!CAUTION]
> Never commit `.env`, `env`, or `*.p8` files to Git. Verify they are ignored in `.gitignore`.

---

## 🌐 Supported Language & Locale Mapping

The CSV column can be specified as `Language` or `Locale`. The tool automatically matches human names (`English`, `French`, `German`, `Japanese`, `Ukrainian`) or standard codes (`en-US`, `es-ES`, `pt-BR`, `zh-Hans`) to the locales configured in the app's App Store Connect record.
