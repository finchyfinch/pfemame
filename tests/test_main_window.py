"""
Tests for main window (pfemame.py / rom_grid.py) logic that doesn't need a real main window: the MainFrame methods
are called with a stand-in object holding just what each one uses.
"""
import logging
import types

import pytest

import functions


def row(name, file_name, program='', favorite='0', runs='0', rating='0', exists='1'):
    """A mylist row (see the index_* constants in rom_grid.py)."""
    return [name, file_name, program, exists, rating, runs, favorite, 'Arcade', '', '', '1981', 'Namco']


@pytest.fixture
def pfemame(wx_app, monkeypatch):
    import pfemame
    monkeypatch.setattr(pfemame, '_', lambda text: text, raising=False)
    return pfemame


def window(pfemame, **attributes):
    """A stand-in for the main window with the given attributes and MainFrame's helper methods bound to it."""
    ns = types.SimpleNamespace(my_logger=logging.getLogger('test'), **attributes)
    for name in ('_match_system_program', 'get_rom_file_name', '_dat_key', '_hidden_columns'):
        setattr(ns, name, types.MethodType(getattr(pfemame.MainFrame, name), ns))
    return ns


# ----------------------------------------------------------------------------------------------------------------------
# Page Up / Page Down
class FakeList:
    def __init__(self, rows, selected, per_page=10):
        self.rows, self.selected, self.per_page = rows, selected, per_page

    def GetItemCount(self):
        return self.rows

    def GetFirstSelected(self):
        return self.selected

    def GetCountPerPage(self):
        return self.per_page

    def Select(self, row):
        self.selected = row

    def EnsureVisible(self, row):
        pass


@pytest.mark.parametrize('start, direction, expected', [
    (20, 1, 30),        # Page Down moves down (it used to move up)
    (20, -1, 10),       # Page Up moves up
    (95, 1, 99),        # Less than a page left - goes to the last ROM rather than doing nothing
    (3, -1, 0),         # ... and to the first ROM
])
def test_page_up_and_down(pfemame, start, direction, expected):
    frame = window(pfemame, list=FakeList(100, start), video_stop=lambda: None)
    pfemame.MainFrame.scroll_list_by_page(frame, direction)
    assert frame.list.selected == expected


def test_page_down_in_an_empty_list_does_nothing(pfemame):
    frame = window(pfemame, list=FakeList(0, -1), video_stop=lambda: pytest.fail('should not be called'))
    pfemame.MainFrame.scroll_list_by_page(frame, 1)


# ----------------------------------------------------------------------------------------------------------------------
# Sorting by a column
def sort_window(pfemame, mylist):
    labels = {}
    grid = types.SimpleNamespace(GetColumnCount=lambda: 12, GetColumnLabel=lambda col: labels.get(col, f'col{col}'),
                                 SetColumnLabel=lambda col, text: labels.__setitem__(col, text))
    refreshed = []
    frame = window(pfemame, mylist=mylist, sort_column=-1, sort_ascending=True, list=grid, filter_cache={'x': 1},
                   on_filter_rom_list=lambda **kwargs: refreshed.append(kwargs), Refresh=lambda: None)
    return frame, refreshed


def test_runs_column_sorts_as_numbers(pfemame):
    rows = [row('A', 'a', runs='10'), row('B', 'b', runs='2'), row('C', 'c', runs='0')]
    frame, refreshed = sort_window(pfemame, rows)
    event = types.SimpleNamespace(GetCol=lambda: 5, Skip=lambda: None)
    pfemame.MainFrame.on_column_clicked(frame, event)
    assert [r[5] for r in frame.mylist] == ['0', '2', '10']
    pfemame.MainFrame.on_column_clicked(frame, event)           # Second click sorts the other way
    assert [r[5] for r in frame.mylist] == ['10', '2', '0']


