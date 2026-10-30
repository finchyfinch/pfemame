#!/usr/bin/env python3

# ----------------------------------------------------------------------------------------------------------------------
# rungame.py

"""
This code calls the external MAME (or non-MAME emulators) to run the selected ROM file
"""

# Import python & wxPython modules
import wx
from dataclasses import dataclass
from pathlib import Path
import threading
import time
import traceback
import subprocess
import shutil
import shlex
import glob
import os
import plistlib
import sys
from pubsub import pub

# Local modules
import functions
import iniFile
import play_stats
from emulator_config import EmulatorFields

_ = functions.set_up_language()  # localization

# Windows and macOS file names are not case-sensitive (Pacman.ZIP is pacman.zip), Linux ones are
CASE_INSENSITIVE_FILE_NAMES = sys.platform in ('win32', 'darwin')


# ----------------------------- Messaging -------------------------------------
class MessagePublisher:
    """Handles publishing messages to the UI (wx) or console fallback."""

    @staticmethod
    def log(message: str):
        if wx.GetApp():
            wx.CallAfter(pub.sendMessage, 'log', msg=message)
        else:
            print(f"LOG: {message}")

    @staticmethod
    def update(message: str, add_delimiter: bool = False, include_datetime: bool = True):
        if message and not message.endswith('\n'):
            message = message + '\n'
        if wx.GetApp():
            wx.CallAfter(pub.sendMessage, 'update', msg=message, add_delimiter=add_delimiter,
                         include_datetime=include_datetime)
        else:
            print(message + ('-' * 100 + '\n' if add_delimiter else ''), end='')

    @staticmethod
    def popup(message: str):
        if wx.GetApp():
            wx.CallAfter(pub.sendMessage, 'popup', msg=message)
        else:
            print(f"POPUP: {message}")

    @staticmethod
    def enable_alert_timer():
        if wx.GetApp():
            wx.CallAfter(pub.sendMessage, 'enable_alert_timer')

    @staticmethod
    def error(message: str):
        """An error the user needs to see: the messages window, the log file and the flashing alert."""
        MessagePublisher.update(message)
        MessagePublisher.log(message)
        MessagePublisher.enable_alert_timer()


# ----------------------------- Data Models -----------------------------------
@dataclass
class EmulatorSettings:
    """Settings read from INI files and preferences."""
    folder_ini: str                     # mame.ini's inipath - can list several folders ('.;ini;ini/presets')
    folders_roms: Path                  # First rompath folder (where a ROM is looked for when nothing else matches)
    folders_systems: Path
    folder_config: Path | None          # cfg_directory resolved (relative to MAME, $HOME expanded); None if not set
    path_to_mame_ini_file: Path
    pref_force_all_fullscreen: str
    pref_force_all_window: str
    rom_folders: list[Path] = None      # Every rompath folder, resolved (rompath can be 'roms;D:\\more roms')
    pref_disable_artwork: str = ''      # 'Disable Artwork for all ROMs' (pfeMAME panel)

    def rom_ini(self, file_name: str, path_executable) -> Path | None:
        """The ROM INI file MAME will use (or where a new one goes) - see functions.find_rom_ini."""
        found = functions.find_rom_ini(file_name, self.folder_ini, str(path_executable),
                                       str(self.path_to_mame_ini_file))
        return Path(found) if found else None

    def find(self, *relative_paths) -> Path | None:
        """The first existing <rom folder>/<relative path>, trying each relative path in each folder."""
        for folder in self.rom_folders or [self.folders_roms]:
            for relative in relative_paths:
                candidate = folder / relative
                if candidate.exists():
                    return candidate
        return None


@dataclass
class GameConfig:
    """Internal config object to reduce parameter sprawl in RunGame."""
    parent: object
    rom_file_name: str
    path_executable: Path
    caller: str
    rom_name: str
    system_file_name: str
    short_name: str
    system_folder_name: str
    folder_mame_ini: Path
    folder_mapping: Path | None
    suppress_short_name: bool
    input_playback_or_record: str = ''
    pb_r_filename: str = ''
    force_mame: bool = False

    @property
    def is_system_program(self) -> bool:
        # A "system" program has a program file name (software list) with an extension, which gives its media type
        return bool(self.system_file_name) and bool(Path(self.system_file_name).suffix)


