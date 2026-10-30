#!/usr/bin/env python3

# ----------------------------------------------------------------------------------------------------------------------
# PanelPfeMame.py

import os
from typing import NamedTuple

import wx
import wx.adv
import wx.lib.checkbox
from pubsub import pub

import functions
import global_defaults as gd
import languagepicker
from custom_drop_down import ModernDropdown, EVT_DROPDOWN_SELECTION
from custom_scrolled_panel import CustomScrolledPanel
from preferences_model import COLOR_OPTIONS

try:
    import get_joystick_names
except ModuleNotFoundError:
    get_joystick_names = None  # Only needed (and only available) on Windows

_ = functions.set_up_language()  # Set up the application language


# Define various user interface constants
class UIConstants:
    # Sizes
    CHECKBOX_PANEL_SIZE = wx.Size(500, 210)
    STANDARD_DROPDOWN_SIZE = wx.Size(200, 25)
    SMALL_TEXT_CTRL_SIZE = wx.Size(50, -1)
    LARGE_DROPDOWN_SIZE = wx.Size(400, 25)
    COLOR_BUTTON_HEIGHT = 20

    # Dropdown Choices
    TILE_SIZE_CHOICES = ['Small', 'Medium', 'Large', 'VeryLarge']
    MAIN_VIEW_CHOICES = ['All', 'Favorites', 'Exists', 'Missing']
    ICON_SIZE_CHOICES = ['16', '24', '32']

    # Grid spacing
    GRID_VGAP = 5
    SIZER_BORDER = 2
    GROUP_SPACING = 6   # Space above each group heading in the checkbox list


class Setting(NamedTuple):
    attr: str               # Preferences attribute (see preferences_model.PFEMAME_OPTIONS)
    label: str
    tooltip: str
    restart: bool = False   # Only takes effect after pfeMAME is restarted (the label shows (*))


