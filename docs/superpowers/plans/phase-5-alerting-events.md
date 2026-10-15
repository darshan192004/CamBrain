# Phase 5 — Alerting & Events Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Execution note (this project):** controller executes inline (no subagents — standing user directive), TDD failing-test-first, Conventional Commits, no `Co-Authored-By`.

**Goal:** Wire fired alerts end to end — persist events + detections, record a 10s pre-roll / 20s post-roll clip plus still, deliver via Telegram with durable retry, broadcast over `/ws/alerts`, enforce retention and the disk quota — proving the Phase 5 gate: *a Telegram photo arrives at 2am*.

**Architecture:** `AlertStage` now fires `Alert`s that carry `camera_id` + pixel `bbox` into a per-camera `AlertHandler` which persists the event, snaps the still from a JPEG pre-roll ring buffer, broadcasts over a tenant-scoped WS hub, and finishes the clip after the 20s post-roll. A `DeliveryWorker` discovers durable `pending` rows by DB poll (no in-memory queue — thread safety + durability) and sends through the `Notifier` protocol (Telegram first, WhatsApp stubbed). A lifespan-managed `Runtime` owns the `StreamManager` pipelines, the stream→DB bridge (frame dims + camera status), retention sweeps, and the quota latch. Everything before the notifier is local and durable; notifier failure loses nothing (spec §5.6).

**Tech Stack:** FastAPI/Starlette WebSocket, httpx (already in `requirements.txt`), PyAV + `libx264` + OpenCV for clip encoding, SQLAlchemy 2.0 + Alembic (forward-only), structlog; Vue 3 + Pinia + native WebSocket; Vitest + VTU.

**Spec:** `docs/superpowers/specs/spec.md` §4.8, §5.6–5.7, §6.3–6.6, §7.3–7.5, §8.2, §10.2, §11, §12, §13 · `docs/API.md` (Events, Notifiers, WS, Rate limits) · `docs/DATABASE.md` §4.7–4.9, §6–§10 · `docs/architecture.md` §7 (data flow for one alert).

## Global Constraints

- Pre-roll **10s**, post-roll **20s** (spec §5.7); retention default **7 days**, batched deletes **500 rows/txn** (§6.5); disk quota default **80%** — refuse clip writes past it and raise a critical system event (§5.7, DATABASE §9).
- Clip/still paths are **generated from `events.id`** (`clips/{id}.mp4`, `stills/{id}.jpg`), never user input; served only inside `settings.media_root` (SECURITY §6.2).
- `site_id` always from the auth token; cross-tenant → **404 never 403**; secrets never returned by GET (`has_token` mask, `mask_url` in errors); no secret ever logged (REDACT_KEYS processor is structural).
- `Notifier` protocol signature is normative: `async def send(self, event: Event) -> None` (spec §5.6).
- WS `/ws/alerts`: token via `Sec-WebSocket-Protocol` `cambrain.jwt.<token>` (or first message), server→client only, heartbeat **30s**, client reconnect jittered **1s→30s** + resync via `GET /events` (API.md §3).
- Rate limits (API.md §6): login lockout exists; `auth/refresh` **30/min**, `cameras/{id}/test` **10/min**, everything else **120/min**, stream slot cap **12/IP** (D1) — all per client IP, `429 RATE_LIMITED` + `Retry-After`.
- Every DB column storing time is **naive UTC** (`_utcnow()` pattern); alembic **forward-only**, never edit a shipped migration.
- Google-style docstrings, module docstring on every file; SQLAlchemy 2.0 style (no `Query`); no inline comments unless non-obvious (CODE_STYLE §8).
- Injectable `now`/`sleep`/`session_factory`/transports in every service class — no clock, network, or real DB in unit tests.
- Backend loop (every shell call): `$env:PATH = "E:\CamBrain\.venv\Scripts;" + $env:PATH` then `python -m pytest -m "not rtsp and not slow"` (baseline **276 passed / 1 skipped / 5 deselected**; `slow` 4, `rtsp` 7) then `python -m ruff check backend` + `python -m mypy backend` — **never pytest and mypy in parallel**.
- Frontend loop (under `frontend/`): `npm run format; if ($?) { npm run lint }; if ($?) { npm run format:check }; if ($?) { npm test }; if ($?) { npm run build }` (baseline **164 tests**).
- Commits: Conventional Commits, message via BOM-free `.tmp/commit_msg.txt` + `git commit -F .tmp\commit_msg.txt`; never stage `.tmp/`, `.playwright-mcp/`, weights, db, clips; no `Co-Authored-By`.
- Frontend: no hardcoded hex (tokens.spec), kebab-case testids, `aria-live` for async results, Tailwind v4 CSS-first, no `src/ui/`.
- Branch: `phase-5-alerting` off `main` (`84b9467`).

## File structure

| Op | File | Responsibility |
|---|---|---|
| CREATE | `backend/app/services/events/clips.py` | `FrameRingBuffer` (JPEG pre/post-roll window) + `ClipWriter` (still, mp4, quota refusal) |
| CREATE | `backend/app/services/events/persist.py` | `create_event` / `attach_media` / `mark_delivery` / `create_system_event` |
| CREATE | `backend/app/services/events/handler.py` | `AlertHandler` — the per-camera `AlertSink` orchestrator |
| CREATE | `backend/app/services/events/retention.py` | batched retention + orphan sweep loops |
| CREATE | `backend/app/services/alerts/notifier.py` | `Notifier` protocol (spec §5.6) |
| CREATE | `backend/app/services/alerts/telegram.py` | `TelegramNotifier` — sendVideo/sendPhoto/sendMessage + `test_message` |
| CREATE | `backend/app/services/alerts/whatsapp.py` | stub behind the same protocol |
| CREATE | `backend/app/services/alerts/hub.py` | `AlertHub` thread-safe tenant broadcast + `event_message` builder |
| CREATE | `backend/app/services/alerts/delivery.py` | `DeliveryWorker` — DB-polled durable retry |
| CREATE | `backend/app/api/ws.py` | `GET /api/v1/ws/alerts` route (auth, heartbeat) |
| CREATE | `backend/app/api/ratelimit.py` | fixed-window per-IP middleware (API.md §6) |
| CREATE | `backend/app/runtime.py` | `Runtime` — pipelines, alert chain, stream→DB bridge |
| CREATE | `backend/migrations/versions/p5a_delivery_retry.py` | `events.last_attempt_at` |
| CREATE | `backend/migrations/versions/p5b_system_events.py` | `events.camera_id` nullable |
| CREATE | `backend/tests/test_ring_buffer.py`, `test_clip_writer.py`, `test_events_persist.py`, `test_event_handler.py`, `test_ws_alerts.py`, `test_telegram.py`, `test_delivery.py`, `test_retention.py`, `test_runtime.py`, `test_api_ratelimit.py` | verification-matrix homes |
| MODIFY | `backend/app/services/alerts/stage.py` | `Alert` gains `camera_id`, `bbox`, `notify`; ctor gains `camera_id` |
| MODIFY | `backend/app/services/alerts/rules.py` | `RuleConfig` gains `notify` |
| MODIFY | `backend/app/services/alerts/replay.py` | map `rule.notify`; extract `_evaluate` for still replay |
| MODIFY | `backend/app/services/stream/pipeline.py` | `PipelineStatus` gains `frame_width`/`frame_height` |
| MODIFY | `backend/app/main.py` | lifespan: runtime + delivery + retention |
| MODIFY | `backend/app/core/config.py` | `runtime_enabled`, `model_path`, `model_input_size`, `telegram_api_base` |
| MODIFY | `backend/app/api/routers/settings.py` | token encryption at rest, real `/notifiers/test` |
| MODIFY | `backend/app/api/schemas.py` | `NotifierOut.has_token`, `EventOut.camera` nullable, `RuleTestRequest.image_b64` |
| MODIFY | `backend/app/api/routers/events.py` | real `get_clip`, null-camera mapping |
| MODIFY | `backend/app/api/routers/rules.py` | still-image replay branch |
| MODIFY | `backend/app/api/routers/system.py` | `events_today` / `alerts_sent` / `alerts_failed` stats |
| MODIFY | `backend/app/api/deps.py` | `get_detector` dependency (runtime-held) |
| MODIFY | `backend/app/db/repositories/events.py` | `stats()` null camera key; pending-delivery query |
| MODIFY | `backend/tests/conftest.py` | `CAMBRAIN_RUNTIME=0` default |
| MODIFY | `backend/tests/test_alert_stage.py`, `test_pipeline.py`, `test_gate_inference.py` | ctor/field updates |
| CREATE | `frontend/src/api/alertsSocket.js` | WS client with jittered reconnect |
| MODIFY | `frontend/src/stores/events.js` | WS upsert replaces polling |
| MODIFY | `frontend/src/camera/EventTicker.vue` | connect/disconnect lifecycle |
| CREATE | `frontend/src/settings/NotifiersPanel.vue` | notifier CRUD + Test (UsersView pattern) |
| MODIFY | `frontend/src/settings/SystemView.vue` | mount panel (admin) |
| MODIFY | `frontend/src/events/EventRow.vue`, `EventDetail.vue` | null camera → "System" |
| CREATE/ MODIFY | `frontend/src/__tests__/alerts-socket.spec.js`, `settings-notifiers.spec.js`, `ticker.spec.js` | frontend verification |

## Decisions

| # | Decision | Why | Where |
|---|---|---|---|
| D1 | Ring buffer depth **30s** (10s pre + 20s post window), fed from the **sampled** sink via tee (gate-passed frames, 2–5 FPS) | Assembly at T+20 must still hold T−10; sampled frames are honest evidence at a few MB/camera; native-rate buffering would cost ~150MB/camera | `clips.py`, runtime |
| D2 | Clip FPS derived from buffered timestamps, clamped **1–15**; encode `libx264` `yuv420p` (proven by `tests/make_fixtures.py`) | Input spacing varies with the motion gate; even dimensions enforced for x264 | `clips.py` |
| D3 | MJPEG/snapshot keep their **per-request** RTSP sources; the shared pipeline runs detection only | Feeding live view from sampled sinks would drop the grid from native 10–15fps to 2–5fps — a UX regression; N+1 RTSP sessions documented as a debt | runtime |
| D4 | Delivery retries **forever** with backoff capped at 1h; new column `events.last_attempt_at` | A 5-attempt cap strands events after a long outage; "retried when connectivity returns" (tasks.md) is the promise | `delivery.py` + `p5a` |
| D5 | System events need **nullable `camera_id`** (migration `p5b`) + `EventOut.camera` nullable → UI "System" | Schema `camera_id NOT NULL` blocks `triggered_by='system'` rows that DATABASE §9 mandates for quota refusal | migration, router, UI |
| D6 | Two `event` broadcasts — `has_clip:false` on fire, `has_clip:true` after the clip — **upsert by id** client-side | Dashboard must show the alert instantly; API.md has only the `event` type, so the message becomes idempotent | hub, events store |
| D7 | `/ws/frames` stays deferred (documented, not built) | The grid ships MJPEG cleanly; base64-over-WS is the main CPU cost of the dashboard (API.md §3) | scope |
| D8 | Still upload for `POST /rules/{id}/test` ships as **base64 JSON** with an injectable detector dep | Spec §7.3 requires still-or-event; multipart would violate the §7.4 JSON-only mutation rule | rules router |
| D9 | Rate limiter: in-memory fixed window, per-route rows above, `login`/`stream`/`ws` excluded | Phase-4 D4 promised the remaining rows to Phase 5; no Redis (architecture §8) | `ratelimit.py` |
| D10 | Runtime gated by `CAMBRAIN_RUNTIME` (default on; conftest sets `0`); missing weights → log + degraded start (API up, no pipelines) | API tests must never open ONNX/RTSP; CI without weights still boots | `runtime.py`, `main.py` |
| D11 | Notifier tokens stored as `bot_token_enc` **inside** `sites.notifier_config` JSON; GET returns `has_token` mask only | DATABASE §6 + "secrets never returned by GET" (§7.4) | settings router |
| D12 | Quota refusal fires **one** system event per crossing (in-process latch per site) | A disk persistently over quota would otherwise alarm-spam every write | handler/latch |
| D13 | Runtime detector = `yolox_nano.onnx` @ **416** (repo `models/`, phase-3 gate config), env-overridable; tier selection is Phase 6 | Weights already fetched + proven by `test_gate_inference`; `capabilities.py` is a Phase-6 task | config, runtime |
| D14 | Delivery discovers work via **DB poll** (`pending`/`failed` rows), not an in-memory queue | `asyncio.Queue` is not thread-safe across the per-camera loops; the DB is already the durable queue | `delivery.py` |

## Risks

| Risk | Mitigation |
|---|---|
| Encoder availability (`libx264`) in the installed PyAV wheel | Already proven by `tests/make_fixtures.py`; task fails loudly if not |
| Lifespan starts heavy resources in API tests | `CAMBRAIN_RUNTIME=0` in conftest before app import; TestClient runs lifespan on enter |
| Rate limiter breaks existing tests (>120 requests to one app) | Fresh middleware per `create_app()`; existing suites stay far under 120; hammer test isolated |
| Alembic batch rebuild of `events` on a populated DB | Both migrations hand-written with tested `downgrade()`; gate runs upgrade+downgrade roundtrip on a DB copy |
| Cross-thread WS broadcast (camera loops → API loop) | `AlertHub` records the API loop at first subscribe; foreign threads marshal via `run_coroutine_threadsafe` |
| Token leaking into httpx exception URLs | `TelegramNotifier` catches httpx errors and raises a token-free `TelegramError`; assert in test |

---

## Tasks

### Task 1: `Alert` carries camera, bbox, and notify flag

**Files:**
- Modify: `backend/app/services/alerts/stage.py`
- Modify: `backend/app/services/alerts/rules.py` (`RuleConfig` + `notify`)
- Modify: `backend/app/services/alerts/replay.py` (map `notify`)
- Modify: `backend/tests/test_alert_stage.py`, `backend/tests/test_pipeline.py`, `backend/tests/test_gate_inference.py` (call sites)
- Test: `backend/tests/test_alert_stage.py` (new case)

**Interfaces:**
- Consumes: `TrackedObject.bbox: tuple[int, int, int, int]` (tracker), `RuleConfig` (rules), `rule.notify: bool` (DB column already exists).
- Produces: `Alert(rule_id:int, rule_name:str, severity:str, track_id:int, class_name:str, confidence:float, zone:str|None, fired_at:datetime, summary:str, camera_id:int, bbox:tuple[int,int,int,int], notify:bool)`; `AlertStage(..., camera_id:int, ...)`; `RuleConfig.notify: bool = True`. Tasks 4/6/13 rely on these exact names.

- [ ] **Step 1: Write the failing test** — append to `backend/tests/test_alert_stage.py`:

```python
async def test_alert_carries_camera_bbox_and_notify() -> None:
    """Persistence needs the camera id, pixel box, and notify flag (tasks 4-6)."""
    alerts: list[Alert] = []
    stage = AlertStage(
        detector=FakeDetector(),
        rules=[rule()],
        camera_id=7,
        on_alert=alerts.append,
        now_fn=lambda: datetime(2026, 10, 6, 12, 0, tzinfo=ZoneInfo("UTC")),
    )
    await stage(frame())
    assert alerts[0].camera_id == 7
    assert alerts[0].bbox == (10, 10, 50, 120)
    assert alerts[0].notify is True
```

- [ ] **Step 2: Run to verify it fails**

Run: `$env:PATH = "E:\CamBrain\.venv\Scripts;" + $env:PATH; python -m pytest backend/tests/test_alert_stage.py::test_alert_carries_camera_bbox_and_notify -v`
Expected: FAIL — `TypeError: __init__() missing 1 required positional argument: 'camera_id'`

- [ ] **Step 3: Implement**

`rules.py` — append to `RuleConfig` (must stay the last field so defaults remain legal):

```python
    notify: bool = True
```

`stage.py` — extend the dataclass and constructor:

```python
@dataclass(frozen=True, slots=True)
class Alert:
    """A fired rule, ready to persist, broadcast, and deliver (spec A5.6)."""

    rule_id: int
    rule_name: str
    severity: str
    track_id: int
    class_name: str
    confidence: float
    zone: str | None
    fired_at: datetime
    summary: str
    camera_id: int
    bbox: tuple[int, int, int, int]
    notify: bool
```

Constructor: add `camera_id: int` after `rules:` (keyword-only, all params are keyword-only already); store `self._camera_id = camera_id`. In `__call__`, the `Alert(...)` literal gains `camera_id=self._camera_id, bbox=track.bbox, notify=config.notify`.

`replay.py` `rule_config()` gains `notify=rule.notify` in the `RuleConfig(...)` call.

- [ ] **Step 4: Fix every existing construction** (they now TypeError)

Run: `$env:PATH = "E:\CamBrain\.venv\Scripts;" + $env:PATH; python -m pytest backend/tests/test_alert_stage.py backend/tests/test_pipeline.py backend/tests/test_gate_inference.py -v`
Expected: `TypeError: __init__() got an unexpected keyword argument` / missing `camera_id`.

Fix rule: add `camera_id=1` to **every** `AlertStage(...)` call in the three files. `rule()` helpers in `test_alert_stage.py`/`test_rules.py` need no change (`notify` has a default; `defaults` dicts may add `"notify": True` for explicitness). No test constructs a full `Alert(...)` literal today, so only the stage call sites break.

- [ ] **Step 5: Run the suite slice and lint**

Run: `$env:PATH = "E:\CamBrain\.venv\Scripts;" + $env:PATH; python -m pytest backend/tests/test_alert_stage.py backend/tests/test_pipeline.py -v; if ($?) { python -m ruff check backend; if ($?) { python -m mypy backend } }`
Expected: PASS, ruff/mypy clean.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/alerts/stage.py backend/app/services/alerts/rules.py backend/app/services/alerts/replay.py backend/tests/test_alert_stage.py backend/tests/test_pipeline.py backend/tests/test_gate_inference.py
```
Message (`feat(rules): carry camera id, bbox, and notify flag on fired alerts`):
body: `Persistence needs to know which camera fired and where the object was in the frame; the notify flag lets a rule opt out of delivery without suppressing the event. Bbox comes straight from the tracker so event_detections stores frame pixels (DATABASE A4.8).`

---

### Task 2: `FrameRingBuffer` — the pre/post-roll window

**Files:**
- Create: `backend/app/services/events/clips.py`
- Test: `backend/tests/test_ring_buffer.py`

**Interfaces:**
- Consumes: `app.services.stream.jpeg.encode_jpeg(frame: Frame) -> bytes`.
- Produces: `BufferedFrame(at: float, jpeg: bytes)`; `FrameRingBuffer(duration_s: float = 30.0, now: Callable[[], float] = time.monotonic)` with `append(frame: Frame) -> None`, `append_jpeg(at: float, jpeg: bytes) -> None`, `latest_jpeg() -> bytes | None`, `slice(start: float, end: float) -> list[BufferedFrame]`, `__len__`. Tasks 3/6/13 rely on these.

- [ ] **Step 1: Write the failing test** — `backend/tests/test_ring_buffer.py`:

```python
"""Pre/post-roll ring buffer: holds ten seconds of pre-roll (spec A5.7, matrix)."""

from __future__ import annotations

from collections.abc import Iterator

import numpy as np
import pytest

from app.services.events.clips import FrameRingBuffer
from app.services.stream.source import Frame


class Clock:
    """Deterministic monotonic clock."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def frame(index: int) -> Frame:
    return Frame(
        data=np.full((36, 64, 3), index % 255, dtype=np.uint8),
        timestamp=float(index),
        width=64,
        height=36,
    )


@pytest.fixture
def clock() -> Iterator[Clock]:
    yield Clock()


def test_holds_ten_seconds(clock: Clock) -> None:
    """A 10s pre-roll must survive: 50 frames at 5 FPS over 10s all stay."""
    ring = FrameRingBuffer(duration_s=30.0, now=clock)
    for i in range(51):
        ring.append(frame(i))
        clock.t += 0.2  # 5 FPS; t spans 0.0..10.0
    assert len(ring) == 51, "every frame of a 10s window is still pre-roll"


def test_evicts_past_duration(clock: Clock) -> None:
    ring = FrameRingBuffer(duration_s=30.0, now=clock)
    ring.append_jpeg(0.0, b"old")
    clock.t = 31.0
    ring.append_jpeg(31.0, b"new")
    assert [f.jpeg for f in ring.slice(0.0, 32.0)] == [b"new"]
    assert ring.latest_jpeg() == b"new"


def test_slice_is_half_open_and_ordered(clock: Clock) -> None:
    ring = FrameRingBuffer(now=clock)
    for at in (1.0, 2.0, 3.0, 4.0):
        ring.append_jpeg(at, f"f{at}".encode())
    got = [f.at for f in ring.slice(2.0, 4.0)]
    assert got == [2.0, 3.0], "start inclusive, end exclusive"


def test_latest_is_none_when_empty() -> None:
    assert FrameRingBuffer().latest_jpeg() is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `$env:PATH = "E:\CamBrain\.venv\Scripts;" + $env:PATH; python -m pytest backend/tests/test_ring_buffer.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.events.clips'` (the `events` package already exists as an empty dir; add nothing else).

- [ ] **Step 3: Implement `backend/app/services/events/clips.py`**

```python
"""Fixed-duration ring buffer of JPEG frames behind every alert (spec A5.7).

Owns nothing but bytes and timestamps: it is fed by the runtime's tee, sliced
by the handler at fire time, and evicts anything older than its window so a
camera that runs for a month costs one window of memory, not a month of it.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from app.services.stream.jpeg import encode_jpeg
from app.services.stream.source import Frame


@dataclass(frozen=True, slots=True)
class BufferedFrame:
    """One buffered JPEG stamped with a monotonic time."""

    at: float
    jpeg: bytes


