#!/usr/bin/env python3

# ----------------------------------------------------------------------------------------------------------------------
# alternate_emulators.py

"""
This module allows the graphical management of the alternate emulators data contained in the XML file called:
non_mame_emulators.xml.
"""

# Import python & wxPython modules
import wx
import wx.lib.agw.ultimatelistctrl as ulc
import os
import xml.etree.ElementTree as ET

# Import my own modules
from functions import data_dir
from functions import (set_colors,
                       UltimateHeaderRenderer,
                       set_font,
                       set_up_language,
                       on_key_up,
                       get_platform,
                       get_application_colors,
                       load_categories_file,
                       path_to_me,
                       load_other_emulators_detail,
                       build_one_button,
                       show_popup_menu)
import rungame
import rom_database
import iniFile
from custom_drop_down import ModernDropdown, EVT_DROPDOWN_SELECTION
from emulator_config import (EMULATORS_XML_FILE,
                             EmulatorFields,
                             PLACEHOLDER_ROM_ENTRY,
                             emulator_names_in_order,
                             fill_rom_names,
                             load_default_emulator_settings,
                             merge_scanned_roms,
                             save_emulators,
                             scan_rom_folders)

# Column indices for list control
COL_ROM_NAME = 0
COL_FILE_NAME = 1

# Shown in place of the emulator name when there are none (a function so it is translated after set_up_language)
def no_emulators_label() -> str:
    return _('No emulators - use CREATE NEW EMULATOR ENTRY')


# Button Sizes
BUTTON_WIDTH_STANDARD = 200
BUTTON_WIDTH_WIDE = 250

_ = set_up_language()  # Set of the application language


# The most problems listed in the warning before saving (the rest are counted)
MAX_PROBLEMS_SHOWN = 15


def find_setup_problems(engine_rows: list[list]) -> list[str]:
    """
    Look through all the emulators for likely mistakes, to warn about before saving.  None of these stop the file
    being saved (a drive may just not be connected at the moment).

    - An enabled emulator whose program, or ROM folder (other than 'Default'), doesn't exist or isn't set
    - The same ROM file listed more than once in one emulator
    - A ROM file listed under more than one enabled emulator, when only the first is used

    :param engine_rows: Rows as returned by load_other_emulators_detail, one per ROM
    :returns: A description of each problem found, in emulator order
    """
    problems = []
    emulators: dict[str, list[list]] = {}
    for row in engine_rows:
        emulators.setdefault(row[EmulatorFields.NAME], []).append(row)

    used_by: dict[str, str] = {}  # ROM file name -> the first enabled emulator listing it, which is the one used
    for name, rows in emulators.items():
        settings = rows[0]
        enabled = settings[EmulatorFields.ENABLED]
        if enabled:
            path = settings[EmulatorFields.PATH]
            if not path:
                problems.append(_('{}: no emulator program has been set.').format(name))
            elif not os.path.isfile(path):
                problems.append(_('{emulator}: the emulator program {path} was not found.').format(emulator=name,
                                                                                             path=path))

            rom_folder = settings[EmulatorFields.ROM_FOLDER]
            if not rom_folder:
                problems.append(_('{}: no ROM folder has been set (use \'Default\' for the MAME ROM folder).')
                                .format(name))
            elif rom_folder != 'Default' and not os.path.isdir(rom_folder):
                problems.append(_('{emulator}: the ROM folder {folder} was not found.').format(emulator=name,
                                                                                    folder=rom_folder))

        seen = set()
        reported = set()
        for row in rows:
            file_name = row[EmulatorFields.ROM_FILE_NAME]
            if file_name.casefold() in seen and file_name.casefold() not in reported:
                problems.append(_('{emulator}: {file_name} is listed more than once.').format(emulator=name,
                                                                                         file_name=file_name))
                reported.add(file_name.casefold())
            seen.add(file_name.casefold())

            if enabled:
                first = used_by.setdefault(file_name, name)
                if first != name:
                    problems.append(_('{file_name} is listed under both {first} and {second}.  '
                                      'Only {first} will be used.')
                                    .format(file_name=file_name, first=first, second=name))
    return problems


