#!/usr/bin/env python3

# ----------------------------------------------------------------------------------------------------------------------
# PanelMisc.py

"""
Miscellaneous MAME options not covered by other tabs

"""

import wx
from functions import PreferenceManager, set_up_language, set_colors

_ = set_up_language()  # Set of the application language


class PanelMisc(wx.Panel):
    # ----------------------------------------------------------------------
    def __init__(self,
                 parent,
                 application_colors: dict,
                 mode: str,
                 pref_cheat: str,
                 pref_skip_game_info: str,
                 path_to_mame_ini_file: str):
        wx.Panel.__init__(self, parent=parent)

        self.mode = mode
        self.pref_cheat = pref_cheat
        self.pref_skip_game_info = pref_skip_game_info
        self.path_to_mame_ini_file = path_to_mame_ini_file

        self.startup_complete = False  # Don't allow the control values to be sent until after startup

        # Create the panel controls
        self.cbCheat = wx.CheckBox(self, -1, _('Enable Cheats'))
        self.cbCheat.Bind(wx.EVT_CHECKBOX, self.on_control_changed)
        self.cbSkipGameInfo = wx.CheckBox(self, -1, _('Skip ROM Info on startup'))
        self.cbSkipGameInfo.Bind(wx.EVT_CHECKBOX, self.on_control_changed)

        # Add the tool tip information
        self.cbCheat.SetToolTip(wx.ToolTip(_('This enables ROMs cheats.  '
                                             'The cheat file must exist and MAME must know where it is.')))
        self.cbSkipGameInfo.SetToolTip(wx.ToolTip(_('Skips the ROM information screen when MAME launches.')))

        # Create the sizers
        sizer = wx.BoxSizer(wx.VERTICAL)

        # Add the controls to the sizer
        sizer.Add(self.cbCheat, 0, wx.ALL, 10)
        sizer.Add(self.cbSkipGameInfo, 0, wx.ALL, 10)

        self.SetSizer(sizer)
        sizer.Fit(self)

        # Ensure all controls have the system-wide colors
        set_colors(self, application_colors)

        # Set the controls values from the INI files
        self.cbCheat.SetValue(self.pref_cheat == 'True')
        self.cbSkipGameInfo.SetValue(self.pref_skip_game_info == 'True')

        self.startup_complete = True

    # Process the controls change event and write its value out to the INI file
    def on_control_changed(self, _event):
        if self.startup_complete:
            # Create the preferences manager
            pref_manager = PreferenceManager(self, self.mode)

            # Register preferences
            pref_manager.add_boolean_preference('pref_cheat', self.cbCheat)
            pref_manager.add_boolean_preference('pref_skip_game_info', self.cbSkipGameInfo)

            # Update the preferences using the manager
            pref_manager.update_all()
