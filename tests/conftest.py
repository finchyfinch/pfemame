"""
Shared test setup for the pfeMAME test suite.

Run from the source folder with:   python -m pytest tests
Nothing here needs MAME, the network or the user's own settings: every test that touches files gets its own
temporary data folder, and network code is exercised against a local HTTP server.
"""
import gzip
import http.server
import os
import sys
import threading

import pytest

SOURCE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures')
sys.path.insert(0, SOURCE_DIR)
os.chdir(SOURCE_DIR)                            # gettext finds 'locales' relative to the working directory


@pytest.fixture(scope='session')
def wx_app():
    """Some modules (global_defaults colours, dialogs) need a wx.App to exist."""
    import wx
    app = wx.App()
    yield app


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """A fresh user-data folder (app_paths.data_dir() points here for the duration of the test)."""
    import app_paths
    folder = tmp_path / 'data'
    folder.mkdir()
    monkeypatch.setenv('PFEMAME_DATA_DIR', str(folder))
    monkeypatch.setattr(app_paths, '_data_dir', None)
    yield folder
    app_paths._data_dir = None


def load_fixture_xml(name: str) -> str:
    """Saved `mame <name> -listxml -nodtd` output (MAME 0.289)."""
    with gzip.open(os.path.join(FIXTURES, f'{name}.xml.gz'), 'rt', encoding='utf-8') as handle:
        return handle.read()


class _RangeHandler(http.server.SimpleHTTPRequestHandler):
    """Static file server that honours 'Range: bytes=a-b' (http.server's own handler ignores it)."""

    def log_message(self, *args):
        pass

    def send_head(self):
        path = self.translate_path(self.path)
        if not os.path.isfile(path):
            self.send_error(404)
            return None
        size = os.path.getsize(path)
        handle = open(path, 'rb')
        header = self.headers.get('Range')
        if header and header.startswith('bytes='):
            first, _sep, last = header[6:].partition('-')
            start = int(first) if first else max(0, size - int(last))
            end = min(int(last), size - 1) if first and last else size - 1
            handle.seek(start)
            self._remaining = end - start + 1
            self.send_response(206)
            self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
            self.send_header('Content-Length', str(self._remaining))
        else:
            self._remaining = size
            self.send_response(200)
            self.send_header('Content-Length', str(size))
        self.send_header('Content-Type', 'application/octet-stream')
        self.end_headers()
        return handle

    def copyfile(self, source, outputfile):
        remaining = self._remaining
        while remaining > 0:
            chunk = source.read(min(65536, remaining))
            if not chunk:
                break
            outputfile.write(chunk)
            remaining -= len(chunk)


@pytest.fixture
def range_server(tmp_path):
    """(folder, base_url): files put in folder are served at base_url/<name> with Range support."""
    folder = tmp_path / 'www'
    folder.mkdir()

    def handler(*args, **kwargs):
        return _RangeHandler(*args, directory=str(folder), **kwargs)

    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield folder, f'http://127.0.0.1:{server.server_port}'
    server.shutdown()