def test_sorting_keeps_the_current_view_and_search(pfemame):
    frame, refreshed = sort_window(pfemame, [row('B', 'b'), row('a', 'a')])
    pfemame.MainFrame.on_column_clicked(frame, types.SimpleNamespace(GetCol=lambda: 0, Skip=lambda: None))
    assert [r[0] for r in frame.mylist] == ['a', 'B']
    assert frame.filter_cache == {}
    assert refreshed == [{'event': -1, 'preserve_search': True}]   # Not 'show every ROM'


# ----------------------------------------------------------------------------------------------------------------------
# Finding a ROM's row (favorites, ratings, number of runs)
def test_rom_is_found_by_its_file_name_even_without_its_full_name(pfemame):
    frame = window(pfemame, mylist=[row('Galaga', 'galaga'), row('Pac-Man', 'pacman')])
    # A ROM started with -r on the command line only has its file name - this used to raise StopIteration
    assert frame.get_rom_file_name('', '', 'pacman') == ('pacman', 1)


def test_a_rom_not_in_the_list_gives_no_index(pfemame):
    frame = window(pfemame, mylist=[row('Galaga', 'galaga')])
    assert frame.get_rom_file_name('', '', 'missing') == ('missing', None)


def test_system_program_key(pfemame):
    frame = window(pfemame, mylist=[row('Nintendo', 'nes', 'smb.zip')])
    assert frame.get_rom_file_name('smb.zip', '', 'nes') == ('nes-->Nintendo-->smb.zip', 0)


# ----------------------------------------------------------------------------------------------------------------------
# Reading favorites.dat / runs.dat
def dat_window(pfemame, mylist, data_dir):
    return window(pfemame, mylist=mylist, data_dir=str(data_dir), statusbar_panel=types.SimpleNamespace(
        set_status=lambda text: None), Refresh=lambda: None, messages_append=lambda *args: None)


def test_system_program_flags_go_to_the_right_system(pfemame, tmp_path):
    # The same program file name in two systems' software lists
    rows = [row('Nintendo', 'nes', 'game.zip'), row('Sega Master System', 'sms', 'game.zip')]
    (tmp_path / 'favorites.dat').write_text('sms-->Sega Master System-->game.zip\n', encoding='utf-8')
    frame = dat_window(pfemame, rows, tmp_path)
    pfemame.MainFrame.get_dat_file_data(frame, 'favorites.dat')
    assert [r[6] for r in rows] == ['0', '1']             # Used to flag the first 'game.zip', the NES one


def test_old_and_new_runs_dat_keys_are_both_read(pfemame, tmp_path):
    rows = [row('Pac-Man', 'pacman'), row('Nintendo', 'nes', 'smb.zip'), row('Sega Master System', 'sms', 'smb.zip')]
    # Older runs.dat files have 'system name-->system ROM-->program', newer ones the favorites.dat order
    (tmp_path / 'runs.dat').write_text('pacman=3\nSega Master System-->sms-->smb.zip=2\n'
                                       'nes-->Nintendo-->smb.zip=5\n', encoding='utf-8')
    frame = dat_window(pfemame, rows, tmp_path)
    pfemame.MainFrame.get_dat_file_data(frame, 'runs.dat')
    assert [r[5] for r in rows] == ['3', '5', '2']


def test_dat_key_matches_favorites_format(pfemame):
    assert pfemame.MainFrame._dat_key(row('Pac-Man', 'pacman')) == 'pacman'
    assert pfemame.MainFrame._dat_key(row('Nintendo', 'nes', 'smb.zip')) == 'nes-->Nintendo-->smb.zip'


# ----------------------------------------------------------------------------------------------------------------------
# Data file encoding
def test_old_data_files_in_the_system_encoding_can_still_be_read(tmp_path, monkeypatch):
    monkeypatch.setattr(functions.locale, 'getpreferredencoding', lambda _do_setlocale=True: 'cp1252')
    path = tmp_path / 'favorites.dat'
    path.write_bytes('nes-->Nintendo-->Pokémon.zip\r\npacman\r\n'.encode('cp1252'))
    assert functions.read_dat_lines(str(path)) == ['nes-->Nintendo-->Pokémon.zip\n', 'pacman\n']
    functions.add_dat_entry(str(path), 'galaga')        # ... and are written back as UTF-8
    assert functions.dat_file_contains(str(path), 'nes-->Nintendo-->Pokémon.zip')
    assert 'Pokémon' in path.read_bytes().decode('utf-8')


