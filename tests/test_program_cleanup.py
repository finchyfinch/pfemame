"""program_cleanup: removing program files an older version left in the install folder's lib/ folder."""
import os
import shutil
import sys

import pytest

import program_cleanup


def make_build_lib(lib_dir, extra=60):
    """A lib/ folder like a build's: library.zip, a package folder and enough files to pass the completeness check."""
    os.makedirs(os.path.join(lib_dir, 'wx', 'locale'))
    for relative in ['library.zip', os.path.join('wx', '_core.so'), os.path.join('wx', 'locale', 'de.mo')] + \
            [f'module_{i}.so' for i in range(extra)]:
        with open(os.path.join(lib_dir, relative), 'w') as f:
            f.write('x')


def write(path, text='old'):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(text)


def test_removes_only_what_the_build_does_not_ship(tmp_path):
    install = tmp_path / 'pfeMAME'
    lib = str(install / 'lib')
    make_build_lib(lib)
    os.makedirs(os.path.join(lib, 'wx', 'empty_but_shipped'))
    program_cleanup.write_manifest(lib)

    # An older version's leftovers, and files outside lib/ (user data in portable mode) that must never be touched
    write(os.path.join(lib, 'opencv_python.libs', 'libQt5Core-9088e21b.so.5'))
    write(os.path.join(lib, 'cv2', 'qt', 'fonts', 'DejaVuSans.ttf'))
    write(os.path.join(lib, 'wx', '_aui.so'))
    write(os.path.join(lib, 'libwx_gtk3u_core-3.2.so.0'))
    write(str(install / 'pfemame.ini'), 'user settings')
    write(str(install / 'favorites.dat'), 'user favourites')

    removed = program_cleanup.remove_old_program_files(lib)

    assert not os.path.exists(os.path.join(lib, 'opencv_python.libs'))      # emptied folders go too
    assert not os.path.exists(os.path.join(lib, 'cv2'))
    assert not os.path.exists(os.path.join(lib, 'wx', '_aui.so'))
    assert not os.path.exists(os.path.join(lib, 'libwx_gtk3u_core-3.2.so.0'))
    for kept in ['library.zip', 'module_59.so', os.path.join('wx', '_core.so'), os.path.join('wx', 'locale', 'de.mo'),
                 program_cleanup.MANIFEST_NAME]:
        assert os.path.isfile(os.path.join(lib, kept)), kept
    assert os.path.isdir(os.path.join(lib, 'wx', 'empty_but_shipped'))      # a folder the build ships stays
    assert (install / 'pfemame.ini').read_text() == 'user settings'
    assert (install / 'favorites.dat').read_text() == 'user favourites'
    assert len(removed) == 4 + 4                                             # 4 files + 4 emptied folders

    assert program_cleanup.remove_old_program_files(lib) == []               # nothing left to do the next time


def test_does_nothing_without_a_list(tmp_path):
    lib = str(tmp_path / 'lib')
    make_build_lib(lib)                                     # an older build: no pfemame_files.txt
    write(os.path.join(lib, 'leftover.so'))
    assert program_cleanup.remove_old_program_files(lib) == []
    assert os.path.exists(os.path.join(lib, 'leftover.so'))


@pytest.mark.parametrize('damage', ['truncated', 'no library.zip'])
def test_does_nothing_with_a_damaged_list(tmp_path, damage):
    lib = str(tmp_path / 'lib')
    make_build_lib(lib)
    program_cleanup.write_manifest(lib)
    manifest = os.path.join(lib, program_cleanup.MANIFEST_NAME)
    with open(manifest) as f:
        lines = f.read().splitlines()
    if damage == 'truncated':
        lines = lines[:10]
    else:
        lines = [line for line in lines if line != 'library.zip']
    with open(manifest, 'w') as f:
        f.write('\n'.join(lines) + '\n')

    assert program_cleanup.remove_old_program_files(lib) == []
    assert os.path.exists(os.path.join(lib, 'module_59.so'))


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows file names ignore case')
def test_windows_file_name_case_does_not_matter(tmp_path):
    lib = str(tmp_path / 'lib')
    make_build_lib(lib)
    program_cleanup.write_manifest(lib)
    os.rename(os.path.join(lib, 'module_1.so'), os.path.join(lib, 'MODULE_1.SO'))   # e.g. an update changed the case
    program_cleanup.remove_old_program_files(lib)
    assert os.path.exists(os.path.join(lib, 'MODULE_1.SO'))


