"""INI files, user data folder, backups, views, versions, MAME paths and the system-program INI swap."""
import gettext
import os
import sys
import zipfile

import pytest

import app_paths
import backup
import mame_paths
import updater_client
import views


# ------------------------------------------------------------------------------------------------------------ versions
def test_compare_version(wx_app):
    import functions
    assert functions.compare_version('3.10.0', '3.9.1') == 1
    assert functions.compare_version('3.9', '3.9.0') == 0
    assert functions.compare_version('0.288', '0.289') == -1


def test_newest_version_on_files_page_wins():
    page = 'pfemame_windows_v3.8.1.zip ... pfemame_windows_v3.10.0.zip ... pfemame_linux_v4.0.0.zip'
    version, url = updater_client.parse_versions(page, 'windows')
    assert version == '3.10.0' and url.endswith('pfemame_windows_v3.10.0.zip/download')
    assert updater_client.parse_versions('nothing here', 'mac') == (None, None)


# --------------------------------------------------------------------------------------------------------------- views
def test_view_keys_work_in_every_language():
    german = gettext.translation('base', localedir='locales', languages=['de']).gettext
    labels = views.view_labels(german)
    assert labels[0] == 'Alle'
    assert [views.normalize_view_key(label, german) for label in labels] == views.VIEW_KEYS
    assert views.normalize_view_key('Favorites', german) == 'Favorites'      # new INI files store the key
    assert views.normalize_view_key('rubbish', german) == 'All'
    assert views.VIEW_FILTERS['Watchlist'] == (views.INDEX_FAVORITE, '2')


# ---------------------------------------------------------------------------------------------------------- INI files
def test_ini_created_when_missing_and_cached(data_dir, wx_app):
    import iniFile
    iniFile._invalidate_cache()
    iniFile.set_ini_file_variables([('system', 'lastviewselected', 'Favorites')])
    assert (data_dir / 'pfemame.ini').exists()
    assert iniFile.read_ini_file('system', 'lastviewselected') == 'Favorites'
    assert iniFile.read_ini_file('preferences', 'tilesize') == 'Medium'       # defaults written too
    assert iniFile.read_ini_file('nope', 'nothing', 'fallback') == 'fallback'
    assert not list(data_dir.glob('*.tmp'))


def test_ini_created_before_wx_app(tmp_path):
    # pfemame --language on the first run saves the language (creating pfemame.ini) before wx.App exists.  Run in a
    # new process, as this one has a wx.App already.
    import subprocess
    script = ('import sys, app_paths, iniFile\n'
              'app_paths.migrate_data = lambda *args, **kwargs: []\n'
              "iniFile.set_ini_file_variables([('preferences', 'language', 'de')])\n")
    source = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    result = subprocess.run([sys.executable, '-c', script], cwd=source, capture_output=True, text=True,
                            env={**os.environ, 'PFEMAME_DATA_DIR': str(tmp_path)}, **mame_paths.NO_CONSOLE)
    assert result.returncode == 0, result.stderr
    text = (tmp_path / 'pfemame.ini').read_text(encoding='utf-8')
    assert 'language = de' in text and 'tilesize = Medium' in text
    assert 'missing_game_color = (255, 153, 153, 255)' in text
    assert 'text_color' not in text and 'button_background_color' not in text    # These follow the system theme


def test_ini_duplicate_settings_are_read_and_merged(data_dir, wx_app):
    # A setting typed twice, or in capitals, by hand used to make every read raise DuplicateOptionError
    import iniFile
    iniFile._invalidate_cache()
    (data_dir / 'pfemame.ini').write_text('[preferences]\nLanguage = de\ntilesize = Small\nlanguage = es\n'
                                          'tilesize = Large\n', encoding='utf-8')
    assert iniFile.read_ini_file('preferences', 'language') == 'es'          # The last one wins
    assert iniFile.read_ini_file('preferences', 'tilesize') == 'Large'
    iniFile.set_ini_file_variables([('preferences', 'language', 'fr')])
    text = (data_dir / 'pfemame.ini').read_text(encoding='utf-8')
    assert text.lower().count('language =') == 1 and 'language = fr' in text
    assert text.count('tilesize =') == 1 and 'tilesize = Large' in text
    assert iniFile.read_ini_file('preferences', 'language') == 'fr'


