#!/usr/bin/env python3

# ----------------------------------------------------------------------------------------------------------------------
# online_image_search.py

"""
Online image search providers for the 'Replace image from online' feature.

This module is intentionally free of any wxPython / GUI code so it can be unit-tested and run on a background
thread.  It locates candidate replacement images for a ROM from a small set of providers and returns them in a
preferred (most accurate first) order:

    1. progettosnaps.net   - the canonical MAME artwork source.  Categories map 1:1 onto pfeMAME's image options
                             and files are keyed by the MAME short (ROM) name.  Best-effort: the site ships ZIP
                             packs rather than offering a clean per-file API, so this provider tries a known URL
                             pattern and silently yields nothing if it cannot resolve a direct file.
    2. libretro-thumbnails - free raw.githubusercontent.com per-file URLs.  Only covers Snapshots and Title
                             Screens, and is keyed by the full game description rather than the short name.
    3. DuckDuckGo          - keyless image search used as a catch-all fallback.  Covers every category but the
                             results are noisier.  This uses DuckDuckGo's unofficial i.js endpoint and may break
                             or rate-limit; failures degrade gracefully to an empty result list.

A ROM row in pfeMAME is either an arcade machine (Galaxian) or a *system program* - a piece of software loaded
into a system / console ROM, e.g. 'Super Mario Bros.' running on 'nes'.  For a system program the MAME machine
name is the console rather than the game, so searching with it would return pictures of the console.  Callers
therefore pass a SystemContext describing both halves, which points each provider at the software item instead:

    * progettosnaps  - software snaps are filed per software list, /MAME/<category>/<softwarelist>/<short>.png
    * libretro       - the per-console thumbnail repositories (Nintendo_-_Nintendo_Entertainment_System, ...),
                       which is where libretro actually keeps console artwork
    * DuckDuckGo     - the game description plus the console name, with console-appropriate keywords

The public entry points are search() and download_image().
"""

import json
import re
import urllib.parse
from dataclasses import dataclass
from typing import Optional
from urllib.request import Request

from fast_download import open_url   # Certificate-verified, credential-safe urlopen

# ----------------------------------------------------------------------------------------------------------------------
# Configuration

USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36'
DEFAULT_TIMEOUT = 15
MAX_RESULTS = 48

# Maps the pfeMAME image-option label (as shown above the image thumbnail) to each provider's parameters.
#   ps              - progettosnaps category folder / pack name
#   libretro        - libretro-thumbnails sub-folder for MAME, or None if that category is not available there
#   keyword         - extra keyword(s) appended to the game name for the DuckDuckGo fallback query
#   libretro_system - libretro-thumbnails sub-folder to use for a system program (console / computer software).
#                     Console artwork has no cabinets or marquees, so those physical-artwork categories fall back
#                     to the box art, which is the nearest equivalent for a boxed console game.
#   keyword_system  - DuckDuckGo keyword(s) for a system program; the word 'arcade' would poison those queries.
CATEGORY_MAP = {
    'Snapshots':      {'ps': 'snap',     'libretro': 'Named_Snaps',  'keyword': 'arcade gameplay screenshot',
                       'libretro_system': 'Named_Snaps',   'keyword_system': 'gameplay screenshot'},
    'PCBs':           {'ps': 'pcb',      'libretro': None,           'keyword': 'arcade pcb board',
                       'libretro_system': None,            'keyword_system': 'cartridge pcb board'},
    'Bosses':         {'ps': 'bosses',   'libretro': None,           'keyword': 'arcade boss screenshot',
                       'libretro_system': None,            'keyword_system': 'boss screenshot'},
    'Cabinets':       {'ps': 'cabinets', 'libretro': None,           'keyword': 'arcade cabinet',
                       'libretro_system': 'Named_Boxarts', 'keyword_system': 'box art'},
    'Control Panels': {'ps': 'cpanel',   'libretro': None,           'keyword': 'arcade control panel',
                       'libretro_system': None,            'keyword_system': 'controller gamepad'},
    'Flyers':         {'ps': 'flyers',   'libretro': None,           'keyword': 'arcade flyer',
                       'libretro_system': 'Named_Boxarts', 'keyword_system': 'box art cover'},
    'Title Screens':  {'ps': 'titles',   'libretro': 'Named_Titles', 'keyword': 'arcade title screen',
                       'libretro_system': 'Named_Titles',  'keyword_system': 'title screen'},
    'Ending Screens': {'ps': 'ends',     'libretro': None,           'keyword': 'arcade ending screen',
                       'libretro_system': None,            'keyword_system': 'ending screen'},
    'Marquees':       {'ps': 'marquees', 'libretro': None,           'keyword': 'arcade marquee',
                       'libretro_system': 'Named_Boxarts', 'keyword_system': 'logo box art'},
}