# ----------------------------------------------------------------------------------------------------------------------
# Window for displaying the rom information
class AlternateEmulators(wx.Frame):
    def __init__(self, on_closed=None):
        """
        :param on_closed: Optional function called (with no arguments) once the window has closed, e.g. for the main
                          window to re-load the emulator data, which may have changed.  The window doesn't block, so
                          the caller can't simply re-load after creating it.
        """
        style = wx.DEFAULT_FRAME_STYLE
        wx.Frame.__init__(self,
                          wx.GetApp().TopWindow,
                          -1,
                          _('Alternate Emulators'),
                          wx.DefaultPosition,
                          wx.Size(-1, -1),
                          style=style)

        # --------------------------------------------------------------------------------------------------------------
        # Set some startup variables.  Done first as on_close() needs these, and the startup checks below can close
        # the window.
        self.on_closed = on_closed
        self.startup_complete = False
        self.block_control_changed = False
        self.unsaved_changes = False
        self.emulator_list = []
        self.rom_entries: list[tuple[str, str]] = []  # The (ROM name, file name) entries of the emulator on screen
        self.rom_view: list[int] = []  # The rom_entries shown in the list control (the search may hide some)
        self.rom_sort: tuple[int, bool] | None = None  # The column the ROMs were last sorted by, and if reversed
        self.mame_descriptions: dict[str, str] | None = None  # MAME machine name -> description, read when needed

        # --------------------------------------------------------------------------------------------------------------
        # Get the absolute path to this application.  This is needed if we run via shortcut
        # or link otherwise we couldn't find relative files like icons etc
        self.path_to_me = path_to_me()

        # --------------------------------------------------------------------------------------------------------------
        # Get colour data from the INI file for the application colors
        self.application_colors = get_application_colors()

        # --------------------------------------------------------------------------------------------------------------
        # Load the categories.dat file
        categories = self.load_categories()
        if categories is None:
            self.on_close(-1)  # The user has been told why; don't build the rest of the window
            return

        # --------------------------------------------------------------------------------------------------------------
        # Define the application icon
        self.SetIcon(wx.Icon(os.path.join(self.path_to_me, 'images', 'pfemame.ico'), wx.BITMAP_TYPE_ICO))
        
        if self.GetParent() is not None:  # Following will only be called if this window is running as a child
            self.CenterOnParent()
            self.GetParent().Disable()

        # --------------------------------------------------------------------------------------------------------------
        # Create the panel and bind events
        panel = wx.Panel(self)
        panel.SetFocus()
        self.Bind(wx.EVT_CHAR_HOOK, self.on_key_up_event)  # Use this to capture the escape key to close the window
        self.Bind(wx.EVT_CLOSE, self.on_close)

        # --------------------------------------------------------------------------------------------------------------
        # Try to work out the platform
        # This is needed to sort out some platform specific differences
        self.system = get_platform()

        # --------------------------------------------------------------------------------------------------------------
        # Read the XML file data into memory
        if not self._load_xml_data():
            self.on_close(-1)  # The user has been told why; don't build the rest of the window
            return

        # --------------------------------------------------------------------------------------------------------------
        # Set up the GUI
        self.Freeze()
        self._create_the_controls(panel, categories)  # Create the GUI control elements
        self._set_the_fonts()  # Set up the fonts for the controls
        self._setup_list_control(panel)  # Set up the list control
        self._set_up_tool_tips()  # Set up the control tool tips
        self._create_sizers_add_controls(panel) # Add the controls to the sizers
        set_colors(panel, self.application_colors)  # Set all control colors
        self.Thaw()

        # --------------------------------------------------------------------------------------------------------------
        # Display the window
        self.Centre()
        self.Show()

        # --------------------------------------------------------------------------------------------------------------
        # Complete the startup process
        self.emulator_get_preferences()  # Force the preferences for the selected emulator to be displayed
        self.enable_emulator_controls()
        self.startup_complete = True

    # ------------------------------------------------------------------------------------------------------------------
    # The settings and ROM controls only mean something for an emulator, so with none they are greyed out, leaving
    # Create New Emulator Entry (and OK) as the things to do.
    def enable_emulator_controls(self) -> None:
        have_emulators = bool(self.emulator_list)
        for control in (self.checkbox_enabled,
                        self.text_ctrl_description,
                        self.text_ctrl_emulator_path,
                        self.text_ctrl_extra_commands,
                        self.button_default_rom_folder,
                        self.text_ctrl_rom_folder,
                        self.text_ctrl_valid_extension,
                        self.checkbox_include_extension,
                        self.checkbox_include_folder_path,
                        self.list_control,
                        self.rom_search,
                        self.button_fill_rom_names,
                        self.button_add_rom_entry,
                        self.button_set_defaults,
                        self.button_test_rom,
                        self.button_rename_emulator,
                        self.button_duplicate_emulator,
                        self.button_delete_emulator):
            control.Enable(have_emulators)
        self.update_auto_scan_button()
        self.emulator_selector.Enable(have_emulators)
        self._show_emulators()

    # ------------------------------------------------------------------------------------------------------------------
    # The emulator on screen ('' if there are none)
    @property
    def current_emulator(self) -> str:
        return self.emulator_list[self.emulator_list_index] if self.emulator_list else ''

    # ------------------------------------------------------------------------------------------------------------------
    # How an emulator is listed in the selector: its name, marked if it is disabled
    def _emulator_label(self, name: str) -> str:
        enabled = next((row[EmulatorFields.ENABLED] for row in self.alternate_emulation_engines
                        if row[EmulatorFields.NAME] == name), False)
        return name if enabled else _('{} (disabled)').format(name)

    # ------------------------------------------------------------------------------------------------------------------
    # Fill the selector with the emulators and show the one on screen (or the no emulators message), widening it if
    # the names need it
    def _show_emulators(self) -> None:
        labels = [self._emulator_label(name) for name in self.emulator_list]
        shown = labels[self.emulator_list_index] if labels else no_emulators_label()
        if labels != self.emulator_selector.GetChoices() or shown != self.emulator_selector.GetValue():
            self.emulator_selector.SetChoices(labels)
            self.emulator_selector.SetValue(shown)

        widest = max(self.emulator_selector.GetTextExtent(text)[0] for text in labels + [shown])
        width = max(BUTTON_WIDTH_STANDARD, widest + 50)  # Room for the padding and the arrow
        if self.emulator_selector.GetMinSize().width != width:  # (This is called on every edit)
            self.emulator_selector.SetMinSize(wx.Size(width, 25))
            self.emulator_selector.SetSize(wx.Size(width, 25))
            self.emulator_selector.GetParent().Layout()

    # ------------------------------------------------------------------------------------------------------------------
    # An emulator was picked in the selector
    def on_emulator_chosen(self, event) -> None:
        index = event.selection
        if 0 <= index < len(self.emulator_list) and index != self.emulator_list_index:
            self._go_to_emulator(index)

    # ------------------------------------------------------------------------------------------------------------------
    # Create the controls
    def _create_the_controls(self, panel, categories):
        # The group boxes come first, as wx expects the controls in each to be created inside it
        self.box_rom_entries = wx.StaticBox(panel, label=_('ROM Entries'))
        self.box_basic_config = wx.StaticBox(panel, label=_('Basic Configuration'))
        self.box_rom_folder = wx.StaticBox(panel, label=_('ROM Folder Configuration'))
        self.box_command_line = wx.StaticBox(panel, label=_('Command Line Options'))
        self.box_actions = wx.StaticBox(panel, label=_('Actions'))

        self.info_text = wx.StaticText(panel, -1, '')
        self.update_emulator_quantity()

        btn_size = wx.Size(20, 22)
        tmp = wx.ArtProvider.GetBitmap(wx.ART_GO_BACK, wx.ART_BUTTON, btn_size)
        self.btn_left = wx.StaticBitmap(panel, -1, tmp, size=btn_size)
        self.btn_left.Bind(wx.EVT_LEFT_DOWN, self.emulators_list_left)

        tmp = wx.ArtProvider.GetBitmap(wx.ART_GO_FORWARD, wx.ART_BUTTON, btn_size)
        self.btn_right = wx.StaticBitmap(panel, -1, tmp, size=btn_size)
        self.btn_right.Bind(wx.EVT_LEFT_DOWN, self.emulators_list_right)

        # Lists every emulator, to jump straight to one (the arrows step through them)
        self.emulator_selector = ModernDropdown(panel,
                                                -1,
                                                no_emulators_label(),
                                                choices=[],
                                                size=wx.Size(BUTTON_WIDTH_STANDARD, 25))
        self.emulator_selector.Bind(EVT_DROPDOWN_SELECTION, self.on_emulator_chosen)
        self.text_ctrl_description = ModernDropdown(self.box_basic_config,
                                                    -1,
                                                    '',
                                                    choices=categories,
                                                    size=wx.Size(400, 25))
        self.text_ctrl_description.Bind(EVT_DROPDOWN_SELECTION, self.on_control_changed)

        self.text_ctrl_emulator_path = wx.FilePickerCtrl(self.box_basic_config,
                                                         id=-1,
                                                         path='',
                                                         message=_('Select Emulator Executable File'),
                                                         wildcard='',
                                                         size=wx.Size(400, -1),
                                                         style=wx.FLP_DEFAULT_STYLE | wx.FLP_SMALL,
                                                         validator=wx.DefaultValidator)

        self.text_ctrl_emulator_path.Bind(wx.EVT_FILEPICKER_CHANGED, self.on_control_changed)

        self.text_ctrl_extra_commands = wx.TextCtrl(self.box_basic_config, value='', size=wx.Size(400, -1))
        self.text_ctrl_extra_commands.Bind(wx.EVT_TEXT, self.on_control_changed)

        self.text_ctrl_rom_folder = wx.DirPickerCtrl(self.box_rom_folder,
                                                     path='',
                                                     message=_('Select ROMs Folder for this Emulator'),
                                                     size=wx.Size(400, -1),
                                                     style=wx.DIRP_DEFAULT_STYLE | wx.FLP_SMALL,
                                                     validator=wx.DefaultValidator)
        self.text_ctrl_rom_folder.Bind(wx.EVT_DIRPICKER_CHANGED, self.on_control_changed)

        self.text_ctrl_valid_extension = wx.TextCtrl(self.box_rom_folder, value='', size=wx.Size(200, -1))
        self.text_ctrl_valid_extension.Bind(wx.EVT_TEXT, self.on_control_changed)

        self.button_default_rom_folder = build_one_button(self.box_rom_folder,
                                                          _('Use Default ROM Folder'),
                                                          self.on_default_rom_folder
                                                          )

        self.checkbox_enabled = wx.CheckBox(self.box_basic_config, label=_('Enabled'))
        self.checkbox_include_extension = wx.CheckBox(self.box_command_line,
                                                      label=_('Include file extension in command line'))
        self.checkbox_include_folder_path = wx.CheckBox(self.box_command_line,
                                                        label=_('Include folder path in command line'))
        self.text_ctrl_description_text = wx.StaticText(self.box_basic_config, label=_('Description:'))
        self.text_ctrl_emulator_path_text = wx.StaticText(self.box_basic_config, label=_('Path To Emulator:'))
        self.text_ctrl_extra_commands_text = wx.StaticText(self.box_basic_config, label=_('Extra Commands:'))
        self.text_ctrl_rom_folder_text = wx.StaticText(self.box_rom_folder, label=_('ROM Folder:'))
        self.text_ctrl_valid_extension_text = wx.StaticText(self.box_rom_folder, label=_('Valid Extensions:'))
        self.checkbox_enabled.Bind(wx.EVT_CHECKBOX, self.on_control_changed)
        self.checkbox_include_extension.Bind(wx.EVT_CHECKBOX, self.on_control_changed)
        self.checkbox_include_folder_path.Bind(wx.EVT_CHECKBOX, self.on_control_changed)


    def _load_xml_data(self) -> bool:
        """Read non_mame_emulators.xml.  Returns False (having told the user) if the file can't be read."""
        # --------------------------------------------------------------------------------------------------------------
        # Check that we have a valid path to the XML file
        if not os.path.exists(os.path.join(data_dir(), 'non_mame_emulators.xml')):
            wx.MessageBox(_('Unable to find the non_mame_emulators.xml file.  This should be in the same folder as the'
                            ' pfeMAME files.  You can create a new version from here by adding at least one alternate'
                            ' emulation engine entry.'),
                          _('ERROR'),
                          wx.OK | wx.ICON_ERROR
                          )

        # --------------------------------------------------------------------------------------------------------------
        # Read the XML file into memory
        self.alternate_emulation_engines, error = load_other_emulators_detail(self.path_to_me)

        if error:
            wx.MessageBox(_('There is an error in the non_mame_emulators.xml file.  Please check the file manually or'
                            ' delete the file to allow it to be rebuilt safely.  You can also restore it from a backup'
                            ' if you have one.'),
                          _('ERROR'),
                          wx.OK | wx.ICON_ERROR
                         )
            return False

        self.emulator_list = self.create_emulator_name_list()  # Make a list of emulator names
        self.emulator_list_index = 0
        return True


    # ------------------------------------------------------------------------------------------------------------------
    # Set the fonts
    def _set_the_fonts(self):
        set_font(self.checkbox_include_folder_path)
        set_font(self.checkbox_enabled)
        set_font(self.checkbox_include_extension)
        set_font(self.text_ctrl_description_text)
        set_font(self.text_ctrl_emulator_path_text)
        set_font(self.text_ctrl_extra_commands_text)
        set_font(self.text_ctrl_rom_folder_text)
        set_font(self.text_ctrl_valid_extension_text)

    def _create_sizers_add_controls(self, panel):
        self.emulator_list_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.emulator_list_sizer.Add(self.btn_left)
        self.emulator_list_sizer.Add(self.emulator_selector, flag=wx.ALIGN_CENTER_VERTICAL | wx.LEFT | wx.RIGHT,
                                     border=4)
        self.emulator_list_sizer.Add(self.btn_right)
        self.emulator_list_sizer.Add(wx.Size(50, 1))

        # Setup the main sizers
        sizer = wx.BoxSizer(wx.VERTICAL)
        top_sizer = wx.BoxSizer(wx.HORIZONTAL)
        sizer_horizontal = wx.BoxSizer(wx.HORIZONTAL)
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)

        # --------------------------------------------------
        # LEFT SIDE: ROM List Section with GroupBox
        # --------------------------------------------------
        rom_list_sizer = wx.StaticBoxSizer(self.box_rom_entries, wx.VERTICAL)

        # ROM entry buttons
        sizer_rom_entry_buttons = wx.BoxSizer(wx.HORIZONTAL)
        self.button_add_rom_entry = build_one_button(self.box_rom_entries,
                                                     _('ADD NEW ROM ENTRY'),
                                                     self.on_add_rom_entry,
                                                     horizontal_size=BUTTON_WIDTH_WIDE
                                                     )
        sizer_rom_entry_buttons.Add(self.button_add_rom_entry, 0, wx.RIGHT, 5)
        self.button_auto_add = build_one_button(self.box_rom_entries,
                                                _('AUTO SCAN ROM FOLDER'),
                                                self.on_add_rom_entry_auto,
                                                tooltip=_('Add the ROM files in the ROM folder that have one of the '
                                                          'valid extensions.  Existing entries and their names are '
                                                          'kept.  Not available when the ROM folder is \'Default\', '
                                                          'as that would add every MAME ROM to this emulator.'),
                                                horizontal_size=BUTTON_WIDTH_WIDE
                                                )
        sizer_rom_entry_buttons.Add(self.button_auto_add)

        self.rom_search = wx.SearchCtrl(self.box_rom_entries, size=wx.Size(-1, -1))
        self.rom_search.ShowCancelButton(True)
        self.rom_search.SetDescriptiveText(_('Search ROMs'))
        self.rom_search.SetToolTip(wx.ToolTip(_('Only show the ROMs whose name or file name contains this text')))
        self.rom_search.Bind(wx.EVT_TEXT, self.on_rom_search)
        self.rom_search.Bind(wx.EVT_SEARCHCTRL_CANCEL_BTN, lambda event: self.rom_search.SetValue(''))

        self.button_fill_rom_names = build_one_button(self.box_rom_entries,
                                                      _('FILL ROM NAMES'),
                                                      self.on_fill_rom_names,
                                                      tooltip=_('Give the unnamed (___) ROMs the names MAME uses for '
                                                                'them.  Names you have entered are kept.'),
                                                      horizontal_size=BUTTON_WIDTH_STANDARD
                                                      )
        sizer_search = wx.BoxSizer(wx.HORIZONTAL)
        sizer_search.Add(self.rom_search, 1, wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 5)
        sizer_search.Add(self.button_fill_rom_names, 0, wx.ALIGN_CENTER_VERTICAL)

        # Add buttons, search and list to the grouped box
        rom_list_sizer.Add(sizer_rom_entry_buttons, 0, wx.ALL | wx.EXPAND, 5)
        rom_list_sizer.Add(sizer_search, 0, wx.LEFT | wx.RIGHT | wx.EXPAND, 5)
        rom_list_sizer.Add(self.list_control, 1, wx.ALL | wx.EXPAND, 5)

        # --------------------------------------------------
        # RIGHT SIDE: Emulator Settings with GroupBoxes
        # --------------------------------------------------
        right_side_sizer = wx.BoxSizer(wx.VERTICAL)

        # Group 1: Basic Configuration
        basic_config_sizer = wx.StaticBoxSizer(self.box_basic_config, wx.VERTICAL)

        basic_grid = wx.FlexGridSizer(7, 1, 5, 5)
        basic_grid.AddMany([
            self.checkbox_enabled,
            self.text_ctrl_description_text,
            self.text_ctrl_description,
            self.text_ctrl_emulator_path_text,
            self.text_ctrl_emulator_path,
            self.text_ctrl_extra_commands_text,
            self.text_ctrl_extra_commands,
        ])
        basic_config_sizer.Add(basic_grid, 0, wx.ALL | wx.EXPAND, 5)

        # Group 2: ROM Folder Configuration
        rom_folder_sizer = wx.StaticBoxSizer(self.box_rom_folder, wx.VERTICAL)

        rom_folder_grid = wx.FlexGridSizer(5, 1, 5, 5)
        rom_folder_grid.AddMany([
            self.button_default_rom_folder,
            self.text_ctrl_rom_folder_text,
            self.text_ctrl_rom_folder,
            self.text_ctrl_valid_extension_text,
            self.text_ctrl_valid_extension,
        ])
        rom_folder_sizer.Add(rom_folder_grid, 0, wx.ALL | wx.EXPAND, 5)

        # Group 3: Command Line Options
        cmdline_sizer = wx.StaticBoxSizer(self.box_command_line, wx.VERTICAL)

        cmdline_grid = wx.FlexGridSizer(2, 1, 5, 5)
        cmdline_grid.AddMany([
            self.checkbox_include_extension,
            self.checkbox_include_folder_path,
        ])
        cmdline_sizer.Add(cmdline_grid, 0, wx.ALL | wx.EXPAND, 5)

        # Group 4: Actions
        actions_sizer = wx.StaticBoxSizer(self.box_actions, wx.VERTICAL)

        self.button_set_defaults = build_one_button(self.box_actions,
                                                    _('SET DEFAULTS'),
                                                    self.on_set_defaults,
                                                    tooltip=_('Set the typical default values for this emulator '
                                                              'engine.'),
                                                    horizontal_size=BUTTON_WIDTH_STANDARD
                                                    )
        actions_sizer.Add(self.button_set_defaults, 0, wx.ALL | wx.EXPAND, 3)

        self.update_xml_button = build_one_button(self.box_actions,
                                                  _('UPDATE XML FILE'),
                                                  self.on_update_xml,
                                                  tooltip=_(
                                                      'Update the XML file with any changes you have made.  You need to '
                                                      'do this manually as the changes are not automatically stored.'),
                                                  horizontal_size=BUTTON_WIDTH_STANDARD
                                                  )
        actions_sizer.Add(self.update_xml_button, 0, wx.ALL | wx.EXPAND, 3)

        self.button_test_rom = build_one_button(self.box_actions,
                                                _('TEST ROM'),
                                                self.test_run,
                                                tooltip=_('Test the selected ROM to see if your configuration is '
                                                          'correct'),
                                                horizontal_size=BUTTON_WIDTH_STANDARD
                                                )
        actions_sizer.Add(self.button_test_rom, 0, wx.ALL | wx.EXPAND, 3)

        self.button_rename_emulator = build_one_button(self.box_actions,
                                                       _('RENAME THIS ENGINE'),
                                                       self.on_rename_emulator,
                                                       tooltip=_('Change the name of this alternate engine, keeping '
                                                                 'its settings and ROMs'),
                                                       horizontal_size=BUTTON_WIDTH_STANDARD
                                                       )
        actions_sizer.Add(self.button_rename_emulator, 0, wx.ALL | wx.EXPAND, 3)

        self.button_duplicate_emulator = build_one_button(self.box_actions,
                                                          _('DUPLICATE THIS ENGINE'),
                                                          self.on_duplicate_emulator,
                                                          tooltip=_('Make a copy of this alternate engine, with its '
                                                                    'settings and ROMs.  The copy starts disabled.'),
                                                          horizontal_size=BUTTON_WIDTH_STANDARD
                                                          )
        actions_sizer.Add(self.button_duplicate_emulator, 0, wx.ALL | wx.EXPAND, 3)

        self.button_delete_emulator = build_one_button(self.box_actions,
                                                       _('DELETE THIS ENGINE'),
                                                       self.on_delete_emulator,
                                                       tooltip=_('Delete this alternate engine entry and all '
                                                                 'associated data'),
                                                       horizontal_size=BUTTON_WIDTH_STANDARD
                                                       )
        actions_sizer.Add(self.button_delete_emulator, 0, wx.ALL | wx.EXPAND, 3)

        # Add all grouped sections to right side
        right_side_sizer.Add(basic_config_sizer, 0, wx.ALL | wx.EXPAND, 3)
        right_side_sizer.Add(rom_folder_sizer, 0, wx.ALL | wx.EXPAND, 3)
        right_side_sizer.Add(cmdline_sizer, 0, wx.ALL | wx.EXPAND, 3)
        right_side_sizer.Add(actions_sizer, 0, wx.ALL | wx.EXPAND, 3)

        # --------------------------------------------------
        # Combine left and right sides
        # --------------------------------------------------
        sizer_horizontal.Add(rom_list_sizer, 1, wx.ALL | wx.EXPAND, 5)
        sizer_horizontal.Add(right_side_sizer, 0, wx.ALL | wx.EXPAND, 5)

        # --------------------------------------------------
        # Build main window layout
        # --------------------------------------------------
        sizer.Add(self.info_text, 0, wx.ALL | wx.EXPAND | wx.ALIGN_LEFT, 2)
        sizer.Add(self.emulator_list_sizer, 0, wx.EXPAND, 2)
        sizer.AddSpacer(4)

        tooltip = _(
            'This allows you to create a new alternate emulator (i.e. something other than MAME).  Once you '
            'have created it, you will need to review the settings below and then assign the ROMs that relate '
            'to this alternate emulation system.')
        btn = build_one_button(panel,
                               _('CREATE NEW EMULATOR ENTRY'),
                               self.on_create_new_emulator,
                               tooltip,
                               )
        sizer.Add(btn, 0, wx.EXPAND, 2)
        sizer.AddSpacer(4)

        line = wx.StaticLine(panel)
        sizer.Add(line, flag=wx.EXPAND | wx.BOTTOM, border=1)
        sizer.Add(sizer_horizontal, 1, wx.EXPAND)

        # OK button at bottom
        btn = build_one_button(panel, _('OK'), self.on_ok)
        button_sizer.Add(btn, 0, wx.ALL | wx.ALIGN_CENTER)

        line = wx.StaticLine(panel)
        sizer.Add(line, flag=wx.EXPAND | wx.BOTTOM, border=1)
        sizer.Add(button_sizer, 0, wx.ALL | wx.ALIGN_RIGHT, 2)
        top_sizer.Add(sizer, 1, wx.ALL | wx.EXPAND, 2)

        # Set the sizer
        panel.SetSizer(top_sizer)
        top_sizer.Fit(self)
        top_sizer.Layout()

    # ------------------------------------------------------------------------------------------------------------------
    # Add tool tips for the controls
    def _set_up_tool_tips(self):

        tooltips = {
            self.text_ctrl_emulator_path: _('This is the full path to the alternate emulator executable file'),
            self.text_ctrl_rom_folder: _('If the emulator has ROMs located in a folder that is not the \'Default\' '
                                         'MAME ROM folder, then you need to define that folder here.  If the ROM '
                                         'can be run by MAME natively then you don\'t need to set this.  AUTO SCAN '
                                         'ROM FOLDER only works with a folder of the emulator\'s own, not '
                                         '\'Default\'.'),
            self.text_ctrl_valid_extension: _('You must list all valid file extensions that can be run by this '
                                              'emulator.  Do not include any dots.  If multiple extensions then '
                                              'separate by a space.'),
            self.text_ctrl_description: _('The category that ROMs in this emulator\'s own ROM folder are listed under '
                                          'in the ROM list (not used when the ROM folder is \'Default\').'),
            self.text_ctrl_extra_commands: _('List any commands to be passed to the emulator in the same format '
                                             'that you would use from the command line.  Separate multiple commands'
                                             ' with a space.  The ROM is added after them, unless you put {rom} '
                                             'where it should go (e.g. -play {rom} -exit).'),
            self.checkbox_enabled: _('Select this to enable / disable this emulator'),
            self.checkbox_include_folder_path: _('If the folder path needs to be given at the command line for the '
                                                 'emulator then check this box.  This will generally depend upon '
                                                 'whether or not the ROMs folder for this emulator is already '
                                                 'defined in it\'s own INI file.'),
            self.checkbox_include_extension: _('Check this box if the emulator needs the file extension to be '
                                               'given with the ROM name')
        }

        for checkbox, tip in tooltips.items():
            checkbox.SetToolTip(wx.ToolTip(tip))

    # ------------------------------------------------------------------------------------------------------------------
    # Setup the list control which holds the ROMs associated with the engine
    def _setup_list_control(self, panel) -> None:
        """Create and configure the ROM list control"""
        self.list_control = ulc.UltimateListCtrl(self.box_rom_entries,
                                                 size=wx.Size(501, 500),
                                                 agwStyle=wx.LC_REPORT |
                                                          ulc.ULC_HRULES)

        self.list_control.Bind(ulc.EVT_LIST_ITEM_ACTIVATED, self.on_double_click_list)
        self.list_control.Bind(wx.EVT_RIGHT_DOWN, self.on_right_click_list)
        self.list_control.Bind(ulc.EVT_LIST_COL_CLICK, self.on_rom_column_click)
        self.list_control.Bind(ulc.EVT_LIST_KEY_DOWN, self.on_rom_list_key)
        self.list_control.SetBackgroundColour(self.application_colors['window_background'])

        # Create the columns
        bold_font = wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT)
        bold_font.SetWeight(wx.BOLD)
        bold_font.SetPointSize(10)
        info = ulc.UltimateListItem()
        info._mask = wx.LIST_MASK_TEXT | wx.LIST_MASK_WIDTH | wx.LIST_MASK_FORMAT | ulc.ULC_MASK_FONT

        def add_one_column(column: int, text: str, width: int, font: wx.Font, position_format: int) -> None:
            info._text = text
            info._width = width
            info._font = font
            info._format = position_format
            custom_render = UltimateHeaderRenderer(self.application_colors)
            info.SetCustomRenderer(custom_render)
            self.list_control.InsertColumnInfo(column, info)

        self.list_control.SetToolTip(wx.ToolTip(_('Click a column heading to sort by it.  Ctrl or Shift click to '
                                                  'select several ROMs, then press Delete to delete them.')))
        columns_list = [
            (COL_ROM_NAME, _('ROM Name'), 330, bold_font, wx.LIST_FORMAT_LEFT),
            (COL_FILE_NAME, _('ROM File Name (No Extn)'), 170, bold_font, wx.LIST_FORMAT_LEFT),
        ]
        for line in columns_list:
            add_one_column(*line)

    # ------------------------------------------------------------------------------------------------------------------
    # Handle the ok event
    def on_ok(self, _event) -> None:
        self.on_close(-1)

    # ------------------------------------------------------------------------------------------------------------------
    # Capture a key event on the panel and look for the escape key to close the window
    def on_key_up_event(self, event) -> None:
        on_key_up(event, self)

    # --------------------------------------------------------------------------------------------------------------
    def on_set_defaults(self, _event) -> None:
        """
        Display a pop-up window allowing you to select an emulator engine type from which it will set recommended
        default values.
        """
        # Parse the XML file.  It ships alongside pfeMAME, so look for it there rather than in the working folder.
        try:
            defaults = load_default_emulator_settings(os.path.join(self.path_to_me, 'non_mame_defaults.xml'))
        except (ET.ParseError, OSError):
            wx.MessageBox(_('Unable to read non_mame_defaults.xml file.'),
                          _('ERROR'),
                          wx.OK | wx.ICON_ERROR)
            return

        # Get the list of emulator names from the XML file
        emulator_names = list(defaults)

        if not emulator_names:
            wx.MessageBox(_('No emulators found in defaults file.'),
                          _('ERROR'),
                          wx.OK | wx.ICON_ERROR)
            return

        # Invoke the custom dialog to allow the values to be changed
        dlg = DefaultSettings(emulator_names)
        resource = dlg.ShowModal()
        if resource != wx.ID_OK:
            dlg.Destroy()
            self.Refresh()
            return

        # Update the controls based on the selection made
        emulator_name = dlg.control_selection.GetValue()
        dlg.Destroy()
        if emulator_name == '':
            self.Refresh()
            return

        # Find the emulator data by name
        emulator = defaults.get(emulator_name)

        if emulator is None:
            wx.MessageBox(_('Selected emulator not found in defaults file.'),
                          _('ERROR'),
                          wx.OK | wx.ICON_ERROR)
            return

        # Pull the emulator data out for the one selected
        valid_extensions = emulator.get('validExtensions', '')
        include_extension = emulator.get('includeExtension', 'False')
        include_path = emulator.get('includePath', 'False')
        default_path = emulator.get('defaultPath', '')
        extra_commands = emulator.get('extraCommands', '')

        # Set the controls values based on the data retrieved
        if default_path == 'Default':
            self.text_ctrl_rom_folder.SetPath('Default')
        elif self.text_ctrl_rom_folder.GetPath() == 'Default':
            # This emulator needs a ROM folder of its own: clear 'Default' so one is chosen (a folder already chosen
            # is kept)
            self.text_ctrl_rom_folder.SetPath('')

        if extra_commands != 'None':
            self.text_ctrl_extra_commands.SetValue(extra_commands)
        else:
            self.text_ctrl_extra_commands.SetValue('')

        self.text_ctrl_valid_extension.SetValue(valid_extensions)
        self.checkbox_include_extension.SetValue(include_extension == 'True')
        self.checkbox_include_folder_path.SetValue(include_path == 'True')

        # Update the values in the list variable
        self.on_control_changed(-1)

        self.Refresh()

    # ------------------------------------------------------------------------------------------------------------------
    # Helper function to remove emulator entry
    def _remove_emulator_entry(self, emulator: str) -> list[list]:
        return [line for line in self.alternate_emulation_engines if line[EmulatorFields.NAME] != emulator]

    # ------------------------------------------------------------------------------------------------------------------
    # Delete the currently selected emulator entry
    def on_delete_emulator(self, _event) -> None:
        if not self.emulator_list:  # Nothing to delete (the button is disabled then anyway)
            return

        emulator = self.emulator_list[self.emulator_list_index]
        dlg = wx.MessageDialog(self,
                               _('Are you sure you want to delete {}?').format(emulator),
                               _('Delete Emulator'),
                               style=wx.YES_NO)
        res = dlg.ShowModal()
        dlg.Destroy()
        if res != wx.ID_YES:
            self.Refresh()
            return

        # Remove the emulator from the emulator data
        self.alternate_emulation_engines = self._remove_emulator_entry(emulator)
        self.mark_unsaved_changes()  # Stays set if the file can't be written, so closing still offers to save

        # Remove the emulator from the emulators list and update the count
        self.emulator_list.remove(emulator)
        self.update_emulator_quantity()

        # Show the emulator before the deleted one (or the first), or the empty state if none are left
        self.block_control_changed = True
        if self.emulator_list:
            self.emulator_list_index = max(0, self.emulator_list_index - 1)
            self._show_emulators()
            self.emulator_get_preferences()  # Force the preferences for the selected emulator to be displayed
        else:
            self._show_no_emulators()
        self.block_control_changed = False
        self.enable_emulator_controls()

        # Update the XML file.  The fields on screen aren't checked: the emulator they showed has just been deleted.
        self.on_update_xml(-1, check_fields=False)
        self.Refresh()

    # ------------------------------------------------------------------------------------------------------------------
    # Clear the window down when there are no emulators left
    def _show_no_emulators(self) -> None:
        self.emulator_list_index = 0
        self.text_ctrl_emulator_path.SetPath('')
        self.text_ctrl_rom_folder.SetPath('')
        self.text_ctrl_description.SetValue('')
        self.text_ctrl_extra_commands.SetValue('')
        self.text_ctrl_valid_extension.SetValue('')
        self.checkbox_enabled.SetValue(False)
        self.checkbox_include_extension.SetValue(False)
        self.checkbox_include_folder_path.SetValue(False)
        self._set_rom_entries([])

    # --------------------------------------------------------------------------------------------------------------
    # Load the categories.dat file
    def load_categories(self) -> list[str] | None:
        """The categories for the Description list, or None (having told the user) if categories.dat is missing."""
        categories, categories_missing, _unused = load_categories_file(self.path_to_me)
        if categories_missing:
            wx.MessageBox(_('ERROR:  The categories.dat file does not exist.  Please ensure you '
                            'have refreshed the database and selected some categories.'),
                          _('ERROR'),
                          wx.OK)
            return None
        return categories

    # --------------------------------------------------------------------------------------------------------------
    # Get the list of emulator engine names, in the order they appear in the XML file
    def create_emulator_name_list(self) -> list[str]:
        return emulator_names_in_order(self.alternate_emulation_engines)

    # ------------------------------------------------------------------------------------------------------------------
    # This function allows for the creation of a new emulation engine entry.  If none exist then it will create the
    # first one, otherwise it will create a new one at the end of the list of existing ones.
    def on_create_new_emulator(self, _event) -> None:
        new_emulator_name = self._ask_emulator_name(_('Please enter the name for the new emulation engine'),
                                                    _('New Emulator Name'))
        if new_emulator_name is None:
            return

        # Reset the ROM list to the one entry it must have
        self.create_default_table_entry()

        # Reset the other controls just in case they have any current data
        self.block_control_changed = True
        self.text_ctrl_emulator_path.SetPath('')
        self.text_ctrl_rom_folder.SetPath('')
        self.text_ctrl_description.SetValue('')
        self.text_ctrl_extra_commands.SetValue('')
        self.text_ctrl_valid_extension.SetValue('')
        self.checkbox_enabled.SetValue(False)
        self.checkbox_include_extension.SetValue(False)
        self.checkbox_include_folder_path.SetValue(False)
        self.block_control_changed = False

        # Add the entry to the emulator data list
        rom_name, rom_file_name = PLACEHOLDER_ROM_ENTRY
        self.append_row(self.alternate_emulation_engines, new_emulator_name, rom_name, rom_file_name)

        # Rebuild the list of emulator names
        self.emulator_list = self.create_emulator_name_list()
        self.emulator_list_index = self.emulator_list.index(new_emulator_name)
        self.update_emulator_quantity()
        self.enable_emulator_controls()  # Also shows the new emulator's name
        self.mark_unsaved_changes()  # Not in the XML file until it is saved

    # ------------------------------------------------------------------------------------------------------------------
    # Ask for an emulator name, for a new, renamed or duplicated emulator
    def _ask_emulator_name(self, message: str, title: str, value: str = '', renaming: str = '') -> str | None:
        """
        :param message: What the name is for
        :param title: The pop-up's title
        :param value: The name to start with
        :param renaming: The emulator being renamed, whose own name is allowed (e.g. to change its upper / lower case)

        :returns:
        The name, trimmed, or None if cancelled or not allowed (blank, or already used - ignoring case, so
        'm2emulator' can't be added next to 'M2emulator').  The user has been told why it wasn't allowed.
        """
        dlg = wx.TextEntryDialog(self, message, title, value)
        res = dlg.ShowModal()
        name = dlg.GetValue().strip()
        dlg.Destroy()
        if res != wx.ID_OK:
            return None

        # Make sure the new entry isn't empty
        if name == '':
            wx.MessageBox(_('Please enter a new valid name.'),
                          _('ERROR'),
                          wx.OK | wx.ICON_ERROR
                          )
            return None

        # Make sure the new entry doesn't already exist
        for existing in self.emulator_list:
            if existing.casefold() == name.casefold() and existing != renaming:
                wx.MessageBox(_('The emulator name {} already exists').format(name),
                              _('ERROR'),
                              wx.OK | wx.ICON_ERROR
                              )
                return None
        return name

    # ------------------------------------------------------------------------------------------------------------------
    # Rename the emulator on screen, keeping its settings and ROMs
    def on_rename_emulator(self, _event) -> None:
        if not self.emulator_list:
            return
        old_name = self.emulator_list[self.emulator_list_index]
        new_name = self._ask_emulator_name(_('Please enter the new name for {}').format(old_name),
                                           _('Rename Emulator'), value=old_name, renaming=old_name)
        if new_name is None or new_name == old_name:
            return

        for row in self.alternate_emulation_engines:
            if row[EmulatorFields.NAME] == old_name:
                row[EmulatorFields.NAME] = new_name
        self.emulator_list = self.create_emulator_name_list()
        self.emulator_list_index = self.emulator_list.index(new_name)
        self._show_emulators()
        self.mark_unsaved_changes()

    # ------------------------------------------------------------------------------------------------------------------
    # Copy the emulator on screen, settings and ROMs, to a new emulator.  The copy starts disabled, so the ROMs still
    # run with the original until the copy is changed and enabled.
    def on_duplicate_emulator(self, _event) -> None:
        if not self.emulator_list:
            return
        old_name = self.emulator_list[self.emulator_list_index]
        new_name = self._ask_emulator_name(_('Please enter the name for the copy of {}').format(old_name),
                                           _('Duplicate Emulator'), value=_('{} (copy)').format(old_name))
        if new_name is None:
            return

        copies = [list(row) for row in self.alternate_emulation_engines if row[EmulatorFields.NAME] == old_name]
        for row in copies:
            row[EmulatorFields.NAME] = new_name
            row[EmulatorFields.ENABLED] = False
        self.alternate_emulation_engines.extend(copies)

        self.emulator_list = self.create_emulator_name_list()
        self.emulator_list_index = self.emulator_list.index(new_name)
        self.update_emulator_quantity()
        self.block_control_changed = True
        self._show_emulators()
        self.emulator_get_preferences()  # Show the copy
        self.block_control_changed = False
        self.mark_unsaved_changes()

    # ------------------------------------------------------------------------------------------------------------------
    # Add a new emulator data row to the list provided
    def append_row(self, list_to_append: list, emulator_name: str, rom_name: str, rom_file_name: str) -> None:
        list_to_append.append([emulator_name,
                               self.text_ctrl_emulator_path.GetPath(),
                               self.text_ctrl_rom_folder.GetPath(),
                               self.text_ctrl_description.GetValue(),
                               bool(self.checkbox_enabled.GetValue()),
                               bool(self.checkbox_include_extension.GetValue()),
                               bool(self.checkbox_include_folder_path.GetValue()),
                               self.text_ctrl_extra_commands.GetValue(),
                               self.text_ctrl_valid_extension.GetValue(),
                               rom_name,
                               rom_file_name
                               ])

    # ------------------------------------------------------------------------------------------------------------------
    # Show the number of emulators.  (Taken from the list rather than read back out of the label, which broke in
    # translations without ': ' in them.)
    def update_emulator_quantity(self) -> None:
        self.info_text.SetLabel(_('Number of alternate emulator engines in file: {}').format(len(self.emulator_list)))

    # ------------------------------------------------------------------------------------------------------------------
    # Update the emulator data list based on the variables stored in the list that was read from the XML file
    # in the first place.
    def on_control_changed(self, _event) -> None:
        if not self.startup_complete:
            return

        self.update_auto_scan_button()  # The ROM folder or extensions may have changed

        if self.block_control_changed:
            return

        if not self.emulator_list:  # No emulator to store the change against (the controls are greyed out then)
            return

        # This is where we update an engine that already exists in the XML file.
        # We do this by reading out everything before that entry, then add the selected emulator, and then we
        # add everything that was after that entry.  We do it this way to maintain the order in tbe XML file.
        self.mark_unsaved_changes()

        new_emulation_engine_data = []

        # Get the index of the first match of what has to be updated
        index = next(index for index, row in enumerate(self.alternate_emulation_engines) if
                     row[EmulatorFields.NAME] == self.current_emulator)

        # Create a new list with the matched data removed
        self.alternate_emulation_engines = self._remove_emulator_entry(self.current_emulator)

        # Now create a new list with the data before the match, the new data, and then the data after the match
        # Create the new data
        for rom_name, rom_file_name in self.rom_entries:
            self.append_row(new_emulation_engine_data, self.current_emulator, rom_name, rom_file_name)

        # Build the result
        self.alternate_emulation_engines = self.alternate_emulation_engines[
                                           0:index] + new_emulation_engine_data + self.alternate_emulation_engines[
                                                                                  index:]
        self._show_emulators()  # In case Enabled was changed

    # ------------------------------------------------------------------------------------------------------------------
    # Note there are changes that haven't been saved to the XML file, and show it in the title and UPDATE XML button
    def mark_unsaved_changes(self) -> None:
        self.unsaved_changes = True
        self.SetTitle(_('Alternate Emulators *'))  # Add asterisk
        self.update_xml_button.SetBackgroundColour(wx.Colour(255, 200, 200))
        self.update_xml_button.Refresh()

    # ------------------------------------------------------------------------------------------------------------------
    # Add a new ROM entry to the list control.
    def on_add_rom_entry(self, _event) -> None:
        # Invoke the custom dialog to allow the values to be created
        dlg = RomInfo(rom_name='', rom_file_name='')
        resource = dlg.ShowModal()
        if resource == wx.ID_OK:
            self.rom_entries.append((dlg.text_rom_name.GetValue(), dlg.text_rom_file_name.GetValue()))
            self.rom_search.ChangeValue('')  # So the new entry can be seen
            self._refresh_rom_list(select=[len(self.rom_entries) - 1])

            # Update the values in the list variable
            self.on_control_changed(-1)
        dlg.Destroy()

    # ------------------------------------------------------------------------------------------------------------------
    # Automatically add new ROM entries to the list control
    def on_add_rom_entry_auto(self, _event) -> None:
        """
        Add the ROM files in the ROM folder with one of the valid extensions.
        Existing entries and their names are kept; entries with no matching file can be removed.
        """
        extensions = self.text_ctrl_valid_extension.GetValue().split()
        if not self.emulator_list or not extensions or self.text_ctrl_rom_folder.GetPath() == 'Default':
            return

        found = scan_rom_folders([self.text_ctrl_rom_folder.GetPath()], extensions)
        if not found:  # Leave the list as it is
            wx.MessageBox(
                _('I couldn\'t find any matches for the extension(s) you have listed. '
                  'Please check your extensions are correct and the folder path is right.'),
                _('ERROR FINDING FILES'),
                wx.OK
            )
            return

        existing = list(self.rom_entries)  # All of them, not just those the search is showing
        merged, added, missing = merge_scanned_roms(existing, found, self.get_mame_descriptions())

        removed = 0
        if missing:
            dlg = wx.MessageDialog(self,
                                   _('{} ROM entries have no matching file in the ROM folder.  Would you like to '
                                     'remove them?').format(len(missing)),
                                   _('ROM Files Not Found'),
                                   wx.YES_NO | wx.ICON_QUESTION)
            if dlg.ShowModal() == wx.ID_YES:
                merged = [row for row in merged if row not in missing]
                removed = len(missing)
            dlg.Destroy()

        if added or removed or existing != merged:
            self.rom_entries = merged
            self._refresh_rom_list()
            self.on_control_changed(-1)

        wx.MessageBox(_('ROM entries added: {added}\nROM entries removed: {removed}').format(added=added,
                                                                                             removed=removed),
                      _('Auto Scan ROM Folder'),
                      wx.OK | wx.ICON_INFORMATION)

    # ------------------------------------------------------------------------------------------------------------------
    # Create the default entry (must always be at least one entry) in the ROMs list control
    def create_default_table_entry(self):
        self._set_rom_entries([PLACEHOLDER_ROM_ENTRY])

    # ------------------------------------------------------------------------------------------------------------------
    # Show a different emulator's ROMs, clearing the search and sort
    def _set_rom_entries(self, entries: list[tuple[str, str]]) -> None:
        self.rom_entries = [tuple(entry) for entry in entries]
        self.rom_sort = None
        self.rom_search.ChangeValue('')
        self._refresh_rom_list()

    # ------------------------------------------------------------------------------------------------------------------
    # Fill the list control with the ROM entries the search matches (all of them if there is no search)
    def _refresh_rom_list(self, select: list[int] = ()) -> None:
        """
        :param select: rom_entries to select afterwards (if they are shown)
        """
        text = self.rom_search.GetValue().strip().casefold()
        self.rom_view = [index for index, (rom_name, rom_file_name) in enumerate(self.rom_entries)
                         if not text or text in rom_name.casefold() or text in rom_file_name.casefold()]
        self.list_control.Freeze()
        self.list_control.DeleteAllItems()
        for row, index in enumerate(self.rom_view):
            rom_name, rom_file_name = self.rom_entries[index]
            self.list_control.InsertStringItem(row, rom_name)
            self.list_control.SetStringItem(row, COL_FILE_NAME, rom_file_name)
        self.color_alternate_rows()
        for index in select:
            if index in self.rom_view:
                row = self.rom_view.index(index)
                self.list_control.Select(row)
                self.list_control.EnsureVisible(row)
        self.list_control.Thaw()

    # ------------------------------------------------------------------------------------------------------------------
    # The rom_entries of the rows selected in the list control
    def _selected_entries(self) -> list[int]:
        return [self.rom_view[row] for row in range(self.list_control.GetItemCount())
                if self.list_control.IsSelected(row)]

    # ------------------------------------------------------------------------------------------------------------------
    # MAME's name for each machine, from the machine list saved when the ROM database was built (machines.cache)
    def get_mame_descriptions(self) -> dict[str, str]:
        """MAME machine name -> description; empty if the machine list hasn't been saved yet."""
        if self.mame_descriptions is None:
            cache = rom_database.load_any_machine_cache(os.path.join(data_dir(), rom_database.MACHINE_CACHE_NAME))
            if cache is None:
                return {}  # Try again next time (the database may be built while this window is open)
            self.mame_descriptions = {machine.name: machine.description for machine in cache[1]}
        return self.mame_descriptions

    # ------------------------------------------------------------------------------------------------------------------
    # Give the unnamed ROM entries the names MAME uses for them
    def on_fill_rom_names(self, _event) -> None:
        if not self.emulator_list:
            return
        descriptions = self.get_mame_descriptions()
        if not descriptions:
            wx.MessageBox(_('The MAME machine list could not be found.  Please build the ROM database first, then '
                            'try again.'),
                          _('Fill ROM Names'),
                          wx.OK | wx.ICON_INFORMATION)
            return

        entries, filled, still_unnamed = fill_rom_names(self.rom_entries, descriptions)
        if filled:
            self.rom_entries = entries
            self._refresh_rom_list()
            self.on_control_changed(-1)

        message = _('ROM names filled in: {}').format(filled)
        if still_unnamed:
            message += '\n' + _('ROMs still without a name (not MAME machines): {}').format(still_unnamed)
        wx.MessageBox(message, _('Fill ROM Names'), wx.OK | wx.ICON_INFORMATION)

    # ------------------------------------------------------------------------------------------------------------------
    # Typing in the search box
    def on_rom_search(self, _event) -> None:
        self._refresh_rom_list()

    # ------------------------------------------------------------------------------------------------------------------
    # Clicking a column heading sorts the ROMs by it; clicking it again reverses the order.  This changes the order
    # they are saved in, which makes no difference to how they run.
    def on_rom_column_click(self, event) -> None:
        column = event.GetColumn()
        if column not in (COL_ROM_NAME, COL_FILE_NAME) or not self.emulator_list:
            return
        reverse = self.rom_sort == (column, False)
        selected = [self.rom_entries[index] for index in self._selected_entries()]
        self.rom_entries.sort(key=lambda entry: entry[column].casefold(), reverse=reverse)
        self.rom_sort = (column, reverse)
        self._refresh_rom_list(select=[self.rom_entries.index(entry) for entry in selected])
        self.on_control_changed(-1)

    # ------------------------------------------------------------------------------------------------------------------
    # The Delete key deletes the selected ROMs
    def on_rom_list_key(self, event) -> None:
        if event.GetKeyCode() == wx.WXK_DELETE:
            self.on_delete_selected_roms()
        else:
            event.Skip()

    # ------------------------------------------------------------------------------------------------------------------
    # Warn about likely mistakes in any emulator (see find_setup_problems) and ask whether to save anyway
    def _ok_to_save_despite_problems(self) -> bool:
        problems = find_setup_problems(self.alternate_emulation_engines)
        if not problems:
            return True

        shown = problems[:MAX_PROBLEMS_SHOWN]
        if len(problems) > len(shown):
            shown.append(_('... and {} more.').format(len(problems) - len(shown)))
        dlg = wx.MessageDialog(self,
                               _('Please check the following:') + '\n\n' + '\n'.join(f'- {line}' for line in shown) +
                               '\n\n' + _('Would you like to save anyway?'),
                               _('Possible Problems'),
                               wx.YES_NO | wx.ICON_WARNING)
        res = dlg.ShowModal()
        dlg.Destroy()
        return res == wx.ID_YES

    # ------------------------------------------------------------------------------------------------------------------
    # Check the settings fields for the emulator on screen are filled in, telling the user if not
    def _fields_are_valid(self) -> bool:
        # Check that we have valid entries in the text input fields
        check_list = [
            (_('Emulator Path'), self.text_ctrl_emulator_path),
            (_('Emulator Description'), self.text_ctrl_description),
            (_('Valid Extensions'), self.text_ctrl_valid_extension)
        ]

        def get_control_value(ctrl) -> str:
            """
            Get the value of the control passed to the function and return it
            :param ctrl: Control object
            :returns: Returns a string value of the control contents
            """
            if isinstance(ctrl, (wx.TextCtrl, ModernDropdown)):
                return ctrl.GetValue()
            return ctrl.GetPath()  # File / folder pickers

        # Check the controls to ensure they have a value set
        for label, control in check_list:
            value = get_control_value(control)

            if value == '':
                wx.MessageBox(_('You must have an entry for {}').format(label),
                              _('ERROR'),
                              wx.OK | wx.ICON_ERROR
                             )
                return False

        if '.' in self.text_ctrl_valid_extension.GetValue():
            wx.MessageBox(_('Please remove any dots from the Valid Extensions'),
                          _('ERROR'),
                          wx.OK | wx.ICON_ERROR
                         )
            return False
        return True

    # ------------------------------------------------------------------------------------------------------------------
    # Update the XMl file data based on the variables stored in the list that was read from the XML file
    # in the first place.
    def on_update_xml(self, _event, check_fields: bool = True) -> bool:
        """
        Write the emulator data to non_mame_emulators.xml.  Returns True if the file was written.

        :param check_fields: Check the settings fields on screen are filled in, and warn about likely mistakes in any
                             emulator, first.  Turned off when saving after deleting an emulator, as the fields then
                             belong to the emulator that was deleted.
        """
        if check_fields and self.alternate_emulation_engines:
            if not self._fields_are_valid():
                return False
            if not self._ok_to_save_despite_problems():
                return False

        # Write out the new XML file
        xml_path = os.path.join(data_dir(), EMULATORS_XML_FILE)
        try:
            save_emulators(xml_path, self.alternate_emulation_engines)
        except OSError:
            wx.MessageBox(_('Unable to write the new non_mame_emulators.xml file.  Check file / folder permissions.'),
                          _('ERROR'),
                          wx.OK | wx.ICON_ERROR
                         )
            self.Refresh()
            return False

        wx.MessageBox(_('XML File has been updated'),
                      _('File Updated'),
                      wx.OK | wx.ICON_INFORMATION
                     )
        self.Refresh()

        self.unsaved_changes = False
        self.SetTitle(_('Alternate Emulators'))  # Add asterisk
        self.update_xml_button.SetBackgroundColour(self.application_colors['button_background'])
        self.update_xml_button.Refresh()
        return True


    # ------------------------------------------------------------------------------------------------------------------
    # Process the double click event
    def on_double_click_list(self, event) -> None:
        """Handle double-click on ROM list - opens edit dialog"""
        self.on_edit_rom_entry(event.GetIndex())

    # ------------------------------------------------------------------------------------------------------------------
    # Handle right-click on list control to show context menu
    def on_right_click_list(self, event) -> None:
        """Show context menu when right-clicking on ROM list"""

        # Get the item that was clicked (if any)
        position = event.GetPosition()
        item, flags = self.list_control.HitTest(position)

        if item == wx.NOT_FOUND:
            return  # Clicked on empty space, do nothing

        # Select the item that was right-clicked, unless it is already part of the selection
        if not self.list_control.IsSelected(item):
            for row in range(self.list_control.GetItemCount()):
                if self.list_control.IsSelected(row):
                    self.list_control.Select(row, False)
            self.list_control.Select(item)
        selected = len(self._selected_entries())

        # Create the context menu
        menu = wx.Menu()

        # Add menu items
        edit_item = menu.Append(wx.ID_EDIT, _('Edit ROM Entry...'))
        menu.AppendSeparator()
        delete_item = menu.Append(wx.ID_DELETE, _('Delete ROM Entry') if selected == 1 else
                                  _('Delete {} ROM Entries').format(selected))

        # There must always be at least one entry left
        if selected >= len(self.rom_entries):
            delete_item.Enable(False)

        # Bind menu events to the menu, so they go when it does
        menu.Bind(wx.EVT_MENU, lambda e: self.on_edit_rom_entry(item), edit_item)
        menu.Bind(wx.EVT_MENU, lambda e: self.on_delete_selected_roms(), delete_item)

        # Show the menu
        show_popup_menu(self.list_control, menu)

    # ------------------------------------------------------------------------------------------------------------------
    # Edit a ROM entry (called from context menu)
    def on_edit_rom_entry(self, row: int) -> None:
        """Edit the ROM entry at the specified row of the list control"""
        index = self.rom_view[row]
        rom_name, rom_file_name = self.rom_entries[index]

        # Invoke the custom dialog
        dlg = RomInfo(rom_name, rom_file_name)
        resource = dlg.ShowModal()
        if resource == wx.ID_OK:
            self.rom_entries[index] = (dlg.text_rom_name.GetValue(), dlg.text_rom_file_name.GetValue())
            self._refresh_rom_list(select=[index])

            # Update the values in the list variable
            self.on_control_changed(-1)
        dlg.Destroy()

    # ------------------------------------------------------------------------------------------------------------------
    # Delete the selected ROM entries (from the right-click menu or the Delete key)
    def on_delete_selected_roms(self) -> None:
        selected = set(self._selected_entries())
        if not selected:
            return
        if len(selected) >= len(self.rom_entries):
            wx.MessageBox(_('Sorry but you cannot delete the last row. '
                            'There must always be at least one row.'),
                          _('Cannot Delete Entry'),
                          style=wx.OK)
            return

        dlg = wx.MessageDialog(self,
                               _('Are you sure you want to delete this entry?') if len(selected) == 1 else
                               _('Are you sure you want to delete these {} entries?').format(len(selected)),
                               _('Delete Entry'),
                               style=wx.YES_NO | wx.ICON_QUESTION)
        res = dlg.ShowModal()
        dlg.Destroy()
        if res == wx.ID_YES:
            self.rom_entries = [entry for index, entry in enumerate(self.rom_entries) if index not in selected]
            self._refresh_rom_list()
            self.on_control_changed(-1)
        self.Refresh()

    # ------------------------------------------------------------------------------------------------------------------
    # Set the emulator format up to use the standard ROM folder.
    # All this actually does is changes the ROM folder to 'Default'.
    def on_default_rom_folder(self, _event) -> None:
        self.text_ctrl_rom_folder.SetPath('Default')
        self.on_control_changed(-1)

    # ------------------------------------------------------------------------------------------------------------------
    # Shift to the previous emulator in the list
    def emulators_list_left(self, _event) -> None:
        if self.emulator_list_index > 0:
            self._go_to_emulator(self.emulator_list_index - 1)

    # ------------------------------------------------------------------------------------------------------------------
    # Shift to the next emulator in the list
    def emulators_list_right(self, _event) -> None:
        if self.emulator_list_index < len(self.emulator_list) - 1:
            self._go_to_emulator(self.emulator_list_index + 1)

    # ------------------------------------------------------------------------------------------------------------------
    # Show the emulator at the position given
    def _go_to_emulator(self, index: int) -> None:
        self.block_control_changed = True
        self.emulator_list_index = index
        self._show_emulators()
        self.emulator_get_preferences()  # Force the preferences for the selected emulator to be displayed
        self.block_control_changed = False

    # ------------------------------------------------------------------------------------------------------------------
    # Get the emulator preferences for the currently selected emulator
    def emulator_get_preferences(self) -> None:
        specific_engine_list = [line for line in self.alternate_emulation_engines if
                                line[EmulatorFields.NAME] == self.current_emulator]
        if specific_engine_list:
            # Get the first config (they all share the same settings, just different ROMs)
            config = specific_engine_list[0]

            # Set the preference controls
            self.text_ctrl_description.SetValue(config[EmulatorFields.DESCRIPTION])
            self.text_ctrl_emulator_path.SetPath(config[EmulatorFields.PATH])
            self.text_ctrl_extra_commands.SetValue(config[EmulatorFields.EXTRA_COMMANDS])
            self.text_ctrl_rom_folder.SetPath(config[EmulatorFields.ROM_FOLDER])
            self.text_ctrl_valid_extension.SetValue(config[EmulatorFields.VALID_EXTENSIONS])
            self.checkbox_include_folder_path.SetValue(config[EmulatorFields.INCLUDE_FOLDER_PATH] is True)
            self.checkbox_enabled.SetValue(config[EmulatorFields.ENABLED] is True)
            self.checkbox_include_extension.SetValue(config[EmulatorFields.INCLUDE_EXTENSION] is True)

            # Set the ROMs list
            self._set_rom_entries([(line[EmulatorFields.ROM_NAME], line[EmulatorFields.ROM_FILE_NAME])
                                   for line in specific_engine_list])

        self.update_auto_scan_button()
        self.Refresh()

    # ------------------------------------------------------------------------------------------------------------------
    # Only allow the auto scan if there is an emulator, a ROM folder of its own that exists and some valid extensions.
    # Never for the 'Default' folder: that is MAME's ROM folder, so a scan would add every MAME ROM to this emulator
    # and they would all then run with it instead of MAME.
    def update_auto_scan_button(self) -> None:
        folder = self.text_ctrl_rom_folder.GetPath()
        self.button_auto_add.Enable(bool(self.emulator_list)
                                    and bool(self.text_ctrl_valid_extension.GetValue().split())
                                    and folder != 'Default'
                                    and os.path.isdir(folder))

    # ------------------------------------------------------------------------------------------------------------------
    # Alternate the row colors in the list control
    def color_alternate_rows(self) -> None:
        for index in range(self.list_control.GetItemCount()):
            color = self.application_colors['row_alt_1'] if index % 2 else self.application_colors['row_alt_2']
            self.list_control.SetItemBackgroundColour(index, wx.Colour(color))
        self.list_control.SetTextColour(wx.BLACK)

    # ------------------------------------------------------------------------------------------------------------------
    # Handle the close event and ensure the parent window is given back control
    def on_close(self, event) -> None:
        """
        Close the window: from the OK button, the window's close button or the escape key (event is -1 for the first
        and last).  If there are unsaved changes ask whether to save them first; Cancel, or a save that fails, keeps
        the window open.
        """
        if self.unsaved_changes:
            dlg = wx.MessageDialog(self,
                                   _('You have made some changes that have not been saved to the XML file.  Would '
                                     'you like to save these changes before exiting?'),
                                   _('UNSAVED CHANGES'),
                                   wx.YES_NO | wx.CANCEL | wx.ICON_QUESTION)
            res = dlg.ShowModal()
            dlg.Destroy()
            can_veto = not isinstance(event, wx.CloseEvent) or event.CanVeto()
            if can_veto and (res == wx.ID_CANCEL or (res == wx.ID_YES and not self.on_update_xml(-1))):
                if isinstance(event, wx.CloseEvent):
                    event.Veto()
                return
            if not can_veto and res == wx.ID_YES:
                self.on_update_xml(-1)  # Closing can't be stopped (e.g. system shutdown) so just try to save

        if self.GetParent() is not None:  # Following will only be called if this window is running as a child
            self.GetParent().Enable()
            parent_list = getattr(self.GetParent(), 'list', None)  # The main window's ROM list
            if parent_list is not None:
                parent_list.SetFocus()
        on_closed, self.on_closed = self.on_closed, None  # Only tell the caller once
        self.Destroy()
        if on_closed is not None:
            on_closed()

    # ------------------------------------------------------------------------------------------------------------------
    # Return the rom_name and rom_file_name from the selected row of the list control
    def get_rom_detail(self, row: int) -> tuple[str, str]:
        return (
            self.list_control.GetItem(row, COL_ROM_NAME).GetText(),
            self.list_control.GetItem(row, COL_FILE_NAME).GetText()
        )

    # ------------------------------------------------------------------------------------------------------------------
    # This is test code to allow you to run the selected ROM so that you can test if your configuration is valid
    def test_run(self, _event) -> None:
        current_item = int(self.list_control.GetFirstSelected())  # Get the currently selected line in the ROM list control

        if current_item == -1:  # Only try to get the text if we have a row selected
            wx.MessageBox(_('Please select a ROM to run from the list'),
                          _('ERROR'),
                          style=wx.OK)
            return

        # A disabled emulator isn't used, so the ROM would quietly run in MAME instead
        if not self.checkbox_enabled.GetValue():
            wx.MessageBox(_('This emulator is not enabled, so the ROM would run in MAME instead.  Tick Enabled and '
                            'save your changes to test it with this emulator.'),
                          _('Emulator Not Enabled'),
                          wx.OK | wx.ICON_INFORMATION)
            return

        # The ROM is run the normal way, which reads the emulator settings from the XML file, so offer to save first
        if self.unsaved_changes:
            dlg = wx.MessageDialog(self,
                                   _('TEST ROM uses the settings saved in the XML file.  Would you like to save your '
                                     'changes first?'),
                                   _('UNSAVED CHANGES'),
                                   wx.YES_NO | wx.CANCEL | wx.ICON_QUESTION)
            res = dlg.ShowModal()
            dlg.Destroy()
            if res == wx.ID_CANCEL or (res == wx.ID_YES and not self.on_update_xml(-1)):
                return

        rom_file_name = self.list_control.GetItem(current_item, COL_FILE_NAME).GetText()
        path_executable = iniFile.read_ini_file('path', 'mame_executable')

        rungame.RunGame(self,
                        rom_file_name=rom_file_name,
                        path_executable=path_executable,
                        caller='Normal View',
                        rom_name='',
                        system_file_name='',
                        short_name='',
                        system_folder_name='',
                        folder_mame_ini='',
                        folder_mapping='',
                        suppress_short_name=False,
                        input_playback_or_record='',
                        pb_r_filename='',
                        force_mame=False
                        )


