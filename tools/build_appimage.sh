#!/bin/bash
#
# build_appimage.sh
#
# Builds a portable, cross-distro Linux AppImage of pfeMAME.
#
# It uses your existing cx_Freeze build for the frozen application, then wraps
# it with linuxdeploy + linuxdeploy-plugin-gtk. The GTK plugin bundles the whole
# GTK3 stack (libgtk-3, gdk-pixbuf loaders, GObject typelibs, immodules) and
# writes an AppRun hook that sets the GTK environment, so the result runs on
# Fedora / Arch / openSUSE / etc. WITHOUT relying on the host's GTK or webkit.
#
# This is a SEPARATE, OPTIONAL build path:
#   - It does NOT modify setup.py and does NOT change `python3 setup.py build`.
#   - It calls `setup.py build`, then packages the result into dist/*.AppImage.
#
# Linux only. First time:
#     chmod +x tools/build_appimage.sh
#     ./tools/build_appimage.sh
#
# The first run downloads linuxdeploy + the GTK plugin (cached in
# tools/.appimage-tools). Requires: curl, and a desktop-class host with GTK3
# dev/runtime present at build time (the plugin copies from the build host).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

APP_NAME="pfeMAME"
EXE_NAME="pfeMAME"                       # cx_Freeze Executable target_name
ARCH="$(uname -m)"

VERSION="$(python3 - <<'PY'
import re
m = re.search(r'''__version__\s*=\s*['"]([^'"]+)''', open('pfemame.py').read())
print(m.group(1) if m else '0.0.0')
PY
)"

TOOLS_DIR="$SCRIPT_DIR/.appimage-tools"
APPDIR="$PROJECT_DIR/AppDir"

echo "============================================================"
echo " Building $APP_NAME $VERSION AppImage ($ARCH)"
echo "============================================================"

# ----------------------------------------------------------------------------
# 1. Freeze the application (your existing, unmodified build path -> build/)
# ----------------------------------------------------------------------------
echo "--- Freezing application (python3 tools/setup.py build) ---"
rm -rf "$APPDIR"
rm -rf build
python3 tools/setup.py build

FROZEN_DIR="$PROJECT_DIR/build"
if [ ! -x "$FROZEN_DIR/$EXE_NAME" ]; then
    echo "ERROR: expected frozen executable at $FROZEN_DIR/$EXE_NAME" >&2
    echo "       (check that 'python3 tools/setup.py build' succeeded)" >&2
    exit 1
fi

# ----------------------------------------------------------------------------
# 2. Lay out an AppDir from the frozen output
# ----------------------------------------------------------------------------
echo "--- Assembling AppDir ---"
mkdir -p "$APPDIR/usr/bin"
cp -a "$FROZEN_DIR/." "$APPDIR/usr/bin/"

# linuxdeploy requires a desktop file and an icon whose name matches Icon=.
mkdir -p "$APPDIR/usr/share/applications"
mkdir -p "$APPDIR/usr/share/icons/hicolor/256x256/apps"
cp "$SCRIPT_DIR/pfemame.desktop" "$APPDIR/usr/share/applications/$APP_NAME.desktop"
cp "$PROJECT_DIR/pfemame.png"    "$APPDIR/usr/share/icons/hicolor/256x256/apps/pfemame.png"

# ----------------------------------------------------------------------------
# 3. Fetch linuxdeploy + the GTK plugin (cached under tools/.appimage-tools)
# ----------------------------------------------------------------------------
echo "--- Fetching build tools ---"
mkdir -p "$TOOLS_DIR"
fetch() {  # fetch <url> <dest>
    if [ ! -f "$2" ]; then
        echo "    downloading $(basename "$2")"
        curl -fL -o "$2" "$1"
        chmod +x "$2"
    fi
}
LD="$TOOLS_DIR/linuxdeploy-$ARCH.AppImage"
LD_GTK="$TOOLS_DIR/linuxdeploy-plugin-gtk.sh"
fetch "https://github.com/linuxdeploy/linuxdeploy/releases/download/continuous/linuxdeploy-$ARCH.AppImage" "$LD"
fetch "https://raw.githubusercontent.com/linuxdeploy/linuxdeploy-plugin-gtk/master/linuxdeploy-plugin-gtk.sh" "$LD_GTK"

# If libfuse2 is unavailable (containers/CI), run the AppImage tools extracted.
LD_RUN=("$LD")
if ! { ldconfig -p 2>/dev/null | grep -q "libfuse.so.2"; }; then
    echo "    libfuse.so.2 not found -> using --appimage-extract-and-run"
    LD_RUN=("$LD" "--appimage-extract-and-run")
fi

# ----------------------------------------------------------------------------
# 4. Bundle GTK + dependencies and build the AppImage
# ----------------------------------------------------------------------------
echo "--- Bundling GTK and building AppImage ---"
export DEPLOY_GTK_VERSION=3              # tell the plugin we use GTK3
export VERSION                          # linuxdeploy embeds this in the filename
export PATH="$TOOLS_DIR:$PATH"          # so linuxdeploy finds the gtk plugin

mkdir -p dist
rm -f "dist/${APP_NAME}"*.AppImage

"${LD_RUN[@]}" --appdir "$APPDIR" \
    --executable "$APPDIR/usr/bin/$EXE_NAME" \
    --desktop-file "$APPDIR/usr/share/applications/$APP_NAME.desktop" \
    --icon-file "$APPDIR/usr/share/icons/hicolor/256x256/apps/pfemame.png" \
    --plugin gtk \
    --output appimage

# linuxdeploy drops the .AppImage in the current dir; move it into dist/.
shopt -s nullglob
for f in "${APP_NAME}"*.AppImage ./*.AppImage; do
    mv -f "$f" dist/ 2>/dev/null || true
done

echo
echo "============================================================"
echo " Done. Output:"
ls -1 dist/*.AppImage 2>/dev/null || echo "  (no AppImage found - check output above)"
echo "============================================================"