def test_ini_single_percent_is_read_and_escaped_at_next_save(data_dir, wx_app):
    # A single '%' (hand edit / older file) used to make the read raise an InterpolationError
    import iniFile
    iniFile._invalidate_cache()
    (data_dir / 'pfemame.ini').write_text('[system]\nlastromselected = 100%\nformat = x%(y)s\nmixed = a%%b%c\n'
                                          'good = 50%%\n', encoding='utf-8')
    expected = {'lastromselected': '100%', 'format': 'x%(y)s', 'mixed': 'a%b%c', 'good': '50%'}
    for key, value in expected.items():
        assert iniFile.read_ini_file('system', key) == value
    iniFile.set_ini_file_variables([('system', 'x', '1')])
    text = (data_dir / 'pfemame.ini').read_text(encoding='utf-8')
    assert 'lastromselected = 100%%\n' in text and 'mixed = a%%b%%c\n' in text and 'good = 50%%\n' in text
    for key, value in expected.items():
        assert iniFile.read_ini_file('system', key) == value


@pytest.mark.parametrize('first_line', ['# My settings\n', ''])
def test_ini_saved_with_a_bom_is_read_and_saved_without_it(data_dir, wx_app, first_line):
    # A BOM used to make the whole file unreadable, and a save dropped the [preferences] settings after it
    import iniFile
    iniFile._invalidate_cache()
    ini = data_dir / 'pfemame.ini'
    ini.write_bytes(('\ufeff' + first_line + '[preferences]\r\ntilesize = Large\r\n[path]\r\nmame_executable = '
                     'C:\\Jeux\\Émulateurs\\mame.exe\r\n').encode('utf-8'))
    assert iniFile.read_ini_file('preferences', 'tilesize') == 'Large'
    assert iniFile.read_ini_file('path', 'mame_executable') == 'C:\\Jeux\\Émulateurs\\mame.exe'
    iniFile.set_ini_file_variables([('system', 'x', '1')])
    assert not ini.read_bytes().startswith(b'\xef\xbb\xbf')
    assert iniFile.read_ini_file('preferences', 'tilesize') == 'Large'
    assert iniFile.read_ini_file('path', 'mame_executable') == 'C:\\Jeux\\Émulateurs\\mame.exe'


def test_ini_in_the_system_encoding_is_read_and_saved_as_utf8(data_dir, monkeypatch, wx_app):
    import iniFile
    monkeypatch.setattr(iniFile, '_fallback_encoding', lambda: 'cp1252')      # Windows' "ANSI", on any system
    iniFile._invalidate_cache()
    ini = data_dir / 'pfemame.ini'
    ini.write_bytes('[path]\nmame_executable = C:\\Jeux\\Émulateurs\\mame.exe\n'.encode('cp1252'))
    assert iniFile.read_ini_file('path', 'mame_executable') == 'C:\\Jeux\\Émulateurs\\mame.exe'
    iniFile.set_ini_file_variables([('system', 'x', '1')])
    assert 'mame_executable = C:\\Jeux\\Émulateurs\\mame.exe' in ini.read_text(encoding='utf-8')


def test_unreadable_ini_is_logged_once_and_never_overwritten(data_dir, monkeypatch, wx_app, caplog):
    import iniFile
    monkeypatch.setattr(iniFile, '_fallback_encoding', lambda: 'utf-8')       # As on Linux
    iniFile._invalidate_cache()
    ini = data_dir / 'pfemame.ini'
    original = b'[path]\nmame_executable = C:\\Jeux\\\xc9mulateurs\\mame.exe\n'
    ini.write_bytes(original)
    with caplog.at_level('ERROR', logger='>'):
        for _ in range(3):
            assert iniFile.read_ini_file('path', 'mame_executable', 'default') == 'default'
        assert len([r for r in caplog.records if 'default settings are being used' in r.getMessage()]) == 1
        iniFile.set_ini_file_variables([('system', 'x', '1')])                # No crash, and the file is kept
        assert any('were not saved' in r.getMessage() for r in caplog.records)
    assert ini.read_bytes() == original


