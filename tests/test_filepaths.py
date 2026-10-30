"""File Paths tab: what Apply writes, how it reports a failed write, where ui.ini is, and reverting edits."""
import dataclasses
import os
import subprocess

import pytest
import wx

import filepaths
import iniFile
import mame_paths

REAL_RUN = subprocess.run


class _FakeDialog:
    """Stands in for the modal dialogs ('File paths saved', 'discard changes?')."""
    answer = wx.ID_OK

    def __init__(self, *args, **kwargs):
        pass

    def ShowModal(self):
        return _FakeDialog.answer

    def Destroy(self):
        pass


@pytest.fixture
def panel(wx_app, data_dir, tmp_path, monkeypatch):
    """A real FilePaths panel with MAME, dialogs and pubsub faked out."""
    errors, messages, error_texts = [], [], []
    monkeypatch.setattr(filepaths, '_', lambda text: text, raising=False)  # pfemame.py normally installs _()
    old_log = wx.Log.SetActiveTarget(wx.LogStderr())     # Any wx error goes to the test output, not a pop-up box
    monkeypatch.setattr(filepaths, 'show_error_dialog', lambda _parent, msg, title: (errors.append(title), error_texts.append(msg)))
    monkeypatch.setattr(filepaths.pub, 'sendMessage', lambda topic, **_kw: messages.append(topic))
    monkeypatch.setattr(wx, 'MessageDialog', _FakeDialog)
    _FakeDialog.answer = wx.ID_OK
    monkeypatch.setattr(subprocess, 'run',
                        lambda *a, **kw: subprocess.CompletedProcess(a, 0, stdout=b'#\n# CORE CONFIGURATION OPTIONS\n'))
    # The tab asks MAME its version in a background thread - answer straight away (the version tests replace this)
    monkeypatch.setattr(filepaths.functions, 'mame_version', lambda path, timeout=30: ('0.289', ''))

    frame = wx.Frame(None)
    fp = filepaths.FilePaths(frame, my_logger=_NullLogger())
    exe = tmp_path / 'mame.exe'
    exe.write_bytes(b'')
    fp.update_table('mame_executable', str(exe))
    ini_folder = tmp_path / 'ini'
    ini_folder.mkdir()
    fp.folders_ini = str(ini_folder)
    fp.update_table('inipath', str(ini_folder))
    fp.update_table('pcbs_directory', 'D:/pcb')
    fp.data_changed = True
    fp.errors, fp.messages, fp.error_texts = errors, messages, error_texts
    fp.use_background_thread = False        # Run APPLY / AUTO FIND / MAKE INI's MAME work straight away
    yield fp
    frame.Destroy()
    wx.Log.SetActiveTarget(old_log)


class _NullLogger:
    def info(self, *_a):
        pass

    def error(self, *_a):
        pass

    def exception(self, *_a):
        pass


def test_apply_saves_and_requests_restart(panel, tmp_path):
    mame_ini = tmp_path / 'mame.ini'
    mame_ini.write_text('rompath     roms\n', encoding='utf-8')
    panel.update_table('mame_ini', str(mame_ini))
    panel.update_table('rompath', 'D:\\roms')

    panel.on_apply(None)

    assert panel.errors == []
    assert iniFile.get_from_mameini('rompath', str(mame_ini)) == 'D:\\roms'
    assert iniFile.get_from_mameini('pcbs_directory', str(tmp_path / 'ini' / 'ui.ini')) == 'D:/pcb'
    assert 'setup_ini' in panel.messages
    assert panel.data_changed is False


def test_apply_reports_a_failed_mame_ini_write(panel, tmp_path):
    panel.update_table('mame_ini', str(tmp_path / 'missing_folder' / 'mame.ini'))

    panel.on_apply(None)

    assert panel.errors == ['ERROR writing to mame.ini file']
    assert 'setup_ini' not in panel.messages
    assert 'setup_ini' not in panel.messages
    assert panel.data_changed is True


def test_apply_reports_a_failed_pfemame_ini_write(panel, tmp_path, data_dir):
    import stat
    mame_ini = tmp_path / 'mame.ini'
    mame_ini.write_text('rompath     roms\n', encoding='utf-8')
    panel.update_table('mame_ini', str(mame_ini))
    iniFile.set_ini_file_variables([('system', 'x', '1')])
    os.chmod(data_dir / 'pfemame.ini', stat.S_IREAD)       # Read-only
    try:
        if os.access(data_dir / 'pfemame.ini', os.W_OK):
            pytest.skip('running as root - every file is writable')
        panel.on_apply(None)
    finally:
        os.chmod(data_dir / 'pfemame.ini', stat.S_IREAD | stat.S_IWRITE)

    assert panel.errors == ['ERROR writing to pfemame.ini file']
    assert 'setup_ini' not in panel.messages
    assert panel.data_changed is True


def test_apply_with_blank_mame_ini_path_writes_nothing(panel, data_dir):
    panel.update_table('mame_ini', '')

    panel.on_apply(None)

    assert len(panel.errors) == 1
    assert 'setup_ini' not in panel.messages
    assert not (data_dir / 'pfemame.ini').exists()       # Apply stopped before writing anything
    assert panel.data_changed is True


def test_mame_ini_bulk_write_refuses_a_blank_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert iniFile.set_to_mameini_bulk([('roms', 'rompath', False)], '') == -1
    assert iniFile.set_to_mameini_bulk([('roms', 'rompath', False)], '   ') == -1
    assert list(tmp_path.parent.glob(f'{tmp_path.name}.tmp')) == []      # no stray temp file beside the folder


# ------------------------------------------------------------------------------------------------------------- ui.ini
@pytest.fixture
def mame_folder(tmp_path):
    folder = tmp_path / 'MAME'
    (folder / 'ini' / 'presets').mkdir(parents=True)
    (folder / 'mame.exe').write_bytes(b'')
    return folder


def test_ui_ini_found_in_the_first_inipath_folder_that_has_one(mame_folder):
    exe = str(mame_folder / 'mame.exe')
    (mame_folder / 'ini' / 'ui.ini').write_text('', encoding='utf-8')
    assert mame_paths.find_ui_ini('.;ini;ini/presets', exe) == str(mame_folder / 'ini' / 'ui.ini')


def test_ui_ini_goes_in_the_first_inipath_folder_that_exists(mame_folder):
    exe = str(mame_folder / 'mame.exe')
    assert mame_paths.find_ui_ini('missing;ini;.', exe) == str(mame_folder / 'ini' / 'ui.ini')
    assert mame_paths.find_ui_ini('missing;also_missing', exe) == ''
    assert mame_paths.find_ui_ini('', exe) == ''


