"""Fetch verification must reject tampered weights before they reach a session."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scripts.fetch_models import Asset, FetchError, fetch, load_manifest, sha256_of, verify


def _asset(tmp_path: Path, body: bytes = b"clean-bytes") -> tuple[Asset, Path]:
    digest = hashlib.sha256(body).hexdigest()
    asset = Asset(
        name="fake.onnx",
        url="https://example.invalid/fake.onnx",
        sha256=digest,
        dest="models/fake.onnx",
        licence="Apache-2.0",
        source="test",
    )
    return asset, tmp_path / "models" / "fake.onnx"


def test_verify_accepts_matching_digest(tmp_path: Path) -> None:
    asset, dest = _asset(tmp_path)
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"clean-bytes")
    verify(asset, dest)


def test_verify_rejects_tampered_file(tmp_path: Path) -> None:
    asset, dest = _asset(tmp_path)
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"tampered")
    with pytest.raises(FetchError, match="sha256 mismatch"):
        verify(asset, dest)


def test_verify_rejects_missing_file(tmp_path: Path) -> None:
    asset, dest = _asset(tmp_path)
    dest.parent.mkdir(parents=True)
    with pytest.raises(FetchError, match="missing"):
        verify(asset, dest)


def test_fetch_downloads_then_verifies(tmp_path: Path) -> None:
    asset, dest = _asset(tmp_path)
    calls: list[str] = []

    def fake_download(url: str, target: Path) -> None:
        calls.append(url)
        target.write_bytes(b"clean-bytes")

    result = fetch(asset, root=tmp_path, download=fake_download)
    assert result == dest
    assert calls == [asset.url]
    assert dest.read_bytes() == b"clean-bytes"


def test_fetch_never_redownloads_a_present_asset(tmp_path: Path) -> None:
    asset, dest = _asset(tmp_path)
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"clean-bytes")

    def explode(_url: str, _target: Path) -> None:
        raise AssertionError("download must not run when the asset is present")

    fetch(asset, root=tmp_path, download=explode)


def test_fetch_rejects_a_poisoned_download(tmp_path: Path) -> None:
    asset, dest = _asset(tmp_path)

    def fake_download(_url: str, target: Path) -> None:
        target.write_bytes(b"wrong-bytes")

    with pytest.raises(FetchError, match="sha256 mismatch"):
        fetch(asset, root=tmp_path, download=fake_download)
    assert not dest.exists(), "a failed download must never be left at the final path"


def test_manifest_is_well_formed() -> None:
    assets = load_manifest()
    names = {a.name for a in assets}
    assert names == {"yolox_s.onnx", "yolox_nano.onnx", "yolox_m.onnx", "gate.mp4"}
    for asset in assets:
        assert len(asset.sha256) == 64
        assert asset.licence in {"Apache-2.0", "CC-BY-4.0"}


def test_sha256_of_matches_hashlib(tmp_path: Path) -> None:
    path = tmp_path / "blob.bin"
    path.write_bytes(b"abc")
    assert sha256_of(path) == hashlib.sha256(b"abc").hexdigest()
