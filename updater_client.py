#!/usr/bin/env python3

# ----------------------------------------------------------------------------------------------------------------------
# updater_client.py

"""
The main application's side of software updates: find the newest release for this platform.  (The download and
install are done by pfemame_updater, which pfemame.py launches.)

This module has no wxPython dependency.
"""

import re
import ssl
import urllib.error
from urllib.request import Request, urlopen

import fast_download

FILES_PAGE = 'https://sourceforge.net/projects/pfemame/files/'


def parse_versions(page: str, system: str) -> tuple[str | None, str | None]:
    """
    Newest pfemame_<system>_v<version>.zip/.7z mentioned in a SourceForge files page: (version, download URL),
    or (None, None).  The highest version wins, not the first one listed.
    """
    versions = set(re.findall(rf'pfemame_{system}_v([0-9]+(?:\.[0-9]+)*)\.(?:7z|zip)', page))
    if not versions:
        return None, None
    best = max(versions, key=lambda v: [int(x) for x in v.split('.')])
    match = re.search(rf'pfemame_{system}_v{re.escape(best)}\.(?:7z|zip)', page)
    return best, f'https://sourceforge.net/projects/pfemame/files/{match.group(0)}/download'


def scrape_latest_version(system: str) -> tuple[str | None, str | None]:
    """
    Fallback version check: read the SourceForge files page.
    Raises urllib.error.URLError / TimeoutError on network problems.
    """
    request = Request(FILES_PAGE, data=None, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; Win64; x64)'})
    try:
        with urlopen(request, context=fast_download.https_context(), timeout=10) as response:
            content = response.read().decode('utf-8', errors='replace')
    except urllib.error.URLError as e:
        if not isinstance(getattr(e, 'reason', None), ssl.SSLError):
            raise
        # Very old systems may lack current root certificates.  The download itself is still made over a verified
        # connection to sourceforge.net by the updater, so an unverified page read is acceptable here.
        with urlopen(request, context=ssl._create_unverified_context(), timeout=10) as response:
            content = response.read().decode('utf-8', errors='replace')
    return parse_versions(content, system)


def find_latest_release(system: str, logger=None) -> tuple[str | None, str | None, str]:
    """
    (version, download URL, checksum) of the newest release for 'windows' / 'linux' / 'mac'.

    SourceForge's best_release.json API is tried first (certificate-verified, and it gives a checksum); the files
    page is the fallback.  Raises urllib.error.URLError / TimeoutError if neither can be reached.
    """
    try:
        release = fast_download.get_latest_release(system)
        if release:
            return release['version'], release['url'], release['checksum']
    except Exception as e:
        if logger:
            logger.info(f'best_release.json lookup failed, falling back to the files page: {e}')
    version, url = scrape_latest_version(system)
    return version, url, ''