# ----------------------------- Helpers ---------------------------------------
class InputMappingManager:
    """
    A ROM's own input mapping (<mapping folder>/<rom>.map, saved from default.cfg by the main window) is copied over
    MAME's default.cfg while that ROM runs.  The user's default.cfg is kept in DEFAULT_CFG_BACKUP and put back
    afterwards, so the next ROM doesn't inherit this ROM's inputs.  Input changes made while the ROM ran (MAME writes
    them to default.cfg) are saved into the ROM's .map file rather than lost.
    """

    def __init__(self, rom_name: str, mapping_folder: Path | None, config_folder: Path | None):
        self.map_file = mapping_folder / f'{rom_name}.map' if mapping_folder and config_folder else None
        self.config_folder = config_folder
        self.default_cfg = config_folder / 'default.cfg' if config_folder else None
        self.applied = False        # The user's default.cfg has been backed up (so it must be put back)
        self.in_place = False       # The ROM's mapping is in default.cfg

    def apply(self) -> bool:
        """Copy the ROM's mapping in place of default.cfg.  Returns True if it was."""
        if not self.map_file or not self.map_file.is_file():
            return False
        backup = self.config_folder / DEFAULT_CFG_BACKUP
        try:
            if backup.exists():
                # Left over from a game that never finished (pfeMAME crashed or was killed) - it is the user's own
                restore_default_cfg(self.config_folder)
            if self.default_cfg.exists():
                shutil.copyfile(str(self.default_cfg), str(backup))
            else:
                backup.write_text(NO_DEFAULT_CFG_MARKER, encoding='utf-8')
            shutil.copyfile(str(self.map_file), str(self.default_cfg))
            self.applied = self.in_place = True
            MessagePublisher.log(
                _('Found inputs mapping file for the ROM.  Copied across and overwriting default.cfg file.')
            )
        except PermissionError:
            error_msg = _(
                'I am unable to overwrite the default.cfg file in the Config folder.  Check the folder permissions and that the folder and files within are not Read Only or write protected.  Under Linux check that everyone has permissions to write to the file / folder.'
            )
            MessagePublisher.update(f'{error_msg}\r\n')
            MessagePublisher.log(_('Permission error: Unable to overwrite the default.cfg file.'))
            MessagePublisher.enable_alert_timer()
            self.applied = backup.exists()      # Put back whatever was saved before the copy failed
        except OSError as e:
            MessagePublisher.log(f'Unable to copy the inputs mapping file {self.map_file}: {e}')
            self.applied = backup.exists()
        return self.applied

    def restore(self):
        """After the game: keep any input changes in the ROM's .map file, then put the user's default.cfg back."""
        if not self.applied:
            return
        try:
            if (self.in_place and self.default_cfg.is_file()
                    and self.default_cfg.read_bytes() != self.map_file.read_bytes()):
                shutil.copyfile(str(self.default_cfg), str(self.map_file))
                MessagePublisher.log(f'Saved the input changes made while playing to {self.map_file}')
        except OSError as e:
            MessagePublisher.log(f'Unable to save the input changes to {self.map_file}: {e}')
        try:
            restore_default_cfg(self.config_folder)
        except OSError as e:
            MessagePublisher.log(f'Unable to restore {self.default_cfg}: {e}')


# The user's own default.cfg while a ROM's input mapping is in its place (in MAME's cfg folder)
DEFAULT_CFG_BACKUP = 'default.cfg.pfemame_backup'

# Written to DEFAULT_CFG_BACKUP when there was no default.cfg before the ROM's mapping was copied in
NO_DEFAULT_CFG_MARKER = '<!-- pfeMAME: there was no default.cfg - remove the ROM mapping copy on restore -->\n'


def restore_default_cfg(config_folder: Path | str | None) -> bool:
    """
    Undo InputMappingManager.apply: put the user's default.cfg back.  Also the startup check for a game that never
    finished (pfeMAME crashed or was killed while it ran).  Returns True if anything was restored.
    """
    if not config_folder:
        return False
    backup = Path(config_folder) / DEFAULT_CFG_BACKUP
    default_cfg = Path(config_folder) / 'default.cfg'
    if not backup.is_file():
        return False
    if backup.read_text(encoding='utf-8', errors='ignore') == NO_DEFAULT_CFG_MARKER:
        default_cfg.unlink(missing_ok=True)
        backup.unlink()
    else:
        os.replace(backup, default_cfg)     # Atomic - default.cfg is never missing
    return True


