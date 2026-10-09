"""Fernet encryption for secrets at rest, keyed by a DPAPI-wrapped master key.

The master key is generated once per installation. On Windows it is wrapped
with DPAPI so decryption is scoped to the OS user account — another user on
the box cannot decrypt it. DPAPI rather than a user passphrase because
installers hand these boxes to customers; a passphrase becomes a support
call when the owner forgets it.

On non-Windows development machines the key file falls back to 0600
permissions with a loud warning. Never a silent permissive fallback.
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from app.core.errors import StorageError

log = logging.getLogger(__name__)

KEY_FILENAME = "master.key"
ENV_KEY_DIR = "CAMBRAIN_KEY_DIR"
CRYPTPROTECT_UI_FORBIDDEN = 0x1

_fernets: dict[str, Fernet] = {}


class CryptoError(StorageError):
    """Raised when key access, encryption, or decryption fails."""


if sys.platform == "win32":
    import ctypes.wintypes as wintypes

    class _DataBlob(ctypes.Structure):
        """Win32 DATA_BLOB, laid out for CryptProtectData/CryptUnprotectData."""

        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def _dpapi(data: bytes, unprotect: bool) -> bytes:
        """Wrap or unwrap bytes through Windows DPAPI."""
        crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        buf = ctypes.create_string_buffer(data, len(data))
        source = _DataBlob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
        target = _DataBlob()

        ctypes.set_last_error(0)
        call = crypt32.CryptUnprotectData if unprotect else crypt32.CryptProtectData
        if not call(ctypes.byref(source), None, None, None, None,
                    CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(target)):
            raise CryptoError(f"DPAPI call failed (WinError {ctypes.get_last_error()})")
        try:
            return ctypes.string_at(target.pbData, target.cbData)
        finally:
            kernel32.LocalFree(target.pbData)

else:

    def _dpapi(data: bytes, unprotect: bool) -> bytes:
        """DPAPI is unavailable off Windows; callers must not reach here."""
        del data, unprotect
        raise CryptoError("DPAPI is only available on Windows")


def _key_dir(key_dir: Path | None = None) -> Path:
    """Resolve the directory holding the master key."""
    if key_dir is not None:
        return Path(key_dir)
    env = os.environ.get(ENV_KEY_DIR)
    if env:
        return Path(env)
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    windows_dir = Path(base) / "CamBrain"
    posix_dir = Path.home() / ".config" / "cambrain"
    return windows_dir if sys.platform == "win32" else posix_dir


def _protect(raw: bytes) -> bytes:
    """Seal the raw key. DPAPI on Windows, file permissions elsewhere."""
    return _dpapi(raw, unprotect=False) if sys.platform == "win32" else raw


def _unprotect(stored: bytes) -> bytes:
    """Unseal the raw key."""
    return _dpapi(stored, unprotect=True) if sys.platform == "win32" else stored


def ensure_master_key(key_dir: Path | None = None) -> Path:
    """Create the master key if absent and return its path."""
    directory = _key_dir(key_dir)
    path = directory / KEY_FILENAME
    if path.exists():
        return path

    directory.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_protect(Fernet.generate_key()))
    if sys.platform != "win32":
        path.chmod(0o600)
        log.warning(
            "master key is not DPAPI-protected on this platform; "
            "restricted to file mode 0600 at %s",
            path,
        )
    log.info("generated a new master key at %s", path)
    return path


def _load_raw(path: Path) -> bytes:
    """Read and unseal the master key from disk."""
    try:
        return _unprotect(path.read_bytes())
    except OSError as exc:
        raise CryptoError(f"cannot read master key at {path}") from exc


def get_fernet(key_dir: Path | None = None) -> Fernet:
    """Return the cipher for this installation, cached by key path."""
    path = ensure_master_key(key_dir)
    cache_key = str(path)
    cipher = _fernets.get(cache_key)
    if cipher is None:
        cipher = Fernet(_load_raw(path))
        _fernets[cache_key] = cipher
    return cipher


def encrypt(plaintext: str, key_dir: Path | None = None) -> str:
    """Encrypt a secret into URL-safe token text safe for a TEXT column."""
    return get_fernet(key_dir).encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(token: str, key_dir: Path | None = None) -> str:
    """Decrypt a token, raising CryptoError rather than returning garbage."""
    try:
        return get_fernet(key_dir).decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeError) as exc:
        raise CryptoError("token failed authentication") from exc
