#!/usr/bin/env python3

# ----------------------------------------------------------------------------------------------------------------------
# rom_credentials.py

"""
Local credential store for the online ROM-download sources that require a login (e.g. archive.org logged-in,
retroroms.net).

IMPORTANT - this is *obfuscation, not strong encryption*.  Credentials sent to a remote site have to be replayed
in full, so they cannot be one-way hashed; they must be reversibly recoverable.  This module hides them from casual
viewing of the file (XOR with a fixed in-app key, then base64) but anyone with this source code and the file can
recover them.  That trade-off was chosen deliberately so the credentials auto-recall with no master password.

Credentials are stored as JSON in '<app folder>/rom_sources.dat', keyed by source name:

    { "retroroms": {"u": "<obfuscated user>", "p": "<obfuscated pass>"}, ... }
"""

import base64
import json
import os

import functions

# Fixed local obfuscation key.  Not a secret (it ships in the source) - it only stops the stored file being
# trivially human-readable.  See the module docstring.
_KEY = b'pfeMAME-rom-sources-v1-obfuscation-key'

# Public so the main app can include it in the backup/restore file set.
STORE_NAME = 'rom_sources.dat'


# ----------------------------------------------------------------------------------------------------------------------
def _store_path() -> str:
    return os.path.join(functions.data_dir(), STORE_NAME)


def _xor(data: bytes) -> bytes:
    return bytes(b ^ _KEY[i % len(_KEY)] for i, b in enumerate(data))


def _obfuscate(text: str) -> str:
    return base64.b64encode(_xor(text.encode('utf-8'))).decode('ascii')


def _deobfuscate(token: str) -> str:
    try:
        return _xor(base64.b64decode(token.encode('ascii'))).decode('utf-8')
    except Exception:
        return ''


def _load() -> dict:
    try:
        with open(_store_path(), encoding='utf-8') as handle:
            data = json.load(handle)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save(data: dict) -> None:
    with open(_store_path(), 'w', encoding='utf-8') as handle:
        json.dump(data, handle)


# ----------------------------------------------------------------------------------------------------------------------
# Public API

def has(source: str) -> bool:
    """True if both a username and a password are stored for the source."""
    entry = _load().get(source)
    return bool(entry and entry.get('u') and entry.get('p'))


def get(source: str):
    """Return (username, password) for the source, or None if not stored."""
    entry = _load().get(source)
    if not entry:
        return None
    username = _deobfuscate(entry.get('u', ''))
    password = _deobfuscate(entry.get('p', ''))
    if not username or not password:
        return None
    return username, password


def set(source: str, username: str, password: str) -> None:
    """Store (obfuscated) credentials for the source, overwriting any existing entry."""
    data = _load()
    data[source] = {'u': _obfuscate(username), 'p': _obfuscate(password)}
    _save(data)


def clear(source: str) -> None:
    """Remove any stored credentials for the source."""
    data = _load()
    if source in data:
        del data[source]
        _save(data)
