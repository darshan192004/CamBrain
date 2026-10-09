"""MediaMTX container fixture for real-RTSP tests.

Spec §11.1: RTSP tests are marked `rtsp`. When Docker is unavailable they
skip with a visible message — never silently pass. A silently-passing skip
is indistinguishable from a green suite, which is how a broken transport
layer survives to production.
"""

from __future__ import annotations

import shutil
import subprocess
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import av
import pytest

from tests.make_fixtures import ensure_clip

MEDIAMTX_IMAGE = "bluenviron/mediamtx:1.11"
RTSP_HOST = "127.0.0.1"
RTSP_PORT = 8554
STREAM_NAME = "cambbrain"
RTSP_URL = f"rtsp://{RTSP_HOST}:{RTSP_PORT}/{STREAM_NAME}"
STARTUP_TIMEOUT_S = 60
CONFIG_DIR = Path(__file__).parent / ".mediamtx"

CONFIG = f"""\
logLevel: warn
rtsp: yes
rtspAddress: :{RTSP_PORT}
gopCache: no
paths:
  {STREAM_NAME}:
"""


def docker_available() -> bool:
    """True when the daemon answers — `docker` on PATH alone proves nothing."""
    if shutil.which("docker") is None:
        return False
    try:
        result = subprocess.run(["docker", "info"], capture_output=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _publish(clip: Path, stop: threading.Event) -> None:
    """Push the clip to MediaMTX in a loop so readers always have a source."""
    while not stop.is_set():
        try:
            _publish_once(clip, stop)
        except (av.error.FFmpegError, OSError, ConnectionError, TimeoutError):
            if stop.is_set():
                return
            time.sleep(1.0)


def _publish_once(clip: Path, stop: threading.Event) -> None:
    """One continuous publish of the clip."""
    with av.open(str(clip)) as source:
        in_stream = source.streams.video[0]
        with av.open(RTSP_URL, mode="w", format="rtsp", options={"rtsp_transport": "tcp"}) as sink:
            out_stream = sink.add_stream("libx264", rate=15)
            out_stream.width = in_stream.codec_context.width
            out_stream.height = in_stream.codec_context.height
            out_stream.pix_fmt = "yuv420p"
            for frame in source.decode(in_stream):
                if stop.is_set():
                    return
                rgb = av.VideoFrame.from_ndarray(frame.to_ndarray(format="rgb24"), format="rgb24")
                for packet in out_stream.encode(rgb):
                    sink.mux(packet)
            for packet in out_stream.encode():
                sink.mux(packet)


def _await_frames(timeout: int) -> None:
    """Block until the stream really delivers, or fail loudly with a reason."""
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with av.open(RTSP_URL, options={"rtsp_transport": "tcp"}) as probe:
                next(probe.decode(probe.streams.video[0]))
            return
        except (av.error.FFmpegError, OSError, StopIteration) as exc:
            last_error = exc
            time.sleep(1.0)
    raise RuntimeError(f"MediaMTX served no frame within {timeout}s: {last_error}")


@pytest.fixture(scope="session")
def mediamtx_url() -> Iterator[str]:
    """Start MediaMTX and a clip publisher once for the whole session."""
    if not docker_available():
        pytest.skip(
            "Docker is not available — RTSP tests need MediaMTX (spec §11.1). "
            "Start Docker Desktop, then re-run with: pytest -m rtsp"
        )

    CONFIG_DIR.mkdir(exist_ok=True)
    (CONFIG_DIR / "mediamtx.yml").write_text(CONFIG, encoding="utf-8")

    container = subprocess.Popen(
        [
            "docker",
            "run",
            "--rm",
            "-p",
            f"{RTSP_PORT}:{RTSP_PORT}",
            "-v",
            f"{CONFIG_DIR}:/etc/mediamtx:ro",
            MEDIAMTX_IMAGE,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
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
        container.terminate()
        try:
            container.wait(timeout=15)
        except subprocess.TimeoutExpired:
            container.kill()
            container.wait(timeout=5)
