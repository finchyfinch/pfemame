"""
Artwork Layout Fixer (fix_artwork_file.py): converting the old view item tags, keeping the file's encoding, finding
the artwork (zip files and folders), the safe zip rewrite, the backups / restore and the summaries.
"""
import os
import zipfile
from collections import Counter

import pytest

import fix_artwork_file as fixer
from fix_artwork_file import ArtworkSet

OLD_LAYOUT = """\
<?xml version="1.0" encoding="ISO-8859-1"?>
<!-- Caf\u00e9 artwork -->
<mamelayout version="2">
  <element name="bg"><image file="bg.png"/></element>
  <view name="Upright Artwork">
    <backdrop element="bg"><bounds x="0" y="0" width="4" height="3"/></backdrop>
    <overlay element='ov'><bounds x="0" y="0" width="4" height="3"/></overlay>
    <bezel name="b1" element="bz">
      <bounds x="0" y="0" width="4" height="3"/>
    </bezel>
    <CPANEL element="cp" /><marquee element="mq"><bounds x="0" y="-1" width="4" height="1"/></marquee>
    <screen index="0"><bounds x="0" y="0" width="4" height="3"/></screen>
  </view>
</mamelayout>
"""

NEW_LAYOUT = """\
<?xml version="1.0" encoding="ISO-8859-1"?>
<!-- Caf\u00e9 artwork -->
<mamelayout version="2">
  <element name="bg"><image file="bg.png"/></element>
  <view name="Upright Artwork">
    <element ref="bg" blend="add"><bounds x="0" y="0" width="4" height="3"/></element>
    <element ref='ov' blend="multiply"><bounds x="0" y="0" width="4" height="3"/></element>
    <element name="b1" ref="bz">
      <bounds x="0" y="0" width="4" height="3"/>
    </element>
    <element ref="cp"/><element ref="mq"><bounds x="0" y="-1" width="4" height="1"/></element>
    <screen index="0"><bounds x="0" y="0" width="4" height="3"/></screen>
  </view>
</mamelayout>
"""

ALL_TAGS = Counter(backdrop=1, overlay=1, bezel=1, cpanel=1, marquee=1)


# ----------------------------------------------------------------------------------------------------------------------
# Converting
def test_convert_layout_replaces_every_old_tag_and_keeps_the_blending():
    text, counts = fixer.convert_layout(OLD_LAYOUT)
    assert text == NEW_LAYOUT
    assert counts == ALL_TAGS


def test_convert_layout_leaves_an_up_to_date_layout_alone():
    text, counts = fixer.convert_layout(NEW_LAYOUT)
    assert text == NEW_LAYOUT
    assert not counts


def test_convert_layout_keeps_an_existing_blend_and_skips_items_without_an_element():
    text, counts = fixer.convert_layout('<overlay element="o" blend="alpha"/><bezel><bounds/></bezel>'
                                        '<bezelx element="z"/>')
    assert text == '<element ref="o" blend="alpha"/><bezel><bounds/></bezel><bezelx element="z"/>'
    assert counts == Counter(overlay=1)


@pytest.mark.parametrize('encoding', ['iso-8859-1', 'utf-8', 'utf-8-sig', 'utf-16'])
def test_convert_layout_bytes_keeps_the_file_encoding(encoding):
    new_raw, counts = fixer.convert_layout_bytes(OLD_LAYOUT.encode(encoding))
    assert counts == ALL_TAGS
    assert new_raw.decode(encoding) == NEW_LAYOUT
    if encoding != 'utf-16':        # Byte for byte, apart from the tags
        assert new_raw == NEW_LAYOUT.encode(encoding)


def test_describe_counts_uses_the_tag_order():
    assert fixer.describe_counts(Counter(overlay=2, backdrop=1)) == '1 backdrop, 2 overlay'


# ----------------------------------------------------------------------------------------------------------------------
# Finding and analysing the artwork
def make_zip(path, files: dict):
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as zout:
        zout.comment = b'kept'
        for name, data in files.items():
            info = zipfile.ZipInfo(name, date_time=(2001, 2, 3, 4, 5, 6))
            info.compress_type = zipfile.ZIP_STORED if name.endswith('.png') else zipfile.ZIP_DEFLATED
            zout.writestr(info, data)


