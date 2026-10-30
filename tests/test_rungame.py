"""Running a game (rungame.py): MAME / system program / alternate emulator command lines and launch errors."""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import mame_paths
import play_stats
import rungame


# ------------------------------------------------------------------------------------------------------------ helpers
@pytest.fixture
def mame(tmp_path):
    folder = tmp_path / 'MAME'
    (folder / 'roms' / 'spectrum').mkdir(parents=True)
    (folder / 'roms' / 'spectrum' / 'game.tzx').write_bytes(b'')
    (folder / 'mame.exe').write_bytes(b'')
    (folder / 'mame.ini').write_text('rompath roms\n', encoding='utf-8')
    return folder


def make_game(mame, system_file_name='game.tzx', short_name='game', caller='Normal View', **settings):
    """A RunGame with its config and settings filled in, without starting the thread."""
    game = object.__new__(rungame.RunGame)
    game.config = rungame.GameConfig(
        parent=None, rom_file_name='spectrum', path_executable=mame / 'mame.exe', caller=caller,
        rom_name='ZX Spectrum', system_file_name=system_file_name, short_name=short_name,
        system_folder_name='spectrum', folder_mame_ini=mame, folder_mapping=None, suppress_short_name=False)
    game.settings = rungame.EmulatorSettings(
        folder_ini='', folders_roms=mame / 'roms', folders_systems=mame / 'roms', folder_config=None,
        path_to_mame_ini_file=mame / 'mame.ini', pref_force_all_fullscreen='', pref_force_all_window='',
        rom_folders=[mame / 'roms'], pref_disable_artwork=settings.get('disableartwork', ''))
    game.engine_info = {'engine': 'mame'}
    game.play_key = play_stats.make_key('spectrum', system_file_name)
    game.play_seconds = 0.0
    return game


class FakeExecutor:
    """Stands in for ProcessExecutor: records each command and returns the queued results ('', '', 0 after)."""
    commands: list = []
    results: list = []

    def __init__(self, command, cwd=None, encoding=None):
        self.command, self.cwd, self.encoding = command, cwd, encoding

    def run(self):
        FakeExecutor.commands.append((self.command, self.cwd, self.encoding))
        return FakeExecutor.results.pop(0) if FakeExecutor.results else ('', '', 0)


@pytest.fixture
def executor(monkeypatch):
    FakeExecutor.commands, FakeExecutor.results = [], []
    monkeypatch.setattr(rungame, 'ProcessExecutor', FakeExecutor)
    monkeypatch.setattr(rungame.functions, 'get_system_media_types',
                        lambda exe, system, ext: (True, 'cass') if ext == '.tzx' else (False, ''))
    monkeypatch.setattr(rungame.functions, 'get_softwarelist_name', lambda *args: 'spectrum_cass')
    return FakeExecutor


@pytest.fixture
def published(monkeypatch):
    """Everything MessagePublisher / _cleanup send, as (topic, kwargs)."""
    sent = []
    monkeypatch.setattr(rungame.wx, 'GetApp', lambda: True)
    monkeypatch.setattr(rungame.wx, 'CallAfter', lambda func, topic, **kwargs: sent.append((topic, kwargs)))
    return sent


# ------------------------------------------------------------------------------------- 1. retry with the full path
def test_retry_only_when_mame_failed_using_the_short_name():
    retry = rungame.RunGame._should_retry_with_full_path
    assert retry('Error: file not found', 1, True)
    assert retry('No such file or directory', 2, True)
    assert not retry('sample.wav: file not found', 0, True)       # The game ran normally
    assert not retry('file not found', 1, False)                  # Already the full path
    assert not retry('file not found', None, True)                # MAME itself didn't start


def test_retry_runs_the_program_from_its_full_path(mame, executor):
    executor.results = [('', 'Error: file not found', 1)]
    make_game(mame)._run_mame_engine()

    first, retry = [command for command, _cwd, _encoding in executor.commands]
    assert first[-2:] == ['-cass', 'game']                         # Short name first...
    assert retry[-2:] == ['-cass', str(mame / 'roms' / 'spectrum' / 'game.tzx')]   # ...then the file (was 'game')
    assert {cwd for _command, cwd, _encoding in executor.commands} == {str(mame)}