class SystemIniManager:
    """Manages system INI files for system programs."""

    def __init__(self, folder_ini: Path, rom_file_name: str, system_file_name: str,
                 rom_specific_ini_path: Path | None = None):
        """
        folder_ini is the folder the system's own INI is swapped in (and its backup kept).  rom_specific_ini_path is
        the program's INI, if it is in a different INI folder.
        """
        self.folder_ini = folder_ini
        self.rom_file_name = rom_file_name
        self.system_file_name = system_file_name

        base = self.folder_ini / rom_file_name
        self.top_level_ini_path = base.with_suffix('.ini')
        self.top_level_ini_backup_path = base.with_name(f'{base.name}_backup.ini')
        self.rom_specific_ini_path = (rom_specific_ini_path or
                                      self.folder_ini / f'{rom_file_name}_system_{system_file_name}.ini')

    def setup_system_ini(self) -> bool:
        """
        Put the program-specific INI in place of the system's INI while the program runs.

        The system's own INI is moved to <rom>_backup.ini.  If the system has no INI of its own, the backup file
        holds NO_ORIGINAL_MARKER instead, so that restoring removes the temporary copy rather than leaving the
        program's settings behind as the system's settings.
        """
        if not self.system_file_name or not self.rom_specific_ini_path.exists():
            return False
        try:
            if self.top_level_ini_backup_path.exists():
                # Left over from a run that never finished (pfeMAME crashed or was killed).  The backup is the
                # user's real INI - put it back before starting, never delete it.
                restore_ini_from_backup(self.top_level_ini_path, self.top_level_ini_backup_path)
            if self.top_level_ini_path.exists():
                os.replace(self.top_level_ini_path, self.top_level_ini_backup_path)
            else:
                self.top_level_ini_backup_path.write_text(NO_ORIGINAL_MARKER, encoding='utf-8')
            shutil.copyfile(str(self.rom_specific_ini_path), str(self.top_level_ini_path))
            return True
        except (OSError, IOError) as e:
            MessagePublisher.log(f"SystemIniManager.setup_system_ini error: {e}")
            return False

    def restore_system_ini(self):
        """Restore original system INI file."""
        try:
            restore_ini_from_backup(self.top_level_ini_path, self.top_level_ini_backup_path)
        except (OSError, IOError) as e:
            MessagePublisher.log(f"SystemIniManager.restore_system_ini error: {e}")


# Written to <rom>_backup.ini when the system had no INI of its own before a program-specific INI was swapped in
NO_ORIGINAL_MARKER = '# pfeMAME: this system had no INI file of its own - remove the temporary copy on restore\n'


def restore_ini_from_backup(top_level_ini_path: Path, backup_path: Path) -> bool:
    """Undo SystemIniManager.setup_system_ini.  Returns True if anything was restored."""
    if not backup_path.exists():
        return False
    if backup_path.read_text(encoding='utf-8', errors='ignore') == NO_ORIGINAL_MARKER:
        top_level_ini_path.unlink(missing_ok=True)
        backup_path.unlink()
    else:
        os.replace(backup_path, top_level_ini_path)   # Atomic - the real INI is never missing
    return True


def recover_stranded_system_inis(folder_ini: str) -> list[str]:
    """
    Startup check: if pfeMAME crashed or was killed while a system program was running, the system's real INI is
    still sitting in <rom>_backup.ini and <rom>.ini holds a program-specific copy.  Put the real one back.

    To avoid touching a '*_backup.ini' the user made themselves, a backup is only restored when it is our
    NO_ORIGINAL_MARKER, or when <rom>.ini is byte-for-byte one of the <rom>_system_*.ini files (i.e. clearly the
    temporary copy).

    :return: the ROM names whose INI was restored
    """
    restored = []
    folder = Path(folder_ini) if folder_ini else None
    if not folder or not folder.is_dir():
        return restored
    for backup_path in folder.glob('*_backup.ini'):
        rom = backup_path.name[:-len('_backup.ini')]
        top_level = folder / f'{rom}.ini'
        try:
            is_marker = backup_path.read_text(encoding='utf-8', errors='ignore') == NO_ORIGINAL_MARKER
            is_temporary_copy = top_level.exists() and any(
                system_ini.read_bytes() == top_level.read_bytes()
                for system_ini in folder.glob(f'{glob.escape(rom)}_system_*.ini'))
            if (is_marker or is_temporary_copy) and restore_ini_from_backup(top_level, backup_path):
                restored.append(rom)
        except OSError as e:
            MessagePublisher.log(f'Unable to restore {backup_path}: {e}')
    return restored


class EngineSelector:
    """Decides whether to use MAME or alternate engine."""

    def __init__(self, settings: EmulatorSettings, force_mame: bool, rom_file_name: str, system_file_name: str):
        self.settings = settings
        self.force_mame = force_mame
        self.rom_file_name = rom_file_name
        self.system_file_name = system_file_name
        self._path_to_me = functions.path_to_me()

    def determine(self) -> dict:
        """The engine to use: {'engine': 'mame'}, or the details of the first enabled emulator listing the ROM."""
        engine_info: dict = {'engine': 'mame'}
        if self.force_mame:
            return engine_info
        try:
            alternate_emulation_engines, error = functions.load_other_emulators_detail(self._path_to_me)
            if alternate_emulation_engines and not error:
                for line in alternate_emulation_engines:
                    listed = line[EmulatorFields.ROM_FILE_NAME]
                    # An entry with no file name must not match every arcade ROM (whose system file name is '')
                    if not listed or listed not in (self.rom_file_name, self.system_file_name):
                        continue
                    if not line[EmulatorFields.ENABLED]:  # A disabled emulator - a later enabled one may list it
                        continue
                    engine_info = {
                        'engine': line[EmulatorFields.NAME],
                        'path': line[EmulatorFields.PATH],
                        'rom_folder': line[EmulatorFields.ROM_FOLDER],
                        'include_extension': line[EmulatorFields.INCLUDE_EXTENSION],
                        'include_folder_path': line[EmulatorFields.INCLUDE_FOLDER_PATH],
                        'extra_commands': line[EmulatorFields.EXTRA_COMMANDS],
                        'extensions': line[EmulatorFields.VALID_EXTENSIONS].split()
                    }
                    break
        except IndexError:
            error_msg = _(
                'ERROR:  There was a problem processing the non_mame_emulators.xml file.  There is likely an error in this file.  Please check it out.'
            )
            MessagePublisher.update(f'{error_msg}\r\n')
            MessagePublisher.log(_('XML File Error : non_mame_emulators.xml file may be corrupted'))
            MessagePublisher.enable_alert_timer()
        return engine_info

    @staticmethod
    def apply_rom_folder(settings: EmulatorSettings, engine_info: dict):
        """An alternate emulator with its own ROM folder looks for ROMs there instead of in MAME's rompath."""
        rom_folder = engine_info.get('rom_folder')
        if engine_info['engine'] != 'mame' and rom_folder != 'Default':
            settings.folders_roms = Path(rom_folder)
            settings.rom_folders = [Path(rom_folder)]


