"""Parallel ranged download and delta update, against a local HTTP server with Range support."""
import os
import zipfile
import hashlib

import pytest

import delta_update
import fast_download


def test_parallel_download_with_checksum(range_server, tmp_path):
    folder, base = range_server
    payload = os.urandom(3_000_000)
    (folder / 'release.zip').write_bytes(payload)
    dest = str(tmp_path / 'out.zip')
    checksum = 'sha256:' + hashlib.sha256(payload).hexdigest()
    assert fast_download.download(f'{base}/release.zip', dest, connections=4, checksum=checksum) == len(payload)
    assert open(dest, 'rb').read() == payload


def test_checksum_mismatch_deletes_the_file(range_server, tmp_path):
    folder, base = range_server
    (folder / 'release.zip').write_bytes(b'abc' * 1000)
    dest = str(tmp_path / 'out.zip')
    with pytest.raises(IOError):
        fast_download.download(f'{base}/release.zip', dest, checksum='md5:' + '0' * 32)
    assert not os.path.exists(dest)


def test_trusted_update_urls():
    assert fast_download.is_trusted_url('https://sourceforge.net/projects/pfemame/files/x.zip/download')
    assert fast_download.is_trusted_url('https://master.dl.sourceforge.net/project/pfemame/x.zip')
    assert not fast_download.is_trusted_url('http://sourceforge.net/x.zip')
    assert not fast_download.is_trusted_url('https://sourceforge.net.evil.com/x.zip')


def make_release(path, files):
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)


def test_delta_update_downloads_only_changed_files(range_server, tmp_path):
    folder, base = range_server
    new_release = {'pfeMAME.exe': b'exe v2' * 1000,
                   'lib/library.zip': os.urandom(200_000),
                   'lib/unchanged.dll': b'dll' * 5000,
                   'images/new.png': b'png' * 100,
                   'catver.ini': b'[Category]\n' * 50}
    make_release(folder / 'pfemame_windows_v9.9.9.zip', new_release)

    install = tmp_path / 'install'
    (install / 'lib').mkdir(parents=True)
    (install / 'pfeMAME.exe').write_bytes(b'exe v1' * 1000)                 # changed
    (install / 'lib' / 'library.zip').write_bytes(b'old')                   # changed
    (install / 'lib' / 'unchanged.dll').write_bytes(b'dll' * 5000)          # same
    (install / 'catver.ini').write_bytes(b'[Category]\n' * 50)              # same
    (install / 'favorites.dat').write_bytes(b'user data')                   # not in the release

    url = f'{base}/pfemame_windows_v9.9.9.zip'
    plan = delta_update.make_plan(url, str(install))
    assert sorted(e.name for e in plan.changed) == ['images/new.png', 'lib/library.zip', 'pfeMAME.exe']
    assert plan.unchanged == 2

    staging = tmp_path / 'staging'
    assert delta_update.download_changes(plan, url, str(staging)) == 3
    for name in ('pfeMAME.exe', 'lib/library.zip', 'images/new.png'):
        assert (staging / name).read_bytes() == new_release[name]
    assert not (staging / 'favorites.dat').exists()


def test_delta_update_strips_a_wrapper_folder(range_server, tmp_path):
    folder, base = range_server
    make_release(folder / 'r.zip', {'pfemame_v2/a.txt': b'new', 'pfemame_v2/b.txt': b'same'})
    install = tmp_path / 'install'
    install.mkdir()
    (install / 'b.txt').write_bytes(b'same')
    plan = delta_update.make_plan(f'{base}/r.zip', str(install))
    assert plan.prefix == 'pfemame_v2/' and [e.name for e in plan.changed] == ['pfemame_v2/a.txt']
    delta_update.download_changes(plan, f'{base}/r.zip', str(tmp_path / 's'))
    assert (tmp_path / 's' / 'a.txt').read_bytes() == b'new'


def test_server_without_ranges_is_rejected(tmp_path):
    import http.server
    import threading
    (tmp_path / 'r.zip').write_bytes(b'PK' * 100)

    def handler(*args, **kwargs):
        return http.server.SimpleHTTPRequestHandler(*args, directory=str(tmp_path), **kwargs)
    http.server.SimpleHTTPRequestHandler.log_message = lambda *a: None
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with pytest.raises(delta_update.DeltaError):
            delta_update.make_plan(f'http://127.0.0.1:{server.server_port}/r.zip', str(tmp_path))
    finally:
        server.shutdown()
