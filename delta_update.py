#!/usr/bin/env python3

# ----------------------------------------------------------------------------------------------------------------------
# delta_update.py

"""
Download only the files that changed between the installed pfeMAME and a new release.

A release zip is ~125 MB (6,000+ files) but a typical release changes only pfeMAME's own code (lib/library.zip,
~3 MB) plus a few documents.  A zip file ends with a 'central directory' listing every file with its size, CRC-32
checksum and position in the archive, so:

  1. read just the central directory with an HTTP range request (a few hundred KB),
  2. compare each entry's size and CRC-32 with the installed file,
  3. fetch only the changed entries with range requests (adjacent entries are merged into one request, and the
     requests run in parallel), decompress them and check each one's CRC-32,
  4. write them to a staging folder that the normal install step copies over the installation.

No change to the build or release process is needed - it works with the zips already on SourceForge.  Anything
unexpected (server without range support, encrypted entries, a damaged download...) raises DeltaError and the updater
falls back to downloading the whole archive.

This module has no wxPython dependency.
"""

import os
import stat
import struct
import threading
import time
import zlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import fast_download

MAX_GAP = 64 * 1024                 # Merge entries into one request when they are closer than this...
MAX_REQUEST = 16 * 1024 * 1024      # ...up to this size per request
HEADER_MARGIN = 1024                # Room for the local header's extra field, which can differ from the central one
RETRIES = 3


class DeltaError(Exception):
    """The delta update can't be done - fall back to the full download."""


@dataclass
class ZipEntry:
    name: str
    crc: int
    compressed_size: int
    size: int
    method: int
    header_offset: int
    external_attr: int
    flags: int

    @property
    def is_dir(self) -> bool:
        return self.name.endswith('/')


# ----------------------------------------------------------------------------------------------------------------------
def _get_range(url: str, start: int, end: int) -> bytes:
    """Bytes start..end (inclusive).  Raises DeltaError if the server ignores the range."""
    with fast_download._open(url, {'Range': f'bytes={start}-{end}'}) as response:
        if response.status != 206:
            raise DeltaError('The server does not support partial downloads')
        return response.read()


def _parse_central_directory(data: bytes, count: int) -> list[ZipEntry]:
    entries = []
    pos = 0
    for _ in range(count):
        if data[pos:pos + 4] != b'PK\x01\x02':
            raise DeltaError('Unexpected data in the zip central directory')
        (_sig, _made, _need, flags, method, _time, _date, crc, csize, usize, name_len, extra_len, comment_len,
         _disk, _int_attr, ext_attr, offset) = struct.unpack('<4s6H3I5H2I', data[pos:pos + 46])
        name_bytes = data[pos + 46:pos + 46 + name_len]
        extra = data[pos + 46 + name_len:pos + 46 + name_len + extra_len]
        name = name_bytes.decode('utf-8' if flags & 0x800 else 'cp437')
        # ZIP64 extra field holds the real values of any field stored as 0xFFFFFFFF
        if 0xFFFFFFFF in (csize, usize, offset):
            epos = 0
            while epos + 4 <= len(extra):
                header_id, size = struct.unpack('<2H', extra[epos:epos + 4])
                if header_id == 0x0001:
                    values = extra[epos + 4:epos + 4 + size]
                    vpos = 0
                    if usize == 0xFFFFFFFF:
                        usize = struct.unpack('<Q', values[vpos:vpos + 8])[0]
                        vpos += 8
                    if csize == 0xFFFFFFFF:
                        csize = struct.unpack('<Q', values[vpos:vpos + 8])[0]
                        vpos += 8
                    if offset == 0xFFFFFFFF:
                        offset = struct.unpack('<Q', values[vpos:vpos + 8])[0]
                    break
                epos += 4 + size
        entries.append(ZipEntry(name, crc, csize, usize, method, offset, ext_attr, flags))
        pos += 46 + name_len + extra_len + comment_len
    return entries