# --------------------------------------------------------------------- 2. a program MAME can't load isn't started
def test_unknown_extension_does_not_start_mame(mame, executor):
    make_game(mame, system_file_name='game.xyz')._run_mame_engine()
    assert executor.commands == []                                 # Used to boot the system on its own


def test_program_without_an_extension_does_not_start_mame(mame, executor):
    make_game(mame, system_file_name='GAME')._run_mame_engine()
    assert executor.commands == []


def test_arcade_rom_and_system_program_still_run(mame, executor):
    make_game(mame, system_file_name='', short_name='')._run_mame_engine()
    make_game(mame, short_name='')._run_mame_engine()
    arcade, program = [command for command, _cwd, _encoding in executor.commands]
    assert arcade[-1] == 'spectrum'
    assert program[-2:] == ['-cass', str(mame / 'roms' / 'spectrum' / 'game.tzx')]
    assert all(encoding == 'utf-8' for _command, _cwd, encoding in executor.commands)   # 8. MAME writes UTF-8


# ---------------------------------------------------------------------------------------- 3. launch errors reported
def test_missing_emulator(tmp_path):
    _out, error, rc = rungame.ProcessExecutor([str(tmp_path / 'missing.exe')]).run()
    assert rc is None and 'missing.exe' in error


def test_folder_or_non_program_as_emulator(tmp_path):
    """A .app folder on macOS, a file without +x on Linux, a non-program on Windows (WinError 193) - no crash."""
    not_a_program = tmp_path / 'readme.txt'
    not_a_program.write_text('hello', encoding='utf-8')
    for path in (tmp_path, not_a_program):
        _out, error, rc = rungame.ProcessExecutor([str(path)]).run()
        assert rc is None and str(path) in error


def test_output_decoded_as_utf8():
    script = "import sys; sys.stdout.buffer.write('Pok\\u00e9mon \\u30c6\\u30b9\\u30c8'.encode('utf-8'))"
    out, _err, rc = rungame.ProcessExecutor([sys.executable, '-c', script], encoding='utf-8').run()
    assert rc == 0 and out == 'Pokémon テスト'


def test_unbalanced_quote_in_extra_commands_is_reported(mame, executor, published):
    game = make_game(mame, system_file_name='')
    game.engine_info = {'engine': 'VPX', 'path': str(mame / 'vpx.exe'), 'rom_folder': 'Default',
                        'include_extension': False, 'include_folder_path': False,
                        'extra_commands': '-play "{rom}', 'extensions': []}
    game._run_alternate_engine()
    assert executor.commands == []
    assert ('enable_alert_timer', {}) in published
    assert any('VPX' in kwargs.get('msg', '') for topic, kwargs in published if topic == 'update')


def test_unexpected_error_is_reported_not_lost(mame, monkeypatch, published):
    game = make_game(mame)
    monkeypatch.setattr(game, '_run_mame_engine', lambda: 1 / 0)
    game.run()                                                     # The thread entry point - must not raise
    assert ('enable_alert_timer', {}) in published
    assert any(topic == 'rom_played' for topic, _kwargs in published)   # Clean-up still happened


# ------------------------------------------------------------------------------------- 4. the config (cfg) folder
def test_config_folder_resolved_like_mame(mame, tmp_path, monkeypatch):
    exe = str(mame / 'mame.exe')
    assert mame_paths.resolve_mame_folder('cfg', exe) == str(mame / 'cfg')     # Was relative to pfeMAME's folder
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    monkeypatch.setenv('MAMEHOME', str(tmp_path / 'home'))
    assert mame_paths.resolve_mame_folder('$MAMEHOME/.mame/cfg', exe) == str(tmp_path / 'home' / '.mame' / 'cfg')
    assert mame_paths.resolve_mame_folder('', exe) == ''


