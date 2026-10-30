"""
ROM Information (rominfo.py) and XML Information (xmlinfo.py): reading MAME's -listroms, -verifyroms and
-listsoftware output, and checking system program files against the HASH file entries.  The MAME output is real
MAME 0.289 output, trimmed.
"""
import hashlib
import io
import os
import zlib

import checkall
import rominfo
import software_lists
import xmlinfo
from rominfo import BAD_DUMP, GOOD_DUMP, NO_DUMP

LISTROMS_PACMAN = """\
ROMs required for driver "pacman".\r
Name                                   Size Checksum\r
pacman.6e                              4096 CRC(c1e6ab10) SHA1(e87e059c5be45753f7e9f33dff851f16d6751181)\r
pacman.5f                              4096 CRC(958fedf9) SHA1(4a937ac02216ea8c96477d4a15522070507fb599)\r
82s123.7f                                32 CRC(2fc650bd) SHA1(8d0268dee78e47c712202b0ec4f1f51109b1f2a5)\r
"""

LISTROMS_ODD_ROWS = """\
ROMs required for driver "test".
Name                                   Size Checksum
kinst                                       SHA1(81d833236e994528d1482979261401b198d1ca53)
6331.sound-u8                            32 BAD CRC(1d298cb0) SHA1(bb0bb62365402543e3154b9a77be9c75010e6abc) BAD_DUMP
prom.1                                   32 NO GOOD DUMP KNOWN
nodisk                                      NO GOOD DUMP KNOWN
"""

VERIFY_BAD_PACMAN = """\
pacman      : pacman.6e (4096 bytes) - INCORRECT LENGTH: 4086 bytes
pacman      : pacman.5f (4096 bytes) - INCORRECT CHECKSUM:
EXPECTED: CRC(958fedf9) SHA1(4a937ac02216ea8c96477d4a15522070507fb599)
   FOUND: CRC(c71c0011)
pacman      : 82s123.7f (32 bytes) - NOT FOUND (puckman)
romset pacman [puckman] is bad
1 romsets found, 0 were OK.
"""


# ---------------------------------------------------------------------------------------------------------- -listroms
def test_listroms_normal_rows():
    header, roms = rominfo.parse_listroms_output(LISTROMS_PACMAN)
    assert header == 'ROMs required for driver "pacman".'
    assert [(r.name, r.size, r.crc, r.dump) for r in roms] == [('pacman.6e', '4096', 'c1e6ab10', GOOD_DUMP),
                                                               ('pacman.5f', '4096', '958fedf9', GOOD_DUMP),
                                                               ('82s123.7f', '32', '2fc650bd', GOOD_DUMP)]
    assert roms[0].sha1 == 'e87e059c5be45753f7e9f33dff851f16d6751181'


def test_listroms_disks_and_bad_dumps_are_kept():
    _header, roms = rominfo.parse_listroms_output(LISTROMS_ODD_ROWS)
    assert [(r.name, r.size, r.crc, r.dump, r.is_disk) for r in roms] == [
        ('kinst', '', '', GOOD_DUMP, True),
        ('6331.sound-u8', '32', '1d298cb0', BAD_DUMP, False),
        ('prom.1', '32', '', NO_DUMP, False),
        ('nodisk', '', '', NO_DUMP, True)]
    assert roms[0].sha1 == '81d833236e994528d1482979261401b198d1ca53'


def test_listroms_no_roms_and_unknown_name():
    assert rominfo.parse_listroms_output('No ROMs required for driver "pong".\r\n') == \
        ('No ROMs required for driver "pong".', [])
    assert rominfo.parse_listroms_output('') == ('', [])


def test_render_html_escapes_and_only_shows_used_columns():
    header, roms = rominfo.parse_listroms_output(LISTROMS_PACMAN)
    page = rominfo.render_html('A & <B>', roms, [], '', None, '#000000', '#ffffff')
    assert 'A &amp; &lt;B&gt;' in page
    assert 'Status' not in page and 'Dump' not in page
    _header, odd = rominfo.parse_listroms_output(LISTROMS_ODD_ROWS)
    page = rominfo.render_html(header, odd, [], '', None, '#000000', '#ffffff')
    assert 'Dump' in page and 'BAD DUMP' in page and 'disk (CHD)' in page


# -------------------------------------------------------------------------------------------------------- -verifyroms
def test_verify_statuses_per_file():
    results, _messages = checkall.parse_verify_output(VERIFY_BAD_PACMAN.splitlines(), ['pacman'])
    assert rominfo.verify_file_statuses(results[0].details) == {
        'pacman.6e': 'INCORRECT LENGTH: 4086 bytes',
        'pacman.5f': 'INCORRECT CHECKSUM - FOUND: CRC(c71c0011)',
        '82s123.7f': 'NOT FOUND (puckman)'}