def test_ini_save_keeps_everything_the_reader_sees(data_dir, wx_app):
    # The save used to read the file by its own rules: these hand-edited lines were dropped or moved
    import configparser
    import iniFile

    def settings() -> dict:
        parser = configparser.ConfigParser(allow_no_value=True, strict=False)
        parser.read(data_dir / 'pfemame.ini', encoding='utf-8')
        return {section: dict(parser.items(section, raw=True)) for section in parser.sections()}

    iniFile._invalidate_cache()
    (data_dir / 'pfemame.ini').write_text('# My own header\n'
                                          '[preferences]\ntilesize = Large\n'
                                          '[path] \n'
                                          'mame_ini: C:/mame/mame.ini\n'
                                          '; old_setting = 1\n'
                                          '  # an indented note\n'
                                          'flag\n'
                                          'multi = first\n    second\n'
                                          '[folders]\nvideo = C:/videos\n', encoding='utf-8')
    before = settings()
    assert before['path']['mame_ini'] == 'C:/mame/mame.ini' and before['path']['multi'] == 'first\nsecond'
    iniFile.set_ini_file_variables([('system', 'x', '1')])
    after = settings()
    assert after.pop('system') == {'x': '1'}
    assert after == before
    text = (data_dir / 'pfemame.ini').read_text(encoding='utf-8')
    assert '; old_setting = 1\n' in text and '# an indented note\n' in text and 'mame_ini = C:/mame/mame.ini\n' in text
    assert iniFile.read_ini_file('path', 'flag', 'default') == 'default'      # A name without a value


def test_one_set_of_defaults_is_used_everywhere(data_dir, wx_app):
    # The defaults used to be set separately in create_ini_file, the Preferences window and each read, and differed
    import configparser
    import re
    import iniFile
    import preferences_model
    defaults = preferences_model.PFEMAME_DEFAULTS
    iniFile._invalidate_cache()
    iniFile.create_ini_file()
    parser = configparser.RawConfigParser()
    parser.read(data_dir / 'pfemame.ini', encoding='utf-8')
    for section, settings in defaults.items():
        for key, value in settings.items():
            assert parser.get(section, key) == value, (section, key)
    assert {option.ini_key for option in preferences_model.PFEMAME_OPTIONS} <= set(defaults['preferences'])

    # A setting missing from an older pfemame.ini reads as its default
    (data_dir / 'pfemame.ini').write_text('[preferences]\ntilesize = Large\n', encoding='utf-8')
    assert iniFile.read_ini_file('preferences', 'showgameicons') == 'True'
    assert iniFile.read_ini_file('preferences', 'dayscheckcache') == '50'
    assert iniFile.read_ini_file('preferences', 'tilesize') == 'Large'
    assert iniFile.read_ini_file('preferences', 'language') == ''              # Not in the table
    assert iniFile.read_ini_file('preferences', 'showgameicons', 'given') == 'given'

    # ... so no read should give its own default for these settings, or they could differ again
    source = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    call = re.compile(r"read_ini_file\(\s*'(\w+)'\s*,\s*'(\w+)'\s*,", re.S)
    own_defaults = []
    for name in os.listdir(source):
        if name.endswith('.py'):
            with open(os.path.join(source, name), encoding='utf-8') as f:
                own_defaults += [f'{name}: {section}.{key}' for section, key in call.findall(f.read())
                                 if key in defaults.get(section, {})]
    assert own_defaults == []


def test_ini_save_that_fails_is_logged_not_raised(data_dir, wx_app, caplog):
    # A read-only pfemame.ini used to raise from set_ini_file_variables - e.g. stopping the main window closing
    import stat
    import iniFile
    iniFile._invalidate_cache()
    assert iniFile.set_ini_file_variables([('system', 'x', '1')]) is True
    ini = data_dir / 'pfemame.ini'
    original = ini.read_bytes()
    os.chmod(ini, stat.S_IREAD)
    try:
        if os.access(ini, os.W_OK):
            pytest.skip('running as root - every file is writable')
        with caplog.at_level('ERROR', logger='>'):
            assert iniFile.set_ini_file_variables([('system', 'x', '2')]) is False
        assert any('were not saved' in record.getMessage() for record in caplog.records)
        assert ini.read_bytes() == original
    finally:
        os.chmod(ini, stat.S_IREAD | stat.S_IWRITE)