def test_symlinks_are_listed_and_never_followed(tmp_path):
    lib = str(tmp_path / 'lib')
    make_build_lib(lib)
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'keep_me.txt').write_text('not part of pfeMAME')
    try:
        os.symlink('module_0.so', os.path.join(lib, 'module_0.so.1'))                # a library's soname link
        program_cleanup.write_manifest(lib)
        os.symlink(str(outside), os.path.join(lib, 'old_linked_folder'), target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip('symbolic links not available here')

    program_cleanup.remove_old_program_files(lib)

    assert os.path.islink(os.path.join(lib, 'module_0.so.1'))               # on the list - kept
    assert not os.path.lexists(os.path.join(lib, 'old_linked_folder'))      # not on the list - the link goes...
    assert (outside / 'keep_me.txt').read_text() == 'not part of pfeMAME'   # ...but never what it points to


def installed(tmp_path, monkeypatch, platform='linux'):
    """Pretend to be an installed (frozen) build in tmp_path/pfeMAME; returns its lib folder."""
    install = tmp_path / 'pfeMAME'
    lib = str(install / 'lib')
    make_build_lib(lib)
    program_cleanup.write_manifest(lib)
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', str(install / 'pfeMAME'))
    monkeypatch.setattr(sys, 'platform', platform)
    monkeypatch.setattr(sys, 'argv', ['pfeMAME'])
    monkeypatch.setattr(program_cleanup, '_messages', [])
    return lib


def test_start_up_cleanup_runs_once_per_version(tmp_path, monkeypatch, caplog):
    lib = installed(tmp_path, monkeypatch)
    write(os.path.join(lib, 'backports', '__init__.pyc'))           # e.g. 3.9.2's Python 3.14 file
    program_cleanup.clean_before_imports()
    assert not os.path.exists(os.path.join(lib, 'backports'))
    assert os.path.isfile(os.path.join(lib, program_cleanup.DONE_NAME))

    import logging
    with caplog.at_level(logging.INFO):
        program_cleanup.log_results(logging.getLogger('pfemame-test'))
    assert 'Removed 2 program file(s) / folder(s)' in caplog.text

    write(os.path.join(lib, 'new_leftover.so'))
    program_cleanup.clean_before_imports()                           # same list: skipped (normal starts stay fast)
    assert os.path.exists(os.path.join(lib, 'new_leftover.so'))

    program_cleanup.write_manifest(lib)                              # an update brings a new list...
    manifest = os.path.join(lib, program_cleanup.MANIFEST_NAME)
    with open(manifest) as f:
        lines = [line for line in f.read().splitlines() if line != 'new_leftover.so']
    with open(manifest, 'w') as f:
        f.write('\n'.join(lines) + '\n')
    os.utime(manifest, ns=(1, 1))
    program_cleanup.clean_before_imports()                           # ...so it runs again
    assert not os.path.exists(os.path.join(lib, 'new_leftover.so'))
    assert os.path.isfile(os.path.join(lib, program_cleanup.DONE_NAME))  # never deletes its own marker


def test_a_marker_copied_from_another_folder_does_not_count(tmp_path, monkeypatch):
    """The release script's start check runs the built program, so build/lib gets a marker; copied with the files
    (cp -a keeps the list's time exactly) it used to make the installed copy skip its clean-up."""
    lib = installed(tmp_path, monkeypatch)
    program_cleanup.clean_before_imports()                           # cleaned "in the build folder"...
    copy = tmp_path / 'copy' / 'pfeMAME'
    shutil.copytree(str(tmp_path / 'pfeMAME'), str(copy), copy_function=shutil.copy2)   # ...copied, times kept
    os.utime(os.path.join(str(copy), 'lib', program_cleanup.MANIFEST_NAME),
             ns=(os.stat(os.path.join(lib, program_cleanup.MANIFEST_NAME)).st_atime_ns,
                 os.stat(os.path.join(lib, program_cleanup.MANIFEST_NAME)).st_mtime_ns))
    write(os.path.join(str(copy), 'lib', 'backports', '__init__.pyc'))           # the old version's leftover
    monkeypatch.setattr(sys, 'executable', str(copy / 'pfeMAME'))
    program_cleanup.clean_before_imports()
    assert not os.path.exists(os.path.join(str(copy), 'lib', 'backports'))


@pytest.mark.parametrize('case', ['source', 'macOS', 'multiprocessing worker'])
def test_start_up_cleanup_does_nothing(tmp_path, monkeypatch, case):
    lib = installed(tmp_path, monkeypatch, platform='darwin' if case == 'macOS' else 'linux')
    if case == 'source':
        monkeypatch.delattr(sys, 'frozen', raising=False)
    if case == 'multiprocessing worker':
        monkeypatch.setattr(sys, 'argv', ['pfeMAME', '--multiprocessing-fork', 'parent_pid=1'])
    write(os.path.join(lib, 'leftover.so'))
    program_cleanup.clean_before_imports()
    assert os.path.exists(os.path.join(lib, 'leftover.so'))
    assert not os.path.exists(os.path.join(lib, program_cleanup.DONE_NAME))