# The checkboxes, in their groups
CHECKBOX_GROUPS = (
    (_('Startup'), (
        Setting('pref_check_software_version', _('Check software version on startup'),
                _('Check for updates to the application software version online on startup automatically.')),
        Setting('pref_check_catver_version', _('Check Catver.ini file version on startup'),
                _('Check the version of the Catver.ini file on startup and compare to the MAME version.  If not '
                  'matched then warn the user that the versions are not matched')),
        Setting('pref_check_database_age', _('Check ROMs database age on startup'),
                _('Check the age of the ROMs database when the application is started.')),
        Setting('pref_use_last_selected', _('Auto Select the last ROM selected and last view (*)'),
                _('Automatically select the View and last ROM selected when pfeMAME was previously shut down.  '
                  'This overrides the control above.'), restart=True),
        Setting('pref_view', _('Set Tile View as Default (after startup)'),
                _('Select this if you want the \'Tile\' view to run automatically after the pfeMAME application has '
                  'launched.')),
        Setting('pref_set_window_fullscreen', _('Set main window full-screen on startup'),
                _('Sets the main view window to full-screen after startup.')),
        Setting('pref_recall_column_widths', _('Recall column widths on startup'),
                _('Recalls the ROM list column widths based on what they were when the application was closed.')),
    )),
    (_('Main View and ROMs List'), (
        Setting('pref_highlight_missing', _('Highlight ROMs with missing files (*)'),
                _('Select this if you want ROMs that don\'t have a corresponding rom file in the defined path to be '
                  'highlighted.'), restart=True),
        Setting('pref_show_game_icons', _('Show an icon of the ROM in the ROMs list (can slow down startup) (*)'),
                _('When selected, the ROM list view will show a small icon next to the ROM name.  This can slow down '
                  'the start up time if the icons are larger than 16x16 pixels'), restart=True),
        Setting('pref_click_fav_rating', _('Click to set Favorite + Rating (*)'),
                _('Allows double clicking on the Favorite and Rating columns to invoke their selection for the '
                  'selected ROM.'), restart=True),
        Setting('pref_flash_messages_if_error', _('Flash errors in messages window'),
                _('Flash the messages window if errors are detected.')),
        Setting('pref_system_support', _('Systems / Software Lists support (*)(**)'),
                _('Provide support for Systems (e.g. ZX Spectrum) by searching for their programs and including them '
                  'in the ROMs list when a refresh is performed (Requires a database refresh).'), restart=True),
        Setting('pref_short_name_global_suppress', _('Suppress Short Names'),
                _('Override the detection of short names in ROMs XML files.  For systems this will prevent cheats '
                  'from being available but is necessary if the rom file doesn\'t match the detail in the XML file')),
    )),
    (_('Tile View'), (
        Setting('pref_tile_dim', _('Dim Tile View Tiles not selected'),
                _('Dim ROM image tiles in \'Tile View\' so that the selected ROM stands out.')),
        Setting('pref_tile_letter_jump', _('Jump to a letter in Tile View with the A-Z keys'),
                _('In Tile View, pressing a letter key jumps to the next ROM starting with that letter.  Leave this '
                  'off if your control panel sends letter keys for its buttons.')),
        Setting('pref_tile_mouse', _('Mouse support in Tile View'),
                _('Use the mouse in Tile View: click to select, double-click to play, the wheel to move and '
                  'right-click for the menu.  The pointer shows while the mouse moves.  Leave this off if your '
                  'cabinet has a trackball or spinner set up as a mouse.')),
    )),
    (_('Playing ROMs and Videos'), (
        Setting('pref_force_all_fullscreen', _('Play all ROMs in Full Screen'),
                _('Forces all ROMs to be played in Full Screen regardless of the ROM specific preference setting.')),
        Setting('pref_force_all_window', _('Play all ROMs in a Window'),
                _('Forces all ROMs to be played in a window regardless of the ROM specific preference setting '
                  '(Except for Tile View that is always in Full Screen.)')),
        Setting('pref_disable_artwork', _('Disable Artwork for all ROMs'),
                _('This disables the showing of artwork around the ROM playing area on the screen for all ROMs')),
        Setting('pref_video_autoload', _('Auto load the ROM video if available (*)'),
                _('Auto Load the ROM video if one exists for the selected ROM.  Video loads and plays after 5 seconds '
                  'in the main view unless another ROM is selected.  In Tile View this turns the tile preview videos '
                  'on or off (the screensaver is not affected).'), restart=True),
        Setting('pref_video_disable', _('Disable all video playback (*)'),
                _('Disable all video playback in the Main and Tile Views.'), restart=True),
        Setting('pref_software_video', _('Use software video rendering (*)'),
                _('Draw videos without OpenGL.  Try this if videos show as a black or flickering box, which can '
                  'happen with some Linux / Wayland graphics drivers.  It uses more CPU than OpenGL.  pfeMAME also '
                  'switches to software rendering by itself if OpenGL fails to start.'), restart=True),
        Setting('pref_screensaver_hide_title', _('Hide the screensaver video title after a few seconds'),
                _('In the full screen video player (the screensaver), show the video title for a few seconds when '
                  'each video starts and then hide it so it does not cover the video.  When this is off the title '
                  'stays on screen.')),
    )),
    (_('Joystick'), (
        Setting('pref_enable_joystick_mainview', _('Enable joystick navigation for Main View (*)'),
                _('Allow the joystick or gamepad selected above to provide navigation in the Main View window.'),
                restart=True),
        Setting('pref_enable_joystick_tileview', _('Enable joystick navigation for Tile View (*)'),
                _('Allow the joystick or gamepad selected above to provide navigation in the Tile View window.'),
                restart=True),
    )),
)

# Preferences other than the checkboxes and colours that only take effect after a restart
RESTART_SETTINGS = frozenset(['pref_icon_size', 'pref_joystick_selected'])

# Ticking one of these unticks the other
OPPOSITES = {'pref_force_all_fullscreen': 'pref_force_all_window',
             'pref_force_all_window': 'pref_force_all_fullscreen'}

# The colour buttons, in their groups: (application colour name, label)
COLOR_GROUPS = (
    (_('List Colors'), (
        ('row_alt_1', _('Alternate Row Color 1:')),
        ('row_alt_2', _('Alternate Row Color 2:')),
        ('selected_row', _('Selected Row Color:')),
        ('selected_row_background', _('Selected Row BG Color:')),
        ('missing_game', _('Missing ROM Color:')),
    )),
    (_('UI Elements'), (
        ('text', _('Text Color:')),
        ('text_background', _('Text Background Color:')),
        ('window_background', _('Window Background Color:')),
        ('control_bar', _('Control Bar Color:')),
        ('button_background', _('Button Background Color:')),
    )),
    (_('Special UI'), (
        ('ribbon_bar', _('Ribbon Bar Color:')),
        ('ribbon_item_highlight', _('Ribbon Bar Highlight Color:')),
        ('scrollbar_thumb', _('Scrollbar Slider Color:')),
        ('scrollbar_track', _('Scrollbar Track Color:')),
    )),
)