def test_ini_saves_at_the_same_time_keep_both_changes(data_dir, wx_app):
    import threading
    import iniFile
    iniFile._invalidate_cache()
    iniFile.set_ini_file_variables([('system', 'start', '1')])

    def save(name):
        for count in range(20):
            assert iniFile.set_ini_file_variables([('system', f'{name}{count}', str(count))])

    threads = [threading.Thread(target=save, args=(name,)) for name in ('a', 'b')]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    for name in ('a', 'b'):
        for count in range(20):
            assert iniFile.read_ini_file('system', f'{name}{count}') == str(count)


def test_unused_settings_are_not_written_to_a_new_ini(data_dir, wx_app):
    import iniFile
    iniFile._invalidate_cache()
    iniFile.create_ini_file()
    text = (data_dir / 'pfemame.ini').read_text(encoding='utf-8')
    for name in ('usemultiprocessor', 'checkforwayland', 'artworkdisable'):
        assert f'\n{name} =' not in text
    assert '\ndisableartwork = False\n' in text


@pytest.mark.parametrize('artworkdisable, disableartwork, expected', [
    ('True', 'False', 'True'), ('False', 'False', 'False'), ('False', 'True', 'True'), (None, 'False', 'False')])
def test_old_video_tab_artwork_setting_is_moved(data_dir, wx_app, artworkdisable, disableartwork, expected):
    # The Video tab's 'Disable the display of artwork' (artworkdisable) was removed - 'Disable Artwork for all ROMs'
    # (disableartwork) takes it over
    import iniFile
    iniFile._invalidate_cache()
    old = f'artworkdisable = {artworkdisable}\n' if artworkdisable is not None else ''
    (data_dir / 'pfemame.ini').write_text(f'[preferences]\n{old}disableartwork = {disableartwork}\n', encoding='utf-8')
    before = (data_dir / 'pfemame.ini').read_bytes()
    iniFile.convert_old_settings()
    assert iniFile.read_ini_file('preferences', 'disableartwork') == expected
    assert iniFile.read_ini_file('preferences', 'artworkdisable') != 'True'
    if artworkdisable != 'True':
        assert (data_dir / 'pfemame.ini').read_bytes() == before        # Nothing to move - the file isn't written
    iniFile.convert_old_settings()                                      # Running again changes nothing
    assert iniFile.read_ini_file('preferences', 'disableartwork') == expected


def test_new_and_saved_ini_look_the_same(data_dir, wx_app):
    # create_ini_file and set_ini_file_variables used to build the file text separately (and wrote comments
    # differently) - now both use _ini_text
    import iniFile
    iniFile._invalidate_cache()
    iniFile.create_ini_file()
    new = (data_dir / 'pfemame.ini').read_text(encoding='utf-8')
    assert new.startswith('# pfemame.ini - pfeMAME settings\n# Modify values as needed.\n\n[preferences]\n'
                          '# Preferences section - UI, fonts, colors\n')
    iniFile.set_ini_file_variables([('preferences', 'tilesize', 'Medium')])     # The value it already has
    assert (data_dir / 'pfemame.ini').read_text(encoding='utf-8') == new


@pytest.mark.parametrize('line, expected, warned', [
    ('iconsize = 24', 24, False), ('iconsize = abc', 16, True), ('iconsize =', 16, True), ('iconsize = 12.5', 16, True),
    ('iconsize = 4', 16, True), ('iconsize = 300', 16, True), ('', 16, False)])
def test_read_ini_int(data_dir, wx_app, caplog, line, expected, warned):
    # A setting that isn't a whole number used to stop pfeMAME starting (e.g. int('abc') for a font size)
    import iniFile
    iniFile._invalidate_cache()
    iniFile._reported_values.clear()
    (data_dir / 'pfemame.ini').write_text(f'[preferences]\n{line}\n', encoding='utf-8')
    with caplog.at_level('WARNING', logger='>'):
        for _ in range(2):
            assert iniFile.read_ini_int('preferences', 'iconsize', low=8, high=256) == expected
    assert len([r for r in caplog.records if 'iconsize' in r.getMessage()]) == (1 if warned else 0)   # Once


