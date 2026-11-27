"""
Release archives: the Windows zip made by tools/make_windows_zip.py, the Linux .tar.gz the updater can now install,
and how the update check chooses between a release's zip and tar.gz.
"""
import io
import json
import os
import sys
import tarfile
import types
import zipfile

import pytest

import fast_download
import updater_client

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tools'))
import make_windows_zip     # noqa: E402  (in the tools folder)


# ----------------------------------------------------------------------------------------------- choosing the archive
def test_the_zip_is_chosen_when_a_release_also_has_a_tar_gz():
    page = 'pfemame_linux_v3.12.0.tar.gz ... pfemame_linux_v3.12.0.zip ... pfemame_linux_v3.11.1.zip'
    version, url = updater_client.parse_versions(page, 'linux')
    assert version == '3.12.0' and url.endswith('/pfemame_linux_v3.12.0.zip/download')


def test_a_release_with_only_a_tar_gz_is_still_found():
    version, url = updater_client.parse_versions('pfemame_linux_v3.12.0.tar.gz pfemame_linux_v3.11.1.zip', 'linux')
    assert version == '3.12.0' and url.endswith('/pfemame_linux_v3.12.0.tar.gz/download')


@pytest.mark.parametrize('file_name, expected', [('pfemame_linux_v3.12.0.tar.gz', '3.12.0'),
                                                 ('pfemame_linux_v3.12.0.zip', '3.12.0'),
                                                 ('pfemame_linux_v3.12.0.deb', None)])
def test_best_release_accepts_a_tar_gz(monkeypatch, file_name, expected):
    answer = {'platform_releases': {'linux': {'filename': f'/{file_name}', 'sha256sum': 'ab'}}}
    monkeypatch.setattr(fast_download, '_open', lambda *args, **kwargs: io.BytesIO(json.dumps(answer).encode()))
    release = fast_download.get_latest_release('linux')
    assert (release['version'] if release else None) == expected


# ------------------------------------------------------------------------------------------ installing from a tar.gz
@pytest.fixture
def updater(monkeypatch, wx_app):
    import pfemame_updater
    monkeypatch.setattr(pfemame_updater.wx, 'CallAfter', lambda *args, **kwargs: None)
    return pfemame_updater


def make_tar(path, members):
    """members: (name, text) for a file, (name, None, link target) for a symlink."""
    with tarfile.open(path, 'w:gz') as archive:
        for name, text, *link in members:
            info = tarfile.TarInfo(name)
            if link:
                info.type, info.linkname = tarfile.SYMTYPE, link[0]
                archive.addfile(info)
            else:
                data = text.encode()
                info.size, info.mode = len(data), 0o755
                archive.addfile(info, io.BytesIO(data))


@pytest.mark.parametrize('use_python_filter', [True, False])
def test_a_tar_gz_update_is_extracted_with_its_symlinks(updater, tmp_path, monkeypatch, use_python_filter):
    if not use_python_filter:
        monkeypatch.setattr(updater, 'TAR_DATA_FILTER', False)     # Older Python without the 'data' filter
    archive = tmp_path / 'pfemame_linux_v3.12.0.tar.gz'
    make_tar(archive, [('pfemame_v3.12.0/pfeMAME', 'program'),
                       ('pfemame_v3.12.0/lib/libtiff.so.5.7.0', 'library'),
                       ('pfemame_v3.12.0/lib/libtiff.so.5', None, 'libtiff.so.5.7.0')])
    frame = types.SimpleNamespace(temp_dir=str(tmp_path / 'temp'), _show_progress=None)

    folder = updater.UpdaterFrame.extract_archive(frame, str(archive))

    assert os.path.basename(folder) == 'pfemame_v3.12.0'                 # The wrapper folder is what gets installed
    link = os.path.join(folder, 'lib', 'libtiff.so.5')
    if os.name != 'nt':                                                  # Windows can't always make symlinks
        assert os.path.islink(link) and os.readlink(link) == 'libtiff.so.5.7.0'
        assert os.access(os.path.join(folder, 'pfeMAME'), os.X_OK)
    with open(link) as file:
        assert file.read() == 'library'


@pytest.mark.parametrize('use_python_filter', [True, False])
@pytest.mark.parametrize('members', [[('../outside.txt', 'x')],
                                     [('pfemame/link', None, '../../outside.txt')],
                                     [('pfemame/link', None, '/etc/passwd')]])
def test_a_tar_gz_cannot_write_outside_its_folder(updater, tmp_path, monkeypatch, members, use_python_filter):
    if not use_python_filter:
        monkeypatch.setattr(updater, 'TAR_DATA_FILTER', False)
    archive_path = tmp_path / 'bad.tar.gz'
    make_tar(archive_path, members)
    target = tmp_path / 'extract'
    target.mkdir()
    with tarfile.open(archive_path) as archive:
        with pytest.raises((ValueError, tarfile.TarError)):
            for member in archive.getmembers():
                updater.extract_tar_member(archive, member, str(target))
    assert not (tmp_path / 'outside.txt').exists() and not (target / 'pfemame' / 'link').exists()


def test_a_tar_gz_with_an_absolute_path_stays_in_its_folder(updater, tmp_path):
    archive_path = tmp_path / 'bad.tar.gz'
    make_tar(archive_path, [('/pfemame_absolute_test.txt', 'x')])
    target = tmp_path / 'extract'
    target.mkdir()
    with tarfile.open(archive_path) as archive:
        try:
            for member in archive.getmembers():
                updater.extract_tar_member(archive, member, str(target))
        except (ValueError, tarfile.TarError):
            pass                                                # Refusing it is fine too
    assert not os.path.exists(os.path.abspath('/pfemame_absolute_test.txt'))


# ------------------------------------------------------------------------------------------------- the Windows zip
def make_build(folder):
    for name, text in [('pfeMAME.exe', 'exe'), ('pfemame_updater.exe', 'exe'), ('catver.ini', 'cat'),
                       (os.path.join('lib', 'library.zip'), 'lib'), (os.path.join('lib', 'pfemame_files.done'), ''),
                       (os.path.join('images', 'icons', 'a.png'), 'png')]:
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


def test_windows_zip_has_the_published_layout(tmp_path):
    make_build(tmp_path / 'build')
    zip_path = tmp_path / 'dist' / 'pfemame_windows_v9.9.9.zip'

    make_windows_zip.make_zip(str(tmp_path / 'build'), str(zip_path))

    with zipfile.ZipFile(zip_path) as archive:
        names = archive.namelist()
        assert archive.getinfo('pfeMAME.exe').compress_type == zipfile.ZIP_DEFLATED
    assert {'pfeMAME.exe', 'pfemame_updater.exe', 'catver.ini', 'lib/', 'lib/library.zip', 'images/',
            'images/icons/', 'images/icons/a.png'} == set(names)                # Top level, folders listed, '/' paths
    assert not os.path.exists(str(zip_path) + '.part')


def test_windows_zip_needs_a_finished_build(tmp_path):
    (tmp_path / 'build').mkdir()
    (tmp_path / 'build' / 'pfeMAME.exe').write_text('exe')
    zip_path = tmp_path / 'dist' / 'pfemame_windows_v9.9.9.zip'
    with pytest.raises(FileNotFoundError, match='pfemame_updater.exe'):
        make_windows_zip.make_zip(str(tmp_path / 'build'), str(zip_path))
    assert not zip_path.exists()


def test_windows_zip_name_uses_the_app_version():
    import pfemame
    assert make_windows_zip.version() == pfemame.__version__
