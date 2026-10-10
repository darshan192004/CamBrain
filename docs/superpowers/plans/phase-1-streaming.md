# CamBrain Phase 1 — Streaming Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Note for this repo:** SDD is suspended (human directive, recorded in the Phase 0 ledger). Execution here is performed directly by the controller with review between tasks.

**Goal:** Build the streaming engine — `FrameSource` seam, `FileSource`, `RtspSource` with reconnection, `MotionGate`, `LatestFrameSlot`, `CameraPipeline`, `StreamManager` — so a camera ingests, samples, gates motion, and survives 50 reconnects with flat memory.

**Architecture:** Single process. One thread per camera, each running its own asyncio loop. Every camera is `RtspSource → MotionGate → sampled sink` inside a `CameraPipeline`; `StreamManager` owns the pipeline lifecycle. The motion gate (MOG2 on a 640×360 grey downscale) is what makes 8 cameras fit on an N100 — no motion, no inference work. Reconnection and the stall watchdog live inside `RtspSource` with full-jitter backoff. Everything is testable offline from a clip via `FileSource` (spec §11.1); the live-RTSP canaries run against the native MediaMTX fixture from Phase 0.

**Tech Stack:** Python 3.13 · PyAV (bundled in `requirements.lock.txt` as `av==19.0.1`) · NumPy (`numpy==2.5.3`) · opencv-python-headless (`opencv-python-headless==5.0.0.93`: MOG2 + resize) · psutil (`psutil==7.2.2`, the memory canary) · structlog · pytest-asyncio. **No dependency changes — `requirements.lock.txt` is untouched in this phase.**

**Spec:** [`docs/superpowers/specs/spec.md`](../specs/spec.md) — §4.3–4.6 (concurrency, backpressure, frame lifecycle, reconnection), §5.1–5.4 (component contracts), §10.2 (build order), §11 (hardware-free tests, canaries), §12 (verification matrix). Design: [`docs/superpowers/specs/2026-10-05-cambrain-mvp-design.md`](../specs/2026-10-05-cambrain-mvp-design.md) §5 (contracts) and §8 (test strategy).