def test_ui_ini_inipath_variables_are_expanded(mame_folder, monkeypatch):
    monkeypatch.setenv('MAMEHOME', str(mame_folder))
    (mame_folder / 'ui.ini').write_text('', encoding='utf-8')
    assert mame_paths.find_ui_ini('$MAMEHOME;ini') == str(mame_folder / 'ui.ini')


def test_panel_loads_ui_ini_folders_from_a_relative_inipath(panel, mame_folder):
    (mame_folder / 'mame.ini').write_text('inipath     .;ini;ini/presets\n', encoding='utf-8')
    (mame_folder / 'ini' / 'ui.ini').write_text('flyers_directory     D:/flyers\n', encoding='utf-8')
    iniFile.set_ini_file_variables([('path', 'mame_executable', str(mame_folder / 'mame.exe'))])
    panel.path_to_mame_ini_file = str(mame_folder / 'mame.ini')
    panel.folders_ini = '.;ini;ini/presets'

    panel.build_filepaths_table()

    assert panel.get_path_list_ctrl('flyers_directory') == 'D:/flyers'


def test_apply_saves_ui_ini_into_a_relative_inipath_folder(panel, mame_folder):
    mame_ini = mame_folder / 'mame.ini'
    mame_ini.write_text('', encoding='utf-8')
    panel.update_table('mame_ini', str(mame_ini))
    panel.update_table('mame_executable', str(mame_folder / 'mame.exe'))
    panel.update_table('inipath', 'missing;ini')

    panel.on_apply(None)

    assert panel.errors == []
    assert iniFile.get_from_mameini('pcbs_directory', str(mame_folder / 'ini' / 'ui.ini')) == 'D:/pcb'


def test_apply_with_no_ini_folder_reports_unsaved_ui_ini_folders(panel, tmp_path):
    mame_ini = tmp_path / 'mame.ini'
    mame_ini.write_text('', encoding='utf-8')
    panel.update_table('mame_ini', str(mame_ini))
    panel.update_table('inipath', str(tmp_path / 'missing'))

    panel.on_apply(None)
    assert panel.errors == ['ERROR writing to ui.ini file']
    assert 'setup_ini' not in panel.messages

    # ... but with no ui.ini folders set there is nothing to save there, so Apply goes ahead
    panel.errors.clear()
    panel.update_table('pcbs_directory', '')
    panel.on_apply(None)
    assert panel.errors == []
    assert 'setup_ini' in panel.messages


# ------------------------------------------------------------------------------------------------------------- revert
@pytest.fixture
def saved_paths(panel, tmp_path):
    """mame.ini on disk with one ROM folder, and the panel loaded from it."""
    mame_ini = tmp_path / 'mame.ini'
    mame_ini.write_text('rompath     D:/roms\n', encoding='utf-8')
    iniFile.set_ini_file_variables([('path', 'mame_ini', str(mame_ini))])
    panel.revert()
    return panel


def test_revert_reloads_the_saved_paths(saved_paths):
    panel = saved_paths
    assert panel.get_path_list_ctrl('rompath') == 'D:/roms'
    assert panel.data_changed is False

    rows = panel.table.row_count()
    panel.update_table('rompath', 'E:/edited')
    panel.insert_row(panel.table.get_row(0), 1)          # an added row should go again too
    panel.data_changed = True

    panel.revert()

    assert panel.get_path_list_ctrl('rompath') == 'D:/roms'
    assert panel.table.row_count() == rows == panel.list_control.GetNumberRows()
    assert panel.data_changed is False


def test_revert_button_asks_before_discarding(saved_paths):
    panel = saved_paths
    panel.update_table('rompath', 'E:/edited')
    panel.data_changed = True

    _FakeDialog.answer = wx.ID_NO
    panel.on_revert(None)
    assert panel.get_path_list_ctrl('rompath') == 'E:/edited'
    assert panel.data_changed is True

    _FakeDialog.answer = wx.ID_YES
    panel.on_revert(None)
    assert panel.get_path_list_ctrl('rompath') == 'D:/roms'
    assert panel.data_changed is False


# ---------------------------------------------------------------------------------------------------------- auto find
@pytest.fixture
def auto_find(panel, tmp_path, monkeypatch):
    """Run AUTO FIND on a fake MAME folder: returns (panel, MAME folder, run function, summaries shown)."""
    folder = tmp_path / 'AutoMAME'
    for name in ('roms', 'snap', 'ini'):
        (folder / name).mkdir(parents=True)
    elsewhere = tmp_path / 'elsewhere'                # Auto Find also looks in the working folder - keep it empty
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    class _FakeDirDialog(_FakeDialog):
        def ShowModal(self):
            return wx.ID_OK

        def GetPath(self):
            return str(folder)
    monkeypatch.setattr(wx, 'DirDialog', _FakeDirDialog)
    # Only a mame.exe inside the test folder counts as working MAME (so a real MAME on the PATH is never picked up)
    monkeypatch.setattr(panel, 'check_mame_executable', lambda path, cwd=None: path.startswith(str(tmp_path)))
    monkeypatch.setattr(panel, 'update_mame_ini_path', lambda: None)
    summaries = []
    monkeypatch.setattr(filepaths, 'show_information_dialog', lambda _parent, msg, _title: summaries.append(msg))

    def run():
        _FakeDialog.answer = wx.ID_YES
        panel.on_auto_find(None)
        _FakeDialog.answer = wx.ID_OK
    return panel, folder, run, summaries


def _paths(panel, ini_key):
    return [row.path for row in panel.table.get_all_rows() if row.ini_key == ini_key]


def test_auto_find_sets_a_multi_path_entry_to_one_row(auto_find):
    panel, folder, run, summaries = auto_find
    first = panel.table.get_all_rows().index(next(r for r in panel.table.get_all_rows() if r.ini_key == 'rompath'))
    for extra in ('E:/more roms', 'F:/even more'):
        panel.insert_row(dataclasses.replace(panel.table.get_row(first), path=extra), first + 1)

    run()

    assert _paths(panel, 'rompath') == [str(folder / 'roms')]
    assert panel.table.row_count() == panel.list_control.GetNumberRows()
    assert 'Roms folder' in summaries[0]


def test_auto_find_leaves_paths_it_does_not_find(auto_find):
    panel, folder, run, summaries = auto_find
    panel.update_table('history_dat', 'D:/history.xml')
    panel.update_table('video', 'D:/videos')

    run()

    assert _paths(panel, 'history_dat') == ['D:/history.xml']
    assert _paths(panel, 'video') == ['D:/videos']
    assert _paths(panel, 'snapshot_directory') == [str(folder / 'snap')]
    not_found = summaries[0].split('Not found (left as they were):')[1]
    assert 'History file' in not_found and 'Video folder' in not_found
    assert panel.data_changed is True