# Written in an alternate emulator's extra commands where the ROM should go (if not there, the ROM goes last)
ROM_PLACEHOLDER = '{rom}'


def macos_app_executable(path: Path) -> Path | None:
    """
    The program inside a macOS application bundle (RetroArch.app -> RetroArch.app/Contents/MacOS/RetroArch), which is
    what has to be run - the .app itself is a folder.  None if path isn't a bundle or has no program in it.
    """
    if path.suffix.lower() != '.app' or not path.is_dir():
        return None
    programs = path / 'Contents' / 'MacOS'
    try:
        with open(path / 'Contents' / 'Info.plist', 'rb') as fp:
            name = plistlib.load(fp).get('CFBundleExecutable')
        if name and (programs / name).is_file():
            return programs / name
    except (OSError, ValueError, AttributeError, plistlib.InvalidFileException):
        pass
    try:
        found = [entry for entry in programs.iterdir() if entry.is_file()]
    except OSError:
        return None
    return found[0] if len(found) == 1 else None


def exit_code_message(engine: str, rom_file_name: str, return_code: int) -> str:
    """What a non-zero exit code means, in words.  MAME's codes are documented; other emulators' are their own."""
    if return_code < 0:                       # Linux / macOS: killed by a signal (e.g. 11 - it crashed)
        code = _('signal {}').format(-return_code)
    elif return_code > 0xFFFF:                # Windows: a crash, e.g. 0xC0000005 (access violation)
        code = f'0x{return_code:08X}'
    else:
        code = str(return_code)

    if engine != 'mame':
        return _('The {0} emulator ended with an error running ROM {1} (exit code {2}).').format(
            engine, rom_file_name, code)

    reasons = {
        1: _('MAME failed its validity checks.'),
        2: _('Required files are missing - check that the ROM set (and any CHD or BIOS it needs) is complete for '
             'this version of MAME.'),
        3: _('MAME stopped with a fatal error - see the messages above.'),
        4: _('A device (such as a slot device or media image) could not be started.'),
        5: _('This version of MAME does not have this machine - it may have been renamed or removed.'),
        6: _('The configuration is not valid - check the ROM\'s INI file and the options set for it.'),
    }
    reason = reasons.get(return_code, _('MAME ended unexpectedly.'))
    return _('ROM {0} did not run correctly (MAME exit code {1}).  {2}').format(rom_file_name, code, reason)