# ----------------------------------------------------------------------------------------------------------------------
# Export favorites
def test_favorite_export_items(pfemame, tmp_path):
    roms = tmp_path / 'roms'
    (roms / 'kinst').mkdir(parents=True)                # A CHD folder
    for name in ('galaga.zip', 'kinst.zip', 'pacman.7z', 'dkong.zip'):
        (roms / name).write_bytes(b'')
    rows = [row('Galaga', 'galaga', favorite='1'), row('Killer Instinct', 'kinst', favorite='1'),
            row('Pac-Man', 'pacman', favorite='1'), row('Donkey Kong', 'dkong'),  # not a favorite
            row('Missing', 'missing', favorite='1'), row('Galaga', 'galaga', favorite='1')]   # twice
    items = pfemame.favorite_export_items(rows, [str(roms)])
    assert [name for _source, name in items] == ['galaga.zip', 'kinst.zip', 'kinst', 'pacman.7z']


# ----------------------------------------------------------------------------------------------------------------------
# Columns
@pytest.mark.parametrize('systems, expected', [('True', {9}), ('False', {9, 2, 8})])
def test_hidden_columns(pfemame, systems, expected):
    assert window(pfemame, prefSystemsSupport=systems)._hidden_columns() == expected


class FakeGrid:
    """Just what RomGrid.distribute_columns uses.  Like wx.grid.Grid, setting a width shows a hidden column."""
    def __init__(self, width, hidden=()):
        import rom_grid
        self.width, self.hidden = width, set(hidden)
        self.sizes = {col: size for col, size in rom_grid.DEFAULT_COLUMN_WIDTHS}

    def GetClientSize(self):
        return types.SimpleNamespace(width=self.width)

    def GetColSize(self, col):
        return 0 if col in self.hidden else self.sizes[col]

    def IsColShown(self, col):
        return col not in self.hidden

    def SetColSize(self, col, size):
        self.sizes[col] = size
        self.hidden.discard(col)


def test_distributing_columns_keeps_a_hidden_system_column_hidden(wx_app):
    import rom_grid
    grid = FakeGrid(2000, hidden={rom_grid.index_system_program_file_name, rom_grid.index_path_media_name})
    rom_grid.RomGrid.distribute_columns(grid)
    assert not grid.IsColShown(rom_grid.index_system_program_file_name)     # Resizing the window used to show it
    assert grid.sizes[rom_grid.index_rom_name] > 1000                        # ROM Name gets the space instead


def test_distributing_columns_shares_the_space_when_systems_are_shown(wx_app):
    import rom_grid
    grid = FakeGrid(2000, hidden={rom_grid.index_path_media_name})
    rom_grid.RomGrid.distribute_columns(grid)
    assert abs(grid.sizes[rom_grid.index_rom_name] - grid.sizes[rom_grid.index_system_program_file_name]) <= 1


# ----------------------------------------------------------------------------------------------------------------------
# ROM image cache
def test_a_replaced_image_is_loaded_again(pfemame, tmp_path):
    import os
    from PIL import Image
    path = tmp_path / 'pacman.png'
    Image.new('RGB', (100, 50)).save(path)
    first = pfemame._scaled_rom_image(str(path), os.path.getmtime(path))
    assert first.GetWidth() == pfemame.image_size_x                     # Wide image: fits the width
    Image.new('RGB', (50, 100)).save(path)
    os.utime(path, (1, 1))                                              # A different modification time
    second = pfemame._scaled_rom_image(str(path), os.path.getmtime(path))
    assert second.GetHeight() == pfemame.image_size_y                   # The new (tall) image, not the cached one


def test_a_file_that_is_not_an_image_raises(pfemame, tmp_path):
    path = tmp_path / 'broken.png'
    path.write_bytes(b'not an image')
    with pytest.raises(Exception):
        pfemame._scaled_rom_image(str(path), 1.0)


