#!/usr/bin/env python3

# ----------------------------------------------------------------------------------------------------------------------
# PanelSlots.py

"""
This allows you to set up the interface slots (e.g. option card slots) for systems

The slot tree comes from slot_model.SlotModel (built from MAME's -listxml output).  Every row in the grid is one
slot: the system's own slots first, each followed by the sub-slots of the device plugged into it (indented), to any
depth.  Choosing a device - whether by hand, by loading MAME's defaults, or when reloading a saved ROM INI file -
adds that device's own sub-slots underneath it.
"""

# Import python & wxpython modules
from dataclasses import dataclass, field
import wx
from pubsub import pub
import subprocess


# Import my own modules
import os

import slot_model
import slot_presets
from custom_drop_down import ModernDropdown, EVT_DROPDOWN_SELECTION
from functions import set_up_language, set_colors, get_application_colors, get_platform, get_font_info, build_one_button
from functions import NO_CONSOLE, mame_working_dir, data_dir, find_rom_ini
from custom_text_ctrl import CustomTextCtrl

_ = set_up_language()  # Set up the application language
KEY_TIME_DELAY = 1000  # milliseconds for the keypress timer
_slot_model_cache: dict[tuple[str, str], slot_model.SlotModel] = {}  # Module-level cache: (exe, rom) → model
GRID_COLUMNS = 5        # cb1, cb2, tc (hidden), tc2 (hidden), clear button - preferences.py relies on this layout
SUBSLOT_MARKER = '└─ '  # Drawn in front of sub-slot names (only for show - SlotRow.slot_name holds the real name)