class CommandBuilder:
    """Builds command lists for emulators (MAME & alternate)."""

    def __init__(self, config: GameConfig, settings: EmulatorSettings, engine_info: dict):
        self.cfg = config
        self.settings = settings
        self.engine_info = engine_info

    # -------- Alternate engine --------

    def build_alt_command(self) -> tuple[list[str], Path]:
        """
        Build command for alternate emulator and return (cmd, cwd).
        Raises ValueError if the extra commands can't be read (e.g. a " with no closing ").
        """
        alt_path = Path(self.engine_info['path'])
        cwd = alt_path.parent
        program = macos_app_executable(alt_path) or alt_path   # A macOS .app is run through the program inside it

        rom_to_run = self.cfg.system_file_name if self.cfg.system_file_name else self.cfg.rom_file_name

        # Handle extension matching
        if self.engine_info['include_extension']:
            rom_to_run = self._get_extension_match(self.engine_info['extensions'], rom_to_run)

        # Determine ROM path
        if self.engine_info['rom_folder'] == 'Default':
            if self.engine_info['include_folder_path']:
                rom_path = self.settings.find(rom_to_run) or self.settings.folders_roms / rom_to_run
            else:
                rom_path = Path(rom_to_run)
        else:
            rom_path = Path(self.engine_info['rom_folder']) / rom_to_run

        cmd: list[str] = [str(program)]
        extra: list[str] = []
        if self.engine_info['extra_commands']:
            # shlex keeps "quoted arguments with spaces" together (a plain split() broke them apart)
            extra = [arg.strip('"') for arg in shlex.split(self.engine_info['extra_commands'],
                                                           posix=(os.name != 'nt'))]

        # The ROM goes where the extra commands have {rom} (e.g. '-play {rom} -exit'), otherwise at the end
        if any(ROM_PLACEHOLDER in arg for arg in extra):
            cmd += [arg.replace(ROM_PLACEHOLDER, str(rom_path)) for arg in extra]
        else:
            cmd += extra
            cmd.append(str(rom_path))
        return cmd, cwd

    def _get_extension_match(self, extensions: list[str], rom_to_run: str) -> str:
        """Get a file extension match based on the base name within ROMs folder."""
        def same_name(name: str) -> str:
            return name.casefold() if CASE_INSENSITIVE_FILE_NAMES else name

        base_target = same_name(Path(rom_to_run).stem)
        valid_exts = {ext.lstrip('.').lower() for ext in extensions}
        for folder in self.settings.rom_folders or [self.settings.folders_roms]:
            try:
                for entry in folder.iterdir():
                    if entry.is_file():
                        if same_name(entry.stem) == base_target and entry.suffix.lstrip('.').lower() in valid_exts:
                            return entry.name
            except OSError:
                continue
        return rom_to_run

    # -------- MAME engine --------

    def build_mame_command_base(self) -> list[str]:
        cmd = [str(self.cfg.path_executable)]

        # Artwork off ('-artpath' with no folder, so MAME finds no artwork)
        if self.settings.pref_disable_artwork == 'True':
            cmd.extend(['-artpath', ''])

        # Display mode settings
        if self.cfg.caller == 'Tile View' or self.settings.pref_force_all_fullscreen == 'True':
            cmd.append('-nowindow')
        elif self.settings.pref_force_all_window == 'True':
            cmd.append('-window')

        # Input recording/playback
        if self.cfg.input_playback_or_record:
            cmd.extend([self.cfg.input_playback_or_record, self.cfg.pb_r_filename])

        # INI path
        cmd.extend(['-inipath', f'{self.cfg.folder_mame_ini};{self.settings.folder_ini}'])

        # ROM name
        cmd.append(self.cfg.rom_file_name)

        return cmd

    def add_slot_devices_from_ini(self, cmd: list[str]):
        """Parse slot device section in the ROM-specific INI and append to cmd."""
        top_level_ini_path = self.settings.rom_ini(f'{self.cfg.rom_file_name}.ini', self.cfg.path_executable)
        if not top_level_ini_path or not top_level_ini_path.exists():
            return

        try:
            with top_level_ini_path.open('r', encoding='utf-8', errors='ignore') as fp:
                ini_file_content = fp.readlines()
        except OSError as e:
            MessagePublisher.log(f'Unable to read the slot devices from {top_level_ini_path}: {e}')
            return

        start_idx = None
        for idx, line in enumerate(ini_file_content):
            if '# SLOT DEVICES' in line:
                start_idx = idx + 1
                break

        if start_idx is None:
            return

        for line in ini_file_content[start_idx:]:
            if '# END OF SLOT DEVICES' in line:
                break
            # strip comments
            if '#' in line:
                line = line.split('#', 1)[0]
            parts = [p for p in line.strip().split(' ') if p.strip()]
            if not parts:
                continue
            parts[0] = f'-{parts[0]}'
            for token in parts:
                if token.strip():
                    cmd.append(token.strip())

    def build_mame_command_for_system(self, force_full_path: bool = False) -> tuple[list[str] | None, bool]:
        """
        Build MAME command for system programs. Returns (cmd, using_short_name).  cmd is None if the program can't
        be run (its file extension isn't one of the system's media types) - the user has been told why.
        force_full_path runs the program from its file path even if it has a software list short name.
        """
        cmd = self.build_mame_command_base()
        program = self.cfg.system_file_name

        # Get system file path (software list tree) - searched for in every rompath folder
        folder = Path(self.cfg.system_folder_name)
        system_file_path = (self.settings.find(folder / program, folder / self.cfg.short_name / program)
                            or self.settings.folders_systems / folder / program)

        file_extension = Path(program).suffix

        # Query media types
        match_found, media_type = functions.get_system_media_types(
            str(self.cfg.path_executable), self.cfg.rom_file_name, file_extension
        )

        if not match_found:
            MessagePublisher.popup(
                _('The file extension \'{}\' for the program you have tried to run does not exist in the list of acceptable media types for this system.').format(
                    file_extension
                )
            )
            MessagePublisher.update(_('Unknown File Extension Type \'{}\'\n').format(file_extension))
            MessagePublisher.log(
                _('Unable to run the program - no file extension match for \'{}\' in the system media types').format(
                    file_extension
                )
            )
            return None, False

        # Slot devices
        self.add_slot_devices_from_ini(cmd)

        # Force snapshot name
        cmd.extend(['-snapname', f'%g/%d_{media_type}'])

        # Short name vs full path
        using_short = False
        if not self.cfg.short_name or self.cfg.suppress_short_name or force_full_path:
            cmd.extend([f'-{media_type}', str(system_file_path)])
            MessagePublisher.log(_('Running system using full path name (not XML short name)'))
        else:
            using_short = True
            cmd.extend([f'-{media_type}', self.cfg.short_name])
            msg = _('Running system using XML short name: {}').format(self.cfg.short_name)
            MessagePublisher.log(msg)
            MessagePublisher.update(f'{msg}\n')

        return cmd, using_short


