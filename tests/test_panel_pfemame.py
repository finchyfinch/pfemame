"""The pfeMAME Preferences tab (PanelPfeMame.py): what it sends to the preferences window when a control changes."""
import os

import pytest
import wx
from pubsub import pub

import preferences_model as model


class FakeDialog:
    """Stands in for wx.MessageDialog: answers with FakeDialog.answer and counts how often it was shown."""
    answer = wx.ID_YES
    shown = 0

    def __init__(self, *args, **kwargs):
        pass

    def ShowModal(self):
        FakeDialog.shown += 1
        return FakeDialog.answer

    def Destroy(self):
        pass


class FakeColourDialog:
    """Stands in for wx.ColourDialog: the user picks FakeColourDialog.colour (None = Cancel)."""
    colour = None

    def __init__(self, parent, data):
        self.data = data

    def ShowModal(self):
        if FakeColourDialog.colour is None:
            return wx.ID_CANCEL
        self.data.SetColour(FakeColourDialog.colour)
        return wx.ID_OK

    def GetColourData(self):
        return self.data

    def Destroy(self):
        pass


def values(**changes):
    """{attribute: value} for the pfeMAME preferences, as a new pfemame.ini has them, with some changed."""
    result = {option.attr: option.default for option in model.PFEMAME_OPTIONS}
    result.update(pref_show_game_icons='True', pref_check_database_age='True', pref_joystick_selected='Joystick 1: Pad')
    result.update(changes)
    return result


@pytest.fixture
def make_panel(wx_app, data_dir, monkeypatch):
    """make_panel(joysticks=1, **preference values) -> the tab, with .sent = the messages it sent"""
    import app_paths
    import PanelPfeMame
    monkeypatch.setattr(app_paths, 'app_dir', lambda: os.getcwd())   # conftest runs the tests from the source folder
    monkeypatch.setattr(app_paths, 'migrate_data', lambda source, target: [])
    old_log = wx.Log.SetActiveTarget(wx.LogStderr())
    monkeypatch.setattr(wx, 'MessageDialog', FakeDialog)
    monkeypatch.setattr(wx, 'ColourDialog', FakeColourDialog)
    FakeDialog.answer, FakeDialog.shown, FakeColourDialog.colour = wx.ID_YES, 0, None
    frame = wx.Frame(None)
    panels = []

    def make(joysticks=1, **changes):
        import functions
        monkeypatch.setattr(PanelPfeMame.PanelPfeMame, 'setup_joysticks',
                            lambda self: (joysticks, ['Pad'] * joysticks))
        panel = PanelPfeMame.PanelPfeMame(frame, functions.get_application_colors(),
                                          functions.get_font_info().global_font_normal, values(**changes))
        panel.sent = []
        wx_app.Yield(True)  # Leave out the startup log messages

        # (The listeners' arguments must match the real ones: the first listener of a topic sets what it takes)
        def set_variable(msg):
            panel.sent.append(('default_set_variable', msg))

        def update_ini():
            panel.sent.append(('default_update_ini',))

        def restart_required():
            panel.sent.append(('restart_required',))
        panel.listeners = [(set_variable, 'default_set_variable'), (update_ini, 'default_update_ini'),
                           (restart_required, 'restart_required')]
        for listener, topic in panel.listeners:
            pub.subscribe(listener, topic)
        panels.append(panel)
        return panel

    yield make
    for panel in panels:
        for listener, topic in panel.listeners:
            pub.unsubscribe(listener, topic)
    frame.Destroy()
    wx_app.Yield(True)
    wx.Log.SetActiveTarget(old_log)


def changes(wx_app, panel):
    """The messages the tab has sent since last asked (they are sent with wx.CallAfter)"""
    wx_app.Yield(True)
    sent, panel.sent[:] = list(panel.sent), []
    return sent


def click(panel, attr, value=True):
    """Tick / untick a checkbox as the user would"""
    checkbox = panel.controls[attr]
    checkbox.SetValue(value)
    event = wx.CommandEvent(wx.wxEVT_CHECKBOX, checkbox.GetId())
    event.SetEventObject(checkbox)
    panel.on_control_changed(event)


