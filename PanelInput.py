#!/usr/bin/env python3

# ----------------------------------------------------------------------------------------------------------------------
# PanelInput.py

import wx
from functions import PreferenceManager, set_up_language, set_colors

_ = set_up_language()  # Set of the application language


class PanelInput(wx.Panel):
    # ----------------------------------------------------------------------
    def __init__(self,
                 parent,
                 application_colors: dict,
                 mode: str,
                 pref_use_mouse: str,
                 pref_use_joystick: str,
                 pref_use_lightgun: str,
                 pref_offscreen_reload: str,
                 path_to_mame_ini_file: str):
        wx.Panel.__init__(self, parent=parent)

        self.mode = mode
        self.pref_use_mouse = pref_use_mouse
        self.pref_use_joystick = pref_use_joystick
        self.pref_use_lightgun = pref_use_lightgun
        self.pref_offscreen_reload = pref_offscreen_reload
        self.path_to_mame_ini_file = path_to_mame_ini_file

        self.startup_complete = False  # Don't allow the control values to be sent until after startup

        # Create the panel controls
        self.cbUseMouse = wx.CheckBox(self, -1, _('Use Mouse'))
        self.cbUseMouse.Bind(wx.EVT_CHECKBOX, self.on_control_changed)
        self.cbUseJoystick = wx.CheckBox(self, -1, _('Use Joystick'))
        self.cbUseJoystick.Bind(wx.EVT_CHECKBOX, self.on_control_changed)
        self.cbUseLightgun = wx.CheckBox(self, -1, _('Use Lightgun (Don\'t use with Use Mouse)'))
        self.cbUseLightgun.Bind(wx.EVT_CHECKBOX, self.on_control_changed)
        self.cbOffscreenReload = wx.CheckBox(self, -1, _('Offscreen Reload'))
        self.cbOffscreenReload.Bind(wx.EVT_CHECKBOX, self.on_control_changed)

        # Add the tool tip information
        self.cbUseMouse.SetToolTip(wx.ToolTip(_('Enables the mouse for ROMs that can use it - typically lightgun '
                                                'ROMs that just use the mouse.')))
        self.cbUseJoystick.SetToolTip(wx.ToolTip(_('Enables the joystick for ROMs that can use it')))
        self.cbUseLightgun.SetToolTip(wx.ToolTip(_('Enables the lightgun controller if present.  Most lightgun ROMs '
                                                   'just use the mouse.  If you have to enable this, disable the '
                                                   'Use Mouse.')))
        self.cbOffscreenReload.SetToolTip(wx.ToolTip(_('Reload when pointer is out of bounds by simulating offscreen')))

        # Create the sizers
        sizer = wx.BoxSizer(wx.VERTICAL)

        # Add the controls to the sizer
        sizer.Add(self.cbUseMouse, 0, wx.ALL, 10)
        sizer.Add(self.cbUseJoystick, 0, wx.ALL, 10)
        sizer.Add(self.cbUseLightgun, 0, wx.ALL, 10)
        sizer.Add(self.cbOffscreenReload, 0, wx.ALL, 10)

        self.SetSizer(sizer)
        sizer.Fit(self)

        # Ensure all controls have the system-wide colors
        set_colors(self, application_colors)

        # Set the controls values from the INI files
        self.cbUseMouse.SetValue(self.pref_use_mouse == 'True')
        self.cbUseJoystick.SetValue(self.pref_use_joystick == 'True')
        self.cbUseLightgun.SetValue(self.pref_use_lightgun == 'True')
        self.cbOffscreenReload.SetValue(self.pref_offscreen_reload == 'True')

        self.startup_complete = True

    # Process the controls change event and write its value out to the INI file
    def on_control_changed(self, _event):
        if self.startup_complete:
            # Create the preferences manager
            pref_manager = PreferenceManager(self, self.mode)

            # Register preferences
            pref_manager.add_boolean_preference('pref_use_mouse', self.cbUseMouse)
            pref_manager.add_boolean_preference('pref_use_joystick', self.cbUseJoystick)
            pref_manager.add_boolean_preference('pref_use_lightgun', self.cbUseLightgun)
            pref_manager.add_boolean_preference('pref_offscreen_reload', self.cbOffscreenReload)

            # Update the preferences using the manager
            pref_manager.update_all()
