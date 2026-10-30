"""The preferences window: ROM INI files (preferences_model) and how preferences.py saves."""
import types

import pytest

import preferences_model as model


def rom_values(**changes):
    """{attribute: value} for every MAME option, as in a default mame.ini, with some changed."""
    values = {option.attr: ('False' if option.is_bool else '') for option in model.MAME_OPTIONS}
    values.update(changes)
    return values


def lines_of(text: str) -> list[str]:
    return [line + '\n' for line in text.splitlines()]


# ------------------------------------------------------------------------------------------------------- the tables
def test_every_preference_has_its_own_attribute_and_key():
    attrs = [o.attr for o in model.MAME_OPTIONS] + [o.attr for o in model.PFEMAME_OPTIONS] + \
            [attr for attr, _name in model.COLOR_OPTIONS]
    assert len(attrs) == len(set(attrs))
    assert len({o.ini_key for o in model.MAME_OPTIONS}) == len(model.MAME_OPTIONS)
    assert len({o.ini_key for o in model.PFEMAME_OPTIONS}) == len(model.PFEMAME_OPTIONS)
    assert 'brightness' not in {o.ini_key for o in model.PFEMAME_OPTIONS}     # Tile View saves that itself
    assert set(attrs) | {'slot_rows', 'manual_config_control_value'} == model.SETTABLE


def test_mame_values_and_defaults():
    assert model.mame_ini_value('1', True) == 'True'
    assert model.mame_ini_value('', True) == 'False'
    assert model.mame_ini_value('48000', False) == '48000'
    fixed = model.apply_mame_defaults({'pref_sound_samplerate': '0', 'pref_video': '', 'pref_cheat': 'True'}, 'linux')
    assert fixed == {'pref_sound_samplerate': '48000', 'pref_video': 'soft', 'pref_cheat': 'True'}
    assert model.apply_mame_defaults({'pref_video': ''}, 'windows')['pref_video'] == 'd3d'


@pytest.mark.parametrize('text, ok', [('5', True), (' -30 ', True), ('0', True), ('', False), ('--5', False),
                                      ('2.5', False), ('²', False), ('6', False), ('-31', False)])
def test_int_in_range(text, ok):
    assert model.int_in_range(text, -30, 5) is ok


def test_read_lines_handles_utf8_and_older_code_page_files(tmp_path):
    path = tmp_path / 'rom.ini'
    path.write_bytes('cheat 1\r\n# Pokémon\n'.encode('utf-8'))
    assert model.read_lines(str(path)) == ['cheat 1\n', '# Pokémon\n']
    path.write_bytes('# Pok\xe9mon\n'.encode('cp1252'))
    assert model.read_lines(str(path)) == ['# Pokémon\n']


# --------------------------------------------------------------------------------------------------- ROM INI files
def test_only_options_that_differ_from_mame_ini_are_written():
    lines = model.build_rom_ini([], 'pacman ', rom_values(pref_cheat='True', pref_sound_volume='-10'),
                                rom_values(pref_sound_volume='0'))
    assert lines == ['# File created by pfeMAME', '#', '# pacman', '#', '# Game preferences section',
                     'cheat 1', 'volume -10', '#', '# END OF FILE']


def test_hand_added_lines_are_kept_and_managed_ones_replaced():
    existing = lines_of('# File created by pfeMAME\n#\n# pacman\n#\n# Game preferences section\n'
                        'cheat 1\nvolume -10\njoystick_deadzone 0.2\n\nctrlr mypad\n#\n# END OF FILE\n')
    lines = model.build_rom_ini(existing, 'pacman', rom_values(), rom_values())
    assert 'cheat 1' not in lines and 'volume -10' not in lines           # now the same as mame.ini
    start = lines.index(model.OTHER_START)
    assert lines[start:start + 4] == [model.OTHER_START, 'joystick_deadzone 0.2', 'ctrlr mypad', model.OTHER_END]
    # Saving again keeps them once (the file is stable)
    again = model.build_rom_ini(lines_of('\n'.join(lines)), 'pacman', rom_values(), rom_values())
    assert again == lines


