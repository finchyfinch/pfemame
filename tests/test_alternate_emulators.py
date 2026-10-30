"""Tests for the alternate emulators window's data handling (no GUI is created)."""
import functions
import emulator_config
from emulator_config import emulator_names_in_order

# An emulator file in the format pfeMAME has always written, so existing users' files must keep loading
EXISTING_FORMAT_XML = '''<pfemame author="gfinch">
    <machine name="Zeta" pathToEmulator="C:\\emu\\zeta.exe" romFolder="Default" useThisEngine="True" includeExtension="False" includeFolderPath="False">
        <description>Arcade</description>
        <extraCommands></extraCommands>
        <extensions>zip 7z</extensions>
        <game name="Daytona" fileName="daytona"/>
        <game name="___" fileName="desert"/>
    </machine>
    <machine name="Alpha" pathToEmulator="C:\\emu\\alpha.exe" romFolder="C:\\roms" useThisEngine="False" includeExtension="True" includeFolderPath="True">
        <description>Arcade</description>
        <extraCommands>-fullscreen</extraCommands>
        <extensions>zip</extensions>
        <game name="___" fileName="scud"/>
    </machine>
    <machine name="Mid" pathToEmulator="C:\\emu\\mid.exe" romFolder="Default" useThisEngine="True" includeExtension="False" includeFolderPath="False">
        <description>Arcade</description>
        <extraCommands></extraCommands>
        <extensions>zip</extensions>
        <game name="___" fileName="vf3"/>
    </machine>
</pfemame>
'''


def row(name: str) -> list:
    return [name, '', '', '', True, False, False, '', '', 'rom', 'file']


def test_names_keep_first_seen_order():
    rows = [row('Zeta'), row('Zeta'), row('Alpha'), row('Mid'), row('Mid'), row('Mid')]
    assert emulator_names_in_order(rows) == ['Zeta', 'Alpha', 'Mid']


def test_new_emulator_is_last():
    rows = [row('Zeta'), row('Alpha'), row('Mid'), row('New one')]
    names = emulator_names_in_order(rows)
    assert names[-1] == 'New one'
    assert names.index('New one') == len(names) - 1


def test_no_rows():
    assert emulator_names_in_order([]) == []


def test_existing_xml_file_loads_in_file_order(data_dir):
    (data_dir / 'non_mame_emulators.xml').write_text(EXISTING_FORMAT_XML, encoding='utf-8')
    rows, error = functions.load_other_emulators_detail('')
    assert not error
    assert len(rows) == 4
    assert emulator_names_in_order(rows) == ['Zeta', 'Alpha', 'Mid']
    assert rows[2] == ['Alpha', 'C:\\emu\\alpha.exe', 'C:\\roms', 'Arcade', False, True, True, '-fullscreen', 'zip',
                       '___', 'scud']


# ----------------------------------------------------------------------------------------------------------------------
# Closing the window with unsaved changes (the window is created for real; dialogs are answered automatically)
import os
import pytest
import wx
import alternate_emulators

# The categories offered in the window's Description list (the test emulators use Arcade)
CATEGORIES = ['Arcade', 'Computer', 'Game Console', 'Handheld', 'Pinball']


class FakeDialog:
    """Stands in for wx.MessageDialog, answering with FakeDialog.answer and counting how often it was shown."""
    answer = wx.ID_CANCEL
    shown = 0

    def __init__(self, *args, **kwargs):
        pass

    def ShowModal(self):
        FakeDialog.shown += 1
        return FakeDialog.answer

    def Destroy(self):
        pass


@pytest.fixture
def xml_text():
    """The non_mame_emulators.xml the window starts with (None for no file).  Override with parametrize."""
    return EXISTING_FORMAT_XML


@pytest.fixture
def categories_file():
    """Whether categories.dat exists when the window opens.  Override with parametrize."""
    return True


@pytest.fixture
def window(wx_app, data_dir, monkeypatch, xml_text, categories_file):
    # Under pytest the app folder would be worked out as pytest's own folder, so the window icon wouldn't be found
    import app_paths
    monkeypatch.setattr(app_paths, 'app_dir', lambda: os.getcwd())  # conftest runs the tests from the source folder
    # ... but then the first-start data migration would copy the real user files from there into the test data folder
    # (and leave a note in the source folder), so switch it off
    monkeypatch.setattr(app_paths, 'migrate_data', lambda source, target: [])
    old_log = wx.Log.SetActiveTarget(wx.LogStderr())  # Any wx error goes to the test output, not a pop-up box
    if categories_file:
        # categories.dat is the user's own file (made when categories are ticked), so it isn't in a clean install -
        # write a small one rather than copying it from the source folder
        (data_dir / 'categories.dat').write_text('\n'.join(CATEGORIES) + '\n', encoding='utf-8')
    if xml_text is not None:
        (data_dir / 'non_mame_emulators.xml').write_text(xml_text, encoding='utf-8')
    monkeypatch.setattr(wx, 'MessageBox', lambda *args, **kwargs: wx.ID_OK)
    monkeypatch.setattr(wx, 'MessageDialog', FakeDialog)
    # The test emulators' programs and folders don't exist, so leave out the 'save anyway?' warning unless a test
    # puts it back (real_problem_check)
    monkeypatch.setattr(alternate_emulators, 'find_setup_problems', lambda rows: [])
    monkeypatch.setattr(alternate_emulators.AlternateEmulators, 'Show', lambda self, show=True: False)  # Stay hidden
    FakeDialog.shown = 0
    FakeDialog.answer = wx.ID_CANCEL
    closed_calls = []

    def record_destroy(self):  # Note the window closed but keep it alive until the test has checked it
        self.destroyed = True
    monkeypatch.setattr(alternate_emulators.AlternateEmulators, 'Destroy', record_destroy)
    monkeypatch.setattr(alternate_emulators.AlternateEmulators, 'destroyed', False, raising=False)
    frame = alternate_emulators.AlternateEmulators(on_closed=lambda: closed_calls.append(True))
    frame.closed_calls = closed_calls
    yield frame
    wx.Frame.Destroy(frame)
    wx.Log.SetActiveTarget(old_log)
    wx_app.Yield(True)  # Windows are only really deleted at idle time; do it while the wx.App still exists


def is_open(frame) -> bool:
    return not frame.destroyed


def shown(frame) -> str:
    """What the emulator selector shows."""
    return frame.emulator_selector.GetValue()


def make_a_change(frame) -> None:
    frame.text_ctrl_extra_commands.SetValue('-changed')  # Fires on_control_changed, which marks the changes unsaved
    assert frame.unsaved_changes


def saved_xml(data_dir) -> str:
    return (data_dir / 'non_mame_emulators.xml').read_text(encoding='utf-8')


@pytest.mark.parametrize('close', ['ok', 'escape', 'close_button'])
def test_no_changes_closes_without_asking(window, close):
    close_window(window, close)
    assert FakeDialog.shown == 0
    assert not is_open(window)
    assert window.closed_calls == [True]  # The main window is told, so it can re-load the emulator data


@pytest.mark.parametrize('close', ['ok', 'escape', 'close_button'])
def test_cancel_keeps_window_open(window, data_dir, close):
    make_a_change(window)
    FakeDialog.answer = wx.ID_CANCEL
    close_window(window, close)
    assert FakeDialog.shown == 1
    assert is_open(window)
    assert window.unsaved_changes
    assert saved_xml(data_dir) == EXISTING_FORMAT_XML
    assert window.closed_calls == []  # Still open, so the main window isn't told yet


@pytest.mark.parametrize('close', ['ok', 'escape', 'close_button'])
def test_no_closes_without_saving(window, data_dir, close):
    make_a_change(window)
    FakeDialog.answer = wx.ID_NO
    close_window(window, close)
    assert not is_open(window)
    assert saved_xml(data_dir) == EXISTING_FORMAT_XML