# ----------------------------------------------------------------------------------------------------------------------
# Messages window
def test_messages_window_keeps_only_the_last_lines(wx_app):
    import wx
    from custom_text_ctrl import CustomTextCtrl
    frame = wx.Frame(None)
    try:
        ctrl = CustomTextCtrl(frame, style=wx.TE_MULTILINE)
        ctrl.SetMaxLines(3)
        for number in range(1, 6):
            ctrl.AppendText(f'line {number}\n')
        assert ctrl.GetValue().splitlines() == ['line 3', 'line 4', 'line 5']
    finally:
        frame.Destroy()


def test_messages_window_scroll_height_follows_clear_and_set_value(wx_app):
    # The height used to stay at the last AppendText's line count, leaving blank space to scroll over.
    # (The text's own height is checked - the scrolled area never reports less than its window height.  Read-only
    # like the Messages window: an editable box is given spare height)
    import wx
    from custom_text_ctrl import CustomTextCtrl
    frame = wx.Frame(None)
    try:
        ctrl = CustomTextCtrl(frame, style=wx.TE_MULTILINE | wx.TE_READONLY)
        line_height = ctrl.text.GetCharHeight()
        for number in range(50):
            ctrl.AppendText(f'line {number}\n')
        assert ctrl.text.GetSize().height == 51 * line_height
        ctrl.Clear()
        assert ctrl.text.GetSize().height == line_height
        ctrl.SetValue('one\ntwo')
        assert ctrl.text.GetSize().height == 2 * line_height
    finally:
        frame.Destroy()


def test_categories_panel_keeps_its_scroll_position_when_resized(wx_app):
    # wx's own layout used to run after the resize handler and put the content back at the top
    import wx
    from custom_scrolled_panel import CustomScrolledPanel
    frame = wx.Frame(None)
    try:
        panel = CustomScrolledPanel(frame, size=wx.Size(150, 200))
        for number in range(60):
            panel.add_widget(wx.CheckBox(panel.content, label=f'Category {number}'))
        panel.content_y = -300
        panel._update_scroll_limits()
        panel.SetSize(wx.Size(170, 240))
        assert panel.content.GetPosition().y == -300
        assert panel.content.GetSize().height == panel.content_sizer.GetMinSize().height
    finally:
        frame.Destroy()


def test_read_only_messages_window_still_takes_text_from_the_code(wx_app):
    # Read-only only stops the user typing - AppendText used to do nothing on a read-only control
    import wx
    from custom_text_ctrl import CustomTextCtrl
    frame = wx.Frame(None)
    try:
        ctrl = CustomTextCtrl(frame, style=wx.TE_MULTILINE | wx.TE_READONLY)
        ctrl.AppendText('first\n')
        ctrl.AppendText('second\n')
        assert ctrl.GetValue().splitlines() == ['first', 'second']
        assert not ctrl.IsEditable() and not ctrl.text.IsEditable()
        ctrl.SetEditable(True)
        assert ctrl.text.IsEditable()
    finally:
        frame.Destroy()


def test_messages_window_drops_old_lines_in_batches(wx_app):
    # Once over the limit the oldest lines go down to 90% of it in one go, and the control keeps the same text
    import wx
    from custom_text_ctrl import CustomTextCtrl
    frame = wx.Frame(None)
    try:
        ctrl = CustomTextCtrl(frame, style=wx.TE_MULTILINE | wx.TE_READONLY)
        ctrl.SetMaxLines(100)
        for number in range(150):
            ctrl.AppendText(f'line {number}\n')
        lines = ctrl.GetValue().splitlines()
        assert 90 <= len(lines) <= 100
        assert lines[-1] == 'line 149'
        assert lines == [f'line {number}' for number in range(150 - len(lines), 150)]
        assert ctrl.GetValue() == ctrl.text_content
    finally:
        frame.Destroy()