SYSTEM_INI = lines_of('''# File created by pfeMAME
#
# spectrum game.tzx
#
# Game preferences section
cheat 1

#
# SLOT DEVICES
exp melodik
exp:melodik:exp fuller #(SUB)(PARENT=exp:melodik)
# END OF SLOT DEVICES
#

#
# MANUAL DATA
ramsize 128K
# END OF MANUAL DATA
#
# END OF FILE
''')


def test_system_slots_and_manual_data_are_kept_until_the_slots_tab_changes():
    # A change on another tab (e.g. Sound) before the Slots tab has sent anything
    lines = model.build_rom_ini(SYSTEM_INI, 'spectrum game.tzx', rom_values(pref_cheat='True'), rom_values(),
                                is_a_system=True)
    assert lines == [line.rstrip('\n') for line in SYSTEM_INI]
    assert model.OTHER_START not in lines            # slot and manual lines are not "other" settings for a system


def test_system_slots_and_manual_data_from_the_slots_tab():
    rows = [('exp', 'kempjoy', ''), (':exp', 'intf1', 'exp:kempjoy'), ('', 'ignored', ''), ('dock', '', '')]
    lines = model.build_rom_ini(SYSTEM_INI, 'spectrum', rom_values(), rom_values(), is_a_system=True,
                                slot_rows=rows, manual_text='  ramsize 48K \n')
    slots = lines[lines.index(model.SLOTS_START) + 1:lines.index(model.SLOTS_END)]
    assert slots == ['exp kempjoy', 'exp:kempjoy:exp intf1 #(SUB)(PARENT=exp:kempjoy)']
    assert lines[lines.index(model.MANUAL_START) + 1:lines.index(model.MANUAL_END)] == ['ramsize 48K']


def test_a_new_system_ini_has_no_empty_slot_section():
    """No slot section means 'MAME's defaults' to the Slots tab."""
    lines = model.build_rom_ini([], 'spectrum', rom_values(pref_cheat='True'), rom_values(), is_a_system=True)
    assert model.SLOTS_START not in lines and model.MANUAL_START not in lines


def test_slot_sections_are_other_settings_for_a_rom_without_a_slots_tab():
    lines = model.build_rom_ini(SYSTEM_INI, 'spectrum', rom_values(), rom_values())
    other = lines[lines.index(model.OTHER_START) + 1:lines.index(model.OTHER_END)]
    assert other == ['exp melodik', 'exp:melodik:exp fuller #(SUB)(PARENT=exp:melodik)', 'ramsize 128K']


def test_written_slots_are_read_back_by_the_slots_tab():
    import slot_model
    rows = [('exp', 'melodik', ''), (':exp', 'fuller', 'exp:melodik')]
    lines = lines_of('\n'.join(model.build_rom_ini([], 'spectrum', rom_values(), rom_values(), is_a_system=True,
                                                   slot_rows=rows, manual_text='')))
    assert slot_model.parse_ini_slots(lines) == {'exp': 'melodik', 'exp:melodik:exp': 'fuller'}


# ------------------------------------------------------------------------------------------------- preferences.py
@pytest.fixture
def prefs(wx_app, monkeypatch):
    """A stand-in for the Preferences panel (the real one builds every notebook page) with its methods attached."""
    import preferences
    monkeypatch.setattr(preferences, '_', lambda text: text, raising=False)
    sent = []
    monkeypatch.setattr(preferences.wx, 'CallAfter', lambda func, *args, **kwargs: sent.append((args, kwargs)))
    panel = types.SimpleNamespace(mode='default', path_to_mame_ini_file='', _mame_ini_error_shown=False,
                                  _pfemame_ini_error_shown=False,
                                  GetParent=lambda: object(), sent=sent)
    for option in model.PFEMAME_OPTIONS:
        setattr(panel, option.attr, option.default)
    for attr, _name in model.COLOR_OPTIONS:
        setattr(panel, attr, '(0, 0, 0, 255)')
    for option in model.MAME_OPTIONS:
        setattr(panel, option.attr, 'False' if option.is_bool else '')
    for name in ('_preference_values', 'save_default_preferences', 'update_status_bar', 'update_log_file',
                 'set_variable', '_on_destroy', '_unsubscribe'):
        setattr(panel, name, getattr(preferences.Preferences, name).__get__(panel))
    panel._saved_values = panel._preference_values()
    return panel