@pytest.mark.parametrize('close', ['ok', 'escape', 'close_button'])
def test_yes_saves_and_closes(window, data_dir, close):
    make_a_change(window)
    FakeDialog.answer = wx.ID_YES
    close_window(window, close)
    assert not is_open(window)
    assert '<extraCommands>-changed</extraCommands>' in saved_xml(data_dir)
    assert window.closed_calls == [True]


def test_yes_with_failed_save_keeps_window_open(window, data_dir):
    make_a_change(window)
    window.text_ctrl_emulator_path.SetPath('')  # A blank emulator path fails the checks before saving
    FakeDialog.answer = wx.ID_YES
    close_window(window, 'close_button')
    assert is_open(window)
    assert saved_xml(data_dir) == EXISTING_FORMAT_XML


def test_saved_file_still_loads(window, data_dir):
    make_a_change(window)
    assert window.on_update_xml(-1) is True
    rows, error = functions.load_other_emulators_detail('')
    assert not error
    assert emulator_names_in_order(rows) == ['Zeta', 'Alpha', 'Mid']
    assert [r[10] for r in rows] == ['daytona', 'desert', 'scud', 'vf3']


def close_window(frame, how: str) -> None:
    if how == 'ok':
        frame.on_ok(-1)
    elif how == 'escape':
        event = wx.KeyEvent(wx.wxEVT_CHAR_HOOK)
        event.SetKeyCode(wx.WXK_ESCAPE)
        frame.on_key_up_event(event)
    else:
        frame.Close()  # Sends the same close event as the window's close button


def test_main_window_told_only_once(window):
    window.on_close(-1)
    window.on_close(-1)
    assert window.closed_calls == [True]


def test_window_works_without_a_closed_function(wx_app, window):
    window.on_closed = None  # As when run on its own (__main__) or by an older caller
    window.on_close(-1)
    assert not is_open(window)


def create_emulator(frame, monkeypatch, name: str, answer: int = wx.ID_OK) -> None:
    """Press CREATE NEW EMULATOR ENTRY, typing the name and pressing OK (or the button given) in the name box."""
    class FakeTextEntry(FakeDialog):
        def ShowModal(self):
            return answer

        def GetValue(self):
            return name
    monkeypatch.setattr(wx, 'TextEntryDialog', FakeTextEntry)
    frame.on_create_new_emulator(None)


# ----------------------------------------------------------------------------------------------------------------------
# Deleting emulators
EMPTY_FILE = '<pfemame author="gfinch">\n</pfemame>\n'


def show_emulator(frame, name: str) -> None:
    while frame.emulator_list[frame.emulator_list_index] != name:
        frame.emulators_list_right(None)


def delete_shown_emulator(frame) -> None:
    FakeDialog.answer = wx.ID_YES
    frame.on_delete_emulator(None)


def saved_names() -> list[str]:
    rows, error = functions.load_other_emulators_detail('')
    assert not error
    return emulator_names_in_order(rows)


def test_delete_shows_the_previous_emulator(window):
    show_emulator(window, 'Mid')
    delete_shown_emulator(window)
    assert window.emulator_list == ['Zeta', 'Alpha']
    assert shown(window) == 'Alpha (disabled)'
    assert window.text_ctrl_extra_commands.GetValue() == '-fullscreen'  # Alpha's settings are on screen
    assert saved_names() == ['Zeta', 'Alpha']
    assert not window.unsaved_changes


def test_delete_first_shows_the_new_first(window):
    delete_shown_emulator(window)
    assert shown(window) == 'Alpha (disabled)'
    assert saved_names() == ['Alpha', 'Mid']


def test_answering_no_deletes_nothing(window, data_dir):
    FakeDialog.answer = wx.ID_NO
    window.on_delete_emulator(None)
    assert window.emulator_list == ['Zeta', 'Alpha', 'Mid']
    assert saved_xml(data_dir) == EXISTING_FORMAT_XML


def test_delete_saves_even_if_the_fields_on_screen_are_blank(window):
    window.text_ctrl_emulator_path.SetPath('')  # Would fail the checks on a normal save
    delete_shown_emulator(window)
    assert saved_names() == ['Alpha', 'Mid']


def test_delete_keeps_other_emulators_edits(window):
    show_emulator(window, 'Mid')
    window.text_ctrl_extra_commands.SetValue('-mid-edit')
    window.emulators_list_left(None)  # Now on Alpha
    delete_shown_emulator(window)
    rows, _error = functions.load_other_emulators_detail('')
    assert [r[7] for r in rows if r[0] == 'Mid'] == ['-mid-edit']


def test_delete_the_last_emulator(window, data_dir):
    for _unused in range(3):
        delete_shown_emulator(window)
    assert window.emulator_list == []
    assert window.list_control.GetItemCount() == 0
    assert window.text_ctrl_emulator_path.GetPath() == ''
    assert not window.button_delete_emulator.IsEnabled()
    assert saved_xml(data_dir) == EMPTY_FILE
    assert saved_names() == []
    assert not window.unsaved_changes

    FakeDialog.shown = 0
    window.on_delete_emulator(None)  # Nothing left: does nothing (used to crash)
    assert FakeDialog.shown == 0


def test_empty_file_is_still_read_by_the_old_line_by_line_loader(window, data_dir):
    # pfeMAME versions before the XML parser read the file line by line until a line containing </pfemame>
    for _unused in range(3):
        delete_shown_emulator(window)
    lines = saved_xml(data_dir).splitlines(keepends=True)
    index = 0
    while '</pfemame>' not in lines[index]:
        assert '<machine' not in lines[index]
        index += 1


def test_create_after_deleting_everything(window, monkeypatch):
    for _unused in range(3):
        delete_shown_emulator(window)

    create_emulator(window, monkeypatch, 'Brand new')
    assert window.emulator_list == ['Brand new']
    assert window.button_delete_emulator.IsEnabled()


@pytest.mark.parametrize('xml_text', [None, EMPTY_FILE])
def test_no_emulators_at_start(window, xml_text):
    assert window.emulator_list == []
    assert not window.button_delete_emulator.IsEnabled()
    FakeDialog.answer = wx.ID_YES
    window.on_delete_emulator(None)  # Used to crash
    assert FakeDialog.shown == 0


# ----------------------------------------------------------------------------------------------------------------------
# The window with no emulators
def emulator_controls(frame) -> list:
    return [frame.checkbox_enabled, frame.text_ctrl_description, frame.text_ctrl_emulator_path,
            frame.text_ctrl_extra_commands, frame.button_default_rom_folder, frame.text_ctrl_rom_folder,
            frame.text_ctrl_valid_extension, frame.checkbox_include_extension, frame.checkbox_include_folder_path,
            frame.list_control, frame.button_add_rom_entry, frame.button_auto_add, frame.button_set_defaults,
            frame.button_test_rom, frame.button_rename_emulator, frame.button_duplicate_emulator,
            frame.button_delete_emulator]


def test_controls_enabled_with_emulators(window):
    disabled = [c for c in emulator_controls(window) if not c.IsEnabled() and c is not window.button_auto_add]
    assert disabled == []
    assert shown(window) == 'Zeta'


@pytest.mark.parametrize('xml_text', [None, EMPTY_FILE])
def test_controls_greyed_out_with_no_emulators(window, xml_text):
    assert [c for c in emulator_controls(window) if c.IsEnabled()] == []
    assert shown(window) == alternate_emulators.no_emulators_label()
    assert window.update_xml_button.IsEnabled()


@pytest.mark.parametrize('xml_text', [None])
def test_editing_with_no_emulators_does_nothing(window, xml_text):
    window.text_ctrl_extra_commands.SetValue('typed')  # Used to crash with StopIteration
    window.checkbox_enabled.SetValue(True)
    window.on_control_changed(None)
    assert window.alternate_emulation_engines == []
    assert not window.unsaved_changes