class SlotNameLabel(wx.Window):
    """
    The slot name at the start of a slot row.  A label, not a drop-down: a machine's slots (and the sub-slots a device
    brings) are fixed - only the device in each one is chosen (the row's other drop-down).  Never a TAB stop.
    """

    def __init__(self, parent, label: str, size: wx.Size):
        super().__init__(parent, size=size, style=wx.BORDER_NONE, name='slot_name')
        self.label = label
        self.padding = self.FromDIP(8)          # Where a drop-down starts its text, so the columns line up
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self.on_paint)

    def AcceptsFocus(self):
        return False

    def AcceptsFocusFromKeyboard(self):
        return False

    def SetValue(self, label: str) -> None:
        self.label = label
        self.Refresh()

    def GetValue(self) -> str:
        return self.label

    def on_paint(self, _event):
        dc = wx.AutoBufferedPaintDC(self)
        dc.SetBackground(wx.Brush(self.GetBackgroundColour()))
        dc.Clear()
        dc.SetFont(self.GetFont())
        dc.SetTextForeground(self.GetForegroundColour())
        width, height = self.GetClientSize()
        text = wx.Control.Ellipsize(self.label, dc, wx.ELLIPSIZE_END, width - 2 * self.padding)
        dc.DrawText(text, self.padding, (height - dc.GetTextExtent(text)[1]) // 2)


@dataclass
class SlotRow:
    cb1: SlotNameLabel     # slot name
    cb2: 'ModernDropdown'  # device picker (shows device descriptions)
    tc:  wx.StaticText     # option short name label (hidden - written to the INI)
    tc2: wx.StaticText     # parent path label (hidden - written to the INI)
    btn_clear: wx.Button | None = None  # per-row clear button
    is_subslot: bool = False
    level: int = 0                      # 0 = system slot, 1+ = sub-slot depth
    slot_name: str = ''                 # 'isa3' or ':fdc:0'
    choices: list = field(default_factory=list)   # slot_model.SlotOption list, in cb2 order (after the blank)

    @property
    def parent(self) -> str:
        return self.tc2.GetLabel()

    @property
    def full_path(self) -> str:
        return f'{self.parent}{self.slot_name}' if self.parent else self.slot_name

    def widgets(self) -> tuple:
        return self.cb1, self.cb2, self.tc, self.tc2, self.btn_clear


class PanelSlots(wx.Panel):
    # ------------------------------------------------------------------------------------------------------------------
    def __init__(self,
                 parent,
                 mode: str,
                 content: list[str],
                 rom_file_name: str,
                 path_executable: str):
        wx.Panel.__init__(self, parent=parent)

        self.mode = mode
        self.content = content
        self.rom_file_name = rom_file_name
        self.path_executable = path_executable

        self.startup_complete = False  # Don't allow the control values to be sent until after startup
        self.slot_rows: list[SlotRow] = []  # Direct references to each row of slot controls

        # Set up the initial data needed for this module
        self.get_bios_and_slots_data()

        # --------------------------------------------------------------------------------------------------------------
        # Try to work out the platform
        # This is needed for platform specific preferences
        self.system = get_platform()

        # --------------------------------------------------------------------------------------------------------------
        # Bind the window destroyed event as this is a notebook tab and the way it is closed is through .DeletePage
        # which destroys it.  The processing handler below will perform any necessary cleanup activities like stopping
        # a running keypress timer.
        self.Bind(wx.EVT_WINDOW_DESTROY, self.on_window_destroyed)

        # --------------------------------------------------------------------------------------------------------------
        # Get font information from the INI file
        self.global_font_bold = get_font_info().global_font_bold
        self.global_font_bold_underline = get_font_info().global_font_bold_underline

        # --------------------------------------------------------------------------------------------------------------
        # Set up the manual config data keypress timer.
        # This is used so that the control value is only written after a period of inactivity so that we don't
        # write date for each key press
        self.keypress_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.on_keypress_timer, self.keypress_timer)

        # --------------------------------------------------------------------------------------------------------------
        # Get the application colors
        self.application_colors = get_application_colors()

        # Create the sizers
        self.sizer = wx.BoxSizer(wx.VERTICAL)
        self.static_box_game_pref = wx.StaticBox(self, -1, _('Slots Configuration'))
        self.static_box_game_pref.SetFont(self.global_font_bold)
        self.static_box_game_pref.SetOwnForegroundColour(self.application_colors['text'])
        sizer_game_preferences = wx.StaticBoxSizer(self.static_box_game_pref, wx.VERTICAL)
        sizer_slots_buttons = wx.BoxSizer(wx.HORIZONTAL)
        sizer_bios = wx.BoxSizer(wx.HORIZONTAL)

        # Create the bios options combobox
        self.cbBios = ModernDropdown(self, wx.ID_ANY, '', choices=self.bios_descriptions, size=wx.Size(250, 25))
        self.cbBios.Bind(EVT_DROPDOWN_SELECTION, self.on_control_changed)
        sizer_bios.Add(self.cbBios, 0, wx.ALIGN_CENTRE_VERTICAL, 2)
        sizer_bios.Add(5, 1)
        sizer_bios.Add(wx.StaticText(self, -1, 'Bios', style=wx.ALIGN_LEFT), 0, wx.ALIGN_CENTRE_VERTICAL, 2)

        sizer_game_preferences.Add(sizer_bios)
        sizer_game_preferences.Add(wx.Size(1, 10))

        # Don't show the following section if this ROM has no slot options
        slots_exist = bool(self.model.top_level_slots())
        self.slots_data_length = self.create_slot_controls(slots_exist)  # Create the slot controls

        if slots_exist:
            # Create the slot control buttons
            button = build_one_button(self,
                                    _('Clear All Selections'),
                                    self.on_reset_slots_to_empty,
                                    _('This removes the device from every slot.  Note that MAME uses its own '
                                      'default for any slot that is left empty here.')
                                    )

            sizer_slots_buttons.Add(button, 0, wx.ALL | wx.ALIGN_LEFT, 2)
            sizer_slots_buttons.Add(wx.Size(10, 1))

            button = build_one_button(self,
                                    _('Load MAME Defaults'),
                                    self.on_reset_slots_to_default,
                                    _('This sets the slot controls, including the sub-slots of each default '
                                      'device, to their MAME DEFAULT values found in the systems XML data.'),
                                    )
            sizer_slots_buttons.Add(button, 0, wx.ALL | wx.ALIGN_LEFT, 2)

            # Named slot setups for this system, and the MAME command line for the current one
            sizer_preset_buttons = wx.BoxSizer(wx.HORIZONTAL)
            for label, handler, tip in (
                    (_('Save Preset...'), self.on_save_preset,
                     _('Save the current slot setup under a name, so you can switch back to it later.')),
                    (_('Load Preset...'), self.on_load_preset, _('Replace the current slot setup with a saved one.')),
                    (_('Delete Preset...'), self.on_delete_preset, _('Delete a saved slot setup.')),
                    (_('Copy MAME Command Line'), self.on_copy_command_line,
                     _('Copy the slot and BIOS options as MAME command-line arguments (e.g. for sharing).'))):
                sizer_preset_buttons.Add(build_one_button(self, label, handler, tip), 0, wx.ALL | wx.ALIGN_LEFT, 2)
                sizer_preset_buttons.Add(wx.Size(10, 1))

            sizer_game_preferences.Add(self.slots_scrolled, 1, wx.ALL | wx.EXPAND, 2)
            sizer_game_preferences.Add(sizer_slots_buttons, 0, wx.ALL | wx.ALIGN_LEFT, 2)
            sizer_game_preferences.Add(sizer_preset_buttons, 0, wx.ALL | wx.ALIGN_LEFT, 2)

        sizer_game_preferences.Add(wx.Size(1, 10))

        self.populate_bios_controls()  # Put information into the Bios controls

        # Add the manual config data entry space and populate it based on data in the INI file.
        # This area is for any INI file commands that you want to manually add that are not currently supported
        # by pfeMAME.  There is no error checking, so you can easily cause MAME program issues.
        text = wx.StaticText(self, -1, _('Manual Configuration:'), style=wx.ALIGN_LEFT)
        text.SetFont(self.global_font_bold)
        self.manual_config_control = CustomTextCtrl(self, value='', size=wx.Size(-1, 100), style=wx.TE_MULTILINE)
        self.manual_config_control.SetScrollbarThumbColor(self.application_colors['scrollbar_thumb'])
        self.manual_config_control.SetScrollbarTrackColor(self.application_colors['scrollbar_track'])
        self.manual_config_control.Bind(wx.EVT_TEXT, self.manual_config_timer)
        sizer_game_preferences.Add(text, 0, wx.ALL | wx.ALIGN_LEFT, 2)
        sizer_game_preferences.Add(self.manual_config_control, 0, wx.ALL | wx.EXPAND, 2)
        self.manual_config_control.SetValue(self.set_manual_data())  # Set the manual data control

        self.sizer.Add(sizer_game_preferences, 1, wx.EXPAND)
        self.sizer.Add(wx.Size(1041, 1))  # Help the window to size correctly

        self.SetSizer(self.sizer)
        self.sizer.Fit(self)

        # Ensure all controls have the system-wide colors
        set_colors(self, self.application_colors)

        self.startup_complete = True

    # ------------------------------------------------------------------------------------------------------------------
    # Get the date for the manual data control
    def set_manual_data(self) -> str:
        try:
            start_index = self.content.index('# MANUAL DATA\n') + 1
            end_index = self.content.index('# END OF MANUAL DATA\n')
            lines = (line.strip() for line in self.content[start_index:end_index])
            return '\n'.join(lines).strip()
        except ValueError:
            # No manual data found in INI file
            return ''

    # ------------------------------------------------------------------------------------------------------------------
    def populate_bios_controls(self) -> None:
        # Make sure we don't try matching a BIOS for systems that don't have a BIOS option (There are some).
        # Only proceed if the system has BIOS options
        if not self.bios_names or self.bios_names == ['']:
            return

        default_bios = next((name for name, _description, is_default in self.model.biossets if is_default),
                            self.bios_names[1])

        # Try to find the selected BIOS from the INI content (a line that is exactly 'bios <name>')
        bios_selected = next(
            (line.split()[1] for line in self.content if len(line.split()) > 1 and line.split()[0] == 'bios'),
            default_bios
        )

        # Attempt to find index; fallback to default if not found
        try:
            bios_index = self.bios_names.index(bios_selected)
        except ValueError:
            bios_index = self.bios_names.index(default_bios)

        wx.CallAfter(self.cbBios.SetValue, self.bios_descriptions[bios_index])

    # ------------------------------------------------------------------------------------------------------------------
    def _init_grid_sizer(self):
        """Create a fresh slot grid sizer and add the column headings."""
        if not hasattr(self, 'slots_scrolled'):
            self.slots_scrolled = wx.ScrolledWindow(self, style=wx.VSCROLL)
            self.slots_scrolled.SetScrollRate(0, 10)
            wx.CallAfter(self.get_scrolled_panel_size)
        self.sizer_grid_slots = wx.FlexGridSizer(rows=0, cols=GRID_COLUMNS, hgap=0, vgap=0)
        self.slots_scrolled.SetSizer(self.sizer_grid_slots)
        self.display_heading()

    def get_scrolled_panel_size(self):
        self.slots_scrolled.SetMinSize(wx.Size(self.slots_scrolled.GetSize()))

    # ------------------------------------------------------------------------------------------------------------------
    # Create the slot controls assuming that data exists for them
    def create_slot_controls(self, slots_exist: bool) -> int:
        """Build the slot rows from the ROM INI file if it has a slot section, otherwise from MAME's defaults."""
        self._init_grid_sizer()
        if not slots_exist:
            return 0

        saved = slot_model.parse_ini_slots(self.content)
        if saved is None:
            # No slot data in the INI file - start from MAME's default configuration (with sub-slots)
            self._rebuild_rows(self.model.default_rows())
            self.static_box_game_pref.SetLabel(_('Slots Configuration: Slots Set To Default from XML'))
            return 0

        # Slots that the INI file doesn't mention are shown with MAME's default, as that is what MAME will use
        self._rebuild_rows(self.model.build_rows(saved))
        self.static_box_game_pref.SetLabel(_('Slots Configuration: Slots From INI File'))
        return len(saved)

    # ------------------------------------------------------------------------------------------------------------------
    def get_bios_and_slots_data(self):
        # Extract the slots information and BIOS options for the selected system by using the MAME -listxml command.
        # The XML output for any given system also contains every device that can be plugged into its slots, which
        # is what lets SlotModel follow sub-slots.
        cache_key = (self.path_executable, self.rom_file_name)
        if cache_key not in _slot_model_cache:
            cmd = [self.path_executable, self.rom_file_name, '-listxml', '-nodtd']
            try:
                output = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                                        encoding='utf-8', errors='replace', check=False,
                                        cwd=mame_working_dir(self.path_executable), **NO_CONSOLE).stdout
            except OSError as e:
                output = ''
                pub.sendMessage('log', msg=f'Unable to read slot information from MAME: {e}')
            model = slot_model.SlotModel(output, self.rom_file_name)
            if model.error:
                pub.sendMessage('log', msg=f'Slot information for {self.rom_file_name}: {model.error}')
            else:
                _slot_model_cache[cache_key] = model   # Only cache good results
        else:
            model = _slot_model_cache[cache_key]

        self.model = model
        self.bios_names = [''] + [name for name, _description, _default in model.biossets]
        self.bios_descriptions = [''] + [description for _name, description, _default in model.biossets]

    # A keypress hasn't reset the timer, so it's expired and triggered this event.  This allows the manual config data to
    # now be written to file.
    def on_keypress_timer(self, _event):
        self.on_control_changed(-1)
        self.keypress_timer.Stop()

    # Start the keypress timer.  If it's already running then it will be restarted
    def manual_config_timer(self, _event):
        if self.startup_complete:
            self.keypress_timer.Start(KEY_TIME_DELAY)

    # If this page is being destroyed, then ensure the keypress timer has been stopped otherwise we will end up with
    # a messy crash.
    def on_window_destroyed(self, event):
        event.Skip()
        # Destroy events from child windows (e.g. slot rows being removed) arrive here too - ignore those
        if event.GetEventObject() is not self:
            return
        if hasattr(self, 'keypress_timer'):
            self.keypress_timer.Stop()

    # ---------------------------------------------------------------------------------------------------------------
    # Redraw the slot grid controls
    def redraw_everything(self):
        if not self:
            return
        self.sizer_grid_slots.Layout()
        self.slots_scrolled.FitInside()
        self.sizer.Layout()
        self.Refresh()

    # ------------------------------------------------------------------------------------------------------------------
    # Row building
    def _rebuild_rows(self, model_rows: list[slot_model.SlotRow]) -> None:
        """Replace every slot row with the given model rows."""
        self.Freeze()
        try:
            self.sizer_grid_slots.Clear(delete_windows=True)
            self.slot_rows = []
            self.display_heading()  # re-add headings to the existing sizer (must not create a new one)
            for model_row in model_rows:
                self._add_row(model_row)
        finally:
            self.Thaw()
        wx.CallAfter(self.redraw_everything)

    def _add_row(self, model_row: slot_model.SlotRow, position: int | None = None) -> SlotRow:
        """Create the controls for one slot row, appended or inserted at `position` in self.slot_rows."""
        is_subslot = model_row.level > 0

        if is_subslot:
            # Indent sub-slots by depth, with a '└─ ' marker in front of the name.
            indent = '    ' * (model_row.level - 1) + '  ' + SUBSLOT_MARKER
            cb1_choices = [indent + model_row.slot_name]
        else:
            cb1_choices = [model_row.slot_name]

        cb2_choices = [''] + [self.model.label(option) for option in model_row.choices]
        selected = next((option for option in model_row.choices if option.name == model_row.option), None)

        row = self.create_slots_controls(cb1choices=cb1_choices,
                                         cb1width=190 if is_subslot else 200,
                                         cb1align=wx.ALIGN_RIGHT if is_subslot else wx.ALIGN_LEFT,
                                         cb2choices=cb2_choices,
                                         tc2_value=model_row.parent,
                                         is_subslot=is_subslot,
                                         position=position)
        row.level = model_row.level
        row.slot_name = model_row.slot_name
        row.choices = list(model_row.choices)
        row.cb1.SetValue(cb1_choices[0])
        if selected:
            row.cb2.SetValue(self.model.label(selected))
            row.tc.SetLabel(selected.name)
        if model_row.level > 0:
            row.cb1.SetToolTip(model_row.full_path)
        return row

    def _descendants(self, row: SlotRow) -> list[SlotRow]:
        """The sub-slot rows that belong to `row` (they follow it, with a deeper level)."""
        index = self.slot_rows.index(row)
        result = []
        for other in self.slot_rows[index + 1:]:
            if other.level <= row.level:
                break
            result.append(other)
        return result

    def _remove_rows(self, rows: list[SlotRow]) -> None:
        for dead in rows:
            for widget in dead.widgets():
                if widget is not None:
                    self.sizer_grid_slots.Detach(widget)
                    widget.Destroy()
            self.slot_rows.remove(dead)

    def _set_row_device(self, row: SlotRow, option: slot_model.SlotOption | None) -> None:
        """Change the device in a row: replace its sub-slot rows with the new device's own sub-slots."""
        self.Freeze()
        try:
            self._remove_rows(self._descendants(row))
            row.tc.SetLabel(option.name if option else '')
            if option:
                row.cb2.SetValue(self.model.label(option))
                position = self.slot_rows.index(row) + 1
                for offset, model_row in enumerate(self.model.expand_rows(row.full_path, option, row.level + 1)):
                    self._add_row(model_row, position + offset)
            else:
                row.cb2.SetValue('')
        finally:
            self.Thaw()
        wx.CallAfter(self.redraw_everything)

    # ------------------------------------------------------------------------------------------------------------------
    # This will remove the device from every slot (and so all sub-slots)
    def on_reset_slots_to_empty(self, _event=-1):
        self.static_box_game_pref.SetLabel(_('Slots Configuration: Slots Empty'))
        self._rebuild_rows([slot_model.SlotRow(0, slot.name, '', '', '', slot.options)
                            for slot in self.model.top_level_slots()])
        self.on_control_changed()  # Proces window controls changed

    # ------------------------------------------------------------------------------------------------------------------
    # Set every slot, and the sub-slots of every default device, to MAME's defaults
    def on_reset_slots_to_default(self, _event=-1):
        rows = self.model.default_rows()
        self._rebuild_rows(rows)
        if any(model_row.devname for model_row in rows):
            self.static_box_game_pref.SetLabel(_('Slots Configuration: Slots Set To Default from XML'))
        self.on_control_changed()

    # ------------------------------------------------------------------------------------------------------------------
    # Slot presets (see slot_presets.py)
    def current_selection(self) -> dict:
        """{full slot path: option name ('' = empty)} for every row - the format SlotModel.build_rows takes."""
        return {row.full_path: row.tc.GetLabel() for row in self.slot_rows}

    def current_bios(self) -> str:
        try:
            return self.bios_names[self.bios_descriptions.index(self.cbBios.GetValue())]
        except ValueError:
            return ''

    @staticmethod
    def presets_path() -> str:
        return os.path.join(data_dir(), slot_presets.FILE_NAME)

    def _choose_preset(self, title: str) -> str | None:
        names = slot_presets.names(self.presets_path(), self.rom_file_name)
        if not names:
            wx.MessageBox(_('There are no saved slot presets for {} yet.').format(self.rom_file_name), title,
                          wx.OK | wx.ICON_INFORMATION, self)
            return None
        with wx.SingleChoiceDialog(self, _('Choose a slot preset:'), title, names) as dlg:
            return dlg.GetStringSelection() if dlg.ShowModal() == wx.ID_OK else None

    def on_save_preset(self, _event=None) -> None:
        with wx.TextEntryDialog(self, _('Name for this slot setup:'), _('Save Slot Preset')) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            name = dlg.GetValue().strip()
        if not name:
            return
        if name in slot_presets.names(self.presets_path(), self.rom_file_name):
            if wx.MessageBox(_('Replace the existing preset "{}"?').format(name), _('Save Slot Preset'),
                             wx.YES_NO | wx.ICON_QUESTION, self) != wx.YES:
                return
        slot_presets.save(self.presets_path(), self.rom_file_name, name, self.current_selection(), self.current_bios())
        pub.sendMessage('status', msg=_('Slot preset "{}" saved').format(name))

    def on_load_preset(self, _event=None) -> None:
        name = self._choose_preset(_('Load Slot Preset'))
        preset = slot_presets.get(self.presets_path(), self.rom_file_name, name) if name else None
        if not preset:
            return
        self._rebuild_rows(self.model.build_rows(preset['slots']))
        if preset['bios'] in self.bios_names:
            self.cbBios.SetValue(self.bios_descriptions[self.bios_names.index(preset['bios'])])
        self.static_box_game_pref.SetLabel(_('Slots Configuration: Preset "{}"').format(name))
        self.on_control_changed()       # Writes the ROM INI file

    def on_delete_preset(self, _event=None) -> None:
        name = self._choose_preset(_('Delete Slot Preset'))
        if name and wx.MessageBox(_('Delete the preset "{}"?').format(name), _('Delete Slot Preset'),
                                  wx.YES_NO | wx.ICON_QUESTION, self) == wx.YES:
            slot_presets.delete(self.presets_path(), self.rom_file_name, name)

    def on_copy_command_line(self, _event=None) -> None:
        text = slot_presets.command_line(self.current_selection(), self.current_bios())
        if wx.TheClipboard.Open():
            wx.TheClipboard.SetData(wx.TextDataObject(text))
            wx.TheClipboard.Close()
            pub.sendMessage('status', msg=_('Copied: {}').format(text or _('(no slot options)')))

    # ------------------------------------------------------------------------------------------------------------------
    # Process the event triggered when a device is selected for a slot (system slot or sub-slot)
    def on_select_option(self, event) -> None:
        row = self._row_for(event.GetEventObject())
        if row is None:
            return
        index = row.cb2.GetSelection()
        option = row.choices[index - 1] if 0 < index <= len(row.choices) else None
        self._set_row_device(row, option)
        self.on_control_changed()

    # ------------------------------------------------------------------------------------------------------------------
    # Create a row of slot controls and record them in self.slot_rows.
    def create_slots_controls(
            self,
            cb1choices: list,
            cb1width: int,
            cb1align: int,
            cb2choices: list,
            tc2_value: str,
            is_subslot: bool = False,
            position: int | None = None
    ) -> SlotRow:

        def styled_static_text(label):
            st = wx.StaticText(self.slots_scrolled, label=label, size=wx.Size(200, 25), name='slot_text')
            st.SetBackgroundColour(self.application_colors['text_background'])
            st.SetForegroundColour(self.application_colors['text'])
            return st

        # The slot name is fixed for each row (one row per slot), so it is a label, not a drop-down
        cb1 = SlotNameLabel(self.slots_scrolled, cb1choices[0], wx.Size(cb1width, 25))
        cb1.SetBackgroundColour(self.application_colors['text_background'])
        cb1.SetForegroundColour(self.application_colors['text'])

        cb2 = ModernDropdown(self.slots_scrolled,
                             choices=cb2choices,
                             size=wx.Size(380, 25),
                             style=wx.CB_READONLY,
                             name='slot_combo')
        cb2.SetBackgroundColour(self.application_colors['text_background'])
        cb2.SetForegroundColour(self.application_colors['text'])
        cb2.Bind(EVT_DROPDOWN_SELECTION, self.on_select_option)

        tc = styled_static_text('')
        tc.SetSize((0, 0))
        tc.Hide()
        tc2 = styled_static_text(tc2_value)
        tc2.SetSize((0, 0))
        tc2.Hide()

        # Per-row clear button
        btn_clear = wx.Button(self.slots_scrolled, label='✕', size=wx.Size(25, 25), name='slot_clear')
        btn_clear.SetBackgroundColour(self.application_colors['text_background'])
        btn_clear.SetForegroundColour(self.application_colors['text'])
        btn_clear.SetToolTip(_('Remove the device from this slot'))
        btn_clear.Bind(wx.EVT_BUTTON, self._on_clear_row)

        row = SlotRow(cb1=cb1, cb2=cb2, tc=tc, tc2=tc2, btn_clear=btn_clear, is_subslot=is_subslot)

        controls = [(cb1, cb1align, 2), (cb2, wx.ALIGN_LEFT, 2),
                    (tc, wx.ALIGN_LEFT, 0), (tc2, wx.ALIGN_LEFT, 0),
                    (btn_clear, wx.ALIGN_LEFT, 2)]

        if position is None or position >= len(self.slot_rows):
            for ctrl, align, border in controls:
                self.sizer_grid_slots.Add(ctrl, 0, wx.ALL | align, border)
            self.slot_rows.append(row)
        else:
            # The headings take the first GRID_COLUMNS cells, then GRID_COLUMNS cells per row
            insert_index = GRID_COLUMNS * (position + 1)
            for offset, (ctrl, align, border) in enumerate(controls):
                self.sizer_grid_slots.Insert(insert_index + offset, ctrl, 0, wx.ALL | align, border)
            # Created after every other row, these would come last when tabbing - put them after the row above
            if position > 0:
                cb1.MoveAfterInTabOrder(self.slot_rows[position - 1].btn_clear)
            else:
                cb1.MoveBeforeInTabOrder(self.slot_rows[0].cb1)
            cb2.MoveAfterInTabOrder(cb1)
            btn_clear.MoveAfterInTabOrder(cb2)
            self.slot_rows.insert(position, row)

        return row

    def _row_for(self, ctrl) -> SlotRow | None:
        """Return the SlotRow that contains the given control, or None."""
        return next((r for r in self.slot_rows
                     if r.cb1 is ctrl or r.cb2 is ctrl or r.btn_clear is ctrl), None)

    def _on_clear_row(self, event):
        """Remove the device (and with it any sub-slots) from the row whose clear button was clicked."""
        row = self._row_for(event.GetEventObject())
        if row is None:
            return
        self._set_row_device(row, None)
        self.on_control_changed()

    # ------------------------------------------------------------------------------------------------------------------
    # Display the slots configs headings
    def display_heading(self):
        # Add the column headers to the grid sizer
        visible_headings = [_('Slot Name'), _('Device Name')]
        hidden_headings = [_('Slot Option Name'), _('Slot Parent')]

        for item in visible_headings:
            text = wx.StaticText(self.slots_scrolled, -1, item, style=wx.ALIGN_LEFT, name='slot_heading')
            text.SetFont(self.global_font_bold_underline)
            text.SetForegroundColour(self.application_colors['text'])
            self.sizer_grid_slots.Add(text, 0, wx.ALL | wx.ALIGN_LEFT, 2)

        # Hidden columns – controls still occupy grid cells but take no space
        for item in hidden_headings:
            text = wx.StaticText(self.slots_scrolled, -1, item, size=(0, 0), name='slot_heading')
            text.Hide()
            self.sizer_grid_slots.Add(text, 0, wx.ALL | wx.ALIGN_LEFT, 0)

        # Empty header above the clear-row buttons
        spacer = wx.StaticText(self.slots_scrolled, -1, '', size=(25, 0), name='slot_heading')
        self.sizer_grid_slots.Add(spacer, 0, wx.ALL | wx.ALIGN_LEFT, 2)

    # ------------------------------------------------------------------------------------------------------------------
    # Process the controls change event and write its value out to the INI file
    def on_control_changed(self, _event=-1):
        if self.startup_complete:
            bios_description = self.cbBios.GetValue()
            try:
                bios_name = self.bios_names[self.bios_descriptions.index(bios_description)]
            except ValueError:
                bios_name = ''

            # (slot name, option name, parent) for each row with a device - preferences_model.build_rom_ini writes them
            slot_rows = [(row.slot_name, row.tc.GetLabel(), row.parent) for row in self.slot_rows if row.cb2.GetValue()]
            wx.CallAfter(pub.sendMessage, self.mode + '_set_variable', msg=['slot_rows', slot_rows])
            wx.CallAfter(pub.sendMessage, self.mode + '_set_variable', msg=['manual_config_control_value', self.manual_config_control.GetValue()])
            wx.CallAfter(pub.sendMessage, self.mode + '_force_layout', msg=['test'])
            wx.CallAfter(pub.sendMessage, self.mode + '_set_variable', msg=['pref_bios', str(bios_name)])
            wx.CallAfter(pub.sendMessage, self.mode + '_update_ini')  # Force the INI files to be updated


