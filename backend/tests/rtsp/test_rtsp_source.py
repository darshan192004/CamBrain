"""RtspSource against real MediaMTX (spec §11.1: skip, never pass)."""

from __future__ import annotations

import asyncio

import pytest

from app.core.errors import StreamError
from app.services.stream.rtsp_source import RtspSource, probe_rtsp

pytestmark = pytest.mark.rtsp


async def test_rtsp_source_reads_frame(mediamtx_url: str) -> None:
    """The real path: PyAV handshake over TCP, then a real frame at size."""
    src = RtspSource(mediamtx_url)
    frames = src.frames()
    try:
        frame = await asyncio.wait_for(anext(frames), timeout=10.0)
        assert frame.width == 640
        assert frame.height == 360
        assert frame.data.shape == (360, 640, 3)
    finally:
        await frames.aclose()
        await src.close()


async def test_probe_raises_no_such_stream_for_bad_path(mediamtx_url: str) -> None:
    """A missing stream classifies as NO_SUCH_STREAM, and raises, not hangs."""
    bad = mediamtx_url.rsplit("/", 1)[0] + "/does_not_exist"
    with pytest.raises(StreamError) as exc_info:
        await asyncio.wait_for(probe_rtsp(bad), timeout=15.0)
    assert str(exc_info.value).startswith("NO_SUCH_STREAM:")