@pytest.mark.parametrize('xml_text', [None])
def test_creating_the_first_emulator_enables_the_controls(window, xml_text, monkeypatch):
    create_emulator(window, monkeypatch, 'First')
    assert shown(window) == 'First (disabled)'  # New emulators start disabled
    assert [c for c in emulator_controls(window) if not c.IsEnabled()] == [window.button_auto_add]
    window.text_ctrl_extra_commands.SetValue('-typed')
    assert [r[7] for r in window.alternate_emulation_engines] == ['-typed']


def test_deleting_everything_greys_out_the_controls(window):
    for _unused in range(3):
        delete_shown_emulator(window)
    assert [c for c in emulator_controls(window) if c.IsEnabled()] == []
    assert shown(window) == alternate_emulators.no_emulators_label()


# ----------------------------------------------------------------------------------------------------------------------
# Auto scan ROM folder
from emulator_config import scan_rom_folders, merge_scanned_roms


def make_files(folder, names) -> str:
    folder.mkdir(parents=True, exist_ok=True)
    for name in names:
        (folder / name).write_text('')
    return str(folder)


def test_scan_matches_extensions_exactly_and_ignoring_case(tmp_path):
    folder = make_files(tmp_path / 'roms', ['a.zip', 'B.ZIP', 'c.7z', 'd.7zip', 'e.txt', 'noextension', 'fzip'])
    (tmp_path / 'roms' / 'folder.zip').mkdir()  # A folder, not a ROM file
    assert scan_rom_folders([folder], ['zip', '7z']) == ['a', 'B', 'c']
    assert scan_rom_folders([folder], ['.zip']) == ['a', 'B']  # A dot typed in by mistake still works


def test_scan_several_folders(tmp_path):
    first = make_files(tmp_path / 'one', ['daytona.zip', 'scud.zip'])
    second = make_files(tmp_path / 'two', ['Daytona.7z', 'vf3.zip'])
    assert scan_rom_folders([first, str(tmp_path / 'missing'), second], ['zip', '7z']) == ['daytona', 'scud', 'vf3']


def test_merge_keeps_names_and_adds_new_files():
    existing = [('Daytona USA', 'daytona'), ('Old one', 'gone')]
    merged, added, missing = merge_scanned_roms(existing, ['DAYTONA', 'newgame'])
    assert merged == [('Daytona USA', 'daytona'), ('Old one', 'gone'), ('___', 'newgame')]
    assert added == 1
    assert missing == [('Old one', 'gone')]


def test_merge_drops_a_new_emulators_placeholder():
    merged, added, missing = merge_scanned_roms([emulator_config.PLACEHOLDER_ROM_ENTRY], ['a', 'b'])
    assert merged == [('___', 'a'), ('___', 'b')]
    assert added == 2
    assert missing == []


def rom_list(frame) -> list:
    return [frame.get_rom_detail(row) for row in range(frame.list_control.GetItemCount())]


def test_auto_scan_button_follows_the_settings(window, tmp_path):
    # Zeta's ROM folder is 'Default' and there are no MAME ROM folders in the test setup
    assert not window.button_auto_add.IsEnabled()
    window.text_ctrl_rom_folder.SetPath(make_files(tmp_path / 'roms', ['a.zip']))
    window.on_control_changed(None)  # As sent when a folder is picked
    assert window.button_auto_add.IsEnabled()
    window.text_ctrl_valid_extension.SetValue('')
    assert not window.button_auto_add.IsEnabled()
    window.text_ctrl_valid_extension.SetValue('zip')
    assert window.button_auto_add.IsEnabled()
    window.on_default_rom_folder(None)
    assert not window.button_auto_add.IsEnabled()


@pytest.mark.parametrize('remove_missing', [False, True])
def test_auto_scan_merges(window, tmp_path, remove_missing):
    window.text_ctrl_rom_folder.SetPath(make_files(tmp_path / 'roms', ['DAYTONA.zip', 'newgame.7z', 'other.chd']))
    window.on_control_changed(None)
    assert window.button_auto_add.IsEnabled()

    FakeDialog.answer = wx.ID_YES if remove_missing else wx.ID_NO  # 'desert' has no file
    window.on_add_rom_entry_auto(None)
    assert FakeDialog.shown == 1
    expected = [('Daytona', 'daytona')] + ([] if remove_missing else [('___', 'desert')]) + [('___', 'newgame')]
    assert rom_list(window) == expected
    assert [(r[9], r[10]) for r in window.alternate_emulation_engines if r[0] == 'Zeta'] == expected
    assert window.unsaved_changes


def test_default_folder_is_never_scanned(window, tmp_path, monkeypatch):
    # Even with a 'Default' folder in the working directory, which used to be what got scanned
    monkeypatch.chdir(tmp_path)
    make_files(tmp_path / 'Default', ['lots.zip', 'of.zip', 'mame.zip', 'roms.zip'])
    assert window.text_ctrl_rom_folder.GetPath() == 'Default'
    window.update_auto_scan_button()
    assert not window.button_auto_add.IsEnabled()
    before = rom_list(window)
    window.on_add_rom_entry_auto(None)
    assert rom_list(window) == before


def test_auto_scan_with_no_matches_leaves_the_list(window, tmp_path):
    window.text_ctrl_rom_folder.SetPath(make_files(tmp_path / 'roms', ['readme.txt']))
    window.on_control_changed(None)
    before = rom_list(window)
    window.on_add_rom_entry_auto(None)
    assert rom_list(window) == before
    assert [(r[9], r[10]) for r in window.alternate_emulation_engines if r[0] == 'Zeta'] == before


# ----------------------------------------------------------------------------------------------------------------------
# Problems while the window opens
@pytest.mark.parametrize('categories_file', [False])
def test_missing_categories_stops_cleanly(window, categories_file):
    assert not is_open(window)
    assert not hasattr(window, 'list_control')  # The rest of the window wasn't built


@pytest.mark.parametrize('xml_text', ['<pfemame author="gfinch"><machine name="broken"'])
def test_corrupt_xml_stops_cleanly(window, xml_text):
    assert not is_open(window)
    assert not hasattr(window, 'list_control')


def test_closing_re_enables_a_main_window_without_a_rom_list(wx_app, window):
    main_window = wx.Frame(None)  # Unlike pfeMAME's main window this has no ROM .list
    main_window.Disable()
    window.GetParent = lambda: main_window
    try:
        window.on_close(-1)  # Used to fail looking for main_window.list
        assert main_window.IsEnabled()
        assert not is_open(window)
    finally:
        main_window.Destroy()
        wx_app.Yield(True)


# ----------------------------------------------------------------------------------------------------------------------
# Test ROM
@pytest.fixture
def runs(window, monkeypatch):
    """The ROM file names Test ROM ran (the game isn't really started)."""
    started = []
    monkeypatch.setattr(alternate_emulators.rungame, 'RunGame', lambda *args, **kwargs: started.append(
        kwargs['rom_file_name']))
    window.list_control.Select(0)  # daytona
    return started


def test_test_rom_runs_the_selected_rom(window, runs):
    window.test_run(None)
    assert runs == ['daytona']
    assert FakeDialog.shown == 0


def test_test_rom_needs_a_selection(window, runs):
    window.list_control.Select(0, False)
    window.test_run(None)
    assert runs == []


def test_test_rom_refuses_a_disabled_emulator(window, runs, monkeypatch):
    messages = []
    monkeypatch.setattr(wx, 'MessageBox', lambda message, *args, **kwargs: messages.append(message))
    window.emulators_list_right(None)  # Alpha is not enabled
    window.list_control.Select(0)
    window.test_run(None)
    assert runs == []
    assert 'not enabled' in messages[0]


@pytest.mark.parametrize('answer, ran, saved', [(wx.ID_CANCEL, False, False),
                                                (wx.ID_NO, True, False),
                                                (wx.ID_YES, True, True)])