def test_only_the_changed_setting_is_sent(wx_app, make_panel):
    panel = make_panel()
    click(panel, 'pref_tile_dim', False)    # On by default
    assert changes(wx_app, panel) == [('default_set_variable', ['pref_tile_dim', 'False']), ('default_update_ini',)]
    panel.on_control_changed()          # e.g. a second event for the same change
    assert changes(wx_app, panel) == []


def test_settings_that_need_a_restart_ask_for_one(wx_app, make_panel):
    panel = make_panel()
    for attr in ('pref_show_game_icons', 'pref_highlight_missing', 'pref_video_disable'):
        click(panel, attr, not panel.controls[attr].GetValue())
        assert ('restart_required',) in changes(wx_app, panel)
    click(panel, 'pref_tile_mouse')
    assert ('restart_required',) not in changes(wx_app, panel)


def test_full_screen_and_window_untick_each_other(wx_app, make_panel):
    panel = make_panel(pref_force_all_window='True')
    click(panel, 'pref_force_all_fullscreen')
    assert not panel.controls['pref_force_all_window'].GetValue()
    assert sorted(msg for topic, *msg in changes(wx_app, panel) if topic == 'default_set_variable') == [
        [['pref_force_all_fullscreen', 'True']], [['pref_force_all_window', 'False']]]


def test_picking_a_colour_updates_its_button(wx_app, make_panel):
    panel = make_panel()
    button = panel.color_panel.buttons['row_alt_1']
    FakeColourDialog.colour = wx.Colour(0, 0, 0)
    event = wx.CommandEvent(wx.wxEVT_BUTTON, button.GetId())
    event.SetEventObject(button)
    panel.on_button_color_select(event)
    assert button.GetLabel() == '#000000'
    assert button.GetForegroundColour() == wx.Colour(wx.WHITE)       # readable on black
    sent = changes(wx_app, panel)
    assert ('default_set_variable', ['row_alt_1_color', '(0, 0, 0, 255)']) in sent
    assert ('restart_required',) in sent

    FakeColourDialog.colour = None                                     # Cancel
    panel.on_button_color_select(event)
    assert button.GetLabel() == '#000000' and changes(wx_app, panel) == []


def test_the_dark_theme_sets_every_colour_after_asking(wx_app, make_panel):
    import PanelPfeMame
    assert set(PanelPfeMame.dark_theme_colors()) == {name for _attr, name in model.COLOR_OPTIONS}
    panel = make_panel()
    FakeDialog.answer = wx.ID_NO
    panel.on_dark_theme(None)
    assert FakeDialog.shown == 1 and changes(wx_app, panel) == []

    FakeDialog.answer = wx.ID_YES
    panel.on_dark_theme(None)
    highlight = panel.color_panel.buttons['ribbon_item_highlight']
    assert highlight.GetBackgroundColour() == wx.Colour(0, 255, 0) and highlight.GetLabel() == '#00FF00'
    assert panel.color_panel.buttons['text_background'].GetForegroundColour() == wx.Colour(wx.WHITE)
    assert ('restart_required',) in changes(wx_app, panel)


def test_settings_that_cant_apply_are_greyed_out(wx_app, make_panel):
    panel = make_panel()
    assert panel.cbIconSize.IsEnabled() and panel.cbDaysCheckCache.IsEnabled()
    assert panel.controls['pref_video_autoload'].IsEnabled() and panel.cbJoystickSelected.IsEnabled()
    click(panel, 'pref_show_game_icons', False)
    click(panel, 'pref_check_database_age', False)
    click(panel, 'pref_video_disable', True)
    assert not panel.cbIconSize.IsEnabled() and not panel.cbDaysCheckCache.IsEnabled()
    assert not panel.controls['pref_video_autoload'].IsEnabled()

    click(panel, 'pref_enable_joystick_mainview', False)
    assert panel.cbJoystickSelected.IsEnabled()                  # still used by Tile View
    click(panel, 'pref_enable_joystick_tileview', False)
    assert not panel.cbJoystickSelected.IsEnabled()              # no navigation uses it
    click(panel, 'pref_enable_joystick_tileview', True)
    assert panel.cbJoystickSelected.IsEnabled()

    no_joystick = make_panel(joysticks=0)
    assert not no_joystick.cbJoystickSelected.IsEnabled()
    assert not no_joystick.controls['pref_enable_joystick_mainview'].IsEnabled()
    assert no_joystick.cbJoystickSelected.GetValue() == 'Joystick 1: Pad'     # the saved choice is kept


