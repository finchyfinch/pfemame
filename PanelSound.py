#!/usr/bin/env python3

# ----------------------------------------------------------------------------------------------------------------------
# PanelSound.py

import wx
from functions import PreferenceManager, set_up_language, set_colors, get_application_colors, set_tab_order
from custom_drop_down import ModernDropdown, EVT_DROPDOWN_SELECTION

_ = set_up_language()  # Set up the application language


class PanelSound(wx.Panel):
    # ----------------------------------------------------------------------
    def __init__(self,
                 parent,
                 application_colors: dict,
                 mode: str,
                 system: str,
                 pref_sound_samplerate: str,
                 pref_sound_samples: str,
                 pref_sound_volume: str,
                 pref_sound_subsystem: str,
                 pref_sound_latency: str,
                 path_to_mame_ini_file: str):
        wx.Panel.__init__(self, parent=parent)

        self.mode = mode
        self.system = system
        self.pref_sound_samplerate = pref_sound_samplerate
        self.pref_sound_samples = pref_sound_samples
        self.pref_sound_volume = pref_sound_volume
        self.pref_sound_subsystem = pref_sound_subsystem
        self.pref_sound_latency = pref_sound_latency
        self.path_to_mame_ini_file = path_to_mame_ini_file

        self.startup_complete = False  # Don't allow the control values to be sent until after startup

        # Create the panel controls
        if system == 'windows':
            spin_ctrl_size = wx.Size(120, -1)
        else:
            spin_ctrl_size = wx.Size(-1, -1)

        views = ['11025', '22050', '44100', '48000']
        self.cbSamplerate = ModernDropdown(self, value = '', choices=views, size=wx.Size(120, 25))
        self.cbSamplerate.Bind(EVT_DROPDOWN_SELECTION, self.on_control_changed)
        self.cbSamplerateText = wx.StaticText(self, -1, _('Sample Rate'), style=wx.ALIGN_LEFT)

        self.cbVolume = wx.SpinCtrl(self, -1, min=-30, max=0, size=spin_ctrl_size)
        self.cbVolume.Bind(wx.EVT_SPINCTRL, self.on_control_changed)
        self.cbVolumeText = wx.StaticText(self, -1, _('Volume'), style=wx.ALIGN_LEFT)

        views = ['auto', 'dsound', 'xaudio2', 'portaudio', 'sdl', 'none'] if \
            self.system == 'windows' else ['auto', 'portaudio', 'coreaudio', 'sdl', 'none']
        self.cbSubsystem = ModernDropdown(self, wx.ID_ANY, '', choices=views, size=wx.Size(120, 25))
        self.cbSubsystem.Bind(EVT_DROPDOWN_SELECTION, self.on_control_changed)
        self.cbSubsystemText = wx.StaticText(self, -1, _('Sound SubSystem'), style=wx.ALIGN_LEFT)

        self.cbLatency = wx.SpinCtrl(self, -1, min=1, max=5, size=spin_ctrl_size)
        self.cbLatency.Bind(wx.EVT_SPINCTRL, self.on_control_changed)
        self.cbLatencyText = wx.StaticText(self, -1, _('Audio Latency'), style=wx.ALIGN_LEFT)

        self.cbSamples = wx.CheckBox(self, -1, _('Use Sample Files'))
        self.cbSamples.Bind(wx.EVT_CHECKBOX, self.on_control_changed)

        # Add the tool tip information
        self.cbSamplerate.SetToolTip(wx.ToolTip(_('Sets the audio sample rate. Smaller values (e.g. 11025) cause lower'
                                                ' audio quality but faster emulation speed.')))
        self.cbVolume.SetToolTip(wx.ToolTip(_('Sets the startup volume. It can later be changed with the user'
                                            ' interface (see Keys section). The volume is an attenuation'
                                            ' in dB: e.g., "-12" will start with -12dB attenuation.  Allowable values '
                                            'are from 0 to -30.')))
        self.cbSubsystem.SetToolTip(wx.ToolTip(_('Specifies which sound subsystem to use. Selecting none disables sound'
                                               ' output altogether (sound hardware is still emulated).  On Windows and'
                                               ' Linux, portaudio is likely to give the lowest possible latency, while'
                                               ' Mac users will find coreaudio provides the best results.')))
        self.cbLatency.SetToolTip(wx.ToolTip(_('The exact behavior depends on the selected audio output module. '
                                             'Smaller values provide less audio delay while requiring better system'
                                             ' performance. Higher values increase audio delay but may help avoid'
                                             ' buffer under-runs and audio interruptions.  Allowable values are 1 to '
                                             '5.')))
        self.cbSamples.SetToolTip(wx.ToolTip(_('Use samples if available.')))

        # Create the sizers
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer_samplerate = wx.BoxSizer(wx.HORIZONTAL)
        sizer_volume = wx.BoxSizer(wx.HORIZONTAL)
        sizer_subsystem = wx.BoxSizer(wx.HORIZONTAL)
        sizer_latency = wx.BoxSizer(wx.HORIZONTAL)

        # Add the controls to the sizer
        sizer_samplerate.Add(self.cbSamplerate, 0, wx.ALL | wx.ALIGN_LEFT, 2)
        sizer_samplerate.Add(self.cbSamplerateText, 0, wx.ALL | wx.ALIGN_LEFT | wx.ALIGN_CENTRE_VERTICAL, 2)
        sizer_volume.Add(self.cbVolume, 0, wx.ALL | wx.ALIGN_LEFT, 2)
        sizer_volume.Add(self.cbVolumeText, 0, wx.ALL | wx.ALIGN_LEFT | wx.ALIGN_CENTRE_VERTICAL, 2)
        sizer_subsystem.Add(self.cbSubsystem, 0, wx.ALL | wx.ALIGN_LEFT, 2)
        sizer_subsystem.Add(self.cbSubsystemText, 0, wx.ALL | wx.ALIGN_LEFT | wx.ALIGN_CENTRE_VERTICAL, 2)
        sizer_latency.Add(self.cbLatency, 0, wx.ALL | wx.ALIGN_LEFT, 2)
        sizer_latency.Add(self.cbLatencyText, 0, wx.ALL | wx.ALIGN_LEFT | wx.ALIGN_CENTRE_VERTICAL, 2)
        sizer.Add(self.cbSamples, 0, wx.ALL, 10)
        sizer.Add(sizer_volume, 0, wx.ALL, 10)
        sizer.Add(sizer_latency, 0, wx.ALL, 10)
        sizer.Add(sizer_samplerate, 0, wx.ALL, 10)
        sizer.Add(sizer_subsystem, 0, wx.ALL, 10)
        sizer.AddSpacer(20)  # This ensures all controls are visible across different platforms

        self.SetSizer(sizer)
        sizer.Fit(self)

        # TAB goes top to bottom, as laid out above (not in the order the controls were created)
        set_tab_order([self.cbSamples, self.cbVolume, self.cbLatency, self.cbSamplerate, self.cbSubsystem])

        # Ensure all controls have the system-wide colors
        set_colors(self, application_colors)

        # Set the controls values from the INI files
        self.cbSamples.SetValue(self.pref_sound_samples == 'True')
        self.cbSamplerate.SetValue(self.pref_sound_samplerate)
        self.cbVolume.SetValue(self.pref_sound_volume)
        self.cbSubsystem.SetValue(self.pref_sound_subsystem)
        self.cbLatency.SetValue(self.pref_sound_latency)

        self.startup_complete = True

    # ------------------------------------------------------------------------------------------------------------------
    # Process the controls change event and write its value out to the INI file
    def on_control_changed(self, _event):
        if self.startup_complete:
            # Create the preferences manager
            pref_manager = PreferenceManager(self, self.mode)

            # Register preferences
            pref_manager.add_boolean_preference('pref_sound_samples', self.cbSamples)
            pref_manager.add_string_preference('pref_sound_samplerate', self.cbSamplerate)
            pref_manager.add_string_preference('pref_sound_volume', self.cbVolume)
            pref_manager.add_string_preference('pref_sound_subsystem', self.cbSubsystem)
            pref_manager.add_string_preference('pref_sound_latency', self.cbLatency)

            # Update the preferences using the manager
            pref_manager.update_all()


