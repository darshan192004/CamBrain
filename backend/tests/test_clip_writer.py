"""ClipWriter: id-derived paths, libx264 roundtrip, quota refusal (matrix)."""

from __future__ import annotations

from pathlib import Path

import av
import numpy as np
import pytest

from app.core.errors import StorageError
from app.services.events.clips import BufferedFrame, ClipWriter, QuotaExceededError


def _jpegs(count: int) -> list[BufferedFrame]:
    import cv2

    frames = []
    for i in range(count):
        img = np.full((64, 96, 3), (i * 3) % 255, dtype=np.uint8)
        ok, buf = cv2.imencode(".jpg", img)
        assert ok
        frames.append(BufferedFrame(at=i * 0.5, jpeg=buf.tobytes()))
    return frames


def test_write_still_is_id_derived(tmp_path: Path) -> None:
    writer = ClipWriter(tmp_path)
    rel = writer.write_still(42, b"\xff\xd8fake")
    assert rel == "stills/42.jpg"
    assert (tmp_path / "stills" / "42.jpg").read_bytes() == b"\xff\xd8fake"


def test_clip_roundtrip_encodes_mp4(tmp_path: Path) -> None:
    # Host disk state is irrelevant to encoding: inject a mostly-empty disk.
    writer = ClipWriter(tmp_path, disk_usage=lambda _p: (1, 100))
    path, size, duration_ms = writer.write_clip(7, _jpegs(8), quota_pct=99.0)
    assert path == "clips/7.mp4"
    assert size > 0 and duration_ms == 3500
    with av.open(str(tmp_path / path)) as container:
        stream = container.streams.video[0]
        decoded = sum(1 for _ in container.decode(stream))
    assert decoded == 8


def test_quota_refuses_writes(tmp_path: Path) -> None:
    """Matrix row: disk quota refuses clips, never partially, never filling the disk."""
    full = (100, 100)  # used == total -> 100% used
    writer = ClipWriter(tmp_path, disk_usage=lambda _p: full)
    with pytest.raises(QuotaExceededError):
        writer.write_clip(1, _jpegs(4), quota_pct=80.0)
    assert not (tmp_path / "clips").exists() or not list((tmp_path / "clips").iterdir())


def test_quota_error_is_a_storage_error(tmp_path: Path) -> None:
    writer = ClipWriter(tmp_path, disk_usage=lambda _p: (100, 100))
    with pytest.raises(StorageError):
        writer.write_clip(1, _jpegs(2), quota_pct=80.0)


def test_short_frame_list_writes_no_clip(tmp_path: Path) -> None:
    writer = ClipWriter(tmp_path)
    with pytest.raises(ValueError, match="at least 2 frames"):
        writer.write_clip(3, _jpegs(1), quota_pct=99.0)