# progettosnaps direct-file URL patterns.  r.mprd.se is progettosnaps' artwork CDN mirror, which exposes the
# individual artwork files keyed by MAME ROM name under /MAME/<category>/.  This is best-effort: if a file or the
# whole mirror stops resolving, the provider simply returns nothing and the other providers take over.  Patterns
# are formatted with {cat} (category folder) and {short} (MAME ROM name).
PROGETTOSNAPS_PATTERNS = [
    'https://r.mprd.se/MAME/{cat}/{short}.png',
]

LIBRETRO_BASE = 'https://raw.githubusercontent.com/libretro-thumbnails/MAME/master/{folder}/{name}.png'

# progettosnaps organises software (console / computer) snaps one level deeper than arcade ones, keyed by the
# software list the item belongs to.  Formatted with {cat} (category folder), {list} (software list name) and
# {short} (software list short name).  Even more best-effort than PROGETTOSNAPS_PATTERNS: the r.mprd.se mirror
# does not currently appear to serve software snaps at all, so this resolves nothing today and costs one HEAD
# request - it is kept because it matches progettosnaps' own pack layout and will start working if the mirror
# adds them.  libretro (below) is the source that actually carries system program artwork.
PROGETTOSNAPS_SOFTWARE_PATTERNS = [
    'https://r.mprd.se/MAME/{cat}/{list}/{short}.png',
]

# libretro-thumbnails keeps one repository per console rather than one folder, so a system program is looked up in
# the repository for its system instead of in the MAME one.
LIBRETRO_SYSTEM_BASE = 'https://raw.githubusercontent.com/libretro-thumbnails/{repo}/master/{folder}/{name}.png'