# ----------------------------------------------------------------------------------------------------------------------
# Window for selecting an emulator engine name from a dropdown list
class DefaultSettings(wx.Dialog):
    """
    This is a custom control that creates a popup for you to select an emulator engine name from a dropdown list

    :param names:    A list of names to be displayed in the dropdown

    :returns:    None
    """

    def __init__(self, names: list[str]) -> None:
        wx.Dialog.__init__(self,
                           None,
                           title=_('Default Settings Selection'))

        # --------------------------------------------------------------------------------------------------------------
        self.application_colors = get_application_colors()  # Get the application colours

        self.SetEscapeId(wx.ID_CANCEL)  # Ensure ESC or cancel returns its own value rather than wx.ID_OK

        top_sizer = wx.BoxSizer(wx.VERTICAL)

        self.control_selection = ModernDropdown(self, wx.ID_ANY, '', choices=names, size=wx.Size(200, 25))

        ok_button = wx.Button(self, wx.ID_OK)

        line = wx.StaticLine(self)  # Add a horizontal line above the button row

        top_sizer.Add(self.control_selection)
        top_sizer.Add(wx.Size(20,20))
        top_sizer.Add(line)
        top_sizer.Add(ok_button, 0, wx.ALL | wx.ALIGN_RIGHT, 2)

        # --------------------------------------------------------------------------------------------------------------
        # Get the window to size automatically based upon sizer requirements
        # and show the sizer
        self.SetSizerAndFit(top_sizer)

        # --------------------------------------------------------------------------------------------------------------
        # Ensure all controls have the system-wide colors
        set_colors(self, self.application_colors)