def test_appending_several_lines_at_once_keeps_them_all(wx_app):
    # On Windows the edit control drops text that doesn't fit its height, so it must be sized before appending
    import wx
    from custom_text_ctrl import CustomTextCtrl
    frame = wx.Frame(None)
    try:
        ctrl = CustomTextCtrl(frame, style=wx.TE_MULTILINE | wx.TE_READONLY)
        ctrl.AppendText('one\n')
        ctrl.AppendText('two\nthree\nfour\nfive\n')
        ctrl.AppendText('a much longer line than the others that would have to wrap in a narrow control\n')
        assert ctrl.GetValue().splitlines() == ['one', 'two', 'three', 'four', 'five', 'a much longer line than the '
                                                'others that would have to wrap in a narrow control']
    finally:
        frame.Destroy()


def test_editable_text_box_has_room_to_type_a_new_line(wx_app):
    # On Windows the edit control drops typing that doesn't fit its height, so an editable box is kept a page taller
    # than its text (outside the scrollable area).  A read-only box is exactly as tall as its text.
    import wx
    from custom_text_ctrl import CustomTextCtrl
    frame = wx.Frame(None)
    try:
        editable = CustomTextCtrl(frame, value='one\ntwo', style=wx.TE_MULTILINE)
        read_only = CustomTextCtrl(frame, value='one\ntwo', style=wx.TE_MULTILINE | wx.TE_READONLY)
        line_height = editable.text.GetCharHeight()
        assert editable.text.GetSize().height >= 2 * line_height + 5 * line_height
        assert read_only.text.GetSize().height == 2 * line_height
        read_only.SetEditable(True)
        assert read_only.text.GetSize().height > 2 * line_height
    finally:
        frame.Destroy()


def test_an_error_alert_scrolls_the_messages_window_to_the_end(pfemame):
    # New messages leave a Messages window that was scrolled up alone - but the flashing alert must show the error
    import wx
    from custom_text_ctrl import CustomTextCtrl
    frame = wx.Frame(None)
    try:
        messages = CustomTextCtrl(frame, style=wx.TE_MULTILINE | wx.TE_READONLY)
        messages.SetSize(wx.Size(300, 100))
        messages.Layout()
        for number in range(100):
            messages.AppendText(f'line {number}\n')
        messages.scrolled_area.Scroll(0, 0)                         # Scrolled up to read
        stand_in = window(pfemame, pref_flash_messages_if_error='True', controlMessages=messages,
                          alert_timer=types.SimpleNamespace(Start=lambda interval: None),
                          messages_append=lambda text, delimiter=False: messages.AppendText(text))
        pfemame.MainFrame.enable_alert_timer(stand_in)
        area = messages.scrolled_area
        assert area.GetViewStart()[1] == area.GetVirtualSize().height - area.GetClientSize().height
    finally:
        frame.Destroy()


def test_the_star_rating_popup_margin_uses_the_colour_scheme(wx_app, data_dir):
    # The margin round the stars used to stay the system's light grey
    import wx
    import functions
    import starRating
    frame = wx.Frame(None)
    try:
        popup = starRating.StarRatingPopup(frame, initial_rating=3)
        background = functions.get_application_colors()['text_background']
        assert popup.GetBackgroundColour() == background == popup.panel.GetBackgroundColour()
        popup.Destroy()
    finally:
        frame.Destroy()


# ----------------------------------------------------------------------------------------------------------------------
# Fading the window in at start-up
def fade_window(pfemame, monkeypatch, clock):
    import wx
    monkeypatch.setattr(wx, 'CallAfter', lambda function, *args: function(*args))
    monkeypatch.setattr(pfemame.time, 'perf_counter', lambda: clock[0])
    stopped = []
    frame = window(pfemame, _window_shown=False, _window_shown_waiting=[], _fade_start=None, alphas=[],
                   _fade_timer=types.SimpleNamespace(Stop=lambda: stopped.append(True)))
    frame.SetTransparent = frame.alphas.append
    for name in ('when_window_shown', '_window_is_shown', '_on_fade_timer'):
        setattr(frame, name, types.MethodType(getattr(pfemame.MainFrame, name), frame))
    return frame, stopped