# Maps a MAME system ROM name (or software list name - the two usually agree) to its libretro-thumbnails
# repository.  Only systems libretro actually carries are listed; anything missing simply falls through to the
# DuckDuckGo provider, so this map can be extended at any time without any other change.
LIBRETRO_SYSTEMS = {
    # Nintendo
    'nes':        'Nintendo_-_Nintendo_Entertainment_System',
    'famicom':    'Nintendo_-_Nintendo_Entertainment_System',
    'fds':        'Nintendo_-_Family_Computer_Disk_System',
    'snes':       'Nintendo_-_Super_Nintendo_Entertainment_System',
    'snespal':    'Nintendo_-_Super_Nintendo_Entertainment_System',
    'sfam':       'Nintendo_-_Super_Nintendo_Entertainment_System',
    'n64':        'Nintendo_-_Nintendo_64',
    'gameboy':    'Nintendo_-_Game_Boy',
    'gbpocket':   'Nintendo_-_Game_Boy',
    'gbcolor':    'Nintendo_-_Game_Boy_Color',
    'gba':        'Nintendo_-_Game_Boy_Advance',
    'vboy':       'Nintendo_-_Virtual_Boy',
    # Sega
    'sms':        'Sega_-_Master_System_-_Mark_III',
    'smspal':     'Sega_-_Master_System_-_Mark_III',
    'smsj':       'Sega_-_Master_System_-_Mark_III',
    'megadriv':   'Sega_-_Mega_Drive_-_Genesis',
    'genesis':    'Sega_-_Mega_Drive_-_Genesis',
    'megadrij':   'Sega_-_Mega_Drive_-_Genesis',
    'gamegear':   'Sega_-_Game_Gear',
    'gamegeaj':   'Sega_-_Game_Gear',
    'sg1000':     'Sega_-_SG-1000',
    'segacd':     'Sega_-_Mega-CD_-_Sega_CD',
    'megacd':     'Sega_-_Mega-CD_-_Sega_CD',
    'saturn':     'Sega_-_Saturn',
    'dc':         'Sega_-_Dreamcast',
    'dcjp':       'Sega_-_Dreamcast',
    'pico':       'Sega_-_PICO',
    '32x':        'Sega_-_32X',
    'sega32x':    'Sega_-_32X',
    # Atari
    'a2600':      'Atari_-_2600',
    'a5200':      'Atari_-_5200',
    'a7800':      'Atari_-_7800',
    'lynx':       'Atari_-_Lynx',
    'jaguar':     'Atari_-_Jaguar',
    'a800':       'Atari_-_8-bit',
    'a800xl':     'Atari_-_8-bit',
    'atarist':    'Atari_-_ST',
    # Other consoles / handhelds
    'pce':        'NEC_-_PC_Engine_-_TurboGrafx_16',
    'tg16':       'NEC_-_PC_Engine_-_TurboGrafx_16',
    'pcecd':      'NEC_-_PC_Engine_CD_-_TurboGrafx-CD',
    'tg16cd':     'NEC_-_PC_Engine_CD_-_TurboGrafx-CD',
    'sgx':        'NEC_-_PC_Engine_SuperGrafx',
    'pc8801':     'NEC_-_PC-8001_-_PC-8801',
    'ngp':        'SNK_-_Neo_Geo_Pocket',
    'ngpc':       'SNK_-_Neo_Geo_Pocket_Color',
    'wswan':      'Bandai_-_WonderSwan',
    'wscolor':    'Bandai_-_WonderSwan_Color',
    'coleco':     'Coleco_-_ColecoVision',
    'intv':       'Mattel_-_Intellivision',
    'vectrex':    'GCE_-_Vectrex',
    'channelf':   'Fairchild_-_Channel_F',
    'odyssey2':   'Magnavox_-_Odyssey2',
    'g7400':      'Philips_-_Videopac',
    'cdimono1':   'Philips_-_CD-i',
    'studio2':    'RCA_-_Studio_II',
    'gamecom':    'Tiger_-_Game.com',
    'supracan':   'Funtech_-_Super_Acan',
    '3do':        'The_3DO_Company_-_3DO',
    'arcadia':    'Emerson_-_Arcadia_2001',
    'crvision':   'VTech_-_CreatiVision',
    # Home computers
    'c64':        'Commodore_-_64',
    'c64p':       'Commodore_-_64',
    'c128':       'Commodore_-_128',
    'vic20':      'Commodore_-_VIC-20',
    'plus4':      'Commodore_-_Plus-4',
    'a500':       'Commodore_-_Amiga',
    'a1200':      'Commodore_-_Amiga',
    'spectrum':   'Sinclair_-_ZX_Spectrum',
    'spec128':    'Sinclair_-_ZX_Spectrum',
    'zx81':       'Sinclair_-_ZX_81',
    'apple2':     'Apple_-_II',
    'apple2e':    'Apple_-_II',
    'msx':        'Microsoft_-_MSX',
    'msx2':       'Microsoft_-_MSX2',
    'msx2p':      'Microsoft_-_MSX2',
    'cpc464':     'Amstrad_-_CPC',
    'cpc6128':    'Amstrad_-_CPC',
    'gx4000':     'Amstrad_-_GX4000',
    'bbcb':       'Acorn_-_BBC_Micro',
    'electron':   'Acorn_-_Electron',
    'x68000':     'Sharp_-_X68000',
    'fmtowns':    'Fujitsu_-_FM_Towns',
    'coco':       'Tandy_-_TRS-80_Color_Computer',
    'oric1':      'Tangerine_-_Oric',
    'svi318':     'Spectravideo_-_SVI-318_-_SVI-328',
}

