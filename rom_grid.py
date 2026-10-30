#!/usr/bin/env python3

# ----------------------------------------------------------------------------------------------------------------------
# rom_grid.py

"""
The ROMs list grid shown on the main window's ROMs List tab: the column layout, the table model that feeds the grid
from the (filtered) ROMs list rows, the cell renderers (icons, stars, ticks) and the grid control itself.

Split out of pfemame.py.  The index_* constants are the column positions in each ROMs list (mylist) row and are
also the grid column numbers.
"""

import os
import wx
import wx.grid

import functions

_ = functions.set_up_language()

# Define the mylist index locations for the table data
index_rom_name = 0
index_rom_file_name = 1
index_system_program_file_name = 2
index_exists = 3
index_rating = 4
index_number_runs = 5
index_favorite = 6
index_category = 7
index_system_short_name = 8
index_system_folder_name = 9
index_path_media_name = 9 #  This is correct and this column is hidden
index_year = 10
index_manufacturer = 11

# Define the number of columns in the main view list (note that some of these are hidden).  This value needs to be
# updated if I change the amount of data that I want to store / display.
display_columns = 12

# Define column widths
rom_name_col_size = 280
file_name_col_size = 120
system_file_name_col_size = 200
exists_col_size = 50
short_name_col_size = 100
rating_col_size = 100
number_of_runs_col_size = 50
favorite_col_size = 50
category_col_size = 80
path_media_name_col_size = 120
year_col_size = 50
manufacturer_col_size = 140

# The standard width of every column (used when the grid is built and by 'reset column spacing')
DEFAULT_COLUMN_WIDTHS = [
    (index_rom_name,                 rom_name_col_size),
    (index_rom_file_name,            file_name_col_size),
    (index_system_program_file_name, system_file_name_col_size),
    (index_system_short_name,        short_name_col_size),
    (index_exists,                   exists_col_size),
    (index_rating,                   rating_col_size),
    (index_number_runs,              number_of_runs_col_size),
    (index_favorite,                 favorite_col_size),
    (index_category,                 category_col_size),
    (index_path_media_name,          path_media_name_col_size),
    (index_year,                     year_col_size),
    (index_manufacturer,             manufacturer_col_size),
]

# Columns holding numbers - sorted as numbers rather than text (so 2 comes before 10)
NUMERIC_COLUMNS = {index_exists, index_rating, index_number_runs, index_favorite}

path_to_me = functions.path_to_me()     # Where the images folder (stars, ticks) is


# ------------------------------------------------------------------------------------------------------------------
# Data model for the ROM list grid