def test_auto_find_keeps_a_working_executable_it_cannot_find(auto_find):
    panel, folder, run, summaries = auto_find
    current = panel.get_path_list_ctrl('mame_executable')        # the fixture's (real) mame.exe outside the folder

    run()

    assert _paths(panel, 'mame_executable') == [current]
    assert panel.errors == []                                     # no "setting it to 'mame'" error


def test_auto_find_uses_the_mame_executable_in_the_folder(auto_find):
    panel, folder, run, summaries = auto_find
    (folder / 'mame.exe').write_bytes(b'')

    run()

    assert _paths(panel, 'mame_executable') == [str(folder / 'mame.exe')]


def test_auto_find_that_changes_nothing_leaves_no_unsaved_changes(auto_find):
    panel, folder, run, summaries = auto_find
    run()
    panel.data_changed = False

    run()                                                         # same folder again: everything already matches

    assert panel.data_changed is False
    assert '(0 changed)' in summaries[1]


# ------------------------------------------------------------------------------------------------- unset paths / '.'
@pytest.fixture
def loaded(panel, tmp_path):
    """Load the panel from a mame.ini that uses MAME's default relative inipath."""
    mame_ini = tmp_path / 'mame.ini'
    mame_ini.write_text('inipath     .;ini;ini/presets\nrompath     roms;\n', encoding='utf-8')
    iniFile.set_ini_file_variables([('path', 'mame_ini', str(mame_ini)),
                                    ('path', 'mame_executable', panel.get_path_list_ctrl('mame_executable')),
                                    ('folders', 'video', '.')])
    panel.revert()
    return panel, mame_ini


def test_mames_own_folder_survives_load_and_apply(loaded):
    panel, mame_ini = loaded
    assert _paths(panel, 'inipath') == ['.', 'ini', 'ini/presets']
    assert _paths(panel, 'rompath') == ['roms']                   # the empty entry after the ';' is dropped

    panel.on_apply(None)

    assert panel.errors == []
    assert iniFile.get_from_mameini('inipath', str(mame_ini)) == '.;ini;ini/presets'
    assert iniFile.get_from_mameini('rompath', str(mame_ini)) == 'roms'


def test_a_dot_in_pfemame_ini_means_not_set(loaded):
    panel, _mame_ini = loaded
    assert _paths(panel, 'video') == ['']


def test_unset_rows_are_never_saved(loaded, data_dir):
    panel, mame_ini = loaded
    first = [r.ini_key for r in panel.table.get_all_rows()].index('rompath')
    panel.insert_row(dataclasses.replace(panel.table.get_row(first), path=''), first + 1)
    assert panel.table.GetValue(first + 1, 1) == 'double click to set'     # shown, but not stored

    panel.on_apply(None)

    assert iniFile.get_from_mameini('rompath', str(mame_ini)) == 'roms'
    for saved in (mame_ini, data_dir / 'pfemame.ini'):
        assert 'double click to set' not in saved.read_text(encoding='utf-8')


def test_clear_all_empties_every_path(loaded):
    panel, _mame_ini = loaded
    _FakeDialog.answer = wx.ID_YES

    panel.on_clear_all(None)

    assert {row.path for row in panel.table.get_all_rows()} == {''}
    assert panel.table.GetValue(0, 1) == 'double click to set'
    assert panel.data_changed is True


# ------------------------------------------------------------------------------------------- choosing another mame.ini
class _RowEvent:
    def __init__(self, row):
        self.row = row

    def GetRow(self):
        return self.row


@pytest.fixture
def choose_other_mame_ini(loaded, tmp_path, monkeypatch):
    """Edit some rows, then pick a different mame.ini on the MAME INI File row (answering the reload question)."""
    panel, old_mame_ini = loaded
    other = tmp_path / 'other' / 'mame.ini'
    other.parent.mkdir()
    other.write_text('rompath     other_roms\n', encoding='utf-8')
    panel.update_table('rompath', 'E:/edited')
    panel.update_table('video', 'E:/videos')
    panel.data_changed = True
    monkeypatch.setattr(panel, 'open_file', lambda path, wildcard, *_start: str(other))

    def choose(answer):
        _FakeDialog.answer = answer
        row = [r.ini_key for r in panel.table.get_all_rows()].index('mame_ini')
        panel.on_double_click_list(_RowEvent(row))
        _FakeDialog.answer = wx.ID_OK
    return panel, old_mame_ini, other, choose


def test_keeping_the_shown_paths_saves_them_into_the_new_mame_ini(choose_other_mame_ini):
    panel, old_mame_ini, other, choose = choose_other_mame_ini
    choose(wx.ID_NO)
    assert _paths(panel, 'rompath') == ['E:/edited']

    panel.on_apply(None)

    assert panel.errors == []
    assert iniFile.get_from_mameini('rompath', str(other)) == 'E:/edited'
    assert iniFile.get_from_mameini('rompath', str(old_mame_ini)) == 'roms;'        # the old file is left alone
    assert iniFile.read_ini_file('path', 'mame_ini') == str(other)


def test_loading_the_new_mame_ini_keeps_pfemames_own_edits(choose_other_mame_ini):
    panel, _old_mame_ini, other, choose = choose_other_mame_ini
    choose(wx.ID_YES)

    assert _paths(panel, 'rompath') == ['other_roms']
    assert _paths(panel, 'mame_ini') == [str(other)]
    assert _paths(panel, 'video') == ['E:/videos']                                  # unsaved pfeMAME edit kept
    assert panel.data_changed is True


# ------------------------------------------------------------------------------------------------------------ buttons
def test_buttons_are_repainted_after_a_button_action(panel, monkeypatch):
    repaints = []
    monkeypatch.setattr(panel, '_repaint_buttons', lambda: repaints.append(True))
    revert = panel.buttons[1]
    event = wx.CommandEvent(wx.EVT_BUTTON.typeId, revert.GetId())
    event.SetEventObject(revert)
    panel.data_changed = False

    revert.GetEventHandler().ProcessEvent(event)

    assert repaints == [True]


# ---------------------------------------------------------------------------------------------------- running MAME
def _fake_mame(monkeypatch, returncode=0, raises=None, writes_ini=True):
    """Replace subprocess.run with a fake MAME (optionally writing mame.ini into the folder it is run from)."""
    def run(cmd, cwd=None, **_kw):
        if raises:
            raise raises
        if writes_ini and cmd[-1] == '-createconfig' and cwd:
            with open(f'{cwd}/mame.ini', 'w', encoding='utf-8') as handle:
                handle.write('rompath     roms\n')
        return subprocess.CompletedProcess(cmd, returncode, stdout=b'# CORE CONFIGURATION OPTIONS', stderr=b'')
    monkeypatch.setattr(subprocess, 'run', run)


