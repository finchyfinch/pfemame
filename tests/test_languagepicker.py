"""The language table (global_defaults.LANGUAGES) and the language picker window (languagepicker.py)."""
import gettext
import os

import polib
import pytest
import wx

import global_defaults as gd


# ------------------------------------------------------------------------------------------------------------ the table
def test_every_language_has_its_files():
    for language in gd.LANGUAGES:
        assert os.path.isfile(os.path.join('images', language.flag)), language.flag
        assert os.path.isfile(os.path.join('license', language.license)), language.license
        if language.code != 'en':
            assert os.path.isfile(os.path.join('locales', language.code, 'LC_MESSAGES', 'base.mo')), language.code


def test_languages_are_unique():
    for field in ('key', 'code', 'native', 'flag', 'license'):
        values = [getattr(language, field) for language in gd.LANGUAGES]
        assert len(values) == len(set(values)), field
    assert all(key == key.lower() for key in gd.LANGUAGE_KEYS)    # pfemame.ini stores them in lower case


def test_unknown_or_empty_languages_fall_back_to_english():
    assert gd.get_language('German').code == 'de'
    assert gd.get_language('').key == 'english'
    assert gd.get_language(None).key == 'english'
    assert gd.get_language('klingon').key == 'english'


def test_every_catalogue_translates_the_picker():
    msgids = [language.english for language in gd.LANGUAGES]
    msgids += ['Select Language', 'pfeMAME will use the new language after it has been restarted.']
    pot = {entry.msgid for entry in polib.pofile(os.path.join('locales', 'base.pot'))}
    assert set(msgids) <= pot
    for language in gd.LANGUAGES[1:]:
        translate = gettext.translation('base', localedir='locales', languages=[language.code]).gettext
        for msgid in msgids:
            assert translate(msgid) != msgid, (language.code, msgid)


def test_language_names_and_licences_come_from_the_table(wx_app):
    import functions
    from aboutbox import license_file_name
    assert functions.language_translation('german').gettext('German') == 'Deutsch'
    assert functions.language_translation('').gettext('German') == 'German'
    assert license_file_name('chinese') == 'license_zh-cn.txt'


# ----------------------------------------------------------------------------------------------------------- the window
@pytest.fixture
def make_picker(wx_app, data_dir, monkeypatch):
    """make_picker(saved language) -> the picker, with .ended = the codes EndModal was called with"""
    import app_paths
    import iniFile
    import languagepicker
    monkeypatch.setattr(app_paths, 'app_dir', lambda: os.getcwd())   # conftest runs the tests from the source folder
    monkeypatch.setattr(app_paths, 'migrate_data', lambda source, target: [])
    old_log = wx.Log.SetActiveTarget(wx.LogStderr())
    frame = wx.Frame(None)
    pickers = []

    def make(saved):
        iniFile.set_ini_file_variables([('preferences', 'language', saved)])
        picker = languagepicker.LanguagePicker(frame)
        picker.ended = []
        monkeypatch.setattr(picker, 'EndModal', picker.ended.append)
        pickers.append(picker)
        return picker

    yield make
    for picker in pickers:
        picker.Destroy()
    frame.Destroy()
    wx_app.Yield(True)
    wx.Log.SetActiveTarget(old_log)


def saved_language():
    import iniFile
    return iniFile.read_ini_file('preferences', 'language')


def tile(picker, key):
    return next(tile for tile in picker.tiles if tile.language.key == key)


def press(picker, key_code):
    event = wx.KeyEvent(wx.wxEVT_CHAR_HOOK)
    event.SetKeyCode(key_code)
    picker.on_char_hook(event)


def test_the_current_language_is_marked(make_picker):
    picker = make_picker('german')
    assert [tile.language.key for tile in picker.tiles] == gd.LANGUAGE_KEYS
    assert [tile.language.key for tile in picker.tiles if tile.current] == ['german']
    assert make_picker('').tiles[0].current is False      # First run: nothing chosen yet


def test_choosing_a_different_language_saves_it_and_says_so(make_picker):
    picker = make_picker('german')
    picker.on_choose(tile(picker, 'japanese').language)
    assert picker.ended == [wx.ID_OK] and picker.chosen == 'japanese'
    assert saved_language() == 'japanese'


def test_choosing_the_same_language_is_not_a_change(make_picker):
    picker = make_picker('german')
    picker.on_choose(tile(picker, 'german').language)
    assert picker.ended == [wx.ID_CANCEL] and picker.chosen is None


def test_choosing_english_on_the_first_run_needs_no_restart(make_picker):
    picker = make_picker('')
    picker.on_choose(tile(picker, 'english').language)
    assert picker.ended == [wx.ID_CANCEL]
    assert saved_language() == 'english'      # ...but it is saved, so the picker isn't shown again


def test_the_keyboard_moves_between_and_picks_languages(make_picker, monkeypatch):
    picker = make_picker('english')
    focused = [0]
    monkeypatch.setattr(picker, 'focused_tile_index', lambda: focused[0])
    for t in picker.tiles:
        monkeypatch.setattr(t, 'SetFocus', lambda t=t: focused.__setitem__(0, picker.tiles.index(t)))
    press(picker, wx.WXK_RIGHT)
    press(picker, wx.WXK_RIGHT)
    assert focused == [2]
    press(picker, wx.WXK_LEFT)
    press(picker, wx.WXK_RETURN)
    assert picker.ended == [wx.ID_OK] and picker.chosen == 'german'
    press(picker, wx.WXK_ESCAPE)
    assert picker.ended[-1] == wx.ID_CANCEL
    press(picker, wx.WXK_LEFT)
    press(picker, wx.WXK_LEFT)
    press(picker, wx.WXK_LEFT)
    assert focused == [len(picker.tiles) - 2]      # Wraps round from the first to the last


def test_hover_highlights_the_whole_tile(make_picker):
    picker = make_picker('english')
    german = tile(picker, 'german')
    german.set_hover(True)
    assert german.is_highlighted()
    assert isinstance(german.highlight, wx.Colour)     # pfemame.ini's colours come back as tuples
    picker.Show()
    german.Update()                                     # Paints it highlighted
    german.set_hover(False)
    assert not german.is_highlighted()


def test_highlighted_text_stays_readable():
    from languagepicker import contrasting_text_colour
    assert contrasting_text_colour(wx.Colour(0, 255, 0)) == wx.BLACK
    assert contrasting_text_colour(wx.Colour(0, 0, 128)) == wx.WHITE


def test_the_restart_note_is_in_the_chosen_language(wx_app, monkeypatch):
    import functions
    import languagepicker
    shown = []
    monkeypatch.setattr(functions, 'show_information_dialog', lambda parent, message, title: shown.append(title))
    languagepicker.show_restart_note(None, 'german')
    assert shown == [gettext.translation('base', localedir='locales', languages=['de']).gettext('Restart Required')]
    assert shown != ['Restart Required']
