#!/usr/bin/env python3

# ----------------------------------------------------------------------------------------------------------------------
# online_rom_search.py

"""
Online ROM ZIP search providers for the 'Search for ROM online' right-click feature.

Like online_image_search, this module is deliberately free of any wxPython / GUI code so it can be unit-tested and
run on a background thread.  It locates candidate ROM ZIP files for a MAME ROM (keyed by the MAME short name, which
is the ZIP file's base name) from a selectable set of sources:

    archive.org (no login) - freely-downloadable per-game / smaller items.  The big "full romset" collections are
                             access-restricted (need a login) and are skipped here.  De-facto includes a noisy
                             DuckDuckGo direct-'.zip' web fallback.
    archive.org (logged in) - same search but INCLUDING the access-restricted full romset collections; downloads use
                             an 'Authorization: LOW key:secret' header obtained from the user's archive.org account.
    retroroms.net          - private mirror keyed by MAME version, each file behind HTTP Basic Auth (nginx).  It only
                             keeps the latest MAME release, so an older MAME falls back to that latest set.

NOTE: the legality of downloading any given ROM depends on the user owning the original and on local law.  This
module only locates files the user asks for; it makes no judgement about which ROMs they are entitled to download.

Credentials are supplied by the caller (see rom_credentials.py); this module never reads or stores them.

The public entry points are search(), download_rom(), and the per-source Test helpers archive_check()/
retroroms_check().
"""

import base64
import json
import logging
import re
import time
import urllib.error
import urllib.parse
from dataclasses import dataclass
from typing import Optional
from urllib.request import Request

from fast_download import open_url   # Certificate-verified, credential-safe urlopen

# Log through pfeMAME's shared logger (named '>') so messages land in logfile.log even when a caller doesn't pass
# its own logger.  getLogger('>') returns the same instance the app configures in functions.setup_logging.
_MODULE_LOGGER = logging.getLogger('>')

# ----------------------------------------------------------------------------------------------------------------------
# Configuration

USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36'
DEFAULT_TIMEOUT = 15
METADATA_TIMEOUT = 20       # Item metadata file-lists can be a few MB for full romsets
MAX_RESULTS = 24
ARCHIVE_ITEMS_TO_SCAN = 30  # How many archive.org search hits to consider for the ROM
ARCHIVE_ENOUGH = 8          # Stop fetching more file-lists once we have collected this many candidates
ARCHIVE_TIME_BUDGET = 60    # Seconds an archive.org search may spend checking items before it settles for what it has

# ----------------------------------------------------------------------------------------------------------------------
# Source registry.  Each download source the GUI can offer.  'needs_credentials' drives the source-selection dialog
# (a source is only selectable once credentials are stored).
SOURCE_ARCHIVE_ANON = 'archive_anon'
SOURCE_ARCHIVE_AUTH = 'archive_auth'
SOURCE_RETROROMS = 'retroroms'

ROM_SOURCES = [
    {'key': SOURCE_ARCHIVE_ANON, 'label': 'archive.org (no login)',  'needs_credentials': False},
    {'key': SOURCE_ARCHIVE_AUTH, 'label': 'archive.org (logged in)', 'needs_credentials': True},
    {'key': SOURCE_RETROROMS,    'label': 'retroroms.net',           'needs_credentials': True},
]

# archive.org login: exchange email/password for S3-style keys, then send them as an 'Authorization: LOW key:secret'
# header on download requests.  This is archive.org's documented keyless-client login endpoint.
ARCHIVE_LOGIN = 'https://archive.org/services/xauthn/?op=login'

# retroroms.net private download mirror.  Files live under a per-MAME-version folder, e.g.
# https://bda.retroroms.net/downloads/mame/mame0288-full/galaxian.zip .  Each file is gated by HTTP Basic Auth
# (nginx) on the bda host - the browser's credential popup - so we send 'Authorization: Basic ...'.  An
# unauthenticated request answers 401 (or 200 that bounces to an authentication-failure page).
RETROROMS_BASE = 'https://bda.retroroms.net/downloads/mame'


