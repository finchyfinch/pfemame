#!/usr/bin/env python3

"""
pfemame_updater.py

This is my software update helper.  It is called from pfeMAME if there is a new software
version.  It will download the new software version and in-place update your files.
Once the update is complete it will run pfeMAME directly.

The download runs in a background thread using parallel HTTP range requests (see fast_download.py) so it is not
limited by SourceForge's per-connection throttling, and the file is checked against SourceForge's published
checksum before anything is installed.
"""

# First, remove program files an older version left in lib/ - a stale one can break the imports below
import program_cleanup
program_cleanup.clean_before_imports()

# Import wxpython & python modules
import os
import urllib.parse
import zipfile
import py7zr
import wx
import subprocess
import logging
import shutil
import tempfile
import threading
import time
import sys
import stat

# Import my own modules
import functions
import fast_download
import delta_update

LOG_FILE_NAME = 'logfile.log'   # Same log file as the main application (it has exited by the time we run)


def setup_logging(install_dir: str) -> None:
    logging.basicConfig(
        filename=os.path.join(install_dir, LOG_FILE_NAME),
        filemode='a',
        level=logging.INFO,
        encoding='utf-8',
        format='[pfemame_updater] %(asctime)s - %(levelname)s - %(message)s'
    )


def _console(msg):
    # The status messages contain emoji, which a cp1252 console can't encode - never let echoing to the console
    # break the update (frozen GUI builds have no console at all).
    try:
        print(msg)
    except (UnicodeEncodeError, OSError, AttributeError):
        pass


def log_info(msg):
    logging.info(msg)
    _console(msg)


def log_error(msg):
    logging.error(msg)
    _console(msg)


# Setup SSL context for frozen apps
def setup_ssl_context():
    """Configure SSL context for certificate verification"""
    if getattr(sys, 'frozen', False):
        try:
            import certifi
            os.environ['SSL_CERT_FILE'] = certifi.where()
            log_info(f"Using certifi CA bundle: {certifi.where()}")
        except ImportError:
            log_info("certifi not available, trying system certificates")
            # Try common system cert locations
            for cert_path in [
                '/etc/ssl/certs/ca-certificates.crt',
                '/etc/pki/tls/certs/ca-bundle.crt',
                '/etc/ssl/ca-bundle.pem',
                '/etc/ssl/cert.pem',
            ]:
                if os.path.exists(cert_path):
                    os.environ['SSL_CERT_FILE'] = cert_path
                    log_info(f"Using system certificates: {cert_path}")
                    break


def format_seconds(seconds: float) -> str:
    seconds = int(max(seconds, 0))
    return f'{seconds // 60}m {seconds % 60:02d}s' if seconds >= 60 else f'{seconds}s'


