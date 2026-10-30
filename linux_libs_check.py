#!/usr/bin/env python3

# ----------------------------------------------------------------------------------------------------------------------
# linux_libs_check.py

"""
Finds the system libraries an installed (frozen) Linux build of pfeMAME needs but can't find, and says which package
provides each one on the user's distro.

The Linux release bundles most of what it needs but still relies on the system for GTK 3 and the libraries the
wxPython wheel was built against (see tools/LINUX_BUILD.md).  When one is missing pfeMAME can't start, and when it is
started from a desktop menu nothing at all appears - so:

  * pfeMAME --check-libs        prints the report (runs before wx is imported, so it works even then), and
  * report_startup_failure()    is called by pfemame.py when importing wx / a required package fails because of a
                                missing library: it prints the report and also tries to show it in a desktop dialog.

Standard library only - this has to work when wx itself can't be loaded.
"""

import ctypes.util
import os
import shutil
import subprocess
import sys

# soname -> package name per package manager: (apt, pacman, dnf, zypper).  Only the libraries a missing one is
# realistically reported for - anything else is listed by name only.
PACKAGES = {
    'libgtk-3.so.0':          ('libgtk-3-0', 'gtk3', 'gtk3', 'libgtk-3-0'),
    'libgdk-3.so.0':          ('libgtk-3-0', 'gtk3', 'gtk3', 'libgtk-3-0'),
    'libnotify.so.4':         ('libnotify4', 'libnotify', 'libnotify', 'libnotify4'),
    'libSDL2-2.0.so.0':       ('libsdl2-2.0-0', 'sdl2-compat', 'SDL2', 'libSDL2-2_0-0'),
    'libsecret-1.so.0':       ('libsecret-1-0', 'libsecret', 'libsecret', 'libsecret-1-0'),
    'libpcre2-32.so.0':       ('libpcre2-32-0', 'pcre2', 'pcre2-utf32', 'libpcre2-32-0'),
    'libpng16.so.16':         ('libpng16-16', 'libpng', 'libpng', 'libpng16-16'),
    'libjpeg.so.8':           ('libjpeg8', 'libjpeg-turbo', 'libjpeg-turbo', 'libjpeg8'),
    'libcurl.so.4':           ('libcurl4', 'curl', 'libcurl', 'libcurl4'),
    'libSM.so.6':             ('libsm6', 'libsm', 'libSM', 'libSM6'),
    'libXtst.so.6':           ('libxtst6', 'libxtst', 'libXtst', 'libXtst6'),
    'libXxf86vm.so.1':        ('libxxf86vm1', 'libxxf86vm', 'libXxf86vm', 'libXxf86vm1'),
    'libGL.so.1':             ('libgl1', 'libglvnd', 'libglvnd-glx', 'libGL1'),
    'libEGL.so.1':            ('libegl1', 'libglvnd', 'libglvnd-egl', 'libEGL1'),
    'libwayland-egl.so.1':    ('libwayland-egl1', 'wayland', 'libwayland-egl', 'libwayland-egl1'),
    'libportaudio.so.2':      ('libportaudio2', 'portaudio', 'portaudio', 'libportaudio2'),
}
MANAGERS = ('apt', 'pacman', 'dnf', 'zypper')
INSTALL_COMMANDS = {
    'apt': 'sudo apt install {}',
    'pacman': 'sudo pacman -S {}',
    'dnf': 'sudo dnf install {}',
    'zypper': 'sudo zypper install {}',
}
# Loaded with ctypes rather than linked, so ldd can't see them: (soname, ctypes.util.find_library name, needed for)
LOADED_AT_RUN_TIME = [
    ('libportaudio.so.2', 'portaudio', 'sound for preview videos (without it they play silently)'),
]


def package_manager(os_release: str = '/etc/os-release') -> str | None:
    """apt / pacman / dnf / zypper for the running distro (from ID and ID_LIKE in os-release), or None."""
    try:
        with open(os_release, encoding='utf-8') as f:
            fields = dict(line.rstrip('\n').split('=', 1) for line in f if '=' in line)
    except OSError:
        return None
    ids = (fields.get('ID', '') + ' ' + fields.get('ID_LIKE', '')).replace('"', '').lower().split()
    for distro_id, manager in [('debian', 'apt'), ('ubuntu', 'apt'), ('arch', 'pacman'), ('fedora', 'dnf'),
                               ('rhel', 'dnf'), ('centos', 'dnf'), ('suse', 'zypper'), ('opensuse', 'zypper')]:
        if distro_id in ids:
            return manager
    return None


