#!/usr/bin/env bash
# ==============================================================================
# Installer for app-store-release-cli (asc-release)
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/vitoksmile/app-store-release-cli/main/install.sh | bash
# ==============================================================================
set -eo pipefail

INSTALL_DIR="$HOME/.asc-release"
BIN_DIR="/usr/local/bin"
ALT_BIN_DIR="$HOME/.local/bin"
TAG="v1.0.0"
BASE_URL="https://raw.githubusercontent.com/vitoksmile/app-store-release-cli/${TAG}"

echo "🚀 Installing app-store-release-cli (${TAG})..."

# 1. Create installation directory
mkdir -p "$INSTALL_DIR"

# 2. Download scripts
echo "⬇️  Downloading release scripts..."
curl -fsSL "${BASE_URL}/release.sh" -o "${INSTALL_DIR}/release.sh"
curl -fsSL "${BASE_URL}/asc_client.py" -o "${INSTALL_DIR}/asc_client.py"
chmod +x "${INSTALL_DIR}/release.sh" "${INSTALL_DIR}/asc_client.py"

# 3. Create symlink in PATH
TARGET_BIN=""
if [ -w "$BIN_DIR" ]; then
    TARGET_BIN="$BIN_DIR/asc-release"
    ln -sf "${INSTALL_DIR}/release.sh" "$TARGET_BIN"
elif command -v sudo &> /dev/null && sudo -n true 2>/dev/null; then
    TARGET_BIN="$BIN_DIR/asc-release"
    sudo ln -sf "${INSTALL_DIR}/release.sh" "$TARGET_BIN"
else
    mkdir -p "$ALT_BIN_DIR"
    TARGET_BIN="$ALT_BIN_DIR/asc-release"
    ln -sf "${INSTALL_DIR}/release.sh" "$TARGET_BIN"
fi

echo "✅ Installed successfully to: ${INSTALL_DIR}"
echo "🔗 Symlinked CLI executable: ${TARGET_BIN}"

# Check if TARGET_BIN directory is in PATH
if [[ ":$PATH:" != *":$(dirname "$TARGET_BIN"):"* ]]; then
    echo ""
    echo "⚠️  Note: $(dirname "$TARGET_BIN") is not currently in your \$PATH."
    echo "Add this to your ~/.zshrc or ~/.bashrc:"
    echo "  export PATH=\"$(dirname "$TARGET_BIN"):\$PATH\""
fi

echo ""
echo "🎉 You can now run: asc-release --help"