def source_label(key: str) -> str:
    for src in ROM_SOURCES:
        if src['key'] == key:
            return src['label']
    return key


def source_needs_credentials(key: str) -> bool:
    for src in ROM_SOURCES:
        if src['key'] == key:
            return src['needs_credentials']
    return False

def N_(text: str) -> str:
    """Mark a progress message for translation; the GUI translates it when it is shown."""
    return text


class SearchCancelled(Exception):
    """Raised when the caller cancels a search or download."""


class Reporter:
    """
    Passes step-by-step progress messages to the caller and checks for cancellation between steps.

    progress(message_format, *args, **kwargs) is called with an untranslated format string (marked with N_) and
    its arguments; cancel is a threading.Event - once it is set, the next step raises SearchCancelled.
    """

    def __init__(self, progress=None, cancel=None):
        self._progress = progress
        self._cancel = cancel

    def check(self) -> None:
        if self._cancel is not None and self._cancel.is_set():
            raise SearchCancelled()

    def __call__(self, message: str, *args, **kwargs) -> None:
        self.check()
        if self._progress:
            self._progress(message, *args, **kwargs)


_NO_REPORT = Reporter()


# Sub-folder name fragments that mean a '<short>.zip' is NOT a playable ROM (it's support media that happens to be
# named after the ROM, e.g. artwork or samples).  Used to reject false positives within an item's file list.
NON_ROM_PATH_HINTS = ('artwork', 'sample', 'snap', 'chd', 'cheat', 'support', 'dats', 'hash', 'nvram')

# archive.org public APIs (no key required).  The big "full romset" collection items are nearly all flagged
# access-restricted-item (they require a logged-in account to download), so we instead surface the freely
# downloadable per-game / smaller items and skip any item whose metadata is access-restricted.
ARCHIVE_SEARCH = 'https://archive.org/advancedsearch.php'
ARCHIVE_METADATA_SUB = 'https://archive.org/metadata/{identifier}/metadata'  # Lightweight: metadata dict only
ARCHIVE_FILES_SUB = 'https://archive.org/metadata/{identifier}/files'        # The file list only
ARCHIVE_DOWNLOAD = 'https://archive.org/download/{identifier}/{name}'


# ----------------------------------------------------------------------------------------------------------------------
@dataclass
class RomCandidate:
    """A single candidate ROM ZIP returned by a provider."""
    source: str                       # Human-readable provider name, e.g. 'archive.org'
    download_url: str                 # URL of the ZIP file (downloaded on selection)
    filename: str                     # Suggested local file name, e.g. 'galaxian.zip'
    item: str = ''                    # Human-readable collection / page title the file came from
    size: Optional[int] = None        # File size in bytes if known
    auth_header: Optional[str] = None  # Authorization header to replay when downloading (e.g. archive.org LOW)
    cookie_header: Optional[str] = None  # Cookie header to replay when downloading (e.g. retroroms session)

    # Filled in by the caller's MAME-validation pass (see pfemame._validate_rom_candidates):
    local_path: str = ''              # Path to an already-downloaded copy (set during validation)
    verify_status: str = ''           # '', 'good', 'bad', 'best available', 'error'
    verify_good: Optional[int] = None  # Count of ROM files that matched (verifyroms)
    verify_bad: Optional[int] = None   # Count of ROM files missing / wrong (verifyroms)


def human_size(num: Optional[int]) -> str:
    """Format a byte count for display, e.g. 1536 -> '1.5 KB'.  Returns '' for an unknown size."""
    if not num or num < 0:
        return ''
    value = float(num)
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if value < 1024 or unit == 'TB':
            return f'{value:.0f} {unit}' if unit == 'B' else f'{value:.1f} {unit}'
        value /= 1024
    return ''


# ----------------------------------------------------------------------------------------------------------------------
# Low level HTTP helpers