class RomTableBase(wx.grid.GridTableBase):
    def __init__(self, application_colors: dict, pref_highlight_missing: str):
        super().__init__()
        self._rows: list = []
        self._app_colors = application_colors
        self._highlight_missing = (pref_highlight_missing == 'True')
        self._col_labels: dict = {}     # only columns explicitly set land here, see GetColLabelValue
        self._attr_even = self._make_attr('row_alt_2')
        self._attr_odd = self._make_attr('row_alt_1')
        self._attr_missing = wx.grid.GridCellAttr()
        self._attr_missing.SetBackgroundColour(wx.Colour(application_colors['missing_game']))
        self._attr_missing.SetTextColour(wx.Colour(application_colors.get('text', '#000000')))

    def _make_attr(self, color_key: str) -> wx.grid.GridCellAttr:
        attr = wx.grid.GridCellAttr()
        attr.SetBackgroundColour(wx.Colour(self._app_colors[color_key]))
        attr.SetTextColour(wx.Colour(self._app_colors.get('text', '#000000')))
        return attr

    def GetNumberRows(self) -> int:
        return len(self._rows)

    def GetNumberCols(self) -> int:
        return 12

    def GetValue(self, row: int, col: int) -> str:
        if col in (index_rating, index_exists, index_favorite):
            return ''
        if 0 <= row < len(self._rows):
            return self._rows[row][col]
        return ''

    def SetValue(self, row: int, col: int, value: str):
        pass  # read-only grid

    def IsEmptyCell(self, row: int, col: int) -> bool:
        return False

    def _default_col_label(self, col: int) -> str:
        # Order must match index_* constants: 0=rom_name,1=file_name,2=sys_file,
        # 3=exists,4=rating,5=runs,6=favorite,7=category,8=short_name,9=path_media,10=year,11=manufacturer
        labels = [_('ROM Name'), _('File Name'), _('System File'), _('Exists'),
                  _('Rating'), _('Runs'), _('Fav'), _('Category'), _('Short Name'),
                  _('Path Media Name'), _('Year'), _('Manufacturer')]
        return labels[col] if 0 <= col < len(labels) else ''

    def GetColLabelValue(self, col: int) -> str:
        # A label set via SetColLabelValue wins — that is how the sort handler adds its
        # arrow.  Every other column falls through and stays translated live.
        return self._col_labels.get(col) or self._default_col_label(col)

    def SetColLabelValue(self, col: int, value: str):
        # The base class stub discards the value, which silently dropped the sort arrows.
        # Setting a column back to its plain label drops the override so that the label
        # keeps following the application language.
        if value == self._default_col_label(col):
            self._col_labels.pop(col, None)
        else:
            self._col_labels[col] = value

    def GetAttr(self, row: int, col: int, kind) -> wx.grid.GridCellAttr:
        # Delegate Row/Col attr requests to base class so SetColAttr/SetRowAttr work correctly.
        # Our override only handles Cell-level attrs (per-row background colours).
        if kind != wx.grid.GridCellAttr.Cell:
            return super().GetAttr(row, col, kind)

        if not (0 <= row < len(self._rows)):
            return None
        r = self._rows[row]
        if self._highlight_missing and r[index_exists] == '0':
            attr = self._attr_missing.Clone()
        elif row % 2 == 0:
            attr = self._attr_even.Clone()
        else:
            attr = self._attr_odd.Clone()
        if col in (index_exists, index_rating, index_favorite, index_number_runs):
            attr.SetAlignment(wx.ALIGN_CENTRE, wx.ALIGN_CENTRE)
        attr.IncRef()  # Transfer ownership: caller (C++ grid) will DecRef; Python local var also DecRefs
        return attr

    def set_data(self, rows: list) -> None:
        self._rows = rows

    def get_row(self, row: int) -> list:
        return self._rows[row]

    def get_rating(self, row: int) -> int:
        return int(self._rows[row][index_rating]) if 0 <= row < len(self._rows) else 0

    def get_favorite(self, row: int) -> int:
        return int(self._rows[row][index_favorite]) if 0 <= row < len(self._rows) else 0

    def update_highlight_missing(self, value: bool) -> None:
        self._highlight_missing = value

    def get_row_background(self, row: int) -> wx.Colour:
        if not (0 <= row < len(self._rows)):
            return wx.Colour(self._app_colors.get('row_alt_1', '#FFFFFF'))
        r = self._rows[row]
        if self._highlight_missing and r[index_exists] == '0':
            return wx.Colour(self._app_colors['missing_game'])
        if row % 2 == 0:
            return wx.Colour(self._app_colors['row_alt_2'])
        return wx.Colour(self._app_colors['row_alt_1'])


