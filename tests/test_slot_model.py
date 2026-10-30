"""Slot / sub-slot model against saved MAME 0.289 -listxml output."""
from conftest import load_fixture_xml

import slot_model


def rows_by_path(rows):
    return {row.full_path: row for row in rows}


def test_ibm5150_defaults_match_mames_default_tree():
    model = slot_model.SlotModel(load_fixture_xml('ibm5150'), 'ibm5150')
    rows = model.default_rows()
    # MAME's own block lists the complete default tree - every path must be produced, and nothing else
    assert {row.full_path for row in rows} == set(model.main_slots)
    by_path = rows_by_path(rows)
    assert by_path['isa3'].option == 'fdc_xt'
    assert by_path['isa3:fdc_xt:fdc:0'].option == '525dd'
    assert by_path['isa3:fdc_xt:fdc:0'].parent == 'isa3:fdc_xt'
    assert by_path['isa3:fdc_xt:fdc:0'].slot_name == ':fdc:0'
    assert by_path['isa2:com:serport0'].option == 'logitech_mouse'
    assert by_path['isa5'].option == ''


def test_colon_named_builtin_slots_stay_top_level():
    # cpc6128's upd765:0 is a connector on the built-in floppy controller, not a sub-slot
    model = slot_model.SlotModel(load_fixture_xml('cpc6128'), 'cpc6128')
    top = [slot.name for slot in model.top_level_slots()]
    assert 'upd765:0' in top and 'upd765:1' in top
    assert all(row.level == 0 for row in model.default_rows())


def test_saved_selection_changes_the_tree():
    model = slot_model.SlotModel(load_fixture_xml('ibm5150'), 'ibm5150')
    rows = rows_by_path(model.build_rows({'isa2': '', 'isa5': 'com', 'isa3:fdc_xt:fdc:0': '35dd'}))
    assert rows['isa2'].option == ''
    assert 'isa2:com:serport0' not in rows                 # isa2 emptied - its sub-slots go
    assert rows['isa5:com:serport0'].option == 'logitech_mouse'   # new card brings its defaults
    assert rows['isa3:fdc_xt:fdc:0'].option == '35dd'
    assert rows['isa3:fdc_xt:fdc:1'].option == '525dd'     # not in the INI -> MAME's default


def test_nested_expansion_is_limited():
    model = slot_model.SlotModel(load_fixture_xml('spectrum'), 'spectrum')
    uslot = model.top_level_slot('exp').option('uslot')
    rows = model.expand_rows('exp', uslot, 1)
    assert [row.full_path for row in rows] == ['exp:uslot:exp1', 'exp:uslot:exp2']
    mface = next(o for o in rows[0].choices if o.name == 'mface128')
    deeper = model.expand_rows('exp:uslot:exp1', mface, 2)
    assert [row.full_path for row in deeper] == ['exp:uslot:exp1:mface128:exp']
    assert model.expand_rows('x', mface, slot_model.MAX_DEPTH + 1) == []


def test_device_labels_use_descriptions():
    model = slot_model.SlotModel(load_fixture_xml('ibm5150'), 'ibm5150')
    option = model.top_level_slot('isa3').option('fdc_xt')
    assert model.label(option) == 'ISA 8bits XT FDC hookup (fdc_xt)'


def test_parse_ini_slots():
    content = ['# SLOT DEVICES\n',
               'isa3 fdc_xt\n',
               'isa3:fdc_xt:fdc:0 35dd #(SUB)(PARENT=isa3:fdc_xt)\n',
               '\n',
               '# END OF SLOT DEVICES\n']
    assert slot_model.parse_ini_slots(content) == {'isa3': 'fdc_xt', 'isa3:fdc_xt:fdc:0': '35dd'}
    assert slot_model.parse_ini_slots(['bios rev3\n']) is None


def test_bad_xml_gives_an_empty_model():
    model = slot_model.SlotModel('Error: unknown system', 'nothing')
    assert model.error and model.default_rows() == []
