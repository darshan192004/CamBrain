"""Multipart MJPEG writer contract (API Cameras /stream).

Parts are `--frame` boundary + image/jpeg headers + JPEG body; a source
failure emits one zero-length part (boundary + blank line) so the client
re-reads the next header; a clean source end closes the multipart stream.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import numpy as np

from app.core.errors import StreamError
from app.services.stream.file_source import FileSource
from app.services.stream.mjpeg import mjpeg_parts
from app.services.stream.source import Frame

_PREFIX = b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
_EMPTY = b"--frame\r\n\r\n"
_CLOSE = b"--frame--\r\n"


def _frame(value: int = 1) -> Frame:
    data = np.full((8, 12, 3), value, dtype=np.uint8)
    return Frame(data=data, timestamp=0.0, width=12, height=8)


def _encode(frame: Frame) -> bytes:
    """Deterministic fake JPEG: SOI + one byte from the frame + EOI (4 bytes)."""
    return b"\xff\xd8" + bytes([int(frame.data[0, 0, 0])]) + b"\xff\xd9"


class _TwoFrames:
    async def frames(self) -> AsyncIterator[Frame]:
        yield _frame(1)
        yield _frame(2)

    async def close(self) -> None:
        return None


class _Flaky:
    """Round 1 yields a frame then fails; round 2 yields a frame then ends."""

    def __init__(self) -> None:
        self.rounds = 0

    def frames(self) -> AsyncIterator[Frame]:
        self.rounds += 1
        if self.rounds == 1:
            return self._round_one()
        return self._round_two()

    async def _round_one(self) -> AsyncIterator[Frame]:
        yield _frame(1)
        raise StreamError("DECODE_FAILED: boom")

    async def _round_two(self) -> AsyncIterator[Frame]:
        yield _frame(2)

    async def close(self) -> None:
        return None


class _AlwaysFails:
    def frames(self) -> AsyncIterator[Frame]:
        return self._fail()

    async def _fail(self) -> AsyncIterator[Frame]:
        raise StreamError("CONNECT_TIMEOUT: no frame")
        yield  # pragma: no cover - makes this an async generator

    async def close(self) -> None:
        return None


async def test_part_headers_and_jpeg_body() -> None:
    parts = [part async for part in mjpeg_parts(_TwoFrames(), encoder=_encode)]
    assert len(parts) == 3
    jpeg1 = _encode(_frame(1))
    assert parts[0] == _PREFIX + b"5\r\n\r\n" + jpeg1 + b"\r\n"
    assert parts[1].startswith(_PREFIX + b"5\r\n\r\n")
    assert parts[1].endswith(b"\r\n")
    assert parts[2] == _CLOSE


async def test_error_emits_empty_part_then_recovers() -> None:
    src = _Flaky()
    parts = [part async for part in mjpeg_parts(src, encoder=_encode)]
    assert len(parts) == 4
    assert b"Content-Length" in parts[0]  # frame before the failure
    assert parts[1] == _EMPTY  # zero-length part: client re-reads next header
    assert b"Content-Length" in parts[2]  # recovered with the next round
    assert parts[3] == _CLOSE
    assert src.rounds == 2


async def test_consecutive_failures_give_up() -> None:
    """A dead source must not spin emitting empty parts forever."""
    parts = [part async for part in mjpeg_parts(_AlwaysFails(), encoder=_encode)]
    assert parts == [_EMPTY, _EMPTY, _EMPTY, _CLOSE]


async def test_source_end_emits_close_boundary(gate_clip_path: Path) -> None:
    src = FileSource(Path(str(gate_clip_path)), loop=False)
    parts = [part async for part in mjpeg_parts(src, encoder=_encode)]
    assert parts[-1] == _CLOSE
    assert len(parts) >= 3  # a clip yields many frames, then the close line
    assert all(b"Content-Length" in part for part in parts[:-1])
