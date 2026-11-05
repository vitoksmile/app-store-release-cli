#!/usr/bin/env bash
# ==============================================================================
# app-store-release-cli: CLI entrypoint
# ==============================================================================
set -eo pipefail

# Resolve symlinks so SCRIPT_DIR points to the actual repository folder
SOURCE="${BASH_SOURCE[0]}"
while [ -h "$SOURCE" ]; do
    DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
    SOURCE="$(readlink "$SOURCE")"
    [[ $SOURCE != /* ]] && SOURCE="$DIR/$SOURCE"
done
SCRIPT_DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
CALLER_DIR="$(pwd)"

# 1. Search for .env / env configuration file:
ENV_FILE=""
for CANDIDATE in \
    "$CALLER_DIR/.env" \
    "$CALLER_DIR/env" \
    "$CALLER_DIR/scripts/release/.env" \
    "$CALLER_DIR/scripts/release/env" \
    "$SCRIPT_DIR/.env" \
    "$SCRIPT_DIR/env"; do
    if [ -f "$CANDIDATE" ]; then
        ENV_FILE="$CANDIDATE"
        break
    fi
done

if [ -n "$ENV_FILE" ]; then
    echo "🔑 Loading environment from $ENV_FILE"
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
fi

# 2. Check for required system utilities
if ! command -v openssl &> /dev/null; then
    echo "❌ Error: 'openssl' command is required for ES256 JWT signing."
    exit 1
fi

if ! command -v python3 &> /dev/null; then
    echo "❌ Error: 'python3' is required to run the release client."
    exit 1
fi

# 3. Resolve CSV path (default: search in caller dir, then scripts/release, then script dir)
CSV_FILE="${APP_METADATA_CSV:-}"
if [ -z "$CSV_FILE" ]; then
    for CANDIDATE in \
        "$CALLER_DIR/app_store_metadata.csv" \
        "$CALLER_DIR/scripts/release/app_store_metadata.csv" \
        "$CALLER_DIR/metadata.csv" \
        "$SCRIPT_DIR/app_store_metadata.csv"; do
        if [ -f "$CANDIDATE" ]; then
            CSV_FILE="$CANDIDATE"
            break
        fi
    done
fi

# 4. Resolve ASC_KEY_FILE path
if [ -n "${ASC_KEY_FILE:-}" ] && [ ! -f "$ASC_KEY_FILE" ]; then
    for CANDIDATE in \
        "$CALLER_DIR/$ASC_KEY_FILE" \
        "$CALLER_DIR/scripts/release/$ASC_KEY_FILE" \
        "$SCRIPT_DIR/$ASC_KEY_FILE" \
        "$HOME/.appstoreconnect/private_keys/$ASC_KEY_FILE"; do
        if [ -f "$CANDIDATE" ]; then
            export ASC_KEY_FILE="$CANDIDATE"
            break
        fi
    done
fi

# Auto-detect AuthKey_*.p8 if not explicitly provided
if [ -z "${ASC_KEY_FILE:-}" ]; then
    FOUND_KEY=$(find "$CALLER_DIR" "$CALLER_DIR/scripts/release" "$SCRIPT_DIR" "$HOME/.appstoreconnect/private_keys" -maxdepth 2 -name "AuthKey_*.p8" 2>/dev/null | head -n 1 || true)
    if [ -n "$FOUND_KEY" ]; then
        export ASC_KEY_FILE="$FOUND_KEY"
        if [ -z "${ASC_KEY_ID:-}" ]; then
            FILENAME=$(basename "$FOUND_KEY")
            EXTRACTED_ID=$(echo "$FILENAME" | sed -E 's/AuthKey_([A-Za-z0-9]+)\.p8/\1/')
            if [ -n "$EXTRACTED_ID" ] && [ "$EXTRACTED_ID" != "$FILENAME" ]; then
                export ASC_KEY_ID="$EXTRACTED_ID"
            fi
        fi
    fi
fi

# 5. Build arguments
PYTHON_ARGS=()
if [ -n "$CSV_FILE" ]; then
    PYTHON_ARGS+=("--csv" "$CSV_FILE")
fi
if [ -n "${APP_BUNDLE_ID:-}" ]; then
    PYTHON_ARGS+=("--bundle-id" "$APP_BUNDLE_ID")
fi

# 6. Run Python release client
if [ ${#PYTHON_ARGS[@]} -gt 0 ]; then
    exec python3 "$SCRIPT_DIR/asc_client.py" "${PYTHON_ARGS[@]}" "$@"
else
    exec python3 "$SCRIPT_DIR/asc_client.py" "$@"
fi
