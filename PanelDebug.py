#!/usr/bin/env python3

# ----------------------------------------------------------------------------------------------------------------------
# PanelDebug.py

import wx
from functions import PreferenceManager, set_up_language, set_colors

_ = set_up_language()  # Set of the application language


class PanelDebug(wx.Panel):
    # ------------------------------------------------------------------------------------------------------------------
    def __init__(self, parent,
                 application_colors: dict,
                 mode: str,
                 pref_logfile: str,
                 pref_verbose: str,
                 path_to_mame_ini_file: str):
        wx.Panel.__init__(self, parent=parent)

        self.mode = mode
        self.pref_logfile = pref_logfile
        self.pref_verbose = pref_verbose
        self.path_to_mame_ini_file = path_to_mame_ini_file

        self.startup_complete = False  # Don't allow the control values to be sent until after startup

        # Create the panel controls
        self.cbLogfile = wx.CheckBox(self, -1, _('Write MAME log messages to file'))
        self.cbLogfile.Bind(wx.EVT_CHECKBOX, self.on_control_changed)
        self.cbVerbose = wx.CheckBox(self, -1, _('Display debug messages'))
        self.cbVerbose.Bind(wx.EVT_CHECKBOX, self.on_control_changed)

        # Add the tool tip information
        self.cbLogfile.SetToolTip(wx.ToolTip(_('Write MAME messages to the log file')))
        self.cbVerbose.SetToolTip(wx.ToolTip(_('Displays MAME diagnostics messages.  Can be useful for debugging.')))

        # Create the sizers
        sizer = wx.BoxSizer(wx.VERTICAL)

        # Add the controls to the sizer
        sizer.Add(self.cbLogfile, 0, wx.ALL, 10)
        sizer.Add(self.cbVerbose, 0, wx.ALL, 10)

        self.SetSizer(sizer)
        sizer.Fit(self)

        # Ensure all controls have the system-wide colors
        set_colors(self, application_colors)

        # Set the controls values from the INI files
        self.cbLogfile.SetValue(self.pref_logfile == 'True')
        self.cbVerbose.SetValue(self.pref_verbose == 'True')

        self.startup_complete = True

    # Process the controls change event and write its value out to the INI file
    def on_control_changed(self, _event):
        if self.startup_complete:
            # Create the preferences manager
            pref_manager = PreferenceManager(self, self.mode)

            # Register preferences
            pref_manager.add_boolean_preference('pref_logfile', self.cbLogfile)
            pref_manager.add_boolean_preference('pref_verbose', self.cbVerbose)

            # Update the preferences using the manager
            pref_manager.update_all()
