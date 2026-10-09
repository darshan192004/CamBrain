"""Prove secrets encrypt, decrypt, and fail loudly — never silently."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from app.core.crypto import (
    ENV_KEY_DIR,
    CryptoError,
    _load_raw,
    decrypt,
    encrypt,
    ensure_master_key,
)
from app.core.errors import StorageError

SAMPLE_URL = "rtsp://admin:hunter2@192.168.1.10:554/Streaming/Channels/101"


@pytest.fixture
def key_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolate the key store per test and force a fresh key."""
    monkeypatch.setenv(ENV_KEY_DIR, str(tmp_path))
    return tmp_path


def test_roundtrip_preserves_value_exactly(key_dir: Path) -> None:
    """Encrypt then decrypt must be byte-identical — no trimming, no re-encoding."""
    token = encrypt(SAMPLE_URL, key_dir)
    assert token != SAMPLE_URL
    assert decrypt(token, key_dir) == SAMPLE_URL


def test_token_is_url_safe_text(key_dir: Path) -> None:
    """A Fernet token must survive a TEXT column and a JSON round-trip."""
    token = encrypt(SAMPLE_URL, key_dir)
    assert token.isascii()
    assert all(c.isalnum() or c in "-_=" for c in token)


def test_tampered_token_raises_crypto_error(key_dir: Path) -> None:
    """HMAC must reject modified ciphertext rather than returning garbage."""
    token = encrypt("secret", key_dir)
    tampered = ("A" * 8) + token[8:]
    with pytest.raises(CryptoError):
        decrypt(tampered, key_dir)


def test_wrong_key_raises_crypto_error(tmp_path: Path) -> None:
    """A key from another installation must not decrypt this ciphertext."""
    token = encrypt("secret", tmp_path / "site-a")
    with pytest.raises(CryptoError):
        decrypt(token, tmp_path / "site-b")


def test_crypto_error_is_catchable_at_both_granularities() -> None:
    """Callers may catch CryptoError for detail or StorageError for strategy."""
    assert issubclass(CryptoError, StorageError)


def test_key_directory_is_created_on_demand(key_dir: Path) -> None:
    """A fresh installation has no key directory yet."""
    nested = key_dir / "nested" / "deeper"
    path = ensure_master_key(nested)
    assert path.exists()
    assert path.parent == nested


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI is Windows-only")
def test_master_key_is_dpapi_wrapped(key_dir: Path) -> None:
    """Stored bytes must differ from the unwrapped key, proving DPAPI ran."""
    path = ensure_master_key(key_dir)
    assert path.read_bytes() != _load_raw(path)


@pytest.mark.skipif(sys.platform == "win32", reason="0600 fallback is POSIX-only")
def test_key_file_is_0600_on_posix(key_dir: Path) -> None:
    """The non-Windows fallback must be restrictive, never silently permissive."""
    import stat

    path = ensure_master_key(key_dir)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_same_key_is_reused_within_one_installation(key_dir: Path) -> None:
    """Two encryptions in one installation share a key; re-creating it must not
    orphan earlier ciphertext."""
    first = encrypt("keep-me", key_dir)
    ensure_master_key(key_dir)
    assert decrypt(first, key_dir) == "keep-me"