def _http(url: str, timeout: int = DEFAULT_TIMEOUT, method: str = 'GET',
          referer: Optional[str] = None, extra_headers: Optional[dict] = None) -> tuple[bytes, int]:
    """Perform an HTTP request and return (body_bytes, status_code).  Raises on network errors."""
    headers = {'User-Agent': USER_AGENT, 'Accept': '*/*'}
    if referer:
        headers['Referer'] = referer
    if extra_headers:
        headers.update(extra_headers)
    req = Request(url, headers=headers, method=method)
    with open_url(req, timeout=timeout) as response:
        body = response.read() if method != 'HEAD' else b''
        return body, response.getcode()


# Substrings that, when they appear in a request's final (post-redirect) URL, mean we were bounced to a login /
# auth-failure page rather than served the real file - so the "file" does not actually exist for us.
AUTH_FAILURE_URL_HINTS = ('authentication-failure', 'login', 'member.php', 'signin', 'account/login')


def _basic_auth_header(username: str, password: str) -> str:
    """Build an HTTP Basic 'Authorization' header value from a username and password."""
    token = base64.b64encode(f'{username}:{password}'.encode('utf-8')).decode('ascii')
    return f'Basic {token}'


def _probe(url: str, auth_header: Optional[str] = None, cookie_header: Optional[str] = None,
           timeout: int = DEFAULT_TIMEOUT) -> tuple[bool, Optional[int]]:
    """
    Check whether a URL points at a real downloadable file.  Returns (exists, size_in_bytes).  Uses HEAD first
    (cheap) and falls back to a ranged GET for servers that don't answer HEAD.  size is None if not reported.

    Guards against sites (e.g. retroroms.net) that answer an unauthenticated request with HTTP 200 but redirect to
    a login / auth-failure page: if the final URL looks like such a page, the file is treated as not available.
    """
    base = {'User-Agent': USER_AGENT, 'Accept': '*/*'}
    if auth_header:
        base['Authorization'] = auth_header
    if cookie_header:
        base['Cookie'] = cookie_header
    for method, extra in (('HEAD', {}), ('GET', {'Range': 'bytes=0-0'})):
        try:
            req = Request(url, headers={**base, **extra}, method=method)
            with open_url(req, timeout=timeout) as response:
                status = response.getcode()
                if not (200 <= status < 300):
                    continue
                final_url = response.geturl().lower()
                if final_url != url.lower() and any(hint in final_url for hint in AUTH_FAILURE_URL_HINTS):
                    return False, None
                content_type = (response.getheader('Content-Type') or '').lower()
                # A real ZIP won't be served as text/html - an html body here means a login/error page.
                if 'text/html' in content_type:
                    return False, None
                size = None
                content_range = response.getheader('Content-Range')  # 'bytes 0-0/123456'
                if content_range and '/' in content_range:
                    tail = content_range.rsplit('/', 1)[-1]
                    if tail.isdigit():
                        size = int(tail)
                if size is None:
                    length = response.getheader('Content-Length')
                    if length and length.isdigit() and method == 'HEAD':
                        size = int(length)
                return True, size
        except Exception:
            continue
    return False, None


def download_rom(url: str, dest_path: str, timeout: int = DEFAULT_TIMEOUT,
                 progress=None, auth_header: Optional[str] = None, cookie_header: Optional[str] = None,
                 cancel=None) -> int:
    """
    Stream a ROM ZIP to dest_path.  Returns the number of bytes written.  Raises on failure so the caller can
    report it.  If supplied, progress(bytes_done, total_or_None) is called periodically for UI feedback.
    auth_header / cookie_header, if given, are replayed as the 'Authorization' / 'Cookie' headers (authed sources).
    cancel, if given, is a threading.Event; setting it stops the download with SearchCancelled.
    """
    headers = {'User-Agent': USER_AGENT, 'Accept': '*/*'}
    if auth_header:
        headers['Authorization'] = auth_header
    if cookie_header:
        headers['Cookie'] = cookie_header
    _MODULE_LOGGER.info('Downloading ROM from %s (auth=%s, cookie=%s) -> %s',
                        url, 'yes' if auth_header else 'no', 'yes' if cookie_header else 'no', dest_path)
    req = Request(url, headers=headers, method='GET')
    written = 0
    with open_url(req, timeout=timeout) as response:
        status = response.getcode()
        if not (200 <= status < 300):
            raise IOError(f'Unexpected response ({status}) downloading {url}')
        # Guard against a stale/invalid session: the server may answer 200 but redirect to a login/auth-failure
        # page (HTML) instead of the file.  Refuse to save that as a ROM.
        final_url = response.geturl().lower()
        if final_url != url.lower() and any(hint in final_url for hint in AUTH_FAILURE_URL_HINTS):
            raise IOError('Download was redirected to a login / authentication-failure page (not signed in?)')
        if 'text/html' in (response.getheader('Content-Type') or '').lower():
            raise IOError('Server returned an HTML page instead of a ROM file (not signed in?)')
        length = response.getheader('Content-Length')
        total = int(length) if length and length.isdigit() else None
        with open(dest_path, 'wb') as handle:
            while True:
                if cancel is not None and cancel.is_set():
                    raise SearchCancelled()
                chunk = response.read(65536)
                if not chunk:
                    break
                handle.write(chunk)
                written += len(chunk)
                if progress:
                    progress(written, total)
    if written == 0:
        raise IOError(f'No data received downloading {url}')
    return written


