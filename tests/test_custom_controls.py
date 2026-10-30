"""
Tests for the custom controls (custom_scrollbar.py, custom_drop_down.py): the scrollbar thumb maths and the drop-down
popup.  The text box and scrolled list tests are in test_main_window.py (Messages window, ROM Categories).
"""
import pytest


@pytest.fixture
def frame(wx_app):
    import wx
    frame = wx.Frame(None, size=wx.Size(400, 300))
    yield frame
    frame.Destroy()


def mouse(event_type, y, left_down=True):
    import wx
    event = wx.MouseEvent(event_type)
    event.SetY(y)
    event.SetLeftDown(left_down)
    return event


@pytest.fixture
def long_text(frame):
    """A text box with 500 lines, 200 pixels tall - its scrollbar has a minimum-size thumb"""
    import wx
    from custom_text_ctrl import CustomTextCtrl
    ctrl = CustomTextCtrl(frame, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.NO_BORDER, hidden=False)
    ctrl.SetSize(wx.Size(250, 200))
    ctrl.Layout()
    for number in range(500):
        ctrl.AppendText(f'line {number}\n')
    scrollbar = ctrl.scrollbar
    # No real mouse in a test - the drag code only needs the capture calls to exist
    scrollbar.CaptureMouse = lambda: None
    scrollbar.ReleaseMouse = lambda: None
    scrollbar.HasCapture = lambda: False
    return ctrl


def max_scroll(ctrl):
    area = ctrl.scrolled_area
    return area.GetVirtualSize().height - area.GetClientSize().height


# ----------------------------------------------------------------------------------------------------------------------
# Scrollbar (target mode, as the text box uses it)
def test_scrollbar_thumb_ends_at_the_bottom_of_the_track(long_text):
    scrollbar = long_text.scrollbar
    long_text.scrolled_area.Scroll(0, max_scroll(long_text))
    thumb_y, thumb_height, _ = scrollbar._target_geometry()
    assert thumb_y + thumb_height == scrollbar.GetClientSize().height


