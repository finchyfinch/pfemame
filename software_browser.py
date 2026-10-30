#!/usr/bin/env python3

# ----------------------------------------------------------------------------------------------------------------------
# software_browser.py

"""
Software list browser: every piece of software MAME knows about for a system (from its software lists / HASH files)
with its title, year, publisher and how well MAME supports it - and whether you have it.  Software you have can be
shown in the ROM list or played straight from here.
"""

import threading

import wx

import functions
import software_lists

_ = functions.set_up_language()

def N_(text: str) -> str:
    """Marks a string for translation (it is translated where it is displayed)."""
    return text


COLUMNS = [(N_('Have'), 50), (N_('Title'), 330), (N_('Year'), 55), (N_('Publisher'), 180), (N_('Supported'), 80),
           (N_('Short name'), 110), (N_('List'), 120)]
SUPPORTED_TEXT = {'yes': N_('Yes'), 'partial': N_('Partially'), 'no': N_('No')}

# mylist columns (see pfemame.py)
INDEX_ROM_FILE_NAME = 1
INDEX_SYSTEM_PROGRAM_FILE_NAME = 2
INDEX_SYSTEM_SHORT_NAME = 8
INDEX_SYSTEM_FOLDER_NAME = 9


def owned_software(mylist: list, system: str) -> tuple[dict, dict]:
    """
    The system's program rows you have, keyed two ways: {(list name, short name): row} using the media folder the
    file was found in, and {short name: row} as a fallback.
    """
    by_list, by_name = {}, {}
    for row in mylist:
        if row[INDEX_ROM_FILE_NAME] == system and row[INDEX_SYSTEM_PROGRAM_FILE_NAME] and row[INDEX_SYSTEM_SHORT_NAME]:
            short = row[INDEX_SYSTEM_SHORT_NAME].lower()
            by_list.setdefault((row[INDEX_SYSTEM_FOLDER_NAME].lower(), short), row)
            by_name.setdefault(short, row)
    return by_list, by_name


class SoftwareListCtrl(wx.ListCtrl):
    """Virtual list - the Spectrum alone has tens of thousands of entries."""

    def __init__(self, parent):
        super().__init__(parent, style=wx.LC_REPORT | wx.LC_VIRTUAL | wx.LC_SINGLE_SEL | wx.LC_HRULES)
        for index, (title, width) in enumerate(COLUMNS):
            self.InsertColumn(index, _(title), width=self.FromDIP(width))
        self.rows: list[tuple] = []      # (row in mylist or None, Software, SoftwareList)
        self.SetItemCount(0)

    def set_rows(self, rows: list[tuple]) -> None:
        self.rows = rows
        self.SetItemCount(len(rows))
        self.Refresh()

    def OnGetItemText(self, item, column):
        owned, software, software_list = self.rows[item]
        return [('✓' if owned is not None else ''), software.description, software.year, software.publisher,
                _(SUPPORTED_TEXT.get(software.supported, software.supported)), software.name,
                software_list.name][column]