@pytest.fixture
def mapping(tmp_path):
    folders = SimpleNamespace(mapping=tmp_path / 'mapping', config=tmp_path / 'cfg')
    folders.mapping.mkdir()
    folders.config.mkdir()
    (folders.mapping / 'pacman.map').write_text('pacman inputs', encoding='utf-8')
    folders.default_cfg = folders.config / 'default.cfg'
    folders.backup = folders.config / rungame.DEFAULT_CFG_BACKUP
    return folders


def test_rom_mapping_copied_to_the_config_folder(mapping):
    manager = rungame.InputMappingManager('pacman', mapping.mapping, mapping.config)
    assert manager.apply()
    assert mapping.default_cfg.read_text(encoding='utf-8') == 'pacman inputs'
    assert not rungame.InputMappingManager('pacman', None, mapping.config).apply()   # No folders set - nothing
    assert not rungame.InputMappingManager('pacman', mapping.mapping, None).apply()
    assert not rungame.InputMappingManager('galaga', mapping.mapping, mapping.config).apply()   # No .map file


# ------------------------------------------------------------------------------- F2. default.cfg put back afterwards
def test_users_default_cfg_is_put_back_after_the_game(mapping):
    mapping.default_cfg.write_text('my inputs', encoding='utf-8')
    manager = rungame.InputMappingManager('pacman', mapping.mapping, mapping.config)
    manager.apply()
    assert mapping.default_cfg.read_text(encoding='utf-8') == 'pacman inputs'
    manager.restore()
    assert mapping.default_cfg.read_text(encoding='utf-8') == 'my inputs'   # The next ROM gets the user's inputs
    assert not mapping.backup.exists()
    assert (mapping.mapping / 'pacman.map').read_text(encoding='utf-8') == 'pacman inputs'   # Unchanged


def test_input_changes_while_playing_go_into_the_roms_mapping(mapping):
    mapping.default_cfg.write_text('my inputs', encoding='utf-8')
    manager = rungame.InputMappingManager('pacman', mapping.mapping, mapping.config)
    manager.apply()
    mapping.default_cfg.write_text('pacman inputs, button 2 changed', encoding='utf-8')     # MAME saved a change
    manager.restore()
    assert (mapping.mapping / 'pacman.map').read_text(encoding='utf-8') == 'pacman inputs, button 2 changed'
    assert mapping.default_cfg.read_text(encoding='utf-8') == 'my inputs'


def test_no_default_cfg_before_means_none_after(mapping):
    manager = rungame.InputMappingManager('pacman', mapping.mapping, mapping.config)
    manager.apply()
    manager.restore()
    assert not mapping.default_cfg.exists() and not mapping.backup.exists()


def test_default_cfg_left_by_a_crash_is_put_back(mapping):
    mapping.default_cfg.write_text('my inputs', encoding='utf-8')
    rungame.InputMappingManager('pacman', mapping.mapping, mapping.config).apply()   # pfeMAME killed mid-game
    assert rungame.restore_default_cfg(mapping.config)                               # Next start-up
    assert mapping.default_cfg.read_text(encoding='utf-8') == 'my inputs'
    assert not rungame.restore_default_cfg(mapping.config)                           # Nothing left to do
    assert not rungame.restore_default_cfg(None)


def test_a_crash_backup_is_never_overwritten_by_the_next_mapping(mapping):
    mapping.default_cfg.write_text('my inputs', encoding='utf-8')
    rungame.InputMappingManager('pacman', mapping.mapping, mapping.config).apply()   # Killed, no restore
    manager = rungame.InputMappingManager('pacman', mapping.mapping, mapping.config)
    manager.apply()                                                                  # Played again
    manager.restore()
    assert mapping.default_cfg.read_text(encoding='utf-8') == 'my inputs'


