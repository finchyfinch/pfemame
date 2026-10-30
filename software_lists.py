#!/usr/bin/env python3

# ----------------------------------------------------------------------------------------------------------------------
# software_lists.py

"""
Read a system's software lists (MAME's HASH files) with `mame <system> -listsoftware`: every list the system can
use, and for each piece of software its short name, title, year, publisher and how well MAME supports it.
Used by the software list browser (software_browser.py) and the XML information window (xmlinfo.py).

This module has no wxPython dependency.
"""

import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from mame_paths import NO_CONSOLE, mame_working_dir


@dataclass
class Software:
    name: str               # Short name (what MAME uses on the command line)
    description: str
    year: str
    publisher: str
    supported: str          # 'yes', 'partial' or 'no'
    cloneof: str = ''


@dataclass
class SoftwareFile:
    """One file of a piece of software (a <rom> or <disk> in the HASH file)."""
    name: str
    size: str               # '' for a disk (CHD) - the HASH files don't give a size for those
    crc: str
    sha1: str
    status: str = 'good'    # MAME's dump status: 'good', 'baddump' or 'nodump'

    @property
    def is_disk(self) -> bool:
        return not self.size


@dataclass
class SoftwareEntry:
    """A piece of software, the list it is in and all of its files."""
    list_name: str
    software: Software
    files: list = field(default_factory=list)


@dataclass
class SoftwareList:
    name: str               # e.g. 'spectrum_cass'
    description: str        # e.g. 'Sinclair ZX Spectrum cassettes'
    software: list = field(default_factory=list)


def parse(stream) -> list[SoftwareList]:
    """Parse -listsoftware output (a binary file object) incrementally."""
    lists: list[SoftwareList] = []
    current = None
    for event, element in ET.iterparse(stream, events=('start', 'end')):
        if event == 'start':
            if element.tag == 'softwarelist':
                current = SoftwareList(element.get('name', ''), element.get('description', ''))
                lists.append(current)
            continue
        if element.tag == 'software' and current is not None:
            current.software.append(Software(name=element.get('name', ''),
                                             description=element.findtext('description', ''),
                                             year=element.findtext('year', ''),
                                             publisher=element.findtext('publisher', ''),
                                             supported=element.get('supported', 'yes'),
                                             cloneof=element.get('cloneof', '')))
            element.clear()
        elif element.tag == 'softwarelist':
            element.clear()
    return lists


def find_software(stream, short_name: str) -> list[SoftwareEntry]:
    """
    Every piece of software called short_name (any case) in -listsoftware output (a binary file object), with its
    files.  Short names are only unique within one list, so a system with several lists can have more than one.
    """
    short_name = short_name.lower()
    found: list[SoftwareEntry] = []
    list_name = ''
    for event, element in ET.iterparse(stream, events=('start', 'end')):
        if event == 'start':
            if element.tag == 'softwarelist':
                list_name = element.get('name', '')
            continue
        if element.tag == 'software':
            if element.get('name', '').lower() == short_name:
                files = []
                for item in element.iter():
                    if item.tag in ('rom', 'disk') and item.get('name'):    # Nameless <rom>s are continuations
                        files.append(SoftwareFile(name=item.get('name'),
                                                  size=item.get('size', '') if item.tag == 'rom' else '',
                                                  crc=item.get('crc', '').lower(),
                                                  sha1=item.get('sha1', '').lower(),
                                                  status=item.get('status', 'good')))
                software = Software(name=element.get('name', ''),
                                    description=element.findtext('description', ''),
                                    year=element.findtext('year', ''),
                                    publisher=element.findtext('publisher', ''),
                                    supported=element.get('supported', 'yes'),
                                    cloneof=element.get('cloneof', ''))
                found.append(SoftwareEntry(list_name, software, files))
            element.clear()
        elif element.tag == 'softwarelist':
            element.clear()
    return found


def _run_listsoftware(mame_exe: str, system: str, parser, *args):
    """Run 'mame <system> -listsoftware' and hand its output to parser(stream, *args)."""
    process = subprocess.Popen([mame_exe, system, '-listsoftware', '-nodtd'], stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, cwd=mame_working_dir(mame_exe), **NO_CONSOLE)
    try:
        return parser(process.stdout, *args)
    except ET.ParseError:
        return []                   # 'No software lists found for this system' is not XML
    finally:
        if process.poll() is None:
            process.kill()
        process.stdout.close()
        process.wait()


def load_for_system(mame_exe: str, system: str) -> list[SoftwareList]:
    """The software lists of one system.  An empty list if it has none (or the HASH files are missing)."""
    return _run_listsoftware(mame_exe, system, parse)


def load_software(mame_exe: str, system: str, short_name: str) -> list[SoftwareEntry]:
    """The software called short_name in the lists of one system (see find_software).  Raises OSError if MAME
    can't be run."""
    return _run_listsoftware(mame_exe, system, find_software, short_name)
