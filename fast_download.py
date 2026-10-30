#!/usr/bin/env python3

# ----------------------------------------------------------------------------------------------------------------------
# fast_download.py

"""
Software update helpers shared by pfeMAME (version check) and pfemame_updater (download).

Why this exists:
SourceForge sends non-browser clients (urllib) to master.dl.sourceforge.net, which throttles every TCP connection to
roughly 300 KB/s and whose load varies a lot - that is why a plain urlretrieve() was slow and inconsistent while a
browser (which is sent to a nearby mirror) was fast.  Splitting the file into byte ranges and fetching them over
several connections in parallel multiplies the throughput almost linearly (measured: 125 MB in 37 s with 8
connections, against ~6.5 minutes with one).

Every request has a timeout, each part resumes and retries on failure, and the finished file is checked against the
checksum SourceForge publishes in its best_release.json API before anything is installed.
"""

import hashlib
import json
import os
import re
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

PROJECT = 'pfemame'
USER_AGENT = 'pfeMAME-updater (+https://sourceforge.net/projects/pfemame/)'
READ_SIZE = 256 * 1024      # Socket read size
TIMEOUT = 30                # Seconds per socket operation - a stalled connection can no longer hang forever
RETRIES = 5                 # Attempts per part before giving up
DEFAULT_CONNECTIONS = 8


# ----------------------------------------------------------------------------------------------------------------------
def https_context() -> ssl.SSLContext:
    """A certificate-verifying SSL context.  Uses certifi's CA bundle when available (needed for frozen builds)."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _same_site(old_url: str, new_url: str) -> bool:
    """
    True when a redirect stays on the same site (same host, or the same base domain such as archive.org ->
    ia800.us.archive.org) and does not downgrade from https to http.
    """
    old, new = urllib.parse.urlparse(old_url), urllib.parse.urlparse(new_url)
    if old.scheme == 'https' and new.scheme != 'https':
        return False
    old_host, new_host = (old.hostname or '').lower(), (new.hostname or '').lower()
    base = '.'.join(old_host.split('.')[-2:])
    return new_host == old_host or new_host == base or new_host.endswith('.' + base)


class _CredentialSafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """urllib copies every header - including Authorization and Cookie - onto a redirect, even to another site.
    Drop them whenever a redirect leaves the original site."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new_request = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new_request is not None and not _same_site(req.full_url, newurl):
            new_request.remove_header('Authorization')
            new_request.remove_header('Cookie')
        return new_request


def open_url(request: urllib.request.Request, timeout: int):
    """
    urlopen() replacement for pfeMAME's online searches: verifies certificates, and never forwards login
    credentials to another site on a redirect.

    Requests that carry no credentials (no Authorization / Cookie header and no POST body) fall back to an
    unverified connection if certificate verification fails - some image/ROM hosts have broken certificate chains
    and nothing secret is being sent.  Requests carrying credentials are never sent unverified.
    """
    carries_secrets = (request.has_header('Authorization') or request.has_header('Cookie')
                       or request.data is not None)
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=https_context()),
                                         _CredentialSafeRedirectHandler())
    try:
        return opener.open(request, timeout=timeout)
    except urllib.error.URLError as e:
        if carries_secrets or not isinstance(getattr(e, 'reason', None), ssl.SSLCertVerificationError):
            raise
    unverified = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ssl._create_unverified_context()),
                                             _CredentialSafeRedirectHandler())
    return unverified.open(request, timeout=timeout)


def _open(url: str, headers: dict | None = None, timeout: int = TIMEOUT):
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT, **(headers or {})})
    return urllib.request.urlopen(request, timeout=timeout, context=https_context())


def is_trusted_url(url: str) -> bool:
    """Only ever download updates over https from SourceForge."""
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or '').lower()
    return parsed.scheme == 'https' and (host == 'sourceforge.net' or host.endswith('.sourceforge.net'))


# ----------------------------------------------------------------------------------------------------------------------
def get_latest_release(platform: str, project: str = PROJECT, timeout: int = 10) -> dict | None:
    """
    Ask SourceForge's best_release.json API for the newest release for this platform.

    :param platform: 'windows', 'linux' or 'mac' (as returned by functions.get_platform())
    :return: {'version', 'filename', 'url', 'size', 'checksum'} or None if the platform has no release listed.
             checksum is 'sha256:<hex>' when SourceForge has one, otherwise 'md5:<hex>', otherwise ''.
    """
    with _open(f'https://sourceforge.net/projects/{project}/best_release.json', timeout=timeout) as response:
        data = json.load(response)

    release = (data.get('platform_releases') or {}).get(platform)
    if not release:
        return None

    filename = release.get('filename', '').lstrip('/')
    match = re.search(rf'{project}_{platform}_v([0-9.]+?)\.(?:7z|zip)$', filename)
    if not match:
        return None

    if release.get('sha256sum'):
        checksum = f"sha256:{release['sha256sum']}"
    elif release.get('md5sum'):
        checksum = f"md5:{release['md5sum']}"
    else:
        checksum = ''

    return {'version': match.group(1),
            'filename': filename,
            # The 'url' in the JSON carries an expiring token, so build the stable download URL instead.
            'url': f'https://sourceforge.net/projects/{project}/files/{urllib.parse.quote(filename)}/download',
            'size': int(release.get('bytes') or 0),
            'checksum': checksum}