def test_apply_with_a_file_that_is_not_a_program_does_not_crash(panel, tmp_path, monkeypatch, data_dir):
    not_mame = tmp_path / 'readme.txt'
    not_mame.write_text('not a program', encoding='utf-8')
    panel.update_table('mame_executable', str(not_mame))
    monkeypatch.setattr(subprocess, 'run', REAL_RUN)       # the real OS error (WinError 193 on Windows)

    panel.on_apply(None)

    assert 'setup_ini' not in panel.messages
    assert not (data_dir / 'pfemame.ini').exists()


def test_apply_when_mame_times_out(panel, monkeypatch, data_dir):
    _fake_mame(monkeypatch, raises=subprocess.TimeoutExpired('mame', filepaths.MAME_TIMEOUT))
    panel.on_apply(None)
    assert 'setup_ini' not in panel.messages
    assert not (data_dir / 'pfemame.ini').exists()


@pytest.mark.parametrize('kwargs, works', [({}, True),
                                           ({'returncode': 1}, False),
                                           ({'raises': OSError(193, 'not a valid Win32 application')}, False),
                                           ({'raises': subprocess.TimeoutExpired('mame', 30)}, False)])
def test_auto_find_only_accepts_mame_that_succeeds(panel, tmp_path, monkeypatch, kwargs, works):
    _fake_mame(monkeypatch, **kwargs)
    assert panel.check_mame_executable(str(tmp_path / 'mame.exe'), cwd=str(tmp_path)) is works


def test_make_ini_creates_mame_ini_beside_mame(panel, tmp_path, monkeypatch):
    panel.update_table('mame_ini', str(tmp_path / 'mame.ini'))       # where MAKE INI writes, on every platform
    _fake_mame(monkeypatch)
    shown = []
    monkeypatch.setattr(filepaths, 'show_information_dialog', lambda _parent, msg, _title: shown.append(msg))

    panel.on_make_ini(None)

    assert panel.errors == []
    assert panel.get_path_list_ctrl('mame_ini') == str(tmp_path / 'mame.ini')
    assert panel.path_to_mame_ini_file == str(tmp_path / 'mame.ini')
    assert len(shown) == 1


@pytest.mark.parametrize('kwargs, reason', [({'returncode': 3}, 'exit code 3'),
                                            ({'writes_ini': False}, 'no mame.ini was written'),
                                            ({'raises': OSError(193, 'not a valid Win32 application')},
                                             'could not be run')])
def test_make_ini_reports_why_it_failed(panel, tmp_path, monkeypatch, kwargs, reason):
    panel.update_table('mame_ini', str(tmp_path / 'mame.ini'))       # where MAKE INI writes, on every platform
    _fake_mame(monkeypatch, **kwargs)
    monkeypatch.setattr(filepaths, 'show_information_dialog', lambda *_a: pytest.fail('reported success'))

    panel.on_make_ini(None)

    assert len(panel.errors) == 1 and reason in panel.error_texts[0]


# ---------------------------------------------------------------------------------------------------- red rows / tips
@pytest.fixture
def mame_panel(panel, mame_folder):
    """The panel with its MAME executable in mame_folder (which has ini/ and ini/presets/)."""
    panel.update_table('mame_executable', str(mame_folder / 'mame.exe'))
    return panel


def _problem(panel, ini_key):
    return next(r.problem for r in panel.table.get_all_rows() if r.ini_key == ini_key)


def _row_index(panel, ini_key):
    return [r.ini_key for r in panel.table.get_all_rows()].index(ini_key)


def test_mame_paths_are_checked_relative_to_the_mame_folder(mame_panel, mame_folder, monkeypatch):
    mame_panel.update_table('inipath', 'ini')
    mame_panel.update_table('rompath', 'roms')                    # doesn't exist in the MAME folder
    monkeypatch.setenv('MAMEHOME', str(mame_folder))
    mame_panel.update_table('cfg_directory', '$MAMEHOME/ini/presets')

    mame_panel.check_valid_paths()

    assert _problem(mame_panel, 'inipath') == ''
    assert _problem(mame_panel, 'cfg_directory') == ''
    assert _problem(mame_panel, 'rompath') == f"Folder not found:  {mame_folder / 'roms'}"


def test_only_required_paths_are_red_when_empty(mame_panel):
    mame_panel.update_table('history_dat', '')
    mame_panel.update_table('bosses_directory', '')

    mame_panel.check_valid_paths()

    assert _problem(mame_panel, 'history_dat').startswith('Required')
    assert _problem(mame_panel, 'bosses_directory') == ''
    assert _problem(mame_panel, 'mame_executable') == ''


def test_a_folder_is_not_accepted_as_a_file(mame_panel, mame_folder):
    mame_panel.update_table('catver_ini', str(mame_folder))
    mame_panel.check_valid_paths()
    assert _problem(mame_panel, 'catver_ini') == 'catver.ini file needs a file, not a folder.'


def test_a_file_is_not_accepted_as_a_folder(mame_panel, mame_folder):
    mame_panel.update_table('snapshot_directory', str(mame_folder / 'mame.exe'))
    mame_panel.check_valid_paths()
    assert _problem(mame_panel, 'snapshot_directory').endswith('needs a folder, not a file.')


def test_browsing_to_a_folder_for_a_file_row_is_refused(mame_panel, mame_folder, monkeypatch):
    # Some platforms' file dialogs can hand back a folder - the row keeps its path and the status bar says why
    statuses = []
    monkeypatch.setattr(filepaths.pub, 'sendMessage',
                        lambda topic, **kwargs: statuses.append(kwargs.get('msg')) if topic == 'status' else None)
    mame_panel.update_table('catver_ini', '')
    mame_panel.data_changed = False
    monkeypatch.setattr(mame_panel, 'open_file', lambda path, *_args: str(mame_folder))

    mame_panel.on_double_click_list(_RowEvent(_row_index(mame_panel, 'catver_ini')))

    assert mame_panel.get_path_list_ctrl('catver_ini') == ''
    assert statuses == ['catver.ini file needs a file, not a folder.']
    assert not mame_panel.data_changed


def test_red_rows_stay_with_their_path_when_rows_are_added(mame_panel, mame_folder):
    mame_panel.update_table('rompath', 'missing')
    mame_panel.update_table('catver_ini', str(mame_folder / 'mame.exe'))     # the row above: a file that exists
    mame_panel.check_valid_paths()
    rom_row = _row_index(mame_panel, 'rompath')
    red = mame_panel.table._attr_invalid.GetBackgroundColour()

    mame_panel.insert_row(dataclasses.replace(mame_panel.table.get_row(0), path='', problem=''), 0)

    attr = mame_panel.table.GetAttr(rom_row + 1, 1, None)
    assert attr.GetBackgroundColour() == red
    assert mame_panel.table.GetAttr(rom_row, 1, None).GetBackgroundColour() != red


