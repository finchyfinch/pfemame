"""
Slots & Bios page (PanelSlots.py) built for real against saved MAME -listxml output (no MAME needed).
"""
import pytest

from conftest import load_fixture_xml


@pytest.fixture
def slots_page(wx_app, data_dir, tmp_path):
    import wx
    import PanelSlots
    import slot_model
    exe = str(tmp_path / 'mame.exe')
    PanelSlots._slot_model_cache[(exe, 'spectrum')] = slot_model.SlotModel(load_fixture_xml('spectrum'), 'spectrum')
    frame = wx.Frame(None)
    page = PanelSlots.PanelSlots(frame, 'game', [], 'spectrum', exe)
    yield page
    frame.Destroy()
    PanelSlots._slot_model_cache.pop((exe, 'spectrum'), None)


def tab_stops(page):
    """The slot rows' TAB stops in TAB order (wx tabs through siblings in the order of GetChildren)"""
    import wx
    # macOS adds its native wx.ScrollBar as a child of the scrolled window and it accepts keyboard focus - it isn't
    # one of the slot rows' controls
    return [child for child in page.slots_scrolled.GetChildren()
            if child.IsShown() and child.AcceptsFocusFromKeyboard() and not isinstance(child, wx.ScrollBar)]


def test_slot_names_are_labels_not_drop_downs(slots_page):
    # A machine's slots are fixed - only the device in each one is chosen, so a one-item drop-down made it look as
    # though something was missing
    import PanelSlots
    from custom_drop_down import ModernDropdown
    for row in slots_page.slot_rows:
        assert isinstance(row.cb1, PanelSlots.SlotNameLabel) and not isinstance(row.cb1, ModernDropdown)
        assert row.cb1.GetValue().endswith(row.slot_name)
        assert not row.cb1.AcceptsFocusFromKeyboard()                 # Not a TAB stop
    assert tab_stops(slots_page)[:2] == [slots_page.slot_rows[0].cb2, slots_page.slot_rows[0].btn_clear]


def test_sub_slot_rows_are_in_tab_order_under_their_slot(slots_page):
    row = next(r for r in slots_page.slot_rows if r.slot_name == 'exp')
    plusd = next(option for option in row.choices if option.name == 'plusd')
    slots_page._set_row_device(row, plusd)                  # Adds its fdc:0, fdc:1 and centronics rows below it

    names = [r.slot_name for r in slots_page.slot_rows]
    assert names.index('exp') < names.index(':fdc:0') < names.index('dma')
    expected = [control for r in slots_page.slot_rows for control in (r.cb1, r.cb2, r.btn_clear)
                if control.AcceptsFocusFromKeyboard()]
    # The new rows used to come after every other row (after dma) when tabbing
    assert tab_stops(slots_page) == expected