def test_mapping_is_applied_and_restored_around_a_mame_run(mame, mapping, executor, monkeypatch):
    mapping.default_cfg.write_text('my inputs', encoding='utf-8')
    seen = []
    monkeypatch.setattr(executor, 'run', lambda self: (
        seen.append(mapping.default_cfg.read_text(encoding='utf-8')), ('', '', 0))[1])
    game = make_game(mame, system_file_name='', short_name='')
    game.config.rom_file_name = 'pacman'
    game.config.folder_mapping, game.settings.folder_config = mapping.mapping, mapping.config
    game._run_mame_engine()
    assert seen == ['pacman inputs']                                               # While MAME ran
    assert mapping.default_cfg.read_text(encoding='utf-8') == 'my inputs'           # Afterwards


# ------------------------------------------------------------------------------------ 5. separator after each game
def test_end_of_game_separator_reaches_the_messages_window(mame, published):
    make_game(mame)._log_end()
    updates = [kwargs for topic, kwargs in published if topic == 'update']
    assert updates[-1] == {'msg': '', 'add_delimiter': True, 'include_datetime': False}


# ------------------------------------------------------------------------- 6. alternate emulator extension matching
def _extension_match(folder, extensions, rom):
    settings = SimpleNamespace(rom_folders=[folder], folders_roms=folder)
    return rungame.CommandBuilder(None, settings, {})._get_extension_match(extensions, rom)


def test_extension_list_is_not_case_sensitive(tmp_path):
    (tmp_path / 'attack.vpx').write_bytes(b'')
    assert _extension_match(tmp_path, ['VPX'], 'attack') == 'attack.vpx'
    assert _extension_match(tmp_path, ['.Vpx'], 'attack') == 'attack.vpx'


@pytest.mark.parametrize('case_insensitive, expected', [(True, 'PacMan.zip'), (False, 'pacman')])
def test_file_name_case_follows_the_platform(tmp_path, monkeypatch, case_insensitive, expected):
    (tmp_path / 'PacMan.zip').write_bytes(b'')
    monkeypatch.setattr(rungame, 'CASE_INSENSITIVE_FILE_NAMES', case_insensitive)
    assert _extension_match(tmp_path, ['zip'], 'pacman') == expected


# ------------------------------------------------------------------------- 7. runs that failed straight away
@pytest.mark.parametrize('seconds, counted', [(0.5, False), (play_stats.MIN_SECONDS, True), (600, True)])
def test_only_real_runs_are_counted(mame, published, seconds, counted):
    game = make_game(mame)
    game.config.parent = SimpleNamespace()
    game.play_seconds = seconds
    game._cleanup()
    runs = [kwargs for topic, kwargs in published if topic == 'number_of_runs']
    assert bool(runs) == counted
    if counted:
        assert runs[0]['attr1'] == 'spectrum' and runs[0]['attr3'] == 'game.tzx' and runs[0]['attr4']
    assert game.config.parent.joystick_block is False


# ------------------------------------------------------------------------------------------ 9. a single -artpath
@pytest.mark.parametrize('disableartwork, expected', [('', 0), ('True', 1), ('False', 0)])
def test_artwork_off_adds_one_artpath(mame, disableartwork, expected):
    game = make_game(mame, disableartwork=disableartwork)
    cmd = rungame.CommandBuilder(game.config, game.settings, game.engine_info).build_mame_command_base()
    assert cmd.count('-artpath') == expected
    if expected:
        assert cmd[cmd.index('-artpath') + 1] == ''


# ------------------------------------------------------------------------- 10. emulator entries with no file name
EMPTY_FILE_NAME_XML = '''<pfemame author="gfinch">
    <machine name="Pinball" pathToEmulator="vpx.exe" romFolder="Default" useThisEngine="True" includeExtension="False" includeFolderPath="False">
        <description>Pinball</description>
        <extraCommands></extraCommands>
        <extensions>vpx</extensions>
        <game name="Blank" fileName=""/>
        <game name="Attack" fileName="attack"/>
    </machine>
</pfemame>
'''