# ------------------------------------------------------------------------------------------------------------------
# Custom cell renderers
class IconCellRenderer(wx.grid.GridCellRenderer):
    def __init__(self, icon_size: int, folders_icons: str, show_icons: bool,
                 icon_cache: dict, table: 'RomTableBase'):
        super().__init__()
        self._size = icon_size
        self._folders_icons = folders_icons
        self._show = show_icons
        self._cache = icon_cache
        self._table = table

    def Draw(self, grid, attr, dc, rect, row, col, isSelected):
        dc.SetClippingRegion(rect)
        try:
            bg = grid.GetSelectionBackground() if isSelected else self._table.get_row_background(row)
            dc.SetBrush(wx.Brush(bg))
            dc.SetPen(wx.TRANSPARENT_PEN)
            dc.DrawRectangle(rect)

            if self._show and 0 <= row < self._table.GetNumberRows():
                rom_file = self._table.get_row(row)[index_rom_file_name]
                bmp = self._get_bitmap(rom_file)
                if bmp and bmp.IsOk():
                    x = rect.x + 2
                    y = rect.y + max(0, (rect.height - bmp.GetHeight()) // 2)
                    dc.DrawBitmap(bmp, x, y, True)

            text = self._table.GetValue(row, col)
            if text:
                fg = grid.GetSelectionForeground() if isSelected else attr.GetTextColour()
                dc.SetTextForeground(fg)
                dc.SetFont(attr.GetFont() if attr.HasFont() else grid.GetDefaultCellFont())
                offset = self._size + 4 if self._show else 2
                text_rect = wx.Rect(rect.x + offset, rect.y, rect.width - offset, rect.height)
                dc.DrawLabel(text, text_rect, wx.ALIGN_CENTER_VERTICAL | wx.ALIGN_LEFT)
        finally:
            dc.DestroyClippingRegion()

    def _get_bitmap(self, rom_file_name: str):
        if rom_file_name in self._cache:
            return self._cache[rom_file_name]
        icon_path = os.path.join(self._folders_icons, f'{rom_file_name}.ico')
        if os.path.isfile(icon_path):
            try:
                bmp = functions.load_and_scale_bitmap(icon_path, self._size, self._size)
                self._cache[rom_file_name] = bmp
                return bmp
            except Exception:
                pass
        self._cache[rom_file_name] = None
        return None

    def GetBestSize(self, grid, attr, dc, row, col) -> wx.Size:
        return wx.Size(self._size + 4, self._size + 2)

    def Clone(self):
        return IconCellRenderer(self._size, self._folders_icons, self._show,
                                self._cache, self._table)


class StarCellRenderer(wx.grid.GridCellRenderer):
    _bitmaps: dict = {}

    def __init__(self, path_to_me_arg: str, icon_size: int, table: 'RomTableBase'):
        super().__init__()
        self._path = path_to_me_arg
        self._size = icon_size
        self._table = table
        self._load_bitmaps()

    def _load_bitmaps(self):
        key = (self._path, self._size)
        if key not in StarCellRenderer._bitmaps:
            bitmaps = [wx.Bitmap.FromRGBA(self._size, self._size, alpha=0)]
            for i in range(1, 6):
                p = os.path.join(self._path, 'images', f'stars_{i}.gif')
                bitmaps.append(wx.Bitmap(p))
            StarCellRenderer._bitmaps[key] = bitmaps
        self._bitmaps_loaded = StarCellRenderer._bitmaps[key]

    def Draw(self, grid, attr, dc, rect, row, col, isSelected):
        dc.SetClippingRegion(rect)
        try:
            bg = grid.GetSelectionBackground() if isSelected else self._table.get_row_background(row)
            dc.SetBrush(wx.Brush(bg))
            dc.SetPen(wx.TRANSPARENT_PEN)
            dc.DrawRectangle(rect)

            if 0 <= row < self._table.GetNumberRows():
                rating = self._table.get_rating(row)
                bmp = self._bitmaps_loaded[min(rating, 5)]
                if bmp and bmp.IsOk():
                    x = rect.x + max(0, (rect.width - bmp.GetWidth()) // 2)
                    y = rect.y + max(0, (rect.height - bmp.GetHeight()) // 2)
                    dc.DrawBitmap(bmp, x, y, True)
        finally:
            dc.DestroyClippingRegion()

    def GetBestSize(self, grid, attr, dc, row, col) -> wx.Size:
        return wx.Size(self._size + 4, self._size + 2)

    def Clone(self):
        return StarCellRenderer(self._path, self._size, self._table)


class TickCrossRenderer(wx.grid.GridCellRenderer):
    _FILENAMES = ['cross.png', 'tick.png', 'tick_w.png']
    _bitmaps: dict = {}

    def __init__(self, path_to_me_arg: str, icon_size: int, col_index: int,
                 table: 'RomTableBase'):
        super().__init__()
        self._path = path_to_me_arg
        self._size = icon_size
        self._col = col_index
        self._table = table
        self._load_bitmaps()

    def _load_bitmaps(self):
        key = (self._path, self._size)
        if key not in TickCrossRenderer._bitmaps:
            bitmaps = []
            for fn in self._FILENAMES:
                p = os.path.join(self._path, 'images', fn)
                bitmaps.append(wx.Bitmap(p))
            TickCrossRenderer._bitmaps[key] = bitmaps
        self._bitmaps_loaded = TickCrossRenderer._bitmaps[key]

    def Draw(self, grid, attr, dc, rect, row, col, isSelected):
        dc.SetClippingRegion(rect)
        try:
            bg = grid.GetSelectionBackground() if isSelected else self._table.get_row_background(row)
            dc.SetBrush(wx.Brush(bg))
            dc.SetPen(wx.TRANSPARENT_PEN)
            dc.DrawRectangle(rect)

            if 0 <= row < self._table.GetNumberRows():
                raw = self._table.get_row(row)[self._col]
                try:
                    value = int(raw)
                except (ValueError, TypeError):
                    value = 0
                value = max(0, min(value, 2))
                bmp = self._bitmaps_loaded[value]
                if bmp and bmp.IsOk():
                    x = rect.x + max(0, (rect.width - bmp.GetWidth()) // 2)
                    y = rect.y + max(0, (rect.height - bmp.GetHeight()) // 2)
                    dc.DrawBitmap(bmp, x, y, True)
        finally:
            dc.DestroyClippingRegion()

    def GetBestSize(self, grid, attr, dc, row, col) -> wx.Size:
        return wx.Size(self._size + 4, self._size + 2)

    def Clone(self):
        return TickCrossRenderer(self._path, self._size, self._col, self._table)


class PlainCellRenderer(wx.grid.GridCellRenderer):
    """Text-only renderer that paints the correct alternating/missing row background."""

    def __init__(self, table: 'RomTableBase'):
        super().__init__()
        self._table = table

    def Draw(self, grid, attr, dc, rect, row, col, isSelected):
        dc.SetClippingRegion(rect)
        try:
            bg = grid.GetSelectionBackground() if isSelected else self._table.get_row_background(row)
            dc.SetBrush(wx.Brush(bg))
            dc.SetPen(wx.TRANSPARENT_PEN)
            dc.DrawRectangle(rect)

            text = self._table.GetValue(row, col)
            if text:
                fg = grid.GetSelectionForeground() if isSelected else attr.GetTextColour()
                dc.SetTextForeground(fg)
                dc.SetFont(attr.GetFont() if attr.HasFont() else grid.GetDefaultCellFont())
                halign, _valign = attr.GetAlignment()
                text_rect = wx.Rect(rect.x + 2, rect.y, rect.width - 4, rect.height)
                dc.DrawLabel(text, text_rect, wx.ALIGN_CENTER_VERTICAL | halign)
        finally:
            dc.DestroyClippingRegion()

    def GetBestSize(self, grid, attr, dc, row, col) -> wx.Size:
        dc.SetFont(attr.GetFont() if attr.HasFont() else grid.GetDefaultCellFont())
        w, h = dc.GetTextExtent(self._table.GetValue(row, col) or ' ')
        return wx.Size(w + 4, h + 2)

    def Clone(self):
        return PlainCellRenderer(self._table)


# ------------------------------------------------------------------------------------------------------------------
# ROM list grid
class RomGrid(wx.grid.Grid):
    def __init__(self,
                 parent: wx.Panel,
                 pref_icon_size: str,
                 pref_show_rom_icons: str,
                 folders_icons: str,
                 pref_highlight_missing: str,
                 application_colors: dict,
                 my_logger):

        wx.grid.Grid.__init__(self, parent, -1, size=wx.Size(-1, 500))

        self.my_logger = my_logger
        self.mylist_filtered = []
        self._icon_cache: dict = {}

        # Keep public attributes with same names as the old VirtualList for external compatibility
        self.pref_icon_size = pref_icon_size
        self.pref_show_rom_icons = pref_show_rom_icons
        self.folders_icons = folders_icons
        self.pref_highlight_missing = pref_highlight_missing

        self.my_logger.info(_('Started building ROM grid.'))

        # Table
        self.table = RomTableBase(application_colors, pref_highlight_missing)
        self.SetTable(self.table, takeOwnership=False)

        # Grid configuration
        self.SetSelectionMode(wx.grid.Grid.GridSelectRows)
        self.EnableEditing(False)
        self.EnableDragRowSize(False)
        self.EnableDragColMove(False)
        self.SetRowLabelSize(0)
        self.SetDefaultRowSize(int(pref_icon_size))

        # Column widths
        for col_idx, width in DEFAULT_COLUMN_WIDTHS:
            self.SetColSize(col_idx, width)

        # Path Media Name is internal data — hide it and donate its space to the visible name columns
        self.HideCol(index_path_media_name)

        # Column header styling
        label_font = wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT)
        label_font.SetWeight(wx.BOLD)
        label_font.SetPointSize(8)
        self.SetLabelFont(label_font)
        self.SetLabelBackgroundColour(wx.Colour(application_colors['control_bar']))
        self.SetLabelTextColour(wx.Colour(application_colors['text']))

        # Grid line color
        self.SetGridLineColour(wx.Colour(application_colors.get('grid_line', '#888888')))

        # Draw the column labels ourselves so the cursor column is not tinted by the selection colour
        functions.style_grid_column_header(self, application_colors)

        # Disable cell-cursor highlight box — row selection is the only visual indicator needed
        self.SetCellHighlightPenWidth(0)
        self.SetCellHighlightROPenWidth(0)

        # Attach custom cell renderers
        self._attach_renderers()

        # Selection colors
        self.SetSelectionBackground(wx.Colour(application_colors.get('selected_row_background', '#3399FF')))
        self.SetSelectionForeground(wx.Colour(application_colors.get('selected_row', '#FFFFFF')))

        # Redistribute expandable columns whenever the grid is resized
        self.Bind(wx.EVT_SIZE, self._on_size)

        self.my_logger.info(_('Completed building ROM grid.'))

    def _attach_renderers(self):
        # Use local variables — do NOT store renderers as instance attributes.
        # When Destroy() is called at app close, wx deletes the C++ grid (and its col-attr
        # renderer refs) before Python GCs these attributes. Keeping Python refs causes a
        # second DecRef on already-freed C++ renderer objects → wxRefCounter assertion.
        # SetRenderer increments the C++ ref count, keeping renderers alive for the grid's
        # lifetime without any Python-side reference needed.
        # All columns need explicit renderers so they paint the correct row background.
        # Custom renderers call get_row_background() directly; PlainCellRenderer does the
        # same for plain-text columns (the default wx renderer ignores the cell attr bg on Windows).
        for col, renderer_factory in [
            (index_rom_name, lambda: IconCellRenderer(
                int(self.pref_icon_size), self.folders_icons,
                self.pref_show_rom_icons == 'True', self._icon_cache, self.table)),

            (index_rating, lambda: StarCellRenderer(
                path_to_me, int(self.pref_icon_size), self.table)),

            (index_exists, lambda: TickCrossRenderer(
                path_to_me, int(self.pref_icon_size), index_exists, self.table)),

            (index_favorite, lambda: TickCrossRenderer(
                path_to_me, int(self.pref_icon_size), index_favorite, self.table)),

            # Plain renderer — NEW INSTANCE EVERY TIME
            (index_rom_file_name, lambda: PlainCellRenderer(self.table)),
            (index_system_program_file_name, lambda: PlainCellRenderer(self.table)),
            (index_number_runs, lambda: PlainCellRenderer(self.table)),
            (index_category, lambda: PlainCellRenderer(self.table)),
            (index_system_short_name, lambda: PlainCellRenderer(self.table)),
            (index_path_media_name, lambda: PlainCellRenderer(self.table)),
            (index_year, lambda: PlainCellRenderer(self.table)),
            (index_manufacturer, lambda: PlainCellRenderer(self.table)),
        ]:
            col_attr = wx.grid.GridCellAttr()
            col_attr.SetRenderer(renderer_factory())  # new instance
            self.SetColAttr(col, col_attr)

    # ------------------------------------------------------------------
    # Column width distribution on window resize

    def _on_size(self, event):
        event.Skip()
        wx.CallAfter(self.distribute_columns)

    def distribute_columns(self):
        """Expand ROM Name and System File equally to fill available grid width.

        All other columns are never touched here so any user manual resize
        is preserved.  ROM Name and System File will not shrink below their
        module-level standard widths.
        """
        try:
            grid_width = self.GetClientSize().width
        except Exception:
            return
        if grid_width <= 0:
            return

        # Fixed columns: use whatever width the user last set (manual or default).
        fixed_cols = [
            index_rom_file_name,
            index_exists,
            index_rating,
            index_number_runs,
            index_favorite,
            index_category,
            index_system_short_name,
            index_year,
            index_manufacturer,
        ]
        fixed_total = sum(self.GetColSize(col) for col in fixed_cols)

        remaining = grid_width - fixed_total

        # A hidden System File column (systems support off) must stay hidden - setting a width shows it again -
        # so ROM Name then gets all the space
        if not self.IsColShown(index_system_program_file_name):
            self.SetColSize(index_rom_name, max(rom_name_col_size, remaining))
            return

        half = remaining // 2
        self.SetColSize(index_rom_name,
                        max(rom_name_col_size, half))
        self.SetColSize(index_system_program_file_name,
                        max(system_file_name_col_size, remaining - half))

    # ------------------------------------------------------------------
    # Thin wrappers — preserve the call conventions used in pfemame.py

    def set_data(self, rows: list) -> None:
        old_count = len(self.mylist_filtered)
        self.mylist_filtered = rows
        self.table.set_data(rows)
        new_count = len(rows)
        if new_count > old_count:
            msg = wx.grid.GridTableMessage(
                self.table, wx.grid.GRIDTABLE_NOTIFY_ROWS_APPENDED,
                new_count - old_count)
            self.ProcessTableMessage(msg)
        elif new_count < old_count:
            msg = wx.grid.GridTableMessage(
                self.table, wx.grid.GRIDTABLE_NOTIFY_ROWS_DELETED,
                new_count, old_count - new_count)
            self.ProcessTableMessage(msg)
        self.ForceRefresh()

    def GetItemCount(self) -> int:
        return self.GetNumberRows()

    def GetFirstSelected(self) -> int:
        rows = self.GetSelectedRows()
        if rows:
            return rows[0]
        cursor = self.GetGridCursorRow()
        return cursor if cursor >= 0 else -1

    def GetFocusedItem(self) -> int:
        return self.GetFirstSelected()

    def Select(self, row: int) -> None:
        if 0 <= row < self.GetNumberRows():
            # Scroll to it first: selecting a row that is off screen makes wx look up every cell between it and the
            # rows on screen (over half a second in a big list).  Select before moving the cursor, as the cursor move
            # runs the main window's ROM selected handler, which reads the selection.
            self.MakeCellVisible(row, 0)
            self.SelectRow(row)
            self.SetGridCursor(row, 0)

    def EnsureVisible(self, row: int) -> None:
        if 0 <= row < self.GetNumberRows():
            self.MakeCellVisible(row, 0)

    def GetCountPerPage(self) -> int:
        row_h = self.GetDefaultRowSize()
        if row_h <= 0:
            return 20
        visible_h = self.GetClientSize().height
        return max(1, visible_h // row_h)

    def SetSelectedRowForegroundColor(self, colour) -> None:
        self.SetSelectionForeground(wx.Colour(colour))

    def SetSelectedRowBackgroundColor(self, colour) -> None:
        self.SetSelectionBackground(wx.Colour(colour))

    def GetColumnCount(self) -> int:
        return self.GetNumberCols()

    def GetColumnWidth(self, col: int) -> int:
        return self.GetColSize(col)

    def SetColumnWidth(self, col: int, width: int) -> None:
        self.SetColSize(col, width)

    def SetColumnShown(self, col: int, shown: bool) -> None:
        if shown:
            self.ShowCol(col)
        else:
            self.HideCol(col)

    def GetColumnLabel(self, col: int) -> str:
        return self.GetColLabelValue(col)

    def SetColumnLabel(self, col: int, text: str) -> None:
        self.SetColLabelValue(col, text)

    def GetItemText(self, row: int, col: int) -> str:
        return self.table.GetValue(row, col)

    def clear_icon_cache(self) -> None:
        self._icon_cache.clear()
        # Recreate icon renderer with updated settings so icons and row size reload correctly
        self.SetDefaultRowSize(int(self.pref_icon_size))
        self._attach_renderers()
        self.ForceRefresh()

    def SetUserLineHeight(self, height: int) -> None:
        self.SetDefaultRowSize(height)

    def SendSizeEvent(self) -> None:
        self.ForceRefresh()