def parse_ldd(output: str) -> list[str]:
    """The sonames ldd reports as 'not found'."""
    return [line.split('=>')[0].strip() for line in output.splitlines() if '=> not found' in line]


def install_dir() -> str:
    return os.path.dirname(os.path.abspath(sys.executable if getattr(sys, 'frozen', False) else __file__))


def elf_files(folder: str) -> list[str]:
    """The program and every shared library in the install folder (symbolic links skipped - ldd follows them)."""
    found = [os.path.join(folder, name) for name in ('pfeMAME', 'pfemame_updater')
             if os.path.isfile(os.path.join(folder, name))]
    for root, _dirs, files in os.walk(os.path.join(folder, 'lib')):
        for name in files:
            path = os.path.join(root, name)
            if (name.endswith('.so') or '.so.' in name) and not os.path.islink(path):
                found.append(path)
    return found


def find_missing(folder: str, run_ldd=None, find_library=ctypes.util.find_library) -> dict[str, list[str]]:
    """{missing soname: [what needs it]} for the install folder."""
    run_ldd = run_ldd or (lambda path: subprocess.run(['ldd', path], capture_output=True, text=True).stdout)
    missing: dict[str, list[str]] = {}
    for path in elf_files(folder):
        for soname in parse_ldd(run_ldd(path)):
            missing.setdefault(soname, []).append(os.path.relpath(path, folder))
    for soname, name, needed_for in LOADED_AT_RUN_TIME:
        if not find_library(name):
            missing.setdefault(soname, []).append(needed_for)
    return missing


def report(missing: dict[str, list[str]], manager: str | None) -> str:
    """The text shown to the user."""
    if not missing:
        return 'pfeMAME library check: every library pfeMAME needs was found.'
    lines = ['pfeMAME can\'t find these system libraries:', '']
    packages = []
    for soname in sorted(missing):
        users = missing[soname]
        shown = ', '.join(users[:2]) + (f' and {len(users) - 2} more' if len(users) > 2 else '')
        package = PACKAGES.get(soname, (None,) * len(MANAGERS))[MANAGERS.index(manager)] if manager else None
        lines.append(f'  {soname:<24} {"package: " + package if package else ""}')
        lines.append(f'  {"":<24} needed by {shown}')
        if package and package not in packages:
            packages.append(package)
    lines.append('')
    if manager and packages:
        lines.append('Install them with:')
        lines.append('  ' + INSTALL_COMMANDS[manager].format(' '.join(packages)))
        unknown = [s for s in missing if not PACKAGES.get(s)]
        if unknown:
            lines.append('For the others, search your package manager for the library name.')
    else:
        lines.append('Install the packages that provide them with your package manager.  Common package names:')
        for soname in sorted(missing):
            if soname in PACKAGES:
                names = ', '.join(f'{m}: {p}' for m, p in zip(MANAGERS, PACKAGES[soname]))
                lines.append(f'  {soname}: {names}')
    return '\n'.join(lines)


def show_dialog(text: str) -> None:
    """Show the report on the desktop (pfeMAME started from a menu has no terminal).  Uses whatever is installed."""
    title = 'pfeMAME could not start'
    for command in (['zenity', '--error', '--no-markup', f'--title={title}', f'--text={text}'],
                    ['kdialog', '--title', title, '--error', text],
                    ['notify-send', '--urgency=critical', title, text],
                    ['xmessage', '-center', text]):
        if shutil.which(command[0]):
            try:
                subprocess.run(command, timeout=600)
                return
            except (OSError, subprocess.SubprocessError):
                continue


def report_startup_failure(error: BaseException) -> None:
    """
    Called when pfeMAME can't start because a package failed to load: print the report and show it on the desktop
    (not when PFEMAME_NO_DIALOG=1, as in tools/build_linux_release.sh's start check).
    """
    text = f'pfeMAME could not start: {error}'
    cause = error.__cause__ or error.__context__        # e.g. numpy hides the real error behind its own message
    if cause is not None and str(cause) not in str(error):
        text += f'\nCaused by: {cause}'
    missing = find_missing(install_dir())
    text += '\n\n' + report(missing, package_manager())
    if not missing:
        text += '\nSo the problem is something else - please report the error above.'
    print(text, file=sys.stderr)
    if (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')) and os.environ.get('PFEMAME_NO_DIALOG') != '1':
        show_dialog(text)


def main() -> int:
    """pfeMAME --check-libs: print the report.  Exit code 1 if anything is missing."""
    if not sys.platform.startswith('linux'):
        print('pfeMAME --check-libs is for the Linux version.')
        return 0
    missing = find_missing(install_dir())
    print(report(missing, package_manager()))
    return 1 if missing else 0