def test_choosing_a_path_rechecks_the_row(mame_panel, mame_folder, monkeypatch):
    mame_panel.update_table('snapshot_directory', 'missing')
    mame_panel.check_valid_paths()
    assert _problem(mame_panel, 'snapshot_directory')
    monkeypatch.setattr(mame_panel, 'open_dir', lambda path, *_start: str(mame_folder))

    mame_panel.on_double_click_list(_RowEvent(_row_index(mame_panel, 'snapshot_directory')))

    assert _problem(mame_panel, 'snapshot_directory') == ''


def test_clear_all_marks_the_required_paths(mame_panel):
    _FakeDialog.answer = wx.ID_YES
    mame_panel.on_clear_all(None)
    red = {r.ini_key for r in mame_panel.table.get_all_rows() if r.problem}
    assert red == filepaths.REQUIRED_PATHS


def test_hovering_a_red_row_shows_why(mame_panel, mame_folder):
    mame_panel.update_table('rompath', 'roms')
    mame_panel.check_valid_paths()
    window = mame_panel.list_control.GetGridWindow()

    mame_panel._show_problem_tooltip(_row_index(mame_panel, 'rompath'))
    assert window.GetToolTipText() == f"Folder not found:  {mame_folder / 'roms'}"

    mame_panel._show_problem_tooltip(_row_index(mame_panel, 'inipath'))     # a row that is fine: no tooltip
    assert window.GetToolTipText() == ''


# ------------------------------------------------------------------------------------------------------- % in paths
def test_a_percent_in_a_path_survives_apply(panel, tmp_path):
    folder = tmp_path / '100% MAME'
    folder.mkdir()
    exe = folder / 'mame.exe'
    exe.write_bytes(b'')
    mame_ini = tmp_path / 'mame.ini'
    mame_ini.write_text('', encoding='utf-8')
    panel.update_table('mame_ini', str(mame_ini))
    panel.update_table('mame_executable', str(exe))
    panel.update_table('video', str(folder))

    panel.on_apply(None)

    assert panel.errors == []
    assert iniFile.read_ini_file('path', 'mame_executable') == str(exe)
    assert iniFile.read_ini_file('folders', 'video') == str(folder)


# ------------------------------------------------------------------------------------------------ finding mame.ini
@pytest.fixture
def home(tmp_path, monkeypatch):
    folder = tmp_path / 'home'
    folder.mkdir()
    monkeypatch.setenv('HOME', str(folder))
    monkeypatch.setenv('USERPROFILE', str(folder))
    return folder


@pytest.fixture
def portable_mame(tmp_path):
    folder = tmp_path / 'portable'
    folder.mkdir()
    (folder / 'mame').write_bytes(b'')
    return folder / 'mame'


def _ini(folder):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'mame.ini').write_text('', encoding='utf-8')
    return str(folder / 'mame.ini')


def test_linux_finds_mame_ini_in_the_usual_order(home, portable_mame):
    exe = str(portable_mame)
    # Nothing there yet: where MAME would look for it (and where MAKE INI creates it)
    assert mame_paths.find_mame_ini(exe, 'linux') == str(home / '.mame' / 'mame.ini')
    portable = _ini(portable_mame.parent)
    assert mame_paths.find_mame_ini(exe, 'linux') == portable               # a portable build's own mame.ini
    in_mame = _ini(home / 'mame')
    assert mame_paths.find_mame_ini(exe, 'linux') == in_mame                # ~/mame comes before that
    in_dot_mame = _ini(home / '.mame')
    assert mame_paths.find_mame_ini(exe, 'linux') == in_dot_mame            # and ~/.mame (MAME's own) first


def test_a_chosen_mame_ini_in_a_usual_place_is_kept(home, portable_mame):
    in_mame = _ini(home / 'mame')
    _ini(home / '.mame')
    assert mame_paths.find_mame_ini(str(portable_mame), 'linux', current=in_mame) == in_mame
    # ... but not one somewhere unrelated to the new executable
    elsewhere = _ini(home / 'elsewhere')
    assert mame_paths.find_mame_ini(str(portable_mame), 'linux', current=elsewhere) == str(home / '.mame' / 'mame.ini')


def test_mac_prefers_the_mame_folder_then_home(home, portable_mame):
    exe = str(portable_mame)
    assert mame_paths.find_mame_ini(exe, 'mac') == str(portable_mame.parent / 'mame.ini')
    library = _ini(home / 'Library' / 'Application Support' / 'mame')
    assert mame_paths.find_mame_ini(exe, 'mac') == library
    in_folder = _ini(portable_mame.parent)
    assert mame_paths.find_mame_ini(exe, 'mac') == in_folder


def test_windows_uses_the_mame_folder(home, portable_mame):
    _ini(home / '.mame')                                                     # not looked at on Windows
    assert mame_paths.find_mame_ini(str(portable_mame), 'windows') == str(portable_mame.parent / 'mame.ini')
    assert mame_paths.find_mame_ini('mame', 'windows') == ''                 # MAME on the PATH: nowhere known


def test_no_home_folder_does_not_crash(portable_mame, monkeypatch):
    monkeypatch.setattr(mame_paths.os.path, 'expanduser', lambda path: path)
    assert mame_paths.find_mame_ini('mame', 'linux') == ''
    assert mame_paths.find_mame_ini(str(portable_mame), 'linux') == str(portable_mame.parent / 'mame.ini')


def test_choosing_an_executable_moves_the_mame_ini_row(panel, portable_mame, home, monkeypatch):
    panel.system = 'linux'
    in_mame = _ini(home / 'mame')
    monkeypatch.setattr(panel, 'open_file', lambda path, wildcard, *_start: str(portable_mame))
    _FakeDialog.answer = wx.ID_NO                                            # keep the folders shown

    panel.on_double_click_list(_RowEvent(_row_index(panel, 'mame_executable')))

    assert panel.get_path_list_ctrl('mame_ini') == in_mame
    assert panel.path_to_mame_ini_file == in_mame


# ------------------------------------------------------------------------------------------ where MAKE INI writes
@pytest.mark.parametrize('platform', ['windows', 'mac', 'linux'])
def test_make_ini_uses_the_folder_of_the_mame_ini_row(panel, home, monkeypatch, platform):
    panel.system = platform
    chosen = home / 'mame' / 'mame.ini'                       # folder doesn't exist yet - MAKE INI creates it
    panel.update_table('mame_ini', str(chosen))
    _fake_mame(monkeypatch)
    monkeypatch.setattr(filepaths, 'show_information_dialog', lambda *_a: None)

    panel.on_make_ini(None)

    assert panel.errors == []
    assert chosen.is_file()
    assert panel.get_path_list_ctrl('mame_ini') == str(chosen)


