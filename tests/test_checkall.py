"""
Check All ROMs (checkall.py): reading MAME's -verifyroms output, the filters, the saved / copied text, the worker
thread (with a stand-in for MAME) and the window itself.
"""
import os
import shelve
import threading

import pytest
import wx

import checkall
from checkall import BAD, BEST_AVAILABLE, GOOD, NOT_FOUND, RomsetResult

MAME_OUTPUT = """\
aaa         : a1.bin (1024 bytes) - NOT FOUND
romset aaa is bad
romset bbb [aaa] is good
ccc         : c1.bin (2048 bytes) - NEEDS REDUMP
romset ccc is best available
romset "zzz" not found!
3 romsets found, 2 were OK.
""".splitlines()


def names(results) -> list:
    return [result.name for result in results]


# ----------------------------------------------------------------------------------------------------------------------
# Reading MAME's output
def test_each_set_gets_its_status_details_and_parent():
    results, messages = checkall.parse_verify_output(MAME_OUTPUT, ['aaa', 'bbb', 'ccc', 'zzz'])
    by_name = {result.name: result for result in results}
    assert by_name['aaa'].status == BAD
    assert by_name['aaa'].details == ['aaa         : a1.bin (1024 bytes) - NOT FOUND']
    assert by_name['bbb'].status == GOOD and by_name['bbb'].parent == 'aaa' and by_name['bbb'].details == []
    assert by_name['ccc'].status == BEST_AVAILABLE
    assert by_name['zzz'].status == NOT_FOUND
    assert messages == []           # MAME's own total line is dropped


def test_set_mame_prints_nothing_for_is_not_found():
    results, _messages = checkall.parse_verify_output(['romset bbb is good'], ['bbb', 'missing'])
    assert {result.name: result.status for result in results} == {'bbb': GOOD, 'missing': NOT_FOUND}
    missing = next(result for result in results if result.name == 'missing')
    assert 'missing' in missing.status_line()


def test_lines_not_about_a_set_are_messages():
    _results, messages = checkall.parse_verify_output(['romset bbb is good', 'Something went wrong'], ['bbb'])
    assert messages == ['Something went wrong']


def test_mame_total_in_the_error_output_is_dropped():
    # MAME 0.28x prints its total on stderr
    assert checkall.stderr_messages(['50 romsets found, 44 were OK.', '', "No matching systems found for 'x'"]) == [
        "No matching systems found for 'x'"]


# ----------------------------------------------------------------------------------------------------------------------
# Filters, totals and merging
@pytest.fixture
def results():
    found, _messages = checkall.parse_verify_output(MAME_OUTPUT, ['aaa', 'bbb', 'ccc', 'zzz'])
    return checkall.merge_results([], found)


def test_results_are_sorted_by_name(results):
    assert names(results) == ['aaa', 'bbb', 'ccc', 'zzz']


def test_filter_keeps_the_first_set(results):
    # The old filter always dropped the first set in the list
    assert names(checkall.filter_results(results, BAD)) == ['aaa']
    assert names(checkall.filter_results(results, None)) == names(results)
    assert names(checkall.filter_results(results, NOT_FOUND)) == ['zzz']


def test_counts(results):
    assert checkall.count_results(results) == {GOOD: 1, BAD: 1, BEST_AVAILABLE: 1, NOT_FOUND: 1, checkall.OTHER: 0}
    header = checkall.summary_lines(results, 12.34, stopped=False)
    assert '4' in header[0] and '12.3' in header[1] and len(header) == 2
    assert len(checkall.summary_lines(results, 1, stopped=True)) == 3


def test_recheck_replaces_only_the_rechecked_sets(results):
    merged = checkall.merge_results(results, [RomsetResult('aaa', GOOD, line='romset aaa is good')])
    assert {result.name: result.status for result in merged} == {'aaa': GOOD, 'bbb': GOOD, 'ccc': BEST_AVAILABLE,
                                                                 'zzz': NOT_FOUND}


# ----------------------------------------------------------------------------------------------------------------------
# Output
def test_saved_text_has_single_line_endings(results, tmp_path):
    text = checkall.render_text(results, ['header'], [])
    assert '\r' not in text
    path = tmp_path / 'out.txt'
    with open(path, 'w', encoding='utf-8') as fp:    # As CheckAll.on_save writes it
        fp.write(text)
    assert b'\r\r' not in path.read_bytes()
    assert text.count(checkall.SEPARATOR) == len(results) + 1


def test_text_can_hold_any_character(tmp_path):
    text = checkall.render_text([RomsetResult('x', GOOD, line='romset x is good ☃中')], [], [])
    path = tmp_path / 'out.txt'
    with open(path, 'w', encoding='utf-8') as fp:
        fp.write(text)
    assert '☃' in path.read_text(encoding='utf-8')


def test_html_is_escaped_and_coloured(results):
    page = checkall.render_html(results, ['a & b'], ['<oops>'], '#ffffff', '#000000')
    assert 'a &amp; b' in page and '&lt;oops&gt;' in page and '<oops>' not in page
    assert '<font color="red">romset aaa is bad</font>' in page
    assert '<font color="orange">romset ccc is best available</font>' in page
    assert 'No ROM sets match' not in page
    assert 'No ROM sets match' in checkall.render_html([], [], [], '#ffffff', '#000000')


def test_detail_colours():
    assert checkall.detail_colour('x.bin - NOT FOUND') == 'red'
    assert checkall.detail_colour('x.bin (960 bytes) - INCORRECT LENGTH: 2240 bytes') == 'red'
    assert checkall.detail_colour('x.bin NOT FOUND - NO GOOD DUMP KNOWN') == 'orange'
    assert checkall.detail_colour('x.bin - NEEDS REDUMP') == 'orange'
    assert checkall.detail_colour('fine') is None