@pytest.fixture
def artwork(tmp_path):
    """An artwork folder with an old zip, an up to date zip, an old unzipped folder, a broken zip and a .7z."""
    folder = tmp_path / 'artwork'
    folder.mkdir()
    make_zip(folder / 'oldgame.zip', {'default.lay': OLD_LAYOUT.encode('latin-1'), 'bg.png': b'\x89PNG' + bytes(50),
                                      'extra/second.lay': b'<backdrop element="x"/>'})
    make_zip(folder / 'newgame.zip', {'default.lay': NEW_LAYOUT.encode('latin-1')})
    (folder / 'foldergame').mkdir()
    (folder / 'foldergame' / 'default.lay').write_bytes(OLD_LAYOUT.encode('utf-8'))
    (folder / 'foldergame' / 'bg.png').write_bytes(b'png')
    (folder / 'broken.zip').write_bytes(b'not a zip')
    (folder / 'packed.7z').write_bytes(b'7z')
    (folder / 'readme.txt').write_text('ignored')
    return folder


def analysed(art_folders):
    scan = fixer.find_artwork_sets(art_folders)
    for artwork_set in scan.sets:
        fixer.analyse_set(artwork_set)
    return scan


def by_name(scan):
    return {artwork_set.name: artwork_set for artwork_set in scan.sets}


def test_analysis_finds_zips_and_folders_that_need_updating(artwork, tmp_path):
    scan = analysed([str(artwork), str(tmp_path / 'missing')])
    sets = by_name(scan)

    assert sorted(sets) == ['broken.zip', 'foldergame', 'newgame.zip', 'oldgame.zip']
    assert sets['oldgame.zip'].changes == {'default.lay': ALL_TAGS, 'extra/second.lay': Counter(backdrop=1)}
    assert sets['oldgame.zip'].layouts_checked == 2
    assert sets['foldergame'].changes == {'default.lay': ALL_TAGS}
    assert not sets['newgame.zip'].changes
    assert sets['broken.zip'].error
    assert [os.path.basename(path) for path in scan.unsupported] == ['packed.7z']
    assert scan.missing_folders == [str(tmp_path / 'missing')]
    assert [artwork_set.name for artwork_set in scan.needing_update()] == ['foldergame', 'oldgame.zip']


def test_analysis_summary_is_easy_to_read(artwork, tmp_path):
    lines = fixer.analysis_summary(analysed([str(artwork), str(tmp_path / 'missing')]))
    text = '\n'.join(lines)
    assert 'Artwork sets checked: 4 (zip files: 3, folders: 1)' in text
    assert 'Layout (.lay) files checked: 4' in text
    assert 'Artwork sets that need updating: 2' in text
    assert 'Old tags to replace: 11 (3 backdrop, 2 overlay, 2 bezel, 2 cpanel, 2 marquee)' in text
    assert 'Artwork sets that could not be read: 1' in text
    assert '.7z artwork skipped' in text
    assert 'Artwork folder not found' in text
    assert 'Press FIX' in text


def test_analysis_summary_when_everything_is_up_to_date(tmp_path):
    make_zip(tmp_path / 'newgame.zip', {'default.lay': NEW_LAYOUT.encode()})
    assert 'Your artwork is up to date - nothing needs changing.' in fixer.analysis_summary(analysed([str(tmp_path)]))


def test_set_lines_name_each_layout_file(artwork):
    sets = by_name(analysed([str(artwork)]))
    lines = fixer.set_lines(sets['oldgame.zip'])
    assert lines[0] == ('oldgame.zip (default.lay): 1 backdrop, 1 overlay, 1 bezel, 1 cpanel, 1 marquee')
    assert lines[0].endswith('oldgame.zip (default.lay): 1 backdrop, 1 overlay, 1 bezel, 1 cpanel, 1 marquee')
    assert lines[1].endswith('oldgame.zip (extra/second.lay): 1 backdrop')
    assert fixer.set_lines(sets['broken.zip'])[0].startswith('broken.zip: could not be read')
    assert fixer.set_lines(sets['foldergame']) == ['foldergame/default.lay: 1 backdrop, 1 overlay, 1 bezel, '
                                                   '1 cpanel, 1 marquee']


def test_set_lines_show_the_full_path_with_several_artwork_folders(artwork, tmp_path):
    other = tmp_path / 'more_art'
    other.mkdir()
    sets = by_name(analysed([str(artwork), str(other)]))
    assert fixer.set_lines(sets['oldgame.zip'])[0].startswith(str(artwork / 'oldgame.zip') + ' (default.lay)')