def test_make_ini_on_linux_defaults_to_dot_mame(panel, home, monkeypatch):
    panel.system = 'linux'
    panel.update_table('mame_ini', '')
    _fake_mame(monkeypatch)
    monkeypatch.setattr(filepaths, 'show_information_dialog', lambda *_a: None)

    panel.on_make_ini(None)

    assert panel.errors == []
    assert panel.get_path_list_ctrl('mame_ini') == str(home / '.mame' / 'mame.ini')
    assert (home / '.mame' / 'mame.ini').is_file()


# ------------------------------------------------------------------------------------- file chooser / finding MAME
def test_file_chooser_filters_offer_the_rows_types_and_all_files(panel, monkeypatch):
    panel.system = 'windows'
    assert panel._file_wildcard('*.xml;*.dat') == '*.xml;*.dat|*.xml;*.dat|All files (*.*)|*.*'
    assert panel._file_wildcard('*.exe') == '*.exe|*.exe|All files (*.*)|*.*'
    panel.system = 'linux'
    assert panel._file_wildcard('*.exe') == 'All files (*)|*'               # programs have no extension

    seen = []

    class _FakeFileDialog(_FakeDialog):
        def __init__(self, *args, wildcard='', **kwargs):
            seen.append(wildcard)

        def ShowModal(self):
            return wx.ID_CANCEL
    monkeypatch.setattr(wx, 'FileDialog', _FakeFileDialog)

    panel.on_double_click_list(_RowEvent(_row_index(panel, 'history_dat')))

    assert seen == ['*.xml;*.dat|*.xml;*.dat|All files (*)|*']


@pytest.fixture
def mame_on_path(tmp_path, monkeypatch):
    """A big enough 'MAME.EXE' (upper case) in a folder that is the only entry on the PATH."""
    folder = tmp_path / 'onpath'
    folder.mkdir()
    exe = folder / 'MAME.EXE'
    exe.write_bytes(b'\0' * 60000)
    exe.chmod(0o755)                    # The search only accepts programs (on Linux / macOS that's the execute bit)
    monkeypatch.setenv('PATH', str(folder))
    return exe


def test_mame_on_the_path_is_found_whatever_its_case_on_windows(panel, mame_on_path, monkeypatch):
    panel.system = 'windows'
    monkeypatch.setattr(panel, 'check_mame_executable', lambda path, cwd=None: path == str(mame_on_path))
    assert panel._search_system_for_mame(cwd='') == str(mame_on_path)


def test_auto_find_searches_the_path_when_the_folders_mame_fails(auto_find, mame_on_path, monkeypatch):
    panel, folder, run, summaries = auto_find
    panel.system = 'windows'
    (folder / 'mame.exe').write_bytes(b'')                                  # broken MAME in the chosen folder
    monkeypatch.setattr(panel, 'check_mame_executable', lambda path, cwd=None: path == str(mame_on_path))

    run()

    assert _paths(panel, 'mame_executable') == [str(mame_on_path)]
    assert panel.errors == []


# ---------------------------------------------------------------------------------------------------------- restart
@pytest.fixture
def ready_to_apply(panel, tmp_path):
    mame_ini = tmp_path / 'mame.ini'
    mame_ini.write_text('', encoding='utf-8')
    panel.update_table('mame_ini', str(mame_ini))
    return panel


def test_apply_restarts_straight_away_on_yes(ready_to_apply):
    _FakeDialog.answer = wx.ID_YES
    ready_to_apply.on_apply(None)
    assert 'restart_now' in ready_to_apply.messages
    assert 'force_restart' not in ready_to_apply.messages        # the old flag that asked again later


def test_apply_without_restarting_leaves_no_restart_pending(ready_to_apply):
    _FakeDialog.answer = wx.ID_NO
    ready_to_apply.on_apply(None)
    assert 'setup_ini' in ready_to_apply.messages
    assert 'restart_now' not in ready_to_apply.messages
    assert 'force_restart' not in ready_to_apply.messages


# ------------------------------------------------------------------------------------------------ browse start folder
@pytest.fixture
def browse(panel, monkeypatch):
    """Double-click a row with the file / folder dialogs faked: returns what each dialog was opened with."""
    opened = []

    class _FakeFileDialog(_FakeDialog):
        def __init__(self, *args, defaultDir='', defaultFile='', **kwargs):
            opened.append((defaultDir, defaultFile))

        def ShowModal(self):
            return wx.ID_CANCEL

    class _FakeDirDialog(_FakeFileDialog):
        def __init__(self, *args, defaultPath='', **kwargs):
            opened.append((defaultPath, ''))
    monkeypatch.setattr(wx, 'FileDialog', _FakeFileDialog)
    monkeypatch.setattr(wx, 'DirDialog', _FakeDirDialog)

    def double_click(ini_key):
        opened.clear()
        panel.on_double_click_list(_RowEvent(_row_index(panel, ini_key)))
        return opened[0]
    return panel, double_click


def test_browsing_a_file_opens_at_that_file(browse, tmp_path):
    panel, double_click = browse
    history = tmp_path / 'dats' / 'history.xml'
    history.parent.mkdir()
    history.write_text('', encoding='utf-8')
    panel.update_table('history_dat', str(history))

    assert double_click('history_dat') == (str(history.parent), 'history.xml')


def test_browsing_a_relative_mame_folder_opens_in_it(browse, mame_folder):
    panel, double_click = browse
    panel.update_table('mame_executable', str(mame_folder / 'mame.exe'))
    panel.update_table('cfg_directory', 'ini/presets')

    assert double_click('cfg_directory') == (str(mame_folder / 'ini' / 'presets'), '')


def test_browsing_an_unset_row_opens_in_the_mame_folder(browse, tmp_path):
    panel, double_click = browse                       # the fixture's MAME executable is tmp_path/mame.exe
    panel.update_table('bosses_directory', '')
    panel.update_table('mameinfo_dat', str(tmp_path / 'gone' / 'mameinfo.dat'))      # set, but no longer there

    assert double_click('bosses_directory') == (str(tmp_path), '')
    assert double_click('mameinfo_dat') == (str(tmp_path), '')