# GitHub's API for the file list of ONE folder of a repository (rather than the whole tree, which is bigger).
# Formatted with {repo} and {folder}.  Used only when guessing file names has already failed - see
# libretro_system_candidates().
LIBRETRO_TREE_API = 'https://api.github.com/repos/libretro-thumbnails/{repo}/git/trees/master:{folder}'
LIBRETRO_INDEX_TIMEOUT = 60     # These listings run to a few MB for the larger platforms

# Region / set suffixes tried when guessing a libretro thumbnail file name.  libretro names its files after the
# No-Intro / Redump release ('Super Mario Bros. (World)') whereas MAME's software description is usually the bare
# title ('Super Mario Bros.'), so the bare title on its own frequently misses.
LIBRETRO_REGION_SUFFIXES = ['(USA)', '(World)', '(Europe)', '(Japan)', '(USA, Europe)', '(Japan, USA)']


# ----------------------------------------------------------------------------------------------------------------------
@dataclass
class ImageCandidate:
    """A single candidate image returned by a provider."""
    source: str                       # Human-readable provider name, e.g. 'DuckDuckGo'
    full_url: str                     # URL of the full-resolution image (downloaded on selection)
    thumb_url: str = ''               # URL of a smaller preview (falls back to full_url if empty)
    title: str = ''                   # Optional caption / description
    width: Optional[int] = None       # Pixel width if known
    height: Optional[int] = None      # Pixel height if known

    def preview_url(self) -> str:
        return self.thumb_url or self.full_url


# ----------------------------------------------------------------------------------------------------------------------
@dataclass
class SystemContext:
    """
    Identifies a *system program* - a software list item loaded into a system ROM (e.g. 'Super Mario Bros.' on
    'nes') - as opposed to a stand-alone arcade machine.

    When search() is given one of these it looks for artwork of the software item, using the system only to pick
    the right software list / thumbnail repository and to disambiguate the web search.
    """
    machine_name: str = ''      # MAME system ROM name, e.g. 'nes'
    machine_desc: str = ''      # Human-readable system description, e.g. 'Nintendo Entertainment System'
    software_list: str = ''     # Software list the item belongs to, e.g. 'nes' (falls back to machine_name)
    software_short: str = ''    # Software list short name of the item, e.g. 'smb'

    def list_name(self) -> str:
        """The software list to search under, falling back to the machine name when it was not resolved."""
        return (self.software_list or self.machine_name).lower()

    def is_valid(self) -> bool:
        """True once there is enough information to aim a provider at the software rather than the machine."""
        return bool(self.machine_name or self.software_list)

    def libretro_repo(self) -> Optional[str]:
        """The libretro-thumbnails repository for this system, or None if libretro does not carry it."""
        for key in (self.machine_name, self.software_list):
            repo = LIBRETRO_SYSTEMS.get((key or '').lower())
            if repo:
                return repo
        return None


# ----------------------------------------------------------------------------------------------------------------------
# Low level HTTP helpers

def _http(url: str, timeout: int = DEFAULT_TIMEOUT, method: str = 'GET',
          referer: Optional[str] = None, extra_headers: Optional[dict] = None) -> tuple[bytes, int]:
    """
    Perform an HTTP request and return (body_bytes, status_code).  Raises on network errors.
    """
    headers = {'User-Agent': USER_AGENT, 'Accept': '*/*'}
    if referer:
        headers['Referer'] = referer
    if extra_headers:
        headers.update(extra_headers)
    req = Request(url, headers=headers, method=method)
    with open_url(req, timeout=timeout) as response:
        body = response.read() if method != 'HEAD' else b''
        return body, response.getcode()