def test_apply_verify_result():
    _header, roms = rominfo.parse_listroms_output(LISTROMS_PACMAN + 'pacman.6f    4096 CRC(1a6fb2d4) SHA1(aa)\n')
    results, _messages = checkall.parse_verify_output(VERIFY_BAD_PACMAN.splitlines(), ['pacman'])
    rominfo.apply_verify_result(roms, results[0])
    assert [r.status for r in roms] == ['INCORRECT LENGTH: 4086 bytes', 'INCORRECT CHECKSUM - FOUND: CRC(c71c0011)',
                                        'NOT FOUND (puckman)', 'OK']
    assert rominfo.status_colour('OK') == rominfo.OK_COLOUR
    assert rominfo.status_colour('NEEDS REDUMP') == rominfo.WARNING_COLOUR
    assert rominfo.status_colour('NOT FOUND') == rominfo.PROBLEM_COLOUR

    not_found, _messages = checkall.parse_verify_output(['romset "pacman" not found!'], ['pacman'])
    rominfo.apply_verify_result(roms, not_found[0])
    assert {r.status for r in roms} == {'NOT FOUND'}


def test_run_mame_reports_a_missing_program(tmp_path):
    stdout, errors, ran = rominfo.run_mame(str(tmp_path / 'no_such_mame'), ['-listroms', 'pacman'], 5)
    assert stdout == '' and not ran and 'Error running MAME' in errors[0]


# ------------------------------------------------------------------------------------------------------ -listsoftware
SIDE_A = b'side a data\n' * 50
SIDE_B = b'side b data, a bit longer\n' * 40


def crc(data: bytes) -> str:
    return f'{zlib.crc32(data) & 0xFFFFFFFF:08x}'