class FrameRingBuffer:
    """Hold the last ``duration_s`` of sampled frames.

    Args:
        duration_s: Retention window; 30s covers 10s pre-roll + 20s post-roll
            (spec A5.7) because assembly happens after the post-roll elapses.
        now: Monotonic clock, injected for deterministic tests.
    """

    def __init__(self, *, duration_s: float = 30.0, now: Callable[[], float] = time.monotonic) -> None:
        self._duration_s = duration_s
        self._now = now
        self._frames: deque[BufferedFrame] = deque()

    def append(self, frame: Frame) -> None:
        """Encode and buffer one pipeline frame."""
        self.append_jpeg(self._now(), encode_jpeg(frame))

    def append_jpeg(self, at: float, jpeg: bytes) -> None:
        """Buffer a pre-encoded JPEG stamped at ``at`` (monotonic seconds)."""
        self._frames.append(BufferedFrame(at=at, jpeg=jpeg))
        while self._frames and at - self._frames[0].at > self._duration_s:
            self._frames.popleft()

    def latest_jpeg(self) -> bytes | None:
        """The newest buffered JPEG, or None when the window is empty."""
        return self._frames[-1].jpeg if self._frames else None

    def slice(self, start: float, end: float) -> list[BufferedFrame]:
        """Frames with ``start <= at < end``, oldest first."""
        return [f for f in self._frames if start <= f.at < end]

    def __len__(self) -> int:
        return len(self._frames)
```

- [ ] **Step 4: Run to verify it passes**

Run: `$env:PATH = "E:\CamBrain\.venv\Scripts;" + $env:PATH; python -m pytest backend/tests/test_ring_buffer.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

Message (`feat(events): add the pre/post-roll frame ring buffer`):
body: `Ten seconds of context before a fired rule and twenty after it are the product's evidence (spec A5.7); a timestamped JPEG window costs a few MB per camera and lets the clip writer assemble both sides after the fact.`

---

### Task 3: `ClipWriter` — still, mp4, and the quota refusal

**Files:**
- Modify: `backend/app/services/events/clips.py` (append)
- Test: `backend/tests/test_clip_writer.py`

**Interfaces:**
- Consumes: `BufferedFrame` (Task 2), `settings.media_root`, `shutil.disk_usage`.
- Produces: `QuotaExceededError(StorageError)`; `ClipWriter(media_root: Path, *, disk_usage: Callable[[Path], tuple[int, int]] | None = None)` with `write_still(event_id: int, still_jpeg: bytes) -> str` (relative `stills/{id}.jpg`) and `write_clip(event_id: int, frames: Sequence[BufferedFrame], *, quota_pct: float) -> tuple[str, int, int]` (relative `clips/{id}.mp4`, bytes, duration_ms; raises `QuotaExceededError` before touching disk). Tasks 6/11 rely on these.

- [ ] **Step 1: Write the failing test** — `backend/tests/test_clip_writer.py`:

```python
"""ClipWriter: id-derived paths, libx264 roundtrip, quota refusal (matrix)."""

from __future__ import annotations

from pathlib import Path

import av
import numpy as np
import pytest

from app.core.errors import StorageError
from app.services.events.clips import BufferedFrame, ClipWriter, QuotaExceededError


def _jpegs(count: int) -> list[BufferedFrame]:
    import cv2

    frames = []
    for i in range(count):
        img = np.full((64, 96, 3), (i * 3) % 255, dtype=np.uint8)
        ok, buf = cv2.imencode(".jpg", img)
        assert ok
        frames.append(BufferedFrame(at=i * 0.5, jpeg=buf.tobytes()))
    return frames


def test_write_still_is_id_derived(tmp_path: Path) -> None:
    writer = ClipWriter(tmp_path)
    rel = writer.write_still(42, b"\xff\xd8fake")
    assert rel == "stills/42.jpg"
    assert (tmp_path / "stills" / "42.jpg").read_bytes() == b"\xff\xd8fake"


def test_clip_roundtrip_encodes_mp4(tmp_path: Path) -> None:
    writer = ClipWriter(tmp_path)
    path, size, duration_ms = writer.write_clip(7, _jpegs(8), quota_pct=99.0)
    assert path == "clips/7.mp4"
    assert size > 0 and duration_ms == 3500
    with av.open(str(tmp_path / path)) as container:
        stream = container.streams.video[0]
        decoded = sum(1 for _ in container.decode(stream))
    assert decoded == 8


def test_quota_refuses_writes(tmp_path: Path) -> None:
    """Matrix row: disk quota refuses clips, never partially, never filling the disk."""
    full = (100, 100)  # used == total -> 100% used
    writer = ClipWriter(tmp_path, disk_usage=lambda _p: full)
    with pytest.raises(QuotaExceededError):
        writer.write_clip(1, _jpegs(4), quota_pct=80.0)
    assert not (tmp_path / "clips").exists() or not list((tmp_path / "clips").iterdir())


def test_quota_error_is_a_storage_error(tmp_path: Path) -> None:
    writer = ClipWriter(tmp_path, disk_usage=lambda _p: (100, 100))
    with pytest.raises(StorageError):
        writer.write_clip(1, _jpegs(2), quota_pct=80.0)


def test_short_frame_list_writes_no_clip(tmp_path: Path) -> None:
    writer = ClipWriter(tmp_path)
    with pytest.raises(ValueError, match="at least 2 frames"):
        writer.write_clip(3, _jpegs(1), quota_pct=99.0)
```

- [ ] **Step 2: Run to verify it fails**

Run: `$env:PATH = "E:\CamBrain\.venv\Scripts;" + $env:PATH; python -m pytest backend/tests/test_clip_writer.py -v`
Expected: FAIL — `ImportError: cannot import name 'QuotaExceededError'`.

- [ ] **Step 3: Implement — append to `clips.py`**

```python
def _disk_usage(path: Path) -> tuple[int, int]:
    """(used_bytes, total_bytes) for the filesystem holding ``path``."""
    usage = shutil.disk_usage(path)
    return usage.used, usage.total


class QuotaExceededError(StorageError):
    """Raised when writing a clip would push the disk past the site quota."""


class ClipWriter:
    """Write event stills and clips under ``media_root`` (spec A5.7).

    Owns: id-derived relative paths, the quota gate, and the libx264 encode.
    Deliberately does not own: event rows — the caller attaches the returned
    paths, so a refused clip is a row with ``clip_path`` NULL, not a rollback.
    """

    def __init__(
        self,
        media_root: Path,
        *,
        disk_usage: Callable[[Path], tuple[int, int]] | None = None,
    ) -> None:
        self._root = media_root
        self._disk_usage = disk_usage or _disk_usage

    def write_still(self, event_id: int, still_jpeg: bytes) -> str:
        """Persist the event still; returns the media-root-relative path."""
        path = self._root / "stills" / f"{event_id}.jpg"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(still_jpeg)
        return f"stills/{event_id}.jpg"

    def write_clip(
        self,
        event_id: int,
        frames: Sequence[BufferedFrame],
        *,
        quota_pct: float,
    ) -> tuple[str, int, int]:
        """Encode pre+post-roll frames to mp4; returns (rel_path, bytes, ms).

        Raises:
            ValueError: Fewer than two frames — a one-frame clip is not a clip.
            QuotaExceededError: Disk usage is at or past ``quota_pct``; checked
                before any file is created, so a refusal never leaves debris.
        """
        if len(frames) < 2:
            raise ValueError(f"clip needs at least 2 frames, got {len(frames)}")
        used, total = self._disk_usage(self._root)
        if total and used / total * 100 >= quota_pct:
            raise QuotaExceededError(
                f"disk at {used / total * 100:.0f}% >= quota {quota_pct:.0f}%; clip refused"
            )
        span = max(frames[-1].at - frames[0].at, 0.001)
        fps = max(1, min(15, round(len(frames) / span)))
        path = self._root / "clips" / f"{event_id}.mp4"
        path.parent.mkdir(parents=True, exist_ok=True)
        with av.open(str(path), mode="w") as container:
            stream = container.add_stream("libx264", rate=fps)
            for buf in frames:
                array = cv2.imdecode(np.frombuffer(buf.jpeg, np.uint8), cv2.IMREAD_COLOR)
                if array is None:
                    continue
                height, width = array.shape[:2]
                stream.width = width - (width % 2)
                stream.height = height - (height % 2)
                video = av.VideoFrame.from_ndarray(array, format="bgr24")
                for packet in stream.encode(video):
                    container.mux(packet)
            for packet in stream.encode(None):
                container.mux(packet)
        size = path.stat().st_size
        return f"clips/{event_id}.mp4", size, round(span * 1000)
```