# ----------------------------------------------------------------------------------------------------------------------
# Providers

def _archive_search_items(short_name: str, logger=None, report: Reporter = _NO_REPORT) -> list[dict]:
    """Search archive.org for items that might carry this ROM, returned as a list of {'identifier','title'} dicts."""
    report(N_('Searching archive.org for {}.zip'), short_name)
    # Bias to MAME software items and key on the short (ROM) name; the per-item file-basename check is the real
    # filter, so this query only has to surface candidate items in roughly the right ballpark.
    query = f'{short_name} AND mame AND mediatype:software'

    params = urllib.parse.urlencode({
        'q': query,
        'fl[]': 'identifier',
        'rows': str(ARCHIVE_ITEMS_TO_SCAN),
        'page': '1',
        'output': 'json',
        'sort[]': 'downloads desc',
    }, doseq=True)
    # urlencode collapses repeated fl[] keys; add the title field explicitly so we get a display name back too.
    params = params.replace('fl%5B%5D=identifier', 'fl%5B%5D=identifier&fl%5B%5D=title')
    try:
        body, _status = _http(f'{ARCHIVE_SEARCH}?{params}')
        return json.loads(body.decode('utf-8', 'replace')).get('response', {}).get('docs', [])
    except Exception as exc:
        if logger:
            logger.warning(f'archive.org search failed: {exc}')
        return []


def _archive_is_restricted(identifier: str) -> bool:
    """Cheap check of just the item's metadata dict for the access-restricted flag (no large file list fetched)."""
    try:
        body, _status = _http(ARCHIVE_METADATA_SUB.format(identifier=urllib.parse.quote(identifier)), timeout=DEFAULT_TIMEOUT)
        result = json.loads(body.decode('utf-8', 'replace')).get('result', {})
        return bool(result.get('access-restricted-item'))
    except Exception:
        # If we can't tell, assume it's restricted so we don't offer a download that will 401.
        return True


def _archive_best_zip(identifier: str, wanted: str, logger=None) -> Optional[dict]:
    """
    From an item's file list, return the best file whose basename is '<short>.zip' (preferring a path under a 'rom'
    folder and rejecting support media like artwork/samples), or None.  Returned dict has 'name' and 'size'.
    """
    try:
        body, _status = _http(ARCHIVE_FILES_SUB.format(identifier=urllib.parse.quote(identifier)),
                              timeout=METADATA_TIMEOUT)
        files = json.loads(body.decode('utf-8', 'replace')).get('result', [])
    except Exception as exc:
        if logger:
            logger.warning(f'archive.org files for {identifier} failed: {exc}')
        return None

    best = None
    best_score = None
    for file_info in files:
        name = file_info.get('name', '')
        if name.rsplit('/', 1)[-1].lower() != wanted:
            continue
        folders = name.rsplit('/', 1)[0].lower() if '/' in name else ''
        if any(hint in folders for hint in NON_ROM_PATH_HINTS):
            continue
        score = 1 if 'rom' in folders else 0
        if best_score is None or score > best_score:
            best, best_score = file_info, score
    return best


