#!/usr/bin/env python3

# ----------------------------------------------------------------------------------------------------------------------
# PanelOSD.py

import wx
from functions import PreferenceManager, set_up_language, set_colors
from custom_drop_down import ModernDropdown, EVT_DROPDOWN_SELECTION

_ = set_up_language()  # Set up the application language


class PanelOSD(wx.Panel):
    # ------------------------------------------------------------------------------------------------------------------
    def __init__(self,
                 parent,
                 application_colors: dict,
                 mode: str,
                 pref_osd_key: str,
                 path_to_mame_ini_file: str):
        wx.Panel.__init__(self, parent=parent)

        self.mode = mode
        self.pref_osd_key = pref_osd_key
        self.path_to_mame_ini_file = path_to_mame_ini_file

        self.startup_complete = False  # Don't allow the control values to be sent until after startup

        # Create the panel controls
        options = ['INSERT', 'SCRLOCK', 'Forward Delete', 'DELETE', 'DEL']
        self.cbOSDKey = ModernDropdown(self, wx.ID_ANY, '', choices=options, size=wx.Size(120, 25))
        self.cbOSDKey.Bind(EVT_DROPDOWN_SELECTION, self.on_control_changed)
        self.cbOSDKeyText = wx.StaticText(self, -1, _('OSD UI Key'), style=wx.ALIGN_LEFT)

        # Add the tool tip information
        self.cbOSDKey.SetToolTip(wx.ToolTip(_('Select the key used to toggle the OSD UI mode for systems')))

        # Create the sizers
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer_osd = wx.BoxSizer(wx.HORIZONTAL)

        # Add the controls to the sizer
        sizer_osd.Add(self.cbOSDKey, 0, wx.ALL | wx.ALIGN_LEFT, 2)
        sizer_osd.Add(self.cbOSDKeyText, 0, wx.ALL | wx.ALIGN_LEFT | wx.ALIGN_CENTRE_VERTICAL, 2)
        sizer.Add(sizer_osd, 0, wx.ALL, 10)

        self.SetSizer(sizer)
        sizer.Fit(self)

        # Ensure all controls have the system-wide colors
        set_colors(self, application_colors)

        # Set the controls values from the INI files
        self.cbOSDKey.SetValue(self.pref_osd_key)

        self.startup_complete = True

    # Process the controls change event and write its value out to the INI file
    def on_control_changed(self, _event):
        if self.startup_complete:
            # Create the preferences manager
            pref_manager = PreferenceManager(self, self.mode)

            # Register preferences
            pref_manager.add_string_preference('pref_osd_key', self.cbOSDKey)

            # Update the preferences using the manager
            pref_manager.update_all()