class UpdaterFrame(wx.Frame):
    def __init__(self, download_url, install_dir, restart_after, checksum='', allow_delta=True):
        super().__init__(None, title="pfeMAME Updater", size=wx.Size(520, 230),
                         style=wx.DEFAULT_FRAME_STYLE & ~(wx.RESIZE_BORDER | wx.MAXIMIZE_BOX))
        self.download_url = download_url
        self.install_dir = install_dir
        self.restart_after = restart_after
        self.checksum = checksum
        self.allow_delta = allow_delta
        self.temp_dir = tempfile.mkdtemp(prefix='pfemame_update_')
        self.cancel_event = threading.Event()
        self.worker = None
        self._last_progress_ui = 0.0

        setup_ssl_context()  # Needed for Linux

        # --------------------------------------------------------------------------------------------------------------
        # Define the application icon
        path_to_me = functions.path_to_me()  # Get the absolute path to me
        self.SetIcon(wx.Icon(os.path.join(path_to_me, 'images', 'pfemame.ico'), wx.BITMAP_TYPE_ICO))

        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        self.status_text = wx.StaticText(panel, label="Starting updater...")
        vbox.Add(self.status_text, flag=wx.ALL | wx.EXPAND, border=10)

        self.progress = wx.Gauge(panel, range=100, style=wx.GA_HORIZONTAL)
        vbox.Add(self.progress, flag=wx.LEFT | wx.RIGHT | wx.EXPAND, border=10)

        self.detail_text = wx.StaticText(panel, label='')
        vbox.Add(self.detail_text, flag=wx.ALL | wx.EXPAND, border=10)

        button_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.retry_button = wx.Button(panel, label='Retry')
        self.retry_button.Bind(wx.EVT_BUTTON, self.on_retry)
        self.retry_button.Hide()
        self.cancel_button = wx.Button(panel, label='Cancel')
        self.cancel_button.Bind(wx.EVT_BUTTON, self.on_cancel)
        button_sizer.AddStretchSpacer()
        button_sizer.Add(self.retry_button, flag=wx.RIGHT, border=6)
        button_sizer.Add(self.cancel_button)
        vbox.Add(button_sizer, flag=wx.ALL | wx.EXPAND, border=10)

        panel.SetSizer(vbox)
        self.Bind(wx.EVT_CLOSE, self.on_cancel)
        self.Centre()
        self.Show()

        wx.CallAfter(self.run_update)

    # ------------------------------------------------------------------------------------------------------------------
    def update_status(self, message: str) -> None:
        self.status_text.SetLabel(message)
        log_info(message)

    def run_update(self):
        """Start the download + extract in a worker thread so the window stays responsive."""
        self.cancel_event.clear()
        self.retry_button.Hide()
        self.cancel_button.SetLabel('Cancel')
        self.cancel_button.Enable()
        self.progress.SetValue(0)
        self.detail_text.SetLabel('')
        self.Layout()
        self.update_status("Preparing update...")
        self.worker = threading.Thread(target=self._download_and_extract, daemon=True)
        self.worker.start()

    def _download_and_extract(self):
        try:
            filename = os.path.basename(urllib.parse.unquote(urllib.parse.urlparse(self.download_url).path))
            if filename == 'download':  # .../files/<name>/download
                filename = os.path.basename(os.path.dirname(
                    urllib.parse.unquote(urllib.parse.urlparse(self.download_url).path)))
            archive_path = os.path.join(self.temp_dir, filename)

            # Normally only the files that changed are downloaded (see delta_update.py)
            extract_dir = self._try_delta_update() if self.allow_delta and filename.endswith('.zip') else None
            if extract_dir is not None:
                wx.CallAfter(self.cancel_button.Disable)
                wx.CallAfter(self._install, extract_dir)
                return

            wx.CallAfter(self.update_status, "🔽 Downloading update...")
            start = time.monotonic()
            size = fast_download.download(self.download_url,
                                          archive_path,
                                          checksum=self.checksum,
                                          progress=self._on_progress,
                                          cancel=self.cancel_event)
            elapsed = time.monotonic() - start
            log_info(f'Downloaded {size:,} bytes in {elapsed:.1f}s ({size / max(elapsed, 1e-6) / 1e6:.2f} MB/s)'
                     + (' - checksum verified' if self.checksum else ' - no checksum available'))

            wx.CallAfter(self.update_status, "📦 Extracting update...")
            wx.CallAfter(self.cancel_button.Disable)   # Past the point where cancelling is useful
            extract_dir = self.extract_archive(archive_path)
            os.remove(archive_path)  # No longer needed - keep the temp folder small

            wx.CallAfter(self._install, extract_dir)

        except InterruptedError:
            wx.CallAfter(self._on_failed, 'Update cancelled.', cancelled=True)
        except Exception as e:
            log_error(f'Updater failed: {e}')
            wx.CallAfter(self._on_failed, f'❌ Update failed: {e}')

    def _try_delta_update(self) -> str | None:
        """
        Download just the files that differ from the installed ones into a staging folder and return it, or None
        to fall back to downloading the whole archive (no range support, most files changed, any error...).
        """
        staging = os.path.join(self.temp_dir, 'delta')
        try:
            wx.CallAfter(self.update_status, '🔍 Checking which files have changed...')
            plan = delta_update.make_plan(
                self.download_url, self.install_dir,
                progress=lambda done, total: wx.CallAfter(self._show_progress, done * 100 // max(total, 1),
                                                          f'Comparing {done:,} of {total:,} files'))
            if plan.download_size > 0.6 * plan.archive_size:
                log_info(f'Most files changed ({len(plan.changed)}) - downloading the full archive')
                return None
            log_info(f'Delta update: {len(plan.changed)} changed file(s), {plan.unchanged} unchanged - downloading '
                     f'{plan.download_size:,} of {plan.archive_size:,} bytes')
            wx.CallAfter(self.update_status,
                         f'🔽 Downloading {len(plan.changed)} changed file(s) - '
                         f'{plan.download_size / 1e6:.1f} MB instead of {plan.archive_size / 1e6:.0f} MB...')
            start = time.monotonic()
            delta_update.download_changes(plan, self.download_url, staging, progress=self._on_progress,
                                          cancel=self.cancel_event)
            log_info(f'Delta download finished in {time.monotonic() - start:.1f}s - every file CRC-32 checked')
            return staging
        except InterruptedError:
            raise                           # The user pressed Cancel
        except Exception as e:
            log_info(f'Delta update not possible ({e}) - downloading the full archive instead')
            shutil.rmtree(staging, ignore_errors=True)
            self.cancel_event.clear()       # download_changes sets it to stop its own workers on an error
            return None

    def _on_progress(self, got: int, total: int, bytes_per_sec: float) -> None:
        """Called from download threads - throttle to ~10 UI updates a second."""
        now = time.monotonic()
        if now - self._last_progress_ui < 0.1 and got != total:
            return
        self._last_progress_ui = now
        percent = min(int(got * 100 / total), 100) if total else 0
        eta = (total - got) / bytes_per_sec if bytes_per_sec and total else 0
        detail = (f'{got / 1e6:,.1f} of {total / 1e6:,.1f} MB    {bytes_per_sec / 1e6:.1f} MB/s    '
                  f'about {format_seconds(eta)} left')
        wx.CallAfter(self._show_progress, percent, detail)

    def _show_progress(self, percent: int, detail: str) -> None:
        if self:
            self.progress.SetValue(percent)
            self.detail_text.SetLabel(detail)

    def _on_failed(self, message: str, cancelled: bool = False) -> None:
        self.update_status(message)
        self.detail_text.SetLabel('' if cancelled else 'Check your network connection and try again.')
        self.retry_button.Show()
        self.cancel_button.SetLabel('Close')
        self.cancel_button.Enable()
        self.Layout()

    # ------------------------------------------------------------------------------------------------------------------
    def on_retry(self, _event):
        self.run_update()

    def on_cancel(self, _event):
        if self.worker is not None and self.worker.is_alive():
            if not self.cancel_button.IsEnabled():
                return  # Already cancelling, or extracting/installing (too late to stop safely)
            self.cancel_event.set()     # The worker reports back through _on_failed
            self.cancel_button.Disable()
            self.update_status('Cancelling...')
            return
        # Nothing running - close, relaunch the existing (un-updated) application and tidy up
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        if self.restart_after:
            self._relaunch_existing()
        self.Destroy()

    def _relaunch_existing(self):
        exe_name = 'pfeMAME.exe' if os.name == 'nt' else 'pfeMAME'
        exe_path = os.path.join(self.install_dir, exe_name)
        if os.path.exists(exe_path):
            try:
                subprocess.Popen([exe_path], cwd=self.install_dir, close_fds=True)
            except OSError as e:
                log_error(f'Unable to restart pfeMAME: {e}')

    # ------------------------------------------------------------------------------------------------------------------
    def _install(self, extract_dir):
        self.update_status("📁 Preparing update...")
        self.progress.SetValue(100)
        try:
            # Platform-specific update strategy
            if os.name == 'nt':  # Windows
                self.windows_deferred_update(extract_dir)
            else:  # Linux and macOS
                self.unix_deferred_update(extract_dir)
        except Exception as e:
            log_error(f'Updater failed: {e}')
            self._on_failed(f'❌ Update failed: {e}')

    def windows_deferred_update(self, extract_dir):
        """Windows: Use batch script to update after process exits"""
        # The script lives OUTSIDE the temp folder so that it can delete that folder once the copy is finished.
        batch_script = os.path.join(tempfile.gettempdir(), f'pfemame_complete_update_{os.getpid()}.bat')
        exe_path = os.path.join(self.install_dir, "pfeMAME.exe")
        install_dir = self.install_dir.rstrip('\\/')
        update_log = os.path.join(install_dir, 'update.log')

        # robocopy exit codes below 8 mean success (0 = nothing to copy, 1 = files copied, 2/3 = extra files...).
        # It retries locked files itself (/R /W); the outer loop covers pfeMAME still shutting down.
        script_content = f'''@echo off
title pfeMAME Update
color 0A
cls
echo.
echo  ========================================
echo   pfeMAME Update
echo  ========================================
echo.
echo  Please wait while the update is being installed...
echo.
echo Update started %DATE% %TIME% > "{update_log}"

timeout /t 3 /nobreak >nul

set RETRY=0
:RETRY_COPY
set /a RETRY+=1
robocopy "{extract_dir}" "{install_dir}" /E /R:3 /W:2 /NP /NFL /NDL /NJH /NJS >> "{update_log}" 2>&1
if %ERRORLEVEL% LSS 8 goto SUCCESS
if %RETRY% GEQ 5 goto FAILED
echo Copy attempt %RETRY% failed, retrying... >> "{update_log}"
timeout /t 3 /nobreak >nul
goto RETRY_COPY

:FAILED
echo Update FAILED after %RETRY% attempts - see update.log >> "{update_log}"
color 0C
echo.
echo  The update could not be installed.  Your existing version has been kept.
echo  Details are in {update_log}
echo.
pause
goto CLEANUP

:SUCCESS
echo Update completed %DATE% %TIME% >> "{update_log}"

:CLEANUP
cd /d "%TEMP%"
rmdir /S /Q "{self.temp_dir}" >nul 2>&1
'''

        # Restart the application
        if self.restart_after:
            script_content += f'start "" /D "{install_dir}" "{exe_path}"\n'

        # Delete this script as the very last action, then close the console window ('start' runs batch files
        # with cmd /K, which would otherwise leave the window open).
        script_content += '(goto) 2>nul & del "%~f0" & exit\n'

        with open(batch_script, 'w') as f:
            f.write(script_content)

        log_info("Launching batch script and exiting updater...")

        # Launch the batch script
        subprocess.Popen(
            ['cmd', '/c', 'start', '/B', batch_script],
            cwd=tempfile.gettempdir(),  # Set working directory to system temp
            close_fds=True
        )

        # Force immediate process termination (doesn't wait for wx cleanup)
        logging.shutdown()
        os._exit(0)

    def unix_deferred_update(self, extract_dir):
        """Linux/Mac: Use shell script to update after process exits"""
        shell_script = os.path.join(tempfile.gettempdir(), f'pfemame_complete_update_{os.getpid()}.sh')
        exe_path = os.path.join(self.install_dir, "pfeMAME")

        extract_dir = os.path.abspath(extract_dir)
        install_dir = os.path.abspath(self.install_dir)
        temp_dir = os.path.abspath(self.temp_dir)

        update_log = os.path.join(install_dir, "update.log")

        # IMPORTANT: never use 'rsync --delete' here.  pfeMAME keeps the user's data (favorites.dat, ratings.dat,
        # runs.dat, pfemame.ini, rom_sources.dat, mylist.db, xmlcache.dat...) in the install folder, and --delete
        # removes every file that is not part of the downloaded archive.
        script_content = f'''#!/bin/bash
# Clear screen and show message
clear
echo ""
echo "========================================"
echo "  pfeMAME Update"
echo "========================================"
echo ""
echo "  Please wait while pfeMAME updates..."
echo ""

echo "Update script started: $(date)" > "{update_log}"

# Wait for updater to exit
echo "Waiting for updater to exit..." >> "{update_log}"
sleep 3

# Wait for updater process to actually terminate
MAX_WAIT=30
for i in $(seq 1 $MAX_WAIT); do
    if ! pgrep -f "pfemame_updater" > /dev/null; then
        echo "Updater process has exited" >> "{update_log}"
        break
    fi
    echo "Waiting for updater... attempt $i" >> "{update_log}"
    sleep 1
done

# Extra delay for file handles to be released
sleep 2
echo "INFO: Temp Dir is {temp_dir}" >> "{update_log}"
echo "Copying files from {extract_dir} to {install_dir}" >> "{update_log}"

# Copy files with retry logic
RETRY=0
MAX_RETRIES=5
SUCCESS=0

while [ $RETRY -lt $MAX_RETRIES ]; do
    RETRY=$((RETRY + 1))
    echo "Copy attempt $RETRY..." >> "{update_log}"

    if command -v rsync &> /dev/null; then
        # -a preserves symlinks and permissions.  NO --delete (it would wipe the user's data files).
        echo "Copying using rsync -a" >> "{update_log}"
        rsync -a "{extract_dir}/" "{install_dir}/" >> "{update_log}" 2>&1
    else
        # cp -a preserves symlinks (archive mode)
        echo "Copying using cp -af" >> "{update_log}"
        cp -af "{extract_dir}/." "{install_dir}/" >> "{update_log}" 2>&1
    fi

    if [ $? -eq 0 ]; then
        echo "Copy successful!" >> "{update_log}"
        SUCCESS=1
        break
    fi

    echo "Copy failed, waiting before retry..." >> "{update_log}"
    sleep 2
done

if [ $SUCCESS -eq 0 ]; then
    echo "Copy failed after $MAX_RETRIES attempts - existing version kept" >> "{update_log}"
    echo ""
    echo "  The update could not be installed.  Details are in {update_log}"
    sleep 10
fi

# Fix permissions for executables
echo "Setting executable permissions..." >> "{update_log}"
chmod +x "{install_dir}/pfeMAME" >> "{update_log}" 2>&1
chmod +x "{install_dir}/pfemame_updater" >> "{update_log}" 2>&1

# Find and set permissions for all executables in lib directory
if [ -d "{install_dir}/lib" ]; then
    find "{install_dir}/lib" -type f -perm -u+x -exec chmod +x {{}} \\; 2>> "{update_log}"
fi

# Clean up temp directory
echo "Cleaning up..." >> "{update_log}"
rm -rf "{temp_dir}" >> "{update_log}" 2>&1
'''

        if self.restart_after:
            script_content += f'''
# Restart application
echo "Restarting pfeMAME..." >> "{update_log}"
cd "{install_dir}"
nohup "{exe_path}" > /dev/null 2>&1 &
'''

        script_content += f'''
echo "Update completed: $(date)" >> "{update_log}"

# Delete this script
sleep 1
rm -f "$0"

# Exit to close terminal window
exit 0
'''

        try:
            with open(shell_script, 'w', encoding='utf-8') as f:
                f.write(script_content)

            # Make script executable
            os.chmod(shell_script, 0o755)

            log_info(f"Created shell script: {shell_script}")
            log_info(f"Update log will be at: {update_log}")

            # Launch in a visible terminal window
            if sys.platform == 'darwin':  # macOS
                applescript = f'''
                        tell application "Terminal"
                            activate
                            do script "{shell_script}; exit"
                        end tell
                        '''
                subprocess.Popen(['osascript', '-e', applescript])
            else:  # Linux
                terminals = [
                    ['gnome-terminal', '--', 'bash', shell_script],
                    ['konsole', '-e', 'bash', shell_script],
                    ['xterm', '-e', 'bash', shell_script],
                    ['x-terminal-emulator', '-e', 'bash', shell_script],
                ]

                launched = False
                for terminal_cmd in terminals:
                    try:
                        subprocess.Popen(terminal_cmd)
                        launched = True
                        log_info(f"✓ Launched with {terminal_cmd[0]}")
                        break
                    except FileNotFoundError:
                        continue

                if not launched:
                    subprocess.Popen(['/bin/bash', shell_script])
                    log_info("✓ Launched without terminal")

            log_info("✓ Shell script launched")

        except Exception as e:
            log_error(f"Failed in unix_deferred_update: {e}")
            raise

        log_info("unix_deferred_update() completed, exiting updater...")

        # Change to neutral directory to release any locks
        try:
            os.chdir(os.path.expanduser("~"))
        except OSError:
            pass

        # Force immediate exit
        logging.shutdown()
        os._exit(0)

    def extract_archive(self, archive_path):
        """Extract archive and return the directory containing files"""
        archive_base = os.path.splitext(os.path.basename(archive_path))[0]
        extract_dir = os.path.join(self.temp_dir, archive_base)
        os.makedirs(extract_dir, exist_ok=True)

        if archive_path.endswith(".zip"):
            with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                members = zip_ref.infolist()
                for count, member in enumerate(members):
                    zip_ref.extract(member, extract_dir)

                    if count % 200 == 0:
                        wx.CallAfter(self._show_progress, count * 100 // max(len(members), 1),
                                     f'Extracting {count:,} of {len(members):,} files')

                    # Check if this is a symlink
                    # Symlinks have the high bits of external_attr set to 0xA (symlink) in Unix
                    is_symlink = stat.S_ISLNK(member.external_attr >> 16)

                    if is_symlink and os.name != 'nt':  # Only handle symlinks on Unix
                        # Read the symlink target from the extracted file
                        extracted_path = os.path.join(extract_dir, member.filename)

                        with open(extracted_path, 'r') as f:
                            link_target = f.read()

                        # Remove the regular file
                        os.remove(extracted_path)

                        # Create the actual symlink
                        os.symlink(link_target, extracted_path)
                        log_info(f"Created symlink: {member.filename} -> {link_target}")
                    else:
                        # Set proper permissions for regular files
                        extracted_path = os.path.join(extract_dir, member.filename)
                        if os.path.exists(extracted_path):
                            # Preserve executable permissions
                            unix_mode = member.external_attr >> 16
                            if unix_mode:
                                os.chmod(extracted_path, unix_mode)

        elif archive_path.endswith(".7z"):
            with py7zr.SevenZipFile(archive_path, mode='r') as archive:
                archive.extractall(path=extract_dir)
        else:
            raise ValueError("Unsupported archive format")

        wx.CallAfter(self._show_progress, 100, '')

        # Handle wrapper folder
        entries = os.listdir(extract_dir)
        if len(entries) == 1:
            first = os.path.join(extract_dir, entries[0])
            if os.path.isdir(first):
                extract_dir = first

        return extract_dir


