"""linux_libs_check: the missing-system-library report for the installed Linux version (pfeMAME --check-libs)."""
import os

import pytest

import linux_libs_check as check

LDD_OUTPUT = """\tlinux-vdso.so.1 (0x00007ffd1a3f2000)
\tlibwx_gtk3u_core-3.2.so.0 => /opt/pfeMAME/lib/wx/libwx_gtk3u_core-3.2.so.0 (0x00007f0e1c000000)
\tlibnotify.so.4 => not found
\tlibgtk-3.so.0 => /usr/lib/libgtk-3.so.0 (0x00007f0e1b800000)
\tlibSDL2-2.0.so.0 => not found
\tlibc.so.6 => /usr/lib/libc.so.6 (0x00007f0e1b400000)
"""


def test_parse_ldd():
    assert check.parse_ldd(LDD_OUTPUT) == ['libnotify.so.4', 'libSDL2-2.0.so.0']
    assert check.parse_ldd('\tstatically linked\n') == []


@pytest.mark.parametrize('content, manager', [
    ('NAME="Arch Linux"\nID=arch\n', 'pacman'),
    ('ID=endeavouros\nID_LIKE=arch\n', 'pacman'),
    ('ID=ubuntu\nID_LIKE=debian\n', 'apt'),
    ('ID=linuxmint\nID_LIKE="ubuntu debian"\n', 'apt'),
    ('ID=fedora\n', 'dnf'),
    ('ID="opensuse-tumbleweed"\nID_LIKE="opensuse suse"\n', 'zypper'),
    ('ID=gentoo\n', None),
])
def test_package_manager_from_os_release(tmp_path, content, manager):
    os_release = tmp_path / 'os-release'
    os_release.write_text(content)
    assert check.package_manager(str(os_release)) == manager
    assert check.package_manager(str(tmp_path / 'missing')) is None


def make_install(folder):
    """An install folder with the programs, a few libraries and a soname symlink (skipped - ldd follows it)."""
    os.makedirs(os.path.join(folder, 'lib', 'wx'))
    for relative in ['pfeMAME', 'pfemame_updater', os.path.join('lib', 'wx', '_core.so'),
                     os.path.join('lib', 'wx', 'libwx_gtk3u_core-3.2.so.0'), os.path.join('lib', 'library.zip')]:
        with open(os.path.join(folder, relative), 'w') as f:
            f.write('x')


def test_find_missing_lists_what_needs_each_library(tmp_path):
    make_install(str(tmp_path))
    fake_ldd = {os.path.join('lib', 'wx', '_core.so'): LDD_OUTPUT,
                os.path.join('lib', 'wx', 'libwx_gtk3u_core-3.2.so.0'): '\tlibnotify.so.4 => not found\n'}
    checked = []

    def run_ldd(path):
        relative = os.path.relpath(path, str(tmp_path))
        checked.append(relative)
        return fake_ldd.get(relative, '')

    missing = check.find_missing(str(tmp_path), run_ldd=run_ldd, find_library=lambda name: None)

    assert sorted(checked) == sorted(['pfeMAME', 'pfemame_updater', os.path.join('lib', 'wx', '_core.so'),
                                      os.path.join('lib', 'wx', 'libwx_gtk3u_core-3.2.so.0')])   # not library.zip
    assert sorted(missing['libnotify.so.4']) == [os.path.join('lib', 'wx', '_core.so'),
                                                 os.path.join('lib', 'wx', 'libwx_gtk3u_core-3.2.so.0')]
    assert missing['libSDL2-2.0.so.0'] == [os.path.join('lib', 'wx', '_core.so')]
    assert 'sound' in missing['libportaudio.so.2'][0]       # loaded with ctypes, so found by name instead of ldd


def test_nothing_missing(tmp_path):
    make_install(str(tmp_path))
    missing = check.find_missing(str(tmp_path), run_ldd=lambda path: '', find_library=lambda name: 'libportaudio.so.2')
    assert missing == {}
    assert 'every library pfeMAME needs was found' in check.report(missing, 'pacman')


def test_report_gives_the_install_command_for_the_distro():
    missing = {'libnotify.so.4': ['lib/wx/_core.so'], 'libportaudio.so.2': ['sound'], 'libodd.so.1': ['lib/x.so']}
    text = check.report(missing, 'pacman')
    assert 'sudo pacman -S libnotify portaudio' in text
    assert 'libodd.so.1' in text and 'search your package manager' in text

    text = check.report(missing, None)                      # unknown distro: every manager's name for each library
    assert 'apt: libnotify4' in text and 'pacman: libnotify' in text and 'dnf: libnotify' in text


def test_every_known_library_has_a_package_for_every_manager():
    for soname, packages in check.PACKAGES.items():
        assert len(packages) == len(check.MANAGERS) and all(packages), soname


def test_startup_failure_shows_the_hidden_cause_and_respects_no_dialog(monkeypatch, capsys):
    monkeypatch.setattr(check, 'find_missing', lambda folder: {})
    monkeypatch.setattr(check, 'package_manager', lambda: 'apt')
    dialogs = []
    monkeypatch.setattr(check, 'show_dialog', dialogs.append)
    monkeypatch.setenv('DISPLAY', ':0')
    try:
        try:
            raise OSError('libfoo.so: ELF load command address/offset not page-aligned')
        except OSError as inner:
            raise ImportError('Error importing numpy: you should not try to import numpy from its source') from inner
    except ImportError as error:
        monkeypatch.setenv('PFEMAME_NO_DIALOG', '1')
        check.report_startup_failure(error)
        assert dialogs == []                                # the release script's start check: no dialog
        monkeypatch.delenv('PFEMAME_NO_DIALOG')
        check.report_startup_failure(error)
    text = capsys.readouterr().err
    assert 'Caused by: libfoo.so: ELF load command address/offset not page-aligned' in text
    assert 'something else - please report the error above' in text
    assert len(dialogs) == 1