def test_bad_number_settings_use_the_defaults(data_dir, wx_app):
    import wx
    import functions
    import iniFile
    iniFile._invalidate_cache()
    (data_dir / 'pfemame.ini').write_text('[preferences]\nglobal_font_normal_pointsize = abc\n'
                                          'global_font_bold_pointsize = 0\nglobal_font_normal_weight = heavy\n'
                                          'joystick_polling_freq = fast\n', encoding='utf-8')
    fonts = functions.get_font_info()
    assert fonts.global_font_normal.IsOk() and fonts.global_font_normal.GetPointSize() == 10
    assert fonts.global_font_normal.GetWeight() == wx.FONTWEIGHT_NORMAL
    assert fonts.global_font_bold.IsOk() and fonts.global_font_bold.GetPointSize() == 10
    assert iniFile.read_ini_int('preferences', 'joystick_polling_freq', low=1, high=1000) == 20


def test_ini_external_edit_is_picked_up(data_dir, wx_app):
    import iniFile
    iniFile._invalidate_cache()
    iniFile.set_ini_file_variables([('system', 'x', '1')])
    text = (data_dir / 'pfemame.ini').read_text(encoding='utf-8').replace('x = 1', 'x = 22')
    (data_dir / 'pfemame.ini').write_text(text, encoding='utf-8')
    assert iniFile.read_ini_file('system', 'x') == '22'


def test_mame_ini_bulk_update_is_atomic(tmp_path, wx_app):
    import iniFile
    mame_ini = tmp_path / 'mame.ini'
    mame_ini.write_text('rompath     roms\nskip_gameinfo     0\n', encoding='utf-8')
    assert iniFile.set_to_mameini_bulk([('1', 'skip_gameinfo', False), ('C:\\snap', 'snapshot_directory', False)],
                                       str(mame_ini)) == 0
    assert iniFile.get_from_mameini('skip_gameinfo', str(mame_ini)) == '1'
    assert iniFile.get_from_mameini('snapshot_directory', str(mame_ini)) == 'C:\\snap'
    assert iniFile.get_from_mameini('rompath', str(mame_ini)) == 'roms'


def test_mame_ini_bulk_update_leaves_an_unreadable_file_alone(tmp_path, monkeypatch, wx_app):
    # A mame.ini that couldn't be read used to be replaced by one holding only the settings being saved
    import builtins
    import iniFile
    mame_ini = tmp_path / 'mame.ini'
    original = 'rompath     C:\\Jeux\\Rôms\nskip_gameinfo     0\n'.encode('cp1252')
    mame_ini.write_bytes(original)
    assert iniFile.set_to_mameini_bulk([('1', 'skip_gameinfo', False)], str(mame_ini)) == -1   # Not UTF-8
    assert mame_ini.read_bytes() == original

    mame_ini.write_text('rompath     roms\n', encoding='utf-8')
    real_open = builtins.open

    def locked_open(file, mode='r', *args, **kwargs):
        if str(file) == str(mame_ini) and 'r' in mode:
            raise PermissionError(13, 'locked by another program')
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, 'open', locked_open)
    assert iniFile.set_to_mameini_bulk([('1', 'skip_gameinfo', False)], str(mame_ini)) == -1
    monkeypatch.undo()
    assert mame_ini.read_text(encoding='utf-8') == 'rompath     roms\n'
    assert not list(tmp_path.glob('*.tmp'))


def test_mame_ini_bulk_update_when_last_line_has_no_line_ending(tmp_path, wx_app):
    # A new setting used to be joined onto the last line: 'skip_gameinfo 0snapshot_directory     snap'
    import iniFile
    mame_ini = tmp_path / 'mame.ini'
    mame_ini.write_text('rompath roms\nskip_gameinfo 0', encoding='utf-8')
    assert iniFile.set_to_mameini_bulk([('snap', 'snapshot_directory', False)], str(mame_ini)) == 0
    assert iniFile.get_from_mameini('skip_gameinfo', str(mame_ini)) == '0'
    assert iniFile.get_from_mameini('snapshot_directory', str(mame_ini)) == 'snap'

    mame_ini.write_text('rompath roms\nskip_gameinfo 0', encoding='utf-8')
    assert iniFile.set_to_mameini_bulk([('1', 'skip_gameinfo', False)], str(mame_ini)) == 0     # Last line changed
    assert iniFile.get_from_mameini('skip_gameinfo', str(mame_ini)) == '1'
    assert iniFile.get_from_mameini('rompath', str(mame_ini)) == 'roms'