def _url_exists(url: str, timeout: int = DEFAULT_TIMEOUT) -> bool:
    """Return True if a HEAD (falling back to GET) request for the URL returns a 2xx status."""
    for method in ('HEAD', 'GET'):
        try:
            _, status = _http(url, timeout=timeout, method=method)
            return 200 <= status < 300
        except Exception:
            continue
    return False


def download_image(url: str, timeout: int = DEFAULT_TIMEOUT) -> bytes:
    """Download the raw bytes of an image.  Raises on failure so the caller can report it."""
    body, status = _http(url, timeout=timeout, method='GET')
    if not (200 <= status < 300) or not body:
        raise IOError(f'Unexpected response ({status}) downloading {url}')
    return body


# ----------------------------------------------------------------------------------------------------------------------
# Providers

def progettosnaps_candidates(short_name: str, ps_category: Optional[str]) -> list[ImageCandidate]:
    """
    Best-effort lookup of a single accurate image on progettosnaps.net keyed by the MAME short name.
    Returns at most one candidate; yields nothing if no direct file can be resolved.
    """
    if not short_name or not ps_category:
        return []
    for pattern in PROGETTOSNAPS_PATTERNS:
        url = pattern.format(cat=ps_category, short=short_name)
        if _url_exists(url):
            return [ImageCandidate(source='progettosnaps', full_url=url, thumb_url=url,
                                   title=f'{short_name} ({ps_category})')]
    return []


def progettosnaps_software_candidates(system: SystemContext, ps_category: Optional[str]) -> list[ImageCandidate]:
    """
    Best-effort lookup of a single accurate image for a system program on progettosnaps, which files software
    snaps under the software list the item belongs to.  Returns at most one candidate.
    """
    if not ps_category or not system or not system.software_short or not system.is_valid():
        return []
    list_name = system.list_name()
    if not list_name:
        return []
    for pattern in PROGETTOSNAPS_SOFTWARE_PATTERNS:
        url = pattern.format(cat=ps_category, list=list_name, short=system.software_short.lower())
        if _url_exists(url):
            return [ImageCandidate(source='progettosnaps', full_url=url, thumb_url=url,
                                   title=f'{list_name}/{system.software_short} ({ps_category})')]
    return []


def _libretro_sanitize(name: str) -> str:
    """Apply libretro-thumbnails' filename rules: replace & * / : ` < > ? \\ | with underscores."""
    for ch in '&*/:`<>?\\|':
        name = name.replace(ch, '_')
    return name.strip()


def libretro_candidates(full_name: str, folder: Optional[str]) -> list[ImageCandidate]:
    """
    Guess libretro-thumbnails filenames from the full game description and keep the ones that exist.
    Tries the full name and the name with any trailing parenthetical (set/region info) removed.
    """
    if not full_name or not folder:
        return []

    guesses = [full_name]
    stripped = re.sub(r'\s*\([^)]*\)\s*$', '', full_name).strip()
    if stripped and stripped != full_name:
        guesses.append(stripped)

    results: list[ImageCandidate] = []
    seen: set[str] = set()
    for guess in guesses:
        name = _libretro_sanitize(guess)
        if not name:
            continue
        url = LIBRETRO_BASE.format(folder=folder, name=urllib.parse.quote(name))
        if url in seen:
            continue
        seen.add(url)
        if _url_exists(url):
            results.append(ImageCandidate(source='libretro', full_url=url, thumb_url=url, title=guess))
    return results


# One entry per thumbnail folder actually looked up, so the multi-megabyte listing is fetched at most once per
# session.  Keyed by (repository, folder); only useful results are cached, so a network failure is retried.
_LIBRETRO_INDEX_CACHE: dict[tuple[str, str], dict[str, list[str]]] = {}