def test_test_rom_with_unsaved_changes(window, data_dir, runs, answer, ran, saved):
    make_a_change(window)
    FakeDialog.answer = answer
    window.test_run(None)
    assert FakeDialog.shown == 1
    assert runs == (['daytona'] if ran else [])
    assert ('<extraCommands>-changed</extraCommands>' in saved_xml(data_dir)) == saved


def test_test_rom_does_not_run_if_the_save_fails(window, data_dir, runs):
    make_a_change(window)
    window.text_ctrl_emulator_path.SetPath('')  # Fails the checks before saving
    FakeDialog.answer = wx.ID_YES
    window.test_run(None)
    assert runs == []
    assert saved_xml(data_dir) == EXISTING_FORMAT_XML


# ----------------------------------------------------------------------------------------------------------------------
# Creating emulators
def test_create_cancelled_does_nothing(window, monkeypatch):
    messages = []
    monkeypatch.setattr(wx, 'MessageBox', lambda message, *args, **kwargs: messages.append(message))
    create_emulator(window, monkeypatch, 'Typed then cancelled', answer=wx.ID_CANCEL)
    assert window.emulator_list == ['Zeta', 'Alpha', 'Mid']
    assert messages == []
    assert not window.unsaved_changes


def test_create_trims_the_name_and_marks_it_unsaved(window, monkeypatch):
    create_emulator(window, monkeypatch, '  New one  ')
    assert window.emulator_list == ['Zeta', 'Alpha', 'Mid', 'New one']
    assert shown(window) == 'New one (disabled)'
    assert window.unsaved_changes
    assert window.GetTitle().endswith('*')


def test_new_emulator_is_not_lost_on_close(window, data_dir, monkeypatch):
    create_emulator(window, monkeypatch, 'New one')
    FakeDialog.answer = wx.ID_CANCEL
    close_window(window, 'close_button')
    assert FakeDialog.shown == 1  # Asked whether to save
    assert is_open(window)


@pytest.mark.parametrize('name', ['', '   ', 'zeta', 'ALPHA', ' Mid '])
def test_create_rejects_blank_and_duplicate_names(window, monkeypatch, name):
    messages = []
    monkeypatch.setattr(wx, 'MessageBox', lambda message, *args, **kwargs: messages.append(message))
    create_emulator(window, monkeypatch, name)
    assert window.emulator_list == ['Zeta', 'Alpha', 'Mid']
    assert len(messages) == 1
    assert not window.unsaved_changes


# ----------------------------------------------------------------------------------------------------------------------
# The emulator count
def test_count_follows_creates_and_deletes(window, monkeypatch):
    assert window.info_text.GetLabel() == 'Number of alternate emulator engines in file: 3'
    create_emulator(window, monkeypatch, 'New one')
    assert window.info_text.GetLabel().endswith(': 4')
    delete_shown_emulator(window)
    delete_shown_emulator(window)
    assert window.info_text.GetLabel().endswith(': 2')


def test_count_works_in_a_translation_without_a_colon_and_space(window, monkeypatch):
    chinese = {'Number of alternate emulator engines in file: {}': '文件中备用模拟器引擎的数量：{}'}
    monkeypatch.setattr(alternate_emulators, '_', lambda text: chinese.get(text, text))
    create_emulator(window, monkeypatch, 'New one')  # Used to crash reading the count back out of the label
    assert window.info_text.GetLabel() == '文件中备用模拟器引擎的数量：4'
    delete_shown_emulator(window)
    assert window.info_text.GetLabel() == '文件中备用模拟器引擎的数量：3'


# ----------------------------------------------------------------------------------------------------------------------
# Choosing the emulator when a game is started (rungame.EngineSelector)
from pathlib import Path
from types import SimpleNamespace
import rungame

ENGINE_CHOICE_XML = '''<pfemame author="gfinch">
    <machine name="Off" pathToEmulator="C:\\emu\\off.exe" romFolder="Default" useThisEngine="False" includeExtension="False" includeFolderPath="False">
        <description>Arcade</description>
        <extraCommands></extraCommands>
        <extensions>zip</extensions>
        <game name="___" fileName="shared"/>
        <game name="___" fileName="offonly"/>
    </machine>
    <machine name="On" pathToEmulator="C:\\emu\\on.exe" romFolder="C:\\on roms" useThisEngine="True" includeExtension="False" includeFolderPath="False">
        <description>Arcade</description>
        <extraCommands></extraCommands>
        <extensions>zip</extensions>
        <game name="___" fileName="shared"/>
        <game name="___" fileName="ononly"/>
    </machine>
    <machine name="On too" pathToEmulator="C:\\emu\\ontoo.exe" romFolder="Default" useThisEngine="True" includeExtension="False" includeFolderPath="False">
        <description>Arcade</description>
        <extraCommands></extraCommands>
        <extensions>zip</extensions>
        <game name="___" fileName="shared"/>
    </machine>
</pfemame>
'''


def engine_for(data_dir, rom_file_name: str, system_file_name: str = '', force_mame: bool = False):
    (data_dir / 'non_mame_emulators.xml').write_text(ENGINE_CHOICE_XML, encoding='utf-8')
    settings = SimpleNamespace(folders_roms=Path('mame roms'), rom_folders=[Path('mame roms')])
    engine = rungame.EngineSelector(settings, force_mame, rom_file_name, system_file_name).determine()
    assert settings.rom_folders == [Path('mame roms')]  # determine() leaves the settings alone
    rungame.EngineSelector.apply_rom_folder(settings, engine)
    return engine['engine'], settings


def test_rom_under_a_disabled_and_an_enabled_emulator_uses_the_enabled_one(data_dir):
    engine, settings = engine_for(data_dir, 'shared')
    assert engine == 'On'  # Used to be MAME, as the disabled 'Off' was found first
    assert settings.rom_folders == [Path(r'C:\on roms')]


def test_first_enabled_emulator_wins(data_dir):
    assert engine_for(data_dir, 'shared')[0] == 'On'  # Not 'On too', which comes later


def test_rom_only_under_a_disabled_emulator_runs_in_mame(data_dir):
    engine, settings = engine_for(data_dir, 'offonly')
    assert engine == 'mame'
    assert settings.rom_folders == [Path('mame roms')]


def test_other_cases_unchanged(data_dir):
    assert engine_for(data_dir, 'ononly')[0] == 'On'
    assert engine_for(data_dir, 'pacman')[0] == 'mame'
    assert engine_for(data_dir, 'pacman', system_file_name='ononly')[0] == 'On'
    assert engine_for(data_dir, 'ononly', force_mame=True)[0] == 'mame'


# ----------------------------------------------------------------------------------------------------------------------
# Saving the XML file safely
from emulator_config import write_file_safely


def leftover_temp_files(folder) -> list:
    return [p.name for p in folder.iterdir() if p.suffix == '.tmp']


def test_write_new_file(tmp_path):
    path = tmp_path / 'non_mame_emulators.xml'
    write_file_safely(str(path), 'new\n')
    assert path.read_text(encoding='utf-8') == 'new\n'
    assert not (tmp_path / 'non_mame_emulators.xml.bak').exists()  # Nothing to back up
    assert leftover_temp_files(tmp_path) == []


def test_write_keeps_a_backup_of_the_old_file(tmp_path):
    path = tmp_path / 'non_mame_emulators.xml'
    path.write_text('old\n', encoding='utf-8')
    write_file_safely(str(path), 'new\n')
    assert path.read_text(encoding='utf-8') == 'new\n'
    assert (tmp_path / 'non_mame_emulators.xml.bak').read_text(encoding='utf-8') == 'old\n'
    assert leftover_temp_files(tmp_path) == []


