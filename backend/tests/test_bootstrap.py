"""First-run bootstrap: the resolved tier's weights self-heal from the manifest (D6-4).

The module must return human reasons instead of raising past the lifespan: a
box that cannot fetch its weights still serves the dashboard (runtime starts
degraded), while /system/status surfaces the reason. These tests pin the
fetch/retry/notice contract against scripts/fetch_models.py's semantics.
"""

from __future__ import annotations

import hashlib
import json
import urllib.error
from pathlib import Path

import pytest

from app.core import bootstrap

DATA = b"fake-onnx-bytes-for-tests-only"
SHA256 = hashlib.sha256(DATA).hexdigest()

ASSET_NAME = "tiny.onnx"


def _write_manifest(tmp_path: Path, **overrides: str) -> Path:
    asset = {
        "name": ASSET_NAME,
        "url": "http://testserver/models/tiny.onnx",
        "sha256": SHA256,
        "dest": f"models/{ASSET_NAME}",
        "licence": "Apache-2.0",
        "source": "unit-test",
    }
    asset.update(overrides)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"assets": [asset]}), encoding="utf-8")
    return manifest


def _write_notice(notice: Path, *, mentions: bool = True) -> None:
    notice.parent.mkdir(parents=True, exist_ok=True)
    text = f"notice\n\n{ASSET_NAME}\n  Licence:  Apache License 2.0\n"
    if not mentions:
        text = "notice\n\nsomething-else.onnx\n"
    notice.write_text(text, encoding="utf-8")


def _ok_downloader(calls: list[str]):
    def download(url: str, dest: Path) -> None:
        calls.append(url)
        dest.write_bytes(DATA)

    return download


def _bad_downloader(calls: list[str]):
    def download(url: str, dest: Path) -> None:
        calls.append(url)
        dest.write_bytes(b"corrupt")

    return download


def _ensure(
    tmp_path: Path,
    manifest: Path,
    download,
) -> str | None:
    return bootstrap.ensure_model(
        root=tmp_path,
        model_name=ASSET_NAME,
        manifest_path=manifest,
        notice_path=tmp_path / "models" / "LICENSE-MODEL-NOTICE",
        download=download,
    )


def test_fetches_and_verifies_then_requires_notice(tmp_path: Path) -> None:
    """Missing weights + good network -> fetched, digest-matched, notice named."""
    manifest = _write_manifest(tmp_path)
    notice = tmp_path / "models" / "LICENSE-MODEL-NOTICE"
    _write_notice(notice)
    calls: list[str] = []

    reason = _ensure(tmp_path, manifest, _ok_downloader(calls))

    assert reason is None
    assert (tmp_path / "models" / ASSET_NAME).read_bytes() == DATA
    assert calls == ["http://testserver/models/tiny.onnx"]
    assert not list(tmp_path.glob("models/*.part"))


def test_missing_notice_fails_loud(tmp_path: Path) -> None:
    """A fetched weight without a LICENSE-MODEL-NOTICE entry is an error (D6-4):
    Apache-2.0 attribution is a legal obligation, not documentation."""
    manifest = _write_manifest(tmp_path)
    notice = tmp_path / "models" / "LICENSE-MODEL-NOTICE"
    _write_notice(notice, mentions=False)
    calls: list[str] = []

    reason = _ensure(tmp_path, manifest, _ok_downloader(calls))

    assert reason is not None
    assert "LICENSE-MODEL-NOTICE" in reason
    assert "tiny.onnx" in reason
    assert not list(tmp_path.glob("models/*.part"))


def test_corrupt_file_redownloads_once(tmp_path: Path) -> None:
    """A corrupted existing file is unlinked and re-fetched; one retry (D6-4)."""
    manifest = _write_manifest(tmp_path)
    notice = tmp_path / "models" / "LICENSE-MODEL-NOTICE"
    _write_notice(notice)
    (tmp_path / "models").mkdir(exist_ok=True)
    (tmp_path / "models" / ASSET_NAME).write_bytes(b"corrupt")
    calls: list[str] = []

    reason = _ensure(tmp_path, manifest, _ok_downloader(calls))

    assert reason is None
    assert len(calls) == 1  # exactly one re-download
    assert (tmp_path / "models" / ASSET_NAME).read_bytes() == DATA


def test_second_mismatch_degrades_with_reason_and_cleans_up(tmp_path: Path) -> None:
    """Both attempts download corrupt bytes -> reason, no dest, no .part litter."""
    manifest = _write_manifest(tmp_path)
    notice = tmp_path / "models" / "LICENSE-MODEL-NOTICE"
    _write_notice(notice)
    calls: list[str] = []

    reason = _ensure(tmp_path, manifest, _bad_downloader(calls))

    assert reason is not None
    assert "sha256 mismatch" in reason
    assert len(calls) == 2
    assert not (tmp_path / "models" / ASSET_NAME).exists()
    assert not list(tmp_path.glob("models/*.part"))


def test_no_network_degrades_with_reason(tmp_path: Path) -> None:
    """Unreachable network -> API-up reason string, weights still absent."""

    def down(_url: str, _dest: Path) -> None:
        raise urllib.error.URLError("no route to host")

    manifest = _write_manifest(tmp_path)
    notice = tmp_path / "models" / "LICENSE-MODEL-NOTICE"
    _write_notice(notice)

    reason = _ensure(tmp_path, manifest, down)

    assert reason is not None
    assert ASSET_NAME in reason
    assert not (tmp_path / "models" / ASSET_NAME).exists()


def test_unknown_model_name_is_a_reason_not_a_crash(tmp_path: Path) -> None:
    """A tier whose asset is absent from the manifest degrades loudly."""
    manifest = _write_manifest(tmp_path)
    notice = tmp_path / "models" / "LICENSE-MODEL-NOTICE"
    _write_notice(notice)

    reason = bootstrap.ensure_model(
        root=tmp_path,
        model_name="ghost.onnx",
        manifest_path=manifest,
        notice_path=notice,
        download=None,
    )

    assert reason is not None
    assert "ghost.onnx" in reason


def test_resolved_model_wires_tier_and_records_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ensure_resolved_model uses resolve_tier() and stores the reason globally."""
    manifest = _write_manifest(
        tmp_path,
        # resolve_tier is monkeypatched to the low tier's file name.
        name="yolox_nano.onnx",
        url="http://testserver/models/yolox_nano.onnx",
        sha256=SHA256,
        dest="models/yolox_nano.onnx",
    )
    notice = tmp_path / "models" / "LICENSE-MODEL-NOTICE"
    _write_notice(notice, mentions=False)  # failing notice -> reason recorded
    model_path = tmp_path / "models" / "yolox_nano.onnx"

    monkeypatch.setattr(bootstrap, "resolve_tier", lambda: ("low", model_path, 416))
    monkeypatch.setattr(bootstrap, "MANIFEST_PATH", manifest)

    reason = bootstrap.ensure_resolved_model(root=tmp_path, download=_bad_downloader([]))

    assert reason is not None
    assert bootstrap.last_reason == reason
    assert "yolox_nano.onnx" in reason


def test_settings_knob_defaults_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """CAMBRAIN_FETCH_MODELS is on for real deployments; conftest turns it off."""
    from app.core.config import Settings

    monkeypatch.delenv("CAMBRAIN_FETCH_MODELS", raising=False)
    assert Settings(_env_file=None).fetch_models is True
