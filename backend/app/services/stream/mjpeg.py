"""Multipart/x-mixed-replace writer and stream slot cap (API Cameras /stream).

Per API.md: on a source error emit a **zero-length part** (boundary + blank
line) so the client re-reads the next header instead of dying with us; give
up after three consecutive failures so a dead source cannot spin; always
close the source. The slot cap implements decision D1 — 12 concurrent
streams per client IP, sized for the 8-tile grid plus focused views.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator, Callable

from app.services.stream.jpeg import encode_jpeg
from app.services.stream.source import Frame, FrameSource

BOUNDARY = b"frame"
DEFAULT_PER_IP = 12
MAX_CONSECUTIVE_FAILURES = 3

_PREFIX = b"--" + BOUNDARY + b"\r\nContent-Type: image/jpeg\r\nContent-Length: "
_EMPTY_PART = b"--" + BOUNDARY + b"\r\n\r\n"
_CLOSE = b"--" + BOUNDARY + b"--\r\n"


async def mjpeg_parts(
    source: FrameSource, *, encoder: Callable[[Frame], bytes] = encode_jpeg
) -> AsyncIterator[bytes]:
    """Yield multipart bytes for one camera stream, then close the source.

    `encoder` is injectable for deterministic tests; the default encodes
    each `Frame` with `encode_jpeg`.
    """
    failures = 0
    try:
        while True:
            round_yielded = False
            ended_cleanly = False
            try:
                async for frame in source.frames():
                    jpeg = encoder(frame)
                    round_yielded = True
                    failures = 0
                    yield _PREFIX + str(len(jpeg)).encode() + b"\r\n\r\n" + jpeg + b"\r\n"
                ended_cleanly = True
            except Exception:  # noqa: BLE001 - one bad round must not kill the view
                failures += 1
                yield _EMPTY_PART
            if ended_cleanly:
                break
            if not round_yielded and failures >= MAX_CONSECUTIVE_FAILURES:
                break
    finally:
        with contextlib.suppress(Exception):
            await source.close()
    yield _CLOSE


class StreamSlots:
    """Per-client-IP concurrent stream counter (D1: cap `per_ip` each)."""

    def __init__(self, per_ip: int = DEFAULT_PER_IP) -> None:
        self.per_ip = per_ip
        self._counts: dict[str, int] = {}

    def try_acquire(self, ip: str) -> bool:
        """Take a slot for `ip`, or False when that client is at the cap."""
        current = self._counts.get(ip, 0)
        if current >= self.per_ip:
            return False
        self._counts[ip] = current + 1
        return True

    def release(self, ip: str) -> None:
        """Give a slot back; never drives the count below zero."""
        left = self._counts.get(ip, 0) - 1
        if left > 0:
            self._counts[ip] = left
        else:
            self._counts.pop(ip, None)


_STREAM_SLOTS = StreamSlots()


def get_stream_slots() -> StreamSlots:
    """FastAPI dependency: the process-wide slot table (tests override it)."""
    return _STREAM_SLOTS