# -------------------------------------------------------------------------------------------------------- translation
def test_the_tabs_text_is_translated(panel, monkeypatch):
    monkeypatch.setattr(filepaths, '_', lambda text: f'[{text}]')
    frame = wx.Frame(None)
    try:
        translated = filepaths.FilePaths(frame, my_logger=_NullLogger())
        table = translated.table
        assert table.GetColLabelValue(0) == '[Name]' and table.GetColLabelValue(1) == '[Path]'
        assert table.GetValue(0, 0) == '[MAME INI File:]'
        unset = next(i for i, row in enumerate(table.get_all_rows()) if not row.path)
        assert table.GetValue(unset, 1) == '[double click to set]'
        assert translated.apply_button.GetLabel() == '[APPLY]'          # still found once its label is translated
        assert [button.GetLabel() for button in translated.buttons] == [
            '[APPLY]', '[REVERT]', '[CLEAR ALL]', '[AUTO FIND]', '[MAKE INI]']
    finally:
        frame.Destroy()


# ------------------------------------------------------------------------------------------------- reordering paths
@pytest.fixture
def three_rom_folders(ready_to_apply):
    """The ROMs entry holding A, B and C (in that order)."""
    panel = ready_to_apply
    first = _row_index(panel, 'rompath')
    panel.table.set_path(first, 'A')
    for offset, path in enumerate(('B', 'C'), start=1):
        panel.insert_row(dataclasses.replace(panel.table.get_row(first), path=path), first + offset)
    panel.data_changed = False
    return panel, first


def test_move_up_and_down_within_an_entry(three_rom_folders):
    panel, first = three_rom_folders

    assert panel.move_row(first + 2, -1)                      # C up
    assert _paths(panel, 'rompath') == ['A', 'C', 'B']
    assert panel.list_control.GetSelectedRows() == [first + 1]  # the moved row stays selected
    assert panel.move_row(first, 1)                           # A down
    assert _paths(panel, 'rompath') == ['C', 'A', 'B']
    assert panel.data_changed is True


def test_rows_cannot_move_out_of_their_entry(three_rom_folders):
    panel, first = three_rom_folders
    before = [row.ini_key for row in panel.table.get_all_rows()]

    assert not panel.move_row(first, -1)                      # top of the entry
    assert not panel.move_row(first + 2, 1)                   # bottom of the entry
    assert not panel.move_row(_row_index(panel, 'video'), 1)  # a single-path entry

    assert [row.ini_key for row in panel.table.get_all_rows()] == before
    assert _paths(panel, 'rompath') == ['A', 'B', 'C']
    assert panel.data_changed is False


def test_apply_saves_the_new_order(three_rom_folders, tmp_path):
    panel, first = three_rom_folders
    panel.move_row(first + 2, -1)
    panel.move_row(first + 1, -1)

    panel.on_apply(None)

    assert iniFile.get_from_mameini('rompath', str(tmp_path / 'mame.ini')) == 'C;A;B'


def test_any_row_can_be_deleted_while_others_remain(three_rom_folders):
    panel, first = three_rom_folders

    assert panel.delete_path_row(first)                       # the first row can go now
    assert _paths(panel, 'rompath') == ['B', 'C']
    assert panel.delete_path_row(first)
    assert not panel.delete_path_row(first)                   # but not the last one
    assert _paths(panel, 'rompath') == ['C']
    assert panel.table.row_count() == panel.list_control.GetNumberRows()


# ------------------------------------------------------------------------------------------ open folder / drag and drop
def _row(panel, ini_key):
    return panel.table.get_row(_row_index(panel, ini_key))


def test_open_folder_shows_the_rows_folder(mame_panel, mame_folder, monkeypatch):
    opened = []
    monkeypatch.setattr(wx, 'LaunchDefaultApplication', lambda path: opened.append(path) or True)
    mame_panel.update_table('history_dat', str(mame_folder / 'mame.exe'))   # a file: its folder is opened
    mame_panel.update_table('cfg_directory', 'ini/presets')                 # relative to the MAME folder
    mame_panel.update_table('snapshot_directory', 'missing')
    mame_panel.update_table('bosses_directory', '')

    assert mame_panel.folder_to_open(_row(mame_panel, 'history_dat')) == str(mame_folder)
    assert mame_panel.folder_to_open(_row(mame_panel, 'cfg_directory')) == str(mame_folder / 'ini' / 'presets')
    assert mame_panel.folder_to_open(_row(mame_panel, 'snapshot_directory')) == ''     # no menu item
    assert mame_panel.folder_to_open(_row(mame_panel, 'bosses_directory')) == ''

    mame_panel.open_folder(str(mame_folder))
    assert opened == [str(mame_folder)]


def test_dropping_a_folder_on_a_folder_row_sets_it(mame_panel, mame_folder):
    mame_panel.data_changed = False
    index = _row_index(mame_panel, 'snapshot_directory')

    assert mame_panel.drop_path(index, [str(mame_folder / 'ini')])

    assert mame_panel.get_path_list_ctrl('snapshot_directory') == str(mame_folder / 'ini')
    assert mame_panel.data_changed is True
    assert _row(mame_panel, 'snapshot_directory').problem == ''              # checked straight away


def test_dropping_the_wrong_kind_of_thing_is_refused(mame_panel, mame_folder):
    mame_panel.data_changed = False
    file_row, folder_row = _row_index(mame_panel, 'catver_ini'), _row_index(mame_panel, 'snapshot_directory')
    before = (mame_panel.get_path_list_ctrl('catver_ini'), mame_panel.get_path_list_ctrl('snapshot_directory'))

    assert not mame_panel.drop_path(file_row, [str(mame_folder)])                     # folder on a file row
    assert not mame_panel.drop_path(folder_row, [str(mame_folder / 'mame.exe')])      # file on a folder row
    assert not mame_panel.drop_path(folder_row, [str(mame_folder), str(mame_folder / 'ini')])   # two at once
    assert not mame_panel.drop_path(-1, [str(mame_folder)])                           # below the last row

    assert (mame_panel.get_path_list_ctrl('catver_ini'), mame_panel.get_path_list_ctrl('snapshot_directory')) == before
    assert mame_panel.data_changed is False
    assert mame_panel.messages.count('status') == 3                          # each refusal says why


def test_dropping_a_mame_ini_offers_to_load_it(mame_panel, tmp_path):
    other = tmp_path / 'other' / 'mame.ini'
    other.parent.mkdir()
    other.write_text('rompath     other_roms\n', encoding='utf-8')
    _FakeDialog.answer = wx.ID_YES

    assert mame_panel.drop_path(_row_index(mame_panel, 'mame_ini'), [str(other)])

    assert mame_panel.path_to_mame_ini_file == str(other)
    assert _paths(mame_panel, 'rompath') == ['other_roms']