def test_mame_ini_values_read_as_mame_reads_them(tmp_path, wx_app):
    # MAME writes a value with spaces in quotes, and reads a tab between the name and value - pfeMAME used to return
    # the quotes ('"D:/My Snaps"' isn't a folder) and nothing for a tab
    import iniFile
    mame_ini = tmp_path / 'mame.ini'
    mame_ini.write_text('rompath                   "C:/My Roms;roms"\n'
                        'snapshot_directory        "D:/My Snaps"\n'
                        'artpath\tartwork;"D:/More Art"\n'
                        'cfg_directory\t\t  cfg  \n'
                        'samplepath\n', encoding='utf-8')
    assert iniFile.get_from_mameini('rompath', str(mame_ini)) == 'C:/My Roms;roms'
    assert iniFile.get_from_mameini('snapshot_directory', str(mame_ini)) == 'D:/My Snaps'
    assert iniFile.get_from_mameini('artpath', str(mame_ini)) == 'artwork;"D:/More Art"'   # For split_mame_paths
    assert mame_paths.split_mame_paths(iniFile.get_from_mameini('artpath', str(mame_ini)))[1] == \
        os.path.normpath('D:/More Art')
    assert iniFile.get_from_mameini('cfg_directory', str(mame_ini)) == 'cfg'
    assert iniFile.get_from_mameini('samplepath', str(mame_ini)) == ''

    # pfeMAME saves a path with spaces without quotes (MAME reads that too) - it reads back the same
    assert iniFile.set_to_mameini_bulk([('D:/Other Snaps', 'snapshot_directory', False)], str(mame_ini)) == 0
    assert iniFile.get_from_mameini('snapshot_directory', str(mame_ini)) == 'D:/Other Snaps'


def test_atomic_write_leaves_no_temp_file_when_it_fails(tmp_path, monkeypatch, wx_app):
    import iniFile
    target = tmp_path / 'mame.ini'
    target.write_text('rompath roms\n', encoding='utf-8')
    with pytest.raises(UnicodeEncodeError):                 # Fails part way through writing
        iniFile.atomic_write_text(str(target), 'rompath \ud800\n')
    monkeypatch.setattr(iniFile.time, 'sleep', lambda seconds: None)

    def locked(source, destination):
        raise PermissionError(13, 'in use')

    monkeypatch.setattr(iniFile.os, 'replace', locked)      # The file stays in use
    with pytest.raises(PermissionError):
        iniFile.atomic_write_text(str(target), 'rompath other\n')
    monkeypatch.undo()
    assert target.read_text(encoding='utf-8') == 'rompath roms\n'
    assert sorted(path.name for path in tmp_path.iterdir()) == ['mame.ini']


def test_atomic_write_refuses_a_read_only_file(tmp_path, wx_app):
    # Linux used to replace a read-only file (Windows refused it)
    import stat
    import iniFile
    target = tmp_path / 'mame.ini'
    target.write_text('rompath roms\n', encoding='utf-8')
    os.chmod(target, stat.S_IREAD)
    try:
        if os.access(target, os.W_OK):
            pytest.skip('running as root - every file is writable')
        with pytest.raises(PermissionError):
            iniFile.atomic_write_text(str(target), 'rompath other\n')
        assert iniFile.set_to_mameini_bulk([('other', 'rompath', False)], str(target)) == -1
        assert target.read_text(encoding='utf-8') == 'rompath roms\n'
        assert sorted(path.name for path in tmp_path.iterdir()) == ['mame.ini']
    finally:
        os.chmod(target, stat.S_IREAD | stat.S_IWRITE)


@pytest.mark.skipif(sys.platform == 'win32', reason='Windows files have no permission bits to keep')
def test_atomic_write_keeps_the_permissions(tmp_path, wx_app):
    import stat
    import iniFile
    target = tmp_path / 'mame.ini'
    target.write_text('rompath roms\n', encoding='utf-8')
    os.chmod(target, 0o664)
    iniFile.atomic_write_text(str(target), 'rompath other\n')
    assert stat.S_IMODE(os.stat(target).st_mode) == 0o664
    new_file = tmp_path / 'ui.ini'
    iniFile.atomic_write_text(str(new_file), 'x\n')
    assert stat.S_IMODE(os.stat(new_file).st_mode) == 0o666 & ~iniFile._UMASK


