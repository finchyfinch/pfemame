#!/usr/bin/env python3

# ----------------------------------------------------------------------------------------------------------------------
# setup.py
#
# """
# This is the cxFreeze setup file for building a Windows / Linux / macOS distribution of pfeMAME
#
# Run it from the command line using python3 setup.py build, or if using Windows you can just run the setup.bat file.
#
# The build includes the Python runtime and the third-party packages pfeMAME uses.  Their licences are copied into
# the build's third_party_licenses folder after every build (tools/third_party_notices.py).  If your platform requires
# support files that are not distributed, look at the reported errors and track the files down from the internet.  This
# is typically only an issue under Windows and usually relates to a missing .Net or C++ redistribution package.
# """
#

"""
cx_Freeze setup file for building Windows/Linux/macOS distributions of pfeMAME.

Usage:
    python3 setup.py build

Every build command first runs the test suite (pytest) and stops if any test fails.  To build anyway in an
emergency, set the environment variable PFEMAME_SKIP_TESTS=1.

Dependencies:
    pip install -r requirements.txt   (in the source folder)
    Use opencv-python-headless, not opencv-python: the build warns if opencv-python is installed, as it adds Qt to the
    build (about 35 MB on Linux, and a second GUI toolkit loaded into pfeMAME).
"""

import os
import sys
import shutil
import subprocess
import glob
import re
import struct
from cx_Freeze import setup, Executable
from cx_Freeze.command.build_exe import build_exe as cx_build_exe

# --- Path Configuration ---
# This setup.py is in the 'tools' subfolder, so we need to reference the parent directory
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)

# Change to parent directory for the build
os.chdir(PARENT_DIR)

# --- Build output directory ---
# cx_Freeze's bdist_mac creates the bundle at <build_base>/<name>.app and then
# copies the ENTIRE build_exe output into Contents/Resources. If the build_exe
# output directory is the build base itself (build/), the freshly created
# build/pfeMAME.app ends up inside its own copy source and cx_Freeze recurses
# forever (build/pfeMAME.app/Contents/Resources/pfeMAME.app/Contents/Resources/...).
# On macOS we therefore keep the frozen output in a dedicated subfolder so the
# bundle (build/pfeMAME.app) and its source (build/exe) never overlap. Windows
# and Linux keep writing straight to build/ as before.
if sys.platform == 'darwin':
    BUILD_EXE_DIR = os.path.join(PARENT_DIR, "build", "exe")
else:
    BUILD_EXE_DIR = os.path.join(PARENT_DIR, "build")

# --- Application Metadata ---
sys.path.insert(0, PARENT_DIR)
import pfemame
VERSION = pfemame.__version__
APP_NAME = 'pfeMAME'
AUTHOR = pfemame.__author__
DESCRIPTION = 'Python front-end for the MAME emulator system'
COPYRIGHT = pfemame.__copyright__

# --- Files to Include ---
include_files = [
    'catver.ini',
    'changelog.docx',
    'controls.txt',
    'pfeMAME_Manual.pdf',
    'non_mame_defaults.xml',
    'images',
    'toolbar_icons',
    'locales',
    'license',
]

# --- Windows SSL DLLs for Python >= 3.7 ---
if sys.platform == 'win32' and sys.version_info >= (3, 7):
    dll_patterns = ['libcrypto-*.dll', 'libssl-*.dll']
    for pattern in dll_patterns:
        for path in glob.glob(os.path.join(sys.base_prefix, 'DLLs', pattern)):
            include_files.append(path)

# --- Executables: pfeMAME and pfemame_updater ---
base = 'gui' if sys.platform == 'win32' else None
executables = [
    Executable(
        script='pfemame.py',
        target_name=APP_NAME,
        base=base,
        icon='images/pfemame.ico',
        copyright=COPYRIGHT
    ),
    Executable(
        script='pfemame_updater.py',
        target_name='pfemame_updater',
        base=base,  # GUI for wxPython
        icon='images/pfemame.ico',
        copyright=COPYRIGHT
    )
]