def test_failed_write_leaves_the_old_file(tmp_path, monkeypatch):
    path = tmp_path / 'non_mame_emulators.xml'
    path.write_text('old\n', encoding='utf-8')

    def fail(*args):
        raise OSError('disk full')
    monkeypatch.setattr(emulator_config.os, 'replace', fail)
    with pytest.raises(OSError):
        write_file_safely(str(path), 'new\n')
    assert path.read_text(encoding='utf-8') == 'old\n'
    assert leftover_temp_files(tmp_path) == []


def test_window_save_backs_up_and_still_loads(window, data_dir):
    make_a_change(window)
    assert window.on_update_xml(-1) is True
    assert (data_dir / 'non_mame_emulators.xml.bak').read_text(encoding='utf-8') == EXISTING_FORMAT_XML
    assert '<extraCommands>-changed</extraCommands>' in saved_xml(data_dir)
    assert saved_names() == ['Zeta', 'Alpha', 'Mid']
    assert leftover_temp_files(data_dir) == []


def test_window_save_that_fails_keeps_the_file_and_the_changes(window, data_dir, monkeypatch):
    messages = []
    monkeypatch.setattr(wx, 'MessageBox', lambda message, *args, **kwargs: messages.append(message))

    def fail(*args):
        raise OSError('disk full')
    monkeypatch.setattr(emulator_config.os, 'replace', fail)
    make_a_change(window)
    assert window.on_update_xml(-1) is False
    assert 'Unable to write' in messages[0]
    assert saved_xml(data_dir) == EXISTING_FORMAT_XML
    assert window.unsaved_changes


# ----------------------------------------------------------------------------------------------------------------------
# Warnings about likely mistakes before saving
from alternate_emulators import find_setup_problems  # The real one (the window fixture swaps it out)


def emulator_rows(name, path, rom_folder, enabled, rom_files) -> list:
    return [[name, path, rom_folder, 'Arcade', enabled, False, False, '', 'zip', '___', rom_file]
            for rom_file in rom_files]


@pytest.fixture
def setup_ok(tmp_path):
    """A program and a ROM folder that exist."""
    program = tmp_path / 'emu.exe'
    program.write_text('')
    roms = tmp_path / 'roms'
    roms.mkdir()
    return str(program), str(roms)


def test_no_problems(setup_ok):
    program, roms = setup_ok
    rows = (emulator_rows('A', program, roms, True, ['one', 'two']) +
            emulator_rows('B', program, 'Default', True, ['three']))
    assert find_setup_problems(rows) == []


def test_missing_program_and_folder(setup_ok, tmp_path):
    program, roms = setup_ok
    rows = (emulator_rows('A', str(tmp_path / 'gone.exe'), str(tmp_path / 'gone'), True, ['one']) +
            emulator_rows('B', '', '', True, ['two']))
    problems = find_setup_problems(rows)
    assert len(problems) == 4
    assert 'A: the emulator program' in problems[0] and 'gone.exe' in problems[0]
    assert 'A: the ROM folder' in problems[1]
    assert problems[2] == 'B: no emulator program has been set.'
    assert problems[3].startswith('B: no ROM folder has been set')


def test_disabled_emulators_are_not_checked_for_program_and_folder(tmp_path):
    rows = emulator_rows('Off', str(tmp_path / 'gone.exe'), str(tmp_path / 'gone'), False, ['one'])
    assert find_setup_problems(rows) == []


def test_rom_listed_twice_in_one_emulator(setup_ok):
    program, roms = setup_ok
    rows = emulator_rows('A', program, roms, False, ['one', 'two', 'ONE', 'one'])
    assert find_setup_problems(rows) == ['A: ONE is listed more than once.']


def test_rom_under_two_enabled_emulators(setup_ok):
    program, roms = setup_ok
    rows = (emulator_rows('A', program, roms, True, ['shared', 'a']) +
            emulator_rows('Off', program, roms, False, ['shared']) +
            emulator_rows('B', program, roms, True, ['shared', 'b']))
    assert find_setup_problems(rows) == ['shared is listed under both A and B.  Only A will be used.']


@pytest.fixture
def real_problem_check(window, monkeypatch):
    """The window's 'save anyway?' check, with the warning text recorded."""
    monkeypatch.setattr(alternate_emulators, 'find_setup_problems', find_setup_problems)
    messages = []

    class RecordingDialog(FakeDialog):
        def __init__(self, parent, message, *args, **kwargs):
            messages.append(message)
    monkeypatch.setattr(wx, 'MessageDialog', RecordingDialog)
    return messages


@pytest.mark.parametrize('answer, saved', [(wx.ID_NO, False), (wx.ID_YES, True)])
def test_save_warns_and_asks(window, data_dir, real_problem_check, answer, saved):
    make_a_change(window)
    FakeDialog.answer = answer
    assert window.on_update_xml(-1) is saved
    assert 'zeta.exe was not found' in real_problem_check[0]  # The test emulators' programs don't exist
    assert 'Would you like to save anyway?' in real_problem_check[0]
    assert ('<extraCommands>-changed</extraCommands>' in saved_xml(data_dir)) == saved
    assert window.unsaved_changes != saved


def test_long_warnings_are_cut_short(window, real_problem_check, monkeypatch):
    many = [f'problem {n}' for n in range(40)]
    monkeypatch.setattr(alternate_emulators, 'find_setup_problems', lambda rows: many)
    make_a_change(window)
    window.on_update_xml(-1)
    message = real_problem_check[0]
    assert '- problem 14' in message
    assert '- problem 15' not in message
    assert '... and 25 more.' in message


def test_delete_does_not_warn(window, real_problem_check):
    delete_shown_emulator(window)
    assert len(real_problem_check) == 1  # Only the 'are you sure' question
    assert saved_names() == ['Alpha', 'Mid']


# ----------------------------------------------------------------------------------------------------------------------
# Labels can be translated
@pytest.fixture
def marked_translation(monkeypatch):
    """Every text passed through _() comes back in [brackets].  Listed before 'window' so it applies to it."""
    monkeypatch.setattr(alternate_emulators, '_', lambda text: f'[{text}]')


def test_window_labels_are_translated(marked_translation, window):
    for checkbox in (window.checkbox_enabled, window.checkbox_include_extension, window.checkbox_include_folder_path):
        assert checkbox.GetLabel().startswith('[')
    assert window.list_control.GetColumn(0).GetText() == '[ROM Name]'
    assert window.list_control.GetColumn(1).GetText() == '[ROM File Name (No Extn)]'


def test_dialog_labels_are_translated(marked_translation, wx_app):
    dlg = alternate_emulators.RomInfo('rom', 'file')
    try:
        assert dlg.GetTitle() == '[ROM Info]'
        labels = [child.GetLabel() for child in dlg.GetChildren() if isinstance(child, wx.StaticText)]
        assert labels == ['[ROM Name:]', '[ROM File Name:]']
    finally:
        dlg.Destroy()

    dlg = alternate_emulators.DefaultSettings(['one'])
    try:
        assert dlg.GetTitle() == '[Default Settings Selection]'
    finally:
        dlg.Destroy()
    wx_app.Yield(True)


# ----------------------------------------------------------------------------------------------------------------------
# ROM list right-click menu
def test_right_click_menu_handlers_belong_to_the_menu(window, monkeypatch):
    edited = []
    monkeypatch.setattr(window, 'on_edit_rom_entry', lambda row: edited.append(row))
    monkeypatch.setattr(window.list_control, 'HitTest', lambda position: (1, 0))  # Right-click on the 2nd ROM
    menus = []
    monkeypatch.setattr(alternate_emulators, 'show_popup_menu', lambda parent, menu: menus.append(menu))

    for _unused in range(2):
        window.on_right_click_list(wx.MouseEvent(wx.wxEVT_RIGHT_DOWN))

    # Choosing Edit on the menu edits the row clicked
    menus[-1].ProcessEvent(wx.CommandEvent(wx.wxEVT_MENU, wx.ID_EDIT))
    assert edited == [1]

    # ... and nothing was left bound to the window itself (those handlers used to build up with each right-click)
    edited.clear()
    window.ProcessEvent(wx.CommandEvent(wx.wxEVT_MENU, wx.ID_EDIT))
    assert edited == []
    for menu in menus:
        menu.Destroy()


