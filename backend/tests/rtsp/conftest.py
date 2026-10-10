"""MediaMTX fixture for real-RTSP tests.

Spec §11.1: RTSP tests are marked `rtsp`. When no MediaMTX binary is
available they skip with a visible message — never silently pass. A
silently-passing skip is indistinguishable from a green suite, which is
how a broken transport layer survives to production. MediaMTX runs
natively (no Docker): pin your version by dropping one release into
``backend/tests/rtsp/.tools/`` or putting ``mediamtx`` on PATH.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import threading
import time
from collections.abc import Awaitable, Callable, Iterator
from pathlib import Path

import av
import pytest

from tests.make_fixtures import ensure_clip

RTSP_HOST = "127.0.0.1"
RTSP_PORT = 8554
STREAM_NAME = "cambbrain"
RTSP_URL = f"rtsp://{RTSP_HOST}:{RTSP_PORT}/{STREAM_NAME}"
STARTUP_TIMEOUT_S = 60
CONFIG_DIR = Path(__file__).parent / ".mediamtx"

_PUBLISH_PAUSE = threading.Event()

CONFIG = f"""\
logLevel: warn
rtsp: yes
rtspAddress: :{RTSP_PORT}
paths:
  {STREAM_NAME}:
"""


def _mediamtx_exe() -> str | None:
    """Locate a MediaMTX binary: explicit env, bundled tool, or PATH."""
    env_exe = os.environ.get("CAMBRAIN_MEDIAMTX")
    if env_exe and Path(env_exe).is_file():
        return env_exe
    bundled = Path(__file__).parent / ".tools" / "mediamtx.exe"
    if bundled.is_file():
        return str(bundled)
    return shutil.which("mediamtx")


def _publish(clip: Path, stop: threading.Event) -> None:
    """Keep one long-lived RTSP publish open so readers never see an EOF gap.

    Reopening the RTSP sink after every clip pass leaves dead windows where a
    new reader connects and gets EOF instead of frames. The sink therefore
    lives for the whole publish: only the local source file is reopened between
    passes, so frames keep flowing without a break.
    """
    with av.open(str(clip)) as meta:
        src = meta.streams.video[0]
        width = src.codec_context.width
        height = src.codec_context.height
    while not stop.is_set():
        try:
            with av.open(
                RTSP_URL, mode="w", format="rtsp", options={"rtsp_transport": "tcp"}
            ) as sink:
                out_stream = sink.add_stream("libx264", rate=15)
                out_stream.width = width
                out_stream.height = height
                out_stream.pix_fmt = "yuv420p"
                out_stream.gop_size = 15
                while not stop.is_set():
                    _publish_pass(clip, out_stream, sink, stop)
        except (av.error.FFmpegError, OSError, ConnectionError, TimeoutError):
            if stop.is_set():
                return
            time.sleep(1.0)


def _publish_pass(
    clip: Path, out_stream: av.Stream, sink: av.OutputContainer, stop: threading.Event
) -> None:
    """Stream one full pass of the clip through the shared publish session.

    Frames are paced at the clip's real 15 fps: blasting a 300-frame clip at
    max encode speed floods the RTSP interleave queue and kills the session,
    which flaps the path (readers see 404 windows). The encoder is also
    never flushed between passes — flush signals end-of-stream, and a live
    camera session has no end until it disconnects.
    """
    frame_interval = 1 / 15
    with av.open(str(clip)) as source:
        in_stream = source.streams.video[0]
        for frame in source.decode(in_stream):
            if _PUBLISH_PAUSE.is_set():
                while _PUBLISH_PAUSE.is_set():
                    time.sleep(0.1)
            if stop.is_set():
                return
            rgb = av.VideoFrame.from_ndarray(frame.to_ndarray(format="rgb24"), format="rgb24")
            for packet in out_stream.encode(rgb):
                sink.mux(packet)
            time.sleep(frame_interval)


def _await_frames(timeout: int) -> None:
    """Block until the stream really delivers, or fail loudly with a reason."""
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            # `timeout` (µs) keeps one dead read from blocking past the deadline:
            # without it a degraded server hangs the probe forever.
            with av.open(
                RTSP_URL, options={"rtsp_transport": "tcp", "timeout": "5000000"}
            ) as probe:
                next(probe.decode(probe.streams.video[0]))
            return
        except (av.error.FFmpegError, OSError, StopIteration, IndexError) as exc:
            # IndexError: the probe connected before the publisher finished
            # initializing the video track, so `streams.video` is still empty.
            last_error = exc
            time.sleep(1.0)
    raise RuntimeError(f"MediaMTX served no frame within {timeout}s: {last_error}")


@pytest.fixture(scope="session")
def mediamtx_url() -> Iterator[str]:
    """Start MediaMTX and a clip publisher once for the whole session."""
    exe = _mediamtx_exe()
    if exe is None:
        pytest.skip(
            "No MediaMTX binary found — RTSP tests need it (spec §11.1). "
            "Drop a release into backend/tests/rtsp/.tools/ or put mediamtx on "
            "PATH (https://github.com/bluenviron/mediamtx/releases), then "
            "re-run with: pytest -m rtsp"
        )

    CONFIG_DIR.mkdir(exist_ok=True)
    config = CONFIG_DIR / "mediamtx.yml"
    config.write_text(CONFIG, encoding="utf-8")

    server = subprocess.Popen(
        [exe, str(config)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    stop = threading.Event()
    publisher = threading.Thread(target=_publish, args=(ensure_clip("motion"), stop), daemon=True)
    publisher.start()
    try:
        _await_frames(STARTUP_TIMEOUT_S)
        yield RTSP_URL
    finally:
        stop.set()
        publisher.join(timeout=10)
        server.terminate()
        try:
            server.wait(timeout=15)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)


@pytest.fixture(scope="session")
def mediamtx_pause(
    mediamtx_url: str,
) -> Iterator[tuple[str, Callable[[float], Awaitable[None]]]]:
    """RTSP URL plus an async ``pause(seconds)`` that silences the publisher.

    The publisher keeps its RTSP session open but sends no frames for the
    requested duration, then resumes. Used by reconnect-recovery tests to
    simulate a transient network stall without killing the server.
    """

    async def pause(seconds: float) -> None:
        _PUBLISH_PAUSE.set()
        try:
            await asyncio.sleep(seconds)
        finally:
            _PUBLISH_PAUSE.clear()

    yield (mediamtx_url, pause)
