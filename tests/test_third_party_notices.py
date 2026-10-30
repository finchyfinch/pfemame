"""The third-party licence notices written into every frozen build (tools/third_party_notices.py)."""
import os
import zipfile

from tools.third_party_notices import write_third_party_licenses, top_level_names, FOLDER_NAME, NOTICES_FILE


def make_build(tmp_path, folders, zipped=()):
    lib = tmp_path / 'lib'
    lib.mkdir()
    for folder in folders:
        (lib / folder).mkdir()
    with zipfile.ZipFile(lib / 'library.zip', 'w') as archive:
        for name in zipped:
            archive.writestr(f'{name}/__init__.pyc', b'')
    return tmp_path


def test_top_level_names_include_zipped_modules_and_extensions(tmp_path):
    build = make_build(tmp_path, ['wx', '_cffi_backend.cp314-win_amd64.pyd'], zipped=['docx'])
    assert {'wx', '_cffi_backend', 'docx'} <= top_level_names(str(build / 'lib'))


def test_notices_list_bundled_packages_and_copy_their_licences(tmp_path):
    build = make_build(tmp_path, ['wx', 'PIL'])
    write_third_party_licenses(str(build))

    folder = build / FOLDER_NAME
    notices = (folder / NOTICES_FILE).read_text(encoding='utf-8')
    assert 'Python ' in notices
    assert 'wxPython' in notices
    assert 'pillow' in notices.lower()
    assert 'Gregory Ember' in notices
    copied = os.listdir(folder)
    assert any(name.lower().startswith('wxpython-') for name in copied)
    assert any(name.lower().startswith('pillow-') for name in copied)


def test_notices_leave_out_packages_that_are_not_in_the_build(tmp_path):
    build = make_build(tmp_path, ['wx'])
    write_third_party_licenses(str(build))
    notices = (build / FOLDER_NAME / NOTICES_FILE).read_text(encoding='utf-8')
    assert 'pillow' not in notices.lower()
    assert 'pytest' not in notices.lower()