# ----------------------------------------------------------------------------------------------------------------------
# Fixing, backing up and restoring
def test_fix_zip_rewrites_only_the_layouts_and_keeps_everything_else(artwork):
    original = (artwork / 'oldgame.zip').read_bytes()
    artwork_set = by_name(analysed([str(artwork)]))['oldgame.zip']

    assert fixer.fix_set(artwork_set) == ALL_TAGS + Counter(backdrop=1)
    assert not artwork_set.changes

    with zipfile.ZipFile(artwork / 'oldgame.zip') as zin:
        assert zin.comment == b'kept'
        assert zin.read('default.lay') == NEW_LAYOUT.encode('latin-1')
        assert zin.read('extra/second.lay') == b'<element ref="x" blend="add"/>'
        assert zin.read('bg.png') == b'\x89PNG' + bytes(50)
        info = zin.getinfo('bg.png')
        assert info.date_time == (2001, 2, 3, 4, 5, 6)
        assert info.compress_type == zipfile.ZIP_STORED

    backup = artwork / fixer.BACKUP_FOLDER / 'oldgame.zip'
    assert backup.read_bytes() == original
    assert not [name for name in os.listdir(artwork) if name.endswith('.tmp')]     # No temp files left behind
    assert [artwork_set.name for artwork_set in analysed([str(artwork)]).needing_update()] == ['foldergame']


def test_fix_folder_and_restore(artwork):
    artwork_set = by_name(analysed([str(artwork)]))['foldergame']
    fixer.fix_set(artwork_set)
    layout = artwork / 'foldergame' / 'default.lay'
    assert layout.read_bytes() == NEW_LAYOUT.encode('utf-8')

    backups = fixer.find_backups([str(artwork)])
    assert backups == [(str(artwork / fixer.BACKUP_FOLDER / 'foldergame' / 'default.lay'), str(layout))]
    for backup, original in backups:
        fixer.restore_file(backup, original)
    assert layout.read_bytes() == OLD_LAYOUT.encode('utf-8')
    assert os.path.exists(backups[0][0])        # The backup is kept


def test_backup_keeps_the_first_original(artwork):
    artwork_set = by_name(analysed([str(artwork)]))['foldergame']
    fixer.fix_set(artwork_set)
    layout = artwork / 'foldergame' / 'default.lay'
    layout.write_bytes(b'<bezel element="changed"/>')       # Edited again by the user, then fixed again
    fixer.fix_set(fixer.analyse_set(artwork_set))
    assert (artwork / fixer.BACKUP_FOLDER / 'foldergame' / 'default.lay').read_bytes() == OLD_LAYOUT.encode()


def test_the_backup_folder_is_not_checked_as_artwork(artwork):
    for artwork_set in analysed([str(artwork)]).needing_update():
        fixer.fix_set(artwork_set)
    assert fixer.BACKUP_FOLDER not in by_name(analysed([str(artwork)]))


def test_a_failed_rewrite_leaves_the_zip_as_it_was(artwork, monkeypatch):
    original = (artwork / 'oldgame.zip').read_bytes()
    artwork_set = by_name(analysed([str(artwork)]))['oldgame.zip']

    def fail(*_args):
        raise OSError('disk full')
    monkeypatch.setattr(fixer.os, 'replace', fail)
    with pytest.raises(OSError):
        fixer.fix_set(artwork_set)
    assert (artwork / 'oldgame.zip').read_bytes() == original
    assert not [name for name in os.listdir(artwork) if name.endswith('.tmp')]


def test_fix_and_restore_summaries():
    text = '\n'.join(fixer.fix_summary(2, 1, Counter(bezel=3), ['C:/art/artwork_backup'], stopped=True))
    assert 'Artwork sets updated: 2' in text
    assert 'Old tags replaced: 3 (3 bezel)' in text
    assert 'Artwork sets that failed (left unchanged): 1' in text
    assert 'Stopped before' in text
    assert 'The original files are in: C:/art/artwork_backup' in text

    text = '\n'.join(fixer.restore_summary(4, 0, stopped=False))
    assert 'Files restored from backup: 4' in text
    assert 'could not be restored' not in text


def test_set_paths_relative_to_the_backup_folder(tmp_path):
    art_folder = str(tmp_path)
    path = os.path.join(art_folder, 'game', 'default.lay')
    assert fixer.backup_path(art_folder, path) == os.path.join(art_folder, fixer.BACKUP_FOLDER, 'game', 'default.lay')
    assert ArtworkSet(art_folder, os.path.join(art_folder, 'A.ZIP')).is_zip