# Preferences attribute for each application colour name
COLOR_ATTRS = {color_name: attr for attr, color_name in COLOR_OPTIONS}
COLOR_OPTIONS_ATTRS = frozenset(COLOR_ATTRS.values())


def dark_theme_colors() -> dict:
    """Application colour name: colour for the Dark Theme (every colour is set)"""
    return {
        'row_alt_1': wx.Colour(192, 192, 192),
        'row_alt_2': wx.Colour(173, 216, 230),
        'text': wx.Colour(255, 255, 255),
        'text_background': wx.Colour(32, 32, 32),
        'window_background': wx.Colour(32, 32, 32),
        'missing_game': wx.Colour(255, 153, 153),
        'control_bar': wx.Colour(104, 108, 113),
        'selected_row': wx.Colour(255, 0, 0),
        'selected_row_background': wx.Colour(0, 255, 0),
        'ribbon_bar': wx.Colour(32, 32, 32),
        'ribbon_item_highlight': wx.Colour(0, 255, 0),
        'scrollbar_thumb': wx.Colour(100, 100, 100),
        'scrollbar_track': wx.Colour(40, 40, 40),
        'button_background': wx.Colour(30, 30, 30),
    }


def contrast_color(color: wx.Colour) -> wx.Colour:
    """
    Black or white, whichever can be read on top of the colour given

    :param color: Background colour
    :returns: Text colour to use on it
    """
    # Perceived luminance (ITU-R BT.709)
    luminance = 0.2126 * color.Red() + 0.7152 * color.Green() + 0.0722 * color.Blue()
    return wx.Colour(wx.WHITE) if luminance < 128 else wx.Colour(wx.BLACK)