def test_atomic_writes_at_the_same_time_never_mix(tmp_path, wx_app):
    # Both writes used to share one '.tmp' file
    import threading
    import iniFile
    target = tmp_path / 'pfemame.ini'
    texts = ['a' * 200_000 + '\n', 'b' * 200_000 + '\n']
    errors = []

    def write(text):
        try:
            for _ in range(10):
                iniFile.atomic_write_text(str(target), text)
        except OSError as e:
            errors.append(e)

    threads = [threading.Thread(target=write, args=(text,)) for text in texts]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert target.read_text() in texts
    assert sorted(path.name for path in tmp_path.iterdir()) == ['pfemame.ini']


def test_mame_ini_bulk_update_creates_a_missing_file(tmp_path, wx_app):
    import iniFile
    mame_ini = tmp_path / 'mame.ini'
    assert iniFile.set_to_mameini_bulk([('roms', 'rompath', False)], str(mame_ini)) == 0
    assert iniFile.get_from_mameini('rompath', str(mame_ini)) == 'roms'


# ------------------------------------------------------------------------------------------------------- data folder
def test_first_run_copies_data_and_leaves_a_note(tmp_path):
    source, target = tmp_path / 'app', tmp_path / 'profile'
    source.mkdir()
    target.mkdir()
    for name in ('pfemame.ini', 'favorites.dat', 'rom_sources.dat', 'mylist.db'):
        (source / name).write_text(name)
    (source / 'backups').mkdir()
    (source / 'backups' / 'old.zip').write_text('z')
    (source / 'catver.ini').write_text('not user data')

    copied = app_paths.migrate_data(str(source), str(target))
    assert set(copied) == {'pfemame.ini', 'favorites.dat', 'rom_sources.dat', 'mylist.db', 'backups/'}
    assert (target / 'favorites.dat').read_text() == 'favorites.dat'
    assert (source / 'favorites.dat').exists()                  # originals left in place
    assert not (target / 'catver.ini').exists()
    assert (source / app_paths.MOVED_NOTE).exists()
    assert app_paths.migrate_data(str(source), str(target)) == []    # only ever once


def test_data_folder_choice(tmp_path, monkeypatch):
    monkeypatch.delenv('PFEMAME_DATA_DIR', raising=False)
    app = tmp_path / 'app'
    app.mkdir()
    monkeypatch.setattr(app_paths, 'app_dir', lambda: str(app))
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(app_paths, 'platform_data_dir', lambda: str(tmp_path / 'profile'))
    assert app_paths._choose_data_dir() == str(tmp_path / 'profile')     # installed build
    (app / app_paths.PORTABLE_MARKER).write_text('')
    assert app_paths._choose_data_dir() == str(app)                      # portable copy
    monkeypatch.setenv('PFEMAME_DATA_DIR', str(tmp_path / 'override'))
    assert app_paths._choose_data_dir() == str(tmp_path / 'override')    # explicit override wins


# ------------------------------------------------------------------------------------------------------------ backups
def test_backup_and_restore_round_trip(tmp_path):
    data = tmp_path / 'data'
    data.mkdir()
    (data / 'favorites.dat').write_text('pacman\n')
    (data / 'rom_sources.dat').write_text('{}')
    target = str(tmp_path / backup.backup_file_name())
    assert backup.write_backup_zip(str(data), target, backup.BACKUP_FILES, '3.9.2') == ['favorites.dat',
                                                                                          'rom_sources.dat']
    assert 'manifest.json' in zipfile.ZipFile(target).namelist()

    (data / 'favorites.dat').write_bytes(b'changed\n')
    names = backup.restorable_files(target)
    safety = backup.restore_files(target, names, str(data), '3.9.2')
    assert (data / 'favorites.dat').read_text() == 'pacman\n'
    assert zipfile.ZipFile(safety).read('favorites.dat') == b'changed\n'     # previous state kept


def test_restore_never_writes_unexpected_names(tmp_path):
    data = tmp_path / 'data'
    data.mkdir()
    evil = tmp_path / 'evil.zip'
    with zipfile.ZipFile(evil, 'w') as archive:
        archive.writestr('../../outside.txt', 'x')
        archive.writestr('favorites.dat', 'ok')
    names = backup.restorable_files(str(evil))
    assert names == ['favorites.dat']
    backup.restore_files(str(evil), names + ['../../outside.txt'], str(data), '1')
    assert not (tmp_path / 'outside.txt').exists() and (data / 'favorites.dat').read_text() == 'ok'