def bare_title(name: str) -> str:
    """
    Strip the trailing annotations MAME puts on a description - 'The Alchemist (set 2, gold inlay)' becomes
    'The Alchemist'.  Those set / revision notes mean nothing to an image search and only narrow it wrongly.
    """
    return re.sub(r'(\s*\([^)]*\))+$', '', name).strip() or name


def _normalise_title(name: str) -> str:
    """
    Reduce a title to a form that can be compared across naming conventions.  MAME, No-Intro and TOSEC annotate
    the same game very differently - 'The Alchemist (set 1)', 'Alchemist, The (USA)' and
    'Alchemist (1983)(Imagine)[a2].png' are all the same thing - so the year, publisher, region, dump flags,
    leading or trailing article and all punctuation are removed, leaving 'alchemist' in each case.
    """
    name = re.sub(r'\.(png|jpg|jpeg)$', '', name, flags=re.IGNORECASE)      # File extension
    name = re.sub(r'[(\[{][^)\]}]*[)\]}]', ' ', name)                       # (1983)(Imagine)[a2], (set 1), ...
    name = name.lower().strip()
    name = re.sub(r'^(the|a|an)\s+', '', name)                              # Leading article
    name = re.sub(r',\s*(the|a|an)\s*$', '', name)                         # Trailing article, No-Intro style
    return re.sub(r'[^a-z0-9]+', ' ', name).strip()


def libretro_index(repo: str, folder: str, logger=None) -> dict[str, list[str]]:
    """
    Fetch the list of files in one libretro thumbnail folder and index it by normalised title.

    This is the accurate but expensive way to find a thumbnail, so it is only used once guessing has failed, and
    the result is cached for the rest of the session because the same platform is usually searched repeatedly.

    :return: {normalised title: [file name, ...]}, empty if the listing could not be fetched.
    """
    key = (repo, folder)
    if key in _LIBRETRO_INDEX_CACHE:
        return _LIBRETRO_INDEX_CACHE[key]

    index: dict[str, list[str]] = {}
    try:
        url = LIBRETRO_TREE_API.format(repo=repo, folder=urllib.parse.quote(folder))
        body, status = _http(url, timeout=LIBRETRO_INDEX_TIMEOUT)
        if 200 <= status < 300:
            for entry in json.loads(body.decode('utf-8', 'replace')).get('tree', []):
                file_name = entry.get('path', '')
                if file_name.lower().endswith('.png'):
                    index.setdefault(_normalise_title(file_name), []).append(file_name)
    except Exception as exc:
        # Anything at all (rate limit, offline, renamed branch) just means no index; the caller falls through
        # to the web search.  Not cached, so a transient failure does not disable this for the whole session.
        if logger:
            logger.warning(f'Could not fetch the libretro listing for {repo}/{folder}: {exc}')
        return {}

    if index:
        _LIBRETRO_INDEX_CACHE[key] = index
    return index


def _no_intro_variants(title: str) -> list[str]:
    """
    No-Intro moves a leading article to the end of a title ('The Legend of Zelda' becomes 'Legend of Zelda, The')
    where MAME leaves it in place, so both forms are worth trying.
    """
    variants = [title]
    match = re.match(r'^(The|A|An)\s+(.+)$', title, re.IGNORECASE)
    if match:
        variants.append(f'{match.group(2)}, {match.group(1)}')
    return variants


def _index_candidates(index: dict[str, list[str]], full_name: str, repo: str, folder: str,
                      max_results: int) -> list[ImageCandidate]:
    """Turn the entries of a libretro folder index that match full_name into candidates."""
    results: list[ImageCandidate] = []
    for file_name in index.get(_normalise_title(full_name), [])[:max_results]:
        title = file_name.rsplit('.', 1)[0]     # LIBRETRO_SYSTEM_BASE appends the .png itself
        url = LIBRETRO_SYSTEM_BASE.format(repo=repo, folder=folder, name=urllib.parse.quote(title))
        results.append(ImageCandidate(source='libretro', full_url=url, thumb_url=url, title=title))
    return results