class PanelPfeMame(wx.Panel):
    # ------------------------------------------------------------------------------------------------------------------
    # This class is for the pfeMAME preferences notebook tab.
    # values: {Preferences attribute: value} for the pfeMAME preferences (preferences_model.PFEMAME_OPTIONS)
    def __init__(self, parent, application_colors: dict, global_font_normal, values: dict):
        wx.Panel.__init__(self, parent=parent)

        self.parent = parent
        self.application_colors = application_colors
        self.global_font_normal = global_font_normal
        self.values = values

        # --------------------------------------------------------------------------------------------------------------
        # Try to work out the platform
        # This is needed for platform specific preferences
        self.system = functions.get_platform()

        # --------------------------------------------------------------------------------------------------------------
        # Get the path to this application
        self.path_to_me = functions.path_to_me()

        # --------------------------------------------------------------------------------------------------------------
        # Start with control changes triggering events blocked so that we can recall the controls current value but
        # not trigger a writing event in the process
        self.startup_complete = False

        self.controls = {}          # Preferences attribute: control
        self.restart_settings = set(RESTART_SETTINGS) | COLOR_OPTIONS_ATTRS
        self.setup_pubsub_listeners()
        self.number_of_joysticks, self.joystick_names = self.setup_joysticks()
        self.create_controls()
        self.define_sizers()
        self.set_tab_order()
        self.apply_system_colors()
        self.set_control_values()
        self.sent_values = self.current_values()  # What the preferences window has - only changes are sent
        self.update_enabled_controls()

        self.startup_complete = True

    # --------------------------------------------------------------------------------------------------------------
    # Create the panel controls
    def create_controls(self) -> None:
        self.panel_checkboxes = self._create_preferences_checkboxes()

        self.cbTileSize = self._add_dropdown('pref_tile_size', UIConstants.TILE_SIZE_CHOICES,
                                             UIConstants.STANDARD_DROPDOWN_SIZE,
                                             _('Set the size of the ROM image tiles in \'Tile View\'.'))
        self.cbMainView = self._add_dropdown('pref_main_view', UIConstants.MAIN_VIEW_CHOICES,
                                             UIConstants.STANDARD_DROPDOWN_SIZE,
                                             _('This sets the default view that the ROMs list will show when the '
                                               'application starts up.'))
        self.cbDaysCheckCache = self._add_spin('pref_days_check_cache', 1, 365, 30,
                                               _('This sets the number of days after which a prompt is produced at '
                                                 'startup to refresh the ROMs cache.'))
        self.cbScreensaverTime = self._add_spin('pref_screensaver_time', 0, 60, 5,
                                                _('Number of minutes of inactivity before the screensaver is '
                                                  'activated.  Set to Zero to disable.'))
        self.cbIconSize = self._add_dropdown('pref_icon_size', UIConstants.ICON_SIZE_CHOICES,
                                             UIConstants.STANDARD_DROPDOWN_SIZE,
                                             _('This sets the scaling size for the ROM icons (if any exist and they '
                                               'are enabled).  16 pixels is the default.'))
        self.cbJoystickSelected = self._add_dropdown('pref_joystick_selected',
                                                     self.get_joystick_views(self.number_of_joysticks,
                                                                             self.joystick_names),
                                                     UIConstants.LARGE_DROPDOWN_SIZE,
                                                     _('The joystick or gamepad used to navigate the Main View and '
                                                       'Tile View.'))

        self.note = wx.StaticText(self, -1, _('* - Requires restart  ** - Requires database refresh'),
                                  style=wx.ALIGN_LEFT)
        self.note.SetFont(self.global_font_normal)

        # Add the color controls
        self.color_panel = ColorControlsPanel(self, self.application_colors, self.global_font_normal,
                                              self.on_button_color_select, self.on_default, self.on_dark_theme)
        for color_name in COLOR_ATTRS:
            self.controls[COLOR_ATTRS[color_name]] = self.color_panel.buttons[color_name]

        # Create the language control
        img = wx.Image(os.path.join(self.path_to_me, 'images', 'languages.png'), wx.BITMAP_TYPE_ANY)
        self.lang_btn = wx.BitmapButton(self, bitmap=wx.Bitmap(img))
        self.lang_btn.SetBackgroundColour(self.application_colors['button_background'])
        self.lang_btn.SetToolTip(_('Choose the language pfeMAME uses.  pfeMAME must be restarted for the change to '
                                   'take effect.'))
        self.lang_btn.Bind(wx.EVT_BUTTON, self.on_select_language)
        self.lang_label = wx.StaticText(self, -1, _('Language (*)'))
        self.lang_label.SetFont(self.global_font_normal)

    # ------------------------------------------------------------------------------------------------------------------
    def _add_dropdown(self, attr: str, choices: list, size: wx.Size, tooltip: str) -> ModernDropdown:
        dropdown = ModernDropdown(self, size=size, choices=choices)
        dropdown.SetToolTip(tooltip)
        dropdown.Bind(EVT_DROPDOWN_SELECTION, self.on_control_changed)
        self.controls[attr] = dropdown
        return dropdown

    def _add_spin(self, attr: str, low: int, high: int, initial: int, tooltip: str) -> wx.SpinCtrl:
        spin = wx.SpinCtrl(self, value='', size=UIConstants.SMALL_TEXT_CTRL_SIZE, style=wx.SP_ARROW_KEYS,
                           min=low, max=high, initial=initial)
        spin.SetToolTip(tooltip)
        spin.Bind(wx.EVT_SPINCTRL, self.on_control_changed)
        spin.Bind(wx.EVT_TEXT, self.on_control_changed)  # For manual typing
        self.controls[attr] = spin
        return spin

    # ------------------------------------------------------------------------------------------------------------------
    # Define the sizers and add the controls
    def define_sizers(self) -> None:

        def _add_labeled_control_row(label_text, control):
            """
            Add a label and control pair to the controls grid.

            :param label_text: Text for the label
            :param control: The control widget
            """
            label = wx.StaticText(self, -1, label_text, style=wx.ALIGN_RIGHT)

            self.controls_grid.Add(label, 0, wx.ALIGN_RIGHT | wx.ALIGN_CENTER_VERTICAL)
            self.controls_grid.Add(control, 0, wx.ALIGN_LEFT)

        self.sizer = wx.BoxSizer(wx.VERTICAL)
        self.sizer_pfemame_preferences = wx.BoxSizer(wx.VERTICAL)
        self.sizer_pfemame_preferences_sub = wx.BoxSizer(wx.VERTICAL)

        # Create ONE FlexGridSizer for all the labeled controls
        self.controls_grid = wx.FlexGridSizer(rows=0, cols=2, hgap=10, vgap=5)

        # Add each row to the same grid
        _add_labeled_control_row(_('Number of days to check ROM cache'), self.cbDaysCheckCache)
        _add_labeled_control_row(_('Minutes for Screensaver'), self.cbScreensaverTime)
        _add_labeled_control_row(_('Default ROM list view at startup'), self.cbMainView)
        _add_labeled_control_row(_('Icons Size for ROMs list (*)'), self.cbIconSize)
        _add_labeled_control_row(_('Tile Size in Tile View'), self.cbTileSize)
        _add_labeled_control_row(_('Joystick Selected For Navigation (*)'), self.cbJoystickSelected)

        sizer_language = wx.BoxSizer(wx.HORIZONTAL)
        sizer_language.Add(self.lang_btn, 0, wx.ALIGN_CENTER_VERTICAL)
        sizer_language.AddSpacer(8)
        sizer_language.Add(self.lang_label, 0, wx.ALIGN_CENTER_VERTICAL)

        # Add the grid to the parent sizer
        self.sizer_pfemame_preferences_sub.Add(self.controls_grid, 0, wx.ALL, 2)
        self.sizer_pfemame_preferences_sub.Add(self.panel_checkboxes, 0, wx.EXPAND)
        self.sizer_pfemame_preferences_sub.AddSpacer(10)
        self.sizer_pfemame_preferences_sub.Add(self.note)
        self.sizer_pfemame_preferences_sub.AddSpacer(5)
        self.sizer_pfemame_preferences_sub.Add(sizer_language)

        self.sizer_grid_2 = wx.BoxSizer(wx.HORIZONTAL)
        self.sizer_grid_2.AddSpacer(10)
        self.sizer_grid_2.Add(self.sizer_pfemame_preferences_sub, 1, wx.EXPAND)
        self.sizer_grid_2.Add(self.color_panel)
        self.sizer_grid_2.AddSpacer(10)

        self.sizer_pfemame_preferences.AddSpacer(5)
        self.sizer_pfemame_preferences.Add(self.sizer_grid_2, 1, wx.EXPAND)

        self.sizer.Add(self.sizer_pfemame_preferences, 1, wx.EXPAND)
        self.sizer.AddSpacer(10)

        self.SetSizer(self.sizer)
        self.sizer.Fit(self)

    # TAB goes down the left column (as laid out in define_sizers), then the colours on the right
    def set_tab_order(self) -> None:
        functions.set_tab_order([self.cbDaysCheckCache, self.cbScreensaverTime, self.cbMainView, self.cbIconSize,
                                 self.cbTileSize, self.cbJoystickSelected, self.panel_checkboxes, self.lang_btn,
                                 self.color_panel])

    # Ensure all controls have the system-wide colors
    def apply_system_colors(self) -> None:
        functions.set_colors(self, self.application_colors)

    # Set the controls values from the INI files
    def set_control_values(self) -> None:
        for attr, control in self.controls.items():
            if attr in COLOR_OPTIONS_ATTRS:
                continue  # The colour buttons are created with their colours
            value = self.values.get(attr, '')
            if isinstance(control, wx.lib.checkbox.GenCheckBox):
                control.SetValue(value == 'True')
            else:
                control.SetValue(value)

    # ------------------------------------------------------------------------------------------------------------------
    def current_values(self) -> dict:
        """{Preferences attribute: value as it is saved} for every control"""
        values = {}
        for attr, control in self.controls.items():
            if attr in COLOR_OPTIONS_ATTRS:
                values[attr] = str(control.GetBackgroundColour())
            else:
                values[attr] = str(control.GetValue())
        return values

    # ------------------------------------------------------------------------------------------------------------------
    def update_enabled_controls(self) -> None:
        """Grey out the settings that can't have any effect with the other settings as they are"""
        joysticks_found = self.number_of_joysticks > 0
        self.controls['pref_enable_joystick_mainview'].Enable(joysticks_found)
        self.controls['pref_enable_joystick_tileview'].Enable(joysticks_found)
        navigation_on = (self.controls['pref_enable_joystick_mainview'].GetValue() or
                         self.controls['pref_enable_joystick_tileview'].GetValue())
        self.cbJoystickSelected.Enable(joysticks_found and navigation_on)
        self.cbIconSize.Enable(self.controls['pref_show_game_icons'].GetValue())
        self.controls['pref_video_autoload'].Enable(not self.controls['pref_video_disable'].GetValue())
        self.cbDaysCheckCache.Enable(self.controls['pref_check_database_age'].GetValue())

    # --------------------------------------------------------------------------------------------------------------
    # Get joystick details from the operating system
    def setup_joysticks(self) -> tuple[int, list[str]]:
        joystick = wx.adv.Joystick()
        number_of_joysticks = joystick.GetNumberJoysticks()
        joystick.Destroy()
        wx.CallAfter(pub.sendMessage, 'update_logfile', msg=f'Number of joysticks found = {number_of_joysticks}')

        joystick_names = []
        if self.system == 'windows':
            if get_joystick_names is not None:
                try:
                    joystick_names = get_joystick_names.get_joystick_names()
                except OSError as error:
                    wx.CallAfter(pub.sendMessage, 'update_logfile', msg=f'Unable to get the joystick names: {error}')
        else:
            # This is for Linux or macOS
            for joystick_id in [wx.JOYSTICK1, wx.JOYSTICK2][:number_of_joysticks]:
                joy = wx.adv.Joystick(joystick=joystick_id)
                joystick_names.append(joy.GetProductName())
                joy.Destroy()
        joystick_names = list(joystick_names)
        joystick_names += ['Unknown'] * (number_of_joysticks - len(joystick_names))  # A name for every joystick
        wx.CallAfter(pub.sendMessage, 'update_logfile', msg=f'Joystick names: {joystick_names}')
        return number_of_joysticks, joystick_names

    # --------------------------------------------------------------------------------------------------------------
    # Set up the pubsub listeners
    def setup_pubsub_listeners(self) -> None:
        self._subscriptions = [(self.disable_catver_check, 'disable_catver_check'),
                               (self.disable_software_version_check, 'disable_software_version_check')]
        for listener, topic in self._subscriptions:
            pub.subscribe(listener, topic)
        self.Bind(wx.EVT_WINDOW_DESTROY, self._on_destroy)

    def _on_destroy(self, event):
        # Destroy events from child windows arrive here too - only act when this panel is being destroyed
        if event.GetEventObject() is self:
            for listener, topic in self._subscriptions:
                pub.unsubscribe(listener, topic)
            self._subscriptions = []
        event.Skip()

    # ------------------------------------------------------------------------------------------------------------------
    def _create_preferences_checkboxes(self) -> wx.Panel:
        """
        Create the checkbox controls, under their group headings, on the scrolled panel and return that panel object
        :returns:  returns a wx.Panel object containing the checkboxs
        """
        panel = CustomScrolledPanel(self,
                                    size=UIConstants.CHECKBOX_PANEL_SIZE,
                                    style=wx.SIMPLE_BORDER
                                    )
        panel.SetScrollbarThumbColor(self.application_colors['scrollbar_thumb'])
        panel.SetScrollbarTrackColor(self.application_colors['scrollbar_track'])

        heading_font = self.global_font_normal.Bold()
        for index, (heading, settings) in enumerate(CHECKBOX_GROUPS):
            if index:
                panel.content_sizer.AddSpacer(UIConstants.GROUP_SPACING)
            title = wx.StaticText(panel.content, -1, heading)
            title.SetFont(heading_font)
            panel.add_widget(title)
            for setting in settings:
                checkbox = wx.lib.checkbox.GenCheckBox(panel.content, -1, setting.label)
                checkbox.SetToolTip(setting.tooltip)
                checkbox.Bind(wx.EVT_CHECKBOX, self.on_control_changed)
                panel.add_widget(checkbox)
                self.controls[setting.attr] = checkbox
                if setting.restart:
                    self.restart_settings.add(setting.attr)

        return panel

    # ------------------------------------------------------------------------------------------------------------------
    def get_joystick_views(self, number_of_joysticks: int, joystick_names: list[str]) -> list[str]:
        """
        Get the joystick views for the control
        :param number_of_joysticks: Number of joysticks detected on the system
        :param joystick_names: List of joystick names
        :returns: Returns a list of joysticks available
        """
        views = []
        for i in range(min(number_of_joysticks, len(joystick_names))):
            views.append(f'Joystick {i + 1}: {joystick_names[i]}')
        return views if views else ['No joysticks detected']

    # ------------------------------------------------------------------------------------------------------------------
    # Untick a startup check that pfemame.py has already switched off in the INI file (the user ticked "Don't show
    # this again").  These are called from pub listeners in the parent pfeMAME file.
    def disable_catver_check(self):
        self._untick('pref_check_catver_version')

    def disable_software_version_check(self):
        self._untick('pref_check_software_version')

    def _untick(self, attr: str) -> None:
        if not self:
            return  # The window has gone
        self.controls[attr].SetValue(False)
        self.send_changes()

    # ------------------------------------------------------------------------------------------------------------------
    # Set up the application language
    def on_select_language(self, _event):
        dlg = languagepicker.LanguagePicker(self)
        if dlg.ShowModal() == wx.ID_OK:  # A different language was chosen
            wx.CallAfter(pub.sendMessage, 'restart_required')
        dlg.Destroy()
        wx.CallAfter(self.color_panel.repaint_buttons)

    # ------------------------------------------------------------------------------------------------------------------
    def _confirm(self, message: str, caption: str) -> bool:
        dlg = wx.MessageDialog(self, message, caption, wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION)
        res = dlg.ShowModal()
        dlg.Destroy()
        wx.CallAfter(self.color_panel.repaint_buttons)  # The buttons stay grey after a modal dialog otherwise
        return res == wx.ID_YES

    # Reset all colors to their default values
    def on_default(self, _event):
        if self._confirm(_('Are you sure you want to reset all colors?'), _('Reset all colors to default')):
            self.set_color_controls(gd.get_color_defaults())

    # Set all colors to Dark Theme
    def on_dark_theme(self, _event):
        if self._confirm(_('Are you sure you want to change all colors to the Dark Theme?'),
                         _('Select Dark Theme')):
            self.set_color_controls(dark_theme_colors())

    # ------------------------------------------------------------------------------------------------------------------
    def set_color_controls(self, colors: dict) -> None:
        """
        Set the color buttons to the colours given and save them.

        :param colors: {application colour name: colour}
        """
        for color_name, color in colors.items():
            self.color_panel.set_button_color(color_name, color)
        self.Refresh()
        self.on_control_changed()

    # ------------------------------------------------------------------------------------------------------------------
    def on_button_color_select(self, event) -> None:
        """
        Select the items color using a color picker object
        """
        # Get the current colour for the button selected
        button = event.GetEventObject()
        data = wx.ColourData()
        data.SetChooseFull(True)
        data.SetColour(button.GetBackgroundColour())

        # Open the color chooser and get a new color
        dialog = wx.ColourDialog(self, data)
        if dialog.ShowModal() == wx.ID_OK:
            self.color_panel.set_button_color(button.GetName(), dialog.GetColourData().GetColour())
            self.on_control_changed()
        dialog.Destroy()
        wx.CallAfter(self.color_panel.repaint_buttons)

    # ------------------------------------------------------------------------------------------------------------------
    def on_control_changed(self, event=None):
        """
        A control has changed: send what changed to the preferences window (which saves it to the INI file)
        """
        if not self.startup_complete:
            return

        # Handle the toggle effect for the window and full screen force checkboxs
        if event is not None:
            for attr, opposite in OPPOSITES.items():
                if event.GetEventObject() is self.controls[attr] and self.controls[attr].GetValue():
                    self.controls[opposite].SetValue(False)

        self.update_enabled_controls()
        changed = self.send_changes()
        if changed & self.restart_settings:
            wx.CallAfter(pub.sendMessage, 'restart_required')

    def send_changes(self) -> set:
        """
        Send the preferences that have changed since they were last sent and ask for them to be saved
        :returns: the attributes sent
        """
        current = self.current_values()
        changed = {attr for attr, value in current.items() if value != self.sent_values.get(attr)}
        for attr in changed:
            wx.CallAfter(pub.sendMessage, 'default_set_variable', msg=[attr, current[attr]])
        if changed:
            wx.CallAfter(pub.sendMessage, 'default_update_ini')
        self.sent_values = current
        return changed