def test_entry_with_no_file_name_does_not_capture_arcade_roms(data_dir):
    (data_dir / 'non_mame_emulators.xml').write_text(EMPTY_FILE_NAME_XML, encoding='utf-8')
    settings = SimpleNamespace(folders_roms=Path('roms'), rom_folders=[Path('roms')])
    assert rungame.EngineSelector(settings, False, 'pacman', '').determine()['engine'] == 'mame'
    assert rungame.EngineSelector(settings, False, 'attack', '').determine()['engine'] == 'Pinball'


# ------------------------------------------------------------------------------------ F1. exit codes put in words
def test_mame_exit_codes_explained():
    message = rungame.exit_code_message('mame', 'pacman', 2)
    assert 'pacman' in message and '(MAME exit code 2)' in message and 'missing' in message
    assert 'renamed or removed' in rungame.exit_code_message('mame', 'pacman', 5)
    assert 'unexpectedly' in rungame.exit_code_message('mame', 'pacman', 42)
    assert '0xC0000005' in rungame.exit_code_message('mame', 'pacman', 0xC0000005)      # A Windows crash
    assert 'signal 11' in rungame.exit_code_message('mame', 'pacman', -11)              # A Linux / macOS crash
    assert rungame.exit_code_message('VPX', 'attack', 1) == \
        'The VPX emulator ended with an error running ROM attack (exit code 1).'


@pytest.mark.parametrize('caller, engine, shown, alert', [
    ('Normal View', 'mame', True, True),
    ('Normal View', 'VPX', True, False),        # Other emulators may end with a non-zero code when all went well
    ('Tile View', 'mame', False, False)])       # Tile View shows no messages - log file only
def test_exit_code_reported(mame, executor, published, caller, engine, shown, alert):
    executor.results = [('', '', 2)]
    game = make_game(mame, system_file_name='', short_name='', caller=caller)
    game._execute(['emulator'], None, engine)
    messages = {topic: [k.get('msg', '') for t, k in published if t == topic] for topic in ('update', 'log')}
    assert any('exit code 2' in msg for msg in messages['log'])
    assert any('exit code 2' in msg for msg in messages['update']) == shown
    assert (('enable_alert_timer', {}) in published) == alert


def test_normal_exit_reports_nothing(mame, executor, published):
    make_game(mame, system_file_name='', short_name='')._execute(['mame'], None, 'mame')
    assert not any('exit code' in kwargs.get('msg', '') for _topic, kwargs in published)
    assert ('enable_alert_timer', {}) not in published


# ------------------------------------------------------------------------------- F3. media types: exact and cached
LISTMEDIA = '''SYSTEM           MEDIA NAME       (brief)    IMAGE FILE EXTENSIONS SUPPORTED
---------------- --------------------------- -------------------------------
spectrum         cassette         (cass)     .wav  .tzx  .tap  .blk
                 snapshot         (dump)     .ach  .frz  .plusd  .prg  .sem  .sit  .sna  .snp  .snx  .sp  .z80  .zx
                 quickload        (quik)     .raw  .scr
                 floppydisk       (flop)     .dsk
'''


@pytest.fixture
def listmedia(monkeypatch, tmp_path):
    import functions
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return SimpleNamespace(stdout=LISTMEDIA, stderr='', returncode=0)

    monkeypatch.setattr(functions.subprocess, 'run', fake_run)
    monkeypatch.setattr(functions, '_media_cache', {})
    exe = tmp_path / 'mame.exe'
    exe.write_bytes(b'')
    return SimpleNamespace(functions=functions, calls=calls, exe=str(exe))


def test_media_type_extension_must_match_exactly(listmedia):
    media = listmedia.functions.get_system_media_types
    assert media(listmedia.exe, 'spectrum', '.tzx') == (True, 'cass')
    assert media(listmedia.exe, 'spectrum', '.TZX') == (True, 'cass')
    assert media(listmedia.exe, 'spectrum', '.dsk') == (True, 'flop')
    assert media(listmedia.exe, 'spectrum', '.d') == (False, '')       # Used to match .dsk
    assert media(listmedia.exe, 'spectrum', '.ta') == (False, '')      # Used to match .tap
    assert '.z80' in media(listmedia.exe, 'spectrum')                  # The full list (View media types)
    assert media(listmedia.exe, '') == -1