**Execution note:** implement this on a new branch off `main` **after** the Phase 0 PR is merged (or explicitly at the user's call while it is open). The Phase 0 branch ends at the PR; it must not accumulate Phase 1 work.

---

## Global Constraints

These apply to every task; each task's requirements implicitly include this block.

- **Licensing — hard constraint, CI-enforced:** no AGPL dependency in any form; `models/*.onnx` gitignored; `models/LICENSE-MODEL-NOTICE` records provenance for every shipped weight file. This phase adds no packages, so the licence scan is unaffected.
- **Stack floors (from the lock, already installed):** PyAV `av` (bundled FFmpeg — no `ffmpeg` on PATH required), NumPy, `opencv-python-headless` (never the full `opencv-python`), structlog, psutil. Python 3.13.
- **Language/type rules:** Python line length 100; type hints on every signature; **no `Any` outside tests and protocol boundaries**; Google-style docstrings on every public function; every module has a module docstring. `mypy --strict` runs on `backend/app` only; ruff's `ASYNC` rules forbid blocking calls in `async def` where the linter can see them (wrap `time.sleep`-style waits in `asyncio`; PyAV decode is *intended* to block the loop — it runs on a per-camera loop and releases the GIL).
- **Concurrency (spec §4.3, design D4):** single process; one thread per camera, each with its own asyncio loop. `CameraPipeline` holds **no shared mutable state**: collaborators are constructor-injected, outward communication is an injected sink. This seam must not be eroded — it is the process-per-camera escape hatch.
- **Backpressure (spec §4.4):** between a source and every *consumer*, a `LatestFrameSlot`; a full queue means **replace the oldest frame — never block, never accumulate**. Frames are dropped before resize, not after decode.
- **Frame ownership (spec §4.5):** a `Frame.data` ndarray is **owned**, never a borrowed decoder view — every decode does a `.copy()`. The decoder container closes in `finally` on every path, including cancellation.
- **Secrets:** RTSP URLs are masked (`rtsp://***:***@host:port/path`) everywhere they reach logs or exceptions — use `safe_error()`/`mask_url()` from `app.core.logging`.
- **No cameras (spec §11.1):** no test may require a camera. Sources are `FileSource` (clips) and `RtspSource` (the native MediaMTX fixture). RTSP tests are marked `rtsp` and **skip with a visible message when no MediaMTX binary is present — never silently pass**. Long-running tests are marked `slow`.
- **Conventions:** Conventional Commits, scope `stream:`; commit messages explain *why*. Never commit: weights, `.env`, `cambrain.db`, clips, `node_modules/`, build output. `test_memory_is_flat_across_reconnects` and `test_no_secret_in_log_output` are canaries — they may not be skipped (other than the documented `rtsp`/`slow` markers).
- **Known stale text (touch only if convenient):** `pyproject.toml` line 13 — the `rtsp` marker description still says "MediaMTX Docker container". When `pyproject.toml` is next edited, change it to "MediaMTX native binary". Not required this phase.

---

## File Structure (Phase 1 slice)

```
backend/app/services/__init__.py            CREATE  (empty)
backend/app/services/stream/__init__.py     CREATE  (empty)
backend/app/services/stream/source.py       CREATE  Frame, FrameSource (spec §5.1)
backend/app/services/stream/file_source.py  CREATE  FileSource (clip, loop|once)
backend/app/services/stream/motion.py       CREATE  MotionGate (MOG2 + brightness reset)
backend/app/services/stream/slot.py         CREATE  LatestFrameSlot (backpressure)
backend/app/services/stream/rtsp_source.py  CREATE  RtspSource, next_backoff, probe_rtsp
backend/app/services/stream/pipeline.py     CREATE  CameraConfig, CameraPipeline, PipelineStatus
backend/app/services/stream/stream_manager.py  CREATE  StreamManager (lifecycle owner)

backend/tests/test_source.py                CREATE  FileSource conformance + 1080p
backend/tests/test_motion.py                CREATE  gate behaviour, fixtures
backend/tests/test_slot.py                  CREATE  backpressure semantics
backend/tests/test_pipeline.py              CREATE  sampling, 8 concurrent, idle CPU
backend/tests/test_stream_manager.py        CREATE  backoff unit + live-RTSP canaries
backend/tests/rtsp/test_rtsp_source.py      CREATE  RtspSource against MediaMTX
backend/tests/rtsp/conftest.py              MODIFY  add a pausable publisher for the drop test
backend/tests/conftest.py                   MODIFY  re-export the live-RTSP fixtures
```

One responsibility per file. `CameraConfig` lives with `CameraPipeline` (it is consumed there and constructed by Phase 2's API layer from the `cameras` rows, whose `sample_fps` matches API.md).

---

## Verification matrix (Phase 1 rows from spec §12)

| Requirement | Proving test (this phase) | Markers |
|---|---|---|
| Concurrent cameras — 8 | `test_pipeline.py::test_eight_pipelines_concurrently` | — |
| Sample rate 2–5 FPS configurable | `test_pipeline.py::test_sample_fps_is_honoured` (+ reject outside range) | — |
| Reconnect transient ≤ 5s | `test_stream_manager.py::test_transient_drop_recovers_fast` | `rtsp` |
| Reconnect backoff to 60s | `test_stream_manager.py::test_backoff_reaches_cap` | — |
| **No thundering herd** | `test_stream_manager.py::test_backoff_has_jitter` | — |
| **Memory flat** | `test_stream_manager.py::test_memory_is_flat_across_reconnects` | `rtsp slow` |
| Idle CPU < 5% | `test_pipeline.py::test_idle_cpu_under_5_percent` | `slow` |
| Works at 1080p | `test_source.py::test_1080p_input_downscaled` | — |
| RTSP never silently passes | `test_stream_manager.py::test_*` two rtsp canaries + `tests/rtsp/test_rtsp_source.py` | `rtsp` |
| Hardware-free default suite | `pytest -m "not rtsp and not slow"` stays green with no MediaMTX binary | — |

---

## Definition of done (spec §13)

1. Every test named above exists and passes.
2. The gate is demonstrated: the memory canary observed (a printed RSS trend, not assumed).
3. `ruff check` and `mypy backend/app` are clean; `ruff format --check backend` passes.
4. Every new public function has a Google-style docstring; every module has a module docstring.
5. No secret is logged or stored — RTSP URLs only ever appear masked; the existing `test_no_secret_in_log_output` stays green.
6. `git status` shows no weights, database files, clips, or `.env`.
7. Commit messages explain **why**.

---

## Task 1.1: The `FrameSource` seam and `FileSource`

**Files:**
- Create: `backend/app/services/__init__.py`, `backend/app/services/stream/__init__.py`
- Create: `backend/app/services/stream/source.py`
- Create: `backend/app/services/stream/file_source.py`
- Create: `backend/tests/test_source.py`

**Interfaces:**
- Consumes: fixtures `clip_path` (`backend/tests/conftest.py`); `tests.make_fixtures.FRAME_COUNT` (300).
- Produces: `Frame` (dataclass used by every later task); `FrameSource` (Protocol used everywhere); `FileSource(path, *, loop=True)` with `async frames()` / `async close()`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_source.py`:

```python
"""Protocol conformance for the source seam and FileSource (spec §5.1).

Everything here runs offline from a generated clip. The 1080p row of the
verification matrix (§12) is split: the gate's downscale handling is proven
by pipeline tests; the frame contract is proven here.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import numpy as np
import pytest

from app.services.stream.file_source import FileSource
from app.services.stream.source import Frame, FrameSource
from tests.make_fixtures import FRAME_COUNT


async def test_file_source_yields_owned_frames(clip_path: Path) -> None:
    """Frames carry real dimensions, monotonic capture times, owned buffers."""
    src = FileSource(clip_path)
    frames = src.frames()
    try:
        frames_seen: list[Frame] = [
            await anext(frames) for _ in range(3)
        ]
    finally:
        await frames.aclose()
        await src.close()

    assert frames_seen[0].width == 640
    assert frames_seen[0].height == 360
    assert frames_seen[0].data.shape == (360, 640, 3)
    assert frames_seen[0].data.dtype == np.uint8
    assert [f.data.base is None for f in frames_seen] == [True, True, True]
    assert frames_seen[0].timestamp <= frames_seen[1].timestamp
    assert frames_seen[1].timestamp <= frames_seen[2].timestamp


async def test_later_decode_does_not_corrupt_earlier_data(clip_path: Path) -> None:
    """`data` must be an owned copy — decoder buffers are reused by PyAV."""
    src = FileSource(clip_path)
    frames = src.frames()
    try:
        first = await anext(frames)
        snapshot = first.data.copy()
        await anext(frames)
        await anext(frames)
        assert np.array_equal(first.data, snapshot)
        assert not np.shares_memory(snapshot, first.data)
    finally:
        await frames.aclose()
        await src.close()


async def test_file_source_once_mode_ends(clip_path: Path) -> None:
    """`loop=False` yields exactly the clip's frames, then stops."""
    src = FileSource(clip_path, loop=False)
    count = 0
    frames = src.frames()
    try:
        async for _ in frames:
            count += 1
    finally:
        await frames.aclose()
        await src.close()
    assert count == FRAME_COUNT


async def test_file_source_loop_mode_wraps(clip_path: Path) -> None:
    """`loop=True` (default) keeps yielding past the end of the clip.

    The motion clip is 300 frames; a loop must pass the boundary.
    """
    src = FileSource(clip_path)
    frames = src.frames()
    count = 0
    try:
        async for _ in frames:
            count += 1
            if count > FRAME_COUNT + 5:
                break
        assert count > FRAME_COUNT
    finally:
        await frames.aclose()
        await src.close()


async def test_close_is_idempotent_and_terminates_iteration(clip_path: Path) -> None:
    """close() twice is safe, and the iterator ends after close (spec §5.1)."""
    src = FileSource(clip_path)
    frames = src.frames()
    first = await anext(frames)
    assert first.width == 640
    await src.close()
    await src.close()
    with pytest.raises(StopAsyncIteration):
        await anext(frames)
    await frames.aclose()


def test_file_source_satisfies_protocol(clip_path: Path) -> None:
    """Static structural check that FileSource implements FrameSource."""
    src: FrameSource = FileSource(clip_path)
    assert callable(src.frames)
    assert callable(src.close)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `$env:PATH = "E:\CamBrain\.venv\Scripts;" + $env:PATH; pytest backend/tests/test_source.py -v`
Expected: `ModuleNotFoundError: No module named 'app.services.stream'`.

- [ ] **Step 3: Write the implementation**

`backend/app/services/__init__.py`:

```python
"""Bounded services: stream, inference, alerts, events (later phases)."""
```

`backend/app/services/stream/__init__.py`:

```python
"""The streaming engine: sources, gating, backpressure, pipelines."""
```

`backend/app/services/stream/source.py`:

```python
"""Frame contract and the source seam that removes hardware dependency.

Spec §5.1. Every source implements ``FrameSource``, so the entire pipeline
is testable from a file on disk and CI needs no cameras. Because it is
narrow, a new source (ONVIF, USB webcam, vendor SDK) is one new class.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol

import numpy as np


@dataclass(frozen=True, slots=True)
class Frame:
    """One decoded frame.

    Frozen so a consumer cannot mutate a frame another consumer holds.
    ``slots`` because these are allocated continuously and per-instance
    ``__dict__`` overhead is measurable at 8 cameras x 15fps.

    ``data`` is owned by the frame — never a borrowed view of a decoder
    buffer, which PyAV reuses on the next decode.
    """

    data: np.ndarray  # (H, W, 3) uint8 RGB, owned.
    timestamp: float  # monotonic seconds from capture.
    width: int
    height: int


class FrameSource(Protocol):
    """Produces frames from something. The seam that removes hardware."""

    async def frames(self) -> AsyncIterator[Frame]:
        """Yield frames until cancelled or the source is exhausted."""
        ...

    async def close(self) -> None:
        """Release every resource. Idempotent and safe mid-iteration."""
        ...
```

`backend/app/services/stream/file_source.py`:

```python
"""Decode a local clip. Loop or once. The CI-safe stand-in for a camera.

Every Phase 1 offline test runs from this class through the ``FrameSource``
seam, so a camera is never required (spec §11.1).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from pathlib import Path

import av

from app.services.stream.source import Frame, FrameSource


class FileSource:
    """Decode ``path`` repeatedly (loop) or once, yielding owned RGB frames.

    The container closes in ``finally`` on every path — including
    cancellation — so a handle is never leaked across reconnects (spec §4.5).
    """

    def __init__(self, path: Path, *, loop: bool = True) -> None:
        self._path = path
        self._loop = loop
        self._closed = False

    async def frames(self) -> AsyncIterator[Frame]:
        while not self._closed:
            container = av.open(str(self._path))
            try:
                stream = container.streams.video[0]
                for raw in container.decode(stream):
                    if self._closed:
                        return
                    data = raw.to_ndarray(format="rgb24").copy()
                    yield Frame(
                        data=data,
                        timestamp=time.monotonic(),
                        width=raw.width,
                        height=raw.height,
                    )
            finally:
                container.close()
            if not self._loop:
                return
            await asyncio.sleep(0)

    async def close(self) -> None:
        """Idempotent: repeated calls and calls mid-iteration are safe."""
        self._closed = True
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest backend/tests/test_source.py -v`
Expected: all 6 pass.

- [ ] **Step 5: Static checks + commit**

Run: `ruff check backend; ruff format --check backend; mypy backend/app`
Expected: all clean.

```bash
git add backend/app/services/__init__.py backend/app/services/stream/__init__.py
git add backend/app/services/stream/source.py backend/app/services/stream/file_source.py
git add backend/tests/test_source.py
git commit -m "feat(stream): add the FrameSource seam and FileSource"
```

Commit body (why): every later streaming component consumes `Frame`/`FrameSource`; the seam lets the whole pipeline run on clips in CI and on cameras in production without touching consumers.

---

## Task 1.2: `MotionGate` — the economics of cheap hardware

**Files:**
- Create: `backend/app/services/stream/motion.py`
- Create: `backend/tests/test_motion.py`

**Interfaces:**
- Consumes: `Frame` from Task 1.1; the `clips` fixture (`static`, `motion`, `brightness_shift`, `low_light`).
- Produces: `MotionGate` with `update(frame) -> bool` and `reset() -> None`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_motion.py`:

```python
"""Motion gate behaviour against the synthetic fixtures (spec §5.3).

The brightness-shift test is the one that matters: a camera switching to IR
at dusk changes every pixel at once. Without an explicit reset the
background model fires a burst of false alerts at the wrong hour.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.stream.motion import MotionGate
from app.services.stream.source import Frame

WARMUP = 30  # MOG2 needs a few frames to build a background model.


def _gate_on_clip(clip: Path) -> list[bool]:
    gate = MotionGate()
    decisions: list[bool] = []
    import av

    with av.open(str(clip)) as container:
        stream = container.streams.video[0]
        for raw in container.decode(stream):
            frame = Frame(
                data=raw.to_ndarray(format="rgb24").copy(),
                timestamp=0.0,
                width=raw.width,
                height=raw.height,
            )
            decisions.append(gate.update(frame))
    return decisions


def test_static_stays_closed(clips: dict[str, Path]) -> None:
    """A still scene must never open the gate — that would be a false alarm."""
    decisions = _gate_on_clip(clips["static"])
    assert not any(decisions[WARMUP:])


def test_motion_opens(clips: dict[str, Path]) -> None:
    """A translating object must open the gate on (nearly) every frame."""
    decisions = _gate_on_clip(clips["motion"])
    assert sum(decisions[WARMUP:]) / len(decisions[WARMUP:]) > 0.9


def test_brightness_shift_resets_instead_of_bursting(
    clips: dict[str, Path],
) -> None:
    """A day/night cut must reset the model, not fire a burst."""
    decisions = _gate_on_clip(clips["brightness_shift"])
    # A burst would be ~150 consecutive opens at the cut. A reset is < 5.
    assert sum(decisions) < 5
    assert not decisions[-50:]  # steady-state after the shift stays closed


def test_reset_clears_the_model(clips: dict[str, Path]) -> None:
    """reset() must make the very next frame *not* count as motion."""
    gate = MotionGate()
    import av

    with av.open(str(clips["static"])) as container:
        stream = container.streams.video[0]
        frames = [f for _, f in zip(range(60), container.decode(stream))]
        for raw in frames[:30]:
            gate.update(_to_frame(raw))
        gate.reset()
        next_decision = gate.update(_to_frame(frames[30]))
        assert next_decision is False


def test_low_light_gate_runs(clips: dict[str, Path]) -> None:
    """The night path must produce decisions without raising (Phase 3 uses it)."""
    decisions = _gate_on_clip(clips["low_light"])
    assert all(isinstance(d, bool) for d in decisions)
```

`_to_frame` helper (add to the test module):

```python
def _to_frame(raw) -> Frame:  # type: ignore[no-untyped-def]
    return Frame(
        data=raw.to_ndarray(format="rgb24").copy(),
        timestamp=0.0,
        width=raw.width,
        height=raw.height,
    )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest backend/tests/test_motion.py -v`
Expected: `ModuleNotFoundError: No module named 'app.services.stream.motion'`.

- [ ] **Step 3: Write the implementation**

`backend/app/services/stream/motion.py`:

```python
"""Cheap gate: is this frame worth inference? (spec §5.3)

MOG2 background subtraction on a 640x360 greyscale downscale costs a few
milliseconds against the detector's tens. That ratio is the entire reason
eight cameras fit on a 6-watt N100 (architecture §3).

Also owns the brightness-shift failure. A camera switching to IR at dusk
changes every pixel at once; without an explicit reset the background model
treats the transition as motion and fires a burst of false alerts at exactly
the hour the customer most needs to trust the product.
"""

from __future__ import annotations

import cv2
import numpy as np

from app.services.stream.source import Frame


class MotionGate:
    """Decide whether a frame warrants running the detector.

    The gate breaks scenes into a cheap per-frame pipeline: downscale to a
    work size, grey, MOG2-diff, count. When the global brightness level
    jumps by ``reset_delta`` or more (an IR cut), the background model is
    reset so the shift itself is not reported as motion.
    """

    def __init__(
        self,
        *,
        width: int = 640,
        height: int = 360,
        min_area: int = 500,
        reset_delta: float = 40.0,
    ) -> None:
        self._width = width
        self._height = height
        self._min_area = min_area
        self._reset_delta = reset_delta
        self._mog = cv2.createBackgroundSubtractorMOG2(
            history=200, varThreshold=16, detectShadows=False
        )
        self._mean: float = -1.0  # -1 = unprimed.

    def update(self, frame: Frame) -> bool:
        """Return True when the frame warrants inference.

        Args:
            frame: A frame, any resolution. Downscaled internally.

        Returns:
            True when the foreground change exceeds ``min_area`` pixels.
        """
        small = cv2.resize(
            frame.data, (self._width, self._height), interpolation=cv2.INTER_AREA
        )
        grey = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY)
        mean_value = float(grey.mean())
        if self._mean >= 0.0 and abs(mean_value - self._mean) > self._reset_delta:
            self.reset()
            self._mean = mean_value
            return False
        self._mean = mean_value
        foreground = self._mog.apply(grey)
        return int(np.count_nonzero(foreground)) >= self._min_area

    def reset(self) -> None:
        """Clear the background model (e.g. after an IR/brightness shift)."""
        self._mog.reset()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest backend/tests/test_motion.py -v`
Expected: 5 pass. If `test_brightness_shift_resets_instead_of_bursting` opens a handful of times, verify the count is small (< 5) and steady-state is closed; a *burst* (~150 opens) means the reset path is not running.

- [ ] **Step 5: Static checks + commit**

Run: `ruff check backend; ruff format --check backend; mypy backend/app`
Expected: clean.

```bash
git add backend/app/services/stream/motion.py backend/tests/test_motion.py
git commit -m "feat(stream): add the motion gate with brightness-shift reset"
```

Commit body: the MOG2 gate on a 640x360 grey downscale is what lets 8 cameras fit on cheap hardware; the global-brightness check prevents a dusk IR cut from firing a false-alert burst.

---

## Task 1.3: `LatestFrameSlot` — drop, never block

**Files:**
- Create: `backend/app/services/stream/slot.py`
- Create: `backend/tests/test_slot.py`

**Interfaces:**
- Consumes: `Frame` from Task 1.1.
- Produces: `LatestFrameSlot` with `async put(frame)`, `async get(timeout=None) -> Frame | None`, `close()`, `dropped -> int`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_slot.py`:

```python
"""Backpressure semantics (spec §4.4): full means replace, never block."""

from __future__ import annotations

import asyncio

import numpy as np

from app.services.stream.slot import LatestFrameSlot
from app.services.stream.source import Frame


def _frame(seed: int = 0) -> Frame:
    return Frame(
        data=np.full((360, 640, 3), seed, dtype=np.uint8),
        timestamp=float(seed),
        width=640,
        height=360,
    )


async def test_newest_replaces_oldest() -> None:
    slot = LatestFrameSlot()
    await slot.put(_frame(1))
    await slot.put(_frame(2))
    got = await slot.get()
    assert got is not None and got.data[0, 0, 0] == 2


async def test_put_never_blocks_when_full() -> None:
    slot = LatestFrameSlot()
    await slot.put(_frame(1))
    # The queue is full; put() must return immediately, not block or raise.
    await asyncio.wait_for(slot.put(_frame(2)), timeout=0.05)


async def test_dropped_counts_overwrites() -> None:
    slot = LatestFrameSlot()
    for seed in range(5):
        await slot.put(_frame(seed))
    # First put filled the empty slot; four newer frames replaced older ones.
    assert slot.dropped == 4


async def test_get_timeout_returns_none() -> None:
    slot = LatestFrameSlot()
    assert await slot.get(timeout=0.05) is None


async def test_close_unblocks_waiter() -> None:
    slot = LatestFrameSlot()
    waiter = asyncio.create_task(slot.get())
    await asyncio.sleep(0.01)
    slot.close()
    result = await asyncio.wait_for(waiter, timeout=1.0)
    assert result is None


async def test_put_after_close_is_a_noop() -> None:
    slot = LatestFrameSlot()
    slot.close()
    await asyncio.wait_for(slot.put(_frame(1)), timeout=0.05)
    assert await slot.get(timeout=0.01) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest backend/tests/test_slot.py -v`
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Write the implementation**

`backend/app/services/stream/slot.py`:

```python
"""Backpressure: drop, never block, never accumulate (spec §4.4).

The single most important streaming rule. Between the source and every
consumer sits a latest-frame slot; a full queue means replace the oldest
frame. If inference falls behind reality, stale frames are dropped — never
queued — so a backlog cannot consume RAM or add latency to alerts.
"""

from __future__ import annotations

import asyncio

from app.services.stream.source import Frame


class LatestFrameSlot:
    """Single-slot mailbox where a new frame replaces an old one.

    Backs onto ``asyncio.Queue(maxsize=1)`` but drops the older frame instead
    of blocking, so a slow consumer never back-pressures the source. The
    ``dropped`` counter is observability, not decoration: it is how a field
    report of "the image froze" is diagnosed without attaching a debugger.
    """

    def __init__(self) -> None:
        self._queue: asyncio.Queue[Frame | None] = asyncio.Queue(maxsize=1)
        self._dropped = 0
        self._closed = False

    async def put(self, frame: Frame) -> None:
        """Store the newest frame, replacing any older one held."""
        if self._closed:
            return
        if self._queue.full():
            self._queue.get_nowait()
            self._dropped += 1
        await self._queue.put(frame)

    async def get(self, timeout: float | None = None) -> Frame | None:
        """Return the newest frame, or None on timeout or after close()."""
        try:
            item = await asyncio.wait_for(self._queue.get(), timeout)
        except asyncio.TimeoutError:
            return None
        return None if item is None else item

    def close(self) -> None:
        """Unblock any waiter: a None sentinel lets it return frame-less."""
        self._closed = True
        if not self._queue.full():
            self._queue.put_nowait(None)

    @property
    def dropped(self) -> int:
        """How many frames were overwritten because a consumer was slow."""
        return self._dropped
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest backend/tests/test_slot.py -v`
Expected: 6 pass.

- [ ] **Step 5: Static checks + commit**

Run: `ruff check backend; ruff format --check backend; mypy backend/app`
Expected: clean.

```bash
git add backend/app/services/stream/slot.py backend/tests/test_slot.py
git commit -m "feat(stream): add the latest-frame slot backpressure"
```

Commit body: a full queue replaces the oldest frame and never blocks; the `dropped` counter makes "image froze" diagnosable from a field box. Phase 2's `ws/frames` stream is this slot's first real consumer.

---

## Task 1.4: `RtspSource` — transport, stall watchdog, jittered backoff

**Files:**
- Create: `backend/app/services/stream/rtsp_source.py`
- Create: `backend/tests/rtsp/test_rtsp_source.py`

**Interfaces:**
- Consumes: `Frame`, `FrameSource`; `StreamError`, `safe_error` from `app.core.errors`; `mask_url` from `app.core.logging`; the `mediamtx_url` fixture (Phase 0 harness).
- Produces:
  - `next_backoff(attempt, *, base=1.0, cap=60.0) -> float`
  - `classify_rtsp_error(exc) -> str` (spec §7.2 codes)
  - `async def probe_rtsp(url, *, timeout_s=5.0) -> None` (the non-retrying probe Phase 2's camera-test endpoint will use)
  - `RtspSource(url, *, stall_timeout_s=3.0)` with `frames()`, `close()`, `last_error`

- [ ] **Step 1: Write the failing tests**

`backend/tests/rtsp/test_rtsp_source.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest -m rtsp backend/tests/rtsp/test_rtsp_source.py -v`
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Write the implementation**

`backend/app/services/stream/rtsp_source.py`:

```python
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
    if not isinstance(exc, (av.error.FFmpegError, OSError, ConnectionError, TimeoutError)):
        return "DECODE_FAILED"
    text = str(exc).lower()
    if any(token in text for token in ("404", "not found", "no such", "invalid data")):
        return "NO_SUCH_STREAM"
    if "connection refused" in text or isinstance(exc, ConnectionRefusedError):
        return "HOST_UNREACHABLE"
    if any(token in text for token in ("401", "403", "unauthor", "wrong password", "auth")):
        return "AUTH_FAILED"
    if any(token in text for token in ("timed out", "timeout")) or isinstance(
        exc, TimeoutError
    ):
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
        with av.open(
            url, options={"rtsp_transport": "tcp", "timeout": timeout_us}
        ) as container:
            next(container.decode(container.streams.video[0]))

    try:
        await asyncio.wait_for(asyncio.to_thread(_probe), timeout=timeout_s + 2.0)
    except asyncio.TimeoutError as exc:
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
                while not self._closed:
                    raw = next(container.decode(stream))
                    data = raw.to_ndarray(format="rgb24").copy()
                    yield Frame(
                        data=data,
                        timestamp=time.monotonic(),
                        width=raw.width,
                        height=raw.height,
                    )
                return
            except (av.error.FFmpegError, OSError, ConnectionError, TimeoutError) as exc:
                if not self._closed:
                    self._note_failure(exc)
            finally:
                if container is not None:
                    container.close()
            if self._closed:
                return
            await asyncio.sleep(next_backoff(self._attempt))
            self._attempt += 1

    async def close(self) -> None:
        """Idempotent. The iterator terminates at its next checked boundary."""
        self._closed = True

    def _note_failure(self, exc: Exception) -> None:
        reason = classify_rtsp_error(exc)
        safe = mask_url(self._url)
        self._last_error = StreamError(safe_error(f"{reason}: {safe} ({safe_error(str(exc))})"))
        _log.warning(
            "rtsp_source.reconnect",
            reason=reason,
            attempt=self._attempt,
            camera_url=safe,
            error=str(exc),
        )

    @property
    def last_error(self) -> StreamError | None:
        """The most recent transport failure, for status surfaces."""
        return self._last_error
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest -m rtsp backend/tests/rtsp/test_rtsp_source.py -v`
Expected: 2 pass (MediaMTX running natively from Phase 0). Verify the bad-path test raises within ~5s (it must not hang — that is the classified failure).

- [ ] **Step 5: Static checks + commit**

Run: `ruff check backend; ruff format --check backend; mypy backend/app`
Expected: clean.

```bash
git add backend/app/services/stream/rtsp_source.py backend/tests/rtsp/test_rtsp_source.py
git commit -m "feat(stream): add RtspSource with stall watchdog and backoff"
```

Commit body: reconnection owns the transport so pipelines never see it; the watchdog is a socket timeout because a TCP connection survives a dead stream. `probe_rtsp` is the non-retrying surface Phase 2's camera-test endpoint returns from.

---

## Task 1.5: `CameraPipeline` — motion-gated, sampled consumption

**Files:**
- Create: `backend/app/services/stream/pipeline.py`
- Create: `backend/tests/test_pipeline.py`
- Modify: `backend/tests/test_source.py` (append the 1080p test)

**Interfaces:**
- Consumes: `Frame`, `FrameSource`; `MotionGate`; `ValidationError`, `CamBrainError` from `app.core.errors`.
- Produces:
  - `CameraConfig(camera_id, name, url, sample_fps=2.0)` — frozen; validates 2.0–5.0.
  - `CameraPipeline(config, source, sink, *, motion=None)` → `run()`, `config`, `snapshot()`.
  - `PipelineStatus` (state, frames_received, frames_consumed, last_frame_at, error).
  - `FrameSink = Callable[[Frame], Awaitable[None]]` — the injected consumer (Phase 3's detector slot).

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_pipeline.py`:

```python
"""CameraPipeline: gating, sampling, concurrency, ownership (spec §5, §12)."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import numpy as np
import psutil
import pytest

from app.core.errors import ValidationError
from app.services.stream.file_source import FileSource
from app.services.stream.pipeline import CameraConfig, CameraPipeline
from app.services.stream.source import Frame


async def _run_for(pipeline: CameraPipeline, seconds: float) -> None:
    task = asyncio.create_task(pipeline.run())
    try:
        await asyncio.sleep(seconds)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_sample_fps_is_honoured(clip_path: Path) -> None:
    """With the gate open (motion clip), emissions follow sample_fps (≤5Hz)."""
    consumed: list[Frame] = []

    async def sink(frame: Frame) -> None:
        consumed.append(frame)

    pipeline = CameraPipeline(
        CameraConfig("cam", "Cam", str(clip_path), sample_fps=5.0),
        FileSource(clip_path),
        sink,
    )
    await _run_for(pipeline, 3.0)

    # 3 s at 5 fps = 15 max; the gate drops a few frames during warmup.
    assert 8 <= len(consumed) <= 19


def test_sample_fps_out_of_range_is_rejected() -> None:
    """Sample rate is 2–5 FPS (spec §1.5); config refuses anything else."""
    with pytest.raises(ValidationError):
        CameraConfig("cam", "Cam", "file://x", sample_fps=1.0)
    with pytest.raises(ValidationError):
        CameraConfig("cam", "Cam", "file://x", sample_fps=7.0)
    assert CameraConfig("cam", "Cam", "file://x", sample_fps=5.0)


async def test_eight_pipelines_concurrently(clip_path: Path) -> None:
    """Eight cameras, each with its own pipeline, all live at once."""
    consumed: dict[str, list[Frame]] = {}

    def make_sink(camera_id: str) -> FrameSink:
        async def sink(frame: Frame) -> None:
            consumed.setdefault(camera_id, []).append(frame)

        return sink

    pipelines = [
        CameraPipeline(
            CameraConfig(f"cam{i}", f"Cam {i}", str(clip_path), sample_fps=5.0),
            FileSource(clip_path),
            make_sink(f"cam{i}"),
        )
        for i in range(8)
    ]
    tasks = [asyncio.create_task(p.run()) for p in pipelines]
    try:
        await asyncio.sleep(2.5)
        for i in range(8):
            assert consumed[f"cam{i}"], f"camera cam{i} consumed nothing"
            assert pipelines[i].snapshot().state == "live"
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.slow
async def test_idle_cpu_under_5_percent() -> None:
    """No motion → no consumer work, and the process idles (spec §1.5)."""

    class PacedSource:
        """Feeds one static frame at a camera's real rate (paced, no decode)."""

        def __init__(self, fps: float) -> None:
            self._interval = 1.0 / fps
            self._closed = False

        async def frames(self) -> AsyncIterator[Frame]:
            while not self._closed:
                yield Frame(
                    data=np.full((360, 640, 3), 30, dtype=np.uint8),
                    timestamp=time.monotonic(),
                    width=640,
                    height=360,
                )
                await asyncio.sleep(self._interval)

        async def close(self) -> None:
            self._closed = True

    consumed: list[Frame] = []

    async def sink(frame: Frame) -> None:
        consumed.append(frame)

    pipeline = CameraPipeline(
        CameraConfig("cam", "Cam", "paced://static", sample_fps=2.0),
        PacedSource(fps=15.0),
        sink,
    )
    proc = psutil.Process()
    proc.cpu_percent()  # prime the interval sample
    await _run_for(pipeline, 3.0)
    cpu = proc.cpu_percent()  # % of one core over the last 3 s

    assert consumed == []  # the gate economics: closed gate does zero work
    assert cpu < 5.0


async def test_pipeline_closes_source_on_cancel(clip_path: Path) -> None:
    """Cancellation must close the source in finally (spec §4.5, §5.1)."""

    class TrackingSource(FileSource):
        def __init__(self, path: Path) -> None:
            super().__init__(path)
            self.closed = False

        async def close(self) -> None:
            super().close()
            self.closed = True

    async def sink(frame: Frame) -> None:
        return None

    source = TrackingSource(clip_path)
    pipeline = CameraPipeline(
        CameraConfig("cam", "Cam", str(clip_path), sample_fps=2.0),
        source,
        sink,
    )
    await _run_for(pipeline, 0.5)
    assert source.closed


async def test_1080p_input_downscaled() -> None:
    """A 1080p input works end to end: the gate downscales internally, the
    consumer still receives the frame at its native size (spec §12)."""
    consumed: list[Frame] = []

    async def sink(frame: Frame) -> None:
        consumed.append(frame)

    class LoopSource:
        async def frames(self) -> AsyncIterator[Frame]:
            i = 0
            while True:
                arr = np.full((1080, 1920, 3), 20, dtype=np.uint8)
                x = (i * 90) % 1500
                arr[200:800, x : x + 120] = 240  # a moving bright block
                yield Frame(
                    data=arr,
                    timestamp=time.monotonic(),
                    width=1920,
                    height=1080,
                )
                i += 1

        async def close(self) -> None:
            return None

    pipeline = CameraPipeline(
        CameraConfig("cam", "Cam", "loop://1080p", sample_fps=5.0),
        LoopSource(),
        sink,
    )
    await _run_for(pipeline, 1.0)

    assert consumed, "1080p motion was not detected through the gate"
    assert consumed[0].width == 1920
    assert consumed[0].height == 1080
    assert consumed[0].data.shape == (1080, 1920, 3)
```

Append to `backend/tests/test_source.py` the imports and the punchline so the matrix-named test lives there:

```python
from app.services.stream.motion import MotionGate  # noqa: F401  (used below)
```

(No separate assertion needed beyond the pipeline 1080p test above — the matrix row is satisfied by `test_source.py::test_1080p_input_downscaled`, which this task appends to `test_source.py`.)

Append this to `backend/tests/test_source.py`:

```python
async def test_1080p_input_downscaled(clip_path: Path) -> None:
    """A 1080p input works end to end (verification matrix §12 row)."""
    import asyncio
    import time

    import numpy as np

    from app.services.stream.motion import MotionGate
    from app.services.stream.pipeline import CameraConfig, CameraPipeline
    from app.services.stream.source import Frame

    received: list[Frame] = []

    async def sink(frame: Frame) -> None:
        received.append(frame)

    class LoopSource:
        async def frames(self) -> AsyncIterator[Frame]:
            i = 0
            while True:
                arr = np.full((1080, 1920, 3), 20, dtype=np.uint8)
                x = (i * 90) % 1500
                arr[200:800, x : x + 120] = 240
                yield Frame(arr, time.monotonic(), 1920, 1080)
                i += 1

        async def close(self) -> None:
            return None

    pipeline = CameraPipeline(
        CameraConfig("cam", "Cam", "loop://1080p", sample_fps=5.0),
        LoopSource(),
        sink,
    )
    task = asyncio.create_task(pipeline.run())
    try:
        await asyncio.sleep(1.0)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    assert received
    assert received[0].width == 1920
    assert received[0].height == 1080
    assert received[0].data.shape == (1080, 1920, 3)
```

(`AsyncIterator` is already imported in `test_source.py`; the 1080p test in `test_pipeline.py` above is then redundant — keep only the `test_source.py` copy to avoid duplication and keep the matrix name exact.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest backend/tests/test_pipeline.py -v`
Expected: `ModuleNotFoundError: No module named 'app.services.stream.pipeline'`.

- [ ] **Step 3: Write the implementation**

`backend/app/services/stream/pipeline.py`:

```python
"""One camera, owned end to end: source -> motion gate -> sampled sink.

Spec §4. Should hold no shared mutable state: collaborators are injected
and outward communication is an injected sink. This is the seam that lets
Phase 3 attach detection and lets a future process-per-camera move touch
one factory function (architecture §4).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace

from app.core.errors import CamBrainError, ValidationError
from app.services.stream.motion import MotionGate
from app.services.stream.source import Frame, FrameSource

FrameSink = Callable[[Frame], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class CameraConfig:
    """Per-camera configuration (spec §1.5: sample rate 2–5 FPS)."""

    camera_id: str
    name: str
    url: str
    sample_fps: float = 2.0

    def __post_init__(self) -> None:
        if not 2.0 <= self.sample_fps <= 5.0:
            raise ValidationError(
                f"sample_fps must be between 2 and 5, got {self.sample_fps}"
            )


@dataclass
class PipelineStatus:
    """Observability snapshot for one pipeline."""

    state: str = "starting"
    frames_received: int = 0
    frames_consumed: int = 0
    last_frame_at: float | None = None
    error: str | None = None


class CameraPipeline:
    """Feed a source through the motion gate to a sampled sink.

    Args:
        config: Per-camera settings, including the sample rate.
        source: Any ``FrameSource`` (clip, RTSP, or a double in tests).
        sink: Receives frames that pass the gate at the sample rate.
        motion: The gate; a default MOG2 gate is used when omitted.
    """

    def __init__(
        self,
        config: CameraConfig,
        source: FrameSource,
        sink: FrameSink,
        *,
        motion: MotionGate | None = None,
    ) -> None:
        self._config = config
        self._source = source
        self._sink = sink
        self._motion = motion or MotionGate()
        self._min_interval = 1.0 / config.sample_fps
        self._last_send_at: float = 0.0
        self._status = PipelineStatus()

    @property
    def config(self) -> CameraConfig:
        return self._config

    def snapshot(self) -> PipelineStatus:
        """Return a consistent copy, safe to read from another thread."""
        return replace(self._status)

    async def run(self) -> None:
        """Run until cancelled. Closes the source on every exit path."""
        self._status.state = "live"
        try:
            async for frame in self._source.frames():
                self._status.frames_received += 1
                self._status.last_frame_at = time.monotonic()
                if not self._motion.update(frame):
                    continue
                now = time.monotonic()
                if now - self._last_send_at < self._min_interval:
                    continue
                self._last_send_at = now
                self._status.frames_consumed += 1
                await self._sink(frame)
        except asyncio.CancelledError:
            raise
        except CamBrainError as exc:
            self._status.error = str(exc)
            raise
        finally:
            await self._source.close()
            self._status.state = "stopped"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest backend/tests/test_pipeline.py backend/tests/test_source.py -v`
Expected: all pass. If `test_sample_fps_is_honoured` counts outside 8–19, the math hints at a gating bug, not a timing flake — investigate.

- [ ] **Step 5: Static checks + commit**

Run: `ruff check backend; ruff format --check backend; mypy backend/app`
Expected: clean.

```bash
git add backend/app/services/stream/pipeline.py
git add backend/tests/test_pipeline.py backend/tests/test_source.py
git commit -m "feat(stream): add CameraPipeline with gating and sampling"
```

Commit body: the pipeline owns nothing shared; motion gating plus configured sampling is what bounds CPU and gives Phase 3 a clean attachment point for the detector.

---

## Task 1.6: `StreamManager` — the lifecycle owner + the two canaries

**Files:**
- Create: `backend/app/services/stream/stream_manager.py`
- Create: `backend/tests/test_stream_manager.py`
- Modify: `backend/tests/rtsp/conftest.py` (pausable publisher)
- Modify: `backend/tests/conftest.py` (re-export the live-RTSP fixtures)

**Interfaces:**
- Consumes: `CameraConfig`, `CameraPipeline`, `PipelineStatus`; `FrameSource`; `Frame`, `FrameSink`; `RtspSource`, `next_backoff`; the `mediamtx_url` fixture (via re-export).
- Produces:
  - `SourceFactory = Callable[[CameraConfig], FrameSource]`
  - `StreamManager(source_factory, sink)` → `add_camera(config)`, `remove_camera(camera_id) -> bool`, `status_all() -> dict[str, PipelineStatus]`, `stop()`.
  - New rtsp/conftest fixture `mediamtx_pause` → `(url, pause: Callable[[float], Awaitable[None]])`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_stream_manager.py`:

```python
"""StreamManager lifecycle + the reconnect canaries (spec §1.5, §12)."""

from __future__ import annotations

import asyncio
import gc
import random
import statistics
import threading
import time
from pathlib import Path

import psutil
import pytest

from app.services.stream.file_source import FileSource
from app.services.stream.pipeline import CameraConfig, CameraPipeline, FrameSink
from app.services.stream.rtsp_source import RtspSource, next_backoff
from app.services.stream.source import Frame, FrameSource
from app.services.stream.stream_manager import StreamManager


def test_backoff_reaches_cap() -> None:
    """Jittered exponential backoff caps at 60s (spec §1.5)."""
    random.seed(3)
    assert all(delay >= 0.0 for delay in (next_backoff(a) for a in range(20)))
    assert all(delay < 60.0 for delay in (next_backoff(a) for a in range(20)))
    samples = [next_backoff(10, cap=60.0) for _ in range(300)]
    assert max(samples) > 58.0  # the cap domain is actually reached
    assert all(0.0 <= delay < 1.0 for delay in [next_backoff(0) for _ in range(20)])
    assert next_backoff(30, base=1.0, cap=60.0) < 60.0


def test_backoff_has_jitter() -> None:
    """No thundering herd (spec §4.6): retries are random, not lockstep."""
    random.seed(11)
    first = [next_backoff(3) for _ in range(50)]
    random.seed(11)
    second = [next_backoff(3) for _ in range(50)]
    assert first == second  # deterministic under a seed — reproducible failures
    distinct = {round(d, 3) for d in first}
    assert len(distinct) > 10  # spans a range, not lockstep
    assert min(first) < 1.0 and max(first) < 8.0  # within [0, 2**attempt)


def test_add_remove_status_all(clip_path: Path) -> None:
    """Manager owns a pipeline's lifecycle from one injected factory."""
    first_frame = threading.Event()

    def make_source(config: CameraConfig) -> FrameSource:
        return FileSource(clip_path, loop=True)

    async def sink(frame: Frame) -> None:
        first_frame.set()

    manager = StreamManager(make_source, sink)
    cfg = CameraConfig("office", "Office", "file://motion.mp4", sample_fps=5.0)
    manager.add_camera(cfg)

    deadline = time.monotonic() + 5.0
    while not first_frame.is_set() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert first_frame.is_set()

    statuses = manager.status_all()
    assert set(statuses) == {"office"}
    assert statuses["office"].frames_consumed >= 1

    assert manager.remove_camera("office") is True
    assert manager.remove_camera("office") is False  # idempotent-ish contract
    assert manager.status_all() == {}


async def test_transient_drop_recovers_fast(mediamtx_pause) -> None:
    """Transient RTSP drop recovers within 5s (spec §1.5, §12)."""
    url, pause = mediamtx_pause
    received: list[float] = []
    src = RtspSource(url)
    frames = src.frames()
    try:
        first = await asyncio.wait_for(anext(frames), timeout=10.0)
        received.append(first.timestamp)
        await pause(2.0)  # publisher silent for 2 s
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            frame = await asyncio.wait_for(anext(frames), timeout=5.0)
            received.append(frame.timestamp)
            gap = received[-1] - received[-2]
            if gap >= 1.0:  # the drop really happened, and frames flow again
                return
        pytest.fail("RtspSource did not resume within 5s of a transient drop")
    finally:
        await frames.aclose()
        await src.close()


@pytest.mark.rtsp
@pytest.mark.slow
async def test_memory_is_flat_across_reconnects(mediamtx_url: str) -> None:
    """50 reconnect cycles; resident memory must plateau, not climb (spec §11.4).

    A ceiling assertion passes on a slow leak; a trend assertion catches it.
    """
    proc = psutil.Process()
    samples: list[tuple[int, int]] = []
    for cycle in range(50):
        src = RtspSource(mediamtx_url)
        frames = src.frames()
        try:
            frame = await asyncio.wait_for(anext(frames), timeout=10.0)
            assert frame.width == 640
        finally:
            await frames.aclose()
            await src.close()
        gc.collect()
        samples.append((cycle, proc.memory_info().rss))

    early = [rss for _, rss in samples[:10]]
    late = [rss for _, rss in samples[-10:]]
    growth = (statistics.fmean(late) - statistics.fmean(early)) / statistics.fmean(early)
    assert growth < 0.10, f"RSS grew {growth * 100:.1f}% over 50 reconnects"
```

(Place `test_transient_drop_recovers_fast` in the same file but also decorate it `@pytest.mark.rtsp` — it depends on MediaMTX.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest backend/tests/test_stream_manager.py -v`
Expected: 3 module failures (`ModuleNotFoundError: app.services.stream.stream_manager`; the two rtsp-marked tests also need the fixture re-export).

- [ ] **Step 3: Write the implementation**

`backend/app/services/stream/stream_manager.py`:

```python
"""Own the pipeline lifecycle.

One thread per camera, each running its own asyncio loop (spec §4.3:
threads, not processes). The source factory is injected so the manager is
testable offline with ``FileSource`` and exercises the real RTSP path with
``RtspSource``.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable, Callable
from typing import Any

from app.services.stream.pipeline import CameraConfig, CameraPipeline, PipelineStatus
from app.services.stream.source import Frame, FrameSource

SourceFactory = Callable[[CameraConfig], FrameSource]
FrameSink = Callable[[Frame], Awaitable[None]]


class _CameraWorker:
    """A dedicated thread running one camera's asyncio event loop."""

    def __init__(self, camera_id: str) -> None:
        self.camera_id = camera_id
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(
            target=self.loop.run_forever,
            name=f"camera-{camera_id}",
            daemon=True,
        )
        self.pipeline: CameraPipeline | None = None
        self.future: Any = None


class StreamManager:
    """Create, stop, and observe pipelines; owns their lifecycle (arch §2).

    Args:
        source_factory: Builds a ``FrameSource`` for a config. The injected
            seam that keeps the manager hardware-free.
        sink: What each pipeline hands motion frames to (later phases wire
            the detector slot here).
    """

    def __init__(self, source_factory: SourceFactory, sink: FrameSink) -> None:
        self._factory = source_factory
        self._sink = sink
        self._workers: dict[str, _CameraWorker] = {}
        self._lock = threading.Lock()

    def add_camera(self, config: CameraConfig) -> None:
        """Start a pipeline for ``config`` on a fresh thread+loop."""
        with self._lock:
            if config.camera_id in self._workers:
                raise ValueError(f"camera {config.camera_id} is already running")
            worker = _CameraWorker(config.camera_id)
            source = self._factory(config)
            worker.pipeline = CameraPipeline(config, source, self._sink)
            worker.thread.start()
            worker.future = asyncio.run_coroutine_threadsafe(
                worker.pipeline.run(), worker.loop
            )
            worker.future.add_done_callback(
                lambda fut: self._on_done(config.camera_id, worker.camera_id, fut)
            )
            self._workers[config.camera_id] = worker

    def remove_camera(self, camera_id: str) -> bool:
        """Stop a camera's pipeline and join its thread. Unknown id → False."""
        with self._lock:
            worker = self._workers.get(camera_id)
            if worker is None:
                return False
            del self._workers[camera_id]
        self._stop_worker(worker)
        return True

    def status_all(self) -> dict[str, PipelineStatus]:
        """Snapshot every running pipeline. Safe to call from any thread."""
        with self._lock:
            workers = list(self._workers.values())
        return {
            w.camera_id: w.pipeline.snapshot()
            for w in workers
            if w.pipeline is not None
        }

    def stop(self) -> None:
        """Stop every camera."""
        for camera_id in list(self.status_all()):
            self.remove_camera(camera_id)

    def _stop_worker(self, worker: _CameraWorker) -> None:
        if worker.future is not None:
            worker.future.cancel()
        # Give the loop 50 ms to deliver the cancellation (so the pipeline's
        # finally closes the source), then stop the run_forever thread.
        worker.loop.call_soon_threadsafe(
            lambda: worker.loop.call_later(0.05, worker.loop.stop)
        )
        worker.thread.join(timeout=5.0)

    def _on_done(self, camera_id: str, worker_camera_id: str, fut: Any) -> None:
        try:
            fut.exception()  # swallow CancelledError and failures; log held them
        except (asyncio.CancelledError, Exception):
            pass
        with self._lock:
            worker = self._workers.get(camera_id)
            if worker is not None and worker.camera_id == worker_camera_id:
                del self._workers[camera_id]
```

`backend/tests/rtsp/conftest.py` — add a module-level pause gate and the new fixture. Insert after `STREAM_NAME`/`RTSP_URL` definitions:

```python
_PUBLISH_PAUSE = threading.Event()  # set while a test wants the stream silent
```

In `_publish_pass`, at the top of the per-frame loop, before the `if stop.is_set():` line:

```python
        for frame in source.decode(in_stream):
            while _PUBLISH_PAUSE.is_set():
                time.sleep(0.1)
            if stop.is_set():
                return
```

Append the fixture (and extend the imports with `asyncio`, `Awaitable`, `Callable`):

```python
@pytest.fixture
def mediamtx_pause(
    mediamtx_url: str,
) -> Iterator[tuple[str, Callable[[float], Awaitable[None]]]]:
    """Stall the publisher for a controlled window, then resume.

    RtspSource must recover from a transient drop within 5s (spec §1.5).
    """

    async def pause(seconds: float) -> None:
        _PUBLISH_PAUSE.set()
        try:
            await asyncio.sleep(seconds)
        finally:
            _PUBLISH_PAUSE.clear()

    try:
        yield mediamtx_url, pause
    finally:
        _PUBLISH_PAUSE.clear()
```

`backend/tests/conftest.py` — re-export the live-RTSP fixtures so the matrix-named canaries live in a root test file while MediaMTX logic stays owned by the rtsp package:

```python
# Re-exported so the live-RTSP canaries (spec §12) can live in
# test_stream_manager.py; the fixtures themselves stay owned by the rtsp
# package, and skip with a visible message when no MediaMTX binary exists.
from tests.rtsp.conftest import mediamtx_pause, mediamtx_url  # noqa: F401
```

- [ ] **Step 4: Run the tests to verify they pass**

Run (offline): `pytest backend/tests/test_stream_manager.py -v`
Expected: `test_backoff_reaches_cap`, `test_backoff_has_jitter`, `test_add_remove_status_all` pass.

Run (live RTSP, MediaMTX on): `pytest -m rtsp backend/tests/test_stream_manager.py -v`
Expected: `test_transient_drop_recovers_fast` and `test_memory_is_flat_across_reconnects` pass. The memory test prints the run; watch for `RSS grew X%` — it must be < 10%.

Run (full local default): `pytest -m "not rtsp and not slow" -q`
Expected: 3 newly deselected (rtsp/slow markers working), nothing else broken.

- [ ] **Step 5: Static checks + commit**

Run: `ruff check backend; ruff format --check backend; mypy backend/app`
Expected: clean.

```bash
git add backend/app/services/stream/stream_manager.py
git add backend/tests/test_stream_manager.py
git add backend/tests/rtsp/conftest.py backend/tests/conftest.py
git commit -m "feat(stream): add StreamManager lifecycle owner and reconnect canaries"
```

Commit body: one thread+loop per camera from an injected source factory; the pausable publisher lets the transient-drop test prove ≤5s recovery deterministically, and the RSS trend canary makes a per-reconnect leak a CI failure instead of a field discovery.

---

## Task 1.7: Phase 1 gate — run every row, record the rulings

**Files:**
- Modify: `.superpowers/sdd/phase-0-bootstrap/progress.md` (append the Phase 1 section)

**Interfaces:**
- Consumes: everything from Tasks 1.1–1.6.

- [ ] **Step 1: Run the full gate**

```bash
ruff check backend
ruff format --check backend
mypy backend/app
pytest -m "not rtsp and not slow" -q          # default: no MediaMTX needed
pytest -m rtsp -v                             # with MediaMTX natively
pytest -m "rtsp and slow" -v                  # the memory canary alone, observed
pytest backend/tests/rtsp -rs                 # skip path: hide mediamtx.exe → visible skip
```

Expected: all green; the skip drill prints the visible reason; the memory canary passes with the observed RSS growth printed (< 10%).

- [ ] **Step 2: Confirm the hardware-free property**

Temporarily rename `backend/tests/rtsp/.tools/mediamtx.exe`, then run `pytest -m rtsp -q` — expect all four RTSP-marked tests to **skip with the visible message** (never silently pass). Restore the binary immediately.

- [ ] **Step 3: Record the phase in the ledger**

Append to `.superpowers/sdd/phase-0-bootstrap/progress.md` (same conventions as Phase 0):

```markdown
## Phase 1 - DONE (<branch>, <date>). Streaming engine.
- Tasks 1.1-1.6 all green; gate rows observed, including the RSS memory canary.
- No dependency changes (av 19.0.1, numpy 2.5.3, opencv-headless 5.0.0.93,
  psutil 7.2.2 already in requirements.lock.txt).
- Rulings to record:
  * RtspSource stalls via a socket timeout (PyAV `timeout`), not a timer;
    the watchdog and the reconnect loop are one mechanism.
  * Reconnection lives in the source, not the manager: the pipeline and
    manager never see transport.
  * `probe_rtsp` is the non-retrying diagnostic surface Phase 2's
    camera-test endpoint returns from.
  * The transient-drop test pauses the *publisher* (pausable conftest
    fixture), because MediaMTX itself cannot be restarted per-test cheaply.
  * `frame.data` is a `.copy()` at decode time: PyAV reuses decoder
    buffers, so a borrowed view would corrupt every held frame.
```

- [ ] **Step 4: Commit the phase (docs only, if any doc changed)**

```bash
git status            # expect: no weights, .env, clips, or DB staged
git commit -m "docs(phase): record Phase 1 gate results and rulings"
```

(If nothing besides the ledger changed, the ledger is machine-local and this commit is a no-op — skip it.)

---

## Self-review (run before declaring the plan done)

1. **Spec coverage (Phase 1 scope):** §4.3 (one thread per camera → Task 1.6), §4.4 (slot → Task 1.3), §4.5 (owned frames → Task 1.1) , §4.6 (backoff → Task 1.4), §5.1 (Frame/FrameSource → Task 1.1), §5.2 slot, §5.3 MotionGate → Task 1.2. Phase 1 has no tracker/rules/detector — those are Phase 3 (design §5.4–5.5) and correctly absent here. Testing rows §12 map to the verification table above.
2. **Placeholders:** every step carries real code or an exact command; no "implement later", no "add validation", no references to types that are not defined in this plan (every symbol is produced by an earlier task).
3. **Type consistency:** `Frame(data, timestamp, width, height)`, `FrameSource.frames()/close()`, `FrameSink`, `CameraConfig(camera_id, name, url, sample_fps)`, `next_backoff(attempt)`, `probe_rtsp(url)` — identical names/types across tasks. `movement_gate` vs the design's `update`/`reset` — only the design's names are used.

**Known deviations from the historical docs (not defects):**
- `2026-10-05-cambrain-mvp-design.md` **D18** and `docs/tasks.md` still say "MediaMTX in Docker" — that decision was superseded in Phase 0 by the native binary (ledger D17). The historical design doc is left untouched.
- The `pyproject.toml` rtsp marker description still says "Docker container" (cosmetic; flagged in Global Constraints).
- `test_pipeline.py::test_idle_cpu_under_5_percent` uses a paced static source rather than decoding an unbounded stream, so the CPU measurement reflects production idle (a gate that is *closed*) rather than decode-as-fast-as-possible (which would swamp the assertion with decode cost, not gate economics).

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/phase-1-streaming.md`.

Two execution options:

1. **Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks. *Note: SDD is suspended in this repo by human directive, so this option is on hold unless you lift it.*
2. **Inline Execution** — execute tasks in a session with `executing-plans`, batch execution with checkpoints after each task's review.

Which approach?