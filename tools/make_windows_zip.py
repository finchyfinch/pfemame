#!/usr/bin/env python3
"""
make_windows_zip.py

Makes the Windows release zip, dist/pfemame_windows_v<version>.zip, from the cx_Freeze build/ folder - the same
layout as the published zips: every file at the top level (no wrapper folder), folders listed, paths with '/'.
The updater downloads this zip (and its delta update reads the zip's file list), so keep the layout.

Run after a build:    python tools/make_windows_zip.py         (tools/setup_raw.bat does this for you)
"""

import hashlib
import os
import re
import sys
import zipfile

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
SOURCE_DIR = os.path.dirname(TOOLS_DIR)

PROGRAMS = ('pfeMAME.exe', 'pfemame_updater.exe')
NOT_SHIPPED = (os.path.join('lib', 'pfemame_files.done'),)     # Marker left by running the build (program_cleanup.py)


def version(source_dir: str = SOURCE_DIR) -> str:
    with open(os.path.join(source_dir, 'pfemame.py'), encoding='utf-8') as file:
        return re.search(r"^__version__\s*=\s*['\"]([0-9.]+)['\"]", file.read(), re.MULTILINE).group(1)


def zip_entries(build_dir: str) -> list[tuple[str, str]]:
    """(path on disk, name in the zip) for every folder and file in build_dir, sorted, folders before their files."""
    entries = []
    for root, folders, files in os.walk(build_dir):
        folders.sort()
        relative_root = os.path.relpath(root, build_dir)
        if relative_root != '.':
            entries.append((root, relative_root.replace(os.sep, '/') + '/'))
        for name in sorted(files):
            relative = os.path.normpath(os.path.join(relative_root, name))
            if relative not in NOT_SHIPPED:
                entries.append((os.path.join(root, name), relative.replace(os.sep, '/')))
    return entries


def make_zip(build_dir: str, zip_path: str) -> int:
    """Write the zip (through a temporary file, so a failed run never leaves a half-written release).  Returns the
    number of entries."""
    missing = [program for program in PROGRAMS if not os.path.isfile(os.path.join(build_dir, program))]
    if missing:
        raise FileNotFoundError(f'{", ".join(missing)} not found in {build_dir} - build pfeMAME first')

    os.makedirs(os.path.dirname(zip_path), exist_ok=True)
    temp_path = zip_path + '.part'
    entries = zip_entries(build_dir)
    try:
        with zipfile.ZipFile(temp_path, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for disk_path, name in entries:
                archive.write(disk_path, name)
        with zipfile.ZipFile(temp_path) as archive:
            bad = archive.testzip()
            if bad:
                raise zipfile.BadZipFile(f'{bad} failed its check in the new zip')
        os.replace(temp_path, zip_path)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
    return len(entries)


def sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, 'rb') as file:
        for block in iter(lambda: file.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    build_dir = os.path.join(SOURCE_DIR, 'build')
    zip_path = os.path.join(SOURCE_DIR, 'dist', f'pfemame_windows_v{version()}.zip')
    print(f'--- Zipping {build_dir} to {zip_path} ---')
    try:
        count = make_zip(build_dir, zip_path)
    except (OSError, zipfile.BadZipFile) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        return 1
    print(f'{count:,} entries, {os.path.getsize(zip_path) / 1e6:.1f} MB')
    print(f'SHA-256: {sha256(zip_path)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
