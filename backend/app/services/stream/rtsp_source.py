"""Real-RTSP source with a stall watchdog and jittered reconnection.

Implements ``FrameSource`` on PyAV. Reconnection and the stall watchdog live
here so the pipeline and manager never touch transport details (spec §4.6,
§5.1). The backoff policy is a pure helper below, unit-tested offline; the
reconnect loop itself is proven against MediaMTX (spec §11.4).
"""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import AsyncIterator

import av

from app.core.errors import StreamError, safe_error
from app.core.logging import get_logger, mask_url
from app.services.stream.source import Frame

DEFAULT_STALL_TIMEOUT_S = 3.0

_log = get_logger(__name__)


def next_backoff(attempt: int, *, base: float = 1.0, cap: float = 60.0) -> float:
    """Full-jitter exponential backoff in seconds (spec §4.6).

    Full jitter randomises each retry over [0, min(cap, base*2**attempt)),
    which keeps eight cameras from retrying a rebooting NVR in lockstep.

    Args:
        attempt: Number of consecutive failures so far (0 for the first).
        base: The one-second floor.
        cap: The sixty-second ceiling (spec §1.5: 1s → 60s).

    Returns:
        A delay in seconds, never negative and never above ``cap``.
    """
    window = min(cap, base * (2.0**attempt))
    return random.uniform(0.0, window)


def classify_rtsp_error(exc: Exception) -> str:
    """Map a PyAV transport failure to a stable reason (spec §7.2 codes).

    Phase 2's ``POST /api/v1/cameras/{id}/test`` returns these codes; the
    classifier is built here so it is testable without HTTP.
    """
    if not isinstance(exc, (av.error.FFmpegError, OSError)):
        return "DECODE_FAILED"
    text = str(exc).lower()
    if any(
        token in text
        for token in ("404", "400", "not found", "no such", "invalid data", "bad request")
    ):
        return "NO_SUCH_STREAM"
    if "connection refused" in text or isinstance(exc, ConnectionRefusedError):
        return "HOST_UNREACHABLE"
    if any(token in text for token in ("401", "403", "unauthor", "wrong password", "auth")):
        return "AUTH_FAILED"
    if any(token in text for token in ("timed out", "timeout")) or isinstance(exc, TimeoutError):
        return "CONNECT_TIMEOUT"
    return "DECODE_FAILED"


async def probe_rtsp(url: str, *, timeout_s: float = 5.0) -> None:
    """Open, read one frame, close. Raises ``StreamError`` with a reason.

    Used by camera diagnostics (spec §7.2) and by tests. Does not retry:
    unlike ``RtspSource.frames`` this surfaces the first failure as the
    typed error rather than reconnecting behind the caller's back.
    """
    safe_url = mask_url(url)
    timeout_us = str(int(timeout_s * 1_000_000))

    def _probe() -> None:
        with av.open(url, options={"rtsp_transport": "tcp", "timeout": timeout_us}) as container:
            next(container.decode(container.streams.video[0]))

    try:
        await asyncio.wait_for(asyncio.to_thread(_probe), timeout=timeout_s + 2.0)
    except TimeoutError as exc:
        raise StreamError(safe_error(f"CONNECT_TIMEOUT: {safe_url}")) from exc
    except (av.error.FFmpegError, OSError, StopIteration) as exc:
        reason = classify_rtsp_error(exc)
        raise StreamError(safe_error(f"{reason}: {safe_url} ({safe_error(str(exc))})")) from exc


class RtspSource:
    """Read frames from an RTSP endpoint, reconnecting forever.

    The stall watchdog is a socket timeout: PyAV's ``timeout`` option bounds
    every read, so a silent stream surfaces as a transport error instead of
    a decode that blocks forever. On any transport failure the container is
    closed in ``finally`` and reopened after full-jitter backoff.
    """

    def __init__(self, url: str, *, stall_timeout_s: float = DEFAULT_STALL_TIMEOUT_S) -> None:
        self._url = url
        self._stall_timeout_us = int(stall_timeout_s * 1_000_000)
        self._closed = False
        self._attempt = 0
        self._last_error: StreamError | None = None

    async def frames(self) -> AsyncIterator[Frame]:
        while not self._closed:
            container = None
            try:
                container = av.open(
                    self._url,
                    options={
                        "rtsp_transport": "tcp",
                        "timeout": str(self._stall_timeout_us),
                    },
                )
                stream = container.streams.video[0]
                # One decode generator per connection: PyAV may pull several
                # packets to yield one frame, and a fresh generator per call
                # would drop whatever the discarded one had already decoded.
                iterator = container.decode(stream)
                while not self._closed:
                    try:
                        raw = next(iterator)
                    except StopIteration:
                        break  # EOF: the server closed — reconnect below.
                    # A live connection proves the network recovered: reset the
                    # backoff ladder so a later blip starts at <=1s again
                    # (spec §1.5's 5s transient bound applies to every drop).
                    self._attempt = 0
                    data = raw.to_ndarray(format="rgb24").copy()
                    yield Frame(
                        data=data,
                        timestamp=time.monotonic(),
                        width=raw.width,
                        height=raw.height,
                    )
            except (av.error.FFmpegError, OSError) as exc:
                if not self._closed:
                    self._note_failure(exc)
            finally:
                if container is not None:
                    container.close()
            if self._is_closed():
                return
            await asyncio.sleep(next_backoff(self._attempt))
            self._attempt += 1

    async def close(self) -> None:
        """Idempotent. The iterator terminates at its next checked boundary."""
        self._closed = True

    def _is_closed(self) -> bool:
        """Read ``_closed`` through a call so mypy cannot narrow it to dead."""
        return self._closed

    def _note_failure(self, exc: Exception) -> None:
        reason = classify_rtsp_error(exc)
        safe = mask_url(self._url)
        self._last_error = StreamError(safe_error(f"{reason}: {safe} ({safe_error(str(exc))})"))
        _log.warning(
            "rtsp_source.reconnect",
            reason=reason,
            attempt=self._attempt,
            camera_url=safe,
            error=safe_error(str(exc)),
        )

    @property
    def last_error(self) -> StreamError | None:
        """The most recent transport failure, for status surfaces."""
        return self._last_error