def _archive_candidates(short_name: str, logger=None, include_restricted: bool = False,
                        auth_header: Optional[str] = None, source: str = 'archive.org',
                        report: Reporter = _NO_REPORT) -> list[RomCandidate]:
    """
    Shared archive.org search.  Matches '<short>.zip' by file *basename* (the per-ROM ZIPs often live in a
    sub-folder, e.g. 'roms/galaxian.zip').  When include_restricted is False the access-restricted full-romset
    items (which need a login) are skipped; when True they are kept and auth_header is attached so the authenticated
    downloader can fetch them.  Gives up checking further items after ARCHIVE_TIME_BUDGET seconds.
    """
    if not short_name:
        return []

    wanted = f'{short_name.lower()}.zip'
    results: list[RomCandidate] = []
    docs = _archive_search_items(short_name, logger, report)
    started = time.monotonic()
    for number, doc in enumerate(docs, 1):
        identifier = doc.get('identifier')
        if not identifier:
            continue
        if time.monotonic() - started > ARCHIVE_TIME_BUDGET:
            (logger or _MODULE_LOGGER).info('%s: stopped after %s seconds having checked %s of %s items',
                                            source, ARCHIVE_TIME_BUDGET, number - 1, len(docs))
            break

        title = doc.get('title') or identifier
        if isinstance(title, list):
            title = title[0] if title else identifier

        # Precision filter: only trust items that actually look like MAME / arcade ROM items.  archive.org is full
        # of unrelated user uploads (e.g. a 'Pacman.zip' VR demo) that share the ROM's name but are not the romset.
        haystack = f'{identifier} {title}'.lower()
        if 'mame' not in haystack and 'arcade' not in haystack:
            continue

        report(N_('Checking {source} item {number} of {count} ({found} found so far)'), source=source,
               number=number, count=len(docs), found=len(results))
        if not include_restricted and _archive_is_restricted(identifier):
            continue

        best = _archive_best_zip(identifier, wanted, logger)
        if best is None:
            continue

        name = best.get('name', '')
        size = best.get('size')
        url = ARCHIVE_DOWNLOAD.format(identifier=urllib.parse.quote(identifier),
                                      name=urllib.parse.quote(name, safe='/'))
        results.append(RomCandidate(
            source=source, download_url=url, filename=f'{short_name}.zip',
            item=str(title), size=int(size) if str(size).isdigit() else None, auth_header=auth_header))

        if len(results) >= ARCHIVE_ENOUGH:
            break
    return results


def archive_candidates(short_name: str, logger=None, report: Reporter = _NO_REPORT) -> list[RomCandidate]:
    """Anonymous archive.org search: freely-downloadable items only (restricted full sets are skipped)."""
    return _archive_candidates(short_name, logger, include_restricted=False, source='archive.org', report=report)


def archive_login(username: str, password: str, logger=None) -> Optional[str]:
    """
    Log in to archive.org and return an 'Authorization: LOW key:secret' header value, or None on failure.  Uses
    archive.org's documented keyless-client login endpoint which exchanges email/password for S3-style keys.
    """
    if not username or not password:
        return None
    try:
        data = urllib.parse.urlencode({'email': username, 'password': password}).encode('utf-8')
        req = Request(ARCHIVE_LOGIN, data=data, method='POST', headers={
            'User-Agent': USER_AGENT,
            'Content-Type': 'application/x-www-form-urlencoded',
        })
        with open_url(req, timeout=DEFAULT_TIMEOUT) as response:
            payload = json.loads(response.read().decode('utf-8', 'replace'))
        if payload.get('success'):
            s3 = payload.get('values', {}).get('s3', {})
            access, secret = s3.get('access'), s3.get('secret')
            if access and secret:
                return f'LOW {access}:{secret}'
        if logger:
            logger.warning(f'archive.org login rejected: {payload.get("error") or payload.get("values")}')
    except Exception as exc:
        if logger:
            logger.warning(f'archive.org login failed: {exc}')
    return None


