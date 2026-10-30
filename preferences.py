#!/usr/bin/env python3

# ----------------------------------------------------------------------------------------------------------------------
# preferences.py

"""
Main preferences window for the pfeMAME application and the MAME exe options.
This can be called to display all preferences, or just game specific preferences.  In the all preferences mode it will
update the pfemame.ini file and mame.ini file.  When used in game specific preferences mode it will create separate
ini files for each game (or systems) and store them in the INI folder for MAME.  This folder obviously needs to be
defined otherwise it won't work.

The preference tables and the ROM INI file format are in preferences_model.py.
"""
# Import python & wxPython modules
import wx
import os
import shutil
from pubsub import pub
import wx.lib.agw.flatnotebook as flatnotebook

# Import my own modules
import iniFile
import functions
import preferences_model
from preferences_model import MAME_OPTIONS, PFEMAME_OPTIONS, COLOR_OPTIONS
import PanelPfeMame
import PanelSound
import PanelVideo
import PanelInput
import PanelPerformance
import PanelOSD
import PanelDebug
import PanelMisc
import PanelSlots

_ = functions.set_up_language()  # Set of the application language

# The panels send a save request on every change (each keystroke in a number box), so wait for the changes to stop
SAVE_DELAY_MS = 300


# ----------------------------------------------------------------------------------------------------------------------
def mame_executable_found(path_executable: str) -> bool:
    """True if the MAME executable exists - either a file path, or a program name found on the PATH (e.g. 'mame')."""
    return bool(path_executable) and (os.path.isfile(path_executable) or shutil.which(path_executable) is not None)


