#!/usr/bin/env python3

# ----------------------------------------------------------------------------------------------------------------------
# rom_source_dialog.py

"""
Source-selection dialog for the 'Search for ROM online' feature.

Shown first when the operator invokes the feature.  It lists the available download sources (see
online_rom_search.ROM_SOURCES), shows whether each credentialed source has stored credentials, and lets the
operator add / edit / test / clear those credentials.  Sources that need credentials cannot be selected for a
search until credentials are stored.

On OK, ShowModal() returns wx.ID_OK and self.selected_sources holds the chosen source keys.
"""

import threading

import wx

import functions
import online_rom_search
import rom_credentials

_ = functions.set_up_language()


# ----------------------------------------------------------------------------------------------------------------------
class _CredentialsDialog(wx.Dialog):
    """Small username / password editor with a Test button for one credentialed source."""

    def __init__(self, parent: wx.Window, source_key: str, mame_version: str, logger=None):
        super().__init__(parent, title=_('Credentials for {}').format(online_rom_search.source_label(source_key)))
        self._source_key = source_key
        self._mame_version = mame_version
        self._logger = logger

        existing = rom_credentials.get(source_key)

        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        note = wx.StaticText(panel, label=_('Credentials are stored locally (obfuscated, not strongly encrypted).'))
        sizer.Add(note, 0, wx.ALL, 10)

        grid = wx.FlexGridSizer(2, 2, 8, 8)
        grid.AddGrowableCol(1, 1)
        grid.Add(wx.StaticText(panel, label=_('Username / email:')), 0, wx.ALIGN_CENTER_VERTICAL)
        self.user_ctrl = wx.TextCtrl(panel, value=existing[0] if existing else '')
        grid.Add(self.user_ctrl, 1, wx.EXPAND)
        grid.Add(wx.StaticText(panel, label=_('Password:')), 0, wx.ALIGN_CENTER_VERTICAL)
        self.pass_ctrl = wx.TextCtrl(panel, value=existing[1] if existing else '', style=wx.TE_PASSWORD)
        grid.Add(self.pass_ctrl, 1, wx.EXPAND)
        sizer.Add(grid, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        self.status = wx.StaticText(panel, label='')
        sizer.Add(self.status, 0, wx.ALL, 10)

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        self.test_button = wx.Button(panel, label=_('Test'))
        self.clear_button = wx.Button(panel, label=_('Clear'))
        save_button = wx.Button(panel, wx.ID_OK, _('Save'))
        cancel_button = wx.Button(panel, wx.ID_CANCEL, _('Cancel'))
        buttons.Add(self.test_button, 0, wx.RIGHT, 6)
        buttons.Add(self.clear_button, 0, wx.RIGHT, 6)
        buttons.AddStretchSpacer()
        buttons.Add(save_button, 0, wx.RIGHT, 6)
        buttons.Add(cancel_button, 0)
        sizer.Add(buttons, 0, wx.EXPAND | wx.ALL, 10)

        panel.SetSizer(sizer)
        sizer.SetSizeHints(self)

        self.test_button.Bind(wx.EVT_BUTTON, self._on_test)
        self.clear_button.Bind(wx.EVT_BUTTON, self._on_clear)
        self.Bind(wx.EVT_BUTTON, self._on_save, id=wx.ID_OK)

    def _on_save(self, _event) -> None:
        user = self.user_ctrl.GetValue().strip()
        password = self.pass_ctrl.GetValue()
        if user and password:
            rom_credentials.set(self._source_key, user, password)
        self.EndModal(wx.ID_OK)

    def _on_clear(self, _event) -> None:
        rom_credentials.clear(self._source_key)
        self.user_ctrl.SetValue('')
        self.pass_ctrl.SetValue('')
        self.status.SetLabel(_('Stored credentials cleared.'))

    def _on_test(self, _event) -> None:
        user = self.user_ctrl.GetValue().strip()
        password = self.pass_ctrl.GetValue()
        if not user or not password:
            self.status.SetLabel(_('Enter a username and password first.'))
            return
        self.test_button.Disable()
        self.status.SetLabel(_('Testing...'))

        def worker():
            if self._source_key == online_rom_search.SOURCE_RETROROMS:
                ok, message = online_rom_search.retroroms_check(user, password, self._mame_version, self._logger)
            else:
                ok, message = online_rom_search.archive_check(user, password, self._logger)
            wx.CallAfter(self._show_test_result, ok, message)

        threading.Thread(target=worker, daemon=True).start()

    def _show_test_result(self, ok: bool, message: str) -> None:
        if not self:
            return
        self.test_button.Enable()
        self.status.SetLabel(('✔ ' if ok else '✗ ') + message)


# ----------------------------------------------------------------------------------------------------------------------
class RomSourceDialog(wx.Dialog):
    """Lets the operator choose which online ROM source(s) to search and manage their credentials."""

    def __init__(self, parent: wx.Window, mame_version: str, logger=None):
        super().__init__(parent, title=_('Choose ROM download source'))
        self._mame_version = mame_version
        self._logger = logger
        self.selected_sources: list[str] = []

        self._rows: list[dict] = []  # one dict per source: {'key','checkbox','status','creds_button'}

        panel = wx.Panel(self)
        main = wx.BoxSizer(wx.VERTICAL)

        heading = wx.StaticText(panel, label=_('Select one or more sources to search for this ROM:'))
        main.Add(heading, 0, wx.ALL, 10)

        grid = wx.FlexGridSizer(len(online_rom_search.ROM_SOURCES), 3, 8, 12)
        grid.AddGrowableCol(0, 1)
        for src in online_rom_search.ROM_SOURCES:
            checkbox = wx.CheckBox(panel, label=src['label'])
            status = wx.StaticText(panel, label='')
            creds_button = None
            if src['needs_credentials']:
                creds_button = wx.Button(panel, label=_('Credentials...'))
                creds_button.Bind(wx.EVT_BUTTON, lambda evt, key=src['key']: self._on_credentials(key))
            # Default-select the no-login source and every credentialed source that already has credentials stored
            checkbox.SetValue(not src['needs_credentials'] or rom_credentials.has(src['key']))
            grid.Add(checkbox, 0, wx.ALIGN_CENTER_VERTICAL)
            grid.Add(status, 0, wx.ALIGN_CENTER_VERTICAL)
            grid.Add(creds_button if creds_button else (0, 0), 0, wx.ALIGN_CENTER_VERTICAL)
            self._rows.append({'key': src['key'], 'checkbox': checkbox, 'status': status, 'creds_button': creds_button})
        main.Add(grid, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        self.search_button = wx.Button(panel, wx.ID_OK, _('Search'))
        cancel_button = wx.Button(panel, wx.ID_CANCEL, _('Cancel'))
        buttons.AddStretchSpacer()
        buttons.Add(self.search_button, 0, wx.RIGHT, 6)
        buttons.Add(cancel_button, 0)
        main.Add(buttons, 0, wx.EXPAND | wx.ALL, 10)

        panel.SetSizer(main)
        self.Bind(wx.EVT_BUTTON, self._on_search, id=wx.ID_OK)

        # Populate the credential-status labels BEFORE sizing, otherwise the dialog is sized while they're still
        # empty and ends up too narrow to show the status text and the 'Credentials...' buttons.
        self._refresh_status()
        main.SetSizeHints(self)
        self.Fit()
        self.CentreOnParent()

    # ------------------------------------------------------------------------------------------------------------------
    def _refresh_status(self) -> None:
        """Update each credentialed row to reflect whether credentials are stored, enabling/disabling its checkbox."""
        for row in self._rows:
            key = row['key']
            if not online_rom_search.source_needs_credentials(key):
                row['status'].SetLabel(_('(no login needed)'))
                continue
            if rom_credentials.has(key):
                row['status'].SetLabel(_('credentials stored'))
                row['checkbox'].Enable()
            else:
                row['status'].SetLabel(_('no credentials - add them to use'))
                row['checkbox'].SetValue(False)
                row['checkbox'].Disable()
        self.Layout()

    def _on_credentials(self, source_key: str) -> None:
        had_credentials = rom_credentials.has(source_key)
        dlg = _CredentialsDialog(self, source_key, self._mame_version, self._logger)
        try:
            dlg.ShowModal()
        finally:
            dlg.Destroy()
        self._refresh_status()
        # Credentials just added for this source - select it, as it would have been had they already been stored
        if not had_credentials and rom_credentials.has(source_key):
            for row in self._rows:
                if row['key'] == source_key:
                    row['checkbox'].SetValue(True)

    def _on_search(self, _event) -> None:
        self.selected_sources = [row['key'] for row in self._rows
                                 if row['checkbox'].IsEnabled() and row['checkbox'].GetValue()]
        if not self.selected_sources:
            wx.MessageBox(_('Select at least one source to search.'), _('No Source Selected'),
                          wx.OK | wx.ICON_INFORMATION, self)
            return
        self.EndModal(wx.ID_OK)