def archive_auth_candidates(short_name: str, username: str, password: str, logger=None,
                            report: Reporter = _NO_REPORT) -> list[RomCandidate]:
    """Authenticated archive.org search: includes the access-restricted full romset collections."""
    report(N_('Logging in to archive.org'))
    auth = archive_login(username, password, logger)
    if not auth:
        report(N_('archive.org login failed'))
        return []
    return _archive_candidates(short_name, logger, include_restricted=True, auth_header=auth,
                               source='archive.org (login)', report=report)


def archive_check(username: str, password: str, logger=None) -> tuple[bool, str]:
    """Test archive.org credentials for the dialog's Test button.  Returns (ok, message)."""
    log = logger or _MODULE_LOGGER
    log.info('archive.org: testing credentials for "%s"', username)
    if archive_login(username, password, logger) is not None:
        log.info('archive.org: login test succeeded')
        return True, 'Login successful'
    log.info('archive.org: login test failed')
    return False, 'Login failed - check your archive.org email and password'


def _retroroms_set_folder(mame_version: str) -> str:
    """Map a MAME version like '0.288' to retroroms' set folder name 'mame0288-full'."""
    return f"mame{(mame_version or '').replace('.', '')}-full"


RETROROMS_SET_PATTERN = re.compile(r'href="(mame(\d+)-full)/"')


def _retroroms_available_sets(logger=None) -> list[str]:
    """
    The full-set folders currently on the mirror, newest first (e.g. ['mame0289-full']), read from the mirror's
    public directory index.  Returns [] if the index can't be read.
    """
    log = logger or _MODULE_LOGGER
    try:
        body, _status = _http(f'{RETROROMS_BASE}/')
    except Exception as exc:
        log.warning('retroroms: could not read the set index: %s', exc)
        return []
    found = {name: int(number) for name, number in RETROROMS_SET_PATTERN.findall(body.decode('utf-8', 'replace'))}
    return sorted(found, key=found.get, reverse=True)


def _retroroms_pick_folder(mame_version: str, logger=None) -> tuple[str, bool]:
    """
    Choose the retroroms set folder to use: the one matching the user's MAME version if the mirror has it,
    otherwise the newest set on the mirror (retroroms only keeps the latest release, so an older MAME would never
    find a match - the newer ROMs very often still work).  Returns (folder, is_exact_version_match).
    """
    wanted = _retroroms_set_folder(mame_version)
    available = _retroroms_available_sets(logger)
    if not available or wanted in available:
        return wanted, True
    (logger or _MODULE_LOGGER).info('retroroms: no set for MAME %s on the mirror, using the latest set %s',
                                    mame_version, available[0])
    return available[0], False


def _retroroms_request(url: str, auth_header: str, method: str = 'GET',
                       ranged: bool = True) -> tuple[int, str, Optional[int]]:
    """
    Make a single authenticated request to the retroroms mirror.  Returns (status, content_type, size).
    On an HTTP error status, returns that status (urllib raises HTTPError which we convert).  size is the full
    file size when known.
    """
    headers = {'User-Agent': USER_AGENT, 'Accept': '*/*', 'Authorization': auth_header}
    if ranged and method == 'GET':
        headers['Range'] = 'bytes=0-0'
    request = Request(url, headers=headers, method=method)
    try:
        with open_url(request, timeout=DEFAULT_TIMEOUT) as response:
            status = response.getcode()
            content_type = (response.getheader('Content-Type') or '').lower()
            final_url = response.geturl().lower()
            # A 200 that bounced to an auth-failure / login page is really "not authorised".
            if final_url != url.lower() and any(hint in final_url for hint in AUTH_FAILURE_URL_HINTS):
                return 401, content_type, None
            size = None
            content_range = response.getheader('Content-Range')
            if content_range and '/' in content_range:
                tail = content_range.rsplit('/', 1)[-1]
                if tail.isdigit():
                    size = int(tail)
            elif status == 200:
                length = response.getheader('Content-Length')
                if length and length.isdigit():
                    size = int(length)
            return status, content_type, size
    except urllib.error.HTTPError as exc:
        return exc.code, '', None


