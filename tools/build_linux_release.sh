#!/bin/bash
#
# build_linux_release.sh
#
# Builds the Linux release zip (pfemame_linux_v<version>.zip) the same way as the published ones:
# the cx_Freeze build/ folder zipped with everything at the top level, symlinks kept (lib/*.so.N) and the
# executable bits preserved - the updater relies on both.
#
# Run from anywhere:   ./tools/build_linux_release.sh            (build + test + zip)
#                      ./tools/build_linux_release.sh --appimage (also build the optional AppImage)
#
# Needs: python3 with requirements.txt installed, patchelf (RPATH fixing in setup.py), strip (binutils - shrinks the
# shared libraries in setup.py), zip.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

VERSION="$(python3 -c "import re; print(re.search(r'__version__\s*=\s*.([0-9.]+)', open('pfemame.py').read()).group(1))")"
ZIP_NAME="pfemame_linux_v${VERSION}.zip"
OUT_DIR="$PROJECT_DIR/dist"

echo "============================================================"
echo " pfeMAME ${VERSION} - Linux release build"
echo "============================================================"

for tool in python3 patchelf strip zip; do
    command -v "$tool" > /dev/null || { echo "ERROR: '$tool' is not installed" >&2; exit 1; }
done

echo "--- Freezing (python3 tools/setup.py build - runs the test suite first and stops if any fail) ---"
rm -rf build
python3 tools/setup.py build

for exe in pfeMAME pfemame_updater; do
    [ -x "build/$exe" ] || { echo "ERROR: build/$exe was not created" >&2; exit 1; }
done

echo "--- Checking the frozen programs start (imports, bundled libraries) ---"
# A throwaway data folder, so the check doesn't create ~/.local/share/pfemame on the build machine
CHECK_DATA="$(mktemp -d)"
RUN_WITH_DISPLAY=()
command -v xvfb-run > /dev/null && RUN_WITH_DISPLAY=(xvfb-run -a)
# Stops the release if a program fails to start (e.g. a missing module or library) - a plain 'cmd && echo OK'
# doesn't stop the script under set -e, so a broken build used to be zipped anyway.
check_starts() {   # check_starts <program>
    local output rc=0
    # PFEMAME_NO_DIALOG: a start-up problem is reported here, not in a desktop dialog that would wait for a click
    output="$(PFEMAME_DATA_DIR="$CHECK_DATA" PFEMAME_NO_DIALOG=1 timeout 20 "${RUN_WITH_DISPLAY[@]}" "./build/$1" \
              --help 2>&1)" || rc=$?
    if [ "$rc" -ne 0 ]; then
        echo "ERROR: build/$1 --help failed (exit code $rc) - not zipping a broken build.  Last output:" >&2
        echo "$output" | tail -20 >&2
        rm -rf "$CHECK_DATA"
        exit 1
    fi
    echo "$1 --help OK"
}
check_starts pfeMAME
check_starts pfemame_updater
rm -rf "$CHECK_DATA"
# Starting them ran the clean-up of lib/ (program_cleanup.py), which leaves a marker for this folder - don't ship it
rm -f build/lib/pfemame_files.done

echo "--- Zipping $ZIP_NAME ---"
mkdir -p "$OUT_DIR"
rm -f "$OUT_DIR/$ZIP_NAME"
(cd build && zip -qry "$OUT_DIR/$ZIP_NAME" .)       # -y keeps symlinks as symlinks
sha256sum "$OUT_DIR/$ZIP_NAME"
echo "Symlinks in the zip: $(zipinfo "$OUT_DIR/$ZIP_NAME" | grep -c '^l')"

if [ "${1:-}" = "--appimage" ]; then
    echo "--- Building the AppImage ---"
    "$SCRIPT_DIR/build_appimage.sh"
fi

echo "============================================================"
echo " Done: $OUT_DIR/$ZIP_NAME"
echo "============================================================"