# ----------------------------------------------------------------------------------------------------------------------
# emulator_config: saving and loading
def test_save_and_load_round_trip(tmp_path):
    original = tmp_path / 'original.xml'
    original.write_text(EXISTING_FORMAT_XML, encoding='utf-8')
    rows, error = emulator_config.load_emulators(str(original))
    assert not error

    saved = tmp_path / 'saved.xml'
    emulator_config.save_emulators(str(saved), rows)
    assert emulator_config.load_emulators(str(saved)) == (rows, False)


def test_rows_for_one_emulator_needn_t_be_together(tmp_path):
    rows = (emulator_rows('A', 'a.exe', 'Default', True, ['one']) +
            emulator_rows('B', 'b.exe', 'Default', True, ['two']) +
            emulator_rows('A', 'a.exe', 'Default', True, ['three']))  # Used to be saved under B
    path = tmp_path / 'emulators.xml'
    emulator_config.save_emulators(str(path), rows)
    loaded, _error = emulator_config.load_emulators(str(path))
    assert [(r[0], r[10]) for r in loaded] == [('A', 'one'), ('A', 'three'), ('B', 'two')]


def test_missing_file_is_no_emulators_and_no_error(tmp_path):
    assert emulator_config.load_emulators(str(tmp_path / 'missing.xml')) == ([], False)


# ----------------------------------------------------------------------------------------------------------------------
# Renaming and duplicating emulators
def type_name(monkeypatch, name: str, answer: int = wx.ID_OK) -> list:
    """Answer the next name pop-up with the name; returns the value each pop-up started with."""
    started_with = []

    class FakeTextEntry(FakeDialog):
        def __init__(self, parent, message, caption='', value=''):
            started_with.append(value)

        def ShowModal(self):
            return answer

        def GetValue(self):
            return name
    monkeypatch.setattr(wx, 'TextEntryDialog', FakeTextEntry)
    return started_with


def zeta_rows(frame) -> list:
    return [row for row in frame.alternate_emulation_engines if row[0] == 'Zeta']


def test_rename_keeps_settings_and_roms(window, data_dir, monkeypatch):
    before = [row[1:] for row in zeta_rows(window)]
    started_with = type_name(monkeypatch, '  Zeta Two  ')
    window.on_rename_emulator(None)
    assert started_with == ['Zeta']
    assert window.emulator_list == ['Zeta Two', 'Alpha', 'Mid']
    assert shown(window) == 'Zeta Two'
    assert [row[1:] for row in window.alternate_emulation_engines if row[0] == 'Zeta Two'] == before
    assert window.unsaved_changes

    assert window.on_update_xml(-1) is True
    assert saved_names() == ['Zeta Two', 'Alpha', 'Mid']


def test_rename_can_change_just_the_case(window, monkeypatch):
    type_name(monkeypatch, 'ZETA')
    window.on_rename_emulator(None)
    assert window.emulator_list == ['ZETA', 'Alpha', 'Mid']


@pytest.mark.parametrize('name, answer', [('alpha', wx.ID_OK), ('', wx.ID_OK), ('Zeta', wx.ID_OK),
                                          ('Other', wx.ID_CANCEL)])
def test_rename_refused_or_cancelled_changes_nothing(window, monkeypatch, name, answer):
    monkeypatch.setattr(wx, 'MessageBox', lambda *args, **kwargs: wx.ID_OK)
    type_name(monkeypatch, name, answer)
    window.on_rename_emulator(None)
    assert window.emulator_list == ['Zeta', 'Alpha', 'Mid']
    assert not window.unsaved_changes


def test_duplicate_copies_settings_and_roms_disabled(window, monkeypatch):
    started_with = type_name(monkeypatch, 'Zeta copy')
    window.on_duplicate_emulator(None)
    assert started_with == ['Zeta (copy)']
    assert window.emulator_list == ['Zeta', 'Alpha', 'Mid', 'Zeta copy']
    assert shown(window) == 'Zeta copy (disabled)'
    assert window.info_text.GetLabel().endswith(': 4')

    copy = [row for row in window.alternate_emulation_engines if row[0] == 'Zeta copy']
    original = zeta_rows(window)
    assert [(r[9], r[10]) for r in copy] == [(r[9], r[10]) for r in original]
    assert all(r[1:4] + r[5:9] == o[1:4] + o[5:9] for r, o in zip(copy, original))
    assert [r[4] for r in copy] == [False, False]  # Disabled, so the ROMs still run with Zeta
    assert all(o[4] for o in original)

    # The copy is on screen, and editing it doesn't touch the original
    assert not window.checkbox_enabled.GetValue()
    assert window.list_control.GetItemCount() == 2
    window.text_ctrl_extra_commands.SetValue('-copy only')
    assert [r[7] for r in zeta_rows(window)] == ['', '']
    assert window.unsaved_changes


def test_duplicate_refused_name(window, monkeypatch):
    monkeypatch.setattr(wx, 'MessageBox', lambda *args, **kwargs: wx.ID_OK)
    type_name(monkeypatch, 'MID')
    window.on_duplicate_emulator(None)
    assert window.emulator_list == ['Zeta', 'Alpha', 'Mid']
    assert not window.unsaved_changes


# ----------------------------------------------------------------------------------------------------------------------
# Choosing the emulator from the selector
def choose(frame, index: int) -> None:
    frame.on_emulator_chosen(SimpleNamespace(selection=index))  # As sent when an emulator is picked from the list


def test_selector_lists_every_emulator(window):
    assert window.emulator_selector.GetChoices() == ['Zeta', 'Alpha (disabled)', 'Mid']
    assert window.emulator_selector.IsEnabled()


def test_choosing_an_emulator_shows_it(window):
    choose(window, 2)
    assert window.current_emulator == 'Mid'
    assert shown(window) == 'Mid'
    assert [window.get_rom_detail(row) for row in range(window.list_control.GetItemCount())] == [('___', 'vf3')]
    assert not window.unsaved_changes  # Just looking

    window.emulators_list_left(None)  # The arrows still step, and the selector follows
    assert shown(window) == 'Alpha (disabled)'
    assert window.text_ctrl_extra_commands.GetValue() == '-fullscreen'


def test_selector_follows_enabled(window):
    window.checkbox_enabled.SetValue(False)
    window.on_control_changed(None)  # As sent when the box is clicked
    assert shown(window) == 'Zeta (disabled)'
    assert window.emulator_selector.GetChoices()[0] == 'Zeta (disabled)'
    window.checkbox_enabled.SetValue(True)
    window.on_control_changed(None)
    assert shown(window) == 'Zeta'


def test_selector_follows_rename_and_delete(window, monkeypatch):
    type_name(monkeypatch, 'Zeta Two')
    window.on_rename_emulator(None)
    assert window.emulator_selector.GetChoices() == ['Zeta Two', 'Alpha (disabled)', 'Mid']
    choose(window, 2)
    delete_shown_emulator(window)
    assert window.emulator_selector.GetChoices() == ['Zeta Two', 'Alpha (disabled)']
    assert shown(window) == 'Alpha (disabled)'


# ----------------------------------------------------------------------------------------------------------------------
# ROM list: search, sort and deleting several at once
FOUR_ROMS_XML = '''<pfemame author="gfinch">
    <machine name="Four" pathToEmulator="four.exe" romFolder="Default" useThisEngine="True" includeExtension="False" includeFolderPath="False">
        <description>Arcade</description>
        <extraCommands></extraCommands>
        <extensions>zip</extensions>
        <game name="Daytona USA" fileName="daytona"/>
        <game name="___" fileName="vf2"/>
        <game name="Virtua Cop" fileName="vcop"/>
        <game name="Arcade Racer" fileName="zracer"/>
    </machine>
</pfemame>
'''
four_roms = pytest.mark.parametrize('xml_text', [FOUR_ROMS_XML])


