"""One-shot frame probe for camera diagnostics (spec §7.2, API Cameras /test).

Reads up to `max_frames` within a wall budget and reports dimensions, fps,
and latency on success; on failure it maps the exception to one of the six
documented `error_code`s. A failed probe is data, never an HTTP error.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from dataclasses import dataclass

from app.core.errors import StreamError
from app.core.logging import mask_url
from app.services.stream.rtsp_source import classify_rtsp_error
from app.services.stream.source import Frame, FrameSource

#: The six codes API.md assigns to POST /cameras/{id}/test.
ERROR_CODES = frozenset(
    {
        "AUTH_FAILED",
        "CONNECT_TIMEOUT",
        "HOST_UNREACHABLE",
        "NO_SUCH_STREAM",
        "DECODE_FAILED",
        "CANCELLED",
    }
)

_MESSAGES = {
    "AUTH_FAILED": "Authentication failed. Check the username and password.",
    "NO_SUCH_STREAM": "No such stream — check the channel or path in the URL.",
    "DECODE_FAILED": "The stream connected but could not be decoded.",
}


@dataclass(frozen=True)
class ProbeOutcome:
    """Result of one probe: success metrics or a typed failure reason."""

    ok: bool
    message: str
    latency_ms: int | None = None
    frame_width: int | None = None
    frame_height: int | None = None
    fps: float | None = None
    error_code: str | None = None


def classify_code(exc: BaseException, *, fallback: str) -> str:
    """Classify an exception, honouring StreamError's typed message prefix."""
    if isinstance(exc, StreamError):
        prefix = str(exc).split(":", 1)[0].strip()
        if prefix in ERROR_CODES:
            return prefix
    if isinstance(exc, TimeoutError):
        return fallback
    if not isinstance(exc, Exception):
        return fallback
    code = classify_rtsp_error(exc)
    return code if code in ERROR_CODES else fallback


def failure_outcome(code: str, url: str) -> ProbeOutcome:
    if code in _MESSAGES:
        message = _MESSAGES[code]
    elif code == "HOST_UNREACHABLE":
        message = f"Could not connect on {mask_url(url)} — host unreachable."
    else:  # CONNECT_TIMEOUT, CANCELLED
        message = f"Could not connect on {mask_url(url)} — timed out."
    return ProbeOutcome(ok=False, message=message, error_code=code)


async def probe_source(
    source: FrameSource,
    *,
    url: str,
    budget_s: float = 3.0,
    max_frames: int = 10,
) -> ProbeOutcome:
    """Read up to `max_frames` from `source` within `budget_s`, then close it.

    `url` is the camera's credential-free `rtsp_url`, used for human messages.
    """
    start = time.monotonic()
    count = 0
    width = height = 0
    first_at = last_at = start
    failure: BaseException | None = None
    try:
        async with asyncio.timeout(budget_s):
            async for frame in source.frames():
                if count == 0:
                    width, height = frame.width, frame.height
                    first_at = time.monotonic()
                count += 1
                last_at = time.monotonic()
                if count >= max_frames:
                    break
    except TimeoutError:
        pass  # count == 0 handled below; budget hit after frames is success
    except Exception as exc:  # noqa: BLE001 - classified, never re-raised raw
        failure = exc
    finally:
        with contextlib.suppress(Exception):
            await source.close()

    if failure is not None:
        return failure_outcome(classify_code(failure, fallback="CONNECT_TIMEOUT"), url)
    if count == 0:
        last = getattr(source, "last_error", None)
        code = (
            classify_code(last, fallback="CONNECT_TIMEOUT")
            if isinstance(last, BaseException)
            else "CONNECT_TIMEOUT"
        )
        return failure_outcome(code, url)

    latency_ms = int((first_at - start) * 1000)
    span = last_at - first_at
    fps = round((count - 1) / span, 1) if count > 1 and span > 0 else 0.0
    return ProbeOutcome(
        ok=True,
        message=f"Connected. {width}\u00d7{height} @ {fps:g} fps.",
        latency_ms=latency_ms,
        frame_width=width,
        frame_height=height,
        fps=fps,
    )


async def capture_frame(source: FrameSource, *, budget_s: float = 5.0) -> Frame:
    """Read the first frame within `budget_s`, then close the source.

    Raises `StreamError` with a typed `CODE:` prefix when no frame arrives;
    exceptions from the source itself propagate for `classify_code`.
    """
    try:
        async with asyncio.timeout(budget_s):
            async for frame in source.frames():
                return frame
        last = getattr(source, "last_error", None)
        if isinstance(last, StreamError):
            raise last
        raise StreamError(f"CONNECT_TIMEOUT: no frame within {budget_s:g}s")
    except TimeoutError as exc:
        last = getattr(source, "last_error", None)
        if isinstance(last, StreamError):
            raise last from exc
        raise StreamError(f"CONNECT_TIMEOUT: no frame within {budget_s:g}s") from exc
    finally:
        with contextlib.suppress(Exception):
            await source.close()