def test_start_up_work_waits_for_the_fade_and_the_alpha_follows_the_time(pfemame, monkeypatch):
    clock = [10.0]
    frame, stopped = fade_window(pfemame, monkeypatch, clock)
    ran = []
    frame.when_window_shown(lambda: ran.append('setup'))
    frame._on_fade_timer(None)                      # The first tick starts the clock
    clock[0] += pfemame.FADE_IN_SECONDS / 2
    frame._on_fade_timer(None)
    assert frame.alphas == [0, 127] and ran == [] and not stopped
    clock[0] += pfemame.FADE_IN_SECONDS             # A late tick goes straight to the end rather than a small step
    frame._on_fade_timer(None)
    assert frame.alphas[-1] == 255 and stopped and ran == ['setup']
    frame.when_window_shown(lambda: ran.append('later'))       # Once shown, callbacks run straight away
    assert ran == ['setup', 'later']


def test_a_missing_catver_ini_is_reported_once_the_window_is_shown(pfemame, monkeypatch, tmp_path):
    # It used to pop up while the window was still being built, before anything was on screen
    shown = []
    monkeypatch.setattr(functions, 'show_error_dialog', lambda parent, text, title: shown.append(text))
    frame, _stopped = fade_window(pfemame, monkeypatch, [0.0])
    frame.pathCatver = str(tmp_path / 'catver.ini')
    categories, version = pfemame.MainFrame.build_categories(frame)     # While the window is built ...
    frame.when_window_shown(lambda: shown.append('start-up'))           # ... then the constructor queues start-up
    assert shown == [] and version == '' and categories['.1'] == 'Not Classified'
    frame._window_is_shown()
    assert shown[0].startswith('Cannot find the catver.ini file') and shown[1] == 'start-up'


def test_selecting_a_rom_scrolls_to_it_first(wx_app):
    # Selecting a row off screen first made wx look up every cell between it and the rows on screen (very slow)
    import rom_grid
    calls = []
    grid = types.SimpleNamespace(GetNumberRows=lambda: 50000,
                                 MakeCellVisible=lambda row, col: calls.append(('scroll', row)),
                                 SelectRow=lambda row: calls.append(('select', row)),
                                 SetGridCursor=lambda row, col: calls.append(('cursor', row)))
    rom_grid.RomGrid.Select(grid, 40000)
    assert calls == [('scroll', 40000), ('select', 40000), ('cursor', 40000)]
    calls.clear()
    rom_grid.RomGrid.Select(grid, 50000)        # Past the end - nothing happens
    assert calls == []


def test_a_catver_ini_path_that_is_a_folder_is_reported_not_a_crash(pfemame, monkeypatch, tmp_path):
    # On Linux opening a folder raised IsADirectoryError, which wasn't caught, so pfeMAME didn't start
    shown = []
    monkeypatch.setattr(functions, 'show_error_dialog', lambda parent, text, title: shown.append(text))
    frame, _stopped = fade_window(pfemame, monkeypatch, [0.0])
    frame.pathCatver = str(tmp_path)
    categories, _version = pfemame.MainFrame.build_categories(frame)
    frame._window_is_shown()
    assert shown[0].startswith('Cannot find the catver.ini file') and categories['.1'] == 'Not Classified'


def test_a_catver_ini_that_cannot_be_read_is_reported(pfemame, monkeypatch, tmp_path):
    shown = []
    monkeypatch.setattr(functions, 'show_error_dialog', lambda parent, text, title: shown.append(text))
    catver = tmp_path / 'catver.ini'
    catver.write_text('[Category]\n', encoding='utf-8')
    frame, _stopped = fade_window(pfemame, monkeypatch, [0.0])
    frame.pathCatver = str(catver)

    def refuse(*args, **kwargs):            # e.g. a network drive that has gone away
        raise OSError(5, 'Input/output error')
    with monkeypatch.context() as patch:
        patch.setattr('builtins.open', refuse)
        pfemame.MainFrame.build_categories(frame)
    frame._window_is_shown()
    assert shown[0].startswith('Unable to read the catver.ini file')