def select_rows(frame, rows) -> None:
    for row in range(frame.list_control.GetItemCount()):
        frame.list_control.Select(row, row in rows)


def saved_roms(frame) -> list:
    return [(row[9], row[10]) for row in frame.alternate_emulation_engines if row[0] == frame.current_emulator]


ALL_FOUR = [('Daytona USA', 'daytona'), ('___', 'vf2'), ('Virtua Cop', 'vcop'), ('Arcade Racer', 'zracer')]


@four_roms
def test_search_shows_matching_roms_only(window, xml_text):
    window.rom_search.SetValue('V')  # Matches a name or a file name, ignoring case
    assert rom_list(window) == [('___', 'vf2'), ('Virtua Cop', 'vcop')]
    window.rom_search.SetValue('racer')
    assert rom_list(window) == [('Arcade Racer', 'zracer')]
    window.rom_search.SetValue('')
    assert rom_list(window) == ALL_FOUR
    assert not window.unsaved_changes  # Searching changes nothing


@four_roms
def test_editing_while_searching_keeps_the_hidden_roms(window, xml_text, monkeypatch):
    window.rom_search.SetValue('cop')
    window.text_ctrl_extra_commands.SetValue('-changed')  # Any edit rebuilds the emulator's rows
    assert saved_roms(window) == ALL_FOUR

    class FakeRomInfo:
        def __init__(self, rom_name, rom_file_name):
            self.text_rom_name = SimpleNamespace(GetValue=lambda: 'Virtua Cop (World)')
            self.text_rom_file_name = SimpleNamespace(GetValue=lambda: rom_file_name)

        def ShowModal(self):
            return wx.ID_OK

        def Destroy(self):
            pass
    monkeypatch.setattr(alternate_emulators, 'RomInfo', FakeRomInfo)
    window.on_edit_rom_entry(0)  # The only row shown
    assert saved_roms(window)[2] == ('Virtua Cop (World)', 'vcop')
    assert len(saved_roms(window)) == 4


@four_roms
def test_sort_by_a_column_and_reverse(window, xml_text):
    window.on_rom_column_click(SimpleNamespace(GetColumn=lambda: 1))
    assert [r[1] for r in rom_list(window)] == ['daytona', 'vcop', 'vf2', 'zracer']
    window.on_rom_column_click(SimpleNamespace(GetColumn=lambda: 1))
    assert [r[1] for r in rom_list(window)] == ['zracer', 'vf2', 'vcop', 'daytona']
    window.on_rom_column_click(SimpleNamespace(GetColumn=lambda: 0))
    assert [r[0] for r in rom_list(window)] == ['___', 'Arcade Racer', 'Daytona USA', 'Virtua Cop']
    assert saved_roms(window) == rom_list(window)  # Saved in the new order
    assert window.unsaved_changes


@four_roms
def test_delete_several_with_the_delete_key(window, xml_text):
    select_rows(window, {1, 3})
    FakeDialog.answer = wx.ID_YES
    window.on_rom_list_key(SimpleNamespace(GetKeyCode=lambda: wx.WXK_DELETE))
    assert rom_list(window) == [('Daytona USA', 'daytona'), ('Virtua Cop', 'vcop')]
    assert saved_roms(window) == rom_list(window)


@four_roms
def test_delete_while_searching_only_deletes_what_was_selected(window, xml_text):
    window.rom_search.SetValue('v')
    select_rows(window, {0})  # vf2
    FakeDialog.answer = wx.ID_YES
    window.on_delete_selected_roms()
    window.rom_search.SetValue('')
    assert rom_list(window) == [('Daytona USA', 'daytona'), ('Virtua Cop', 'vcop'), ('Arcade Racer', 'zracer')]


@four_roms
def test_cannot_delete_every_rom(window, xml_text, monkeypatch):
    messages = []
    monkeypatch.setattr(wx, 'MessageBox', lambda message, *args, **kwargs: messages.append(message))
    select_rows(window, {0, 1, 2, 3})
    window.on_delete_selected_roms()
    assert len(rom_list(window)) == 4
    assert 'cannot delete the last row' in messages[0]


@four_roms
def test_right_click_keeps_a_multiple_selection(window, xml_text, monkeypatch):
    select_rows(window, {0, 2})
    monkeypatch.setattr(window.list_control, 'HitTest', lambda position: (2, 0))  # On a selected row
    menus = []
    monkeypatch.setattr(alternate_emulators, 'show_popup_menu', lambda parent, menu: menus.append(menu))
    window.on_right_click_list(wx.MouseEvent(wx.wxEVT_RIGHT_DOWN))
    assert window._selected_entries() == [0, 2]
    assert menus[0].FindItemById(wx.ID_DELETE).GetItemLabelText() == 'Delete 2 ROM Entries'

    monkeypatch.setattr(window.list_control, 'HitTest', lambda position: (1, 0))  # On an unselected row
    window.on_right_click_list(wx.MouseEvent(wx.wxEVT_RIGHT_DOWN))
    assert window._selected_entries() == [1]
    for menu in menus:
        menu.Destroy()


@four_roms
def test_adding_a_rom_clears_the_search_and_selects_it(window, xml_text, monkeypatch):
    class FakeRomInfo:
        def __init__(self, rom_name, rom_file_name):
            self.text_rom_name = SimpleNamespace(GetValue=lambda: 'New')
            self.text_rom_file_name = SimpleNamespace(GetValue=lambda: 'newrom')

        def ShowModal(self):
            return wx.ID_OK

        def Destroy(self):
            pass
    monkeypatch.setattr(alternate_emulators, 'RomInfo', FakeRomInfo)
    window.rom_search.SetValue('cop')
    window.on_add_rom_entry(None)
    assert window.rom_search.GetValue() == ''
    assert rom_list(window)[-1] == ('New', 'newrom')
    assert window._selected_entries() == [4]
    assert len(saved_roms(window)) == 5


@four_roms
def test_auto_scan_keeps_roms_hidden_by_the_search(window, xml_text, tmp_path):
    window.text_ctrl_rom_folder.SetPath(make_files(tmp_path / 'roms', ['daytona.zip', 'vf2.zip', 'vcop.zip',
                                                                          'zracer.zip', 'extra.zip']))
    window.on_control_changed(None)
    window.rom_search.SetValue('cop')
    window.on_add_rom_entry_auto(None)
    assert FakeDialog.shown == 0  # Nothing missing, so not asked about removing any
    assert saved_roms(window) == ALL_FOUR + [('___', 'extra')]


@four_roms
def test_changing_emulator_clears_the_search(window, xml_text, monkeypatch):
    window.rom_search.SetValue('cop')
    create_emulator(window, monkeypatch, 'Other')
    assert window.rom_search.GetValue() == ''
    choose(window, 0)
    assert window.rom_search.GetValue() == ''
    assert rom_list(window) == ALL_FOUR


@four_roms
def test_list_events_reach_the_handlers(window, xml_text):
    import wx.lib.agw.ultimatelistctrl as ulc
    click = ulc.UltimateListEvent(ulc.wxEVT_COMMAND_LIST_COL_CLICK, window.list_control.GetId())
    click.m_col = 1
    window.list_control.GetEventHandler().ProcessEvent(click)  # A click on the File Name heading
    assert [r[1] for r in rom_list(window)] == ['daytona', 'vcop', 'vf2', 'zracer']

    select_rows(window, {0})
    FakeDialog.answer = wx.ID_YES
    key = ulc.UltimateListEvent(ulc.wxEVT_COMMAND_LIST_KEY_DOWN, window.list_control.GetId())
    key.m_code = wx.WXK_DELETE
    window.list_control.GetEventHandler().ProcessEvent(key)
    assert [r[1] for r in rom_list(window)] == ['vcop', 'vf2', 'zracer']