def test_a_startup_dont_show_again_unticks_the_box(wx_app, make_panel):
    panel = make_panel(pref_check_catver_version='True')
    pub.sendMessage('disable_catver_check')
    assert not panel.controls['pref_check_catver_version'].GetValue()
    assert ('default_set_variable', ['pref_check_catver_version', 'False']) in changes(wx_app, panel)


def test_the_closed_tab_stops_listening(wx_app, make_panel):
    panel = make_panel()
    panel.lang_label.Destroy()                      # a child window going doesn't unsubscribe
    assert pub.isSubscribed(panel.disable_catver_check, 'disable_catver_check')
    panel.Destroy()
    wx_app.Yield(True)
    pub.sendMessage('disable_catver_check')         # would raise if the deleted tab still listened
    pub.sendMessage('disable_software_version_check')


def test_the_real_preferences_window_saves_only_what_the_tab_changed(wx_app, data_dir, monkeypatch, tmp_path):
    import app_paths
    import iniFile
    import preferences
    import PanelPfeMame
    monkeypatch.setattr(app_paths, 'app_dir', lambda: os.getcwd())
    monkeypatch.setattr(app_paths, 'migrate_data', lambda source, target: [])
    monkeypatch.setattr(wx, 'MessageBox', lambda *args, **kwargs: wx.OK)
    old_log = wx.Log.SetActiveTarget(wx.LogStderr())
    mame = tmp_path / 'MAME'
    mame.mkdir()
    (mame / 'mame.ini').write_text('cheat 0\n', encoding='utf-8')
    iniFile.set_ini_file_variables([('path', 'mame_ini', str(mame / 'mame.ini')),
                                    ('preferences', 'checkdatabaseage', '')])
    frame = wx.Frame(None)
    window = preferences.Preferences(frame, 'Default Preferences', 'default', '', '', '', '')
    window.reset_block()
    def descendants(parent):
        for child in parent.GetChildren():
            yield child
            yield from descendants(child)
    tab = next(child for child in descendants(window) if isinstance(child, PanelPfeMame.PanelPfeMame))
    click(tab, 'pref_tile_dim', not tab.controls['pref_tile_dim'].GetValue())
    wx_app.Yield(True)
    window.process_preferences()
    assert iniFile.read_ini_file('preferences', 'tiledim') == str(tab.controls['pref_tile_dim'].GetValue())
    assert iniFile.read_ini_file('preferences', 'checkdatabaseage') == ''     # not rewritten as 'False'
    frame.Destroy()
    wx_app.Yield(True)
    wx.Log.SetActiveTarget(old_log)


def test_tab_goes_down_the_left_column_then_the_colours(wx_app, make_panel):
    # wx tabs through the children in creation order: Tile Size and the default view used to come first, before the
    # number boxes above them, and the checkbox list before all of them
    panel = make_panel()
    expected = [panel.cbDaysCheckCache, panel.cbScreensaverTime, panel.cbMainView, panel.cbIconSize, panel.cbTileSize,
                panel.cbJoystickSelected, panel.panel_checkboxes, panel.lang_btn, panel.color_panel]
    order = [child for child in panel.GetChildren() if child in expected]
    assert order == expected


def test_choosing_a_new_language_asks_for_a_restart(wx_app, make_panel, monkeypatch):
    import languagepicker
    answers = []

    class FakePicker:
        def __init__(self, parent):
            assert parent is panel          # Centred on the Preferences window, not the main window

        def ShowModal(self):
            return answers.pop(0)

        def Destroy(self):
            pass

    monkeypatch.setattr(languagepicker, 'LanguagePicker', FakePicker)
    panel = make_panel()
    answers[:] = [wx.ID_CANCEL]
    panel.on_select_language(None)
    assert ('restart_required',) not in changes(wx_app, panel)
    answers[:] = [wx.ID_OK]
    panel.on_select_language(None)
    assert ('restart_required',) in changes(wx_app, panel)
