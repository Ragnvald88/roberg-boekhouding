#!/bin/bash
# Build Boekhouding.app from AppleScript source.
# Usage: bash build-app.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_NAME="Boekhouding"
SOURCE="$SCRIPT_DIR/$APP_NAME.applescript"
OUTPUT="$SCRIPT_DIR/$APP_NAME.app"

if [ ! -f "$SOURCE" ]; then
    echo "ERROR: $SOURCE not found." >&2
    exit 1
fi

# Pre-flight: ensure old instance isn't running
if osascript -e 'if application "Boekhouding" is running then tell application "Boekhouding" to quit' 2>/dev/null; then
    sleep 1
fi

# Remove old build
rm -rf "$OUTPUT"

# Compile as one-shot launcher (NOT stay-open — the script quits itself
# after spawning main.py; pywebview owns the running-app presence).
echo "Compiling $APP_NAME.app..."
osacompile -o "$OUTPUT" "$SOURCE"

# Ad-hoc code sign (prevents Gatekeeper issues on Sequoia)
codesign -s - --force "$OUTPUT" 2>/dev/null

# Remove quarantine attribute recursively
xattr -dr com.apple.quarantine "$OUTPUT" 2>/dev/null || true

echo ""
echo "Built: $OUTPUT"
echo "Drag to ~/Applications or the Dock to use."
