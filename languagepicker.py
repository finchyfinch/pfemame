#!/usr/bin/env python3

# ----------------------------------------------------------------------------------------------------------------------
# languagepicker.py

"""
Presents a row of flag buttons to select the language pfeMAME is shown in.

Each button shows the flag and the language's own name (Deutsch, 日本語 ...) so it can be found whatever language
pfeMAME is in now.  The current language has a coloured border.  The buttons work with the mouse and the keyboard:
Tab / the arrow keys move between them, Enter or Space picks one and Escape closes the window without a change.
"""
# Import python & wxPython modules
import wx
import os

# Import my own modules
import functions
import global_defaults as gd
import iniFile

_ = functions.set_up_language()  # Set up the application language
N_ = gd.N_

FLAG_SIZE = wx.Size(80, 40)
TILE_SIZE = wx.Size(110, 90)
CURRENT_BORDER = 3      # Width of the border round the current language


def contrasting_text_colour(background: wx.Colour) -> wx.Colour:
    """Black or white, whichever is easier to read on background."""
    luminance = 0.299 * background.Red() + 0.587 * background.Green() + 0.114 * background.Blue()
    return wx.BLACK if luminance > 140 else wx.WHITE


# ----------------------------------------------------------------------------------------------------------------------
# One language button.  It is a single window that draws its own flag and name: a flag control inside a panel made
# the panel lose its hover highlight whenever the mouse went over the flag.
class LanguageTile(wx.Window):
    def __init__(self, parent, language: gd.Language, bitmap: wx.Bitmap, current: bool, highlight: wx.Colour,
                 on_choose):
        wx.Window.__init__(self, parent, size=TILE_SIZE, name=language.key)
        self.language = language
        self.bitmap = bitmap
        self.current = current
        self.highlight = wx.Colour(highlight)  # The application colours can be (r, g, b, a) tuples
        self.on_choose = on_choose
        self.hover = False

        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.SetToolTip(_(language.english))
        self.SetMinSize(TILE_SIZE)

        self.Bind(wx.EVT_PAINT, self.on_paint)
        self.Bind(wx.EVT_LEFT_DOWN, lambda _event: self.on_choose(self.language))
        self.Bind(wx.EVT_ENTER_WINDOW, lambda _event: self.set_hover(True))
        self.Bind(wx.EVT_LEAVE_WINDOW, lambda _event: self.set_hover(False))
        self.Bind(wx.EVT_SET_FOCUS, self.on_focus_changed)
        self.Bind(wx.EVT_KILL_FOCUS, self.on_focus_changed)

    def AcceptsFocus(self):
        return True

    def set_hover(self, hover: bool) -> None:
        self.hover = hover
        self.Refresh()

    def on_focus_changed(self, event):
        self.Refresh()
        event.Skip()

    def is_highlighted(self) -> bool:
        return self.hover or self.HasFocus()

    def on_paint(self, _event):
        dc = wx.AutoBufferedPaintDC(self)
        width, height = self.GetClientSize()
        background = self.highlight if self.is_highlighted() else self.GetBackgroundColour()
        dc.SetBackground(wx.Brush(background))
        dc.Clear()

        # The border: a thick one in the system highlight colour round the current language, a thin one otherwise
        if self.current:
            pen = wx.Pen(wx.SystemSettings.GetColour(wx.SYS_COLOUR_HIGHLIGHT), CURRENT_BORDER)
            inset = CURRENT_BORDER // 2
        else:
            pen = wx.Pen(self.GetForegroundColour(), 1)
            inset = 0
        dc.SetPen(pen)
        dc.SetBrush(wx.TRANSPARENT_BRUSH)
        dc.DrawRectangle(inset, inset, width - 2 * inset, height - 2 * inset)

        # The flag, then the language's own name under it
        top = 10
        if self.bitmap.IsOk():
            dc.DrawBitmap(self.bitmap, (width - self.bitmap.GetWidth()) // 2, top, True)
        font = self.GetFont()
        if self.current:
            font = font.Bold()
        dc.SetFont(font)
        dc.SetTextForeground(contrasting_text_colour(background) if self.is_highlighted()
                             else self.GetForegroundColour())
        text_width, text_height = dc.GetTextExtent(self.language.native)
        text_top = top + FLAG_SIZE.height + (height - top - FLAG_SIZE.height - text_height) // 2
        dc.DrawText(self.language.native, (width - text_width) // 2, text_top)


# ----------------------------------------------------------------------------------------------------------------------
# Window for displaying the language picker modal dialog window.
# ShowModal() returns wx.ID_OK when a different language was chosen (it is saved in pfemame.ini and is in .chosen),
# otherwise wx.ID_CANCEL.
class LanguagePicker(wx.Dialog):
    def __init__(self, parent=None):
        if parent is None:
            parent = wx.GetApp().GetTopWindow()
        wx.Dialog.__init__(self, parent, -1, _('Select Language'))

        path_to_me = functions.path_to_me()
        self.application_colors = functions.get_application_colors()
        self.SetIcon(wx.Icon(os.path.join(path_to_me, 'images', 'pfemame.ico'), wx.BITMAP_TYPE_ICO))

        # The language in pfemame.ini.  It is empty the first time pfeMAME runs, which is shown in English.
        self.saved_language = iniFile.read_ini_file('preferences', 'language', 'english').lower()
        self.running_language = gd.get_language(self.saved_language).key
        self.chosen = None

        self.panel = wx.Panel(self)
        self.tiles = []
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)
        for language in gd.LANGUAGES:
            bitmap = functions.load_and_scale_bitmap(os.path.join(path_to_me, 'images', language.flag),
                                                     FLAG_SIZE.width, FLAG_SIZE.height)
            tile = LanguageTile(self.panel, language, bitmap, language.key == self.saved_language,
                                self.application_colors['ribbon_item_highlight'], self.on_choose)
            self.tiles.append(tile)
            button_sizer.Add(tile, 0, wx.ALL, 10)

        top_sizer = wx.BoxSizer(wx.VERTICAL)
        top_sizer.Add(button_sizer, 1, wx.ALL | wx.EXPAND, 10)
        self.panel.SetSizer(top_sizer)
        top_sizer.Fit(self)

        # Ensure all controls have the system-wide colors
        functions.set_colors(self.panel, self.application_colors)

        self.Bind(wx.EVT_CHAR_HOOK, self.on_char_hook)
        self.Bind(wx.EVT_CLOSE, lambda _event: self.EndModal(wx.ID_CANCEL))

        self.CentreOnParent()
        wx.CallAfter(self.focus_initial_tile)  # Once ShowModal() has shown the window

    def focus_initial_tile(self) -> None:
        if not self:
            return
        current = [tile for tile in self.tiles if tile.current]
        (current or self.tiles)[0].SetFocus()

    def focused_tile_index(self):
        for index, tile in enumerate(self.tiles):
            if tile.HasFocus():
                return index
        return None

    # ------------------------------------------------------------------------------------------------------------------
    # Escape closes the window, the arrow keys move between the languages and Enter / Space picks one
    def on_char_hook(self, event):
        key = event.GetKeyCode()
        index = self.focused_tile_index()
        if key == wx.WXK_ESCAPE:
            self.EndModal(wx.ID_CANCEL)
        elif key in (wx.WXK_LEFT, wx.WXK_UP, wx.WXK_RIGHT, wx.WXK_DOWN) and index is not None:
            step = -1 if key in (wx.WXK_LEFT, wx.WXK_UP) else 1
            self.tiles[(index + step) % len(self.tiles)].SetFocus()
        elif key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER, wx.WXK_SPACE) and index is not None:
            self.on_choose(self.tiles[index].language)
        else:
            event.Skip()

    def on_choose(self, language: gd.Language) -> None:
        iniFile.set_ini_file_variables([('preferences', 'language', language.key)])
        if language.key != self.running_language:
            self.chosen = language.key
            self.EndModal(wx.ID_OK)
        else:
            self.EndModal(wx.ID_CANCEL)


# ----------------------------------------------------------------------------------------------------------------------
def show_restart_note(parent, language_key: str) -> None:
    """Tell the user pfeMAME changes language when it restarts - in the language they have just chosen."""
    translate = functions.language_translation(language_key).gettext
    functions.show_information_dialog(parent,
                                      translate(N_('pfeMAME will use the new language after it has been restarted.')),
                                      translate('Restart Required'))


if __name__ == '__main__':
    app = wx.App()
    # This is just used for testing purposes
    dlg = LanguagePicker()
    print('Result:', 'OK' if dlg.ShowModal() == wx.ID_OK else 'Cancel', dlg.chosen)
    dlg.Destroy()