def read_central_directory(url: str) -> tuple[str, int, list[ZipEntry]]:
    """
    Read a remote zip's file list without downloading the archive.
    :return: (resolved download URL, archive size, entries)
    """
    final_url, total, ranged = fast_download.resolve_final_url(url)
    if not ranged or total <= 0:
        raise DeltaError('The server does not support partial downloads')

    tail_start = max(0, total - (66 * 1024))            # End record + the largest possible comment
    tail = _get_range(final_url, tail_start, total - 1)
    eocd = tail.rfind(b'PK\x05\x06')
    if eocd < 0:
        raise DeltaError('Not a zip file (no end of central directory record)')
    (_sig, _disk, _cd_disk, _count_disk, count, cd_size, cd_offset,
     _comment_len) = struct.unpack('<4s4H2IH', tail[eocd:eocd + 22])

    if count == 0xFFFF or cd_size == 0xFFFFFFFF or cd_offset == 0xFFFFFFFF:     # ZIP64 archive
        locator = tail.rfind(b'PK\x06\x07', 0, eocd)
        if locator < 0:
            raise DeltaError('ZIP64 archive without a locator')
        zip64_offset = struct.unpack('<Q', tail[locator + 8:locator + 16])[0]
        record = _get_range(final_url, zip64_offset, zip64_offset + 55)
        if record[:4] != b'PK\x06\x06':
            raise DeltaError('Bad ZIP64 end of central directory record')
        count, cd_size, cd_offset = struct.unpack('<3Q', record[32:56])

    if cd_offset >= tail_start:
        directory = tail[cd_offset - tail_start:cd_offset - tail_start + cd_size]
    else:
        directory = _get_range(final_url, cd_offset, cd_offset + cd_size - 1)
    return final_url, total, _parse_central_directory(directory, count)


# ----------------------------------------------------------------------------------------------------------------------
def _common_prefix(entries: list[ZipEntry]) -> str:
    """'pfemame_v3.9.2/' when every entry sits in one top-level folder (as the full-archive extract handles)."""
    tops = {entry.name.split('/', 1)[0] for entry in entries}
    if len(tops) == 1 and all('/' in entry.name for entry in entries):
        return tops.pop() + '/'
    return ''


def file_crc32(path: str) -> int:
    crc = 0
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            crc = zlib.crc32(block, crc)
    return crc & 0xFFFFFFFF


@dataclass
class DeltaPlan:
    url: str                        # Resolved (signed) download URL
    archive_size: int
    prefix: str                     # Top-level folder inside the zip to strip ('' if none)
    changed: list[ZipEntry]
    unchanged: int

    @property
    def download_size(self) -> int:
        return sum(entry.compressed_size for entry in self.changed)


def make_plan(url: str, install_dir: str, progress=None) -> DeltaPlan:
    """Work out which files in the new release differ from the installed ones."""
    final_url, total, entries = read_central_directory(url)
    files = [entry for entry in entries if not entry.is_dir]
    if any(entry.flags & 0x1 for entry in files):
        raise DeltaError('The archive contains encrypted entries')
    if any(entry.method not in (0, 8) for entry in files):
        raise DeltaError('The archive uses an unsupported compression method')

    prefix = _common_prefix(files)
    changed, unchanged = [], 0
    for count, entry in enumerate(files):
        if progress and count % 250 == 0:
            progress(count, len(files))
        local = os.path.join(install_dir, *entry.name[len(prefix):].split('/'))
        try:
            same = (os.path.isfile(local) and not os.path.islink(local) and os.path.getsize(local) == entry.size
                    and file_crc32(local) == entry.crc)
        except OSError:
            same = False
        if same:
            unchanged += 1
        else:
            changed.append(entry)
    return DeltaPlan(final_url, total, prefix, changed, unchanged)


def _group(entries: list[ZipEntry]) -> list[tuple[int, int, list[ZipEntry]]]:
    """Merge entries that sit close together in the archive into (start, end, entries) requests."""
    groups = []
    for entry in sorted(entries, key=lambda e: e.header_offset):
        start = entry.header_offset
        end = start + 30 + len(entry.name.encode('utf-8')) + HEADER_MARGIN + entry.compressed_size
        if groups and start - groups[-1][1] <= MAX_GAP and end - groups[-1][0] <= MAX_REQUEST:
            groups[-1][1] = max(groups[-1][1], end)
            groups[-1][2].append(entry)
        else:
            groups.append([start, end, [entry]])
    return [(start, end, members) for start, end, members in groups]