def libretro_system_candidates(full_name: str, folder: Optional[str], repo: Optional[str],
                               max_results: int = 6, logger=None) -> list[ImageCandidate]:
    """
    Look for a system program in the libretro-thumbnails repository for its console.

    Two passes, cheapest first:

    1. Guess the file name.  Cartridge consoles are filed under No-Intro names, so MAME's
       'Super Mario Bros. (Europe, rev. A)' is a short hop from libretro's 'Super Mario Bros. (World)'.  This
       tries the name as given, the bare title, the No-Intro article ordering of it ('Legend of Zelda, The') and
       each of those with the common region suffixes: at most fifteen HEAD requests, stopping early once enough
       matches are found.
    2. If nothing matched, fetch the folder's actual file list and match against that.  Home computer platforms
       are filed under TOSEC names carrying a year and publisher - MAME's 'The Alchemist (set 1)' lives under
       'Alchemist (1983)(Imagine).png' - which guessing can never reach.  The listing costs one request of a few
       megabytes, so it is only done on a miss, and is cached for the session.

    Once that listing has been fetched it is both free and exact, so a later search of the same folder consults
    it up front and skips the guessing entirely.
    """
    if not full_name or not folder or not repo:
        return []

    cached = _LIBRETRO_INDEX_CACHE.get((repo, folder))
    if cached is not None:
        matched = _index_candidates(cached, full_name, repo, folder, max_results)
        if matched:
            return matched

    base = bare_title(full_name)

    guesses = [full_name]
    for variant in _no_intro_variants(base):
        if variant != full_name:
            guesses.append(variant)
        guesses.extend(f'{variant} {suffix}' for suffix in LIBRETRO_REGION_SUFFIXES)

    results: list[ImageCandidate] = []
    seen: set[str] = set()
    for guess in guesses:
        name = _libretro_sanitize(guess)
        if not name:
            continue
        url = LIBRETRO_SYSTEM_BASE.format(repo=repo, folder=folder, name=urllib.parse.quote(name))
        if url in seen:
            continue
        seen.add(url)
        if _url_exists(url):
            results.append(ImageCandidate(source='libretro', full_url=url, thumb_url=url, title=guess))
            if len(results) >= max_results:
                break

    if results:
        return results

    # Nothing guessable: fall back to matching the folder's real contents.
    return _index_candidates(libretro_index(repo, folder, logger), full_name, repo, folder, max_results)


def _extract_vqd(html: str) -> Optional[str]:
    """Pull DuckDuckGo's per-query vqd token out of the search results page HTML."""
    for pattern in (r'vqd=["\']([\d-]+)["\']', r'vqd=([\d-]+)&', r'vqd=["\']([^"\']+)["\']'):
        match = re.search(pattern, html)
        if match:
            return match.group(1)
    return None