def test_only_changed_preferences_are_saved(prefs, monkeypatch):
    import iniFile
    written = []
    monkeypatch.setattr(iniFile, 'set_ini_file_variables', lambda data: written.append(data) or True)
    monkeypatch.setattr(iniFile, 'set_to_mameini_bulk', lambda data, path: written.append(data) or 0)

    prefs.save_default_preferences(True)
    assert written == []                                   # nothing changed - nothing written

    prefs.pref_tile_size = 'Large'
    prefs.save_default_preferences(True)
    assert written == [[('preferences', 'tilesize', 'Large')]]   # e.g. Tile View's brightness is left alone

    written.clear()
    prefs.save_default_preferences(True)
    assert written == []


def test_a_mame_ini_failure_is_reported_once_and_in_the_status_bar(prefs, monkeypatch):
    import iniFile
    import preferences
    boxes = []
    monkeypatch.setattr(iniFile, 'set_to_mameini_bulk', lambda data, path: -1)
    monkeypatch.setattr(preferences.wx, 'MessageBox', lambda *args, **kwargs: boxes.append(args))
    for volume in ('-1', '-2'):
        prefs.pref_sound_volume = volume
        prefs.save_default_preferences(True)
    assert len(boxes) == 1
    statuses = [kwargs['msg'] for args, kwargs in prefs.sent if args and args[0] == 'status']
    assert statuses == ['ERROR: Unable to write to the mame.ini file'] * 2


def test_a_pfemame_ini_failure_is_reported_once_and_not_marked_saved(prefs, monkeypatch):
    # set_ini_file_variables used to raise (e.g. pfemame.ini read-only) - now it returns False
    import iniFile
    import preferences
    boxes, written = [], []
    monkeypatch.setattr(iniFile, 'set_ini_file_variables', lambda data: written.append(data) and False)
    monkeypatch.setattr(preferences.wx, 'MessageBox', lambda *args, **kwargs: boxes.append(args))
    prefs.pref_tile_size = 'Large'
    prefs.save_default_preferences(True)
    prefs.save_default_preferences(True)                   # Not saved, so tried again
    assert written == [[('preferences', 'tilesize', 'Large')]] * 2
    assert len(boxes) == 1 and 'pfemame.ini' in boxes[0][0]
    statuses = [kwargs['msg'] for args, kwargs in prefs.sent if args and args[0] == 'status']
    assert statuses == ['ERROR writing to pfemame.ini file'] * 2


def test_unknown_settings_are_not_stored(prefs):
    prefs.set_variable(['pref_tile_size', 'Small'])
    prefs.set_variable(['pref_tile_sise', 'Small'])
    assert prefs.pref_tile_size == 'Small' and not hasattr(prefs, 'pref_tile_sise')


def test_destroy_events_from_child_windows_dont_unsubscribe(prefs):
    calls = []
    prefs._subscriptions = [(lambda: None, 'default_set_variable')]
    prefs._save_timer = None
    prefs._unsubscribe = lambda: calls.append('unsubscribed')

    class Event:
        def __init__(self, obj):
            self.obj = obj

        def GetEventObject(self):
            return self.obj

        def Skip(self):
            pass

    prefs._on_destroy(Event(object()))       # a slot row being removed
    assert calls == []
    prefs._on_destroy(Event(prefs))          # the window itself
    assert calls == ['unsubscribed']