def retroroms_candidates(short_name: str, mame_version: str, username: str, password: str,
                         logger=None, report: Reporter = _NO_REPORT) -> list[RomCandidate]:
    """
    Look up '<short>.zip' on the retroroms.net private mirror, in the set for the user's MAME version or, when the
    mirror no longer has that version, in its latest set (see _retroroms_pick_folder).  The mirror gates each
    file behind HTTP Basic Auth (nginx), so we send 'Authorization: Basic ...' and keep it on the candidate to
    replay at download time.  Returns at most one candidate.
    """
    log = logger or _MODULE_LOGGER
    if not short_name or not mame_version or not username or not password:
        return []
    report(N_('Connecting to retroroms.net'))
    folder, exact = _retroroms_pick_folder(mame_version, log)
    url = f'{RETROROMS_BASE}/{folder}/{urllib.parse.quote(short_name)}.zip'
    auth = _basic_auth_header(username, password)
    report(N_('Logging in to retroroms.net and looking for {rom}.zip in {folder}'), rom=short_name, folder=folder)
    log.info('retroroms: probing %s', url)
    status, content_type, size = _retroroms_request(url, auth)
    if status == 401:
        log.warning('retroroms: %s -> 401 (bad credentials or not authorised)', url)
        return []
    if status == 404:
        log.info('retroroms: %s -> 404 (ROM not in this set)', url)
        return []
    if not (200 <= status < 300) or 'text/html' in content_type:
        log.info('retroroms: %s -> HTTP %s, content-type %s (not a ROM)', url, status, content_type or '?')
        return []
    log.info('retroroms: found %s (size=%s)', url, size)
    item = folder if exact else f'{folder} (newer than MAME {mame_version})'
    return [RomCandidate(source='retroroms.net', download_url=url, filename=f'{short_name}.zip',
                         item=item, size=size, auth_header=auth)]


def retroroms_check(username: str, password: str, mame_version: str = '', logger=None) -> tuple[bool, str]:
    """Test retroroms.net credentials for the dialog's Test button.  Returns (ok, message)."""
    log = logger or _MODULE_LOGGER
    if not username or not password:
        return False, 'Enter a username and password'
    if not mame_version:
        return False, 'Set your MAME version first, then test again'
    log.info('retroroms: testing credentials for "%s" (MAME %s)', username, mame_version)

    # One authenticated probe of a near-universal ROM.  200 = authorised + file served; 404 = authorised but that
    # ROM isn't in the set; 401 = bad credentials.  (Kept to a single request to avoid the mirror's rate limiter.)
    auth = _basic_auth_header(username, password)
    folder, _exact = _retroroms_pick_folder(mame_version, log)
    url = f'{RETROROMS_BASE}/{folder}/pacman.zip'
    status, content_type, _size = _retroroms_request(url, auth)
    log.info('retroroms test: %s -> HTTP %s (%s)', url, status, content_type or '?')
    if status == 200 and 'text/html' not in content_type:
        return True, 'Login successful - downloads are accessible'
    if status == 404:
        return True, 'Login successful (test ROM not in this set, but the mirror accepted your credentials)'
    if status == 401:
        return False, 'Invalid username or password (401)'
    if status == 429:
        return False, 'retroroms is rate-limiting requests (429) - wait a minute and try again'
    return False, f'Could not confirm login (HTTP {status})'


def _decode_ddg_link(href: str) -> str:
    """DuckDuckGo HTML results wrap the real URL in a redirect (.../l/?uddg=...); pull the target back out."""
    if 'uddg=' in href:
        try:
            query = urllib.parse.urlparse(href).query
            target = urllib.parse.parse_qs(query).get('uddg', [''])[0]
            if target:
                return urllib.parse.unquote(target)
        except Exception:
            return ''
    if href.startswith('http'):
        return href
    return ''