# ----------------------------------------------------------------------------------------------------------------------
# The ROM list
def test_only_present_roms_are_checked(data_dir):
    row = ['Name', '', '', '', '', '', '', '', '', '', '', '']
    rows = [row[:1] + ['bbb'] + row[2:3] + ['1'] + row[4:],
            row[:1] + ['aaa'] + row[2:3] + ['1'] + row[4:],
            row[:1] + ['absent'] + row[2:3] + ['0'] + row[4:],
            row[:1] + ['aaa'] + row[2:3] + ['1'] + row[4:]]
    with shelve.open(os.path.join(str(data_dir), 'mylist.db')) as db:
        db['mylist'] = rows
    assert checkall.load_rom_names() == ['aaa', 'bbb']


def test_missing_rom_list_is_empty(data_dir):
    assert checkall.load_rom_names() == []


# ----------------------------------------------------------------------------------------------------------------------
# The worker thread, with a stand-in for MAME
class FakeMame:
    """Stands in for subprocess.Popen.  Reports every set as good, or blocks until killed when block is set."""
    block = False
    runs = []
    started = threading.Event()

    def __init__(self, cmd, **kwargs):
        self.names = cmd[cmd.index('-verifyroms') + 1:]
        self.rom_path = cmd[cmd.index('-rompath') + 1]
        self.killed = threading.Event()
        FakeMame.runs.append(self)

    def communicate(self):
        FakeMame.started.set()
        if FakeMame.block:
            self.killed.wait(10)
        return ''.join(f'romset {name} is good\n' for name in self.names), 'a warning\n'

    def kill(self):
        self.killed.set()


@pytest.fixture
def fake_mame(monkeypatch):
    monkeypatch.setattr(checkall.subprocess, 'Popen', FakeMame)
    monkeypatch.setattr(checkall.wx, 'CallAfter', lambda function, *args: function(*args))
    FakeMame.block = False
    FakeMame.runs = []
    FakeMame.started = threading.Event()
    return FakeMame


def run_worker(set_names, rom_path='roms1;roms2'):
    progress, finished = [], []
    worker = checkall.CheckAllThread('mame', rom_path, set_names, lambda *args: progress.append(args),
                                     lambda *args: finished.append(args))
    return worker, progress, finished


def test_worker_checks_every_set_with_every_rom_folder(fake_mame):
    set_names = [f'set{i:03}' for i in range(120)]
    worker, progress, finished = run_worker(set_names)
    worker.start()
    worker.join(10)
    results, messages, _elapsed, stopped = finished[0]
    assert sorted(names(results)) == set_names and not stopped
    assert all(result.status == GOOD for result in results)
    assert messages == ['a warning']                    # Once, not once per MAME run
    assert progress[-1] == (120, 120)
    assert {run.rom_path for run in fake_mame.runs} == {'roms1;roms2'}
    assert len(fake_mame.runs) == len(checkall.chunk_names(set_names))


def test_stop_ends_mame_and_drops_unfinished_sets(fake_mame):
    fake_mame.block = True
    worker, _progress, finished = run_worker([f'set{i:03}' for i in range(500)])
    worker.start()
    assert fake_mame.started.wait(10)
    worker.stop()
    worker.join(10)
    assert not worker.is_alive()
    results, _messages, _elapsed, stopped = finished[0]
    assert stopped and results == []                   # Not reported as 'not found'
    assert len(fake_mame.runs) <= checkall.mame_worker_count()     # The chunks not started were cancelled
    assert all(run.killed.is_set() for run in fake_mame.runs)


def test_mame_that_will_not_start_is_reported(monkeypatch):
    def fail(*args, **kwargs):
        raise OSError('no such file')
    monkeypatch.setattr(checkall.subprocess, 'Popen', fail)
    monkeypatch.setattr(checkall.wx, 'CallAfter', lambda function, *args: function(*args))
    worker, _progress, finished = run_worker(['aaa'])
    worker.start()
    worker.join(10)
    results, messages, _elapsed, _stopped = finished[0]
    assert results == [] and 'no such file' in messages[0]


# ----------------------------------------------------------------------------------------------------------------------
# The window
@pytest.fixture
def window(wx_app, data_dir, monkeypatch):
    import app_paths
    monkeypatch.setattr(app_paths, 'app_dir', lambda: os.getcwd())     # See test_alternate_emulators.window
    monkeypatch.setattr(app_paths, 'migrate_data', lambda source, target: [])
    old_log = wx.Log.SetActiveTarget(wx.LogStderr())
    monkeypatch.setattr(wx, 'MessageBox', lambda *args, **kwargs: wx.ID_OK)
    monkeypatch.setattr(checkall.CheckAll, 'Show', lambda self, show=True: False)
    frame = checkall.CheckAll.open('mame', str(data_dir), None)
    yield frame
    if frame:
        frame.Close()
    wx.Log.SetActiveTarget(old_log)
    wx_app.Yield(True)


def test_only_one_window_opens(window, data_dir):
    assert checkall.CheckAll.open('mame', str(data_dir), None) is window


def test_filters_show_counts_and_matching_sets(window, results):
    window.on_finished(results, [], 1.0, False)
    labels = [rb.GetLabel() for rb in window.filter_buttons]
    assert labels[0].endswith('(4)') and labels[2].endswith('(1)')
    assert window.recheck_button.IsEnabled()
    window.filter_buttons[2].SetValue(True)                 # Is Bad
    shown, _header = window.shown_results()
    assert names(shown) == ['aaa']


def test_closing_stops_the_check(window):
    stopped = []

    class Worker:
        def stop(self):
            stopped.append(True)
    window.worker = Worker()
    window.Close()
    assert stopped == [True]
    assert checkall.CheckAll._open_window is None
