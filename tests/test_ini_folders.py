"""ROM INI files when mame.ini's inipath lists several folders (MAME's default is '.;ini;ini/presets')."""
import types
from pathlib import Path

import pytest

import mame_paths

DEFAULT_INIPATH = '.;ini;ini/presets'


@pytest.fixture
def mame(tmp_path):
    """A MAME folder laid out like a default Windows install: mame.exe, mame.ini, ini\\ and ini\\presets\\."""
    folder = tmp_path / 'MAME'
    (folder / 'ini' / 'presets').mkdir(parents=True)
    (folder / 'mame.exe').write_bytes(b'')
    (folder / 'mame.ini').write_text(f'inipath     {DEFAULT_INIPATH}\n', encoding='utf-8')
    return types.SimpleNamespace(folder=folder, exe=str(folder / 'mame.exe'), ini=str(folder / 'mame.ini'))


# ------------------------------------------------------------------------------------------------------------ helpers
def test_search_order_is_mame_ini_folder_then_inipath(mame):
    assert mame_paths.ini_search_folders(DEFAULT_INIPATH, mame.exe, mame.ini) == [
        str(mame.folder), str(mame.folder / 'ini'), str(mame.folder / 'ini' / 'presets')]
    # Folders that don't exist are left out
    assert mame_paths.ini_search_folders('missing;ini', mame.exe) == [str(mame.folder / 'ini')]


def test_new_rom_inis_go_in_the_first_ini_folder_that_isnt_mames_own(mame):
    assert mame_paths.rom_ini_folder(DEFAULT_INIPATH, mame.exe) == str(mame.folder / 'ini')
    assert mame_paths.rom_ini_folder('.', mame.exe) == str(mame.folder)              # the only one there is
    assert mame_paths.rom_ini_folder('missing', mame.exe) == ''


def test_inipath_variables_are_expanded(mame, tmp_path, monkeypatch):
    home = tmp_path / 'home' / '.mame'
    home.mkdir(parents=True)
    monkeypatch.setenv('MAMEHOME', str(tmp_path / 'home'))
    assert mame_paths.rom_ini_folder('$MAMEHOME/.mame;.;ini', mame.exe) == str(home)


def test_an_existing_rom_ini_is_used_where_mame_finds_it(mame):
    def find():
        return mame_paths.find_rom_ini('pacman.ini', DEFAULT_INIPATH, mame.exe, mame.ini)

    assert find() == str(mame.folder / 'ini' / 'pacman.ini')                          # new: the INI folder
    (mame.folder / 'ini' / 'presets' / 'pacman.ini').write_text('', encoding='utf-8')
    assert find() == str(mame.folder / 'ini' / 'presets' / 'pacman.ini')              # the only existing one
    (mame.folder / 'pacman.ini').write_text('', encoding='utf-8')
    assert find() == str(mame.folder / 'pacman.ini')                                  # MAME reads this one first
    assert mame_paths.find_rom_ini('pacman.ini', 'missing', mame.exe) == ''          # nowhere to put one


# ------------------------------------------------------------------------------------------- ROM preferences / reset
def test_rom_preferences_use_the_ini_folder(mame, wx_app):
    import preferences
    panel = types.SimpleNamespace(rom_file_name='spectrum', system_file_name='game.tzx', folder_ini=DEFAULT_INIPATH,
                                  path_executable=mame.exe, path_to_mame_ini_file=mame.ini)
    assert preferences.Preferences.construct_filepath(panel) == str(mame.folder / 'ini' /
                                                                    'spectrum_system_game.tzx.ini')
    panel.system_file_name = ''
    (mame.folder / 'spectrum.ini').write_text('', encoding='utf-8')
    assert preferences.Preferences.construct_filepath(panel) == str(mame.folder / 'spectrum.ini')