def duckduckgo_candidates(short_name: str, full_name: str, max_results: int = MAX_RESULTS,
                          report: Reporter = _NO_REPORT) -> list[RomCandidate]:
    """
    Catch-all web search for direct '.zip' links mentioning the game and MAME.  Unofficial and best-effort: any
    failure returns an empty list rather than raising.  Only links whose path ends in '.zip' are kept.
    """
    query = ' '.join(part for part in (full_name or short_name, 'mame rom zip') if part)
    if not query.strip():
        return []
    report(N_('Searching the web (DuckDuckGo) for {}'), query)
    try:
        url = 'https://html.duckduckgo.com/html/?' + urllib.parse.urlencode({'q': query})
        body, _status = _http(url, referer='https://duckduckgo.com/')
        html = body.decode('utf-8', 'replace')
    except Exception:
        return []

    results: list[RomCandidate] = []
    seen: set[str] = set()
    for match in re.finditer(r'href="([^"]+)"', html):
        target = _decode_ddg_link(match.group(1))
        if not target:
            continue
        path = urllib.parse.urlparse(target).path.lower()
        if not path.endswith('.zip') or target in seen:
            continue
        seen.add(target)
        results.append(RomCandidate(
            source='DuckDuckGo',
            download_url=target,
            filename=f'{short_name}.zip',
            item=urllib.parse.urlparse(target).netloc,
        ))
        if len(results) >= max_results:
            break
    return results


# ----------------------------------------------------------------------------------------------------------------------
# Orchestration

def search(short_name: str, full_name: str, sources=None, mame_version: str = '', creds=None,
           logger=None, max_results: int = MAX_RESULTS, progress=None, cancel=None) -> list[RomCandidate]:
    """
    Run the selected providers and return a de-duplicated candidate list.

    :param short_name:   MAME short / ROM name (e.g. 'galaxian').  This is the ZIP file's base name.
    :param full_name:    Full game description (e.g. 'Galaxian (Namco set 1)') - used by the DuckDuckGo fallback.
    :param sources:      List of source keys to query (see ROM_SOURCES).  Defaults to anonymous archive.org.
    :param mame_version: MAME version string like '0.288' - required by the retroroms source.
    :param creds:        Dict mapping source key -> (username, password) for credentialed sources.
    :param logger:       Optional logger; provider errors are logged but never raised to the caller.
    :param max_results:  Cap on the number of returned candidates.
    :param progress:     Optional progress(message_format, *args, **kwargs) callback for each step (see Reporter).
    :param cancel:       Optional threading.Event; setting it makes search() raise SearchCancelled.
    """
    sources = sources or [SOURCE_ARCHIVE_ANON]
    creds = creds or {}
    candidates: list[RomCandidate] = []
    report = Reporter(progress, cancel)

    def run(name, fn):
        try:
            candidates.extend(fn())
        except SearchCancelled:
            raise
        except Exception as exc:  # Providers must never break the whole search
            if logger:
                logger.warning(f'Online ROM provider {name} failed: {exc}')

    # Credentialed, MAME-version-accurate sources first
    if SOURCE_RETROROMS in sources and creds.get(SOURCE_RETROROMS):
        user, password = creds[SOURCE_RETROROMS]
        run('retroroms', lambda: retroroms_candidates(short_name, mame_version, user, password, logger, report))

    if SOURCE_ARCHIVE_AUTH in sources and creds.get(SOURCE_ARCHIVE_AUTH):
        user, password = creds[SOURCE_ARCHIVE_AUTH]
        run('archive.org(login)', lambda: archive_auth_candidates(short_name, user, password, logger, report))

    # Anonymous archive.org, plus the generic catch-all only when the anonymous source is selected
    if SOURCE_ARCHIVE_ANON in sources:
        run('archive.org', lambda: archive_candidates(short_name, logger, report))
        run('duckduckgo', lambda: duckduckgo_candidates(short_name, full_name, max_results, report))

    # De-duplicate on the download URL while preserving provider order
    seen: set[str] = set()
    unique: list[RomCandidate] = []
    for candidate in candidates:
        if candidate.download_url and candidate.download_url not in seen:
            seen.add(candidate.download_url)
            unique.append(candidate)

    return unique[:max_results]