def sha1(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


LISTSOFTWARE = f"""<?xml version="1.0"?>
<softwarelists>
\t<softwarelist name="spectrum_cass" description="Sinclair ZX Spectrum cassettes">
\t\t<software name="arkos">
\t\t\t<description>Arkos</description>
\t\t\t<year>1988</year>
\t\t\t<publisher>Zigurat</publisher>
\t\t\t<part name="cass1" interface="spectrum_cass">
\t\t\t\t<dataarea name="cass" size="{len(SIDE_A)}">
\t\t\t\t\t<rom name="arkos - side a.tzx" size="{len(SIDE_A)}" crc="{crc(SIDE_A).upper()}" sha1="{sha1(SIDE_A)}"/>
\t\t\t\t</dataarea>
\t\t\t</part>
\t\t\t<part name="cass2" interface="spectrum_cass">
\t\t\t\t<dataarea name="cass" size="{len(SIDE_B)}">
\t\t\t\t\t<rom name="arkos - side b.tzx" size="{len(SIDE_B)}" crc="{crc(SIDE_B)}" sha1="{sha1(SIDE_B)}"/>
\t\t\t\t\t<rom size="10" offset="0" loadflag="continue"/>
\t\t\t\t</dataarea>
\t\t\t</part>
\t\t</software>
\t\t<software name="cdonly">
\t\t\t<description>Disk only</description>
\t\t\t<part name="cdrom" interface="cdrom"><diskarea name="cdrom"><disk name="cdonly" sha1="abc"/></diskarea></part>
\t\t</software>
\t</softwarelist>
\t<softwarelist name="spectrum_flop" description="Sinclair ZX Spectrum disks">
\t\t<software name="ARKOS">
\t\t\t<description>Arkos (disk)</description>
\t\t\t<part name="flop1" interface="floppy_3"><dataarea name="flop" size="5"><rom name="arkos.dsk" size="5" crc="1" sha1="2" status="baddump"/></dataarea></part>
\t\t</software>
\t</softwarelist>
</softwarelists>
"""


def find(short_name):
    return software_lists.find_software(io.BytesIO(LISTSOFTWARE.encode()), short_name)


def test_find_software_returns_every_list_and_all_files():
    entries = find('Arkos')
    assert [e.list_name for e in entries] == ['spectrum_cass', 'spectrum_flop']
    cass = entries[0]
    assert (cass.software.description, cass.software.year, cass.software.publisher) == ('Arkos', '1988', 'Zigurat')
    assert [f.name for f in cass.files] == ['arkos - side a.tzx', 'arkos - side b.tzx']     # Continuation skipped
    assert cass.files[0].crc == crc(SIDE_A)                                                # Lower case
    assert entries[1].files[0].status == 'baddump'

    disk_only = find('cdonly')[0]
    assert [(f.name, f.is_disk) for f in disk_only.files] == [('cdonly', True)]
    assert find('nothing') == []


# ------------------------------------------------------------------------------------------------- checking the files
def test_file_hashes(tmp_path):
    path = tmp_path / 'file.bin'
    path.write_bytes(b'abc')
    assert xmlinfo.file_hashes(str(path)) == xmlinfo.FileHashes('3', '352441c2',
                                                                'a9993e364706816aba3e25717850c26c9cd0d89d')


def test_program_folders_search_every_rom_folder():
    assert xmlinfo.program_folders(['r1', 'r2'], ['spectrum_cass'], 'arkos') == [
        os.path.join('r1', 'spectrum_cass'), os.path.join('r1', 'spectrum_cass', 'arkos'),
        os.path.join('r2', 'spectrum_cass'), os.path.join('r2', 'spectrum_cass', 'arkos')]


def make_roms(tmp_path, side_b_name='arkos - side b.tzx', side_b=SIDE_B):
    folder = tmp_path / 'more roms' / 'spectrum_cass'
    folder.mkdir(parents=True)
    (folder / 'arkos - side a.tzx').write_bytes(SIDE_A)
    if side_b_name:
        (folder / side_b_name).write_bytes(side_b)
    return [str(tmp_path / 'roms'), str(tmp_path / 'more roms')]


def analyse(monkeypatch, rom_folders, program_file, short_name='arkos', system_folder_name='spectrum_cass'):
    monkeypatch.setattr(software_lists, 'load_software', lambda _exe, _system, name: find(name))
    return xmlinfo.analyse('mame', 'spectrum', short_name, program_file, rom_folders, system_folder_name)


def test_second_side_is_compared_with_its_own_entry(tmp_path, monkeypatch):
    report, message = analyse(monkeypatch, make_roms(tmp_path), 'arkos - side b.tzx')
    assert message == ''
    assert report.entry.list_name == 'spectrum_cass'
    assert report.program.expected.name == 'arkos - side b.tzx'
    assert [(c.expected.name, c.result) for c in report.files] == [('arkos - side a.tzx', xmlinfo.MATCH),
                                                                   ('arkos - side b.tzx', xmlinfo.MATCH)]


def test_renamed_file_is_matched_by_checksum(tmp_path, monkeypatch):
    rom_folders = make_roms(tmp_path, side_b_name='my copy.tzx')
    report, _message = analyse(monkeypatch, rom_folders, 'my copy.tzx')
    assert report.program.expected.name == 'arkos - side b.tzx'
    assert report.program.result == xmlinfo.MATCH
    assert report.files[1] is report.program
    assert [c.result for c in report.files] == [xmlinfo.MATCH, xmlinfo.MATCH]


def test_wrong_file_and_missing_file(tmp_path, monkeypatch):
    rom_folders = make_roms(tmp_path, side_b=SIDE_B.replace(b'side b', b'side c'))      # Same size, wrong data
    report, _message = analyse(monkeypatch, rom_folders, 'arkos - side b.tzx')
    assert report.program.expected.name == 'arkos - side b.tzx'
    assert [c.result for c in report.files] == [xmlinfo.MATCH, xmlinfo.WRONG_CHECKSUM]

    os.remove(os.path.join(rom_folders[1], 'spectrum_cass', 'arkos - side b.tzx'))
    report, _message = analyse(monkeypatch, rom_folders, 'arkos - side a.tzx')
    assert [c.result for c in report.files] == [xmlinfo.MATCH, xmlinfo.MISSING]

    report, message = analyse(monkeypatch, rom_folders, 'not there.tzx')
    assert report is None and 'not there.tzx' in message and 'more roms' in message

    report, message = analyse(monkeypatch, rom_folders, 'x.tzx', short_name='nothing')
    assert report is None and 'nothing' in message


def test_disk_only_software_is_not_compared(tmp_path, monkeypatch):
    folder = tmp_path / 'roms' / 'spectrum_cass'
    folder.mkdir(parents=True)
    (folder / 'cdonly.cue').write_bytes(b'x')
    report, message = analyse(monkeypatch, [str(tmp_path / 'roms')], 'cdonly.cue', short_name='cdonly')
    assert report is None and 'disk image' in message


def test_report_html_and_text(tmp_path, monkeypatch):
    report, _message = analyse(monkeypatch, make_roms(tmp_path, side_b_name='B & B.tzx'), 'B & B.tzx')
    rows = xmlinfo.info_rows('ZX <Spectrum>', 'spectrum', 'B & B.tzx', 'arkos', report)
    page = xmlinfo.render_html(rows, report, '', '#000000', '#ffffff')
    assert 'B &amp; B.tzx' in page and 'ZX &lt;Spectrum&gt;' in page
    assert 'Files in this software:' in page and 'Zigurat' in page
    text = xmlinfo.render_text(rows, report, '')
    assert 'Program file: B & B.tzx' in text
    assert 'arkos - side b.tzx' in text and '(selected)' in text