# --- macOS .app bundle configuration ---
# Build with: python3 setup.py bdist_mac   (and optionally bdist_dmg for a .dmg)
#
# cx_Freeze runs build_exe first, then copies the ENTIRE build output - the
# executables, the Python runtime, every shared library and every include_files
# entry above - into <bundle_name>.app/Contents/MacOS. That means all
# dependencies and resources travel inside the bundle automatically; nothing has
# to be copied in by hand. The adjacent Contents/Resources folder receives the
# icon and the generated Info.plist. functions.path_to_me() is bundle-aware and
# resolves resources from Contents/MacOS or Contents/Resources, so the app keeps
# working even if the data files are later relocated for code-signing.
#
# Adjust BUNDLE_IDENTIFIER to your own reverse-DNS string if you sign/notarise.
BUNDLE_IDENTIFIER = 'com.pfemame.pfemame'

bdist_mac_options = {
    'bundle_name': APP_NAME,
    'iconfile': os.path.join('images', 'pfemame.icns'),
    'plist_items': [
        ('CFBundleName', APP_NAME),
        ('CFBundleDisplayName', APP_NAME),
        ('CFBundleIdentifier', BUNDLE_IDENTIFIER),
        ('CFBundleVersion', VERSION),
        ('CFBundleShortVersionString', VERSION),
        ('NSHighResolutionCapable', True),
        ('NSHumanReadableCopyright', COPYRIGHT),
    ],
}

bdist_dmg_options = {
    'volume_label': f'{APP_NAME}-{VERSION}',
    'applications_shortcut': True,
}

# --- Windows .msi installer configuration ---
# Build with: python setup.py bdist_msi   (or tools\setup_msi.bat)
#
# The upgrade code tells Windows that every pfeMAME MSI is the same product, so installing a new version replaces the
# old one instead of adding a second "pfeMAME" to Installed apps.  NEVER change it - a different code makes Windows
# treat the next version as a separate product again.  (MSIs built before 3.10.2 had no upgrade code, so the first
# MSI with one still installs alongside those; uninstall the old one first.)
#
# bdist_dir: bdist_msi copies the whole build/ folder into its temp folder, which by default is INSIDE build/
# (build/bdist.win-amd64/msi), so it copied itself until the path was too long and the MSI build failed - the same
# trap as bdist_mac above.  Its temp folder is therefore kept next to build/ instead (deleted when the MSI is made).
bdist_msi_options = {
    'upgrade_code': '{EB76A8FD-D7BC-4A14-8779-F9BEF3F7E18C}',
    'bdist_dir': os.path.join(PARENT_DIR, 'build_msi_temp'),
}


# --- Linux-only: Shared Library Bundling ---
SYSTEM_PREFIXES = [
    "/lib", "/lib64",
    "/usr/lib", "/usr/lib64",
    "/usr/local/lib", "/usr/local/lib64"
]


# System libraries to bundle even though they are in a system folder, because newer distros no longer have them
# (the Ubuntu 22.04 wxPython wheel needs libtiff.so.5; Ubuntu 24.04+, Arch, Fedora... only have libtiff.so.6).
# Their own dependencies are bundled with them (except HOST_BASE_LIBS / NEVER_BUNDLE) - e.g. libtiff.so.5 also needs
# libjbig.so.0 and libdeflate.so.0, which other distros don't have under those names.  A soname nothing in the build
# needs is skipped (e.g. when building on a distro whose wxPython uses libtiff.so.6); one that is needed but can't be
# found stops the build.
FORCE_INCLUDE_SONAMES = [
    "libtiff.so.5",
]

# Never bundled: every Linux system has these with a stable ABI, and a bundled older copy would be used by the whole
# process instead of the system's own (including by the system's GTK).
HOST_BASE_LIBS = {
    "libc", "libm", "libdl", "libpthread", "librt", "libutil", "ld-linux-x86-64", "ld-linux-aarch64",
    "libgcc_s", "libstdc++", "libz", "liblzma", "libzstd", "libbz2",
}

# Removed from the build if nothing in it needs them: libraries cx_Freeze copies only because the host keeps them in
# a private folder (Ubuntu: /usr/lib/x86_64-linux-gnu/pulseaudio/libpulsecommon-15.99.so).  They belong to a host
# library (libpulse) and only work with that exact version, and on other distros their own dependencies are missing
# (pfeMAME --check-libs then reported libapparmor / libasyncns / libsndfile as missing on Arch).
HOST_PRIVATE_LIBS = ("libpulsecommon",)

