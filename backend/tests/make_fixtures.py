"""Generate the synthetic clips the whole test suite runs on.

No test may require a camera (spec §11.1). Clips are produced here from
NumPy arrays and encoded with PyAV, so they are reproducible, reviewable
as code, and free to git.

Scenario → what it proves:
    static           the motion gate stays closed — no false alerts
    motion           the gate opens on a translating object
    brightness_shift the gate resets at a day/night cut instead of bursting
    low_light        the night path has something to look at
    multi_object     ROI boundary logic with several candidates
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from itertools import chain
from pathlib import Path

import av
import numpy as np

WIDTH = 640
HEIGHT = 360
FRAME_COUNT = 300
FPS = 15

CLIPS_DIR = Path(__file__).parent / "fixtures" / "clips"
CLIP_NAMES = ("static", "motion", "brightness_shift", "low_light", "multi_object")

FrameIterator = Callable[[], Iterator[np.ndarray]]


def _static() -> Iterator[np.ndarray]:
    """A still scene. Nothing should move, so nothing should fire."""
    base = np.full((HEIGHT, WIDTH, 3), 40, dtype=np.uint8)
    base[140:220, 260:380] = (200, 200, 200)
    for _ in range(FRAME_COUNT):
        yield base.copy()


def _motion() -> Iterator[np.ndarray]:
    """A bright block travelling left to right — the gate's open signal."""
    for i in range(FRAME_COUNT):
        frame = np.full((HEIGHT, WIDTH, 3), 30, dtype=np.uint8)
        x = int((i / FRAME_COUNT) * (WIDTH - 80))
        frame[140:220, x : x + 80] = (230, 230, 230)
        yield frame


def _brightness_shift() -> Iterator[np.ndarray]:
    """A hard day→night cut at frame 150: every pixel changes at once."""
    for i in range(FRAME_COUNT):
        level = 40 if i < FRAME_COUNT // 2 else 210
        frame = np.full((HEIGHT, WIDTH, 3), level, dtype=np.uint8)
        frame[150:210, 300:360] = min(level + 40, 255)
        yield frame


def _low_light() -> Iterator[np.ndarray]:
    """Near-black with a low-contrast human-sized blob — the night path."""
    rng = np.random.default_rng(7)
    for i in range(FRAME_COUNT):
        frame = rng.integers(0, 18, size=(HEIGHT, WIDTH, 3), dtype=np.uint8)
        x = 60 + int((i / FRAME_COUNT) * 300)
        frame[120:300, x : x + 70] = 45
        yield frame


def _multi_object() -> Iterator[np.ndarray]:
    """Three candidates; only one crosses into the right-hand zone."""
    for i in range(FRAME_COUNT):
        frame = np.full((HEIGHT, WIDTH, 3), 25, dtype=np.uint8)
        frame[40:100, 20 + i : 80 + i] = (180, 180, 180)
        frame[150:210, 400:460] = (160, 160, 160)
        if i > 150:
            frame[250:320, 320 + (i - 150) : 380 + (i - 150)] = (235, 235, 235)
        yield frame


_GENERATORS: dict[str, FrameIterator] = {
    "static": _static,
    "motion": _motion,
    "brightness_shift": _brightness_shift,
    "low_light": _low_light,
    "multi_object": _multi_object,
}


def _encode(path: Path, frames: Iterator[np.ndarray]) -> None:
    """Write frames to an H.264 MP4 at a fixed size and frame rate."""
    first = next(frames)
    height, width = first.shape[:2]

    with av.open(str(path), mode="w") as container:
        stream = container.add_stream("libx264", rate=FPS)
        stream.width = width
        stream.height = height
        stream.pix_fmt = "yuv420p"
        stream.options = {"crf": "30", "preset": "veryfast"}

        for array in chain((first,), frames):
            frame = av.VideoFrame.from_ndarray(array, format="rgb24")
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)


def ensure_clip(name: str) -> Path:
    """Return the path to a clip, generating it on first request."""
    if name not in _GENERATORS:
        raise KeyError(f"unknown fixture clip {name!r}; known: {sorted(CLIP_NAMES)}")
    path = CLIPS_DIR / f"{name}.mp4"
    if not path.exists():
        CLIPS_DIR.mkdir(parents=True, exist_ok=True)
        _encode(path, _GENERATORS[name]())
    return path


if __name__ == "__main__":
    for clip_name in CLIP_NAMES:
        print(ensure_clip(clip_name))
