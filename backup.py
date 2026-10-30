#!/usr/bin/env python3

# ----------------------------------------------------------------------------------------------------------------------
# backup.py

"""
Backup and restore of the user's settings and DAT files (the file handling only - the dialogs are in pfemame.py).

A backup is a single zip holding the chosen files plus a manifest.json.  Restore accepts one of those zips or, for
backups made by older versions, a folder of loose files.  Only names in the allowed list are ever restored, so a
crafted zip cannot write anywhere else.

This module has no wxPython dependency.
"""

import datetime
import json
import os
import shutil
import zipfile

BACKUP_FILES = ['categories.dat',
                'favorites.dat',
                'watchlist.dat',
                'ratings.dat',
                'runs.dat',
                'pfemame.ini',
                'non_mame_emulators.xml',
                'rom_sources.dat',      # Stored online-ROM-source logins (rom_credentials.STORE_NAME)
                'play_stats.json',      # Play counts / times (play_stats.FILE_NAME)
                'slot_presets.json']    # Saved slot setups (slot_presets.FILE_NAME)


def backup_file_name(when: datetime.datetime | None = None) -> str:
    return f'pfeMAME_backup_{(when or datetime.datetime.now()).strftime("%Y%m%d_%H%M%S")}.zip'


def write_backup_zip(data_dir: str, target: str, files: list[str], app_version: str) -> list[str]:
    """Zip the files (those that exist in data_dir) plus a manifest into target.  Returns the files included."""
    included = [name for name in files if os.path.isfile(os.path.join(data_dir, name))]
    manifest = {'application': 'pfeMAME',
                'version': app_version,
                'created': datetime.datetime.now().isoformat(timespec='seconds'),
                'files': included}
    temp_target = target + '.tmp'
    with zipfile.ZipFile(temp_target, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in included:
            archive.write(os.path.join(data_dir, name), name)
        archive.writestr('manifest.json', json.dumps(manifest, indent=2))
    os.replace(temp_target, target)
    return included


def restorable_files(chosen: str, allowed: list[str] = BACKUP_FILES) -> list[str]:
    """
    The allowed files available in a backup: `chosen` is a backup zip, or any file inside an older-style backup
    folder (the folder is used).  Raises OSError / zipfile.BadZipFile if it can't be read.
    """
    if zipfile.is_zipfile(chosen):
        with zipfile.ZipFile(chosen) as archive:
            names = set(archive.namelist())
        return [name for name in allowed if name in names]
    folder = os.path.dirname(chosen)
    return [name for name in allowed if os.path.isfile(os.path.join(folder, name))]


def restore_files(chosen: str, names: list[str], data_dir: str, app_version: str,
                  allowed: list[str] = BACKUP_FILES) -> str:
    """
    Restore `names` from the backup into data_dir.  The current files are first saved to
    data_dir/backups/pre_restore_<date>.zip, and each file is written via a temporary file + rename so a failure
    never leaves a half-written file.  Returns the safety-copy path.
    """
    names = [name for name in names if name in allowed]
    safety_folder = os.path.join(data_dir, 'backups')
    os.makedirs(safety_folder, exist_ok=True)
    safety_zip = os.path.join(safety_folder, f'pre_restore_{datetime.datetime.now().strftime("%Y%m%d_%H%M%S")}.zip')
    write_backup_zip(data_dir, safety_zip, allowed, app_version)

    from_zip = zipfile.is_zipfile(chosen)
    for name in names:
        destination = os.path.join(data_dir, name)
        temp_destination = destination + '.restore'
        if from_zip:
            with zipfile.ZipFile(chosen) as archive, archive.open(name) as source, \
                    open(temp_destination, 'wb') as target:
                shutil.copyfileobj(source, target)
        else:
            shutil.copy2(os.path.join(os.path.dirname(chosen), name), temp_destination)
        os.replace(temp_destination, destination)
    return safety_zip