# ----------------------------------------------------------------------------------------------------------------------
# The following is the Default game preferences window management
class Preferences(wx.Panel):
    def __init__(self, parent, title: str, mode: str, rom_file_name: str, folder_ini: str, path_executable: str,
                 system_file_name: str, is_a_system: bool = False):

        wx.Panel.__init__(self, parent=parent)

        # --------------------------------------------------------------------------------------------------------------
        # Create pubsub receivers
        # These allow messages to be sent back to the main class from the notebook classes.
        # The mode is appended to the front of the pub message name so that we can differentiate between listeners
        # for default preferences and ROM specific preferences as both windows can be open at the same time in
        # different tabs.  The topics without a mode come from the pfeMAME Preferences panel, which only the default
        # preferences tab has.
        self._subscriptions = [(self.set_variable, mode + '_set_variable'),
                               (self.force_layout, mode + '_force_layout'),
                               (self.update_ini_files, mode + '_update_ini')]
        if mode == 'default':
            self._subscriptions += [(self.restart_required, 'restart_required'),
                                    (self.update_log_file, 'update_logfile')]
        for listener, topic in self._subscriptions:
            pub.subscribe(listener, topic)
        self.Bind(wx.EVT_WINDOW_DESTROY, self._on_destroy)

        self.block_changes = True  # Start with all pubsub writes disabled until after the page is loaded
        self._save_timer = None
        self._mame_ini_error_shown = False
        self._pfemame_ini_error_shown = False

        # --------------------------------------------------------------------------------------------------------------
        # Get the application colors
        self.application_colors = functions.get_application_colors()

        # --------------------------------------------------------------------------------------------------------------
        # Get font information from the INI file
        fonts = functions.get_font_info()
        self.global_font_bold = fonts.global_font_bold
        self.global_font_normal = fonts.global_font_normal

        # --------------------------------------------------------------------------------------------------------------
        self.SetBackgroundColour(self.application_colors['text_background'])

        # --------------------------------------------------------------------------------------------------------------
        # Set some startup default values
        self.mode = mode
        self.rom_file_name = rom_file_name
        self.folder_ini = folder_ini
        self.path_executable = path_executable
        self.system_file_name = system_file_name
        self.is_a_system = is_a_system
        self.slot_rows = None                   # Sent by PanelSlots: [(slot name, option name, parent)]
        self.manual_config_control_value = None  # Sent by PanelSlots.  None = not changed, keep what the file has

        # --------------------------------------------------------------------------------------------------------------
        # Try to work out the platform
        # This is needed for platform specific preferences
        self.system = functions.get_platform()

        # --------------------------------------------------------------------------------------------------------------
        # Get variables from the pfemame.ini file.  Each preference is an attribute named in the preferences_model
        # tables - the notebook panels set them by name through pubsub (see set_variable).
        for option in PFEMAME_OPTIONS:
            setattr(self, option.attr, iniFile.read_ini_file('preferences', option.ini_key, default=option.default))
        for attr, color_name in COLOR_OPTIONS:
            setattr(self, attr, str(self.application_colors[color_name]))
        self.path_to_mame_ini_file = iniFile.read_ini_file('path', 'mame_ini')

        # Get variables from the mame.ini file
        values = {option.attr: preferences_model.mame_ini_value(
                      iniFile.get_from_mameini(option.ini_key, self.path_to_mame_ini_file), option.is_bool)
                  for option in MAME_OPTIONS}
        # What a ROM gets if its INI file doesn't set an option (ROM INI files only store the differences)
        self.global_mame_values = preferences_model.apply_mame_defaults(values, self.system)

        # --------------------------------------------------------------------------------------------------------------
        # If we are in the ROM specific preferences mode, then override default preferences
        # with ROM specific ones if they exist.
        self.content = []
        # The INI file name will be different if it is a system so that we can identify it as a system program INI file
        file_path = self.construct_filepath()  # Get the file path

        if mode == 'game' and file_path and os.path.isfile(file_path):
            # Now read out all preferences settings in the ROMs INI file
            try:
                self.content = preferences_model.read_lines(file_path)
            except OSError:
                # The following will only be called if this window is running as a child
                if self.GetParent() is not None:
                    self.update_log_file(_('Error reading from ROM INI file'))
            for option in MAME_OPTIONS:
                values[option.attr] = functions.find_mame_ini_line(self.content, option.ini_key,
                                                                   values[option.attr], option.is_bool)

        # Check if some mame.ini values are valid. If not, then set them to valid default values.
        for attr, value in preferences_model.apply_mame_defaults(values, self.system).items():
            setattr(self, attr, value)

        # The values as they are saved - only preferences that change are written (see save_default_preferences)
        self._saved_values = self._preference_values()

        # --------------------------------------------------------------------------------------------------------------
        # Check that we have valid paths
        if mode == 'game':
            message = ''
            if not mame_executable_found(self.path_executable):
                message = _('Unable to find the MAME executable path.  Check the file path settings.')
            elif not file_path:  # None of the INI folders exist (they are required to store the ROM settings)
                message = _('You need to set a valid INI path.  This is where ROM specific INI files'
                            ' are stored and used by the MAME executable.')
            if message:
                self._show_unavailable(title, message)
                return

        # --------------------------------------------------------------------------------------------------------------
        # Create the sizers
        self.sizer_main_vertical = wx.BoxSizer(wx.VERTICAL)
        self.sizer_main_horizontal = wx.BoxSizer(wx.HORIZONTAL)

        # --------------------------------------------------------------------------------------------------------------
        # Create the notebook control and add the panels
        notebook = flatnotebook.FlatNotebook(self,
                                             agwStyle=flatnotebook.FNB_NO_NAV_BUTTONS |
                                                      flatnotebook.FNB_NO_X_BUTTON |
                                                      flatnotebook.FNB_TABS_BORDER_SIMPLE |
                                                      flatnotebook.FNB_NODRAG)
        notebook.SetActiveTabColour(self.application_colors['window_background'])
        notebook.SetTabAreaColour(self.application_colors['control_bar'])
        notebook.SetNonActiveTabTextColour(self.application_colors['text'])
        notebook.SetForegroundColour(self.application_colors['text'])
        notebook.SetActiveTabTextColour(self.application_colors['text'])

        if mode != 'game':
            pfemame_values = {option.attr: getattr(self, option.attr) for option in PFEMAME_OPTIONS}
            notebook.AddPage(PanelPfeMame.PanelPfeMame(notebook,
                                                       self.application_colors,
                                                       self.global_font_normal,
                                                       pfemame_values), "pfeMAME Preferences")
        if mode == 'game' and file_path and is_a_system:
            notebook.AddPage(PanelSlots.PanelSlots(notebook,
                                                   mode,
                                                   self.content,
                                                   self.rom_file_name,
                                                   self.path_executable), "Slots & Bios")
        notebook.AddPage(PanelSound.PanelSound(notebook,
                                               self.application_colors,
                                               mode,
                                               self.system,
                                               self.pref_sound_samplerate,
                                               self.pref_sound_samples,
                                               self.pref_sound_volume,
                                               self.pref_sound_subsystem,
                                               self.pref_sound_latency,
                                               self.path_to_mame_ini_file), "Sound")
        notebook.AddPage(PanelVideo.PanelVideo(notebook,
                                               self.application_colors,
                                               mode,
                                               self.system,
                                               self.pref_window,
                                               self.pref_video,
                                               self.pref_bgfx_backend,
                                               self.pref_bgfx_screenchains,
                                               self.pref_bgfx_shadowmask,
                                               self.pref_artwork_crop,
                                               self.path_to_mame_ini_file), "Video")
        notebook.AddPage(PanelInput.PanelInput(notebook,
                                               self.application_colors,
                                               mode,
                                               self.pref_use_mouse,
                                               self.pref_use_joystick,
                                               self.pref_use_lightgun,
                                               self.pref_offscreen_reload,
                                               self.path_to_mame_ini_file), "Inputs")
        notebook.AddPage(PanelPerformance.PanelPerformance(notebook,
                                                           self.application_colors,
                                                           mode,
                                                           self.pref_auto_frame_skip,
                                                           self.path_to_mame_ini_file), "Performance")
        notebook.AddPage(PanelOSD.PanelOSD(notebook,
                                           self.application_colors,
                                           mode,
                                           self.pref_osd_key,
                                           self.path_to_mame_ini_file), "OSD")
        notebook.AddPage(PanelDebug.PanelDebug(notebook,
                                               self.application_colors,
                                               mode,
                                               self.pref_logfile,
                                               self.pref_verbose,
                                               self.path_to_mame_ini_file), "Debug")
        notebook.AddPage(PanelMisc.PanelMisc(notebook,
                                             self.application_colors,
                                             mode,
                                             self.pref_cheat,
                                             self.pref_skip_game_info,
                                             self.path_to_mame_ini_file), "Misc")
        text = wx.StaticText(self, -1, title)
        text.SetFont(self.global_font_bold)
        text.SetForegroundColour(self.application_colors['text'])
        text.SetBackgroundColour(self.application_colors['text_background'])

        self.sizer_main_vertical.Add(text, 0, wx.ALIGN_CENTRE)
        self.sizer_main_vertical.Add(notebook, 1, wx.EXPAND)
        self.sizer_main_horizontal.Add(self.sizer_main_vertical, 1, wx.EXPAND)

        # --------------------------------------------------------------------------------------------------------------
        # Get the window to size automatically based upon sizer requirements and show the sizer
        self.SetSizer(self.sizer_main_horizontal)
        self.sizer_main_horizontal.Fit(self)

        # Only allow the control changes to be written after the page has fully loaded
        wx.CallAfter(self.reset_block)

    def reset_block(self):
        self.block_changes = False

    # ------------------------------------------------------------------------------------------------------------------
    def _show_unavailable(self, title: str, message: str) -> None:
        """Show why the ROM preferences can't be used, in place of the preference tabs."""
        self._unsubscribe()
        sizer = wx.BoxSizer(wx.VERTICAL)
        for label, font in ((title, self.global_font_bold), (message, self.global_font_normal)):
            text = wx.StaticText(self, -1, label)
            text.SetFont(font)
            text.SetForegroundColour(self.application_colors['text'])
            sizer.Add(text, 0, wx.ALL | wx.ALIGN_CENTRE, 10)
        self.SetSizer(sizer)

    # ------------------------------------------------------------------------------------------------------------------
    def _preference_values(self) -> dict[str, str]:
        """{attribute: value} of every preference that is saved."""
        attrs = ([option.attr for option in MAME_OPTIONS] + [option.attr for option in PFEMAME_OPTIONS] +
                 [attr for attr, _color_name in COLOR_OPTIONS])
        return {attr: getattr(self, attr) for attr in attrs}

    # ------------------------------------------------------------------------------------------------------------------
    def validation_problem(self) -> tuple[str, str] | None:
        """(message, title) for the first preference that doesn't have a valid number, or None if they are all fine."""
        prompt_text = _('Please set a valid value for the ')
        numeric_entries_to_check = []
        if self.mode == 'default':  # pfeMAME's own preferences are only saved by the default preferences
            numeric_entries_to_check += [
                (self.pref_days_check_cache, 1, 365,
                 prompt_text + _('cache check days (1 to 365)'),
                 _('Cache Check Days Error')),
                (self.pref_screensaver_time, 0, 60,
                 prompt_text + _('screensaver time in minutes (0 to 60)'),
                 _('Screensaver Time Value Error')),
            ]
        numeric_entries_to_check += [
            (self.pref_sound_volume, -30, 0,
             prompt_text + _('volume attenuation (-30 to 0)'),
             _('Volume Attenuation Value Error')),
            (self.pref_sound_latency, 1, 5,
             prompt_text + _('volume latency (1 to 5)'),
             _('Volume Latency Value Error')),
        ]
        for value, low, high, message, title in numeric_entries_to_check:
            if not preferences_model.int_in_range(value, low, high):
                return message, title
        return None

    # ------------------------------------------------------------------------------------------------------------------
    # This will process all preference settings and then the slot configuration settings for systems.
    # interactive=False when saving as the window closes: problems are logged instead of shown in a message box.
    def process_preferences(self, interactive: bool = True) -> None:
        if self.block_changes:
            return

        problem = self.validation_problem()
        if problem:
            if interactive:
                wx.MessageBox(problem[0], problem[1], wx.OK | wx.ICON_INFORMATION)
            else:
                self.update_log_file(problem[0])
            return

        if self.mode == 'default':
            self.save_default_preferences(interactive)
        else:
            self.save_rom_preferences(interactive)

    # ------------------------------------------------------------------------------------------------------------------
    def save_default_preferences(self, interactive: bool) -> None:
        """
        Save the preferences that have changed to pfemame.ini and mame.ini.  Only changed ones are written: other parts
        of pfeMAME save some of the same settings (e.g. "don't show this again"), and writing back the values this
        window loaded at startup would undo them.
        """
        current = self._preference_values()
        changed = {attr for attr, value in current.items() if value != self._saved_values.get(attr)}
        if not changed:
            return

        pfemame_updates = [('preferences', option.ini_key, current[option.attr])
                           for option in PFEMAME_OPTIONS if option.attr in changed]
        pfemame_updates += [('preferences', attr, current[attr]) for attr, _color_name in COLOR_OPTIONS
                            if attr in changed]
        mame_updates = [(current[option.attr], option.ini_key, option.is_bool)
                        for option in MAME_OPTIONS if option.attr in changed]

        mame_attrs = {option.attr for option in MAME_OPTIONS}
        pfemame_ini_saved = True
        if pfemame_updates:
            # set_ini_file_variables logs and returns False rather than raising if the write fails
            pfemame_ini_saved = iniFile.set_ini_file_variables(pfemame_updates)
            if pfemame_ini_saved:
                for attr in changed - mame_attrs:
                    self._saved_values[attr] = current[attr]
            elif interactive and not self._pfemame_ini_error_shown:
                # Shown once - the log file reports any later failures
                self._pfemame_ini_error_shown = True
                wx.MessageBox(_('Unable to write to the pfemame.ini file. The file is most likely read-only.'),
                              _('ERROR writing to pfemame.ini file'),
                              wx.OK | wx.ICON_ERROR
                              )

        # Update the mame.ini file (set_to_mameini_bulk returns -1 rather than raising if the write fails)
        mame_ini_saved = True
        if mame_updates:
            mame_ini_saved = iniFile.set_to_mameini_bulk(mame_updates, self.path_to_mame_ini_file) != -1
            if mame_ini_saved:
                for attr in changed & mame_attrs:
                    self._saved_values[attr] = current[attr]
            elif interactive and not self._mame_ini_error_shown and pfemame_ini_saved:   # (It says they were saved)
                # Shown once - the status bar and log file report any later failures
                self._mame_ini_error_shown = True
                wx.MessageBox(_('Unable to write to the mame.ini file.  Check that the MAME INI File path is '
                                'set in File Paths and that the file is not read-only.  The pfeMAME '
                                'settings have been saved.'),
                              _('Error in writing INI file'),
                              wx.OK | wx.ICON_ERROR
                              )

        if self.GetParent() is not None:  # Following will only be called if this window is running as a child
            if not pfemame_ini_saved:
                self.update_status_bar(_('ERROR writing to pfemame.ini file'))
                self.update_log_file(_('ERROR writing to pfemame.ini file'))
                if not mame_ini_saved:
                    self.update_log_file(_('ERROR: Unable to write to the mame.ini file'))
            elif mame_ini_saved:
                self.update_status_bar(_('INI file settings updated'))
                self.update_log_file(_('pfeMAME and MAME INI file settings updated'))
            else:
                self.update_status_bar(_('ERROR: Unable to write to the mame.ini file'))
                self.update_log_file(_('ERROR: pfeMAME settings updated but unable to write to the '
                                       'mame.ini file'))
            wx.CallAfter(pub.sendMessage, 'setup_ini')  # Force the main app to reload its variables from the INI file

    # ------------------------------------------------------------------------------------------------------------------
    def save_rom_preferences(self, interactive: bool) -> None:
        """Write the ROM specific INI file (see preferences_model.build_rom_ini for what goes in it)."""
        # Check that the ini folder exists before we try to write to it
        file_path = self.construct_filepath()  # Get the file path
        if not file_path:
            if interactive:
                wx.MessageBox(
                    _('The INI folder has not been set.  Check folder settings.'),
                    _('Error in writing INI file'),
                    wx.OK | wx.ICON_ERROR
                )
            # Following will only be called if this window is running as a child
            if self.GetParent() is not None:
                self.update_log_file(_('ERROR: Path to INI folder not set'))
            return

        lines = preferences_model.build_rom_ini(
            self.content,
            f'{self.rom_file_name} {self.system_file_name}',
            {option.attr: getattr(self, option.attr) for option in MAME_OPTIONS},
            self.global_mame_values,
            is_a_system=self.is_a_system,
            slot_rows=self.slot_rows,
            manual_text=self.manual_config_control_value)

        # Now write out all preferences settings in the ROMs INI file
        try:
            iniFile.atomic_write_text(file_path, '\n'.join(lines))
        except OSError:
            if interactive:
                wx.MessageBox(_('Unable to write to the ROM specific INI file.  Check that the INI '
                                'folder is defined and that you have permission to write to it.'),
                              _('Error in writing INI file'),
                              wx.OK | wx.ICON_ERROR
                              )

            # Following will only be called if this window is running as a child
            if self.GetParent() is not None:
                self.update_log_file(_('ERROR: Unable to write to ROM INI file.  '
                                       'Check the folder permissions and file / folder path settings.'))
            return

        self.content = [line + '\n' for line in lines]  # What the file now holds (the next save keeps from this)

        # Following will only be called if this window is running as a child
        if self.GetParent() is not None:
            msg = _('ROM INI file settings updated')
            self.update_status_bar(msg)
            self.update_log_file(msg)  # Write to the log file

    # ------------------------------------------------------------------------------------------------------------------
    def construct_filepath(self) -> str:
        """
        Return the path of the ROM's INI file (named differently for a system program).  folder_ini is the mame.ini
        inipath setting, which can list several folders: an existing file is used where MAME will find it, a new one
        goes in the usual INI folder (see functions.find_rom_ini).  '' if none of the INI folders exist.
        :return: file path
        """
        suffix = f"_system_{self.system_file_name}" if self.system_file_name else ""
        return functions.find_rom_ini(f"{self.rom_file_name}{suffix}.ini", self.folder_ini, self.path_executable,
                                      self.path_to_mame_ini_file)

    # ------------------------------------------------------------------------------------------------------------------
    def _unsubscribe(self) -> None:
        for listener, topic in self._subscriptions:
            pub.unsubscribe(listener, topic)
        self._subscriptions = []

    def _on_destroy(self, event):
        # Destroy events from child windows arrive here too - only act when this panel is being destroyed
        if event.GetEventObject() is self:
            if self._save_timer is not None and self._save_timer.IsRunning():
                self._save_timer.Stop()
                self.process_preferences(interactive=False)  # Save the last change before the window goes
            self._unsubscribe()
        event.Skip()

    # ------------------------------------------------------------------------------------------------------------------
    # This sets the restart required flag.  It is used by the notebook panel classes and called through pubsub.
    def restart_required(self):
        wx.CallAfter(pub.sendMessage, 'force_restart')

    # ------------------------------------------------------------------------------------------------------------------
    # Force a layout of the window.  It is used by the notebook panel classes and called through pubsub.
    def force_layout(self, msg: str):
        self.sizer_main_vertical.Fit(self)
        self.Layout()

    # ------------------------------------------------------------------------------------------------------------------
    # This is a pubsub function to allow a preference to be set based on its name and a value
    def set_variable(self, msg: list):
        name, value = msg
        if name not in preferences_model.SETTABLE:
            # A panel is sending a name the window doesn't save - it would be silently lost
            self.update_log_file(f'Preferences: unknown setting {name!r} ignored')
            return
        setattr(self, name, value)

    # ------------------------------------------------------------------------------------------------------------------
    # This is a pubsub function to update the INI file(s).  The save waits until the changes stop for a moment.
    def update_ini_files(self):
        if self._save_timer is None:
            self._save_timer = wx.CallLater(SAVE_DELAY_MS, self.process_preferences)
        else:
            self._save_timer.Start(SAVE_DELAY_MS)

    # ------------------------------------------------------------------------------------------------------------------
    def update_log_file(self, msg: str) -> None:
        """
        Write a message to the parent log file
        :param msg: message to write
        :return: None
        """
        wx.CallAfter(pub.sendMessage, 'log', msg=msg)  # Write to the log file

    # ------------------------------------------------------------------------------------------------------------------
    def update_status_bar(self, msg: str) -> None:
        """
        Update the parent status bar
        :param msg: message to write
        :return: None
        """
        wx.CallAfter(pub.sendMessage, 'status', msg=msg)  # Update the statusbar

    # ------------------------------------------------------------------------------------------------------------------
    def update_messages_window(self, msg: str) -> None:
        """
        Update the parent messages window
        :param msg: message to write
        :return: None
        """
        wx.CallAfter(pub.sendMessage, 'update', msg=msg + '\n')  # Update the messages window


