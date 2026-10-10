"""One camera, owned end to end: source -> motion gate -> sampled sink.

Spec §4. Should hold no shared mutable state: collaborators are injected
and outward communication is an injected sink. This is the seam that lets
Phase 3 attach detection and lets a future process-per-camera move touch
one factory function (architecture §4).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace

from app.core.errors import CamBrainError, ValidationError
from app.services.stream.motion import MotionGate
from app.services.stream.source import Frame, FrameSource

FrameSink = Callable[[Frame], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class CameraConfig:
    """Per-camera configuration (spec §1.5: sample rate 2–5 FPS)."""

    camera_id: str
    name: str
    url: str
    sample_fps: float = 2.0

    def __post_init__(self) -> None:
        if not 2.0 <= self.sample_fps <= 5.0:
            raise ValidationError(f"sample_fps must be between 2 and 5, got {self.sample_fps}")


@dataclass
class PipelineStatus:
    """Observability snapshot for one pipeline."""

    state: str = "starting"
    frames_received: int = 0
    frames_consumed: int = 0
    last_frame_at: float | None = None
    error: str | None = None


class CameraPipeline:
    """Feed a source through the motion gate to a sampled sink.

    Args:
        config: Per-camera settings, including the sample rate.
        source: Any ``FrameSource`` (clip, RTSP, or a double in tests).
        sink: Receives frames that pass the gate at the sample rate.
        motion: The gate; a default MOG2 gate is used when omitted.
    """

    def __init__(
        self,
        config: CameraConfig,
        source: FrameSource,
        sink: FrameSink,
        *,
        motion: MotionGate | None = None,
    ) -> None:
        self._config = config
        self._source = source
        self._sink = sink
        self._motion = motion or MotionGate()
        self._min_interval = 1.0 / config.sample_fps
        self._last_send_at: float = 0.0
        self._status = PipelineStatus()

    @property
    def config(self) -> CameraConfig:
        """The camera this pipeline serves."""
        return self._config

    def snapshot(self) -> PipelineStatus:
        """Return a consistent copy, safe to read from another thread."""
        return replace(self._status)

    async def run(self) -> None:
        """Run until cancelled. Closes the source on every exit path."""
        self._status.state = "live"
        try:
            async for frame in self._source.frames():
                self._status.frames_received += 1
                self._status.last_frame_at = time.monotonic()
                if not self._motion.update(frame):
                    continue
                now = time.monotonic()
                if now - self._last_send_at < self._min_interval:
                    continue
                self._last_send_at = now
                self._status.frames_consumed += 1
                await self._sink(frame)
        except asyncio.CancelledError:
            raise
        except CamBrainError as exc:
            self._status.error = str(exc)
            raise
        finally:
            await self._source.close()
            self._status.state = "stopped"