# ----------------------------------------------------------------------------------------------------------------------
def resolve_final_url(url: str) -> tuple[str, int, bool]:
    """
    Follow the SourceForge redirect chain once to get the signed mirror URL.
    :return: (final_url, total_size, server_supports_ranges)
    """
    with _open(url, {'Range': 'bytes=0-0'}) as response:
        final = response.geturl()
        content_range = response.headers.get('Content-Range', '')      # 'bytes 0-0/124869958'
        if '/' in content_range and content_range.rsplit('/', 1)[1].isdigit():
            size = int(content_range.rsplit('/', 1)[1])
        else:
            size = int(response.headers.get('Content-Length') or 0)
        ranged = response.status == 206
    return final, size, ranged


def verify_checksum(path: str, checksum: str) -> bool:
    """checksum is 'sha256:<hex>' or 'md5:<hex>'.  An empty checksum always passes."""
    if not checksum:
        return True
    algorithm, _sep, expected = checksum.partition(':')
    digest = hashlib.new(algorithm)
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest().lower() == expected.strip().lower()


def download(url: str,
             dest: str,
             connections: int = DEFAULT_CONNECTIONS,
             checksum: str = '',
             progress=None,
             cancel: threading.Event | None = None) -> int:
    """
    Download url -> dest using up to `connections` parallel HTTP range requests.

    :param checksum: 'sha256:<hex>' / 'md5:<hex>' / '' - the file is deleted and IOError raised on mismatch.
    :param progress: progress(done_bytes, total_bytes, bytes_per_second).  Called from worker threads, so GUI code
                     must marshal it with wx.CallAfter.
    :param cancel:   optional threading.Event; setting it aborts the download with InterruptedError.
    :return: number of bytes downloaded.
    """
    current_url, total, ranged = resolve_final_url(url)
    if not ranged or total <= 0:
        connections = 1     # Server can't do ranges (or size unknown) - fall back to one plain stream

    # Pre-allocate the file so each part can write at its own offset
    with open(dest, 'wb') as handle:
        if total > 0 and connections > 1:
            handle.truncate(total)

    if connections > 1:
        part_size = -(-total // connections)
        ranges = [(i * part_size, min(total, (i + 1) * part_size) - 1) for i in range(connections)]
    else:
        ranges = [(0, None)]

    done = [0] * len(ranges)
    lock = threading.Lock()
    url_holder = [current_url]
    start = time.monotonic()

    def fetch(index: int) -> None:
        low, high = ranges[index]
        for attempt in range(1, RETRIES + 1):
            position = low + done[index]            # Resume where this part stopped
            if high is not None and position > high:
                return
            headers = {'Range': f'bytes={position}-{high}'} if high is not None else {}
            if high is None and done[index]:
                done[index] = 0                     # Single plain stream can't resume - start again
                position = 0
            try:
                with _open(url_holder[0], headers) as response, open(dest, 'r+b') as handle:
                    handle.seek(position)
                    while True:
                        if cancel is not None and cancel.is_set():
                            raise InterruptedError('Download cancelled')
                        chunk = response.read(READ_SIZE)
                        if not chunk:
                            break
                        handle.write(chunk)
                        with lock:
                            done[index] += len(chunk)
                            got = sum(done)
                        if progress:
                            progress(got, total, got / max(time.monotonic() - start, 1e-6))
                if high is None or low + done[index] > high:
                    return
            except InterruptedError:
                raise
            except Exception:
                if attempt == RETRIES:
                    raise
            time.sleep(min(2 ** attempt, 10))
            try:
                url_holder[0] = resolve_final_url(url)[0]   # Signed SourceForge URLs expire - refresh on retry
            except Exception:
                pass
        raise IOError('Download part could not be completed')

    with ThreadPoolExecutor(max_workers=len(ranges)) as pool:
        futures = [pool.submit(fetch, i) for i in range(len(ranges))]
        try:
            for future in futures:
                future.result()
        except BaseException:
            if cancel is not None:
                cancel.set()    # Stop the other parts quickly
            raise

    downloaded = sum(done)
    if total and downloaded != total:
        raise IOError(f'Incomplete download: {downloaded} of {total} bytes')

    if not verify_checksum(dest, checksum):
        os.remove(dest)
        raise IOError('Checksum mismatch - the download was corrupted.  Please try again.')

    return downloaded


# ----------------------------------------------------------------------------------------------------------------------
# Command line test:  python fast_download.py [windows|linux|mac] [connections]
if __name__ == '__main__':
    import sys
    platform = sys.argv[1] if len(sys.argv) > 1 else 'windows'
    conns = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_CONNECTIONS
    info = get_latest_release(platform)
    print('latest:', info)
    last = [0.0]

    def show(got, total, bps):
        if time.monotonic() - last[0] > 5:
            last[0] = time.monotonic()
            print(f'  {got * 100 // max(total, 1):3d}%  {bps / 1e6:5.2f} MB/s', flush=True)

    started = time.monotonic()
    size = download(info['url'], 'update_test.zip', connections=conns, checksum=info['checksum'], progress=show)
    elapsed = time.monotonic() - started
    print(f'{conns} connections: {size / 1e6:.1f} MB in {elapsed:.1f}s = {size / 1e6 / elapsed:.2f} MB/s, '
          f'checksum {info["checksum"][:10]}... OK')
    os.remove('update_test.zip')