def test_mame_executable_check(tmp_path):
    import preferences
    exe = tmp_path / 'mame'
    exe.write_bytes(b'')
    assert preferences.mame_executable_found(str(exe))
    assert not preferences.mame_executable_found(str(tmp_path / 'missing'))
    assert not preferences.mame_executable_found('')


# ---------------------------------------------------------------------------------------------- the real window
@pytest.fixture
def real_window(wx_app, data_dir, monkeypatch, tmp_path):
    """Build real Preferences panels against a temporary MAME folder and data folder."""
    import os
    import wx
    import app_paths
    import iniFile
    monkeypatch.setattr(app_paths, 'app_dir', lambda: os.getcwd())
    monkeypatch.setattr(app_paths, 'migrate_data', lambda source, target: [])
    old_log = wx.Log.SetActiveTarget(wx.LogStderr())
    boxes = []
    monkeypatch.setattr(wx, 'MessageBox', lambda *args, **kwargs: boxes.append(args) or wx.OK)

    mame = tmp_path / 'MAME'
    (mame / 'ini').mkdir(parents=True)
    (mame / 'mame.exe').write_bytes(b'')
    (mame / 'mame.ini').write_text('inipath ini\ncheat 0\nvolume 0\naudio_latency 2\nsamplerate 48000\n',
                                   encoding='utf-8')
    iniFile.set_ini_file_variables([('path', 'mame_ini', str(mame / 'mame.ini')),
                                    ('preferences', 'brightness', '0.7')])
    frame = wx.Frame(None)
    env = types.SimpleNamespace(frame=frame, mame=mame, exe=str(mame / 'mame.exe'), boxes=boxes)
    yield env
    frame.Destroy()
    wx.Log.SetActiveTarget(old_log)


def test_real_default_preferences_dont_undo_other_settings(real_window):
    import iniFile
    import preferences
    panel = preferences.Preferences(real_window.frame, 'Default Preferences', 'default', '', '', '', '')
    panel.reset_block()
    iniFile.set_ini_file_variables([('preferences', 'brightness', '0.9')])     # e.g. Tile View closing
    panel.set_variable(['pref_tile_size', 'Large'])
    panel.process_preferences()
    assert iniFile.read_ini_file('preferences', 'tilesize') == 'Large'
    assert iniFile.read_ini_file('preferences', 'brightness') == '0.9'
    assert real_window.boxes == []
    panel.Destroy()


def test_real_rom_preferences_save_the_last_change_when_the_tab_closes(real_window):
    import preferences
    rom_ini = real_window.mame / 'ini' / 'pacman.ini'
    rom_ini.write_text('cheat 1\njoystick_deadzone 0.2\n', encoding='utf-8')
    panel = preferences.Preferences(real_window.frame, 'ROM Preferences', 'game', 'pacman', 'ini', real_window.exe, '')
    assert panel.pref_cheat == 'True'
    panel.reset_block()
    panel.set_variable(['pref_sound_volume', '-5'])
    panel.update_ini_files()            # waits for SAVE_DELAY_MS ...
    panel.Destroy()                     # ... but the tab closing saves straight away
    lines = rom_ini.read_text(encoding='utf-8').splitlines()
    assert 'cheat 1' in lines and 'volume -5' in lines
    assert 'audio_latency 2' not in lines                                   # same as mame.ini
    assert lines[lines.index('# OTHER SETTINGS') + 1] == 'joystick_deadzone 0.2'


def test_real_rom_preferences_without_mame(real_window):
    import preferences
    panel = preferences.Preferences(real_window.frame, 'ROM Preferences', 'game', 'pacman', 'ini',
                                    str(real_window.mame / 'missing.exe'), '')
    assert panel._subscriptions == []                                      # nothing left listening
    assert not hasattr(panel, 'sizer_main_vertical')                       # the message, not empty tabs
    panel.Destroy()