# ------------------------------------------------------------------------------------------------------------------
# This class allows us to run the PanelSound module locally for testing purposes
class PanelSoundLocal(wx.Frame):
    def __init__(self,
                 application_colors,
                 mode,
                 system,
                 pref_sound_samplerate,
                 pref_sound_samples,
                 pref_sound_volume,
                 pref_sound_subsystem,
                 pref_sound_latency,
                 path_to_mame_ini_file):
        style = (wx.SYSTEM_MENU | wx.CAPTION | wx.CLOSE_BOX)
        wx.Frame.__init__(self, wx.GetApp().TopWindow, -1, 'PanelSound', wx.DefaultPosition, style=style)

        self.SetSize(900, 400)

        self.Bind(wx.EVT_CLOSE, self.on_close)

        self.panel = PanelSound(self,
                                application_colors,
                                mode,
                                system,
                                pref_sound_samplerate,
                                pref_sound_samples,
                                pref_sound_volume,
                                pref_sound_subsystem,
                                pref_sound_latency,
                                path_to_mame_ini_file
                                )

        self.Show()
        self.Layout()

    def on_close(self, _event):
        self.Destroy()


if __name__ == '__main__':
    app = wx.App()

    import iniFile

    path_to_mame_ini_file = iniFile.read_ini_file('path', 'mame_ini')
    application_colors = get_application_colors()
    mode = 'game'
    system = 'windows'
    pref_sound_samplerate = '48000'
    pref_sound_samples = True
    pref_sound_volume = '0'
    pref_sound_subsystem = 'Auto'
    pref_sound_latency = '0'

    PanelSoundLocal(application_colors,
                    mode,
                    system,
                    pref_sound_samplerate,
                    pref_sound_samples,
                    pref_sound_volume,
                    pref_sound_subsystem,
                    pref_sound_latency,
                    path_to_mame_ini_file)

    app.MainLoop()
