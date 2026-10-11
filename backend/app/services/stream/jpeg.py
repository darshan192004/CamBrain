"""RGB ndarray -> JPEG bytes for snapshot and MJPEG (API Cameras).

`Frame.data` is a raw RGB ndarray (`source.py`), so both the ROI editor's
frozen still and the MJPEG multipart parts need an encoder. One helper, one
quality knob; a fresh context per frame (MJPEG is intra-only, so there is no
state to reuse).
"""

from __future__ import annotations

import av
from av.codec import CodecContext

from app.services.stream.source import Frame

DEFAULT_QUALITY = 5


def encode_jpeg(frame: Frame, *, quality: int = DEFAULT_QUALITY) -> bytes:
    """Encode one frame as JPEG.

    `quality` maps to FFmpeg's mjpeg `qscale` (2 = best, 31 = worst); 5 is
    the CCTV default — sharp enough to read a face, small enough for tiles.
    Options and geometry must be set before the first `encode` opens the
    codec. PyAV re-formats rgb24 to the encoder's yuvj420p automatically.
    """
    ctx = CodecContext.create("mjpeg", "w")
    ctx.width, ctx.height = frame.width, frame.height
    ctx.pix_fmt = "yuvj420p"
    ctx.options = {"qscale": str(quality)}
    vf = av.VideoFrame.from_ndarray(frame.data, format="rgb24")
    packets = ctx.encode(vf)
    return b"".join(bytes(packet) for packet in packets)