# ----------------------------------------------------------------------------------------------------------------------
# Naming ROMs from MAME's machine list
DESCRIPTIONS = {'vf2': 'Virtua Fighter 2 (Version 2.1)', 'daytona': 'Daytona USA (Revision A)',
                'desert': 'Desert Tank'}


def test_fill_rom_names_only_names_unnamed_mame_roms():
    entries = [('Daytona', 'daytona'), ('___', 'vf2'), ('', 'DESERT'), ('___', 'pinball'),
               emulator_config.PLACEHOLDER_ROM_ENTRY]
    result, filled, still_unnamed = emulator_config.fill_rom_names(entries, DESCRIPTIONS)
    assert result == [('Daytona', 'daytona'),  # Typed names are kept
                      ('Virtua Fighter 2 (Version 2.1)', 'vf2'),
                      ('Desert Tank', 'DESERT'),  # Matched ignoring case
                      ('___', 'pinball'),  # Not a MAME machine
                      emulator_config.PLACEHOLDER_ROM_ENTRY]
    assert (filled, still_unnamed) == (2, 2)


def test_scan_names_new_entries():
    merged, added, _missing = merge_scanned_roms([('Mine', 'daytona')], ['daytona', 'vf2', 'pinball'], DESCRIPTIONS)
    assert merged == [('Mine', 'daytona'), ('Virtua Fighter 2 (Version 2.1)', 'vf2'), ('___', 'pinball')]
    assert added == 2


@pytest.fixture
def machine_list(data_dir):
    """A machines.cache like the one saved when the ROM database is built."""
    import rom_database
    machines = [rom_database.Machine(name, description, '1995', 'Sega', '', (), False, ())
                for name, description in DESCRIPTIONS.items()]
    rom_database.save_machine_cache(str(data_dir / rom_database.MACHINE_CACHE_NAME), '0.289', machines)


def test_fill_rom_names_button(machine_list, window, monkeypatch):
    messages = []
    monkeypatch.setattr(wx, 'MessageBox', lambda message, *args, **kwargs: messages.append(message))
    window.on_fill_rom_names(None)
    assert rom_list(window) == [('Daytona', 'daytona'), ('Desert Tank', 'desert')]  # 'Daytona' kept
    assert saved_roms(window) == rom_list(window)
    assert window.unsaved_changes
    assert messages == ['ROM names filled in: 1']


def test_fill_rom_names_reports_roms_it_cannot_name(machine_list, window, monkeypatch):
    messages = []
    monkeypatch.setattr(wx, 'MessageBox', lambda message, *args, **kwargs: messages.append(message))
    choose(window, 2)  # Mid: vf3, which isn't in the test machine list
    window.on_fill_rom_names(None)
    assert rom_list(window) == [('___', 'vf3')]
    assert not window.unsaved_changes
    assert messages == ['ROM names filled in: 0\nROMs still without a name (not MAME machines): 1']


def test_fill_rom_names_without_a_machine_list(window, monkeypatch):
    messages = []
    monkeypatch.setattr(wx, 'MessageBox', lambda message, *args, **kwargs: messages.append(message))
    window.on_fill_rom_names(None)
    assert 'build the ROM database first' in messages[0]
    assert rom_list(window) == [('Daytona', 'daytona'), ('___', 'desert')]


def test_auto_scan_names_new_roms(machine_list, window, tmp_path):
    window.text_ctrl_rom_folder.SetPath(make_files(tmp_path / 'roms', ['daytona.zip', 'desert.zip', 'vf2.zip',
                                                                          'pinball.zip']))
    window.on_control_changed(None)
    window.on_add_rom_entry_auto(None)
    assert rom_list(window) == [('Daytona', 'daytona'), ('___', 'desert'),  # Existing entries left alone
                                ('___', 'pinball'), ('Virtua Fighter 2 (Version 2.1)', 'vf2')]


# ----------------------------------------------------------------------------------------------------------------------
# SET DEFAULTS (using the non_mame_defaults.xml that ships with pfeMAME)
def apply_preset(frame, monkeypatch, preset: str) -> None:
    class FakeDefaultSettings:
        def __init__(self, names):
            assert preset in names
            self.control_selection = SimpleNamespace(GetValue=lambda: preset)

        def ShowModal(self):
            return wx.ID_OK

        def Destroy(self):
            pass
    monkeypatch.setattr(alternate_emulators, 'DefaultSettings', FakeDefaultSettings)
    frame.on_set_defaults(None)


def test_preset_with_its_own_folder_clears_default(window, monkeypatch):
    assert window.text_ctrl_rom_folder.GetPath() == 'Default'  # Zeta
    apply_preset(window, monkeypatch, 'Visual Pinball X')
    assert window.text_ctrl_rom_folder.GetPath() == ''  # To be chosen, rather than MAME's ROM folder
    assert window.text_ctrl_extra_commands.GetValue() == '-minimized -exit -play'
    assert [r[2] for r in zeta_rows(window)] == ['', '']
    assert window.unsaved_changes


def test_preset_with_its_own_folder_keeps_a_chosen_folder(window, monkeypatch, tmp_path):
    window.text_ctrl_rom_folder.SetPath(str(tmp_path))
    apply_preset(window, monkeypatch, 'Visual Pinball X')
    assert window.text_ctrl_rom_folder.GetPath() == str(tmp_path)


def test_preset_using_the_default_folder_sets_it(window, monkeypatch):
    window.text_ctrl_rom_folder.SetPath('')
    apply_preset(window, monkeypatch, 'SEGA M2 Emulator')
    assert window.text_ctrl_rom_folder.GetPath() == 'Default'
    assert window.text_ctrl_valid_extension.GetValue() == 'zip 7z'


# ----------------------------------------------------------------------------------------------------------------------
# The alternate emulator's command line (rungame.CommandBuilder), with and without {rom} in the extra commands
# Paths in this platform's own form (C:\VPX\... on Windows, /VPX/... on Linux / macOS)
ROOT = Path(os.path.abspath(os.sep))
EMULATOR = str(ROOT / 'VPX' / 'VPinballX.exe')
TABLES = str(ROOT / 'VPX' / 'tables')


def alt_command(extra_commands: str, rom_folder: str = TABLES) -> list[str]:
    config = SimpleNamespace(rom_file_name='attack', system_file_name='')
    settings = SimpleNamespace(rom_folders=[Path('mame roms')], folders_roms=Path('mame roms'))
    engine_info = {'engine': 'VPX', 'path': EMULATOR, 'rom_folder': rom_folder,
                   'include_extension': False, 'include_folder_path': False, 'extra_commands': extra_commands,
                   'extensions': ['vpx']}
    cmd, cwd = rungame.CommandBuilder(config, settings, engine_info).build_alt_command()
    assert cwd == ROOT / 'VPX'
    return cmd


ROM = str(Path(TABLES) / 'attack')


def test_rom_goes_last_without_a_placeholder():
    assert alt_command('') == [EMULATOR, ROM]
    assert alt_command('-minimized -exit -play') == [EMULATOR, '-minimized', '-exit', '-play', ROM]


def test_rom_goes_where_the_placeholder_is():
    assert alt_command('-minimized -play {rom} -exit') == [EMULATOR, '-minimized', '-play', ROM, '-exit']
    assert alt_command('-file={rom}') == [EMULATOR, f'-file={ROM}']  # Part of an argument


def test_placeholder_with_quoted_arguments_and_spaces():
    my_tables = str(ROOT / 'My Tables')
    rom = str(Path(my_tables) / 'attack')
    assert alt_command('"-title=Big Game" -play {rom}', rom_folder=my_tables) == \
        [EMULATOR, '-title=Big Game', '-play', rom]