# Never bundled: must come from the host system (GPU / display driver dependent)
NEVER_BUNDLE = {
    "libEGL", "libEGL_mesa", "libGL", "libGLX", "libGLX_mesa",
    "libGLdispatch", "libGLESv2",
    "libgbm", "libdrm", "libvulkan",
    "libwayland-client", "libwayland-server", "libwayland-egl",
    "libxcb", "libX11",
}


def lib_stem(lib_name):
    """
    The library name without version or wheel hash, for matching against HOST_BASE_LIBS / NEVER_BUNDLE:
    libdrm.so.2 -> libdrm, and libdrm-b0291a67.so.2.4.0 (a wheel's renamed copy) -> libdrm.
    """
    return re.sub(r"-[0-9a-f]{8}$", "", lib_name.split(".so")[0])


def has_symbols(path):
    """True if an ELF file still has a symbol table or debug information, i.e. strip would make it smaller."""
    result = subprocess.run(["readelf", "-S", "-W", path], capture_output=True, text=True)
    return result.returncode == 0 and re.search(r"\s\.(symtab|debug_\w+)\s", result.stdout) is not None


def elf_load_segments_aligned(path):
    """
    The loader's own check on a 64-bit ELF file: every PT_LOAD segment's address and file offset must agree modulo
    its alignment, otherwise loading fails with 'ELF load command address/offset not page-aligned'.
    """
    with open(path, "rb") as f:
        header = f.read(64)
        if len(header) < 64 or header[:4] != b"\x7fELF" or header[4] != 2:
            return True                         # Not a 64-bit ELF file - nothing to check
        order = "<" if header[5] == 1 else ">"
        phoff, = struct.unpack_from(order + "Q", header, 0x20)
        phentsize, phnum = struct.unpack_from(order + "HH", header, 0x36)
        f.seek(phoff)
        table = f.read(phentsize * phnum)
    for i in range(phnum):
        p_type, _flags, p_offset, p_vaddr, _paddr, _filesz, _memsz, p_align = \
            struct.unpack_from(order + "IIQQQQQQ", table, i * phentsize)
        if p_type == 1 and p_align > 1 and (p_vaddr - p_offset) % p_align:
            return False
    return True


def direct_needed(path):
    """The sonames an ELF file links to directly (its own DT_NEEDED entries, unlike ldd's full list)."""
    result = subprocess.run(["readelf", "-d", "-W", path], capture_output=True, text=True)
    return re.findall(r"\(NEEDED\)\s+Shared library: \[([^\]]+)\]", result.stdout)


def ldd(path):
    """{soname: resolved path} of the libraries an ELF file needs - the path is None if ldd reports 'not found'."""
    result = subprocess.run(["ldd", path], capture_output=True, text=True, check=True)
    deps = {}
    for line in result.stdout.splitlines():
        # Lines look like:   libtiff.so.5 => /lib/x86_64-linux-gnu/libtiff.so.5 (0x00007f...)
        #                    libjbig.so.0 => not found
        parts = line.strip().split("=>")
        if len(parts) != 2:
            continue
        target = parts[1].strip().split(" ")[0]
        deps[parts[0].strip()] = target if os.path.isabs(target) and os.path.exists(target) else None
    return deps

# wx modules pfeMAME doesn't import.  wx.html2 (WebView) went when the ribbon bar became native wxPython - leaving it
# out also removes the libwebkit2gtk dependency that broke cross-distro Linux runs.  Before adding a wx
# import to pfeMAME, check it isn't listed here.  wx.richtext IS used (Tile View).  wx.media (MediaCtrl) went with the
# Wayland video problems - leaving it out also removes the need for GStreamer on Linux.
UNUSED_WX_MODULES = ["html2", "propgrid", "dataview", "aui", "ribbon", "stc", "xrc", "media"]
# The wxWidgets library behind each of those, as it appears in the file names (libwx_gtk3u_aui-3.2.so.0,
# wxmsw32u_aui_vc140_x64.dll, libwx_osx_cocoau_aui-3.2.dylib).  dataview has no library of its own (it is in core).
UNUSED_WX_LIBRARIES = ["webview", "propgrid", "aui", "ribbon", "stc", "xrc", "media"]


