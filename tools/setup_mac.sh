#!/bin/bash
#
# setup_mac.sh
#
# macOS equivalent of the Windows setup_raw.bat build script.
# Removes any existing build folder, then builds the pfeMAME.app bundle with
# cx_Freeze's bdist_mac command.
#
# First time only, make it executable:
#     chmod +x tools/setup_mac.sh
#
# Then run it from a Terminal:
#     ./tools/setup_mac.sh
#
# (Rename it to setup_mac.command if you would rather double-click it in Finder.)

set -e  # stop on the first error

# Resolve the project root (the parent of this tools/ folder) so the script
# works regardless of the directory it is launched from.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

echo "-------------------------------------------"
echo "- Building pfeMAME.app (macOS)            -"
echo "-------------------------------------------"

# Remove any existing build folder (including a previous bundle) so the build
# starts clean.
if [ -d build ]; then
    echo "Removing existing build folder..."
    rm -rf build
fi

# Build the .app bundle. setup.py changes into the project directory itself,
# so the path below is relative to PROJECT_DIR.
python3 tools/setup.py bdist_mac

echo
echo "!!!!!!!!! Build complete: build/pfeMAME.app !!!!!!!!!"