def duckduckgo_candidates(query: str, max_results: int = MAX_RESULTS) -> list[ImageCandidate]:
    """
    Query DuckDuckGo's unofficial image endpoint.  Unofficial and best-effort: any failure (token missing,
    rate-limited, JSON change) returns an empty list rather than raising.
    """
    if not query:
        return []
    try:
        token_url = 'https://duckduckgo.com/?' + urllib.parse.urlencode({'q': query, 'iax': 'images', 'ia': 'images'})
        body, _ = _http(token_url)
        vqd = _extract_vqd(body.decode('utf-8', 'replace'))
        if not vqd:
            return []

        api_url = 'https://duckduckgo.com/i.js?' + urllib.parse.urlencode({
            'l': 'us-en', 'o': 'json', 'q': query, 'vqd': vqd, 'f': ',,,', 'p': '1',
        })
        # The i.js endpoint rejects plain requests with 403; it expects an XHR-style request.
        body, _ = _http(api_url, referer='https://duckduckgo.com/', extra_headers={
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'X-Requested-With': 'XMLHttpRequest',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin',
        })
        data = json.loads(body.decode('utf-8', 'replace'))
    except Exception:
        return []

    results: list[ImageCandidate] = []
    for item in data.get('results', [])[:max_results]:
        image = item.get('image', '')
        if not image:
            continue
        results.append(ImageCandidate(
            source='DuckDuckGo',
            full_url=image,
            thumb_url=item.get('thumbnail', ''),
            title=item.get('title', ''),
            width=item.get('width'),
            height=item.get('height'),
        ))
    return results


# ----------------------------------------------------------------------------------------------------------------------
# Orchestration

def search(short_name: str, full_name: str, category_label: str,
           logger=None, max_results: int = MAX_RESULTS,
           system: Optional[SystemContext] = None) -> list[ImageCandidate]:
    """
    Run all applicable providers in preferred order and return a de-duplicated candidate list.

    :param short_name:     MAME short / ROM name (e.g. 'galaxian'), or the software list short name (e.g. 'smb')
                           when searching for a system program - used by progettosnaps.
    :param full_name:      Full game description (e.g. 'Galaxian (Namco set 1)' or 'Super Mario Bros.') - used by
                           libretro and DuckDuckGo.
    :param category_label: The pfeMAME image-option label, e.g. 'Snapshots', 'Cabinets'.
    :param logger:         Optional logger; provider errors are logged but never raised to the caller.
    :param max_results:    Cap on the number of returned candidates.
    :param system:         Set when the selected ROM is a system program rather than an arcade machine, so that
                           the providers look for the software item and not for the console it runs on.
    """
    info = CATEGORY_MAP.get(category_label, {'ps': None, 'libretro': None, 'keyword': category_label})
    is_system = bool(system and system.is_valid())
    candidates: list[ImageCandidate] = []

    def run(name, fn):
        try:
            candidates.extend(fn())
        except Exception as exc:  # Providers must never break the whole search
            if logger:
                logger.warning(f'Online image provider {name} failed: {exc}')

    if is_system:
        # 1. progettosnaps, keyed by software list + software short name
        run('progettosnaps', lambda: progettosnaps_software_candidates(system, info['ps']))
        # 2. The libretro thumbnail repository for this console, for the categories it carries
        run('libretro', lambda: libretro_system_candidates(full_name, info.get('libretro_system'),
                                                           system.libretro_repo(), logger=logger))
        # 3. Generic catch-all fallback, qualified with the console name so the results are about the game as it
        #    appeared on that system rather than any other release of it.  MAME's set annotations are dropped:
        #    'The Alchemist (set 2, gold inlay) ZX Spectrum' finds far less than 'The Alchemist ZX Spectrum'.
        query = ' '.join(part for part in (bare_title(full_name), system.machine_desc,
                                           info.get('keyword_system') or info['keyword']) if part)
    else:
        # 1. Accurate, MAME-keyed source first
        run('progettosnaps', lambda: progettosnaps_candidates(short_name, info['ps']))
        # 2. libretro for the categories it actually carries
        run('libretro', lambda: libretro_candidates(full_name, info['libretro']))
        # 3. Generic catch-all fallback
        query = ' '.join(part for part in (full_name, info['keyword']) if part)

    run('duckduckgo', lambda: duckduckgo_candidates(query, max_results))

    # De-duplicate on the full-resolution URL while preserving provider order
    seen: set[str] = set()
    unique: list[ImageCandidate] = []
    for candidate in candidates:
        if candidate.full_url and candidate.full_url not in seen:
            seen.add(candidate.full_url)
            unique.append(candidate)

    return unique[:max_results]
