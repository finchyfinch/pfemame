#!/usr/bin/env python3

# ----------------------------------------------------------------------------------------------------------------------
# PanelPerformance.py

import wx
from functions import PreferenceManager, set_up_language, set_colors

_ = set_up_language()  # Set of the application language


class PanelPerformance(wx.Panel):
    # ----------------------------------------------------------------------
    def __init__(self,
                 parent,
                 application_colors: dict,
                 mode: str,
                 pref_auto_frame_skip: str,
                 path_to_mame_ini_file: str):
        wx.Panel.__init__(self, parent=parent)

        self.mode = mode
        self.pref_auto_frame_skip = pref_auto_frame_skip
        self.path_to_mame_ini_file = path_to_mame_ini_file

        self.startup_complete = False  # Don't allow the control values to be sent until after startup

        # Create the panel controls
        self.cbAutoFrameSkip = wx.CheckBox(self, -1, _('Auto Frame skip'))
        self.cbAutoFrameSkip.Bind(wx.EVT_CHECKBOX, self.on_control_changed)

        # Add the tool tip information
        self.cbAutoFrameSkip.SetToolTip(wx.ToolTip(_('Automatically skip frames to improve ROM speed.  Can be useful '
                                                     'for slow ROMs.')))

        # Create the sizers
        sizer = wx.BoxSizer(wx.VERTICAL)

        # Add the controls to the sizer
        sizer.Add(self.cbAutoFrameSkip, 0, wx.ALL, 10)

        self.SetSizer(sizer)
        sizer.Fit(self)

        # Ensure all controls have the system-wide colors
        set_colors(self, application_colors)

        # Set the controls values from the INI files
        self.cbAutoFrameSkip.SetValue(self.pref_auto_frame_skip == 'True')

        self.startup_complete = True

    # Process the controls change event and write its value out to the INI file
    def on_control_changed(self, _event):
        if self.startup_complete:
            # Create the preferences manager
            pref_manager = PreferenceManager(self, self.mode)

            # Register preferences
            pref_manager.add_boolean_preference('pref_auto_frame_skip', self.cbAutoFrameSkip)

            # Update the preferences using the manager
            pref_manager.update_all()
