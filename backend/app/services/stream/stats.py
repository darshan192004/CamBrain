"""Per-camera live stream stats for GET /system/status (API §System).

The MJPEG route is per-viewer, so the honest source of "is this camera
producing frames right now" is the stream itself: every connected consumer
registers, every yielded part is counted, and a camera reads as `live` only
while a consumer holds frames fresh enough to matter. Cameras nobody is
watching fall back to their stored `status` (the pipeline manager that will
run background streams lands in a later phase).

`fps` is measured between successive `row()` reads — the status poll comes
every 10s (design §4), so the rate is frames-per-second over the poll window,
not a guess about the camera's native rate. Frame counts are per consumer:
two viewers of the same camera count the same frames twice, which is the
stat we can honestly attribute here.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime

# A frame older than this is stale: the viewer dropped or the source stalled.
LIVE_WINDOW_S = 5.0


class StreamStats:
    """Thread-safe per-camera stream counters with a poll-once fps measure.

    Args:
        now: Monotonic clock seam; tests inject a controllable one.
    """

    def __init__(self, now: Callable[[], float] = time.monotonic) -> None:
        self._lock = threading.Lock()
        self._now = now
        self._consumers: dict[int, int] = {}
        self._frames: dict[int, int] = {}
        self._last_frame_at: dict[int, float] = {}
        self._last_frame_wall: dict[int, datetime] = {}
        self._baseline: dict[int, tuple[int, float]] = {}

    def begin(self, camera_id: int) -> None:
        """Register one consumer connected to this camera's stream."""
        with self._lock:
            self._consumers[camera_id] = self._consumers.get(camera_id, 0) + 1

    def end(self, camera_id: int) -> None:
        """Drop one consumer; the count never goes below zero."""
        with self._lock:
            left = self._consumers.get(camera_id, 0) - 1
            if left > 0:
                self._consumers[camera_id] = left
            else:
                self._consumers.pop(camera_id, None)

    def frame(self, camera_id: int) -> None:
        """Record one part emitted to a consumer."""
        with self._lock:
            self._frames[camera_id] = self._frames.get(camera_id, 0) + 1
            self._last_frame_at[camera_id] = self._now()
            self._last_frame_wall[camera_id] = datetime.now(UTC)

    def row(self, camera_id: int) -> dict[str, object]:
        """Snapshot one camera; measures fps against the previous snapshot.

        Returns:
            ``{active, frames, fps, last_frame_at}`` where `active` needs a
            connected consumer and a frame inside the live window, and `fps`
            is None until a second snapshot establishes the window.
        """
        with self._lock:
            total = self._frames.get(camera_id, 0)
            last = self._last_frame_at.get(camera_id)
            active = (
                self._consumers.get(camera_id, 0) > 0
                and last is not None
                and self._now() - last <= LIVE_WINDOW_S
            )
            fps: float | None = None
            previous = self._baseline.get(camera_id)
            if previous is not None:
                prev_frames, prev_at = previous
                dt = self._now() - prev_at
                if dt > 0:
                    fps = round(max(total - prev_frames, 0) / dt, 1)
            self._baseline[camera_id] = (total, self._now())
            wall = self._last_frame_wall.get(camera_id)
            return {
                "active": active,
                "frames": total,
                "fps": fps,
                "last_frame_at": wall.isoformat() if wall else None,
            }


_STATS = StreamStats()


def get_stream_stats() -> StreamStats:
    """FastAPI dependency: the process-wide stream stats (tests override it)."""
    return _STATS
