"""Prove the RTSP harness delivers real frames before anything depends on it.

Phase 0 gate (spec §10): MediaMTX reachable. Reads use raw PyAV — the
application-side RtspSource arrives in Phase 1 against this same fixture.
"""

from __future__ import annotations

import av
import pytest

pytestmark = pytest.mark.rtsp


def test_mediamtx_serves_generated_clip(mediamtx_url: str) -> None:
    """The harness must deliver the fixture we encoded, at its real size."""
    with av.open(mediamtx_url, options={"rtsp_transport": "tcp"}) as container:
        frame = next(container.decode(container.streams.video[0]))
    assert frame.width == 640
    assert frame.height == 360


def test_stream_survives_repeated_open_close(mediamtx_url: str) -> None:
    """Phase 1's backoff tests reopen the same URL many times. The harness
    must support that, or those tests will fail for the wrong reason."""
    for _ in range(3):
        with av.open(mediamtx_url, options={"rtsp_transport": "tcp"}) as container:
            next(container.decode(container.streams.video[0]))


def test_missing_path_raises_instead_of_hanging(mediamtx_url: str) -> None:
    """Phase 1 maps this failure to error_code NO_SUCH_STREAM. If it hangs
    instead of raising, the whole typed-error design is untestable."""
    bad_url = mediamtx_url.rsplit("/", 1)[0] + "/does_not_exist"
    with (
        pytest.raises((av.error.FFmpegError, OSError)),
        av.open(bad_url, options={"rtsp_transport": "tcp"}) as container,
    ):
        next(container.decode(container.streams.video[0]))
