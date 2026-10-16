"""Pre-roll ring buffer and event clip/still writer (Phase 5).

Owns: holding the last N seconds of frames per camera and turning an
`Alert` into a still JPEG plus an MP4 clip under the media root.
Does not own: detection, rules, or delivery — those call into here.

Paths derive from `events.id` only (`clips/{id}.mp4`, `stills/{id}.jpg`),
never from `camera.name`, which is user input (SECURITY §6.2). Past the
site's disk quota the writer refuses rather than filling the customer's
disk and breaking their NVR (DATABASE §9).
"""

from __future__ import annotations

import shutil
from collections import deque
from dataclasses import dataclass
from pathlib import Path

import av

from app.core.errors import StorageError
from app.services.stream.jpeg import encode_jpeg
from app.services.stream.source import Frame

CLIP_FPS = 15


@dataclass(frozen=True, slots=True)
class ClipPaths:
    """Where one event's media landed. `clip` is None when refused."""

    clip: Path | None
    still: Path


class RingBuffer:
    """Newest-N-frames mailbox for pre-roll (spec §5.7: 10s pre-roll)."""

    def __init__(self, capacity: int) -> None:
        """Create a buffer holding at most `capacity` frames."""
        self._frames: deque[Frame] = deque(maxlen=max(1, capacity))

    @classmethod
    def from_seconds(cls, seconds: float, *, fps: float) -> RingBuffer:
        """Size a buffer for `seconds` of video sampled at `fps`."""
        return cls(max(1, int(seconds * fps)))

    def push(self, frame: Frame) -> None:
        """Append a frame, dropping the oldest when full — never blocks."""
        self._frames.append(frame)

    def snapshot(self) -> list[Frame]:
        """Oldest-first copy of the buffered frames."""
        return list(self._frames)

    def clear(self) -> None:
        """Drop everything (camera removed or source restarted)."""
        self._frames.clear()

    def __len__(self) -> int:
        return len(self._frames)


class ClipWriter:
    """Write one event's still + clip. Refuses past the disk quota."""

    def __init__(self, media_root: Path, *, quota_pct: int = 80) -> None:
        """Point at the media root; `quota_pct` is the site's cap (DATABASE §9)."""
        self._root = media_root
        self._quota_pct = quota_pct

    def _check_quota(self) -> None:
        """Raise `StorageError` instead of filling the customer's disk."""
        usage = shutil.disk_usage(self._root if self._root.exists() else Path("/"))
        if usage.used / usage.total * 100 >= self._quota_pct:
            raise StorageError("disk quota reached; refusing clip write")

    def write(self, event_id: int, pre_roll: list[Frame], post_roll: list[Frame]) -> ClipPaths:
        """Persist still + clip for `event_id` from buffered and live frames."""
        self._check_quota()
        frames = [*pre_roll, *post_roll]
        if not frames:
            raise StorageError("no frames to write")
        stills = self._root / "stills"
        clips = self._root / "clips"
        stills.mkdir(parents=True, exist_ok=True)
        clips.mkdir(parents=True, exist_ok=True)
        still_path = stills / f"{event_id}.jpg"
        still_path.write_bytes(encode_jpeg(frames[len(pre_roll) // 2] if pre_roll else frames[0]))
        clip_path = clips / f"{event_id}.mp4"
        self._write_mp4(clip_path, frames)
        return ClipPaths(clip=clip_path, still=still_path)

    def _write_mp4(self, path: Path, frames: list[Frame]) -> None:
        """Encode frames as H.264 MP4 — same idiom as the fixture generator."""
        first = frames[0]
        with av.open(str(path), mode="w") as container:
            stream = container.add_stream("libx264", rate=CLIP_FPS)
            stream.width = first.width
            stream.height = first.height
            stream.pix_fmt = "yuv420p"
            stream.options = {"crf": "30", "preset": "veryfast"}
            for frame in frames:
                video = av.VideoFrame.from_ndarray(frame.data, format="rgb24")
                for packet in stream.encode(video):
                    container.mux(packet)
            for packet in stream.encode():
                container.mux(packet)