# ----------------------------------------------------------------------------------------------------------------------
# Window for entering rom name and rom file name
class RomInfo(wx.Dialog):
    """
    This is a custom control that creates a popup for you to enter the ROM name and ROM file name

    :param rom_name:       Currently selected ROM name
    :param rom_file_name:  Currently selected ROM file name

    :returns:    None
    """
    def __init__(self, rom_name: str, rom_file_name: str) -> None:
        wx.Dialog.__init__(self,
                           None,
                           title=_('ROM Info'))

        # --------------------------------------------------------------------------------------------------------------
        # Get the application colours
        self.application_colors = get_application_colors()

        self.SetEscapeId(wx.ID_CANCEL)  # Ensure ESC or cancel returns its own value rather than wx.ID_OK

        top_sizer = wx.BoxSizer(wx.VERTICAL)
        sizer = wx.FlexGridSizer(2, 2, 5, 5)
        self.text_rom_name = wx.TextCtrl(self, value=rom_name, size=wx.Size(300, -1))
        self.text_rom_file_name = wx.TextCtrl(self, value=rom_file_name, size=wx.Size(300, -1))
        sizer.AddMany([
            wx.StaticText(self, label=_('ROM Name:')),
            self.text_rom_name,
            wx.StaticText(self, label=_('ROM File Name:')),
            self.text_rom_file_name]
        )

        top_sizer.Add(sizer)

        ok_button = build_one_button(self,
                                     _('OK'),
                                     self.on_close,
                                     )

        top_sizer.Add(ok_button, 0, wx.ALL | wx.ALIGN_RIGHT, 2)

        # --------------------------------------------------------------------------------------------------------------
        # Get the window to size automatically based upon sizer requirements
        # and show the sizer
        self.SetSizerAndFit(top_sizer)

        # --------------------------------------------------------------------------------------------------------------
        # Ensure all controls have the system-wide colors
        set_colors(self, self.application_colors)

    def on_close(self, _event):
        self.EndModal(wx.ID_OK)


if __name__ == '__main__':
    app = wx.App()
    # This data is just used for testing purposes
    frame = AlternateEmulators()

    frame.Show()
    app.MainLoop()