class ProcessExecutor:
    """Runs subprocesses and captures output."""

    def __init__(self, command: list[str], cwd: Path | str | None = None, encoding: str | None = None):
        """encoding: how the program's output is decoded (None - the system's code page).  MAME writes UTF-8."""
        self.command = command
        self.cwd = cwd
        self.encoding = encoding

    def run(self) -> tuple[str, str, int | None]:
        """
        Returns (stdout, stderr, return code).  If the program couldn't be started at all the return code is None
        and stderr says why.
        """
        # No shell (names like 'Tom&Jerry.zip' are passed through untouched - cmd.exe used to split them) and no
        # os.chdir (this runs in a background thread, and chdir would change the directory for the whole app).
        try:
            process = subprocess.run(
                self.command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                encoding=self.encoding,
                errors='replace',
                cwd=str(self.cwd) if self.cwd else None,
                **functions.NO_CONSOLE
            )
            return process.stdout or "", process.stderr or "", process.returncode
        except (FileNotFoundError, NotADirectoryError):
            return '', _('ERROR:  The emulator cannot be found: {}').format(self.command[0]), None
        except PermissionError:
            # Linux / macOS: not marked as executable (e.g. a downloaded AppImage), or a folder such as a .app bundle
            return '', _('ERROR:  The emulator could not be started - permission denied: {}.  Check that it is a '
                         'program and not a folder, and under Linux / macOS that it is marked as executable '
                         '(chmod +x).').format(self.command[0]), None
        except (OSError, ValueError) as e:  # e.g. WinError 193 - not a Windows program
            return '', _('ERROR:  The emulator could not be started: {0} ({1})').format(self.command[0], e), None


# ----------------------------- RunGame (public) ------------------------------