# ----------------------------------------------------------------------------------------------------------------------
class ColorControlsPanel(wx.Panel):
    """
    This is my color control.
    It allows you to adjust the color values for various aspects of the interface, including setting a global
    'Light' or 'Dark' mode for colors.
    """

    def __init__(self, parent, application_colors, global_font_normal, on_color_select, on_default, on_dark_theme):
        super().__init__(parent)
        self.application_colors = application_colors
        self.global_font_normal = global_font_normal
        self.on_color_select = on_color_select
        self.on_default = on_default
        self.on_dark_theme = on_dark_theme
        self.parent = parent
        self.buttons = {}           # Application colour name: its colour button
        self.action_buttons = []

        sizer = self._build_ui()
        self.SetSizer(sizer)

    # ------------------------------------------------------------------------------------------------------------------
    def _build_ui(self) -> wx.Sizer:
        """
        Build the user interface
        :returns: Returns a wx.BoxSizer which will contain the grouped controls
        """
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        for heading, color_definitions in COLOR_GROUPS:
            box = wx.StaticBox(self, label=heading)
            box_sizer = wx.StaticBoxSizer(box, wx.VERTICAL)
            grid = self._create_color_group(box, color_definitions)
            box_sizer.Add(grid, 0, wx.ALL | wx.EXPAND, 5)
            main_sizer.Add(box_sizer, 0, wx.ALL | wx.EXPAND, 5)

        # Add action buttons at the bottom
        main_sizer.AddSpacer(10)
        self._add_action_buttons(main_sizer)

        return main_sizer

    # ------------------------------------------------------------------------------------------------------------------
    def _create_color_group(self, parent, color_definitions) -> wx.GridBagSizer:
        """
        Create a group of color controls

        :param color_definitions: (application colour name, label text) for each colour
        :returns: GridBagSizer containing the color controls
        """
        sizer = wx.GridBagSizer(vgap=UIConstants.GRID_VGAP, hgap=5)

        for idx, (color_name, text_display) in enumerate(color_definitions):
            text_ctrl = functions.create_text_ctrl(
                parent, -1, text_display, wx.ALIGN_LEFT, 10, wx.DEFAULT, wx.NORMAL, wx.NORMAL,
                self.application_colors['text']
            )
            color = wx.Colour(self.application_colors[color_name])

            color_btn = functions.build_one_button(
                parent=parent,
                label=color.GetAsString(wx.C2S_HTML_SYNTAX),
                handler=self.on_color_select,
                tooltip=_('Click here to change the color'),
                background_color=self.application_colors[color_name],
                vertical_size=UIConstants.COLOR_BUTTON_HEIGHT,
                name=color_name,
                foreground_color=contrast_color(color)
            )
            self.buttons[color_name] = color_btn

            sizer.Add(text_ctrl, pos=(idx, 0), flag=wx.ALIGN_CENTRE_VERTICAL)
            sizer.Add(color_btn, pos=(idx, 1), flag=wx.ALIGN_CENTRE_VERTICAL | wx.ALIGN_RIGHT)
            if not sizer.IsColGrowable(0):
                sizer.AddGrowableCol(0)  # Helps to align the color buttons to the right

        return sizer

    # ------------------------------------------------------------------------------------------------------------------
    def _add_action_buttons(self, sizer: wx.Sizer) -> None:
        """
        Add the action buttons (Default, Dark Theme)

        :param sizer: Sizer to add buttons to
        """
        def_btn = functions.build_one_button(
            self, _('DEFAULT ALL COLORS'), self.on_default,
            _('Set all color values to their application default.'),
            background_color=self.application_colors['text_background'],
            foreground_color=self.application_colors['text']
        )
        def_btn.SetFont(self.global_font_normal)

        dark_btn = functions.build_one_button(
            self, _('SELECT DARK THEME'), self.on_dark_theme,
            _('Set the application colors to Dark Theme.'),
            background_color=self.application_colors['text_background'],
            foreground_color=self.application_colors['text']
        )
        dark_btn.SetFont(self.global_font_normal)
        self.action_buttons = [def_btn, dark_btn]

        sizer.Add(def_btn, 0, wx.ALL | wx.EXPAND, 2)
        sizer.Add(dark_btn, 0, wx.ALL | wx.EXPAND, 2)

    # ------------------------------------------------------------------------------------------------------------------
    def set_button_color(self, color_name: str, color) -> None:
        """Show a colour on its button: the background, its #RRGGBB code and a text colour that can be read on it"""
        color = wx.Colour(color)
        button = self.buttons[color_name]
        button.SetBackgroundColour(color)
        button.SetForegroundColour(contrast_color(color))
        button.SetLabel(color.GetAsString(wx.C2S_HTML_SYNTAX))
        button.Refresh()

    def repaint_buttons(self) -> None:
        """
        Redraw the buttons after a modal dialog: they are drawn greyed out while it is open and nothing redraws them
        when it closes
        """
        if not self:
            return
        for button in list(self.buttons.values()) + self.action_buttons:
            button.Refresh()
            button.Update()


# ------------------------------------------------------------------------------------------------------------------
# This class allows us to run the PanelPfeMame module locally for testing purposes
class PanelPfeMameLocal(wx.Frame):

    def __init__(self):
        style = (wx.SYSTEM_MENU | wx.CAPTION | wx.CLOSE_BOX)
        wx.Frame.__init__(self, wx.GetApp().TopWindow, -1, 'PanelPfeMame', wx.DefaultPosition, style=style)

        self.SetSize(1300, 600)

        self.Bind(wx.EVT_CLOSE, self.on_close)

        import iniFile
        from preferences_model import PFEMAME_OPTIONS
        values = {option.attr: iniFile.read_ini_file('preferences', option.ini_key, default=option.default)
                  for option in PFEMAME_OPTIONS}
        self.panel = PanelPfeMame(self, functions.get_application_colors(), functions.get_font_info().global_font_normal,
                                  values)

        self.Show()

    def on_close(self, _event):
        self.Destroy()


if __name__ == '__main__':

    app = wx.App()
    PanelPfeMameLocal()
    app.MainLoop()