def test_grabbing_the_thumb_part_way_down_does_not_jump(long_text):
    import wx
    scrollbar, area = long_text.scrollbar, long_text.scrolled_area
    area.Scroll(0, max_scroll(long_text) // 2)
    before = area.GetViewStart()[1]
    thumb_y, thumb_height, _ = scrollbar._target_geometry()
    grab = thumb_y + thumb_height // 2
    scrollbar.on_mouse_down(mouse(wx.wxEVT_LEFT_DOWN, grab))
    scrollbar.on_mouse_move(mouse(wx.wxEVT_MOTION, grab + 1))
    assert abs(area.GetViewStart()[1] - before) < 50     # Used to jump back near the top


def test_dragging_the_thumb_reaches_both_ends(long_text):
    import wx
    scrollbar, area = long_text.scrollbar, long_text.scrolled_area
    area.Scroll(0, 0)
    thumb_y, thumb_height, _ = scrollbar._target_geometry()
    scrollbar.on_mouse_down(mouse(wx.wxEVT_LEFT_DOWN, thumb_y + 5))
    scrollbar.on_mouse_move(mouse(wx.wxEVT_MOTION, 10000))
    assert area.GetViewStart()[1] == max_scroll(long_text)
    scrollbar.on_mouse_move(mouse(wx.wxEVT_MOTION, -10000))
    assert area.GetViewStart()[1] == 0


def test_clicking_the_track_moves_a_page(long_text):
    import wx
    scrollbar, area = long_text.scrollbar, long_text.scrolled_area
    area.Scroll(0, 1000)
    thumb_y, thumb_height, _ = scrollbar._target_geometry()
    scrollbar.on_mouse_down(mouse(wx.wxEVT_LEFT_DOWN, thumb_y + thumb_height + 2))
    assert area.GetViewStart()[1] == 1000 + area.GetClientSize().height
    assert not scrollbar.dragging


def test_the_scrollbar_widens_while_hovered_or_dragged(long_text):
    import wx
    scrollbar = long_text.scrollbar
    assert scrollbar.target_expand == 0.0                   # Thin to start with
    scrollbar.on_mouse_enter(wx.MouseEvent(wx.wxEVT_ENTER_WINDOW))
    assert scrollbar.target_expand == 1.0
    scrollbar.on_mouse_leave(wx.MouseEvent(wx.wxEVT_LEAVE_WINDOW))
    assert scrollbar.target_expand == 0.0
    thumb_y, _, _ = scrollbar._target_geometry()
    scrollbar.on_mouse_down(mouse(wx.wxEVT_LEFT_DOWN, thumb_y + 2))
    assert scrollbar.target_expand == 1.0                   # Stays wide while dragging, wherever the mouse is
    scrollbar.fade_timer.Stop()


def test_losing_the_mouse_capture_ends_the_drag(long_text):
    import wx
    scrollbar = long_text.scrollbar
    thumb_y, _, _ = scrollbar._target_geometry()
    scrollbar.on_mouse_down(mouse(wx.wxEVT_LEFT_DOWN, thumb_y + 2))
    assert scrollbar.dragging
    scrollbar.on_capture_lost(wx.MouseCaptureLostEvent())
    assert not scrollbar.dragging


# ----------------------------------------------------------------------------------------------------------------------
# Messages window auto-scroll: only follow new text when already at the end
def top_line(ctrl):
    """The text of the line at the top of the view"""
    return ctrl.GetValue().split('\n')[ctrl.scrolled_area.GetViewStart()[1] // ctrl.text.GetCharHeight()]


def test_new_text_is_followed_when_at_the_end(long_text):
    long_text.AppendText('new message\n')
    assert long_text.scrolled_area.GetViewStart()[1] == max_scroll(long_text)


def test_new_text_does_not_move_the_view_when_scrolled_up(long_text):
    long_text.scrolled_area.Scroll(0, 30 * long_text.text.GetCharHeight())
    before = top_line(long_text)
    for number in range(20):
        long_text.AppendText(f'new message {number}\n')
    assert top_line(long_text) == before == 'line 30'


def test_view_stays_on_the_same_line_when_old_lines_are_dropped(long_text):
    long_text.SetMaxLines(500)          # Full already - each trim drops the oldest 50 + lines
    long_text.scrolled_area.Scroll(0, 200 * long_text.text.GetCharHeight())
    assert top_line(long_text) == 'line 200'
    for number in range(30):
        long_text.AppendText(f'new message {number}\n')
    assert not long_text.GetValue().startswith('line 0\n')      # Trimmed
    assert top_line(long_text) == 'line 200'


def test_following_starts_again_back_at_the_end(long_text):
    long_text.scrolled_area.Scroll(0, 0)
    long_text.AppendText('while scrolled up\n')
    long_text.scrolled_area.Scroll(0, max_scroll(long_text))
    long_text.AppendText('back at the end\n')
    assert long_text.scrolled_area.GetViewStart()[1] == max_scroll(long_text)


# ----------------------------------------------------------------------------------------------------------------------
# Keyboard scrolling (the text control is as tall as its text, so its own keys don't move the view)
def press(ctrl, key, control=False):
    import wx
    event = wx.KeyEvent(wx.wxEVT_KEY_DOWN)
    event.SetKeyCode(key)
    event.SetControlDown(control)
    ctrl.on_key_down(event)


def test_page_down_and_up_scroll_a_page_of_whole_lines(long_text):
    import wx
    line = long_text.text.GetCharHeight()
    long_text.scrolled_area.Scroll(0, 0)
    press(long_text, wx.WXK_PAGEDOWN)
    page = long_text.target_scroll_pos
    assert page > 0 and page % line == 0
    assert page <= long_text.scrolled_area.GetClientSize().height
    press(long_text, wx.WXK_PAGEUP)
    assert long_text.target_scroll_pos == 0


def test_end_and_home_go_to_the_end_and_the_top(long_text):
    import wx
    long_text.scrolled_area.Scroll(0, 0)
    press(long_text, wx.WXK_END, control=True)
    assert long_text.target_scroll_pos == max_scroll(long_text)
    long_text.scroll_timer.Stop()
    press(long_text, wx.WXK_HOME)
    assert long_text.target_scroll_pos == 0


def test_the_view_follows_the_caret(long_text):
    long_text.scrolled_area.Scroll(0, 0)
    long_text.text.SetInsertionPoint(long_text.text.XYToPosition(0, 300))
    long_text.show_caret()
    line = long_text.text.GetCharHeight()
    view = long_text.scrolled_area.GetViewStart()[1]
    assert view <= 300 * line and 301 * line <= view + long_text.scrolled_area.GetClientSize().height


def test_the_scrollbar_is_not_a_tab_stop(long_text):
    # It is only used with the mouse - TAB used to stop on it (and do nothing)
    assert not long_text.scrollbar.AcceptsFocus()
    assert not long_text.scrollbar.AcceptsFocusFromKeyboard()


@pytest.mark.parametrize('both', [True, False])
def test_scrollbar_needs_exactly_one_of_target_or_callback(frame, both):
    import wx
    import custom_scrollbar
    arguments = {'target_scroller': wx.ScrolledWindow(frame), 'on_scroll': print} if both else {}
    with pytest.raises(ValueError):
        custom_scrollbar.UnifiedScrollbar(frame, **arguments)


# ----------------------------------------------------------------------------------------------------------------------
# Scrolled list (ROM Categories): a checkbox that gets the focus is scrolled into view
def test_a_focused_checkbox_is_scrolled_into_view(frame):
    import wx
    from custom_scrolled_panel import CustomScrolledPanel
    panel = CustomScrolledPanel(frame, size=wx.Size(200, 150))
    boxes = [wx.CheckBox(panel.content, label=f'Category {number}') for number in range(30)]
    panel.add_widgets(boxes)

    def fully_visible(box):
        top = box.GetPosition().y + panel.content_y
        return 0 <= top and top + box.GetSize().height <= panel.GetClientSize().height

    assert not fully_visible(boxes[25])
    panel.on_child_focus(wx.ChildFocusEvent(boxes[25]))     # What TAB onto it sends
    assert fully_visible(boxes[25])
    panel.on_child_focus(wx.ChildFocusEvent(boxes[0]))
    assert panel.content_y == 0 and fully_visible(boxes[0])


# ----------------------------------------------------------------------------------------------------------------------
# Drop-down list
@pytest.fixture
def dropdown(frame):
    import wx
    from custom_drop_down import ModernDropdown
    panel = wx.Panel(frame)     # In a panel, as in the app (the old code bound to the parent, unbound from the frame)
    dropdown = ModernDropdown(panel, choices=[f'Item {number}' for number in range(30)], size=(150, 25))
    yield dropdown
    dropdown.CloseDropdown()


def test_dropdown_leaves_no_click_handler_behind(dropdown):
    import wx
    for _ in range(3):
        dropdown.OpenDropdown()
        dropdown.CloseDropdown()
    # Each opening used to bind a handler on the parent that was never removed
    assert not dropdown.GetParent().Unbind(wx.EVT_LEFT_DOWN)


def test_dropdown_closes_when_its_popup_closes_itself(dropdown):
    dropdown.OpenDropdown()
    assert dropdown.is_dropdown_open
    dropdown.dropdown_popup.OnDismiss()       # What wx calls after a click outside the list
    assert not dropdown.is_dropdown_open
    assert dropdown.dropdown_popup is None


def dropdown_key(dropdown, key):
    import wx
    event = wx.KeyEvent(wx.wxEVT_CHAR_HOOK)
    event.SetKeyCode(key)
    dropdown.OnKeyDown(event)


def dropdown_type(dropdown, text):
    import wx
    for character in text:
        event = wx.KeyEvent(wx.wxEVT_CHAR)
        event.SetUnicodeKey(ord(character))
        dropdown.OnChar(event)


@pytest.fixture
def names_dropdown(dropdown):
    dropdown.SetChoices(['Alpha', 'Beta', 'Gamma', 'Gemini', 'Delta', 'Golf'])
    dropdown.SetValue('Alpha')
    return dropdown


def test_arrow_keys_step_the_choice_of_a_closed_dropdown(names_dropdown):
    import wx
    dropdown_key(names_dropdown, wx.WXK_DOWN)
    assert names_dropdown.GetValue() == 'Beta' and not names_dropdown.is_dropdown_open
    dropdown_key(names_dropdown, wx.WXK_END)
    assert names_dropdown.GetValue() == 'Golf'
    dropdown_key(names_dropdown, wx.WXK_DOWN)                # Stays on the last
    assert names_dropdown.GetValue() == 'Golf'
    dropdown_key(names_dropdown, wx.WXK_HOME)
    assert names_dropdown.GetValue() == 'Alpha'


def test_typing_jumps_to_a_matching_choice(names_dropdown):
    dropdown_type(names_dropdown, 'g')
    assert names_dropdown.GetValue() == 'Gamma'
    dropdown_type(names_dropdown, 'g')                      # Same letter again: the next one
    assert names_dropdown.GetValue() == 'Gemini'
    names_dropdown.typed_at = 0                             # A pause
    dropdown_type(names_dropdown, 'go')
    assert names_dropdown.GetValue() == 'Golf'


def test_keys_in_the_open_list_move_the_highlight_and_enter_chooses(names_dropdown):
    import wx
    dropdown_key(names_dropdown, wx.WXK_SPACE)
    assert names_dropdown.is_dropdown_open
    dropdown_key(names_dropdown, wx.WXK_DOWN)
    dropdown_key(names_dropdown, wx.WXK_DOWN)
    assert names_dropdown.GetValue() == 'Alpha'             # Only highlighted so far
    dropdown_key(names_dropdown, wx.WXK_RETURN)
    assert names_dropdown.GetValue() == 'Gamma' and not names_dropdown.is_dropdown_open


def test_the_list_is_wide_enough_for_the_longest_item(dropdown):
    import wx
    long_name = 'a much longer item name than the drop-down is wide'
    dropdown.SetChoices(['short', long_name])
    _position, size = dropdown.GetPopupRect()
    dc = wx.ClientDC(dropdown)
    dc.SetFont(dropdown.GetFont())
    assert size.width >= dropdown.popup_text_x + dc.GetTextExtent(long_name)[0]
    assert size.width > dropdown.GetSize().width


def test_a_cut_off_value_is_shown_in_the_tooltip(dropdown):
    import wx
    dropdown.SetToolTip(wx.ToolTip('What this setting does'))
    dropdown.SetChoices(['short', 'a much longer item name than the drop-down is wide'])
    dropdown.SetValue('a much longer item name than the drop-down is wide')
    assert dropdown.GetToolTipText() == 'a much longer item name than the drop-down is wide\n\nWhat this setting does'
    dropdown.SetValue('short')
    assert dropdown.GetToolTipText() == 'What this setting does'


def test_the_placeholder_is_translated(frame, monkeypatch):
    import custom_drop_down
    monkeypatch.setattr(custom_drop_down, '_', lambda text: f'<{text}>')
    assert custom_drop_down.ModernDropdown(frame, choices=['a']).GetHint() == '<Select an option...>'


@pytest.mark.parametrize('language', ['de', 'es', 'fr', 'ja', 'ru', 'zh-CN'])
def test_every_language_has_the_placeholder(language):
    import gettext
    translation = gettext.translation('base', localedir='locales', languages=[language])
    assert translation.gettext('Select an option...') != 'Select an option...'


# ----------------------------------------------------------------------------------------------------------------------
# functions.set_colors
def scheme():
    import wx
    return {'text': wx.Colour(230, 230, 230), 'text_background': wx.Colour(32, 32, 32),
            'scrollbar_thumb': wx.Colour(200, 120, 0), 'scrollbar_track': wx.Colour(60, 30, 0)}


def test_set_colors_exclusions_apply_inside_child_panels_too(frame):
    import wx
    import functions
    outer = wx.Panel(frame)
    inner = wx.Panel(outer)
    excluded = wx.StaticText(inner, label='excluded')
    excluded.SetBackgroundColour(wx.Colour(1, 2, 3))
    coloured = wx.CheckBox(inner, label='coloured')
    functions.set_colors(outer, scheme(), [wx.StaticText])
    assert excluded.GetBackgroundColour() == wx.Colour(1, 2, 3)     # Used to be coloured: only the top was checked
    assert coloured.GetBackgroundColour() == scheme()['text_background']


def test_set_colors_gives_the_custom_controls_the_scrollbar_colours(frame):
    import wx
    import functions
    from custom_drop_down import ModernDropdown
    from custom_scrolled_panel import CustomScrolledPanel
    from custom_text_ctrl import CustomTextCtrl
    panel = wx.Panel(frame)
    dropdown = ModernDropdown(panel, choices=['a'])
    text = CustomTextCtrl(panel, style=wx.TE_MULTILINE)
    listing = CustomScrolledPanel(panel)
    functions.set_colors(panel, scheme())
    assert dropdown.GetThemeColor('scrollbar_thumb') == scheme()['scrollbar_thumb']
    assert text.scrollbar.thumb_color == scheme()['scrollbar_thumb']
    assert listing.scrollbar.track_color == scheme()['scrollbar_track']


def screen_area(dropdown):
    import wx
    display = wx.Display.GetFromWindow(dropdown)
    return wx.Display(display if display != wx.NOT_FOUND else 0).GetClientArea()


def place(dropdown, x, y):
    """Pretend the drop-down is at (x, y) on the screen"""
    import wx
    dropdown.ClientToScreen = lambda point: wx.Point(x + point[0], y + point[1])


def test_dropdown_list_opens_below_when_there_is_room(dropdown):
    area = screen_area(dropdown)
    place(dropdown, area.x + 10, area.y + 10)
    position, size = dropdown.GetPopupRect()
    assert position.y == area.y + 10 + dropdown.GetSize().height


def test_dropdown_list_opens_upwards_near_the_bottom_of_the_screen(dropdown):
    area = screen_area(dropdown)
    top = area.GetBottom() - 40
    place(dropdown, area.x + 10, top)
    position, size = dropdown.GetPopupRect()
    assert position.y + size.height == top          # Ends just above the drop-down
    assert position.y >= area.y


def test_dropdown_list_stays_on_the_screen_near_the_right_edge(dropdown):
    area = screen_area(dropdown)
    place(dropdown, area.GetRight() - 20, area.y + 10)
    position, size = dropdown.GetPopupRect()
    assert position.x + size.width <= area.GetRight() + 1