Add module-level imports at the top of `clips.py` (merge with Task 2's block): `import shutil`, `import av`, `import cv2`, `import numpy as np`, `from collections.abc import Callable, Sequence`, and `from app.core.errors import StorageError`.

- [ ] **Step 4: Run to verify it passes**

Run: `$env:PATH = "E:\CamBrain\.venv\Scripts;" + $env:PATH; python -m pytest backend/tests/test_clip_writer.py backend/tests/test_ring_buffer.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

Message (`feat(events): clip writer with still, mp4, and quota refusal`):
body: `The disk quota protects the NVR that holds the customer's evidence — the refusal path checks usage before creating any file (spec A5.7, DATABASE A9). Paths derive from events.id so no user string ever reaches the filesystem (SECURITY A6.2).`

---

### Task 4: Event + detection persistence (+ `last_attempt_at` migration)

**Files:**
- Create: `backend/migrations/versions/p5a_delivery_retry.py`
- Modify: `backend/app/db/models/event.py` (add `last_attempt_at`)
- Create: `backend/app/services/events/persist.py`
- Test: `backend/tests/test_events_persist.py`

**Interfaces:**
- Consumes: `Alert` (Task 1), `Event`/`EventDetection` models (exist), `Camera` model.
- Produces: `create_event(db: Session, alert: Alert) -> Event`; `attach_media(db: Session, event_id: int, *, thumbnail_path: str | None, clip_path: str | None, clip_bytes: int | None, duration_ms: int | None) -> Event`; `mark_delivery(db: Session, event_id: int, *, status: str, attempts: int | None = None, error: str | None = None, delivered: datetime | None = None, attempted: datetime | None = None) -> None`; migration head `p5a_delivery_retry` (Task 9 chains on it; Task 12 adds `create_system_event`). Tasks 6/9/11/12 rely on these.

- [ ] **Step 1: Write the failing test** — `backend/tests/test_events_persist.py`:

```python
"""Alert -> events + event_detections rows (DATABASE A4.7-A4.8)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from app.db.models import Camera, Event, Site
from app.db.models.event import EventDetection
from app.services.alerts.stage import Alert
from app.services.events.persist import attach_media, create_event, mark_delivery


def _alert(**overrides: object) -> Alert:
    defaults: dict[str, object] = {
        "rule_id": 3,
        "rule_name": "After-hours",
        "severity": "critical",
        "track_id": 9,
        "class_name": "person",
        "confidence": 0.81,
        "zone": "Loading dock",
        "fired_at": datetime(2026, 10, 6, 22, 0, tzinfo=UTC),
        "summary": "1 person in Loading dock",
        "camera_id": 0,
        "bbox": (12, 24, 120, 300),
        "notify": True,
    }
    defaults.update(overrides)
    return Alert(**defaults)  # type: ignore[arg-type]


def _camera(db, site: Site) -> Camera:
    camera = Camera(site_id=site.id, name="Back door", rtsp_url="rtsp://10.0.0.6/ch1")
    db.add(camera)
    db.commit()
    return camera


def test_create_event_writes_event_and_detection(db_session, seeded) -> None:
    site, _admin, _viewer = seeded
    camera = _camera(db_session, site)
    event = create_event(db_session, _alert(camera_id=camera.id))
    assert event.site_id == site.id and event.delivery_status == "pending"
    assert event.started_at.tzinfo is None, "DB columns are naive UTC"
    rows = db_session.execute(
        select(EventDetection).where(EventDetection.event_id == event.id)
    ).scalars().all()
    assert len(rows) == 1
    det = rows[0]
    assert det.bbox == [12, 24, 120, 300]
    assert det.class_name == "person" and det.zone_name == "Loading dock"
    assert det.camera_id == camera.id


def test_notify_false_starts_skipped(db_session, seeded) -> None:
    site, _admin, _viewer = seeded
    camera = _camera(db_session, site)
    event = create_event(db_session, _alert(camera_id=camera.id, notify=False))
    assert event.delivery_status == "skipped"


def test_attach_media_and_mark_delivery(db_session, seeded) -> None:
    site, _admin, _viewer = seeded
    camera = _camera(db_session, site)
    event = create_event(db_session, _alert(camera_id=camera.id))
    attach_media(
        db_session,
        event.id,
        thumbnail_path="stills/1.jpg",
        clip_path="clips/1.mp4",
        clip_bytes=2048,
        duration_ms=9000,
    )
    mark_delivery(
        db_session,
        event.id,
        status="sent",
        attempts=1,
        delivered=datetime(2026, 10, 6, 22, 1, tzinfo=UTC),
        attempted=datetime(2026, 10, 6, 22, 1, tzinfo=UTC),
    )
    db_session.expire_all()
    row = db_session.get(Event, event.id)
    assert row.clip_path == "clips/1.mp4" and row.clip_bytes == 2048
    assert row.delivery_status == "sent" and row.delivery_attempts == 1
    assert row.delivered_at is not None and row.last_attempt_at is not None
```

- [ ] **Step 2: Run to verify it fails**

Run: `$env:PATH = "E:\CamBrain\.venv\Scripts;" + $env:PATH; python -m pytest backend/tests/test_events_persist.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.events.persist'`.

- [ ] **Step 2: Run to verify it fails**

Run: `$env:PATH = "E:\CamBrain\.venv\Scripts;" + $env:PATH; python -m pytest backend/tests/test_events_persist.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.events.persist'`.

- [ ] **Step 3a: Migration `p5a` + model column**

Create `backend/migrations/versions/p5a_delivery_retry.py`:

```python
"""Add events.last_attempt_at for durable delivery backoff (phase 5).

Revision ID: p5a_delivery_retry
Revises: b0d9844cf940
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "p5a_delivery_retry"
down_revision: str | None = "b0d9844cf940"
branch_labels: str | list[str] | None = None
depends_on: str | list[str] | None = None


def upgrade() -> None:
    op.add_column("events", sa.Column("last_attempt_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("events") as batch:
        batch.drop_column("last_attempt_at")
```

In `backend/app/db/models/event.py`, after `last_delivery_error`:

```python
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
```

Run: `$env:PATH = "E:\CamBrain\.venv\Scripts;" + $env:PATH; python -m alembic upgrade head` then `python -m alembic downgrade -1` then `python -m alembic upgrade head` — Expected: three clean runs (roundtrip proves the downgrade).

- [ ] **Step 3b: Implement `backend/app/services/events/persist.py`**

```python
"""Durable event writes: fired alerts become rows, never memory (spec A4.8).

Owns the events/event_detections insert paths and the delivery-status updates.
Deliberately does not own: files (ClipWriter), transport (notifier), or
broadcasts (hub) — each is a separate collaborator the handler composes.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.db.models import Camera, Event
from app.db.models.event import EventDetection
from app.services.alerts.stage import Alert


def _naive_utc(when: datetime) -> datetime:
    """DB columns are naive UTC; aware inputs are converted, naive kept."""
    return when.astimezone(UTC).replace(tzinfo=None) if when.tzinfo else when


def create_event(db: Session, alert: Alert) -> Event:
    """Insert the event and its first detection row; commits once.

    Raises:
        ValueError: The alert's camera does not exist — a programming error
            in the runtime wiring, not a recoverable condition.
    """
    camera = db.get(Camera, alert.camera_id)
    if camera is None:
        raise ValueError(f"alert references unknown camera {alert.camera_id}")
    fired = _naive_utc(alert.fired_at)
    event = Event(
        site_id=camera.site_id,
        camera_id=alert.camera_id,
        rule_id=alert.rule_id,
        triggered_by="rule",
        started_at=fired,
        severity=alert.severity,
        summary=alert.summary,
        delivery_status="pending" if alert.notify else "skipped",
    )
    db.add(event)
    db.flush()
    db.add(
        EventDetection(
            event_id=event.id,
            camera_id=alert.camera_id,
            class_name=alert.class_name,
            confidence=alert.confidence,
            bbox=list(alert.bbox),
            track_id=alert.track_id,
            zone_name=alert.zone,
            detected_at=fired,
        )
    )
    db.commit()
    db.refresh(event)
    return event


def attach_media(
    db: Session,
    event_id: int,
    *,
    thumbnail_path: str | None,
    clip_path: str | None,
    clip_bytes: int | None,
    duration_ms: int | None,
) -> Event:
    """Attach id-derived media paths (and optional clip stats) to an event."""
    event = db.get(Event, event_id)
    if event is None:
        raise ValueError(f"event {event_id} not found")
    event.thumbnail_path = thumbnail_path
    event.clip_path = clip_path
    event.clip_bytes = clip_bytes
    event.duration_ms = duration_ms
    db.commit()
    db.refresh(event)
    return event


def mark_delivery(
    db: Session,
    event_id: int,
    *,
    status: str,
    attempts: int | None = None,
    error: str | None = None,
    delivered: datetime | None = None,
    attempted: datetime | None = None,
) -> None:
    """Update the durable delivery record for an event."""
    event = db.get(Event, event_id)
    if event is None:
        return
    event.delivery_status = status
    if attempts is not None:
        event.delivery_attempts = attempts
    if error is not None:
        event.last_delivery_error = error
    if delivered is not None:
        event.delivered_at = _naive_utc(delivered)
    if attempted is not None:
        event.last_attempt_at = _naive_utc(attempted)
    db.commit()
```

- [ ] **Step 4: Run to verify it passes**

Run: `$env:PATH = "E:\CamBrain\.venv\Scripts;" + $env:PATH; python -m pytest backend/tests/test_events_persist.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

Message (`feat(events): persist fired alerts as events and detections`):
body: `The event row is the durable record the dashboard, retention, and delivery all read (DATABASE A4.7). Bbox is stored in frame pixels once, at the recorded resolution, and never re-projected; delivery starts as pending so a Telegram outage cannot lose the alert. last_attempt_at lands with it so retry backoff survives restarts.`

---

### Task 5: `AlertHub` + `GET /api/v1/ws/alerts`

**Files:**
- Create: `backend/app/services/alerts/hub.py`
- Create: `backend/app/api/ws.py`
- Modify: `backend/app/main.py` (include router)
- Test: `backend/tests/test_ws_alerts.py`

**Interfaces:**
- Consumes: `Event` model, `verify_access_token` (`app.api.auth`), `SessionLocal`.
- Produces: `AlertHub` with `subscribe(site_id: int, ws: WebSocket) -> None`, `unsubscribe(site_id: int, ws: WebSocket) -> None`, `broadcast(site_id: int, message: dict[str, Any]) -> None` (thread-safe, callable from camera loops); `event_message(event: Event, camera_name: str | None) -> dict[str, Any]` returning the API.md `event` payload; `get_alert_hub() -> AlertHub` singleton. Tasks 6/13 rely on these. Route: `GET /api/v1/ws/alerts`, subprotocol `cambrain.jwt.<token>`, heartbeat 30s.

- [ ] **Step 1: Write the failing test** — `backend/tests/test_ws_alerts.py`:

```python
"""/ws/alerts: subprotocol auth, tenant isolation, event delivery (API A3)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api import ws as ws_module
from app.db.models import Camera, Event


def _token(client: TestClient, username: str = "ramesh", password: str = "correct-horse-battery") -> str:
    res = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


def _event(db_session, seeded) -> Event:
    site, _admin, _viewer = seeded
    camera = Camera(site_id=site.id, name="Back door", rtsp_url="rtsp://10.0.0.6/ch1")
    db_session.add(camera)
    db_session.commit()
    event = Event(
        site_id=site.id,
        camera_id=camera.id,
        rule_id=None,
        triggered_by="rule",
        started_at=ws_module._naive_now(),
        severity="critical",
        summary="1 person in Loading dock",
    )
    db_session.add(event)
    db_session.commit()
    return event


def test_connects_with_jwt_subprotocol(client: TestClient, db_session, seeded) -> None:  # noqa: ARG001
    token = _token(client)
    with client.websocket_connect("/api/v1/ws/alerts", subprotocols=[f"cambrain.jwt.{token}"]) as ws:
        hub = ws_module.get_alert_hub()
        event = _event(db_session, seeded)
        hub.broadcast(event.site_id, ws_module.event_message(event, "Back door"))
        frame = ws.receive_json()
        assert frame["type"] == "event"
        assert frame["data"]["camera"]["name"] == "Back door"
        assert frame["data"]["has_clip"] is False


def test_rejects_bad_token(client: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            "/api/v1/ws/alerts", subprotocols=["cambrain.jwt.nope"]
        ) as ws:
            ws.receive_json()


def test_first_message_auth_fallback(client: TestClient) -> None:
    token = _token(client)
    with client.websocket_connect("/api/v1/ws/alerts") as ws:
        ws.send_json({"type": "auth", "token": token})
        # Authenticated: a broadcast now arrives without error.
        hub = ws_module.get_alert_hub()
        hub.broadcast(1, {"type": "heartbeat", "data": {"ts": "2026-10-06T22:00:00Z"}})
        assert ws.receive_json()["type"] == "heartbeat"


def test_cross_site_broadcast_never_arrives(client: TestClient, db_session, seeded) -> None:
    token = _token(client)
    site, _admin, _viewer = seeded
    with client.websocket_connect("/api/v1/ws/alerts", subprotocols=[f"cambrain.jwt.{token}"]) as ws:
        hub = ws_module.get_alert_hub()
        hub.broadcast(site.id + 999, {"type": "event", "data": {"id": 999}})
        # The wrong-site message must not appear; guard with a short heartbeat.
        import anyio

        with anyio.fail_after(0.2):
            frame = ws.receive_json()
        assert frame["type"] != "event" or frame["data"]["id"] != 999
```

- [ ] **Step 2: Run to verify it fails**

Run: `$env:PATH = "E:\CamBrain\.venv\Scripts;" + $env:PATH; python -m pytest backend/tests/test_ws_alerts.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.api.ws'` / `hub` not found.

- [ ] **Step 3: Implement `backend/app/services/alerts/hub.py`**

```python
"""Tenant-scoped fan-out for /ws/alerts (API A3).

Owns: the subscriber sets and the cross-thread marshal from camera loops onto
the API event loop. Deliberately does not own: authentication (the route
verifies the token) or payload shape policy beyond the two builders here.
"""

from __future__ import annotations

import asyncio
import threading
from datetime import UTC, datetime
from typing import Any

from starlette.websockets import WebSocket

from app.db.models import Event


class AlertHub:
    """Thread-safe broadcaster: camera worker threads -> API loop -> sockets."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subs: dict[int, set[WebSocket]] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    def subscribe(self, site_id: int, ws: WebSocket) -> None:
        """Register a socket; records the API loop on first subscribe."""
        with self._lock:
            if self._loop is None:
                self._loop = asyncio.get_running_loop()
            self._subs.setdefault(site_id, set()).add(ws)

    def unsubscribe(self, site_id: int, ws: WebSocket) -> None:
        """Drop a socket; never raises when already gone."""
        with self._lock:
            subs = self._subs.get(site_id)
            if subs is not None:
                subs.discard(ws)
                if not subs:
                    self._subs.pop(site_id, None)

    def broadcast(self, site_id: int, message: dict[str, Any]) -> None:
        """Send ``message`` to every socket of ``site_id``; no-op with none.

        Safe from any thread: same-loop callers create a task, foreign threads
        marshal onto the API loop. Send failures drop that socket only.
        """
        with self._lock:
            subs = list(self._subs.get(site_id, ()))
            loop = self._loop
        if not subs or loop is None:
            return

        async def _dispatch() -> None:
            for ws in subs:
                try:
                    await ws.send_json(message)
                except Exception:  # noqa: BLE001 - a dead socket must not break fan-out
                    self.unsubscribe(site_id, ws)

        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            loop.create_task(_dispatch())
        else:
            asyncio.run_coroutine_threadsafe(_dispatch(), loop)


_HUB = AlertHub()


def get_alert_hub() -> AlertHub:
    """The process-wide hub (tests reset it via the fixture below)."""
    return _HUB


def event_message(event: Event, camera_name: str | None) -> dict[str, Any]:
    """The API.md `event` frame; idempotent — clients upsert by id (D6)."""
    started = event.started_at
    if started.tzinfo is None:
        started = started.replace(tzinfo=UTC)
    return {
        "type": "event",
        "data": {
            "id": event.id,
            "camera": {"id": event.camera_id, "name": camera_name or "System"},
            "severity": event.severity,
            "summary": event.summary,
            "started_at": started.isoformat().replace("+00:00", "Z"),
            "has_clip": event.clip_path is not None,
        },
    }
```

- [ ] **Step 4: Implement `backend/app/api/ws.py`**

```python
"""/ws/alerts — server-to-client only (API A3).

Token travels via Sec-WebSocket-Protocol (`cambrain.jwt.<token>`) because URLs
leak into logs and history; a first-message fallback covers clients that cannot
set subprotocols. Mutations never ride this socket.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.security import WebSocketSeparateBearer  # not used; see _token_from below

from app.api.auth import AuthError, verify_access_token
from app.db.session import SessionLocal
from app.services.alerts.hub import get_alert_hub

router = APIRouter()

HEARTBEAT_S = 30.0
_PROTOCOL_PREFIX = "cambrain.jwt."


def _naive_now() -> datetime:
    """Naive UTC now for event rows created in tests."""
    return datetime.now(tz=UTC).replace(tzinfo=None)


def _token_from(websocket: WebSocket) -> str | None:
    """Pull the JWT out of the subprotocol list, if present."""
    for proto in websocket.headers.get("sec-websocket-protocol", "").split(","):
        value = proto.strip()
        if value.startswith(_PROTOCOL_PREFIX):
            return value[len(_PROTOCOL_PREFIX) :]
    return None


async def _authenticate(websocket: WebSocket, token: str) -> int | None:
    """Verify the token; return site_id or None (route then closes 4401)."""
    db = SessionLocal()
    try:
        claims = verify_access_token(db, token)
        return int(claims["site_id"])
    except AuthError:
        return None
    finally:
        db.close()


async def _heartbeat(websocket: WebSocket) -> None:
    """Send the API.md heartbeat every HEARTBEAT_S until cancelled."""
    while True:
        await asyncio.sleep(HEARTBEAT_S)
        await websocket.send_json(
            {"type": "heartbeat", "data": {"ts": datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")}}
        )


@router.websocket("/ws/alerts")
async def ws_alerts(websocket: WebSocket) -> None:
    """Authenticated per-site alert stream (API A3)."""
    token = _token_from(websocket)
    site_id = await _authenticate(websocket, token) if token else None
    if site_id is None:
        # No (valid) subprotocol: accept, allow one auth message, else 4401.
        await websocket.accept()
        try:
            message = await asyncio.wait_for(websocket.receive_json(), timeout=5.0)
        except (TimeoutError, WebSocketDisconnect, ValueError):
            await websocket.close(code=4401)
            return
        token = message.get("token") if isinstance(message, dict) else None
        site_id = await _authenticate(websocket, token) if token else None
        if site_id is None:
            await websocket.close(code=4401)
            return
    else:
        await websocket.accept(
            subprotocol=_PROTOCOL_PREFIX + token
            if _PROTOCOL_PREFIX + token in websocket.headers.get("sec-websocket-protocol", "")
            else None
        )

    hub = get_alert_hub()
    hub.subscribe(site_id, websocket)
    heartbeat = asyncio.create_task(_heartbeat(websocket))
    try:
        while True:
            await websocket.receive_text()  # client frames are ignored (server->client only)
    except WebSocketDisconnect:
        pass
    finally:
        heartbeat.cancel()
        hub.unsubscribe(site_id, websocket)
```

Note: `fastapi.security.WebSocketSeparateBearer` does not exist — drop that import line entirely when writing the file; the module needs only the imports shown minus it.

- [ ] **Step 5: Wire the router and run**

`main.py`: add `from app.api.ws import router as ws_router` and `app.include_router(ws_router, prefix=API_PREFIX)` after the events router. Add to `backend/tests/conftest.py` (near the top, with the JWT env line) a fixture:

```python
@pytest.fixture(autouse=True)
def _reset_alert_hub() -> Iterator[None]:
    """The hub is process-wide; clear subscribers between tests."""
    from app.services.alerts.hub import get_alert_hub

    hub = get_alert_hub()
    with hub._lock:  # noqa: SLF001 - test-only reset
        hub._subs.clear()
        hub._loop = None
    yield
```

Run: `$env:PATH = "E:\CamBrain\.venv\Scripts;" + $env:PATH; python -m pytest backend/tests/test_ws_alerts.py -v`
Expected: 4 passed. (If `test_rejects_bad_token` hangs, the close-before-accept path failed — Starlette closes the handshake when `close()` is awaited without `accept()`; keep the code as written.)

- [ ] **Step 6: Commit**

Message (`feat(api): tenant-scoped /ws/alerts broadcast hub`):
body: `The ticker's 10s poll becomes an instant push without ever letting the socket mutate state (API A3). The hub marshals sends from camera worker loops onto the API loop, because those threads have no business touching sockets they do not own.`

---

### Task 6: `AlertHandler` — the per-camera orchestrator

**Files:**
- Create: `backend/app/services/events/handler.py`
- Test: `backend/tests/test_event_handler.py`

**Interfaces:**
- Consumes: `Alert` (T1), `FrameRingBuffer`, `ClipWriter`, `QuotaExceededError` (T2/3), `create_event`/`attach_media` (T4), `AlertHub`/`event_message` (T5).
- Produces: `AlertHandler(camera_id:int, site_id:int, camera_name:str, *, ring, writer, hub, session_factory: Callable[[], Session] = SessionLocal, post_roll_s: float = 20.0, pre_roll_s: float = 10.0, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep, now: Callable[[], float] = time.monotonic, quota_pct: Callable[[], float] | None = None, on_quota_exceeded: Callable[[str], None] | None = None)` implementing `async def __call__(alert: Alert) -> None` (an `AlertSink`); plus `async def close() -> None` cancelling in-flight post-roll tasks. Task 13 constructs these.

- [ ] **Step 1: Write the failing test** — `backend/tests/test_event_handler.py`:

```python
"""AlertHandler: persist -> still -> broadcast -> post-roll clip (arch A7)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select

from app.db.models import Camera, Event, Site
from app.db.models.event import EventDetection
from app.services.alerts.stage import Alert
from app.services.events.clips import BufferedFrame, ClipWriter, FrameRingBuffer
from app.services.events.handler import AlertHandler


class FakeHub:
    """Records broadcasts instead of touching sockets."""

    def __init__(self) -> None:
        self.messages: list[tuple[int, dict]] = []

    def broadcast(self, site_id: int, message: dict) -> None:
        self.messages.append((site_id, message))


def _alert(camera_id: int) -> Alert:
    return Alert(
        rule_id=3,
        rule_name="After-hours",
        severity="critical",
        track_id=9,
        class_name="person",
        confidence=0.81,
        zone="Loading dock",
        fired_at=datetime(2026, 10, 6, 22, 0, tzinfo=UTC),
        summary="1 person in Loading dock",
        camera_id=camera_id,
        bbox=(12, 24, 120, 300),
        notify=True,
    )


@pytest.fixture
def world(db_session, seeded, tmp_path: Path):
    site, _admin, _viewer = seeded
    camera = Camera(site_id=site.id, name="Back door", rtsp_url="rtsp://10.0.0.6/ch1")
    db_session.add(camera)
    db_session.commit()
    ring = FrameRingBuffer()
    for i in range(6):
        ring.append_jpeg(float(i), b"\xff\xd8" + bytes([i]))
    hub = FakeHub()
    slept: list[float] = []

    async def instant(seconds: float) -> None:
        slept.append(seconds)

    handler = AlertHandler(
        camera_id=camera.id,
        site_id=site.id,
        camera_name="Back door",
        ring=ring,
        writer=ClipWriter(tmp_path),
        hub=hub,  # type: ignore[arg-type]
        session_factory=lambda: db_session,
        sleep=instant,
        quota_pct=lambda: 99.0,
    )
    return handler, db_session, hub, slept, tmp_path, camera.id


async def test_fire_persists_still_broadcasts_then_clips(world) -> None:
    handler, db, hub, slept, _tmp, camera_id = world
    await handler(_alert(camera_id))
    event = db.execute(select(Event)).scalars().one()
    assert event.thumbnail_path == f"stills/{event.id}.jpg"
    assert event.clip_path is None, "clip lands after the post-roll"
    assert hub.messages[0][1]["data"]["has_clip"] is False
    await asyncio.sleep(0)  # let the scheduled _finish task run (sleep is instant)

    db.expire_all()
    event = db.execute(select(Event)).scalars().one()
    assert slept == pytest.approx([20.0]), "post-roll waits 20s"
    # Clip may be refused only for <2 frames; we buffered 6, so it must exist.
    assert event.clip_path == f"clips/{event.id}.mp4"
    assert (db.get(Camera, camera_id)) is not None
    assert hub.messages[-1][1]["data"]["has_clip"] is True
    dets = db.execute(select(EventDetection)).scalars().all()
    assert len(dets) == 1 and dets[0].bbox == [12, 24, 120, 300]


async def test_quota_refusal_fires_system_hook(world) -> None:
    handler, db, hub, _slept, _tmp, camera_id = world
    quotas: list[str] = []
    handler.set_quota_hook(lambda summary: quotas.append(summary))
    handler._quota_pct = lambda: 0.0  # noqa: SLF001 - force refusal
    await handler(_alert(camera_id))
    await asyncio.sleep(0)
    assert quotas and "quota" in quotas[0]
    event = db.execute(select(Event)).scalars().one()
    assert event.clip_path is None, "refused clip leaves the row, not debris"
```

- [ ] **Step 2: Run to verify it fails**

Run: `$env:PATH = "E:\CamBrain\.venv\Scripts;" + $env:PATH; python -m pytest backend/tests/test_event_handler.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.events.handler'`.

- [ ] **Step 3: Implement `backend/app/services/events/handler.py`**

```python
"""One fired alert, carried from stage to disk to dashboard (arch A7).

Owns the ordering: persist first (an event exists before any IO can fail),
still and broadcast next (the operator sees it instantly), clip after the
20s post-roll (a task the handler tracks and cancels on shutdown).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

from sqlalchemy.orm import Session

from app.db.models import Event, Site
from app.db.session import SessionLocal
from app.services.alerts.hub import AlertHub, event_message
from app.services.alerts.stage import Alert
from app.services.events.clips import ClipWriter, FrameRingBuffer, QuotaExceededError
from app.services.events.persist import attach_media, create_event


class AlertHandler:
    """The per-camera AlertSink: persist, snap, announce, finish the clip."""

    def __init__(
        self,
        *,
        camera_id: int,
        site_id: int,
        camera_name: str,
        ring: FrameRingBuffer,
        writer: ClipWriter,
        hub: AlertHub,
        session_factory: Callable[[], Session] = SessionLocal,
        post_roll_s: float = 20.0,
        pre_roll_s: float = 10.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        now: Callable[[], float] = time.monotonic,
        quota_pct: Callable[[], float] | None = None,
        on_quota_exceeded: Callable[[str], None] | None = None,
    ) -> None:
        self._camera_id = camera_id
        self._site_id = site_id
        self._camera_name = camera_name
        self._ring = ring
        self._writer = writer
        self._hub = hub
        self._session_factory = session_factory
        self._post_roll_s = post_roll_s
        self._pre_roll_s = pre_roll_s
        self._sleep = sleep
        self._now = now
        self._quota_pct = quota_pct or self._site_quota
        self._on_quota_exceeded = on_quota_exceeded
        self._tasks: set[asyncio.Task[None]] = set()

    def set_quota_hook(self, hook: Callable[[str], None] | None) -> None:
        """Attach the quota-refusal hook after construction (runtime wiring)."""
        self._on_quota_exceeded = hook

    def _site_quota(self) -> float:
        """The site's disk quota percentage (default 80 when unreadable)."""
        db = self._session_factory()
        try:
            site = db.get(Site, self._site_id)
            return float(site.disk_quota_pct) if site else 80.0
        finally:
            db.close()

    async def __call__(self, alert: Alert) -> None:
        """Persist immediately, then schedule the post-roll clip (AlertSink)."""
        fire_at = self._now()
        db = self._session_factory()
        try:
            event = create_event(db, alert)
            event_id, site_id = event.id, event.site_id
        finally:
            db.close()

        still = self._ring.latest_jpeg()
        if still is not None:
            db = self._session_factory()
            try:
                thumb = self._writer.write_still(event_id, still)
                attach_media(
                    db,
                    event_id,
                    thumbnail_path=thumb,
                    clip_path=None,
                    clip_bytes=None,
                    duration_ms=None,
                )
                event = db.get(Event, event_id)
                self._hub.broadcast(site_id, event_message(event, self._camera_name))
            finally:
                db.close()

        task = asyncio.create_task(self._finish(event_id, fire_at))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _finish(self, event_id: int, fire_at: float) -> None:
        """After the post-roll: assemble the slice and attach the clip."""
        await self._sleep(self._post_roll_s)
        frames = self._ring.slice(fire_at - self._pre_roll_s, fire_at + self._post_roll_s)
        db = self._session_factory()
        try:
            try:
                path, size, duration_ms = self._writer.write_clip(
                    event_id, frames, quota_pct=self._quota_pct()
                )
            except QuotaExceededError as exc:
                if self._on_quota_exceeded is not None:
                    self._on_quota_exceeded(str(exc))
                return
            except ValueError:
                return  # fewer than two buffered frames — still and event stand
            current = db.get(Event, event_id)
            event = attach_media(
                db,
                event_id,
                thumbnail_path=current.thumbnail_path if current else None,
                clip_path=path,
                clip_bytes=size,
                duration_ms=duration_ms,
            )
            self._hub.broadcast(event.site_id, event_message(event, self._camera_name))
        finally:
            db.close()

    async def close(self) -> None:
        """Cancel in-flight post-roll tasks on shutdown."""
        for task in list(self._tasks):
            task.cancel()
```

- [ ] **Step 4: Run to verify it passes**

Run: `$env:PATH = "E:\CamBrain\.venv\Scripts;" + $env:PATH; python -m pytest backend/tests/test_event_handler.py -v`
Expected: 2 passed.

- [ ] **Step 5: Run full backend loop**

Run: `$env:PATH = "E:\CamBrain\.venv\Scripts;" + $env:PATH; python -m pytest backend -m "not rtsp and not slow"; if ($?) { python -m ruff check backend; if ($?) { python -m mypy backend } }`
Expected: all prior tests + 6 new pass; ruff/mypy clean.

- [ ] **Step 6: Commit**

Message (`feat(events): alert handler persists, snaps, announces, then clips`):
body: `Ordering is the design: the event row exists before any file IO can fail, the still and WS broadcast land within milliseconds, and the clip is assembled after the 20s post-roll in a task the handler owns and cancels on shutdown (arch A7).`

---

### Task 7: `Notifier` protocol, Telegram transport, WhatsApp stub

**Files:**
- Create: `backend/app/services/alerts/notifier.py`
- Create: `backend/app/services/alerts/telegram.py`
- Create: `backend/app/services/alerts/whatsapp.py`
- Test: `backend/tests/test_telegram.py`

**Interfaces:**
- Consumes: `Event` model, `app.core.config.settings.media_root` / `settings.telegram_api_base` (added this task), httpx (already in requirements).
- Produces: `Notifier` Protocol (`async def send(self, event: Event) -> None`); `TelegramError(Exception)`; `TelegramNotifier(bot_token: str, chat_id: str, *, client: httpx.AsyncClient | None = None, base_url: str | None = None, media_root: Path | None = None)` with `async send(event)`, `async test_message() -> dict[str, Any]`; `WhatsAppNotifier` with the same `send` raising `NotImplementedError`. Tasks 8/9 rely on these.

`config.py` additions (this task, before tests run): `telegram_api_base: str = "https://api.telegram.org"` and `runtime_enabled: bool = True` and `model_path: Path = Path(__file__).resolve().parents[3] / "models" / "yolox_nano.onnx"` and `model_input_size: int = 416` (D13 — `parents[3]` is the repo root from `backend/app/core/config.py`).

- [ ] **Step 1: Write the failing test** — `backend/tests/test_telegram.py`:

```python
"""Telegram transport: photo/video/text, masked errors, offline survival."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from app.db.models import Camera, Event, Site
from app.services.alerts.telegram import TelegramError, TelegramNotifier


def _event(db_session, seeded, tmp_path: Path, *, with_media: bool) -> Event:
    site, _admin, _viewer = seeded
    camera = Camera(site_id=site.id, name="Back door", rtsp_url="rtsp://10.0.0.6/ch1")
    db_session.add(camera)
    db_session.commit()
    if with_media:
        (tmp_path / "stills").mkdir()
        (tmp_path / "stills" / "1.jpg").write_bytes(b"\xff\xd8still")
        (tmp_path / "clips").mkdir()
        (tmp_path / "clips" / "1.mp4").write_bytes(b"\x00clip")
    event = Event(
        site_id=site.id,
        camera_id=camera.id,
        rule_id=None,
        triggered_by="rule",
        started_at=datetime(2026, 10, 6, 22, 0, tzinfo=UTC).replace(tzinfo=None),
        severity="critical",
        summary="1 person in Loading dock",
        thumbnail_path="stills/1.jpg" if with_media else None,
        clip_path="clips/1.mp4" if with_media else None,
    )
    db_session.add(event)
    db_session.commit()
    return event


def _recording_client(responses: list[httpx.Response], captured: list[httpx.Request]) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return responses.pop(0) if responses else httpx.Response(200, json={"ok": True, "result": {}})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_sends_video_when_clip_exists(db_session, seeded, tmp_path: Path) -> None:
    event = _event(db_session, seeded, tmp_path, with_media=True)
    captured: list[httpx.Request] = []
    notifier = TelegramNotifier(
        bot_token="SECRET-TOKEN", chat_id="42", client=_recording_client([], captured), media_root=tmp_path
    )
    await notifier.send(event)
    request = captured[0]
    assert "sendVideo" in str(request.url)
    assert "SECRET-TOKEN" in str(request.url)
    assert b"42" in request.content  # chat_id travels as a form field


async def test_sends_photo_when_only_still(db_session, seeded, tmp_path: Path) -> None:
    event = _event(db_session, seeded, tmp_path, with_media=False)
    (tmp_path / "stills").mkdir()
    (tmp_path / "stills" / "1.jpg").write_bytes(b"\xff\xd8still")
    event.thumbnail_path = "stills/1.jpg"
    captured: list[httpx.Request] = []
    notifier = TelegramNotifier(
        bot_token="SECRET-TOKEN", chat_id="42", client=_recording_client([], captured), media_root=tmp_path
    )
    await notifier.send(event)
    assert "sendPhoto" in str(captured[0].url)


async def test_sends_text_when_no_media(db_session, seeded, tmp_path: Path) -> None:
    event = _event(db_session, seeded, tmp_path, with_media=False)
    captured: list[httpx.Request] = []
    notifier = TelegramNotifier(
        bot_token="SECRET-TOKEN", chat_id="42", client=_recording_client([], captured), media_root=tmp_path
    )
    await notifier.send(event)
    assert "sendMessage" in str(captured[0].url)


async def test_api_failure_raises_masked_error(db_session, seeded, tmp_path: Path) -> None:
    event = _event(db_session, seeded, tmp_path, with_media=False)
    failing = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _r: httpx.Response(200, json={"ok": False, "description": "chat not found"}))
    )
    notifier = TelegramNotifier(bot_token="SECRET-TOKEN", chat_id="42", client=failing, media_root=tmp_path)
    with pytest.raises(TelegramError) as excinfo:
        await notifier.send(event)
    assert "SECRET-TOKEN" not in str(excinfo.value)
    assert "chat not found" in str(excinfo.value)


async def test_transport_error_never_leaks_the_token(db_session, seeded, tmp_path: Path) -> None:
    event = _event(db_session, seeded, tmp_path, with_media=False)

    def boom(_r: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=_r)

    failing = httpx.AsyncClient(transport=httpx.MockTransport(boom))
    notifier = TelegramNotifier(bot_token="SECRET-TOKEN", chat_id="42", client=failing, media_root=tmp_path)
    with pytest.raises(TelegramError) as excinfo:
        await notifier.send(event)
    assert "SECRET-TOKEN" not in str(excinfo.value)


async def test_offline_event_survives(db_session, seeded, tmp_path: Path) -> None:
    """Matrix row: Telegram down -> the event row is still durable (spec A5.6)."""
    from app.services.events.persist import create_event
    from app.services.alerts.stage import Alert

    camera = Camera(site_id=seeded[0].id, name="C", rtsp_url="rtsp://x/ch1")
    db_session.add(camera)
    db_session.commit()
    alert = Alert(
        rule_id=1, rule_name="r", severity="critical", track_id=1, class_name="person",
        confidence=0.9, zone=None, fired_at=datetime.now(tz=UTC), summary="1 person in frame",
        camera_id=camera.id, bbox=(1, 2, 3, 4), notify=True,
    )
    event = create_event(db_session, alert)

    def boom(_r: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("network is down", request=_r)

    failing = httpx.AsyncClient(transport=httpx.MockTransport(boom))
    notifier = TelegramNotifier(bot_token="T", chat_id="1", client=failing, media_root=tmp_path)
    with pytest.raises(TelegramError):
        await notifier.send(event)
    db_session.expire_all()
    row = db_session.get(Event, event.id)
    assert row is not None, "an offline delivery must never lose the event"
    assert row.summary == "1 person in frame"


async def test_test_message_returns_telegram_response() -> None:
    captured: list[httpx.Request] = []
    client = _recording_client(
        [httpx.Response(200, json={"ok": True, "result": {"message_id": 7}})], captured
    )
    notifier = TelegramNotifier(bot_token="T", chat_id="1", client=client)
    result = await notifier.test_message()
    assert result == {"ok": True, "result": {"message_id": 7}}
    assert "sendMessage" in str(captured[0].url)
```

- [ ] **Step 2: Run to verify it fails**

Run: `$env:PATH = "E:\CamBrain\.venv\Scripts;" + $env:PATH; python -m pytest backend/tests/test_telegram.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.alerts.telegram'`.

- [ ] **Step 3: Implement the three modules**

`notifier.py`:

```python
"""The delivery seam where the product's promise is kept (spec A5.6).

Notification failure must never lose an event: everything before this
protocol is local and durable, and Telegram is the one permitted failure.
"""

from __future__ import annotations

from typing import Protocol

from app.db.models import Event


class Notifier(Protocol):
    """Send one persisted event. Implementations raise on failure."""

    async def send(self, event: Event) -> None: ...
```

`telegram.py`:

```python
"""Telegram transport: sendVideo > sendPhoto > sendMessage, token never logged.

The bot token appears inside Telegram's URL, so every httpx failure is caught
and re-raised as TelegramError with the reason only — a token in an error
string is a token in a log file (SECURITY A3).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from app.core.config import settings
from app.db.models import Event

DEFAULT_CAPTION_LIMIT = 1024


class TelegramError(Exception):
    """A Telegram delivery failed; the message is credential-free."""


class TelegramNotifier:
    """Notifier for a single bot token + chat id (spec A5.6)."""

    def __init__(
        self,
        *,
        bot_token: str,
        chat_id: str,
        client: httpx.AsyncClient | None = None,
        base_url: str | None = None,
        media_root: Path | None = None,
    ) -> None:
        self._token = bot_token
        self._chat_id = chat_id
        self._client = client or httpx.AsyncClient(timeout=15.0)
        self._base_url = (base_url or settings.telegram_api_base).rstrip("/")
        self._media_root = media_root or settings.media_root

    async def send(self, event: Event) -> None:
        """Deliver the event as video, photo, or text — best media first."""
        caption = f"{event.severity.upper()}: {event.summary or 'CamBrain alert'}"
        caption = caption[:DEFAULT_CAPTION_LIMIT]
        clip = self._resolve(event.clip_path)
        still = self._resolve(event.thumbnail_path)
        if clip is not None and clip.is_file():
            await self._call(
                "sendVideo",
                data={"chat_id": self._chat_id, "caption": caption},
                files={"video": (clip.name, clip.read_bytes(), "video/mp4")},
            )
        elif still is not None and still.is_file():
            await self._call(
                "sendPhoto",
                data={"chat_id": self._chat_id, "caption": caption},
                files={"photo": (still.name, still.read_bytes(), "image/jpeg")},
            )
        else:
            await self._call(
                "sendMessage",
                data={"chat_id": self._chat_id, "text": caption},
            )

    async def test_message(self) -> dict[str, Any]:
        """POST /notifiers/test: a real ping, Telegram's response verbatim."""
        return await self._call(
            "sendMessage",
            data={"chat_id": self._chat_id, "text": "CamBrain test message"},
        )

    def _resolve(self, relative: str | None) -> Path | None:
        return (self._root() / relative) if relative else None

    def _root(self) -> Path:
        return self._media_root

    async def _call(self, method: str, *, data: dict[str, str], files: dict | None = None) -> dict[str, Any]:
        url = f"{self._base_url}/bot{self._token}/{method}"
        try:
            response = await self._client.post(url, data=data, files=files)
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise TelegramError(f"telegram {method} failed: {type(exc).__name__}: {exc}") from None
        if not payload.get("ok"):
            raise TelegramError(f"telegram {method} rejected: {payload.get('description', 'unknown error')}")
        return payload
```

Guard the token leak: httpx exception text can embed the URL. The `f"...{exc}"` above may include it — replace the HTTPError branch with:

```python
        except httpx.HTTPError as exc:
            raise TelegramError(f"telegram {method} failed: {type(exc).__name__}") from None
        except ValueError as exc:
            raise TelegramError(f"telegram {method} returned invalid JSON: {type(exc).__name__}") from None
```

so the message contains only the exception class name, never `str(exc)`.

`whatsapp.py`:

```python
"""WhatsApp adapter stub behind the same interface (spec A5.6).

Deferred deliberately: Meta business verification plus approved templates
would stall the MVP on setup friction. The protocol is what ships now, so
adding WhatsApp later touches one file.
"""

from __future__ import annotations

from app.db.models import Event


class WhatsAppNotifier:
    """Not implemented (Phase 5+). Present so the seam is real, not planned."""

    async def send(self, event: Event) -> None:
        """Raise: WhatsApp delivery does not exist yet."""
        raise NotImplementedError("WhatsApp ships after MVP verification (spec A5.6)")
```

- [ ] **Step 4: Run to verify it passes**

Run: `$env:PATH = "E:\CamBrain\.venv\Scripts;" + $env:PATH; python -m pytest backend/tests/test_telegram.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

Message (`feat(alerts): notifier protocol, Telegram transport, WhatsApp stub`):
body: `Telegram sends the clip as video when one exists, else the still, else text — the owner asked for exactly this egress and nothing else (spec A5.6, arch A1). Every httpx failure is re-raised credential-free because the bot token lives in the request URL.`

---

### Task 8: Notifier secrets at rest + a real `/notifiers/test`

**Files:**
- Modify: `backend/app/api/routers/settings.py`
- Modify: `backend/app/api/schemas.py` (`NotifierOut.has_token`)
- Modify: `backend/tests/test_api_settings.py` (extend — if the file is named differently, find it with `Select-String -Path E:\CamBrain\backend\tests\*.py -Pattern "notifiers"` and extend that file)
- Test: same file, new cases below

**Interfaces:**
- Consumes: `encrypt`/`decrypt` (`app.core.crypto`), `TelegramNotifier` (T7), notifier CRUD (exists).
- Produces: GET `/notifiers` never returns a token — entries carry `has_token: bool`; POST/PATCH accept `config.bot_token` and store `config.bot_token_enc` (Fernet text); POST `/notifiers/test` → `200 {"ok": true, "response": {...}}` or `200 {"ok": false, "error": "..."}` (mirrors the camera-test contract). Tasks 9/17 rely on `has_token`.

- [ ] **Step 1: Write the failing tests** — append:

```python
def test_notifier_token_is_encrypted_and_masked(client, db_session, seeded) -> None:
    res = client.post(
        "/api/v1/notifiers",
        json={"kind": "telegram", "enabled": True, "config": {"chat_id": "42", "bot_token": "SECRET-TOKEN"}},
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert "bot_token" not in json.dumps(body) and "SECRET-TOKEN" not in json.dumps(body)
    assert body["has_token"] is True

    got = client.get("/api/v1/notifiers")
    assert "SECRET-TOKEN" not in got.text
    assert got.json()[0]["has_token"] is True

    from app.core.crypto import decrypt

    site, _a, _v = seeded
    db_session.expire_all()
    raw = db_session.get(type(site), site.id).notifier_config
    assert raw[0]["config"]["bot_token_enc"] != "SECRET-TOKEN"
    assert decrypt(raw[0]["config"]["bot_token_enc"]) == "SECRET-TOKEN"


def test_notifier_patch_without_token_keeps_existing(client, db_session, seeded) -> None:
    client.post(
        "/api/v1/notifiers",
        json={"kind": "telegram", "enabled": True, "config": {"chat_id": "42", "bot_token": "SECRET-TOKEN"}},
    )
    res = client.patch("/api/v1/notifiers/0", json={"enabled": False, "config": {"chat_id": "43"}})
    assert res.status_code == 200
    assert res.json()["has_token"] is True, "a config without a token must not wipe the old one"
    from app.core.crypto import decrypt

    site, _a, _v = seeded
    db_session.expire_all()
    raw = db_session.get(type(site), site.id).notifier_config
    assert decrypt(raw[0]["config"]["bot_token_enc"]) == "SECRET-TOKEN"
    assert raw[0]["config"]["chat_id"] == "43"


def test_notifier_test_endpoint_sends_real_message(client, monkeypatch) -> None:
    from app.api.routers import settings as settings_router

    class FakeNotifier:
        async def send(self, event):  # noqa: ANN001, ARG002
            return None

        async def test_message(self):
            return {"ok": True, "result": {"message_id": 7}}

    monkeypatch.setattr(settings_router, "_build_notifier", lambda _entry: FakeNotifier())
    client.post(
        "/api/v1/notifiers",
        json={"kind": "telegram", "enabled": True, "config": {"chat_id": "42", "bot_token": "T"}},
    )
    res = client.post("/api/v1/notifiers/test")
    assert res.status_code == 200 and res.json()["ok"] is True
    assert res.json()["response"] == {"ok": True, "result": {"message_id": 7}}


def test_notifier_test_endpoint_reports_failure(client, monkeypatch) -> None:
    from app.api.routers import settings as settings_router
    from app.services.alerts.telegram import TelegramError

    def boom(_entry):
        raise TelegramError("telegram sendMessage rejected: chat not found")

    monkeypatch.setattr(settings_router, "_build_notifier", lambda _entry: boom(None))
    client.post(
        "/api/v1/notifiers",
        json={"kind": "telegram", "enabled": True, "config": {"chat_id": "42", "bot_token": "T"}},
    )
    res = client.post("/api/v1/notifiers/test")
    assert res.status_code == 200 and res.json()["ok"] is False
    assert "chat not found" in res.json()["error"]
```

(The failure test's `lambda _entry: boom(None)` is a deliberate call-on-construct; simpler: `monkeypatch.setattr(settings_router, "_build_notifier", boom)` — use that form.)

- [ ] **Step 2: Run to verify it fails**

Run: `$env:PATH = "E:\CamBrain\.venv\Scripts;" + $env:PATH; python -m pytest backend/tests -k notifier -v`
Expected: FAIL — `has_token` missing / plaintext token returned / 501 from the test endpoint.

- [ ] **Step 3: Implement**

`schemas.py` — `NotifierOut` gains:

```python
    has_token: bool = False
```

`settings.py` changes:

```python
from app.core.crypto import decrypt, encrypt
from app.services.alerts.telegram import TelegramError, TelegramNotifier


def _seal(config: dict[str, Any]) -> dict[str, Any]:
    """Encrypt a plaintext bot_token into bot_token_enc; pass the rest through."""
    out = {k: v for k, v in config.items() if k != "bot_token"}
    token = config.get("bot_token")
    if isinstance(token, str) and token:
        out["bot_token_enc"] = encrypt(token)
    return out


def _merge_patch(existing: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Patch a config without ever dropping the sealed token (D11)."""
    merged = dict(existing)
    sealed = merged.pop("bot_token_enc", None)
    merged.update(patch) if "bot_token" not in patch else None
    out = _seal({**{k: v for k, v in merged.items() if k != "bot_token"}, **({"bot_token": patch["bot_token"]} if patch.get("bot_token") else {})})
    if sealed is not None and "bot_token_enc" not in out:
        out["bot_token_enc"] = sealed
    return out
```

Replace `_merge_patch` with this simpler, correct form:

```python
def _merge_patch(existing: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing)
    sealed = merged.pop("bot_token_enc", None)
    merged.update(patch)
    out = _seal(merged)
    if sealed is not None and "bot_token_enc" not in out:
        out["bot_token_enc"] = sealed
    return out
```

`_notifier_out` gains `has_token="bot_token_enc" in dict(raw_config)` (pass `bool(entry.get("config", {}).get("bot_token_enc"))` — config is the entry's config dict).

`create_notifier`: `entry = {"kind": body.kind, "enabled": body.enabled, "config": _seal(body.config)}`.
`patch_notifier`: when `config` present: `entry["config"] = _merge_patch(entry.get("config", {}), updates["config"])`.

Test endpoint:

```python
def _build_notifier(entry: dict[str, Any]) -> TelegramNotifier:
    """Construct a TelegramNotifier from a stored notifier_config entry."""
    config = entry.get("config", {})
    token = decrypt(str(config["bot_token_enc"]))
    return TelegramNotifier(bot_token=token, chat_id=str(config.get("chat_id", "")))


@router.post("/notifiers/test")
async def test_notifier(claims: AdminDep, db: DbSessionDep) -> dict[str, Any]:
    """Send a real test message; Telegram's response verbatim (API ASystem)."""
    entries = [e for e in _notifiers(_site(db, claims)) if e.get("enabled", True)]
    if not entries:
        return {"ok": False, "error": "no enabled notifiers configured"}
    try:
        response = await _build_notifier(entries[0]).test_message()
    except TelegramError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "response": response}
```

Add `from typing import Any` (already present) and make sure `get` import includes nothing unused; run ruff after.

- [ ] **Step 4: Run to verify it passes**

Run: `$env:PATH = "E:\CamBrain\.venv\Scripts;" + $env:PATH; python -m pytest backend/tests -k notifier -v; if ($?) { python -m ruff check backend; if ($?) { python -m mypy backend } }`
Expected: all notifier tests pass (old CRUD tests keep passing — `has_token` is additive); ruff/mypy clean.

- [ ] **Step 5: Commit**

Message (`feat(api): seal notifier tokens at rest and send real test messages`):
body: `The bot token is Fernet-sealed inside notifier_config (DATABASE A6) and masked from every response (spec A7.4); a config that has never delivered is not a working config, so /notifiers/test now really sends (API ASystem).`

---

### Task 9: `DeliveryWorker` — durable retry with capped backoff + status stats

**Files:**
- Create: `backend/app/services/alerts/delivery.py`
- Modify: `backend/app/api/routers/system.py` (`events_today` / `alerts_sent` / `alerts_failed`)
- Test: `backend/tests/test_delivery.py`

**Interfaces:**
- Consumes: `mark_delivery` (T4), `Event.last_attempt_at` (T4/`p5a`), notifier config (T8), `Event.stats` conventions.
- Produces: `DeliveryWorker(*, session_factory=SessionLocal, notifier_for: Callable[[int], list[Notifier]] | None = None, now: Callable[[], datetime] = _utcnow, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep, interval_s: float = 10.0, backoff_cap_s: float = 3600.0)` with `async def sweep_once(self) -> int` (delivers due events, returns count) and `async def run(self) -> None` (loop until cancelled) and `async def close(self) -> None`; `backoff_s(attempts: int, *, cap_s: float = 3600.0) -> float`; system status gains `stats.events_today`/`stats.alerts_sent`/`stats.alerts_failed`. Task 13 starts `run()`.

Retry semantics (D4 + DATABASE §8): rows with `delivery_status in ('pending','failed')` whose `last_attempt_at IS NULL OR last_attempt_at + backoff <= now` are due. Success → `sent` + `delivered_at`. Failure → attempts+1, `last_delivery_error`, status stays `pending` (D4: retry forever, never give up); after 5 attempts status flips to `failed` for visibility but a later sweep still retries `failed` rows — wait, that contradicts. Resolution: **status stays `pending` while retrying; `failed` is set only when no notifier is configured for the site** (misconfiguration, human fix required). Backoff = `min(2 ** attempts * 5, 3600)` seconds (5s → 10s → … capped 1h).

- [ ] **Step 1: Write the failing tests** — `backend/tests/test_delivery.py`:

```python
"""DeliveryWorker: durable retry, capped backoff, notifier plumbing."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.services.alerts.delivery import DeliveryWorker, backoff_s


def _pending_event(db_session, seeded, *, attempts: int = 0, last_attempt: datetime | None = None):
    from app.db.models import Event

    site, _admin, _viewer = seeded
    event = Event(
        site_id=site.id,
        camera_id=None,
        rule_id=None,
        triggered_by="system",
        started_at=datetime(2026, 10, 6, 22, 0),
        severity="critical",
        summary="1 person in Loading dock",
        delivery_status="pending",
        delivery_attempts=attempts,
        last_attempt_at=last_attempt,
    )
    db_session.add(event)
    db_session.commit()
    return event


class FakeNotifier:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.sent: list[int] = []

    async def send(self, event) -> None:  # noqa: ANN001
        if self.fail:
            raise RuntimeError("telegram network is down")
        self.sent.append(event.id)


def test_backoff_grows_and_caps() -> None:
    """Matrix: exponential backoff capped at one hour (D4)."""
    assert backoff_s(0) == 5.0
    assert backoff_s(1) == 10.0
    assert backoff_s(2) == 20.0
    assert backoff_s(20) == 3600.0


async def test_sweep_delivers_due_event(db_session, seeded) -> None:
    event = _pending_event(db_session, seeded)
    notifier = FakeNotifier()
    worker = DeliveryWorker(
        session_factory=lambda: db_session,
        notifier_for=lambda _site_id: [notifier],
    )
    delivered = await worker.sweep_once()
    assert delivered == 1 and notifier.sent == [event.id]
    db_session.expire_all()
    row = db_session.get(type(event), event.id)
    assert row.delivery_status == "sent" and row.delivery_attempts == 1
    assert row.delivered_at is not None and row.last_attempt_at is not None


async def test_failed_delivery_retries_forever_with_backoff(db_session, seeded) -> None:
    event = _pending_event(db_session, seeded, attempts=3)
    worker = DeliveryWorker(
        session_factory=lambda: db_session,
        notifier_for=lambda _site_id: [FakeNotifier(fail=True)],
    )
    assert await worker.sweep_once() == 0
    db_session.expire_all()
    row = db_session.get(type(event), event.id)
    assert row.delivery_status == "pending", "offline retries forever (D4)"
    assert row.delivery_attempts == 4
    assert "network is down" in (row.last_delivery_error or "")
    assert row.last_attempt_at is not None


async def test_backoff_delays_the_next_attempt(db_session, seeded) -> None:
    now = datetime(2026, 10, 6, 22, 0, tzinfo=UTC)
    event = _pending_event(db_session, seeded, attempts=1, last_attempt=now.replace(tzinfo=None))
    calls: list[Any] = []
    worker = DeliveryWorker(
        session_factory=lambda: db_session,
        notifier_for=lambda _site_id: calls.append("x") or [FakeNotifier()],
        now=lambda: now,
    )
    assert await worker.sweep_once() == 0, "attempt 1 backs off 10s; only 3s elapsed"
    assert calls == []
    worker_now = lambda: now + timedelta(seconds=11)  # noqa: E731
    worker = DeliveryWorker(
        session_factory=lambda: db_session,
        notifier_for=lambda _site_id: calls.append("x") or [FakeNotifier()],
        now=worker_now,
    )
    assert await worker.sweep_once() == 1


async def test_no_notifier_marks_failed(db_session, seeded) -> None:
    event = _pending_event(db_session, seeded)
    worker = DeliveryWorker(
        session_factory=lambda: db_session,
        notifier_for=lambda _site_id: [],
    )
    await worker.sweep_once()
    db_session.expire_all()
    row = db_session.get(type(event), event.id)
    assert row.delivery_status == "failed"
    assert row.last_delivery_error and "notifier" in row.last_delivery_error


async def test_run_loop_stops_on_close(db_session, seeded) -> None:
    import asyncio

    _pending_event(db_session, seeded)
    worker = DeliveryWorker(
        session_factory=lambda: db_session,
        notifier_for=lambda _site_id: [FakeNotifier()],
        interval_s=0.01,
    )
    task = asyncio.create_task(worker.run())
    await asyncio.sleep(0.05)
    await worker.close()
    with pytest.raises(asyncio.CancelledError):
        await task
```

- [ ] **Step 2: Run to verify it fails**

Run: `$env:PATH = "E:\CamBrain\.venv\Scripts;" + $env:PATH; python -m pytest backend/tests/test_delivery.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.alerts.delivery'`.

Also write the system-stats failing test — append to the system/status test file (find it: `Select-String -Path E:\CamBrain\backend\tests\*.py -Pattern "system/status"`):

```python
def test_status_reports_delivery_stats(client, db_session, seeded) -> None:
    from datetime import datetime, timezone

    from app.db.models import Event

    site, _a, _v = seeded
    today = datetime.now(tz=timezone.utc).replace(tzinfo=None)
    for status in ("sent", "sent", "pending", "failed"):
        db_session.add(
            Event(
                site_id=site.id,
                camera_id=None,
                rule_id=None,
                triggered_by="system",
                started_at=today,
                severity="warning",
                summary="s",
                delivery_status=status,
            )
        )
    db_session.commit()
    res = client.get("/api/v1/system/status")
    stats = res.json()["stats"]
    assert stats["events_today"] == 4
    assert stats["alerts_sent"] == 2
    assert stats["alerts_failed"] == 1
```

Run: `$env:PATH = "E:\CamBrain\.venv\Scripts;" + $env:PATH; python -m pytest backend/tests -k "status" -v` → FAIL (`KeyError: 'events_today'`).

- [ ] **Step 3: Implement**

`delivery.py`:

```python
"""Durable delivery sweep: DB poll, exponential backoff capped at 1h (D4, A5.6).

Work is discovered in the database, never a queue — an asyncio.Queue dies
with the process and is not thread-safe from the camera loops, while a
pending row survives restarts exactly as the event itself does.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from sqlalchemy import select

from app.db.models.event import Event
from app.db.models.site import Site
from app.db.session import SessionLocal
from app.services.alerts.notifier import Notifier
from app.services.events.persist import mark_delivery

RetryableStatus = ("pending", "failed")


def backoff_s(attempts: int, *, cap_s: float = 3600.0) -> float:
    """min(5 * 2**attempts, cap) — 5s, 10s, 20s … capped at one hour."""
    return float(min(5 * (2 ** max(attempts, 0)), cap_s))


def _utcnow() -> datetime:
    return datetime.now(tz=UTC).replace(tzinfo=None)


def _build_notifiers(config: dict) -> list[Notifier]:
    """Notifiers from one stored site config; only Telegram constructs today."""
    from app.core.crypto import decrypt
    from app.services.alerts.telegram import TelegramNotifier
    from app.services.alerts.whatsapp import WhatsAppNotifier

    out: list[Notifier] = []
    for entry in config.get("notifiers", []) if isinstance(config, dict) else []:
        if not entry.get("enabled", True):
            continue
        if entry.get("kind") == "telegram":
            token = (entry.get("config") or {}).get("bot_token_enc")
            if token:
                out.append(
                    TelegramNotifier(
                        bot_token=decrypt(token),
                        chat_id=str((entry.get("config") or {}).get("chat_id", "")),
                    )
                )
        elif entry.get("kind") == "whatsapp":
            out.append(WhatsAppNotifier())
    return out


class DeliveryWorker:
    """Sweeps due events to their site's notifiers (spec A5.6, arch A7)."""

    def __init__(
        self,
        *,
        session_factory: Callable[[], Any] = SessionLocal,
        notifier_for: Callable[[int], list[Notifier]] | None = None,
        now: Callable[[], datetime] = _utcnow,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        interval_s: float = 10.0,
        backoff_cap_s: float = 3600.0,
        batch: int = 25,
    ) -> None:
        self._session_factory = session_factory
        self._notifier_for = notifier_for or self._default_notifiers
        self._now = now
        self._sleep = sleep
        self._interval_s = interval_s
        self._cap_s = backoff_cap_s
        self._batch = batch
        self._stopped = asyncio.Event()

    def _default_notifiers(self, site_id: int) -> list[Notifier]:
        db = self._session_factory()
        try:
            site = db.get(Site, site_id)
            return _build_notifiers(site.notifier_config or {}) if site else []
        finally:
            db.close()

    async def sweep_once(self) -> int:
        """Deliver every due pending/failed event once; returns delivered count."""
        db = self._session_factory()
        delivered = 0
        try:
            now = self._now()
            events = (
                db.execute(
                    select(Event)
                    .where(Event.delivery_status.in_(RetryableStatus))
                    .order_by(Event.id)
                    .limit(self._batch)
                )
                .scalars()
                .all()
            )
            for event in events:
                if event.last_attempt_at is not None:
                    elapsed = (now - event.last_attempt_at).total_seconds()
                    if elapsed < backoff_s(event.delivery_attempts, cap_s=self._cap_s):
                        continue
                notifiers = self._notifier_for(event.site_id)
                if not notifiers:
                    mark_delivery(
                        db,
                        event.id,
                        status="failed",
                        attempts=event.delivery_attempts + 1,
                        error="no enabled notifier configured for this site",
                        attempted=now,
                    )
                    continue
                try:
                    for notifier in notifiers:
                        await notifier.send(event)
                except Exception as exc:  # noqa: BLE001 - one failure, durable retry
                    mark_delivery(
                        db,
                        event.id,
                        status="pending",
                        attempts=event.delivery_attempts + 1,
                        error=f"{type(exc).__name__}: {exc}",
                        attempted=now,
                    )
                else:
                    mark_delivery(
                        db,
                        event.id,
                        status="sent",
                        attempts=event.delivery_attempts + 1,
                        error=None,
                        delivered=now,
                        attempted=now,
                    )
                    delivered += 1
        finally:
            db.close()
        return delivered

    async def run(self) -> None:
        """Poll loop until close() is called (started by the runtime, T13)."""
        while not self._stopped.is_set():
            try:
                await self.sweep_once()
            except Exception:  # noqa: BLE001 - the loop must survive anything
                pass
            try:
                await self._wait()
            except asyncio.CancelledError:
                break

    async def _wait(self) -> None:
        try:
            await asyncio.wait_for(self._stopped.wait(), timeout=self._interval_s)
        except TimeoutError:
            return

    async def close(self) -> None:
        """Stop the loop; pending rows stay pending for the next run."""
        self._stopped.set()
```

Note: `mark_delivery(..., error=None)` must *clear* the error on success — Task 4's `mark_delivery` only writes when `error is not None`. Fix Task 4's function when implementing this task (or write a sentinel): change `if error is not None:` to `if error is not None or status == "sent": event.last_delivery_error = error` — i.e., clearing on success. Simplest correct form inside `mark_delivery`:

```python
    event.last_delivery_error = error
```
(assign unconditionally; `attempts`/`delivered`/`attempted` keep their `is not None` guards).

`system.py` stats (inside `status_route`, before the return):

```python
    from datetime import datetime, timezone

    from app.db.models.event import Event

    today = datetime.now(tz=timezone.utc).replace(tzinfo=None).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    events_today = db.execute(
        select(func.count(Event.id)).where(Event.site_id == site_id, Event.started_at >= today)
    ).scalar_one()
    alerts_sent = db.execute(
        select(func.count(Event.id)).where(
            Event.site_id == site_id, Event.started_at >= today, Event.delivery_status == "sent"
        )
    ).scalar_one()
    alerts_failed = db.execute(
        select(func.count(Event.id)).where(
            Event.site_id == site_id, Event.started_at >= today, Event.delivery_status == "failed"
        )
    ).scalar_one()
```

and the returned `"stats"` dict gains `"events_today": events_today, "alerts_sent": alerts_sent, "alerts_failed": alerts_failed` (alongside the existing `cameras_total`/`retention_days`). Add `from sqlalchemy import func` to the imports (move the `from datetime import...` to module top with `import time`).

- [ ] **Step 4: Run to verify it passes**

Run: `$env:PATH = "E:\CamBrain\.venv\Scripts;" + $env:PATH; python -m pytest backend/tests/test_delivery.py -v; if ($?) { python -m pytest backend/tests -k "status or notifier" -v }; if ($?) { python -m ruff check backend; if ($?) { python -m mypy backend } }`
Expected: all pass; ruff/mypy clean.

- [ ] **Step 5: Commit**

Message (`feat(alerts): durable delivery worker with capped backoff`):
body: `Work is discovered in the database, never a queue: a pending row survives restarts and an offline Telegram delays delivery by 5s-10s-20s... capped at 1h, retrying forever (spec A5.6, D4). /system/status now reports events_today/alerts_sent/alerts_failed so "did it send" is answerable at 2am (API ASystem).`

---

### Task 10: Real clip streaming (`GET /events/{id}/clip`)

**Files:**
- Modify: `backend/app/api/routers/events.py`
- Test: extend the events router test file (`Select-String -Path E:\CamBrain\backend\tests\*.py -Pattern "events/\{.*\}/clip|clip not found"` to locate)

**Interfaces:**
- Consumes: `settings.media_root`, `Event.clip_path`.
- Produces: `GET /events/{id}/clip` → `FileResponse(media_type="video/mp4", content_disposition_type="inline", filename=f"event-{id}.mp4")` with `Accept-Ranges`/Range support via Starlette's FileResponse; 404 when missing/pruned/escaping (same resolve guard as thumbnail). API.md L356 promises inline + Range.

- [ ] **Step 1: Write the failing test** — append:

```python
def test_clip_route_serves_real_file(client, db_session, seeded, tmp_path) -> None:
    from datetime import datetime

    from app.core.config import settings as app_settings
    from app.db.models import Event

    site, _a, _v = seeded
    (tmp_path / "clips").mkdir()
    (tmp_path / "clips" / "1.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64)
    event = Event(
        site_id=site.id, camera_id=None, rule_id=None, triggered_by="system",
        started_at=datetime(2026, 10, 6, 22, 0), severity="critical", summary="s",
        clip_path="clips/1.mp4", clip_bytes=76,
    )
    db_session.add(event)
    db_session.commit()
    monkey_media = tmp_path  # the route resolves under settings.media_root
    res = client.get(f"/api/v1/events/{event.id}/clip")
    assert res.status_code == 404  # until Step 3 lands: media_root is not tmp_path yet
```

Realise the media-root problem: use `monkeypatch.setattr(app_settings, "media_root", tmp_path)` so resolution finds the file (the thumbnail test in Phase 4 already does this if present — follow its pattern; `Select-String -Path E:\CamBrain\backend\tests\*.py -Pattern "media_root"` shows it). Then:

- `assert res.status_code == 200 and res.headers["content-type"] == "video/mp4"`
- `assert res.headers["content-disposition"].startswith("inline")`
- `assert res.content.startswith(b"\x00\x00\x00\x18ftyp")`
- `partial = client.get(f"/api/v1/events/{event.id}/clip", headers={"Range": "bytes=0-7"})` → `assert partial.status_code == 206`

Also a prune/missing case: `clip_path="clips/999.mp4"` → 404.

- [ ] **Step 2: Run to verify it fails**

Run: `$env:PATH = "E:\CamBrain\.venv\Scripts;" + $env:PATH; python -m pytest backend/tests -k "clip" -v`
Expected: FAIL — 404 (route still raises unconditionally).

- [ ] **Step 3: Implement** — replace the tail of `get_clip`:

```python
    event = _repo(db, claims).get(event_id)
    if event is None or event.clip_path is None:
        raise NotFoundError("clip not found")
    root = settings.media_root.resolve()
    path = Path(event.clip_path)
    resolved = path.resolve() if path.is_absolute() else (root / path).resolve()
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise NotFoundError("clip not found")
    return FileResponse(
        resolved,
        media_type="video/mp4",
        content_disposition_type="inline",
        filename=f"event-{event_id}.mp4",
    )
```

Change the return annotation from `Response` to `FileResponse` and update the docstring ("Phase 4 wires real storage" → "Streams the stored clip inline with Range support (API §Events)").

- [ ] **Step 4: Run to verify it passes**

Run: `$env:PATH = "E:\CamBrain\.venv\Scripts;" + $env:PATH; python -m pytest backend/tests -k "clip or thumbnail" -v; if ($?) { python -m ruff check backend; if ($?) { python -m mypy backend } }`
Expected: pass; ruff/mypy clean.

- [ ] **Step 5: Commit**

Message (`feat(events): stream stored clips inline with range support`):
body: `FileResponse gives the browser seeking for free (API AEvents); the path resolves inside media_root only, so an escaping clip_path is a 404, never a served file (SECURITY A6.2).`

---

### Task 11: Retention sweeps — batched deletes, file unlink, orphan reclamation

**Files:**
- Create: `backend/app/services/events/retention.py`
- Test: `backend/tests/test_retention.py`

**Interfaces:**
- Consumes: `settings.media_root`, `Site.retention_days` (default 7).
- Produces: `prune_events(db, *, site_id: int, now: datetime | None = None, batch: int = 500, media_root: Path | None = None) -> int` (deletes events older than retention, unlinking clip/still first, returns rows deleted); `sweep_orphans(db, *, site_id: int, media_root: Path | None = None, min_age_s: float = 86400.0, now: datetime | None = None) -> int` (files older than 24h with no matching row); `async def retention_loop(*, session_factory=SessionLocal, sleep=..., interval_s=86400.0) -> None` / `RetentionRunner` with `run()`+`close()` for Task 13. Task 13 starts it.

Batching rule (DATABASE §6.5): delete **ids** in pages of 500 (`SELECT id ... LIMIT 500`), unlink each file **before** committing the row delete, sleep ~0.05s between batches.

- [ ] **Step 1: Write the failing tests** — `backend/tests/test_retention.py`:

```python
"""Retention: batched age deletes, unlink-before-commit, orphan sweep."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from app.db.models import Camera, Event, Site
from app.services.events.retention import prune_events, sweep_orphans


def _site(db, **overrides) -> Site:
    site = Site(name="s", slug="s", timezone="UTC", **overrides)
    db.add(site)
    db.commit()
    return site


def _event(db, site: Site, started_at: datetime, *, clip: str | None = None, thumb: str | None = None) -> Event:
    event = Event(
        site_id=site.id, camera_id=None, rule_id=None, triggered_by="system",
        started_at=started_at, severity="warning", summary="s",
        clip_path=clip, thumbnail_path=thumb,
    )
    db.add(event)
    db.commit()
    return event


def test_prune_deletes_only_events_past_retention(db_session, tmp_path: Path) -> None:
    site = _site(db_session)
    now = datetime(2026, 10, 6, 12, 0)
    old = _event(db_session, site, now - timedelta(days=8))
    fresh = _event(db_session, site, now - timedelta(days=1))
    deleted = prune_events(db_session, site_id=site.id, now=now, media_root=tmp_path)
    assert deleted == 1
    db_session.expire_all()
    assert db_session.get(Event, old.id) is None
    assert db_session.get(Event, fresh.id) is not None


def test_prune_unlinks_clip_and_still_before_deleting_row(db_session, tmp_path: Path) -> None:
    site = _site(db_session)
    (tmp_path / "clips").mkdir()
    (tmp_path / "stills").mkdir()
    (tmp_path / "clips" / "1.mp4").write_bytes(b"v")
    (tmp_path / "stills" / "1.jpg").write_bytes(b"j")
    now = datetime(2026, 10, 6, 12, 0)
    _event(
        db_session, site, now - timedelta(days=9),
        clip="clips/1.mp4", thumb="stills/1.jpg",
    )
    assert prune_events(db_session, site_id=site.id, now=now, media_root=tmp_path) == 1
    assert not (tmp_path / "clips" / "1.mp4").exists()
    assert not (tmp_path / "stills" / "1.jpg").exists()


def test_prune_batches_and_respects_per_site_retention(db_session, tmp_path: Path) -> None:
    site_a = _site(db_session, retention_days=1)
    site_b = _site(db_session, retention_days=30)
    now = datetime(2026, 10, 6, 12, 0)
    for _ in range(700):
        _event(db_session, site_a, now - timedelta(days=5))
    _event(db_session, site_b, now - timedelta(days=5))
    deleted = prune_events(db_session, site_id=site_a.id, now=now, media_root=tmp_path, batch=500)
    assert deleted == 700, "two batches of 500 + 200, all one site's rows"
    db_session.expire_all()
    kept = db_session.execute(
        __import__("sqlalchemy").select(Event).where(Event.site_id == site_b.id)
    ).scalars().all()
    assert len(kept) == 1, "retention never crosses a tenant boundary"


def test_retention_days_zero_means_nothing_pruned(db_session, tmp_path: Path) -> None:
    site = _site(db_session, retention_days=0)
    now = datetime(2026, 10, 6, 12, 0)
    _event(db_session, site, now - timedelta(days=365))
    assert prune_events(db_session, site_id=site.id, now=now, media_root=tmp_path) == 0


def test_orphan_sweep_removes_old_unreferenced_files(db_session, tmp_path: Path) -> None:
    site = _site(db_session)
    (tmp_path / "clips").mkdir()
    orphan = tmp_path / "clips" / "999.mp4"
    orphan.write_bytes(b"v")
    import os

    stale = now = datetime(2026, 10, 6, 12, 0)
    old_ts = (stale - timedelta(hours=25)).timestamp()
    os.utime(orphan, (old_ts, old_ts))
    fresh = tmp_path / "clips" / "1000.mp4"
    fresh.write_bytes(b"v")
    removed = sweep_orphans(db_session, site_id=site.id, media_root=tmp_path, now=stale)
    assert removed == 1 and not orphan.exists() and fresh.exists()


def test_orphan_sweep_keeps_files_with_a_row(db_session, tmp_path: Path) -> None:
    site = _site(db_session)
    (tmp_path / "clips").mkdir()
    kept = tmp_path / "clips" / "1.mp4"
    kept.write_bytes(b"v")
    import os

    old = datetime(2026, 10, 6, 12, 0) - timedelta(hours=40)
    os.utime(kept, (old.timestamp(), old.timestamp()))
    _event(db_session, site, datetime(2026, 10, 1), clip="clips/1.mp4")
    assert sweep_orphans(db_session, site_id=site.id, media_root=tmp_path, now=datetime(2026, 10, 6, 12, 0)) == 0
    assert kept.exists()


def test_missing_files_never_break_a_prune(db_session, tmp_path: Path) -> None:
    site = _site(db_session)
    now = datetime(2026, 10, 6, 12, 0)
    _event(db_session, site, now - timedelta(days=9), clip="clips/gone.mp4", thumb="stills/gone.jpg")
    assert prune_events(db_session, site_id=site.id, now=now, media_root=tmp_path) == 1
```

(The `__import__("sqlalchemy").select` line — write it properly: `from sqlalchemy import select` at module top.)

- [ ] **Step 2: Run to verify it fails**

Run: `$env:PATH = "E:\CamBrain\.venv\Scripts;" + $env:PATH; python -m pytest backend/tests/test_retention.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.events.retention'`.

- [ ] **Step 3: Implement** `backend/app/services/events/retention.py`:

```python
"""Retention: events age out in batches, files die with their rows (A6.5, A9).

Batches of 500 ids keep write locks short on a busy box; each file is
unlinked before its row commits, so a crash leaves an orphan the sweep
reclaims rather than a row pointing at nothing.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models.event import Event
from app.db.models.site import Site
from app.db.session import SessionLocal

DEFAULT_INTERVAL_S = 86_400.0
ORPHAN_MIN_AGE_S = 86_400.0


def _now(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(tz=UTC).replace(tzinfo=None)
    return now.astimezone(UTC).replace(tzinfo=None) if now.tzinfo else now


def _unlink(root: Path, relative: str | None) -> None:
    if not relative:
        return
    path = Path(relative)
    resolved = path.resolve() if path.is_absolute() else (root / path).resolve()
    with contextlib.suppress(OSError):
        if resolved.is_relative_to(root.resolve()) and resolved.is_file():
            resolved.unlink()


def prune_events(
    db: Session,
    *,
    site_id: int,
    now: datetime | None = None,
    batch: int = 500,
    media_root: Path | None = None,
) -> int:
    """Delete this site's events older than its retention; return rows removed."""
    site = db.get(Site, site_id)
    if site is None or site.retention_days <= 0:
        return 0
    root = (media_root or settings.media_root).resolve()
    cutoff = _now(now) - timedelta(days=site.retention_days)
    total = 0
    while True:
        ids = (
            db.execute(
                select(Event.id)
                .where(Event.site_id == site_id, Event.started_at < cutoff)
                .order_by(Event.id)
                .limit(batch)
            )
            .scalars()
            .all()
        )
        if not ids:
            break
        for event_id in ids:
            event = db.get(Event, event_id)
            if event is None:
                continue
            _unlink(root, event.clip_path)
            _unlink(root, event.thumbnail_path)
        db.execute(delete(Event).where(Event.id.in_(ids)))
        db.commit()
        total += len(ids)
        if len(ids) < batch:
            break
        time.sleep(0.05)
    return total


def sweep_orphans(
    db: Session,
    *,
    site_id: int,
    media_root: Path | None = None,
    min_age_s: float = ORPHAN_MIN_AGE_S,
    now: datetime | None = None,
) -> int:
    """Remove media files older than min_age with no matching event row."""
    root = (media_root or settings.media_root).resolve()
    stamp = _now(now).timestamp() - min_age_s
    referenced = {
        p for folder in ("clips", "stills")
        for p in _referenced(db, site_id, folder)
    }
    removed = 0
    for folder in ("clips", "stills"):
        directory = root / folder
        if not directory.is_dir():
            continue
        for path in directory.iterdir():
            if not path.is_file() or path.name in referenced:
                continue
            try:
                if path.stat().st_mtime > stamp:
                    continue
                path.unlink()
                removed += 1
            except OSError:
                continue
    return removed


def _referenced(db: Session, site_id: int, folder: str) -> set[str]:
    """Basename set of clip/still paths this site's events still point at."""
    rows = db.execute(
        select(Event.clip_path, Event.thumbnail_path).where(Event.site_id == site_id)
    ).all()
    names: set[str] = set()
    prefix = f"{folder}/"
    for clip, thumb in rows:
        for value in (clip, thumb):
            if value and value.startswith(prefix):
                names.add(value.removeprefix(prefix))
    return names


class RetentionRunner:
    """Daily prune + orphan sweep for one site (started by the runtime, T13)."""

    def __init__(
        self,
        *,
        site_id: int,
        session_factory: Callable[[], Session] = SessionLocal,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        interval_s: float = DEFAULT_INTERVAL_S,
        media_root: Path | None = None,
    ) -> None:
        self._site_id = site_id
        self._session_factory = session_factory
        self._sleep = sleep
        self._interval_s = interval_s
        self._media_root = media_root
        self._stopped = asyncio.Event()

    async def sweep_once(self) -> int:
        """One prune + one orphan sweep; returns rows deleted."""
        db = self._session_factory()
        try:
            deleted = prune_events(db, site_id=self._site_id, media_root=self._media_root)
            sweep_orphans(db, site_id=self._site_id, media_root=self._media_root)
            return deleted
        finally:
            db.close()

    async def run(self) -> None:
        """Loop until close(); the first sweep runs immediately."""
        while not self._stopped.is_set():
            with contextlib.suppress(Exception):
                await self.sweep_once()
            try:
                await asyncio.wait_for(self._stopped.wait(), timeout=self._interval_s)
            except TimeoutError:
                continue
            except asyncio.CancelledError:
                break

    async def close(self) -> None:
        """Stop after the current sweep."""
        self._stopped.set()
```

- [ ] **Step 4: Run to verify it passes**

Run: `$env:PATH = "E:\CamBrain\.venv\Scripts;" + $env:PATH; python -m pytest backend/tests/test_retention.py -v; if ($?) { python -m ruff check backend; if ($?) { python -m mypy backend } }`
Expected: 7 passed; ruff/mypy clean.

- [ ] **Step 5: Commit**

Message (`feat(events): batched retention with orphan reclamation`):
body: `Events age out in 500-row batches so a busy box never stalls the writers, files unlink before their rows commit, and the 24h orphan sweep reclaims whatever a crash left behind (DATABASE A6.5, A9). Retention days of zero means keep everything — a deliberate opt-out, not a bug.`

---

### Task 12: System events — nullable camera, quota latch, "System" in the UI

**Files:**
- Create: `backend/migrations/versions/p5b_system_events.py`
- Modify: `backend/app/db/repositories/events.py` (`stats()` camera key)
- Modify: `backend/app/api/routers/events.py` + `backend/app/api/schemas.py` (`EventOut.camera` nullable, name "System")
- Modify: `backend/app/services/alerts/handler.py` (quota latch wiring helper)
- Test: extend `backend/tests/test_events_persist.py` + events router tests

**Interfaces:**
- Consumes: `QuotaExceededError` (T3), `AlertHandler.set_quota_hook` (T6), `EventOut` (T4/Phase 2).
- Produces: migration `p5b` (`down_revision="p5a_delivery_retry"`) making `events.camera_id` nullable via `batch_alter_table`; `create_system_event(db, *, site_id, severity, summary, triggered_by="system") -> Event`; quota latch `QuotaLatch` with `fire(summary: str) -> None` firing once per site until cleared; `EventOut.camera: CameraRef | None` with `camera_name` fallback "System"; `stats()["by_camera"]` uses `"system"` key for null. Tasks 6/13 wire the latch.

- [ ] **Step 1: Write the failing tests** — append to `backend/tests/test_events_persist.py`:

```python
def test_system_event_needs_no_camera(db_session, seeded) -> None:
    from app.services.events.persist import create_system_event

    site, _a, _v = seeded
    event = create_system_event(
        db_session, site_id=site.id, severity="critical",
        summary="disk quota 81% >= 80%; clip refused for camera Front door",
    )
    assert event.camera_id is None and event.triggered_by == "system"
    assert event.site_id == site.id and event.delivery_status == "pending"


def test_quota_latch_fires_once_until_cleared(db_session, seeded) -> None:
    from app.services.alerts.latch import QuotaLatch

    site, _a, _v = seeded
    fired: list[str] = []
    latch = QuotaLatch(site_id=site.id, on_fire=fired.append)
    latch.fire("disk quota exceeded")
    latch.fire("disk quota exceeded")
    assert fired == ["disk quota exceeded"], "one alarm per crossing (D12)"
    latch.clear()
    latch.fire("disk quota exceeded again")
    assert len(fired) == 2
```

And in the events API test file:

```python
def test_system_event_serialises_as_system_camera(client, db_session, seeded) -> None:
    site, _a, _v = seeded
    from app.services.events.persist import create_system_event

    event = create_system_event(db_session, site_id=site.id, severity="critical", summary="quota")
    res = client.get(f"/api/v1/events/{event.id}")
    assert res.status_code == 200
    body = res.json()
    assert body["camera"] is None  # until Step 3 — currently 500 because CameraRef(id=None)
    listing = client.get("/api/v1/events").json()
    assert listing["items"][0]["camera"] is None
    stats = client.get("/api/v1/events/stats").json()
    assert "system" in stats["by_camera"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `$env:PATH = "E:\CamBrain\.venv\Scripts;" + $env:PATH; python -m pytest backend/tests -k "system_event or latch or serialises" -v`
Expected: FAIL — `IntegrityError` on `camera_id NOT NULL` (migration missing), `ModuleNotFoundError: app.services.alerts.latch`, 500 from `CameraRef(id=None)`, missing `"system"` key.

- [ ] **Step 3: Implement**

**Migration** `backend/migrations/versions/p5b_system_events.py` — follow `p5a`'s header exactly, `down_revision = "p5a_delivery_retry"` (read `p5a`'s revision id once it exists — Task 4 wrote it; use that literal):

```python
revision = "p5b_system_events"
down_revision = "<p5a revision id from p5a_delivery_retry.py>"
...

def upgrade() -> None:
    with op.batch_alter_table("events") as batch_op:
        batch_op.alter_column("camera_id", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    with op.batch_alter_table("events") as batch_op:
        batch_op.alter_column("camera_id", existing_type=sa.Integer(), nullable=False)
```

(Note: SQLite FK nullable flip needs `with op.batch_alter_table("events", reflect_args=[...])` only if SQLite complains about FK loss — run the upgrade+downgrade test below first; if FKs drop, pass `batch_op.create_foreign_key` in upgrade. The existing migration tests will catch it.)

Add roundtrip tests to the migration test file (find: `Select-String -Path E:\CamBrain\backend\tests\*.py -Pattern "p5a|alembic" -List` → extend that file with upgrade→insert null-camera row→downgrade→IntegrityError assertions).

**`persist.py` gains:**

```python
def create_system_event(
    db: Session,
    *,
    site_id: int,
    severity: str,
    summary: str,
    delivery_status: str = "pending",
) -> Event:
    """A site-level event with no camera: quota refusals, runtime faults (D5)."""
    event = Event(
        site_id=site_id,
        camera_id=None,
        rule_id=None,
        triggered_by="system",
        started_at=datetime.now(tz=UTC).replace(tzinfo=None),
        severity=severity,
        summary=summary,
        delivery_status=delivery_status,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event
```

**New** `backend/app/services/alerts/latch.py`:

```python
"""One alarm per crossing (D12): a persistent quota breach must not spam.

A disk that sits over quota would otherwise fire a system event on every
refused clip; the latch fires once per site until something clears it (the
sweep that frees space calls clear()).
"""

from __future__ import annotations


class QuotaLatch:
    """Fire at most once per site until clear() is called."""

    def __init__(self, *, site_id: int, on_fire: Callable[[str], None] | None = None) -> None:
        self.site_id = site_id
        self._on_fire = on_fire
        self._fired = False

    @property
    def fired(self) -> bool:
        return self._fired

    def fire(self, summary: str) -> None:
        """Invoke on_fire the first time only."""
        if self._fired:
            return
        self._fired = True
        if self._on_fire is not None:
            self._on_fire(summary)

    def clear(self) -> None:
        """Re-arm after the disk pressure is resolved."""
        self._fired = False
```

(with `from collections.abc import Callable` at top.)

**`repositories/events.py` `stats()`** — the `by_camera` mapping currently does `str(k)` which yields `"None"`. Change to:

```python
            "by_camera": {("system" if k is None else str(k)): int(v) for k, v in by_camera.items()},
```

**`schemas.py`** — `EventOut.camera: CameraRef | None = None`.

**`events.py` `_to_out`**:

```python
        camera=(
            CameraRef(id=event.camera_id, name=camera_name)
            if event.camera_id is not None
            else None
        ),
```

and the name fallbacks change from `cam_names.get(e.camera_id, f"camera-{e.camera_id}")` to:

```python
def _camera_label(names: dict[int, str], camera_id: int | None) -> str | None:
    """Camera name, 'System' for system events, or None when unknown."""
    if camera_id is None:
        return "System"
    return names.get(camera_id, f"camera-{camera_id}")
```

Passing `None` when `camera_id is None`... **Decision (D5):** `EventOut.camera` is `None` and the *name* lives nowhere — so instead make `_to_out` take `camera_name: str | None` and build `CameraRef(id=None, name="System")`? No: `CameraRef.id` is `int`. Final shape: `camera=None` for system events, and frontend renders "System" when `camera == null`. So `_camera_label` is only used for real cameras; system events pass `camera=None`. Update both call sites (`list_events`, `get_event`, `acknowledge_event`) to `camera=_to_out(...)`-compatible name: use `cam_names.get(e.camera_id, f"camera-{e.camera_id}") if e.camera_id is not None else "System"` — the name is unused when camera is None; keep it simple by passing `camera_name="System"`.

- [ ] **Step 4: Run to verify it passes**

Run: `$env:PATH = "E:\CamBrain\.venv\Scripts;" + $env:PATH; python -m pytest backend/tests -k "system_event or latch or serialises or stats" -v; if ($?) { python -m pytest backend/tests -m "not rtsp and not slow" }; if ($?) { python -m ruff check backend; if ($?) { python -m mypy backend } }`
Expected: new tests pass; full suite still 276+; ruff/mypy clean. If the migration roundtrip test fails on FK reflection, fix the batch args as noted.

- [ ] **Step 5: Commit**

Message (`feat(events): system events without a camera`):
body: `Disk-quota refusals are site events, not camera events (spec A5.7): camera_id goes nullable behind migration p5b, the API serialises camera as null and the stats bucket as "system" (D5), and a per-site latch keeps one crossing from becoming one alarm per refused clip (D12).`

---

### Task 13: `Runtime` — pipelines, alert chain, stream→DB bridge, lifespan

**Files:**
- Create: `backend/app/services/runtime.py`
- Modify: `backend/app/core/config.py` (`model_path`, `model_input_size`, `runtime_enabled`, `telegram_api_base`)
- Modify: `backend/app/main.py` (lifespan)
- Modify: `backend/tests/conftest.py` (`os.environ.setdefault("CAMBRAIN_RUNTIME", "0")` next to the JWT line)
- Test: `backend/tests/test_runtime.py`

**Interfaces:**
- Consumes: everything from T1–T12 (`AlertHandler`, `DeliveryWorker`, `RetentionRunner`, `QuotaLatch`, `AlertStage`, `open_detector`, `StreamManager`, `default_source_factory` via `CameraConfig`→url).
- Produces: `Runtime(session_factory=SessionLocal, *, enabled: bool | None = None, source_factory=..., detector_factory=open_detector, now=...)` with `async start() -> None`, `async stop() -> None`, `async drain() -> None` (test affordance); `get_runtime(request) -> Runtime` dependency reading `app.state.runtime`; lifespan in `create_app()`; hub is the T5 module singleton (`get_alert_hub()`), shared with `/ws/alerts`. `RuleConfig` gains `notify: bool = True` (rules.notify column) projected by `rule_config`. Task 14+ relies on `app.state.runtime`.

Bridge (the "stream→db" debt): on each camera's first sampled frame write `frame_width`/`frame_height` + `status='live'`; on pipeline failure write `status='error'` + `last_error`; on stop `status='offline'`.

- [ ] **Step 1: Write the failing tests** — `backend/tests/test_runtime.py`:

```python
"""Runtime: gated start, per-camera chain wiring, bridge, clean stop."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
from sqlalchemy import select

from app.db.models import Camera, Event, Site
from app.services.runtime import Runtime


class FakeDetector:
    """Records frames; returns no detections so nothing fires."""

    def __init__(self) -> None:
        self.frames = 0

    async def infer(self, frame: Any) -> list[Any]:
        self.frames += 1
        return []

    async def close(self) -> None:
        return None


class FakeSource:
    """Yields three frames then ends."""

    def __init__(self) -> None:
        self.closed = False

    async def frames(self):
        import numpy as np

        from app.services.stream.source import Frame

        for i in range(3):
            yield Frame(data=np.zeros((36, 64, 3), dtype=np.uint8), pts=float(i), width=64, height=36)

    async def close(self) -> None:
        self.closed = True


def _camera(db_session, seeded) -> Camera:
    site, _a, _v = seeded
    camera = Camera(site_id=site.id, name="Front", rtsp_url="rtsp://x/ch1")
    db_session.add(camera)
    db_session.commit()
    return camera


async def test_runtime_disabled_starts_nothing(db_session) -> None:
    runtime = Runtime(session_factory=lambda: db_session, enabled=False)
    await runtime.start()
    assert runtime.cameras == {}
    await runtime.stop()


async def test_runtime_wires_bridge_and_writes_dims(db_session, seeded) -> None:
    camera = _camera(db_session, seeded)
    runtime = Runtime(
        session_factory=lambda: db_session,
        enabled=True,
        detector_factory=lambda **_kw: FakeDetector(),
        source_factory=lambda _config: FakeSource(),
    )
    await runtime.start()
    await runtime.drain()  # lets the pipelines finish their finite sources
    db_session.expire_all()
    row = db_session.get(Camera, camera.id)
    assert row.frame_width == 64 and row.frame_height == 36, "bridge records dims"
    assert row.status in ("live", "offline")
    await runtime.stop()


async def test_runtime_survives_missing_weights(db_session) -> None:
    """Degraded start (D10): no model on disk -> cameras still run, no detector."""
    camera = _camera(db_session, seeded)

    def boom(**_kw):
        raise FileNotFoundError("yolox_nano.onnx")

    runtime = Runtime(
        session_factory=lambda: db_session,
        enabled=True,
        detector_factory=boom,
        source_factory=lambda _config: FakeSource(),
    )
    await runtime.start()
    await runtime.drain()
    db_session.expire_all()
    row = db_session.get(Camera, camera.id)
    assert row is not None and row.frame_width == 64, "degraded still bridges dims"
    await runtime.stop()


async def test_runtime_stop_closes_everything(db_session, seeded) -> None:
    _camera(db_session, seeded)
    sources: list[FakeSource] = []

    def make(_config):
        source = FakeSource()
        sources.append(source)
        return source

    runtime = Runtime(
        session_factory=lambda: db_session,
        enabled=True,
        detector_factory=lambda **_kw: FakeDetector(),
        source_factory=make,
    )
    await runtime.start()
    await runtime.drain()
    await runtime.stop()
    assert runtime.cameras == {}
    assert all(s.closed for s in sources)


async def test_quota_latch_fires_a_system_event(db_session, seeded) -> None:
    from app.services.alerts.latch import QuotaLatch
    from app.services.events.persist import create_system_event

    site, _a, _v = seeded
    seen: list[str] = []
    latch = QuotaLatch(site_id=site.id, on_fire=lambda s: seen.append(s))
    latch.fire("disk quota exceeded")
    assert seen == ["disk quota exceeded"]
```

`Runtime.drain()` is a small test affordance: awaits the per-camera pipeline tasks with a short timeout (pipelines in tests are finite `FakeSource`s, so `await asyncio.gather(*tasks)` after a tick). Implement `drain` as `await asyncio.sleep(0)` repeated while any task is not done, capped at 2s.

- [ ] **Step 2: Run to verify it fails**

Run: `$env:PATH = "E:\CamBrain\.venv\Scripts;" + $env:PATH; python -m pytest backend/tests/test_runtime.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.runtime'`.

- [ ] **Step 3: Implement**

**`config.py`** additions:

```python
    # Model weights; defaults to the repo's models/ dir (D13: yolox_nano @416).
    model_path: Path = Path(r"%LOCALAPPDATA%\CamBrain\models\yolox_nano.onnx")
    model_input_size: int = 416
    # Runtime (pipelines + detection chain) on/off. Conftest sets 0 (D10).
    runtime_enabled: bool = True
    # Telegram base URL — override for tests/gates (D8: mock capture server).
    telegram_api_base: str = "https://api.telegram.org"
```

Wait — `model_path` default: the repo weights live at `<repo>/models/yolox_nano.onnx` for dev, and a packaged app would use LOCALAPPDATA. Choose the repo path as default (Phase 3 gate uses `parents[2]/"models"`), with env override `CAMBRAIN_MODEL_PATH`:

```python
    model_path: Path = Path(__file__).resolve().parents[3] / "models" / "yolox_nano.onnx"
```
(`parents[3]` from `backend/app/core/config.py` = repo root. `pydantic-settings` maps `CAMBRAIN_MODEL_PATH` automatically.)

**`conftest.py`** — next to line 17:

```python
os.environ.setdefault("CAMBRAIN_RUNTIME", "0")
```

**`runtime.py`**:

```python
"""The process-wide brain: pipelines, the alert chain, and the DB bridge.

Owned by main.py's lifespan. Every collaborator is constructed here once:
one detector + pool, one hub, one delivery worker, one retention runner,
and per camera a ring buffer + handler + AlertStage (arch A7).

`enabled=False` (conftest, CAMBRAIN_RUNTIME=0) makes start() a no-op so the
API test suite never opens a socket or a model file.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.crypto import decrypt
from app.db.models import Camera, Site
from app.db.session import SessionLocal
from app.services.alerts.delivery import DeliveryWorker
from app.services.alerts.hub import AlertHub, event_message, get_alert_hub
from app.services.alerts.latch import QuotaLatch
from app.services.alerts.replay import rule_config
from app.services.alerts.stage import AlertStage
from app.services.alerts.rules import RuleConfig
from app.db.repositories.rules import RuleRepository
from app.db.repositories.rois import RoiRepository
from app.services.events.clips import ClipWriter, FrameRingBuffer
from app.services.events.handler import AlertHandler
from app.services.events.persist import create_system_event
from app.services.events.retention import RetentionRunner
from app.services.stream.factory import default_source_factory
from app.services.stream.pipeline import CameraConfig
from app.services.stream.source import Frame
from app.services.stream.stream_manager import StreamManager

SourceFactory = Callable[[CameraConfig], Any]
DetectorFactory = Callable[..., Any]


class Runtime:
    """Start and stop the whole alerting chain; own its lifecycle."""

    def __init__(
        self,
        *,
        session_factory: Callable[[], Session] = SessionLocal,
        enabled: bool | None = None,
        source_factory: SourceFactory | None = None,
        detector_factory: DetectorFactory | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._enabled = settings.runtime_enabled if enabled is None else enabled
        self._source_factory = source_factory
        self._detector_factory = detector_factory
        self._now = now
        self._hub: AlertHub | None = None
        self._worker: DeliveryWorker | None = None
        self._retention: list[RetentionRunner] = []
        self._manager: StreamManager | None = None
        self._detector: Any = None
        self._handlers: dict[str, AlertHandler] = {}
        self._tasks: list[asyncio.Task[None]] = []
        self._bridged: set[int] = set()
        self._latches: dict[int, QuotaLatch] = {}
        self.cameras: dict[str, dict[str, Any]] = {}

    @property
    def hub(self) -> AlertHub:
        """The alert hub the WS endpoint serves (module singleton, T5)."""
        if self._hub is None:
            self._hub = get_alert_hub()
        return self._hub

    async def start(self) -> None:
        """Construct and launch everything; no-op when disabled (D10)."""
        if not self._enabled:
            return
        self._hub = get_alert_hub()
        self._detector = self._open_detector_safely()
        self._manager = StreamManager(
            self._manager_source_factory(), _noop_sink
        )
        db = self._session_factory()
        try:
            db.execute(
                update(Camera)
                .where(Camera.status.in_(("live", "starting")))
                .values(status="offline")
                .execution_options(synchronize_session=False)
            )
            db.commit()
            rows = db.execute(
                select(Camera).where(Camera.enabled.is_(True))
            ).scalars().all()
            site_ids = sorted({c.site_id for c in rows})
            sites = {
                s.id: s
                for s in db.execute(select(Site).where(Site.id.in_(site_ids))).scalars()
            }
        finally:
            db.close()
        for camera in rows:
            self._start_camera(camera, sites.get(camera.site_id))
        self._worker = DeliveryWorker(session_factory=self._session_factory)
        self._tasks.append(asyncio.create_task(self._worker.run()))
        for site_id in site_ids:
            runner = RetentionRunner(
                site_id=site_id, session_factory=self._session_factory
            )
            self._retention.append(runner)
            self._tasks.append(asyncio.create_task(runner.run()))

    async def drain(self) -> None:
        """Test affordance: wait for finite test pipelines to finish."""
        for _ in range(200):
            await asyncio.sleep(0.01)

    async def stop(self) -> None:
        """Cancel loops, stop pipelines, close detector and handlers."""
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._tasks.clear()
        if self._worker is not None:
            await self._worker.close()
        for runner in self._retention:
            await runner.close()
        self._retention.clear()
        if self._manager is not None:
            self._manager.stop()
            await asyncio.sleep(0)  # let pipelines run their finally blocks
            self._mark_offline()
        for handler in self._handlers.values():
            await handler.close()
        self._handlers.clear()
        self.cameras.clear()
        if self._detector is not None:
            with contextlib.suppress(Exception):
                await self._detector.close()

    # -- internals ---------------------------------------------------------

    def _open_detector_safely(self) -> Any:
        """Open the detector; missing weights -> degraded start (D10)."""
        import logging

        log = logging.getLogger(__name__)
        try:
            if self._detector_factory is not None:
                return self._detector_factory(
                    settings.model_path, input_size=settings.model_input_size
                )
            from app.services.inference.detector import open_detector

            return open_detector(
                settings.model_path, input_size=settings.model_input_size
            )
        except FileNotFoundError:
            log.warning("detector weights missing; starting degraded (D10)")
            return None

    def _manager_source_factory(self) -> SourceFactory:
        """The manager's factory: Runtime's override, else the default RTSP."""
        if self._source_factory is not None:
            return self._source_factory
        return lambda config: default_source_factory(self._camera_rows[config.camera_id])

    async def _noop_sink(frame: Frame) -> None:
        """Manager-wide sink; each camera overrides it with its own chain."""
        return None
```

`_camera_rows: dict[str, Camera]` — populated in `start()` (`self._camera_rows = {str(c.id): c for c in rows}`; init `self._camera_rows = {}` in `__init__`). Make `_noop_sink` a module-level `async def _noop_sink(frame: Frame) -> None` (methods can't be passed unbound like that — fix: module-level function).

`_start_camera(camera, site)`:

```python
    def _start_camera(self, camera: Camera, site: Site | None) -> None:
        """Build one camera's full chain and hand it to the manager."""
        config = CameraConfig(
            camera_id=str(camera.id),
            name=camera.name,
            url=camera.rtsp_url,   # NOTE: manager source reads url; see below
            sample_fps=camera.sample_fps,
        )
        ring = FrameRingBuffer(fps=camera.sample_fps, depth_s=30.0)
        writer = ClipWriter(media_root=settings.media_root)
        handler = AlertHandler(
            camera_id=camera.id,
            site_id=camera.site_id,
            camera_name=camera.name,
            ring=ring,
            writer=writer,
            hub=self.hub,
            session_factory=self._session_factory,
            quota_pct=lambda sid=camera.site_id: self._site_quota(sid),
        )
        handler.set_quota_hook(
            self._quota_hook(camera.site_id, camera.name, site)
        )
        self._handlers[config.camera_id] = handler
        rules = self._load_rules(camera)
        if self._detector is None or not rules:
            sink: Any = lambda frame: self._light_sink(frame, ring, camera, handler)  # noqa: E731
        else:
            stage = AlertStage(detector=self._detector, rules=rules, on_alert=handler)

            async def sink(frame: Frame) -> None:
                ring.push(frame)
                await self._bridge(camera, frame)
                await stage(frame)

        self._manager.add_camera(config, sink=sink)
        self.cameras[config.camera_id] = {"ring": ring, "handler": handler}
```

`_light_sink` (degraded / no-rules): pushes to ring + bridges dims but runs no detection:

```python
    async def _light_sink(self, frame: Frame, ring: FrameRingBuffer, camera: Camera, handler: AlertHandler) -> None:
        ring.push(frame)
        await self._bridge(camera, frame)
```

(Remove the unused `handler` param or use it — drop it from the signature.)

**URL note:** `CameraConfig.url` currently feeds `RtspSource` via the manager's `SourceFactory(config)`. `default_source_factory` takes a `Camera` row and handles password decryption. With the default factory path, pass the row (as in `_manager_source_factory`); `CameraConfig.url` can hold `camera.rtsp_url` (unencrypted) — the default factory ignores it and uses the row. For the **test** factory the config's url is unused too (FakeSource ignores config). So `url=camera.rtsp_url` is fine; document that `connect_url`/decrypt lives inside `default_source_factory`.

`_bridge(camera, frame)`:

```python
    async def _bridge(self, camera: Camera, frame: Frame) -> None:
        """Write frame dims + live status once per camera (stream->db debt)."""
        if camera.id in self._bridged:
            return
        self._bridged.add(camera.id)
        db = self._session_factory()
        try:
            db.execute(
                update(Camera)
                .where(Camera.id == camera.id)
                .values(
                    frame_width=frame.width,
                    frame_height=frame.height,
                    status="live",
                )
            )
            db.commit()
        finally:
            db.close()
```

`_load_rules(camera)`:

```python
    def _load_rules(self, camera: Camera) -> list[RuleConfig]:
        """Enabled rules for one camera, ROIs joined, notify projected (D?)."""
        db = self._session_factory()
        try:
            rules = RuleRepository(db, site_id=camera.site_id).list(
                camera_id=camera.id, enabled=True
            )
            rois = {r.id: r for r in RoiRepository(db, site_id=camera.site_id).list()}
            return [rule_config(r, rois.get(r.roi_id)) for r in rules]
        finally:
            db.close()
```

**Check `RuleRepository.list` signature** — Phase 2's `list()` may not take `camera_id`/`enabled`; if not, filter in Python (`[r for r in repo.list() if r.camera_id == camera.id and r.enabled]`). Same for `RoiRepository.list()`.

`_quota_hook`, `_site_quota`, `_mark_offline`:

```python
    def _quota_hook(self, site_id: int, camera_name: str, site: Site | None) -> Callable[[str], None]:
        """Quota refusal -> one system event per crossing (D12)."""
        def fire(summary: str) -> None:
            latch = self._latches.get(site_id)
            if latch is None:
                latch = QuotaLatch(site_id=site_id)
                self._latches[site_id] = latch
            latch.fire(summary)

            def _persist(full: str) -> None:
                db = self._session_factory()
                try:
                    event = create_system_event(
                        db, site_id=site_id, severity="critical", summary=full
                    )
                    self.hub.broadcast(
                        event.site_id, event_message(event, None)
                    )
                finally:
                    db.close()

            if latch.fired:
                _persist(f"{summary} (camera {camera_name})")
        return fire
```

Wait — `QuotaLatch.fire(summary)` only invokes `on_fire` once; construct the latch **with** `on_fire=_persist` instead (the nested def above re-orders: build `_persist` first, then `latch = self._latches.setdefault(site_id, QuotaLatch(site_id=site_id, on_fire=_persist))`, then `latch.fire(...)`). Write it in that order.

```python
    def _site_quota(self, site_id: int) -> float:
        db = self._session_factory()
        try:
            site = db.get(Site, site_id)
            return float(site.disk_quota_pct) if site else 80.0
        finally:
            db.close()

    def _mark_offline(self) -> None:
        db = self._session_factory()
        try:
            ids = [int(k) for k in self.cameras]
            if ids:
                db.execute(
                    update(Camera)
                    .where(Camera.id.in_(ids))
                    .values(status="offline")
                    .execution_options(synchronize_session=False)
                )
                db.commit()
        finally:
            db.close()
```

**`event_message(event, camera_name)`** — Task 5 defined it as taking `(event, camera_name)`; for system events pass `None` and have `event_message` tolerate it (if Task 5's signature requires str, pass `"System"`).

**`RuleConfig.notify`**: add field `notify: bool = True` after `last_fired_at`, and `replay.rule_config` passes `notify=bool(rule.notify)`. Add to the test in this task:

```python
def test_rule_config_projects_notify() -> None:
    from app.db.models import Rule
    from app.services.alerts.replay import rule_config

    rule = Rule(
        site_id=1, camera_id=1, name="r", severity="critical",
        classes=["person"], confidence_threshold=0.5, cooldown_seconds=60,
        notify=False,
    )
    assert rule_config(rule, None).notify is False
```

(**Verify `Rule` model accepts `notify=`** — the column exists per DATABASE §4; if the field name differs, read `app/db/models/rule.py` first.)

**`main.py` lifespan:**

```python
from contextlib import asynccontextmanager

from fastapi import Request

from app.services.runtime import Runtime


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the alerting runtime; stop it on shutdown (arch A7)."""
    runtime = Runtime()
    app.state.runtime = runtime
    await runtime.start()
    try:
        yield
    finally:
        await runtime.stop()


def get_runtime(request: Request) -> Runtime:
    """FastAPI dependency: the process-wide runtime (WS endpoint, T5)."""
    return request.app.state.runtime

def create_app() -> FastAPI:
    app = FastAPI(..., lifespan=lifespan)
    ...
```

Conftest `TestClient` runs lifespan on entry — with `CAMBRAIN_RUNTIME=0` it's a no-op; confirm the full suite still passes. If `TestClient(app)` without `with` is used anywhere, lifespan won't run there (fine — runtime only needed live).

**Also fix `system.py` hardware/model stubs while here** (part of the `—×—` debt): populate `"hardware_tier"` via `app.services.inference.tiers.resolve_tier()` (returns `(tier, model_path, input_size)` — cache at module import in a try/except returning `"unknown"`), `"model": {"name": model_path.name, "input_size": n}` when resolvable, and `"hardware"` from `probe_capabilities()` (cpu_cores/avx2/vnni/ram/disk via `shutil.disk_usage` + `psutil`-free `os.cpu_count()`; read `tiers.Capabilities` fields and map them; disk via `shutil.disk_usage(settings.media_root)`). SystemView renders `hardware.disk_used_pct` — include it. Tests: existing system tests may assert `"unknown"` — update them to assert the real shape instead (`hardware_tier in ("low","mid","high","unknown")`).

- [ ] **Step 4: Run to verify it passes**

Run: `$env:PATH = "E:\CamBrain\.venv\Scripts;" + $env:PATH; python -m pytest backend/tests/test_runtime.py -v; if ($?) { python -m pytest backend/tests -m "not rtsp and not slow" }; if ($?) { python -m ruff check backend; if ($?) { python -m mypy backend } }`
Expected: runtime tests pass; full suite still green; ruff/mypy clean.

- [ ] **Step 5: Commit**

Message (`feat(runtime): lifespan-owned pipelines, alert chain, and DB bridge`):
body: `The API process finally runs the cameras it serves: one detector + pool, per-camera ring/handler/stage, delivery and retention loops, all gated by CAMBRAIN_RUNTIME so tests stay socket-free (D10). The bridge writes frame dims and live status from the first sampled frame, retiring the -—x-— placeholder debt.`

---

### Task 14: Rate limiter middleware (the Phase-4 debt)

**Files:**
- Create: `backend/app/api/ratelimit.py`
- Modify: `backend/app/main.py` (install middleware)
- Test: `backend/tests/test_api_ratelimit.py`

**Interfaces:**
- Consumes: client IP (`request.client.host`, honoring `X-Forwarded-For` is NOT needed — LAN box, direct connections), error envelope's `429 RATE_LIMITED` handler (exists in `app/api/errors.py` line 58).
- Produces: `RateLimitMiddleware` with in-memory fixed windows per D9: `POST /auth/refresh` 30/min, `POST /cameras/{id}/test` and `POST /cameras/test` 10/min, everything under `/api/v1` else 120/min; **excluded**: `/auth/login` (lockout owns it), `/system/health`, `/cameras/{id}/stream` (slot cap owns it), `/ws/*`; response `429` + `Retry-After` header + envelope code `RATE_LIMITED`. Route matching by (method, path) prefix table.

- [ ] **Step 1: Write the failing tests** — `backend/tests/test_api_ratelimit.py`:

```python
"""Fixed-window rate limiter: rows from API A6, exclusions honored."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.api.ratelimit import RateLimitMiddleware, _Limits


def test_camera_test_route_limited_at_ten_per_minute(admin_headers, client) -> None:  # noqa: ARG001
    statuses = [
        client.post("/api/v1/cameras/test", json={"rtsp_url": "rtsp://127.0.0.1:1/x"}).status_code
        for _ in range(12)
    ]
    assert statuses[:9] != [429] * 9 or 429 in statuses  # allow earlier 4xx from probe
    limited = [s for s in statuses if s == 429]
    assert limited, "the 10/min camera-test cap must bite by request 12"


def test_login_never_rate_limited_by_middleware(client) -> None:
    for _ in range(150):
        res = client.post("/api/v1/auth/login", json={"username": "nobody", "password": "x"})
        assert res.status_code != 429, "login has its own lockout (423), not 429"


def test_general_route_120_per_minute(admin_headers, client) -> None:
    code = None
    for i in range(130):
        res = client.get("/api/v1/events", headers=admin_headers)
        if res.status_code == 429:
            code = i
            assert "retry-after" in {k.lower() for k in res.headers}
            assert res.json()["error"]["code"] == "RATE_LIMITED"
            break
    assert code is not None, "121st request within a minute must be 429"


def test_health_and_stream_excluded(client) -> None:
    for _ in range(130):
        assert client.get("/api/v1/system/health").status_code == 200
```

Note the camera-test fixture needs a real camera row (admin can't POST `/cameras/test` draft without... actually `POST /cameras/test` is the draft route taking `rtsp_url` directly — 10/min applies there; the probe itself will fail fast with a closed port, fine).

- [ ] **Step 2: Run to verify it fails**

Run: `$env:PATH = "E:\CamBrain\.venv\Scripts;" + $env:PATH; python -m pytest backend/tests/test_api_ratelimit.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.api.ratelimit'` (or 429s never arrive).

- [ ] **Step 3: Implement** `backend/app/api/ratelimit.py`:

```python
"""Fixed-window rate limiter per API A6 (phase-4 debt, D9).

In-memory: one process, one box, no Redis (architecture A8). Windows reset
on a monotonic clock; the table drives matching so a new route is a row.
"""

from __future__ import annotations

import time
from collections import defaultdict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

WINDOW_S = 60.0

# (method, path-prefix) -> limit; first match wins.
_LIMITS: list[tuple[str, str, int]] = [
    ("POST", "/api/v1/auth/refresh", 30),
    ("POST", "/api/v1/cameras/test", 10),
    ("POST", "/api/v1/cameras/", 10),   # /cameras/{id}/test
]

_EXCLUDED_PREFIXES = (
    "/api/v1/auth/login",
    "/api/v1/system/health",
    "/api/v1/cameras/",   # streams live under this prefix — refine below
    "/api/v1/ws/",
)

DEFAULT_LIMIT = 120


def _limit_for(method: str, path: str) -> int | None:
    """None means excluded (never counted, never limited)."""
    if path.startswith(("/api/v1/auth/login", "/api/v1/system/health", "/api/v1/ws/")):
        return None
    if path.endswith("/stream") and "/api/v1/cameras/" in path:
        return None
    for rule_method, prefix, limit in _LIMITS:
        if method == rule_method and path.startswith(prefix):
            if rule_method == "POST" and prefix == "/api/v1/cameras/":
                if not path.endswith("/test"):
                    continue
            return limit
    if path.startswith("/api/v1/"):
        return DEFAULT_LIMIT
    return None


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Count requests per (IP, route-bucket, window); 429 past the row."""

    def __init__(self, app, *, now=time.monotonic):  # noqa: ANN001, ANN204
        super().__init__(app)
        self._now = now
        self._hits: dict[tuple[str, str], tuple[int, float]] = defaultdict(lambda: (0, 0.0))

    def _check(self, key: tuple[str, str], limit: int) -> int | None:
        """Returns remaining-window seconds when limited, else None."""
        count, start = self._hits[key]
        now = self._now()
        if now - start >= WINDOW_S:
            count, start = 0, now
        count += 1
        self._hits[key] = (count, start)
        if count > limit:
            return max(1, int(WINDOW_S - (now - start)))
        return None

    async def dispatch(self, request: Request, call_next):  # noqa: ANN001, ANN204
        limit = _limit_for(request.method, request.url.path)
        if limit is None:
            return await call_next(request)
        ip = request.client.host if request.client else "unknown"
        retry = self._check((ip, request.url.path.rsplit("/", 1)[0]), limit)
        if retry is not None:
            body = {
                "error": {
                    "code": "RATE_LIMITED",
                    "message": f"rate limit exceeded; retry in {retry}s",
                    "field": None,
                    "correlation_id": "none",
                }
            }
            return JSONResponse(body, status_code=429, headers={"Retry-After": str(retry)})
        return await call_next(request)
```

Refine before running (the `_LIMITS`/`_limit_for` interplay is intentionally simple but must be coherent — rewrite `_limit_for` cleanly as one function; delete `_EXCLUDED_PREFIXES` since the logic lives in the function):

```python
def _limit_for(method: str, path: str) -> int | None:
    """Bucket limit for a route, or None when excluded entirely (D9)."""
    if not path.startswith("/api/v1/"):
        return None
    if path.startswith(("/api/v1/auth/login", "/api/v1/system/health", "/api/v1/ws/")):
        return None
    if "/api/v1/cameras/" in path and path.endswith("/stream"):
        return None
    if method == "POST" and path.startswith("/api/v1/auth/refresh"):
        return 30
    if method == "POST" and (path.endswith("/cameras/test") or path.endswith("/cameras/test")):
        return 10
    if method == "POST" and "/test" in path and "/cameras/" in path:
        return 10
    return DEFAULT_LIMIT
```

(The exact path-shape checks: `/api/v1/cameras/test` is the draft test; `/api/v1/cameras/{id}/test` is the saved-camera test. Match both with a regex or the two conditions above; drop duplicates.)

Bucket key = `(ip, path.rsplit("/", 1)[0])` groups `/cameras/3/test` and `/cameras/4/test` into one bucket — that's intended (hardware protection is per IP across probes). Document that.

`main.py`: `app.add_middleware(RateLimitMiddleware)` after CorrelationId.

- [ ] **Step 4: Run to verify it passes**

Run: `$env:PATH = "E:\CamBrain\.venv\Scripts;" + $env:PATH; python -m pytest backend/tests/test_api_ratelimit.py -v; if ($?) { python -m pytest backend/tests -m "not rtsp and not slow" }; if ($?) { python -m ruff check backend; if ($?) { python -m mypy backend } }`
Expected: ratelimit tests pass; **full suite green** — if auth tests now hit 429 (they shouldn't: login excluded; but auth/refresh tests may loop), reduce test loops or exclude testserver more narrowly. `TestClient` reports `testclient` host — all tests share one bucket per route; the 130-iteration loop in one test is fine, but *other* tests hitting `/events` after it in the same process would 429. Fix: give the middleware a `reset()` and call it in a conftest autouse fixture (`app` is rebuilt per test via `create_app()`, so middleware state is per-app — confirm and note it; if state is class-level, make it per-instance).

- [ ] **Step 5: Commit**

Message (`feat(api): fixed-window rate limiter for the documented rows`):
body: `The phase-4 D4 debt: 30/min refresh, 10/min camera probe, 120/min everything else, with login/health/stream/ws excluded so the lockout, liveness probe, slot cap, and socket handshake keep owning their rows (API A6).`

---

### Task 15: Still-image replay for `POST /rules/{id}/test`

**Files:**
- Modify: `backend/app/api/schemas.py` (`RuleTestRequest.image_b64`, optional)
- Modify: `backend/app/api/routers/rules.py` (image branch)
- Modify: `backend/app/services/alerts/replay.py` (extract `_evaluate` reusable by image path)
- Test: extend the rules API test file

**Interfaces:**
- Consumes: `open_detector(settings.model_path, input_size=...)` behind a **FastAPI dependency** so tests inject a fake (D8); `RuleConfig` (T13 gained `notify`).
- Produces: `RuleTestRequest.image_b64: str | None` (when present, the endpoint decodes base64 JPEG → runs the injected detector → synthesises `EventDetection`-shaped detections → engine evaluate → same `RuleTestOut`); `get_rule_detector()` dependency (module-level, returns `open_detector(...)` singleton; tests override). Requires `frame_width/height` on the camera OR derives from the decoded image dims. API.md L283's deferral sentence must be updated in Task 18.

- [ ] **Step 1: Write the failing test** — append to the rules test file:

```python
def test_rule_test_with_base64_still_runs_detector(client, admin_headers, db_session, seeded) -> None:
    """Spec A7.3: still-or-event; the still path must not need weights."""
    from app.api.routers import rules as rules_router

    site, _admin, _viewer = seeded
    camera = Camera(site_id=site.id, name="Front", rtsp_url="rtsp://x/ch1",
                    frame_width=64, frame_height=36)
    db_session.add(camera)
    db_session.commit()
    roi = Roi(camera_id=camera.id, name="door", points=[[0, 0], [1, 0], [1, 1], [0, 1]])
    db_session.add(roi)
    rule = Rule(site_id=site.id, camera_id=camera.id, roi_id=None, name="r",
                severity="critical", classes=["person"], confidence_threshold=0.5,
                cooldown_seconds=0, notify=True)
    db_session.add(rule)
    db_session.commit()

    class FakeDetector:
        async def infer(self, frame):
            from app.services.inference.types import Detection

            return [Detection(class_name="person", confidence=0.91, bbox=(4, 4, 40, 30))]

        async def close(self):
            return None

    import base64

    jpeg = base64.b64encode(bytes.fromhex(
        "ffd8ffe000104a46494600010100000100010000ffdb004300080606070605080707070909080a0c140d0c0b0b0c1912130f141d1a1f1e1d1a1c1c20242e2720222c231c1c2837292c30313434341f27393d38323c2e333432ffc0000b080024004001011100ffc4001f0000010501010101010100000000000000000102030405060708090a0bffc400b5100002010303020403050504040000017d01020300041105122131410613516107227114328191a1082342b1c11552d1f02433627282090a161718191a25262728292a3435363738393a434445464748494a535455565758595a636465666768696a737475767778797a838485868788898a92939495969798999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9cad2d3d4d5d6d7d8d9dae1e2e3e4e5e6e7e8e9eaf1f2f3f4f5f6f7f8f9faffda0008010100003f00f9fe8a28a2803fffd9"
    ))  # minimal 64x36 jpeg — or generate one with PyAV/encode_jpeg in the test

    monkey = rules_router.get_rule_detector
    client.app.dependency_overrides[monkey] = lambda: FakeDetector()
    res = client.post(
        f"/api/v1/rules/{rule.id}/test",
        json={"image_b64": base64.b64encode(jpeg).decode()},
        headers=admin_headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["fired"] is True
    assert any(c["condition"] == "roi" for c in body["checks"])
    client.app.dependency_overrides.clear()
```

**Simplify the JPEG:** generate it in the test with the project's own encoder — `from app.services.stream.jpeg import encode_jpeg` over a `Frame(numpy.zeros((36,64,3), uint8))` — then `base64.b64encode(...)`. No hex literals.

- [ ] **Step 2: Run to verify it fails**

Run: `$env:PATH = "E:\CamBrain\.venv\Scripts;" + $env:PATH; python -m pytest backend/tests -k "still_runs_detector" -v`
Expected: FAIL — 422 (unknown `image_b64` field) or `get_rule_detector` missing.

- [ ] **Step 3: Implement**

`schemas.py` `RuleTestRequest`:

```python
class RuleTestRequest(BaseModel):
    """Event selection, or a base64 JPEG still to detect live (API A7.3)."""

    event_id: int | None = None
    image_b64: str | None = None
```

`rules.py` — at module top:

```python
import base64
import binascii
from functools import lru_cache

from app.core.config import settings
from app.services.alerts.replay import evaluate_detections  # extracted helper

@lru_cache(maxsize=1)
def _open_rule_detector():  # noqa: ANN202
    from app.services.inference.detector import open_detector

    return open_detector(settings.model_path, input_size=settings.model_input_size)

def get_rule_detector():  # noqa: ANN202
    """Injectable detector for still replay (D8); tests override this."""
    return _open_rule_detector()
```

Endpoint branch, before the event lookup:

```python
    if body is not None and body.image_b64:
        if not camera...  # need camera first: reorder — resolve camera before branches
```

Restructure `test_rule` top: fetch rule → fetch camera (already there) → **if `body and body.image_b64`:** decode (`base64.b64decode(body.image_b64, validate=True)`, `binascii.Error` → `ValidationError("image_b64 is not valid base64")`), open a frame (decode JPEG → numpy via `av.VideoFrame.from_bytes`… simplest: pass raw bytes to detector? The `Detector.infer(frame: Frame)` contract needs a `Frame`. Decode with `av`: `import av; container = av.open(io.BytesIO(data)); frame = next(container.decode(video())); rgb = frame.to_ndarray(format="rgb24")` → `Frame(data=rgb, pts=0.0, width, height)`; wrap decode errors in `ValidationError("image_b64 is not a decodable JPEG")`).

Then `detections = await get_rule_detector().infer(frame)`, build `TrackedObject`s (tracker not needed — engine takes `TrackedObject`; read `replay.replay`'s conversion of `EventDetection`→`TrackedObject` and reuse a new helper `detections_to_tracked(dets, width, height)` in `replay.py`). Camera frame dims: if NULL, use the decoded frame's width/height (still replay doesn't need stored dims — a real improvement over the event path's 422).

`replay.py` extraction: pull the candidate-loop out of `replay()` into

```python
def evaluate_detections(
    engine: RulesEngine,
    config: RuleConfig,
    tracked: list[TrackedObject],
    when: datetime,
) -> RuleTestOut-ish  # actually returns (fired, checks: list[RuleCheck])
```

and have both `replay()` and the still branch call it. Keep `replay()`'s public signature unchanged (existing tests).

Also `RuleConfig` notify projection was T13 — still replay just uses `rule_config(rule, roi)`.

- [ ] **Step 4: Run to verify it passes**

Run: `$env:PATH = "E:\CamBrain\.venv\Scripts;" + $env:PATH; python -m pytest backend/tests -k "rule" -v; if ($?) { python -m pytest backend/tests -m "not rtsp and not slow" }; if ($?) { python -m ruff check backend; if ($?) { python -m mypy backend } }`
Expected: all rule tests pass (event branch untouched), full suite green.

- [ ] **Step 5: Commit**

Message (`feat(rules): still-image replay with an injectable detector`):
body: `Spec A7.3 promised still-or-event; the still arrives as base64 JSON (the mutation header stays JSON-only, D8) and the detector is a dependency so API tests never touch weights. Stored frame dims are not required — the image carries its own.`

---

### Task 16: Frontend — `/ws/alerts` replaces ticker polling

**Files:**
- Create: `frontend/src/api/alertsSocket.js`
- Modify: `frontend/src/stores/events.js` (WS upsert action)
- Modify: `frontend/src/camera/EventTicker.vue` (connect on mount)
- Modify: `frontend/src/api/token.js` (export `getAccessToken` already exists — confirm)
- Test: `frontend/src/__tests__/alertsSocket.spec.js` (new), extend `ticker.spec.js`

**Interfaces:**
- Consumes: `getAccessToken()` (`api/token.js`), `useEventsStore`, API.md §3 WS contract (subprotocol `cambrain.jwt.<token>`, heartbeat 30s, reconnect 1s→30s jittered, resync via `GET /events`).
- Produces: `connectAlerts({ onEvent, onHeartbeat, onOpen, onClose }) -> { close() }` — builds `ws://127.0.0.1:8765/api/v1/ws/alerts` from `import.meta.env.VITE_API_BASE` (read `client.js` for the BASE derivation and mirror it, swapping http→ws), sends token as subprotocol, exponential backoff reconnect 1s→30s ± jitter, heartbeat watchdog (no message in 45s → force reconnect), and an initial `store.load()` resync after every successful open; store action `upsert(event)` (new → prepend + cap 5; existing → replace in place) used by the WS handler; ticker keeps its 10s poll **as fallback while WS is down** (poll continues; WS presence doesn't remove the safety net — simpler: keep polling always, WS just makes it immediate. Decision: **keep both**, document in file header).

- [ ] **Step 1: Write the failing tests** — `frontend/src/__tests__/alertsSocket.spec.js`:

```js
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { connectAlerts } from "../api/alertsSocket.js";
import { clearTokens, setTokens } from "../api/token.js";

const pair = { access_token: "at", refresh_token: "rt", expires_in: 43200 };

class FakeSocket {
  static instances = [];
  constructor(url, protocols) {
    this.url = url;
    this.protocols = protocols;
    this.sent = [];
    FakeSocket.instances.push(this);
  }
  send(data) { this.sent.push(data); }
  close() { this.closed = true; }
  // test helpers
  emit(data) { this.onmessage?.({ data: JSON.stringify(data) }); }
}

beforeEach(() => {
  FakeSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeSocket);
  setTokens(pair);
  vi.useFakeTimers();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  clearTokens();
});

describe("connectAlerts", () => {
  it("dials with the jwt subprotocol", () => {
    const handle = connectAlerts({ onEvent: () => {} });
    const sock = FakeSocket.instances[0];
    expect(sock.protocols).toEqual(["cambrain.jwt.at"]);
    expect(sock.url).toContain("/api/v1/ws/alerts");
    handle.close();
  });

  it("invokes onEvent for event frames only", () => {
    const onEvent = vi.fn();
    const handle = connectAlerts({ onEvent });
    const sock = FakeSocket.instances[0];
    sock.emit({ type: "heartbeat", data: { ts: "x" } });
    expect(onEvent).not.toHaveBeenCalled();
    const event = { type: "event", data: { id: 9, summary: "p" } };
    sock.emit(event);
    expect(onEvent).toHaveBeenCalledWith(event.data);
    handle.close();
  });

  it("reconnects with backoff after a drop", () => {
    const handle = connectAlerts({ onEvent: () => {} });
    const sock = FakeSocket.instances[0];
    sock.onerror?.();
    sock.onclose?.();
    expect(FakeSocket.instances).toHaveLength(1);
    vi.advanceTimersByTime(1_100);
    expect(FakeSocket.instances.length).toBeGreaterThanOrEqual(2);
    handle.close();
  });
});
```

Extend `ticker.spec.js` with one case: mounting the ticker calls `store.load()` **and** opens a socket (assert `FakeSocket.instances.length === 1` after stubbing global WebSocket in that test); keep the existing poll assertions (fallback behavior).

- [ ] **Step 2: Run to verify it fails**

Run (in `frontend/`): `npm test -- --run alertsSocket`
Expected: FAIL — cannot resolve `../api/alertsSocket.js`.

- [ ] **Step 3: Implement**

`frontend/src/api/alertsSocket.js`:

```js
/**
 * /ws/alerts client (API §3): subprotocol auth, heartbeat watchdog,
 * jittered 1s→30s reconnect. The ticker's 10s poll stays as the fallback
 * so a dead socket degrades to Phase-4 behaviour, never to silence.
 * @module api/alertsSocket
 */

import { getAccessToken } from "./token.js";

const RECONNECT_BASE_MS = 1_000;
const RECONNECT_MAX_MS = 30_000;
const HEARTBEAT_TIMEOUT_MS = 45_000;

/** Derive the ws:// endpoint from the same base the REST client uses. */
function alertsUrl() {
  const base = import.meta.env?.VITE_API_BASE ?? "http://127.0.0.1:8765";
  return `${base.replace(/^http/, "ws")}/api/v1/ws/alerts`;
}

/**
 * Open the alerts socket; returns a handle whose close() stops everything.
 * @param {object} hooks onEvent(data), onOpen(), onClose()
 * @returns {{close: () => void}} teardown
 */
export function connectAlerts({ onEvent, onOpen, onClose } = {}) {
  let socket = null;
  let closed = false;
  let attempt = 0;
  let watchdog = null;
  let reconnectTimer = null;

  function teardownWatchdog() {
    if (watchdog !== null) {
      clearTimeout(watchdog);
      watchdog = null;
    }
  }

  function armWatchdog() {
    teardownWatchdog();
    watchdog = setTimeout(() => socket?.close(), HEARTBEAT_TIMEOUT_MS);
  }

  function scheduleReconnect() {
    if (closed) return;
    const delay =
      Math.min(RECONNECT_BASE_MS * 2 ** attempt, RECONNECT_MAX_MS) *
      (0.8 + Math.random() * 0.4);
    attempt += 1;
    reconnectTimer = setTimeout(dial, delay);
  }

  function dial() {
    const token = getAccessToken();
    if (!token) {
      scheduleReconnect();
      return;
    }
    socket = new WebSocket(alertsUrl(), `cambrain.jwt.${token}`);
    socket.onopen = () => {
      attempt = 0;
      armWatchdog();
      onOpen?.();
    };
    socket.onmessage = (evt) => {
      armWatchdog();
      let frame;
      try {
        frame = JSON.parse(evt.data);
      } catch {
        return;
      }
      if (frame?.type === "event") onEvent?.(frame.data);
    };
    socket.onclose = () => {
      teardownWatchdog();
      onClose?.();
      scheduleReconnect();
    };
    socket.onerror = () => socket.close();
  }

  dial();

  return {
    close() {
      closed = true;
      teardownWatchdog();
      if (reconnectTimer !== null) clearTimeout(reconnectTimer);
      socket?.close();
    },
  };
}
```

`stores/events.js` — add action:

```js
    /**
     * Insert or replace one event from a WS frame; keeps five, newest first.
     * @param {object} event EventOut payload
     */
    upsert(event) {
      if (!event?.id) return;
      const rest = this.events.filter((e) => e.id !== event.id);
      this.events = [event, ...rest].slice(0, 5);
    },
```

`EventTicker.vue` — keep the interval, add WS:

```js
import { connectAlerts } from "../api/alertsSocket.js";

let socketHandle = null;

onMounted(() => {
  store.load();
  timer = setInterval(() => store.load(), POLL_MS);
  socketHandle = connectAlerts({
    onEvent: (event) => store.upsert(event),
    onOpen: () => store.load(),   // resync after every (re)connect
  });
});

onBeforeUnmount(() => {
  ...clearInterval...
  socketHandle?.close();
});
```

- [ ] **Step 4: Run to verify it passes**

Run (in `frontend/`): `npm run format; if ($?) { npm run lint }; if ($?) { npm test }; if ($?) { npm run build }`
Expected: all tests pass (164 + new), build green.

- [ ] **Step 5: Commit**

Message (`feat(frontend): live alerts over /ws/alerts with poll fallback`):
body: `The ticker opens the alerts socket with subprotocol auth, upserts events as they fire, resyncs via GET /events on every reconnect, and keeps the 10s poll as the degradation path (API A3, phase-4 D6 retired).`

---

### Task 17: Notifiers panel in System settings

**Files:**
- Create: `frontend/src/settings/NotifiersPanel.vue`
- Modify: `frontend/src/settings/SystemView.vue` (render panel for admins)
- Test: `frontend/src/__tests__/notifiers.spec.js`

**Interfaces:**
- Consumes: `get/post/patch/del` from `api/client.js`, `NotifierOut` (`id`, `kind`, `enabled`, `config`, `has_token`), `POST /notifiers/test` → `{ok, response?, error?}`, RoleGate/admin check pattern from `UsersView.vue`.
- Produces: `NotifiersPanel.vue` — list rows (kind + enabled toggle + "token set" indicator from `has_token`), add form (kind=telegram: chat_id + bot_token inputs — token write-only), Test button → `aria-live` result, delete; testids `notifiers-panel`, `notifier-row-*`, `notifier-add`, `field-chat_id`, `field-bot_token`, `notifier-test`, `notifier-test-result`, `notifier-save`.

- [ ] **Step 1: Write the failing test** — `frontend/src/__tests__/notifiers.spec.js` (UsersView.spec pattern: pinia + fetch double):

```js
// cases:
// 1. renders rows from GET /notifiers, shows "token set" when has_token,
//    never renders bot_token (response has no such field — assert JSON of
//    rendered state has no token material)
// 2. add form POSTs {kind:"telegram", enabled:true, config:{chat_id, bot_token}}
// 3. Test button POSTs /notifiers/test and renders ok/error into aria-live
// 4. viewer role hides the panel (or disables controls) — match UsersView
```

(Write the four tests concretely following `users.spec.js` helpers: `jsonRes`, `envelope`, `setTokens`, `adminHeaders` if exported.)

- [ ] **Step 2: Run to verify it fails**

Run (in `frontend/`): `npm test -- --run notifiers`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement** `NotifiersPanel.vue` following `UsersView.vue`'s structure (local refs + load on mount + inline form). Telegram only in the form (`kind` fixed), `has_token` renders "Token set ✓" instead of any secret, Test button guarded (403 → viewer never sees it: wrap in `v-if="isAdmin"` — read how SystemView learns the role; `stores/auth` has `role`). Wire into SystemView below the cameras list with `v-if="auth.role === 'admin'"`.

- [ ] **Step 4: Run to verify it passes**

Run (in `frontend/`): `npm run format; if ($?) { npm run lint }; if ($?) { npm test }; if ($?) { npm run build }`
Expected: green.

- [ ] **Step 5: Commit**

Message (`feat(frontend): notifier configuration with write-only secrets`):
body: `The System page gains the Telegram panel the Phase-4 comment promised: chat id and token are entered once, the token only ever surfaces as has_token (API A7.4), and Test sends a real message whose verbatim result lands in an aria-live region.`

---

### Task 18: Docs, gate, PR

**Files:**
- Modify: `docs/API.md` (clip Range note already present L356 — verify; WS section exists L414 — verify it matches shipped subprotocol/heartbeat; `image_b64` at rules test L283 — remove the "not implemented in Phase 3" deferral; system/status stats L404 exists — verify; rate-limit table L508 already documents rows — now true; notifiers has_token)
- Modify: `docs/DATABASE.md` (§4.7 add `last_attempt_at`; §4.7 `camera_id` nullable note; §6 `bot_token_enc` inside notifier_config — already documented, verify)
- Modify: `docs/tasks.md` (tick all 8 Phase-5 boxes)
- Create: `.tmp/gate-5.mjs` (headed Playwright walkthrough)
- Create: PR

**Gate checklist (spec §11 row 5: "A Telegram photo arrives at 02:00"):**

1. Start stack: uvicorn :8765 with `CAMBRAIN_RUNTIME=1`, MediaMTX :8554 + `publish.py` loop, vite :5173.
2. Mock Telegram capture: a tiny local HTTP server (`python -m http.server` won't do — needs POST capture): `.tmp/mock_telegram.py` using `http.server` that records POSTs (path/body/headers) to `.tmp/telegram_capture.json` and returns `{"ok":true,"result":{"message_id":1}}`. Point `CAMBRAIN_TELEGRAM_API_BASE=http://127.0.0.1:8799` at it.
3. Configure via UI (headed Playwright, screenshots → `.tmp/gate-5-*.png`):
   - login → System → add Telegram notifier (chat_id `gate`, token `SECRET-GATE-TOKEN`) → Test → success aria-live (gate-5-1).
   - Camera "Shop Front" already exists; wait for `/system/status` to show `frame_width` (bridge) — verify dims no longer `—×—` on the events page overlay (gate-5-2).
   - Create ROI + rule (person, confidence 0.4, cooldown 1s, notify on) on the camera.
4. Trigger: `publish.py` loop runs a person-ish moving scene; wait for the event: ticker shows it via WS (gate-5-3: ticker entry), events page shows still + (after 20s) clip playing inline (gate-5-4, gate-5-5).
5. Delivery proof: `.tmp/telegram_capture.json` contains a `sendPhoto` (or `sendVideo`) POST with the bot token in path and `chat_id` in body (gate-5-6). Assert programmatically in the gate script.
6. Offline proof (optional but in matrix): stop the mock → fire another event → `delivery_status='pending'`, attempts ≥1 → restart mock → next sweep sends it (`test_offline_event_survives` covers unit; live check is bonus).
7. Retention/quota smoke: `PATCH /settings` retention_days=0, insert an old event, POST nothing — covered by unit tests; live: run `prune_events` once from a script against the live DB, confirm rows/files gone (gate-5-7).
8. Frontend loop + backend loop both green; `npm run build`.

Gate script follows `.tmp/gate-4.18.mjs` conventions (BASE, screenshots dir, headed chromium, PLAYWRIGHT_BROWSERS_PATH).

**PR flow:** branch `phase-5-alerting` → commits per task → push → PR with body summarizing the phase + gate evidence → PR-Agent `/review` via `gh api .../issues/{N}/comments` (persistent comment, poll for marker) → disposition findings → tick tasks.md → merge → delete branch. Direct pushes to main are blocked.

- [ ] **Step 1: Docs edits** (checklist above, each line verified against shipped code).
- [ ] **Step 2: Loops green.**
- [ ] **Step 3: Gate run** — all screenshots captured, capture file proves sendPhoto.
- [ ] **Step 4: Commit docs + tasks ticks** — `docs(phase-5): amend living docs and tick tasks`.
- [ ] **Step 5: PR + review + merge** — conventional body, no Co-Authored-By.

---

## Execution ledger

| Task | Status | Date | Evidence | Notes |
|---|---|---|---|---|
| 1 Alert contract | pending | | | |
| 2 FrameRingBuffer | pending | | | |
| 3 ClipWriter | pending | | | |
| 4 Persistence + p5a | pending | | | |
| 5 Hub + /ws/alerts | pending | | | |
| 6 AlertHandler | pending | | | |
| 7 Notifier/Telegram/WhatsApp | pending | | | |
| 8 Secrets + /notifiers/test | pending | | | |
| 9 DeliveryWorker + stats | pending | | | |
| 10 Clip route | pending | | | |
| 11 Retention | pending | | | |
| 12 System events + p5b | pending | | | |
| 13 Runtime + lifespan | pending | | | |
| 14 Rate limiter | pending | | | |
| 15 Still replay | pending | | | |
| 16 Frontend WS | pending | | | |
| 17 Notifiers UI | pending | | | |
| 18 Docs + gate + PR | pending | | | |

## Gates

**Phase 5 gate — "a Telegram photo arrives at 2am":** scripted headed-Playwright walkthrough (Task 18) proving: (1) motion on the live camera produces an event visible in the ticker within the WS frame, (2) the still and (after 20s) the clip render on the events page, (3) `.tmp/telegram_capture.json` holds a sendPhoto/sendVideo POST from the delivery worker, (4) frame dims are no longer `—×—` (bridge), (5) notifier Test button returns success in aria-live, (6) retention prunes a planted old event + its files, (7) full backend + frontend loops green.

**Verification matrix (spec §12 additions):**

| Row | Test |
|---|---|
| Ring holds ten seconds | `test_ring_buffer.py::test_holds_ten_seconds` |
| Quota refuses writes | `test_clip_writer.py::test_quota_refuses_writes` |
| Offline event survives | `test_telegram.py::test_offline_event_survives` |
| Backoff capped at 1h | `test_delivery.py::test_backoff_grows_and_caps` |
| Cross-tenant WS silent | `test_ws_alerts.py::test_cross_site_broadcast_never_arrives` |
| Token never returned | `test_api_settings.py::test_notifier_token_is_encrypted_and_masked` |

## Definition of done

- [ ] Every task's acceptance checkboxes ticked in this file; ledger complete.
- [ ] Backend: `pytest -m "not rtsp and not slow"` green (baseline 276 + new), ruff + mypy clean; migrations upgrade/downgrade roundtrip (`p5a`, `p5b`) green.
- [ ] Frontend: format + lint + `npm test` + `npm run build` green.
- [ ] `docs/API.md`, `docs/DATABASE.md` match shipped behaviour; `docs/tasks.md` Phase 5 all ticked.
- [ ] Gate walkthrough evidence recorded; verification-matrix rows pass.
- [ ] PR reviewed by PR-Agent `/review`, findings dispositioned, merged; branch deleted.