class RunGame(threading.Thread):
    """
    Runs a ROM (or a system with a program) in MAME or an alternate emulator, in a background thread that is
    started by the constructor.  Uses GameConfig + helpers (EngineSelector, CommandBuilder, ProcessExecutor).
    """

    def __init__(self,
                 parent,
                 rom_file_name: str,
                 path_executable: str,
                 caller: str,
                 rom_name: str,
                 system_file_name: str,
                 short_name: str,
                 system_folder_name: str,
                 folder_mame_ini: str,
                 folder_mapping: str,
                 suppress_short_name: bool,
                 input_playback_or_record: str = '',
                 pb_r_filename: str = '',
                 force_mame: bool = False):

        # Used to credit the run / play time to the ROM that was actually played (not whatever is selected in the
        # ROM list when the game ends)
        self.play_key = play_stats.make_key(rom_file_name, system_file_name)
        self.play_seconds = 0.0

        self.config = GameConfig(
            parent=parent,
            rom_file_name=rom_file_name,
            path_executable=Path(path_executable),
            caller=caller,
            rom_name=rom_name,
            system_file_name=system_file_name,
            short_name=short_name,
            system_folder_name=system_folder_name,
            folder_mame_ini=Path(folder_mame_ini),
            folder_mapping=Path(folder_mapping) if folder_mapping else None,
            suppress_short_name=suppress_short_name,
            input_playback_or_record=input_playback_or_record,
            pb_r_filename=pb_r_filename,
            force_mame=force_mame
        )

        self.settings = self._load_settings()

        # Engine selection
        self.engine_info = EngineSelector(
            self.settings, self.config.force_mame, self.config.rom_file_name, self.config.system_file_name
        ).determine()
        EngineSelector.apply_rom_folder(self.settings, self.engine_info)

        # Start the thread
        threading.Thread.__init__(self)
        self.daemon = True
        self.start()

    # ----------------------------- Internals ---------------------------------

    def _load_settings(self) -> EmulatorSettings:
        """Load all settings from INI files."""
        path_to_mame_ini_file = Path(iniFile.read_ini_file('path', 'mame_ini'))
        path_mame_exe = str(self.config.path_executable)

        # rompath can list several folders ('roms;D:\\more roms'), relative to the MAME folder
        rom_folders = [Path(folder) for folder in functions.split_mame_paths(
            iniFile.get_from_mameini('rompath', str(path_to_mame_ini_file)), path_mame_exe)]
        folders_roms = rom_folders[0] if rom_folders else Path('')
        folders_systems = folders_roms

        # cfg_directory is relative to the MAME folder ('cfg') or uses $HOME ('$HOME/.mame/cfg' on Linux)
        folder_config = functions.resolve_mame_folder(
            iniFile.get_from_mameini('cfg_directory', str(path_to_mame_ini_file)), path_mame_exe)

        return EmulatorSettings(
            folder_ini=iniFile.get_from_mameini('inipath', str(path_to_mame_ini_file)),
            folders_roms=folders_roms,
            folders_systems=folders_systems,
            folder_config=Path(folder_config) if folder_config else None,
            path_to_mame_ini_file=path_to_mame_ini_file,
            pref_force_all_fullscreen=iniFile.read_ini_file('preferences', 'force_all_fullscreen'),
            pref_force_all_window=iniFile.read_ini_file('preferences', 'force_all_window'),
            rom_folders=rom_folders,
            pref_disable_artwork=iniFile.read_ini_file('preferences', 'disableartwork')
        )

    def run(self) -> None:
        """Thread entrypoint."""
        started = time.monotonic()
        try:
            if self.engine_info['engine'] != 'mame':
                self._run_alternate_engine()
            else:
                self._run_mame_engine()
        except Exception as e:  # A thread's exception is otherwise only printed to the console - nobody sees it
            MessagePublisher.log(traceback.format_exc())
            MessagePublisher.error(_('ERROR:  Unable to run ROM {0}: {1}').format(self.config.rom_file_name, e))
        finally:
            self.play_seconds = time.monotonic() - started
            self._cleanup()

    # -------- Alternate engine path --------

    def _run_alternate_engine(self):
        builder = CommandBuilder(self.config, self.settings, self.engine_info)
        try:
            cmd, cwd = builder.build_alt_command()
        except ValueError as e:
            MessagePublisher.error(
                _('ERROR:  The extra commands for the {0} emulator could not be read ({1}).  Check that every " '
                  'has a matching ".').format(self.engine_info['engine'], e))
            return

        self._execute(cmd, cwd, self.engine_info['engine'])
        self._log_end()

    # -------- MAME engine path --------

    def _run_mame_engine(self):
        # A program needs a file extension - it is how its media type (-cart, -flop1...) is found
        if self.config.system_file_name and not self.config.is_system_program:
            MessagePublisher.error(
                _('Unable to run the program {0}: it has no file extension, so pfeMAME cannot tell which media type '
                  'of the {1} system it is.').format(self.config.system_file_name, self.config.rom_file_name))
            return

        # System program: swap in its INI.  ROM: swap in its input mapping (if it has one).
        ini_manager: SystemIniManager | None = None
        mapping: InputMappingManager | None = None
        if self.config.system_file_name:
            ini_manager = self._system_ini_manager()
            if ini_manager:
                ini_manager.setup_system_ini()
        else:
            mapping = InputMappingManager(self.config.rom_file_name, self.config.folder_mapping,
                                          self.settings.folder_config)
            mapping.apply()

        try:
            # Check for ROM-specific INI (log only)
            self._check_rom_specific_ini()

            builder = CommandBuilder(self.config, self.settings, self.engine_info)

            if self.config.is_system_program:
                cmd, using_short_name = builder.build_mame_command_for_system()
                if cmd is None:
                    return  # Not a media type of this system - the user has been told
            else:
                cmd = builder.build_mame_command_base()
                using_short_name = False

            stdout, stderr, rc = self._execute(cmd, self._mame_cwd(), 'mame')

            # Retry with full path if needed (system program + short name failed)
            if self._should_retry_with_full_path(stderr, rc, using_short_name):
                self._retry_with_full_path()

            self._log_end()
        finally:
            if ini_manager:
                ini_manager.restore_system_ini()
            if mapping:
                mapping.restore()

    # -------- Utilities --------

    def _mame_cwd(self) -> str | None:
        """MAME runs from its own folder (mame.ini's relative paths), or inherits the folder if it's on the PATH."""
        return functions.mame_working_dir(str(self.config.path_executable))

    def _execute(self, cmd: list[str], cwd, engine: str) -> tuple[str, str, int | None]:
        """Run the emulator and show its output.  A program that couldn't be started is always reported."""
        self._log_start(cmd, engine)
        is_mame = engine == 'mame'
        stdout, stderr, rc = ProcessExecutor(cmd, cwd=cwd, encoding='utf-8' if is_mame else None).run()
        self._publish_io(stdout, stderr)
        if rc is None:
            MessagePublisher.log(stderr)
            MessagePublisher.enable_alert_timer()
        elif rc != 0:
            self._report_exit_code(engine, rc)
        return stdout, stderr, rc

    def _report_exit_code(self, engine: str, return_code: int):
        """
        Say why the emulator ended with an error.  Tile View shows no messages, so there it only goes in the log file.
        Only MAME flashes the alert: other emulators may end with a non-zero code even when all went well.
        """
        msg = exit_code_message(engine, self.config.rom_file_name, return_code)
        MessagePublisher.log(msg)
        if self.config.caller == 'Tile View':
            return
        MessagePublisher.update(msg)
        if engine == 'mame':
            MessagePublisher.enable_alert_timer()

    def _system_ini_manager(self) -> 'SystemIniManager | None':
        """
        The INI swap for a system program.  inipath can list several folders: the program's INI is wherever it was
        saved, and the swap happens where the system's own INI is (the one MAME will read), or next to the
        program's INI if the system has none.
        """
        rom, system = self.config.rom_file_name, self.config.system_file_name
        program_ini = self.settings.rom_ini(f'{rom}_system_{system}.ini', self.config.path_executable)
        if not program_ini:
            return None
        system_ini = self.settings.rom_ini(f'{rom}.ini', self.config.path_executable)
        folder = system_ini.parent if system_ini and system_ini.is_file() else program_ini.parent
        return SystemIniManager(folder, rom, system, rom_specific_ini_path=program_ini)

    def _check_rom_specific_ini(self):
        """Check for ROM specific INI file and log appropriate message."""
        top_level_ini_path = self.settings.rom_ini(f'{self.config.rom_file_name}.ini', self.config.path_executable)
        if top_level_ini_path and top_level_ini_path.is_file():
            msg = _('Using ROM specific INI file for preferences')
        else:
            msg = _('Using default preferences')
        MessagePublisher.log(msg)
        MessagePublisher.update(f'{msg}\r\n')

    @staticmethod
    def _should_retry_with_full_path(error_output: str, return_code: int | None, using_short_name: bool) -> bool:
        """
        Retry with the full path if MAME couldn't find the program by its short name.  Only when MAME failed (a
        game that ran normally can still mention 'file not found', e.g. for a missing sample).
        """
        if not using_short_name or return_code in (0, None):
            return False
        eo = (error_output or "").lower()
        return 'file not found' in eo or 'no such file or directory' in eo

    def _retry_with_full_path(self):
        """Retry running system program with full path instead of short name."""
        softwarelist_name = functions.get_softwarelist_name(
            functions.path_to_me(), str(self.config.path_executable), self.config.rom_file_name, self.config.short_name
        )
        error_msg = _(
            'ERROR Detected.  You have tried running a system program with an XML file short name but MAME '
            'was unable to locate it where it was expected; {0}{1}{2}{3}{4}{5}{6} The application will now '
            'attempt to run the system program using the full file path.'
        ).format(
            self.settings.folders_systems, os.path.sep, softwarelist_name, os.path.sep,
            self.config.short_name, os.path.sep, self.config.system_file_name
        )
        MessagePublisher.log(error_msg)
        MessagePublisher.update(f'{error_msg}\n')

        retry_msg = _('Re-Running system using full path name (not XML short name)')
        MessagePublisher.log(retry_msg)
        MessagePublisher.update(f'{retry_msg}\n')
        MessagePublisher.enable_alert_timer()

        builder = CommandBuilder(self.config, self.settings, self.engine_info)
        cmd, _using_short = builder.build_mame_command_for_system(force_full_path=True)
        if cmd is not None:
            self._execute(cmd, self._mame_cwd(), 'mame')

    def _log_start(self, cmd: list[str], engine: str):
        if self.config.parent is not None:
            MessagePublisher.log(
                _('Starting ROM {1} in {0}, Options: {2}, Using engine: {3}').format(
                    self.config.caller, self.config.rom_file_name, ' '.join(cmd), engine
                )
            )

    def _publish_io(self, stdout: str, stderr: str):
        if self.config.caller != "Tile View":
            if stdout:
                MessagePublisher.update(stdout)
            if stderr:
                MessagePublisher.update(stderr)

    def _log_end(self):
        end_msg = f'ROM {self.config.rom_file_name} ended'
        MessagePublisher.log(end_msg)
        MessagePublisher.update(f'{end_msg}\n')
        MessagePublisher.update('', add_delimiter=True, include_datetime=False)

    def _cleanup(self):
        """Cleanup after execution."""
        if self.config.parent:
            self.config.parent.joystick_block = False
            self.config.parent.inactivity_timer_block = False

            # A run that ended straight away (MAME couldn't start it - missing ROM...) isn't counted, as for play time
            if self.config.caller == 'Normal View' and self.play_seconds >= play_stats.MIN_SECONDS:
                wx.CallAfter(pub.sendMessage, 'number_of_runs',
                             attr1=self.config.rom_file_name, attr2=self.config.rom_name,
                             attr3=self.config.system_file_name, attr4=bool(self.config.system_file_name),
                             attr5='normal_view')

        # Play statistics (all callers - normal view, tile view...).  Too-short runs are ignored by play_stats.
        wx.CallAfter(pub.sendMessage, 'rom_played', key=self.play_key, seconds=self.play_seconds)
