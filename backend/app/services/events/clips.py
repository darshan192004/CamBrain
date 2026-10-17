"""Fixed-duration ring buffer of JPEG frames behind every alert (spec A5.7).

Owns nothing but bytes and timestamps: it is fed by the runtime's tee, sliced
by the handler at fire time, and evicts anything older than its window so a
camera that runs for a month costs one window of memory, not a month of it.
"""

from __future__ import annotations

import shutil
import time
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import av
import cv2
import numpy as np

from app.core.errors import StorageError
from app.services.stream.jpeg import encode_jpeg
from app.services.stream.source import Frame


@dataclass(frozen=True, slots=True)
class BufferedFrame:
    """One buffered JPEG stamped with a monotonic time."""

    at: float
    jpeg: bytes


class FrameRingBuffer:
    """Hold the last ``duration_s`` of sampled frames.

    Args:
        duration_s: Retention window; 30s covers 10s pre-roll + 20s post-roll
            (spec A5.7) because assembly happens after the post-roll elapses.
        now: Monotonic clock, injected for deterministic tests.
    """

    def __init__(
        self, *, duration_s: float = 30.0, now: Callable[[], float] = time.monotonic
    ) -> None:
        self._duration_s = duration_s
        self._now = now
        self._frames: deque[BufferedFrame] = deque()

    def append(self, frame: Frame) -> None:
        """Encode and buffer one pipeline frame."""
        self.append_jpeg(self._now(), encode_jpeg(frame))

    def append_jpeg(self, at: float, jpeg: bytes) -> None:
        """Buffer a pre-encoded JPEG stamped at ``at`` (monotonic seconds)."""
        self._frames.append(BufferedFrame(at=at, jpeg=jpeg))
        while self._frames and at - self._frames[0].at > self._duration_s:
            self._frames.popleft()

    def latest_jpeg(self) -> bytes | None:
        """The newest buffered JPEG, or None when the window is empty."""
        return self._frames[-1].jpeg if self._frames else None

    def slice(self, start: float, end: float) -> list[BufferedFrame]:
        """Frames with ``start <= at < end``, oldest first."""
        return [f for f in self._frames if start <= f.at < end]

    def __len__(self) -> int:
        return len(self._frames)


def _disk_usage(path: Path) -> tuple[int, int]:
    """(used_bytes, total_bytes) for the filesystem holding ``path``.

    ``path`` itself may not exist yet (the first clip creates it), so probe
    the nearest existing ancestor instead of raising FileNotFoundError.
    """
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    usage = shutil.disk_usage(probe)
    return usage.used, usage.total


class QuotaExceededError(StorageError):
    """Raised when writing a clip would push the disk past the site quota."""


class ClipWriter:
    """Write event stills and clips under ``media_root`` (spec A5.7).

    Owns: id-derived relative paths, the quota gate, and the libx264 encode.
    Deliberately does not own: event rows — the caller attaches the returned
    paths, so a refused clip is a row with ``clip_path`` NULL, not a rollback.
    """

    def __init__(
        self,
        media_root: Path,
        *,
        disk_usage: Callable[[Path], tuple[int, int]] | None = None,
    ) -> None:
        self._root = media_root
        self._disk_usage = disk_usage or _disk_usage

    def write_still(self, event_id: int, still_jpeg: bytes) -> str:
        """Persist the event still; returns the media-root-relative path."""
        path = self._root / "stills" / f"{event_id}.jpg"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(still_jpeg)
        return f"stills/{event_id}.jpg"

    def write_clip(
        self,
        event_id: int,
        frames: Sequence[BufferedFrame],
        *,
        quota_pct: float,
    ) -> tuple[str, int, int]:
        """Encode pre+post-roll frames to mp4; returns (rel_path, bytes, ms).

        Raises:
            ValueError: Fewer than two frames — a one-frame clip is not a clip.
            QuotaExceededError: Disk usage is at or past ``quota_pct``; checked
                before any file is created, so a refusal never leaves debris.
        """
        if len(frames) < 2:
            raise ValueError(f"clip needs at least 2 frames, got {len(frames)}")
        used, total = self._disk_usage(self._root)
        if total and used / total * 100 >= quota_pct:
            raise QuotaExceededError(
                f"disk at {used / total * 100:.0f}% >= quota {quota_pct:.0f}%; clip refused"
            )
        span = max(frames[-1].at - frames[0].at, 0.001)
        fps = max(1, min(15, round(len(frames) / span)))
        first = cv2.imdecode(np.frombuffer(frames[0].jpeg, np.uint8), cv2.IMREAD_COLOR)
        if first is None:
            raise ValueError("first frame does not decode")
        height, width = np.asarray(first, dtype=np.uint8).shape[:2]
        path = self._root / "clips" / f"{event_id}.mp4"
        path.parent.mkdir(parents=True, exist_ok=True)
        with av.open(str(path), mode="w") as container:
            # Dimensions must be set before the first encode: pyav opens the
            # codec on encode and then refuses any width/height mutation.
            stream = container.add_stream("libx264", rate=fps)
            stream.width = width - (width % 2)
            stream.height = height - (height % 2)
            for buf in frames:
                array = cv2.imdecode(np.frombuffer(buf.jpeg, np.uint8), cv2.IMREAD_COLOR)
                if array is None:
                    continue
                video = av.VideoFrame.from_ndarray(
                    np.asarray(array, dtype=np.uint8), format="bgr24"
                )
                for packet in stream.encode(video):
                    container.mux(packet)
            for packet in stream.encode(None):
                container.mux(packet)
        size = path.stat().st_size
        return f"clips/{event_id}.mp4", size, round(span * 1000)
