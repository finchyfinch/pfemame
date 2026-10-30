#!/usr/bin/env python3

# ----------------------------------------------------------------------------------------------------------------------
# rom_picker_dialog.py

"""
Online ROM-ZIP picker dialog.

Presents the candidate ROM ZIP files returned by online_rom_search in a sortable report-style list (there is
nothing to preview for a ZIP, so a list is clearer than the tiled image picker).  Each row shows the result of the
caller's MAME validation pass (see pfemame._validate_rom_candidates): how many ROM files in the ZIP matched the
user's MAME version, how many were missing/wrong, the ZIP size, and an overall status.

The operator selects a row and presses 'Download Selected' to accept (double-click confirms straight away) or
'Cancel'/Escape to abort.  An optional 'Verify more' button validates further (so-far unverified) candidates.

On accept, ShowModal() returns wx.ID_OK and self.selected_candidate holds the chosen RomCandidate; otherwise it
returns wx.ID_CANCEL and self.selected_candidate is None.
"""

import wx

import functions
import online_rom_search

_ = functions.set_up_language()

# Overall-status text shown per row, keyed by RomCandidate.verify_status.
_STATUS_LABELS = {
    'good': _('Good'),
    'bad': _('Bad / incomplete'),
    'best available': _('Best available'),
    'error': _('Could not verify'),
    '': _('Not verified'),
}


# ----------------------------------------------------------------------------------------------------------------------
class RomPickerDialog(wx.Dialog):
    """Modal dialog that lets the operator pick one ROM ZIP from a list of online candidates."""

    def __init__(self, parent: wx.Window, title: str,
                 candidates: list[online_rom_search.RomCandidate], on_verify_more=None):
        super().__init__(parent, title=title,
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER | wx.MAXIMIZE_BOX,
                         size=wx.Size(880, 480))

        self.selected_candidate: online_rom_search.RomCandidate | None = None
        self._candidates = candidates
        self._on_verify_more = on_verify_more

        try:
            self.SetIcon(wx.Icon(functions.path_to_me() + '/images/pfemame.ico', wx.BITMAP_TYPE_ICO))
        except Exception:
            pass

        panel = wx.Panel(self)
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        heading = wx.StaticText(panel, label=_('Select a ROM ZIP to download, then choose "Download Selected". '
                                               'Double-click a row to download it straight away.'))
        main_sizer.Add(heading, 0, wx.ALL, 10)

        self.list_ctrl = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.BORDER_SUNKEN)
        self.list_ctrl.InsertColumn(0, _('Source'), width=130)
        self.list_ctrl.InsertColumn(1, _('ROM'), width=110)
        self.list_ctrl.InsertColumn(2, _('All matching files'), width=120, format=wx.LIST_FORMAT_RIGHT)
        self.list_ctrl.InsertColumn(3, _('Partial matching files'), width=140, format=wx.LIST_FORMAT_RIGHT)
        self.list_ctrl.InsertColumn(4, _('Size'), width=90, format=wx.LIST_FORMAT_RIGHT)
        self.list_ctrl.InsertColumn(5, _('Status'), width=130)
        self.list_ctrl.InsertColumn(6, _('Found in'), width=240)

        for index in range(len(candidates)):
            self.list_ctrl.InsertItem(index, '')
            self._populate_row(index)

        if candidates:
            self.list_ctrl.Select(0)
            self.list_ctrl.Focus(0)
            self.selected_candidate = candidates[0]

        main_sizer.Add(self.list_ctrl, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        # Buttons
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)
        if on_verify_more is not None:
            self.verify_button = wx.Button(panel, label=_('Verify more'))
            self.verify_button.Bind(wx.EVT_BUTTON, self._on_verify_more_clicked)
            button_sizer.Add(self.verify_button, 0, wx.RIGHT, 6)
        self.ok_button = wx.Button(panel, wx.ID_OK, _('Download Selected'))
        self.ok_button.Enable(bool(candidates))
        cancel_button = wx.Button(panel, wx.ID_CANCEL, _('Cancel'))
        button_sizer.AddStretchSpacer()
        button_sizer.Add(self.ok_button, 0, wx.ALL, 6)
        button_sizer.Add(cancel_button, 0, wx.ALL, 6)
        main_sizer.Add(button_sizer, 0, wx.EXPAND)

        panel.SetSizer(main_sizer)

        self.list_ctrl.Bind(wx.EVT_LIST_ITEM_SELECTED, self._on_row_selected)
        self.list_ctrl.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_row_activated)
        self.Bind(wx.EVT_BUTTON, self._on_ok, id=wx.ID_OK)
        cancel_button.Bind(wx.EVT_BUTTON, self._on_cancel)
        self.Bind(wx.EVT_CLOSE, self._on_cancel)

        self.CentreOnParent()

    # ------------------------------------------------------------------------------------------------------------------
    def _populate_row(self, index: int) -> None:
        """(Re)fill one row from its RomCandidate's current values."""
        candidate = self._candidates[index]
        good = '-' if candidate.verify_good is None else str(candidate.verify_good)
        bad = '-' if candidate.verify_bad is None else str(candidate.verify_bad)
        status = _STATUS_LABELS.get(candidate.verify_status, candidate.verify_status or _('Not verified'))
        self.list_ctrl.SetItem(index, 0, candidate.source)
        self.list_ctrl.SetItem(index, 1, candidate.filename)
        self.list_ctrl.SetItem(index, 2, good)
        self.list_ctrl.SetItem(index, 3, bad)
        self.list_ctrl.SetItem(index, 4, online_rom_search.human_size(candidate.size))
        self.list_ctrl.SetItem(index, 5, status)
        self.list_ctrl.SetItem(index, 6, candidate.item)

    def refresh_rows(self) -> None:
        """Re-read every candidate (e.g. after a 'Verify more' pass) and update the displayed values."""
        if not self:
            return
        for index in range(len(self._candidates)):
            self._populate_row(index)

    def set_verify_enabled(self, enabled: bool) -> None:
        if getattr(self, 'verify_button', None) is not None and self:
            self.verify_button.Enable(enabled)

    # ------------------------------------------------------------------------------------------------------------------
    def _on_verify_more_clicked(self, _event) -> None:
        if self._on_verify_more is not None:
            self.set_verify_enabled(False)
            self._on_verify_more(self)   # The caller validates remaining rows and calls refresh_rows() when done.

    def _on_row_selected(self, event) -> None:
        index = event.GetIndex()
        if 0 <= index < len(self._candidates):
            self.selected_candidate = self._candidates[index]
            self.ok_button.Enable()

    def _on_row_activated(self, event) -> None:
        self._on_row_selected(event)
        if self.selected_candidate is not None:
            self._on_ok(None)

    def _on_ok(self, _event) -> None:
        self.EndModal(wx.ID_OK)

    def _on_cancel(self, _event) -> None:
        self.selected_candidate = None
        self.EndModal(wx.ID_CANCEL)
