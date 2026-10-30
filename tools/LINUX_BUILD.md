# Building the pfeMAME Linux release

The Linux release has to be built on Linux (cx_Freeze can't cross-compile from Windows).

**Build on Ubuntu 22.04.**  A program built on an older distro runs on newer ones (glibc is backwards compatible),
not the other way round, so 22.04 gives the widest reach.  The release is then checked on a current Ubuntu.
In the commands below, `<version>` is the pfeMAME version being built, e.g. `3.10.2`.

## 1. Get the source onto the Linux machine

Copy `pfemame_source_v<version>.zip` (made by `tools/build_source_distribution.py`) and unzip it:

```bash
unzip pfemame_source_v<version>.zip -d pfemame_source_v<version>
cd pfemame_source_v<version>
```

## 2. One-time setup

```bash
sudo apt install python3-venv patchelf binutils zip unzip rsync xvfb libportaudio2   # binutils = strip
python3 -m venv .venv && source .venv/bin/activate
# wxPython: use the wheel for the build distro (building it from source takes a long time):
pip install -f https://extras.wxpython.org/wxPython4/extras/linux/gtk3/ubuntu-22.04 wxPython
pip uninstall -y opencv-python      # if it's there: requirements.txt uses opencv-python-headless (no Qt) instead
pip install -r requirements.txt
```

If `opencv-python` was installed alongside `opencv-python-headless`, uninstalling it damages the shared `cv2`
folder - run `pip install --force-reinstall opencv-python-headless` afterwards.  `tools/setup.py` warns at the start
of a build if `opencv-python` is installed.

If a freshly built `./pfeMAME` stops with a numpy error that has nothing to do with pfeMAME - e.g.
`RuntimeError: object already has a different docstring` raised from `numpy/_core/overrides.py` - the numpy install
is mixed: its Python files and its compiled core come from different numpy versions (an upgrade written over an
existing copy, or a second numpy on the path).  The build just freezes that mixture.  Reinstall numpy cleanly and
build from an empty build folder:

```bash
pip install --force-reinstall --no-cache-dir numpy opencv-python-headless
rm -rf build
```

`./tools/build_linux_release.sh` deletes `build` itself, but `python3 tools/setup.py build` on its own does not -
and whatever an older build left in `build/exe.*/lib` then gets listed in `lib/pfemame_files.txt` as if pfeMAME
shipped it, so `program_cleanup` won't remove it either.

## 3. Build, test and zip

```bash
chmod +x tools/build_linux_release.sh tools/build_appimage.sh
./tools/build_linux_release.sh              # add --appimage for the optional AppImage as well
```

This:

1. runs the test suite (the build stops if any test fails - `PFEMAME_SKIP_TESTS=1` builds anyway, emergencies only),
2. freezes the app with `tools/setup.py`, which on Linux also
   - deletes the wx modules pfeMAME doesn't use,
   - bundles `libtiff.so.5` and the libraries it needs (newer distros only have `libtiff.so.6`) - the build stops if
     one of them can't be found,
   - strips the debugging symbols from every shared library (this more than halves the size),
   - adds the `lib/` folder to each library's search path (RPATH),
3. checks `pfeMAME --help` and `pfemame_updater --help` run - a broken build stops here and is not zipped,
4. writes `dist/pfemame_linux_v<version>.zip` - files at the top level, symlinks kept (`zip -y`) and executable bits
   preserved, like the published releases.

Upload the zip to SourceForge and set it as the default download for Linux so the updater's `best_release.json`
check finds it.

## 4. Check before uploading

- Run `./build/pfeMAME` on a desktop and open a ROM list; play a preview video; run a game.
- `./build/pfemame_updater --install-dir /tmp/test_install --download <SourceForge URL of the previous zip>` in a
  scratch folder: it should download only the changed files ("Delta update: ... downloading ...").

## What the release needs from the user's system

The release relies on the user's system for GTK 3 and the libraries the wxPython wheel was built against.  On a
desktop distro these are normally installed already.  If one is missing, pfeMAME says so when it starts (in the
terminal, and in a desktop dialog if zenity, kdialog, notify-send or xmessage is installed) and names the package to
install for the user's distro.  Users can also run the check themselves (`linux_libs_check.py`):

```bash
./pfeMAME --check-libs
```

The main ones: `libgtk-3`, `libnotify`, `libSDL2`, `libSM`, `libsecret`, `libpcre2-32`, `libpng16`, PortAudio
(`libportaudio.so.2`, for the sound of preview videos - without it they play silently) and the OpenGL / EGL drivers.  (GStreamer is no
longer needed - pfeMAME doesn't use wx.media.)  Checked on Arch (2026-10): a desktop with GTK 3 also needs
`sudo pacman -S sdl2-compat libsm libnotify portaudio`.

## History: things that changed in 3.9.1 that affect Linux

- **User data moves** to `~/.local/share/pfemame` (or `$XDG_DATA_HOME/pfemame`) the first time the new version runs;
  the old files are copied, not moved, and a `SETTINGS_MOVED.txt` note is left in the install folder.  Create an
  empty `portable.txt` in the install folder to keep the data there instead.  For the AppImage this also means the
  settings are now writable (the AppImage itself is read-only).
- **Updating from 3.8.1 or older with the built-in updater still runs the OLD updater**, whose `rsync --delete` can
  wipe the user's favourites / ratings / settings in the install folder.  Tell Linux users to back up (File > Backup)
  or install 3.9.1 or later manually.  From 3.9.1 on the updater never deletes anything.
- The updater's Linux script now uses `rsync -a` (no `--delete`) or `cp -af`, and cleans up its temp folder.