# ------------------------------------------------------------------------------------------------------------------
# This class allows us to run the Slots module locally for testing purposes
class PanelSlotsLocal(wx.Frame):

    def __init__(self, rom_file_name: str = 'spectrum'):
        style = (wx.SYSTEM_MENU | wx.CAPTION | wx.CLOSE_BOX)
        wx.Frame.__init__(self, wx.GetApp().TopWindow, -1, 'PanelSlots', wx.DefaultPosition, style=style)

        self.SetSize(1300, 600)

        self.Bind(wx.EVT_CLOSE, self.on_close)

        import iniFile
        import os

        system_file_name = ''

        path_to_mame_ini_file = iniFile.read_ini_file('path', 'mame_ini')
        folder_ini = iniFile.get_from_mameini('inipath', path_to_mame_ini_file)
        path_executable = iniFile.read_ini_file('path', 'mame_executable')

        # inipath can list several folders - read the file MAME will use
        file_name = f'{rom_file_name}.ini' if system_file_name == '' else f'{rom_file_name}_system_{system_file_name}.ini'
        filepath = find_rom_ini(file_name, folder_ini, path_executable, path_to_mame_ini_file)
        try:
            with open(filepath, 'r') as fp:
                content = fp.readlines()
        except FileNotFoundError:
            # INI file doesnt exist
            content = []
        self.panel = PanelSlots(self,
                                'game',
                                content,
                                rom_file_name,
                                path_executable)

        self.Show()

    def on_close(self, _event):
        self.Destroy()


if __name__ == '__main__':
    import sys

    app = wx.App()
    PanelSlotsLocal(sys.argv[1] if len(sys.argv) > 1 else 'spectrum')
    app.MainLoop()