def test_reset_removes_the_rom_ini_mame_uses(mame, wx_app, monkeypatch):
    import pfemame
    monkeypatch.setattr(pfemame, '_', lambda text: text, raising=False)
    in_root, in_ini = mame.folder / 'pacman.ini', mame.folder / 'ini' / 'pacman.ini'
    for path in (in_root, in_ini):
        path.write_text('', encoding='utf-8')
    messages = []
    window = types.SimpleNamespace(
        folder_ini=DEFAULT_INIPATH, path_mame_exe=mame.exe, path_to_mame_ini_file=mame.ini,
        get_virtual_list_row_info=lambda: types.SimpleNamespace(rom_file_name='pacman', rom_name='Pac-Man',
                                                                system_file_name=''),
        messages_append=lambda msg, *_a: messages.append(msg))

    pfemame.MainFrame.on_ini_file_reset(window, None)

    assert not in_root.exists() and in_ini.exists()          # the copy MAME reads first
    assert 'removed' in messages[0]


def test_reset_with_no_ini_folder_says_so(tmp_path, wx_app, monkeypatch):
    import pfemame
    monkeypatch.setattr(pfemame, '_', lambda text: text, raising=False)
    messages = []
    window = types.SimpleNamespace(
        folder_ini='missing', path_mame_exe='', path_to_mame_ini_file='',
        get_virtual_list_row_info=lambda: types.SimpleNamespace(rom_file_name='pacman', rom_name='Pac-Man',
                                                                system_file_name=''),
        messages_append=lambda msg, *_a: messages.append(msg))

    pfemame.MainFrame.on_ini_file_reset(window, None)

    assert 'not been correctly defined' in messages[0]


# ------------------------------------------------------------------------------------------------- running a game
def _run_game(mame, rom='spectrum', system='game.tzx'):
    import rungame
    settings = rungame.EmulatorSettings(
        folder_ini=DEFAULT_INIPATH, folders_roms=Path(''), folders_systems=Path(''), folder_config=Path(''),
        path_to_mame_ini_file=Path(mame.ini), pref_force_all_fullscreen='',
        pref_force_all_window='')
    config = types.SimpleNamespace(rom_file_name=rom, system_file_name=system, path_executable=Path(mame.exe))
    return types.SimpleNamespace(settings=settings, config=config)


def test_system_ini_swap_happens_where_the_systems_own_ini_is(mame, wx_app):
    import rungame
    program_ini = mame.folder / 'ini' / 'spectrum_system_game.tzx.ini'
    program_ini.write_text('program settings', encoding='utf-8')
    system_ini = mame.folder / 'spectrum.ini'                           # the system's own INI, in the MAME folder
    system_ini.write_text('system settings', encoding='utf-8')

    manager = rungame.RunGame._system_ini_manager(_run_game(mame))
    assert manager.rom_specific_ini_path == program_ini
    assert manager.top_level_ini_path == system_ini

    assert manager.setup_system_ini()
    assert system_ini.read_text(encoding='utf-8') == 'program settings'   # MAME reads the program's settings
    manager.restore_system_ini()
    assert system_ini.read_text(encoding='utf-8') == 'system settings'


def test_system_ini_swap_without_a_system_ini_goes_beside_the_programs(mame, wx_app):
    import rungame
    program_ini = mame.folder / 'ini' / 'spectrum_system_game.tzx.ini'
    program_ini.write_text('program settings', encoding='utf-8')

    manager = rungame.RunGame._system_ini_manager(_run_game(mame))

    assert manager.top_level_ini_path == mame.folder / 'ini' / 'spectrum.ini'
    # A program with no INI of its own: nothing is swapped
    assert not rungame.RunGame._system_ini_manager(_run_game(mame, system='other.tzx')).setup_system_ini()
    assert not (mame.folder / 'ini' / 'spectrum.ini').exists()


def test_rom_ini_is_found_for_slots_and_messages(mame, wx_app):
    game = _run_game(mame)
    assert game.settings.rom_ini('spectrum.ini', game.config.path_executable) == mame.folder / 'ini' / 'spectrum.ini'
    (mame.folder / 'ini' / 'presets' / 'spectrum.ini').write_text('', encoding='utf-8')
    assert game.settings.rom_ini('spectrum.ini', game.config.path_executable) == (
        mame.folder / 'ini' / 'presets' / 'spectrum.ini')
