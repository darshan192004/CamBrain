"""Clip + still writing: paths from the event id, quota refusal, retention."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from app.core.errors import StorageError
from app.services.events.clips import ClipWriter, RingBuffer
from app.services.stream.source import Frame


def _frame(index: int = 0) -> Frame:
    return Frame(
        data=np.full((36, 64, 3), 120, dtype=np.uint8),
        timestamp=float(index) / 2.0,
        width=64,
        height=36,
    )


def test_paths_derive_from_event_id(tmp_path: Path) -> None:
    """SECURITY §6.2: no user input (camera name) in a filesystem path."""
    writer = ClipWriter(tmp_path, quota_pct=100)
    ring = RingBuffer(capacity=4)
    ring.push(_frame())
    paths = writer.write(7, ring.snapshot(), [_frame(1)])
    assert paths.clip is not None and paths.clip.name == "7.mp4"
    assert paths.still.name == "7.jpg"
    assert paths.clip.is_file() and paths.still.is_file()
    assert "Back door" not in str(paths.clip)


def test_still_is_valid_jpeg(tmp_path: Path) -> None:
    writer = ClipWriter(tmp_path, quota_pct=100)
    paths = writer.write(3, [_frame()], [])
    assert paths.still.read_bytes()[:2] == b"\xff\xd8"


def test_quota_refuses_writes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Past the quota the writer refuses instead of filling the NVR's disk."""

    class _Usage:
        total = 100
        used = 90
        free = 10

    monkeypatch.setattr("app.services.events.clips.shutil.disk_usage", lambda _p: _Usage())
    with pytest.raises(StorageError):
        ClipWriter(tmp_path, quota_pct=80).write(9, [_frame()], [])
    assert list(tmp_path.rglob("*")) == []