class SoftwareBrowser(wx.Frame):
    def __init__(self, main_frame, system: str, system_title: str, mame_exe: str, mylist: list):
        super().__init__(main_frame, title=_('Software Lists - {}').format(system_title),
                         size=wx.Size(1000, 650))
        self.main_frame = main_frame
        self.system = system
        self.lists: list[software_lists.SoftwareList] = []
        self.owned_by_list, self.owned_by_name = owned_software(mylist, system)
        self.sort_column, self.sort_ascending = 1, True

        colours = functions.get_application_colors()
        panel = wx.Panel(self)
        panel.SetBackgroundColour(colours['window_background'])

        self.list_choice = wx.Choice(panel, choices=[_('Loading...')])
        self.list_choice.SetSelection(0)
        self.search = wx.SearchCtrl(panel, size=self.FromDIP(wx.Size(260, -1)))
        self.search.ShowCancelButton(True)
        self.search.SetHint(_('Search title, publisher, year'))
        self.only_owned = wx.CheckBox(panel, label=_('Only software I have'))
        self.count_text = wx.StaticText(panel, label=_('Reading the software lists from MAME...'))

        top = wx.BoxSizer(wx.HORIZONTAL)
        top.Add(wx.StaticText(panel, label=_('List:')), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        top.Add(self.list_choice, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        top.Add(self.search, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        top.Add(self.only_owned, 0, wx.ALIGN_CENTER_VERTICAL)

        self.grid = SoftwareListCtrl(panel)

        self.show_button = wx.Button(panel, label=_('Show in ROM list'))
        self.play_button = wx.Button(panel, label=_('Play'))
        close_button = wx.Button(panel, id=wx.ID_CLOSE, label=_('Close'))
        buttons = wx.BoxSizer(wx.HORIZONTAL)
        buttons.Add(self.count_text, 1, wx.ALIGN_CENTER_VERTICAL)
        buttons.Add(self.show_button, 0, wx.RIGHT, 6)
        buttons.Add(self.play_button, 0, wx.RIGHT, 6)
        buttons.Add(close_button, 0)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(top, 0, wx.EXPAND | wx.ALL, 8)
        sizer.Add(self.grid, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        sizer.Add(buttons, 0, wx.EXPAND | wx.ALL, 8)
        panel.SetSizer(sizer)
        for control in (self.count_text, self.only_owned):
            control.SetForegroundColour(colours['text'])

        self.list_choice.Bind(wx.EVT_CHOICE, self.on_filter)
        self.search.Bind(wx.EVT_TEXT, self.on_filter)
        self.only_owned.Bind(wx.EVT_CHECKBOX, self.on_filter)
        self.grid.Bind(wx.EVT_LIST_COL_CLICK, self.on_sort)
        self.grid.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_selection)
        self.grid.Bind(wx.EVT_LIST_ITEM_ACTIVATED, lambda _e: self.on_play(None))
        self.show_button.Bind(wx.EVT_BUTTON, self.on_show)
        self.play_button.Bind(wx.EVT_BUTTON, self.on_play)
        close_button.Bind(wx.EVT_BUTTON, lambda _e: self.Close())
        self.on_selection(None)

        self.CentreOnParent()
        self.Show()
        threading.Thread(target=self._load, args=(mame_exe,), daemon=True).start()

    # ------------------------------------------------------------------------------------------------------------------
    def _load(self, mame_exe: str) -> None:
        try:
            lists = software_lists.load_for_system(mame_exe, self.system)
        except OSError:
            lists = []
        wx.CallAfter(self._loaded, lists)

    def _loaded(self, lists: list) -> None:
        if not self:
            return
        self.lists = [software_list for software_list in lists if software_list.software]
        if not self.lists:
            self.list_choice.SetItems([_('No software lists')])
            self.list_choice.SetSelection(0)
            self.count_text.SetLabel(_('MAME has no software lists for this system (or its HASH files are missing).'))
            return
        total = sum(len(software_list.software) for software_list in self.lists)
        choices = [_('All lists ({:,})').format(total)] + [
            f'{software_list.description or software_list.name} ({len(software_list.software):,})'
            for software_list in self.lists]
        self.list_choice.SetItems(choices)
        self.list_choice.SetSelection(0)
        self.on_filter(None)

    def _owned_row(self, software_list, software):
        return (self.owned_by_list.get((software_list.name.lower(), software.name.lower()))
                or self.owned_by_name.get(software.name.lower()))

    # ------------------------------------------------------------------------------------------------------------------
    def on_filter(self, _event) -> None:
        if not self.lists:
            return
        choice = self.list_choice.GetSelection()
        chosen = self.lists if choice <= 0 else [self.lists[choice - 1]]
        words = self.search.GetValue().lower().split()
        only_owned = self.only_owned.GetValue()
        rows = []
        for software_list in chosen:
            for software in software_list.software:
                owned = self._owned_row(software_list, software)
                if only_owned and owned is None:
                    continue
                if words:
                    text = f'{software.description} {software.publisher} {software.year} {software.name}'.lower()
                    if not all(word in text for word in words):
                        continue
                rows.append((owned, software, software_list))
        self._sort(rows)
        self.grid.set_rows(rows)
        have = sum(1 for owned, _software, _list in rows if owned is not None)
        self.count_text.SetLabel(_('{:,} shown, {:,} of them you have').format(len(rows), have))
        self.on_selection(None)

    def _sort(self, rows: list) -> None:
        def key(row):
            owned, software, software_list = row
            return [owned is None, software.description.lower(), software.year, software.publisher.lower(),
                    software.supported, software.name, software_list.name][self.sort_column]
        rows.sort(key=key, reverse=not self.sort_ascending)

    def on_sort(self, event) -> None:
        column = event.GetColumn()
        self.sort_ascending = not self.sort_ascending if column == self.sort_column else True
        self.sort_column = column
        rows = list(self.grid.rows)
        self._sort(rows)
        self.grid.set_rows(rows)

    def _selected(self):
        index = self.grid.GetFirstSelected()
        return self.grid.rows[index] if 0 <= index < len(self.grid.rows) else None

    def on_selection(self, _event) -> None:
        selected = self._selected()
        owned = selected is not None and selected[0] is not None
        self.show_button.Enable(owned)
        self.play_button.Enable(owned)

    def on_show(self, _event) -> bool:
        selected = self._selected()
        if not selected or selected[0] is None:
            return False
        if not self.main_frame.select_rom_row(selected[0]):
            wx.MessageBox(_('This program is not in the ROM list with the current category selection.'),
                          _('Software Lists'), wx.OK | wx.ICON_INFORMATION, self)
            return False
        return True

    def on_play(self, _event) -> None:
        selected = self._selected()
        if not selected:
            return
        if selected[0] is None:
            wx.MessageBox(_("You don't have this software in your system programs folder."), _('Software Lists'),
                          wx.OK | wx.ICON_INFORMATION, self)
            return
        if self.on_show(None):
            self.main_frame.on_double_click(ignore_columns=True)