def test_restore_from_an_old_style_backup_folder(tmp_path):
    old = tmp_path / 'old_backup'
    old.mkdir()
    (old / 'pfemame.ini').write_text('[system]\n')
    (old / 'ratings.dat').write_text('pacman=5\n')
    assert backup.restorable_files(str(old / 'pfemame.ini')) == ['ratings.dat', 'pfemame.ini']


# -------------------------------------------------------------------------------------------------------- MAME paths
def test_split_mame_paths(tmp_path, monkeypatch):
    mame = tmp_path / 'mame.exe'
    mame.write_bytes(b'x')
    monkeypatch.setenv('PFE_TEST_ROOT', str(tmp_path / 'env'))
    more_roms = str(tmp_path / 'More Roms')          # an absolute path with a space, in this platform's own form
    folders = mame_paths.split_mame_paths(f'roms;"{more_roms}";$PFE_TEST_ROOT;roms', str(mame))
    assert folders == [str(tmp_path / 'roms'), more_roms, str(tmp_path / 'env')]
    assert mame_paths.split_mame_paths('', str(mame)) == []


def test_rom_sets_as_archives_folders_and_chds(tmp_path):
    (tmp_path / 'pacman.zip').write_bytes(b'x')
    (tmp_path / 'mslug').mkdir()
    (tmp_path / 'mslug' / '201-p1.p1').write_bytes(b'x')
    (tmp_path / 'area51').mkdir()
    (tmp_path / 'area51' / 'area51.chd').write_bytes(b'x')
    (tmp_path / 'nes').mkdir()
    (tmp_path / 'nes' / 'smb.zip').write_bytes(b'x')           # a software list folder, not a ROM set
    assert mame_paths.find_rom_sets([str(tmp_path)]) == {'pacman', 'mslug', 'area51'}
    assert mame_paths.rom_set_present([str(tmp_path)], 'mslug')
    assert not mame_paths.rom_set_present([str(tmp_path)], 'nes')


def test_no_shell_passes_awkward_names_unchanged():
    import subprocess
    name = 'Tom&Jerry^v1_100%PATH%.zip'
    out = subprocess.run([sys.executable, '-c', 'import sys; print(sys.argv[1])', name], capture_output=True,
                         text=True, **mame_paths.NO_CONSOLE).stdout.strip()
    assert out == name


# ------------------------------------------------------------------------------------------- system program INI swap
@pytest.fixture
def ini_folder(tmp_path, wx_app):
    folder = tmp_path / 'ini'
    folder.mkdir()
    (folder / 'spectrum_system_game.tzx.ini').write_text('program\n')
    return folder


def test_launch_after_a_crash_keeps_the_real_ini(ini_folder):
    import rungame
    (ini_folder / 'spectrum.ini').write_text('real\n')
    rungame.SystemIniManager(ini_folder, 'spectrum', 'game.tzx').setup_system_ini()    # crash: no restore
    manager = rungame.SystemIniManager(ini_folder, 'spectrum', 'game.tzx')
    manager.setup_system_ini()
    manager.restore_system_ini()
    assert (ini_folder / 'spectrum.ini').read_text() == 'real\n'
    assert not (ini_folder / 'spectrum_backup.ini').exists()


def test_system_without_its_own_ini(ini_folder):
    import rungame
    manager = rungame.SystemIniManager(ini_folder, 'spectrum', 'game.tzx')
    manager.setup_system_ini()
    assert (ini_folder / 'spectrum.ini').read_text() == 'program\n'
    manager.restore_system_ini()
    assert not (ini_folder / 'spectrum.ini').exists()


def test_startup_recovery_only_touches_our_files(ini_folder):
    import rungame
    (ini_folder / 'spectrum.ini').write_text('real\n')
    rungame.SystemIniManager(ini_folder, 'spectrum', 'game.tzx').setup_system_ini()    # crash mid-run
    (ini_folder / 'pacman.ini').write_text('current\n')
    (ini_folder / 'pacman_backup.ini').write_text('the user made this\n')
    assert rungame.recover_stranded_system_inis(str(ini_folder)) == ['spectrum']
    assert (ini_folder / 'spectrum.ini').read_text() == 'real\n'
    assert (ini_folder / 'pacman.ini').read_text() == 'current\n'