class build_exe(cx_build_exe):
    def run(self):
        super().run()
        self.remove_unused_wx_modules()
        if sys.platform.startswith("linux"):
            self.bundle_shared_libs()
        if sys.platform != "darwin":
            self.write_program_file_list()

    def write_program_file_list(self):
        """
        List every file the build ships in lib/ (lib/pfemame_files.txt).  The installed pfeMAME deletes anything else
        it finds in lib/ - files an older version left behind, as updates never delete anything (program_cleanup.py).
        Must be the last step, after everything has been added to or removed from lib/.
        """
        from program_cleanup import write_manifest, MANIFEST_NAME
        count = write_manifest(os.path.join(self.build_exe, "lib"))
        print(f"📋 Wrote lib/{MANIFEST_NAME} ({count} entries)")

    def remove_unused_wx_modules(self):
        """Delete the C extensions and wxWidgets libraries of UNUSED_WX_MODULES, which cx_Freeze copies anyway."""
        wx_dir = os.path.join(self.build_exe, "lib", "wx")
        if not os.path.isdir(wx_dir):
            return
        extension = re.compile(r"^_(%s)\." % "|".join(UNUSED_WX_MODULES))
        library = re.compile(r"u_(%s)[-_.]" % "|".join(UNUSED_WX_LIBRARIES))
        removed = 0
        for file in os.listdir(wx_dir):
            if extension.match(file) or library.search(file):
                path = os.path.join(wx_dir, file)
                removed += os.lstat(path).st_size
                os.remove(path)
                print(f"🗑️ Removed unused wx file: {file}")
        print(f"✅ Removed unused wx modules ({removed / 1048576:.0f} MB)")
        self.write_third_party_licenses()

    def write_third_party_licenses(self):
        """Copy the licences of the bundled third-party packages into the build (see tools/third_party_notices.py)."""
        sys.path.insert(0, SCRIPT_DIR)
        from third_party_notices import write_third_party_licenses, FOLDER_NAME
        missing = write_third_party_licenses(self.build_exe)
        print(f"\n📄 Third-party licences written to {os.path.join(self.build_exe, FOLDER_NAME)}")
        if missing:
            print("   No licence file found for: " + ", ".join(missing) + " (still listed in THIRD_PARTY_NOTICES.txt)")

    def bundle_shared_libs(self):
        print("\n🔍 Scanning for shared library dependencies...")

        lib_dir = os.path.join(self.build_exe, "lib")
        os.makedirs(lib_dir, exist_ok=True)

        real_dest_paths = set()
        all_deps = set()
        needed = {}     # soname -> resolved path (None = not found) of every library the build's ELF files need
        build_root = os.path.realpath(self.build_exe) + os.sep

        # --- Step 1: Collect ELF files
        so_files = []
        for root, _, files in os.walk(self.build_exe):
            for file in files:
                if file.endswith(".so") or ".so." in file or file == APP_NAME:
                    so_files.append(os.path.join(root, file))

        # --- Step 2: Scan with ldd
        for so_path in so_files:
            try:
                deps = ldd(so_path)
                for soname, lib_path in deps.items():
                    if needed.get(soname) is None:
                        needed[soname] = lib_path
                    if lib_path is None:
                        continue
                    # Already in the build (wx/libwx_*.so, opencv_python.libs, numpy.libs...) - copying it to lib/
                    # again only doubled the download size
                    if os.path.realpath(lib_path).startswith(build_root):
                        continue
                    if any(lib_path.startswith(prefix) for prefix in SYSTEM_PREFIXES):
                        continue
                    all_deps.add(lib_path)
            except subprocess.CalledProcessError as e:
                print(f"⚠️ Skipping {so_path}: {e.stderr.strip()}")

        # --- Step 2b: Remove HOST_PRIVATE_LIBS copies nothing in the build links to directly (ldd's list can't be
        # used: it includes what the host's own libpulse needs, which finds its own copy)
        private = [p for p in so_files if os.path.basename(p).startswith(HOST_PRIVATE_LIBS)]
        linked = set()
        if private:
            for so_path in so_files:
                linked.update(direct_needed(so_path))
        for so_path in private:
            name = os.path.basename(so_path)
            if name not in linked and os.path.isfile(so_path):
                os.remove(so_path)
                print(f"🗑️ Removed {os.path.relpath(so_path, self.build_exe)} (a host library's private part - "
                      f"nothing in the build uses it)")

        # --- Step 3: Add the forced libs (FORCE_INCLUDE_SONAMES) and, recursively, their own dependencies
        self.bundle_forced_libs(needed, lib_dir, build_root, real_dest_paths)

        # --- Step 4: Copy discovered deps
        for lib_path in all_deps:
            lib_name = os.path.basename(lib_path)
            dest_path = os.path.join(lib_dir, lib_name)
            real_src = os.path.realpath(lib_path)

            # Skip GPU/display libs - must use host system versions
            if lib_stem(lib_name) in NEVER_BUNDLE:
                print(f"⏭️ Skipping system lib: {lib_name}")
                continue

            if real_src in real_dest_paths or os.path.exists(dest_path):
                continue

            try:
                shutil.copy(lib_path, dest_path)
                real_dest_paths.add(real_src)

                if ".so." in lib_name:
                    base, version = lib_name.split(".so.", 1)
                    major = version.split(".")[0]
                    symlink_name = f"{base}.so.{major}"
                    symlink_path = os.path.join(lib_dir, symlink_name)
                    if not os.path.exists(symlink_path):
                        os.symlink(lib_name, symlink_path)
                        print(f"🔗 Symlink: {symlink_name} → {lib_name}")
            except Exception as e:
                print(f"⚠️ Error copying {lib_name}: {e}")

        # --- Step 4b: Strip debug symbols from every shared library
        # The wxPython wheels from extras.wxpython.org keep their debug symbols (wx alone drops from about 340 MB to
        # about 50 MB).  --strip-unneeded keeps the symbols other libraries link against.  Done before Step 5 because
        # stripping a file patchelf has already changed can break it.
        self.strip_shared_libs()

        # --- Step 5: Add the lib dir to the RPATH of every shared library
        # The lib dir is ADDED to each library's existing search path rather than replacing it, so libraries still
        # find their neighbours first (e.g. wx/_core*.so -> wx/libwx_*.so via $ORIGIN) and only fall back to lib/
        # for the libraries copied in above.  The pfeMAME / pfemame_updater executables are left alone: cx_Freeze
        # sets them up itself and patchelf corrupts them (it aborts on cx_Freeze 8 launchers).
        patched = 0
        for root, _, files in os.walk(self.build_exe):
            for file in files:
                filepath = os.path.join(root, file)
                if not (file.endswith(".so") or ".so." in file) or os.path.islink(filepath):
                    continue

                # Calculate relative path from this file back to the lib dir
                rel = os.path.relpath(lib_dir, root)
                lib_rpath = f"$ORIGIN/{rel}" if rel != "." else "$ORIGIN"

                try:
                    current = subprocess.run(["patchelf", "--print-rpath", filepath],
                                             check=True, capture_output=True, text=True).stdout.strip()
                    entries = [e for e in current.split(":") if e]
                    if lib_rpath in entries:
                        continue
                    subprocess.run(
                        ["patchelf", "--set-rpath", ":".join(entries + [lib_rpath]), "--force-rpath", filepath],
                        check=True, capture_output=True
                    )
                    patched += 1
                except Exception as e:
                    print(f"⚠️ Failed to patch RPATH for {file}: {e}")

        print(f"✅ Patched RPATH on {patched} shared libraries")

    def bundle_forced_libs(self, needed, lib_dir, build_root, real_dest_paths):
        """
        Copy each FORCE_INCLUDE_SONAMES library the build needs into lib/, then the libraries it needs in turn (except
        HOST_BASE_LIBS / NEVER_BUNDLE), each with its soname symlink.  Stops the build if one can't be found - the
        release would otherwise fail to start on distros that don't have it.
        """
        queue = []
        for soname in FORCE_INCLUDE_SONAMES:
            if soname in needed:
                queue.append((soname, needed[soname], "the build"))
            else:
                print(f"ℹ️ {soname} isn't needed by this build - not bundled")

        missing = []
        seen = set()
        while queue:
            soname, lib_path, needed_by = queue.pop(0)
            if soname in seen:
                continue
            seen.add(soname)
            if lib_path is None:
                missing.append(f"{soname} (needed by {needed_by})")
                continue
            real_path = os.path.realpath(lib_path)
            if real_path.startswith(build_root):
                continue        # cx_Freeze has already bundled it (and its dependencies)

            # Copy the real file, then the soname symlink (e.g. libtiff.so.5 -> libtiff.so.5.7.0)
            real_name = os.path.basename(real_path)
            if not os.path.exists(os.path.join(lib_dir, real_name)):
                shutil.copy2(real_path, os.path.join(lib_dir, real_name))
                real_dest_paths.add(real_path)
                print(f"📦 Forced copy: {real_name}" + ("" if needed_by == "the build" else f" (needed by {needed_by})"))
            symlink_path = os.path.join(lib_dir, soname)
            if soname != real_name and not os.path.lexists(symlink_path):
                os.symlink(real_name, symlink_path)
                print(f"🔗 Symlink: {soname} → {real_name}")

            for dep, dep_path in ldd(real_path).items():
                if lib_stem(dep) not in HOST_BASE_LIBS and lib_stem(dep) not in NEVER_BUNDLE:
                    queue.append((dep, dep_path, soname))

        if missing:
            sys.exit("ERROR: these libraries must be bundled but weren't found on the build machine - install them "
                     "and build again:\n    " + "\n    ".join(missing))

    def strip_shared_libs(self):
        if not shutil.which("strip"):
            print("⚠️ 'strip' not found (install binutils) - shared libraries left unstripped, the build will be much "
                  "bigger")
            return

        # Only files that still have symbols / debug information are stripped.  The libraries wheels bundle
        # (numpy.libs, opencv_python_headless.libs, cx_Freeze's own libreadline-<hash>...) are already stripped and
        # were rewritten by patchelf when the wheel was made - strip before binutils 2.39 (Ubuntu 22.04 has 2.38)
        # corrupts those ("ELF load command address/offset not page-aligned", so numpy failed to import).  Each
        # stripped copy is also checked the way the loader does, and the original kept if the check fails.
        before = after = 0
        failed = []
        for root, _, files in os.walk(self.build_exe):
            for file in files:
                filepath = os.path.join(root, file)
                if not (file.endswith(".so") or ".so." in file) or os.path.islink(filepath):
                    continue
                size = os.path.getsize(filepath)
                before += size
                if has_symbols(filepath):
                    stripped = filepath + ".stripped"
                    result = subprocess.run(["strip", "--strip-unneeded", "-o", stripped, filepath],
                                            capture_output=True, text=True)
                    if result.returncode != 0:
                        failed.append(f"{file}: {result.stderr.strip()}")
                    elif not elf_load_segments_aligned(stripped):
                        failed.append(f"{file}: strip damaged it (load segments not aligned) - original kept")
                    else:
                        shutil.copymode(filepath, stripped)
                        os.replace(stripped, filepath)
                        size = os.path.getsize(filepath)
                    if os.path.exists(stripped):
                        os.remove(stripped)
                after += size

        for failure in failed:
            print(f"⚠️ Could not strip {failure}")
        print(f"✅ Stripped shared libraries: {before / 1048576:.0f} MB -> {after / 1048576:.0f} MB")