# ------------------------------------------------------------------------------------------------------------------
# This class allows us to run the Preferences module locally for testing purposes
class PreferencesLocal(wx.Frame):
    __slots__ = ('title', 'mode', 'rom_file_name', 'folder_ini', 'path_executable', 'system_file_name', 'is_a_system')

    def __init__(self,
                 title: str,
                 mode: str,
                 rom_file_name: str,
                 folder_ini: str,
                 path_executable: str,
                 system_file_name: str,
                 is_a_system: bool = False):
        style = (wx.SYSTEM_MENU | wx.CAPTION | wx.CLOSE_BOX)
        wx.Frame.__init__(self, wx.GetApp().TopWindow, -1, title, wx.DefaultPosition, style=style)

        self.SetSize(900, 600)

        self.Bind(wx.EVT_CLOSE, self.on_close)

        self.panel = Preferences(self, title, mode, rom_file_name, folder_ini, path_executable,
                                 system_file_name, is_a_system)

        self.Show()

    def on_close(self, _event):
        self.Destroy()


if __name__ == '__main__':
    app = wx.App()

    rom_name_local = 'Spectrum'
    rom_file_name_local = 'spectrum'
    # rom_file_name_local = 'ibm5162'
    # rom_file_name_local = 'zookeep2'
    # system_file_name_local = 'airwolf.tzx'
    system_file_name_local=''
    path_to_mame_ini_file_local = iniFile.read_ini_file('path', 'mame_ini')
    folder_ini_local = iniFile.get_from_mameini('inipath', path_to_mame_ini_file_local)
    path_executable_local = iniFile.read_ini_file('path', 'mame_executable')

    # PreferencesLocal(title=f'ROM Specific Preferences - {rom_name_local}',
    #                  mode='game',
    #                  rom_file_name=rom_file_name_local,
    #                  folder_ini=folder_ini_local,
    #                  path_executable=path_executable_local,
    #                  system_file_name=system_file_name_local,
    #                  is_a_system=True)

    PreferencesLocal('Default Preferences',
                     'default',
                     '',
                     '',
                     '',
                     '',
                     False)
    app.MainLoop()