# ------------------------------------------------------------------------------------------------------- MAME version
def test_mame_version_is_read_from_mames_help(tmp_path, monkeypatch):
    exe = tmp_path / 'mame.exe'
    exe.write_bytes(b'')
    output = 'MAME v0.289 (mame0289)\nCopyright Nicola Salmoria and the MAME team\n\nUsage:  mame [machine] [media]\n'
    monkeypatch.setattr(subprocess, 'run', lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout=output))
    assert mame_paths.mame_version(str(exe)) == ('0.289', '')

    monkeypatch.setattr(subprocess, 'run', lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout='hello'))
    assert mame_paths.mame_version(str(exe)) == ('', 'it did not report a MAME version')


def test_mame_version_problems_are_reported_not_raised(tmp_path, monkeypatch):
    not_mame = tmp_path / 'readme.txt'
    not_mame.write_text('not a program', encoding='utf-8')
    version, problem = mame_paths.mame_version(str(not_mame))                 # the real OS error
    assert version == '' and problem

    def hang(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, kw['timeout'])
    monkeypatch.setattr(subprocess, 'run', hang)
    assert mame_paths.mame_version(str(not_mame), timeout=5) == ('', 'no answer within 5 seconds')
    assert mame_paths.mame_version('') == ('', 'no MAME executable is set')


def _version_label(panel):
    """The MAME version label as one line - the panel wraps it to its width, which on GTK (wider fonts) breaks long
    messages over two lines."""
    return panel.mame_version_text.GetLabel().replace('\n', ' ')


def _wait_for_version(panel):
    panel._version_thread.join(5)
    wx.GetApp().ProcessPendingEvents()          # run the thread's wx.CallAfter
    return _version_label(panel)


def test_the_tab_shows_the_mame_version_when_the_executable_changes(panel, tmp_path, monkeypatch):
    answers = {}
    monkeypatch.setattr(filepaths.functions, 'mame_version',      # (other tests' queued checks also run here)
                        lambda path, timeout=30: answers.get(path, ('', 'not this test')))
    good, bad = str(tmp_path / 'mame.exe'), str(tmp_path / 'broken.exe')
    answers.update({good: ('0.289', ''), bad: ('', 'no answer within 30 seconds')})

    panel.update_table('mame_executable', good)
    panel.check_valid_paths()
    assert _wait_for_version(panel) == 'MAME version:  0.289'

    panel.update_table('mame_executable', bad)
    panel.check_valid_paths()
    assert _wait_for_version(panel) == 'MAME version:  not working (no answer within 30 seconds)'

    panel._show_mame_version(good, '0.289', '')                     # a late answer for the old executable
    assert _version_label(panel) == 'MAME version:  not working (no answer within 30 seconds)'


def test_main_window_waits_for_the_mame_version(wx_app):
    """The database load and catver check wait for the version, which arrives from a background thread."""
    import types
    import pfemame
    frame = types.SimpleNamespace(
        _mame_version_known=False, _mame_version_waiting=[], mame_version='',
        text_version_mame=wx.StaticText(wx.Frame(None)), my_logger=_NullLogger())
    frame.my_logger.warning = lambda *_a: None
    ran = []

    pfemame.MainFrame.when_mame_version_known(frame, lambda: ran.append(frame.mame_version))
    pfemame.MainFrame.when_mame_version_known(frame, lambda: ran.append('second'))
    assert ran == []                                                # nothing runs before MAME has answered

    pfemame.MainFrame._mame_version_found(frame, '0.289', '')
    assert ran == ['0.289', 'second']
    assert frame.text_version_mame.GetLabel() == '0.289'

    pfemame.MainFrame.when_mame_version_known(frame, lambda: ran.append('later'))
    assert ran[-1] == 'later'                                       # known now: runs straight away
    frame.text_version_mame.GetParent().Destroy()


# ---------------------------------------------------------------------------------------------- MAME in the background
def _finish_background(panel_or_worker):
    """Wait for the worker thread, then run its wx.CallAfter (what the event loop would do)."""
    panel_or_worker.join(5)
    wx.GetApp().ProcessPendingEvents()


def test_make_ini_runs_mame_in_the_background(panel, tmp_path, monkeypatch):
    panel.update_table('mame_ini', str(tmp_path / 'mame.ini'))       # where MAKE INI writes, on every platform
    panel.use_background_thread = True
    _fake_mame(monkeypatch)
    shown = []
    monkeypatch.setattr(filepaths, 'show_information_dialog', lambda _parent, msg, _title: shown.append(msg))

    panel.on_make_ini(None)
    assert not panel.IsEnabled()                         # the tab can't be changed while MAME runs
    worker = panel._worker
    _finish_background(worker)

    assert panel.IsEnabled()
    assert panel.get_path_list_ctrl('mame_ini') == str(tmp_path / 'mame.ini')
    assert len(shown) == 1


def test_apply_checks_mame_in_the_background(ready_to_apply):
    panel = ready_to_apply
    panel.use_background_thread = True

    panel.on_apply(None)
    assert 'setup_ini' not in panel.messages             # nothing saved until MAME has answered
    _finish_background(panel._worker)

    assert panel.IsEnabled()
    assert 'setup_ini' in panel.messages


def test_a_failing_background_task_still_re_enables_the_tab(ready_to_apply, monkeypatch):
    panel = ready_to_apply
    panel.use_background_thread = True

    def broken(*_args):
        raise RuntimeError('unexpected')
    monkeypatch.setattr(panel, '_run_mame', broken)

    panel.on_apply(None)
    _finish_background(panel._worker)

    assert panel.IsEnabled()
    assert panel.errors == ['ERROR']
    assert 'setup_ini' not in panel.messages


def test_a_result_after_the_tab_has_closed_is_ignored(panel, tmp_path, monkeypatch):
    panel.update_table('mame_ini', str(tmp_path / 'mame.ini'))       # where MAKE INI writes, on every platform
    panel.use_background_thread = True
    _fake_mame(monkeypatch)
    monkeypatch.setattr(filepaths, 'show_information_dialog', lambda *_a: pytest.fail('closed tab was updated'))

    panel.on_make_ini(None)
    worker = panel._worker
    panel.Destroy()
    _finish_background(worker)                           # must not touch the destroyed tab


def test_cancelling_auto_find_changes_nothing(auto_find, monkeypatch):
    panel, folder, run, summaries = auto_find
    (folder / 'mame.exe').write_bytes(b'')
    before = [(row.ini_key, row.path) for row in panel.table.get_all_rows()]

    def cancel_while_checking(path, cwd=None):
        panel._auto_find_cancel.set()                    # as if Cancel was clicked while this MAME was running
        return False
    monkeypatch.setattr(panel, 'check_mame_executable', cancel_while_checking)

    run()

    assert [(row.ini_key, row.path) for row in panel.table.get_all_rows()] == before
    assert summaries == []
    assert panel.data_changed is True                    # (the fixture's own setting - not changed by Auto Find)