# --- Run the test suite before building ---
# Any command that builds something - plain build or an installer / bundle
BUILD_COMMANDS = {'build', 'build_exe', 'bdist_msi', 'bdist_mac', 'bdist_dmg', 'bdist_appimage', 'bdist_deb',
                  'bdist_rpm'}


def run_tests_before_building():
    """
    Stop the build unless every test passes.  Set the environment variable PFEMAME_SKIP_TESTS=1 to build anyway
    (emergencies only - it prints a warning).
    """
    if not BUILD_COMMANDS.intersection(sys.argv[1:]):
        return
    if os.environ.get('PFEMAME_SKIP_TESTS') == '1':
        print('\n' + '!' * 78)
        print(' WARNING: PFEMAME_SKIP_TESTS=1 is set - building WITHOUT running the tests')
        print('!' * 78 + '\n')
        return
    try:
        import pytest  # noqa: F401  (only checking it is installed - the tests run in their own process)
    except ImportError:
        sys.exit('ERROR: pytest is not installed, so the tests can\'t be run before building.  Run:  pip install pytest')

    print('--- Running the test suite before building ---', flush=True)     # (before pytest's own output)
    result = subprocess.run([sys.executable, '-m', 'pytest', 'tests', '-q', '-p', 'no:cacheprovider'], cwd=PARENT_DIR)
    if result.returncode != 0:
        sys.exit(f'ERROR: Tests failed - build stopped (pytest exit code {result.returncode}).  Fix the failing '
                 f'tests, or set PFEMAME_SKIP_TESTS=1 to build anyway.')
    print('--- All tests passed - building ---')


