#!/usr/bin/env python3

# ----------------------------------------------------------------------------------------------------------------------
# image_picker_dialog.py

"""
Tiled online-image picker dialog.

Presents the candidate images returned by online_image_search in a scrollable grid of thumbnail tiles.  Thumbnails
are downloaded lazily on a background thread pool so the dialog opens instantly and fills in as previews arrive.

The operator clicks a tile to select it (double-click confirms), then presses 'Use This Image' to accept or
'Cancel'/Escape to abort.  On accept, ShowModal() returns wx.ID_OK and self.selected_candidate holds the chosen
ImageCandidate; otherwise it returns wx.ID_CANCEL and self.selected_candidate is None.
"""

import io
from concurrent.futures import ThreadPoolExecutor

import wx

import functions
import online_image_search

_ = functions.set_up_language()

# Tile geometry
THUMB_W = 180
THUMB_H = 180
TILE_PAD = 6
SELECTED_COLOUR = wx.Colour(0, 120, 215)      # Highlight border / background for the selected tile
NORMAL_COLOUR = wx.Colour(60, 60, 60)


# ----------------------------------------------------------------------------------------------------------------------
class _ImageTile(wx.Panel):
    """A single clickable thumbnail tile (preview image + caption)."""

    def __init__(self, parent: wx.Window, candidate: online_image_search.ImageCandidate, on_select, on_confirm):
        super().__init__(parent, style=wx.BORDER_SIMPLE)
        self.candidate = candidate
        self._on_select = on_select
        self._on_confirm = on_confirm
        self.selected = False

        self.SetBackgroundColour(NORMAL_COLOUR)

        self.bitmap = wx.StaticBitmap(self, bitmap=self._placeholder_bitmap())

        dims = ''
        if candidate.width and candidate.height:
            dims = f'  ({candidate.width}x{candidate.height})'
        caption = wx.StaticText(self, label=f'{candidate.source}{dims}',
                                style=wx.ST_ELLIPSIZE_END | wx.ALIGN_CENTRE_HORIZONTAL)
        caption.SetForegroundColour(wx.Colour(220, 220, 220))
        caption.Wrap(THUMB_W)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.bitmap, 0, wx.ALL | wx.ALIGN_CENTRE_HORIZONTAL, TILE_PAD)
        sizer.Add(caption, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.ALIGN_CENTRE_HORIZONTAL, TILE_PAD)
        self.SetSizer(sizer)

        # Make the whole tile (and its children) respond to clicks
        for widget in (self, self.bitmap, caption):
            widget.Bind(wx.EVT_LEFT_DOWN, self._handle_click)
            widget.Bind(wx.EVT_LEFT_DCLICK, self._handle_dclick)

    @staticmethod
    def _placeholder_bitmap() -> wx.Bitmap:
        bmp = wx.Bitmap(THUMB_W, THUMB_H)
        dc = wx.MemoryDC(bmp)
        dc.SetBackground(wx.Brush(wx.Colour(40, 40, 40)))
        dc.Clear()
        dc.SetTextForeground(wx.Colour(150, 150, 150))
        text = _('Loading...')
        tw, th = dc.GetTextExtent(text)
        dc.DrawText(text, (THUMB_W - tw) // 2, (THUMB_H - th) // 2)
        del dc
        return bmp

    def set_preview(self, image: wx.Image) -> None:
        """Scale and display a downloaded preview image, preserving aspect ratio."""
        w, h = image.GetWidth(), image.GetHeight()
        if w <= 0 or h <= 0:
            return
        scale = min(THUMB_W / w, THUMB_H / h, 1.0)
        image = image.Scale(max(1, int(w * scale)), max(1, int(h * scale)), wx.IMAGE_QUALITY_HIGH)
        self.bitmap.SetBitmap(wx.Bitmap(image))
        self.Layout()

    def set_failed(self) -> None:
        bmp = wx.Bitmap(THUMB_W, THUMB_H)
        dc = wx.MemoryDC(bmp)
        dc.SetBackground(wx.Brush(wx.Colour(40, 40, 40)))
        dc.Clear()
        dc.SetTextForeground(wx.Colour(180, 120, 120))
        text = _('No preview')
        tw, th = dc.GetTextExtent(text)
        dc.DrawText(text, (THUMB_W - tw) // 2, (THUMB_H - th) // 2)
        del dc
        self.bitmap.SetBitmap(bmp)

    def set_selected(self, selected: bool) -> None:
        self.selected = selected
        self.SetBackgroundColour(SELECTED_COLOUR if selected else NORMAL_COLOUR)
        self.Refresh()

    def _handle_click(self, _event):
        self._on_select(self)

    def _handle_dclick(self, _event):
        self._on_select(self)
        self._on_confirm()


# ----------------------------------------------------------------------------------------------------------------------
class ImagePickerDialog(wx.Dialog):
    """Modal dialog that lets the operator pick one image from a list of online candidates."""

    def __init__(self, parent: wx.Window, title: str, candidates: list[online_image_search.ImageCandidate]):
        super().__init__(parent, title=title,
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER | wx.MAXIMIZE_BOX,
                         size=wx.Size(820, 640))

        self.selected_candidate: online_image_search.ImageCandidate | None = None
        self._selected_tile: _ImageTile | None = None
        self._tiles: list[_ImageTile] = []
        self._executor = ThreadPoolExecutor(max_workers=6)

        try:
            self.SetIcon(wx.Icon(functions.path_to_me() + '/images/pfemame.ico', wx.BITMAP_TYPE_ICO))
        except Exception:
            pass

        panel = wx.Panel(self)
        panel.SetBackgroundColour(wx.Colour(30, 30, 30))
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        heading = wx.StaticText(panel, label=_('Click an image to select it, then choose "Use This Image". '
                                               'Double-click to use it straight away.'))
        heading.SetForegroundColour(wx.Colour(220, 220, 220))
        main_sizer.Add(heading, 0, wx.ALL, 10)

        # Scrolled area holding the tiles.  This deliberately does NOT use a wx.WrapSizer: a WrapSizer cannot
        # report a height for a given width, so it reports the size of a single tile as its minimum and the
        # scrolled window concludes everything already fits - no scrollbar is ever created and any tile past the
        # first screenful is unreachable.  A wx.GridSizer with an explicit column count reports a real height, so
        # FitInside() produces a correct scroll range; the column count is recalculated whenever the dialog is
        # resized, which reproduces the wrapping behaviour.
        self.scroller = wx.ScrolledWindow(panel, style=wx.VSCROLL)
        self.scroller.SetScrollRate(0, 20)
        self.scroller.SetBackgroundColour(wx.Colour(30, 30, 30))
        self.grid_sizer = wx.GridSizer(1, 0, 0)

        for candidate in candidates:
            tile = _ImageTile(self.scroller, candidate, self._on_tile_selected, self._confirm)
            self._tiles.append(tile)
            self.grid_sizer.Add(tile, 0, wx.ALL, TILE_PAD)

        self.scroller.SetSizer(self.grid_sizer)
        self.scroller.Bind(wx.EVT_SIZE, self._on_scroller_resized)
        main_sizer.Add(self.scroller, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)

        # The wheel is delivered to whichever window is under the pointer, and a tile is not a scrolled window,
        # so without this the wheel does nothing whenever the pointer happens to be over a thumbnail.
        for tile in self._tiles:
            self._bind_mouse_wheel(tile)

        # Buttons
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.ok_button = wx.Button(panel, wx.ID_OK, _('Use This Image'))
        self.ok_button.Disable()
        cancel_button = wx.Button(panel, wx.ID_CANCEL, _('Cancel'))
        button_sizer.AddStretchSpacer()
        button_sizer.Add(self.ok_button, 0, wx.ALL, 6)
        button_sizer.Add(cancel_button, 0, wx.ALL, 6)
        main_sizer.Add(button_sizer, 0, wx.EXPAND)

        panel.SetSizer(main_sizer)

        self.Bind(wx.EVT_BUTTON, self._on_ok, id=wx.ID_OK)
        self.Bind(wx.EVT_CLOSE, self._on_cancel)
        cancel_button.Bind(wx.EVT_BUTTON, self._on_cancel)

        self.CentreOnParent()
        self._reflow_tiles()
        self.scroller.SetFocus()
        self._start_thumbnail_loads()

    # ------------------------------------------------------------------------------------------------------------------
    # Tile layout / scrolling

    def _tile_span(self) -> int:
        """The horizontal space one tile occupies, including its border and the padding around it."""
        if self._tiles:
            return self._tiles[0].GetBestSize().width + (2 * TILE_PAD)
        return THUMB_W + (2 * TILE_PAD)

    def _reflow_tiles(self) -> None:
        """Fit as many tiles across the scrolled area as will go, then resize its scrollable area to suit."""
        if not self._tiles:
            return
        columns = max(1, self.scroller.GetClientSize().width // self._tile_span())
        if columns != self.grid_sizer.GetCols():
            self.grid_sizer.SetCols(columns)
            self.scroller.Layout()
        self.scroller.FitInside()

    def _on_scroller_resized(self, event) -> None:
        event.Skip()
        self._reflow_tiles()

    def _bind_mouse_wheel(self, window: wx.Window) -> None:
        """Forward the mouse wheel from a tile (and everything inside it) to the scrolled area."""
        window.Bind(wx.EVT_MOUSEWHEEL, self._on_mouse_wheel)
        for child in window.GetChildren():
            self._bind_mouse_wheel(child)

    def _on_mouse_wheel(self, event) -> None:
        delta = event.GetWheelDelta() or 120
        lines = event.GetLinesPerAction() or 3
        self.scroller.ScrollLines(-(event.GetWheelRotation() // delta) * lines)

    # ------------------------------------------------------------------------------------------------------------------
    def _start_thumbnail_loads(self) -> None:
        for tile in self._tiles:
            self._executor.submit(self._load_thumbnail, tile)

    def _load_thumbnail(self, tile: _ImageTile) -> None:
        """Runs on a worker thread: download the preview and hand the image back to the GUI thread."""
        try:
            data = online_image_search.download_image(tile.candidate.preview_url())
            image = wx.Image(io.BytesIO(data))
            if not image.IsOk():
                raise IOError('decode failed')
        except Exception:
            wx.CallAfter(self._apply_thumbnail, tile, None)
            return
        wx.CallAfter(self._apply_thumbnail, tile, image)

    def _apply_thumbnail(self, tile: _ImageTile, image) -> None:
        if not self:  # Dialog already destroyed
            return
        if image is None:
            tile.set_failed()
        else:
            tile.set_preview(image)
        self._reflow_tiles()

    # ------------------------------------------------------------------------------------------------------------------
    def _on_tile_selected(self, tile: _ImageTile) -> None:
        if self._selected_tile is not None and self._selected_tile is not tile:
            self._selected_tile.set_selected(False)
        tile.set_selected(True)
        self._selected_tile = tile
        self.selected_candidate = tile.candidate
        self.ok_button.Enable()

    def _confirm(self) -> None:
        if self.selected_candidate is not None:
            self._on_ok(None)

    def _on_ok(self, _event) -> None:
        self._shutdown()
        self.EndModal(wx.ID_OK)

    def _on_cancel(self, _event) -> None:
        self.selected_candidate = None
        self._shutdown()
        self.EndModal(wx.ID_CANCEL)

    def _shutdown(self) -> None:
        # Don't wait on in-flight downloads; the GUI callbacks guard against a destroyed dialog.
        self._executor.shutdown(wait=False)