def test_media_types_asked_for_once_per_system(listmedia):
    media = listmedia.functions.get_system_media_types
    for _ in range(3):
        media(listmedia.exe, 'spectrum', '.tzx')
    media(listmedia.exe, 'spectrum')
    assert len(listmedia.calls) == 1
    media(listmedia.exe, 'c64', '.tzx')
    assert len(listmedia.calls) == 2                                   # Another system is asked separately


def test_media_types_asked_again_after_a_mame_update(listmedia):
    import os
    media = listmedia.functions.get_system_media_types
    media(listmedia.exe, 'spectrum', '.tzx')
    os.utime(listmedia.exe, (1, 1))                                    # A new mame.exe
    media(listmedia.exe, 'spectrum', '.tzx')
    assert len(listmedia.calls) == 2


def test_media_types_not_kept_when_mame_could_not_be_run(listmedia, monkeypatch):
    def cannot_run(cmd, **kwargs):
        listmedia.calls.append(cmd)
        raise FileNotFoundError(cmd[0])

    monkeypatch.setattr(listmedia.functions.subprocess, 'run', cannot_run)
    media = listmedia.functions.get_system_media_types
    assert media(listmedia.exe, 'spectrum', '.tzx') == (False, '')
    assert media(listmedia.exe, 'spectrum', '.tzx') == (False, '')
    assert len(listmedia.calls) == 2


# ------------------------------------------------------------------------------------ F4. macOS .app bundles
def make_app(folder, name='RetroArch', plist_name='RetroArch', extra_programs=()):
    import plistlib
    app = folder / f'{name}.app'
    (app / 'Contents' / 'MacOS').mkdir(parents=True)
    for program in (plist_name, *extra_programs):
        if program:
            (app / 'Contents' / 'MacOS' / program).write_bytes(b'')
    if plist_name is not None:
        with open(app / 'Contents' / 'Info.plist', 'wb') as fp:
            plistlib.dump({'CFBundleExecutable': plist_name}, fp)
    return app


def test_app_bundle_runs_the_program_inside_it(tmp_path):
    app = make_app(tmp_path, extra_programs=('helper',))
    assert rungame.macos_app_executable(app) == app / 'Contents' / 'MacOS' / 'RetroArch'


def test_app_bundle_without_info_plist_uses_its_only_program(tmp_path):
    app = make_app(tmp_path, name='Stella', plist_name=None, extra_programs=('Stella',))
    assert rungame.macos_app_executable(app) == app / 'Contents' / 'MacOS' / 'Stella'
    unclear = make_app(tmp_path, name='Odd', plist_name=None, extra_programs=('one', 'two'))
    assert rungame.macos_app_executable(unclear) is None             # Left as it is - the launch error says why


def test_not_a_bundle(tmp_path):
    assert rungame.macos_app_executable(Path(EMULATOR_PATH)) is None
    assert rungame.macos_app_executable(tmp_path / 'Missing.app') is None


EMULATOR_PATH = str(Path('emulators') / 'emulator.exe')


def test_alternate_emulator_command_uses_the_bundle_program(tmp_path):
    app = make_app(tmp_path)
    config = SimpleNamespace(rom_file_name='pacman', system_file_name='')
    settings = SimpleNamespace(rom_folders=[tmp_path], folders_roms=tmp_path)
    engine_info = {'engine': 'RetroArch', 'path': str(app), 'rom_folder': 'Default', 'include_extension': False,
                   'include_folder_path': False, 'extra_commands': '-L core.dylib', 'extensions': []}
    cmd, cwd = rungame.CommandBuilder(config, settings, engine_info).build_alt_command()
    assert cmd == [str(app / 'Contents' / 'MacOS' / 'RetroArch'), '-L', 'core.dylib', 'pacman']
    assert cwd == tmp_path                                             # The folder the .app is in, as before