def warn_if_full_opencv_installed():
    """
    pfeMAME only needs opencv-python-headless.  opencv-python also provides cv2 but adds Qt (about 35 MB on Linux, and
    a second GUI toolkit loaded into pfeMAME), so warn if that is the one installed.
    """
    if not BUILD_COMMANDS.intersection(sys.argv[1:]):
        return
    from importlib.metadata import PackageNotFoundError, version
    try:
        full_version = version('opencv-python')
    except PackageNotFoundError:
        return
    print('\n' + '!' * 78)
    print(f' WARNING: opencv-python {full_version} is installed - the build will include OpenCV\'s own windows (Qt on')
    print(' Linux), which pfeMAME doesn\'t need.  Switch to the headless package (both use the same cv2 folder, so')
    print(' reinstall it afterwards):')
    print('     pip uninstall -y opencv-python')
    print('     pip install --force-reinstall opencv-python-headless')
    print('!' * 78 + '\n')


warn_if_full_opencv_installed()
run_tests_before_building()

# --- Setup ---
setup(
    name=APP_NAME,
    version=VERSION,
    author=AUTHOR,
    description=DESCRIPTION,
    options={
        "build_exe": {
            "build_exe": BUILD_EXE_DIR,  # Build output dir (subfolder on macOS to avoid bdist_mac recursion)
            "include_files": include_files,
            # wx is deliberately not listed: cx_Freeze follows pfeMAME's own wx imports.  Listing it copied every
            # wx module, and with them reportlab (wx.lib.pdfviewer), pip (wx.tools.wxget) and setuptools.
            # email: py7zr -> importlib.metadata needs email.header, which cx_Freeze misses on Python 3.14 (its
            # email._policybase uses 'from email import header').  wx.media used to pull it in; without it the
            # Windows build failed to start ("cannot import name 'header' from 'email'").
            "packages": ["dbm", "py7zr", "OpenGL", "certifi", "email"],
             "excludes": [
                    "tkinter",
                    "cv2.gapi.wip",
                    "unittest",
                    "test",
                    # Build / packaging tools - never used by pfeMAME itself
                    "pip",
                    "setuptools",
                    "pkg_resources",
                    "reportlab",
                    "pytest",
                    "_pytest",
                    # wx modules pfeMAME doesn't use (their C extensions and wx libraries are removed after the
                    # build by remove_unused_wx_modules(), as cx_Freeze's wx hook copies them regardless)
                    *[f"wx.{module}" for module in UNUSED_WX_MODULES],
                    *[f"wx._{module}" for module in UNUSED_WX_MODULES],
                    # Exclude most OpenGL extensions and advanced features
                    #"OpenGL.GL.ARB.shader_objects",
                    #"OpenGL.GL.ARB.vertex_program",
                    #"OpenGL.GL.ARB.fragment_program",
                    #"OpenGL.GL.ARB.geometry_shader4",
                    #"OpenGL.GL.ARB.compute_shader",
                    #"OpenGL.GL.ARB.tessellation_shader",
                    #"OpenGL.GL.EXT",
                    #"OpenGL.GL.NV",
                    #"OpenGL.GL.AMD",
                    #"OpenGL.GL.INTEL",
                    #"OpenGL.GLUT",
                    #"OpenGL.GLU",
                    # Exclude shader-related modules
                    "OpenGL.GL.shaders",
                    # Exclude image handling you don't use
                    #"OpenGL.GL.images",
                ]
        },
        "bdist_msi": bdist_msi_options,
        "bdist_mac": bdist_mac_options,
        "bdist_dmg": bdist_dmg_options,
    },
    executables=executables,
    cmdclass={"build_exe": build_exe},
)