def _extract_entry(buffer: bytes, buffer_start: int, entry: ZipEntry, url: str) -> bytes:
    """Decompress one entry from a downloaded block (re-fetching it exactly if the block was too short)."""
    pos = entry.header_offset - buffer_start
    if buffer[pos:pos + 4] != b'PK\x03\x04':
        raise DeltaError(f'Bad local header for {entry.name}')
    name_len, extra_len = struct.unpack('<2H', buffer[pos + 26:pos + 30])
    data_start = pos + 30 + name_len + extra_len
    data = buffer[data_start:data_start + entry.compressed_size]
    if len(data) < entry.compressed_size:        # Local extra field bigger than the margin - fetch exactly
        absolute = entry.header_offset + 30 + name_len + extra_len
        data = _get_range(url, absolute, absolute + entry.compressed_size - 1) if entry.compressed_size else b''
    if entry.method == 0:
        content = data
    else:
        inflater = zlib.decompressobj(-15)
        content = inflater.decompress(data) + inflater.flush()
    if len(content) != entry.size or (zlib.crc32(content) & 0xFFFFFFFF) != entry.crc:
        raise DeltaError(f'Checksum mismatch for {entry.name}')
    return content


def _write_entry(staging_dir: str, relative: str, entry: ZipEntry, content: bytes) -> None:
    target = os.path.join(staging_dir, *relative.split('/'))
    os.makedirs(os.path.dirname(target), exist_ok=True)
    mode = entry.external_attr >> 16
    if os.name != 'nt' and stat.S_ISLNK(mode):
        if os.path.lexists(target):
            os.remove(target)
        os.symlink(content.decode('utf-8'), target)
        return
    with open(target, 'wb') as handle:
        handle.write(content)
    if os.name != 'nt' and mode & 0o777:
        os.chmod(target, mode & 0o7777)


def download_changes(plan: DeltaPlan, source_url: str, staging_dir: str, progress=None,
                     cancel: threading.Event | None = None, connections: int = 8) -> int:
    """
    Fetch and verify every changed entry into staging_dir (mirroring the install folder layout).
    :param source_url: the original (unsigned) URL, used to get a fresh signed URL if one expires.
    :param progress:   progress(bytes_done, bytes_total, bytes_per_second), called from worker threads.
    :return: number of files written.
    """
    groups = _group(plan.changed)
    total = sum(end - start for start, end, _members in groups)
    done = [0]
    lock = threading.Lock()
    url_holder = [plan.url]
    started = time.monotonic()

    def fetch(group) -> int:
        start, end, members = group
        for attempt in range(1, RETRIES + 1):
            if cancel is not None and cancel.is_set():
                raise InterruptedError('Download cancelled')
            try:
                block = _get_range(url_holder[0], start, min(end, plan.archive_size) - 1)
                for entry in members:
                    content = _extract_entry(block, start, entry, url_holder[0])
                    _write_entry(staging_dir, entry.name[len(plan.prefix):], entry, content)
                with lock:
                    done[0] += end - start
                    got = done[0]
                if progress:
                    progress(got, total, got / max(time.monotonic() - started, 1e-6))
                return len(members)
            except (DeltaError, OSError) as e:
                if attempt == RETRIES:
                    raise DeltaError(f'Could not download changed files: {e}') from e
                time.sleep(2 * attempt)
                try:
                    url_holder[0] = fast_download.resolve_final_url(source_url)[0]   # Signed URLs expire
                except Exception:
                    pass
        return 0

    os.makedirs(staging_dir, exist_ok=True)
    written = 0
    with ThreadPoolExecutor(max_workers=max(1, min(connections, len(groups)))) as pool:
        futures = [pool.submit(fetch, group) for group in groups]
        try:
            for future in futures:
                written += future.result()
        except BaseException:
            if cancel is not None:
                cancel.set()
            raise
    return written