def main():
    import argparse
    parser = argparse.ArgumentParser(description="pfeMAME Updater")
    parser.add_argument('--download', required=False, help="URL of the update ZIP")
    parser.add_argument('--install-dir', default=None, help="Install directory")
    parser.add_argument('--restart', action='store_true', help="Restart the application after update")
    parser.add_argument('--checksum', default='', help="Expected checksum of the archive, e.g. sha256:<hex>")
    parser.add_argument('--full', action='store_true',
                        help="Always download the whole archive (don't download only the changed files)")
    args = parser.parse_args()

    # Handle default if not set
    if not args.install_dir:
        if getattr(sys, 'frozen', False):
            # Path for frozen files
            args.install_dir = os.path.dirname(sys.executable)
        else:
            # Path for not-frozen files
            args.install_dir = os.path.dirname(os.path.abspath(__file__))

    setup_logging(args.install_dir)

    # 🔧 For local testing only: fallback to the newest release for this platform
    if not args.download:
        release = fast_download.get_latest_release(functions.get_platform())
        args.download, args.checksum = release['url'], release['checksum']
        print(f"[LOCAL TEST] Using latest release: {args.download}")

    if not fast_download.is_trusted_url(args.download):
        log_error(f'Refusing to download an update from an untrusted location: {args.download}')
        sys.exit(1)

    app = wx.App(False)
    UpdaterFrame(args.download, args.install_dir, args.restart, args.checksum, allow_delta=not args.full)
    app.MainLoop()


if __name__ == "__main__":
    main()
