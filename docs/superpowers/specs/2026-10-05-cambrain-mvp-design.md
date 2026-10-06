# CamBrain MVP — Design Specification

**Date:** 2026-10-05
**Status:** Approved for planning
**Author:** Claude Opus 4.8 (1M context)
**Plan:** [`../plans/2026-10-05-cambrain-mvp-plan.md`](../plans/2026-10-05-cambrain-mvp-plan.md)

---

## 1. Purpose

This document is the **specification the implementation plan argues from**. It is not a restatement of the ten living documents in `docs/` — those specify the product, the architecture, the schema, the API, and the security posture. This document specifies **what gets built, in what order, and what proves it is correct.**

Read the living docs for *why* and *what*. Read this for *how the build is sequenced and verified*.

| Document | Answers |
|---|---|
| [`prd.md`](../../prd.md) | Who is this for, what must it do |
| [`architecture.md`](../../architecture.md) | How the components fit |
| [`DATABASE.md`](../../DATABASE.md) | What the schema is |
| [`API.md`](../../API.md) | What the HTTP surface is |
| [`SECURITY.md`](../../SECURITY.md) | What the trust boundaries are |
| [`memory.md`](../../memory.md) | Why each decision was made |
| **This spec** | What order, what gate, what proof |
| [The plan](../plans/2026-10-05-cambrain-mvp-plan.md) | The exact steps |

---

## 2. What the MVP is

A Windows-first edge appliance that installs alongside existing NVR/VMS software, opens its own RTSP connections to cameras the customer already owns, detects objects, applies per-camera rules, saves short event clips, and delivers alerts to Telegram.

**The single sentence that constrains every decision:** the customer's existing recorder must keep working, untouched, whether CamBrain is running or not.

### 2.1 Success criteria

A first-time user adds a camera, draws one ROI, sets one rule, and receives a real Telegram alert for an intruding person **without contacting support.** (`prd.md` §4)

This is the acceptance test for the whole build. Every phase exists to make that sentence more achievable.

### 2.2 Non-goals

Explicitly out of the MVP. These are sequenced, not rejected.

- Continuous recording — CamBrain is not an NVR
- Cloud sync, central fleet console, any hosted component
- Behavioural detection — loitering, fall, mask removal
- Facial recognition or any biometric identifier
- PPE / helmet detection
- Mobile app — Telegram *is* the mobile app
- Per-camera subscription billing
- WebRTC live view
- ONVIF camera discovery
- Celery / Redis
- Linux appliance build (the engine is OS-agnostic; only the tray shell is platform-bound)

---

## 3. Environment baseline

Verified against the development machine on 2026-10-05. These are facts, not assumptions, and they determine what Phase 0 must fix.

| Component | State | Action needed |
|---|---|---|
| Python | 3.13.13 | none |
| Node | 24.19.0 | none |
| npm | 11.17.0 | none |
| Cargo / Rust | **not installed** | install for Tauri (Phase 6) |
| Docker Desktop | installed, **daemon not running** | must be started for RTSP tests |
| `ffmpeg` on PATH | **not installed** | PyAV bundles its own FFmpeg, so not required — but needed to author new fixtures by hand |
| `av` (PyAV) | not installed | Phase 0 |
| `onnxruntime` | not installed | Phase 0 |
| `sqlalchemy`, `alembic` | not installed | Phase 0 |
| `opencv` | not installed | Phase 0 |
| `cryptography`, `structlog`, `httpx` | not installed | Phase 0 |
| `fastapi` | 0.140.0 installed | satisfied |
| `numpy` | 2.4.6 installed | satisfied |
| `pytest` | 9.1.1 installed | satisfied |
| `pytest-asyncio` | 1.4.0 installed | satisfied |
| Git | repo initialised, **1 commit** (`b2f886c intial commit`) | — |
| Model weights | none present | fetched by script, checksum-pinned |

**Why this baseline justifies Phase 0 as a real phase.** Eight missing runtime packages and a stopped Docker daemon are exactly the conditions under which a Phase 1 failure is ambiguous: is the streaming code broken, or is ONNX Runtime not installed? Phase 0 exists so that every later failure is unambiguously a code failure.

---

## 4. Design decisions made during planning

These are decisions taken in the brainstorming session that supplement — and in two cases narrow — the existing decision log. Recorded here so the plan has a single place to read them from.

### D16 — Bootstrap is a numbered phase, not an implicit prerequisite

**Decided:** planning. **Status:** locked.

The six-phase model in `tasks.md` had no entry for environment setup. Folding it into Phase 1 means a missing package surfaces as a confusing test failure in the streaming engine.

Phase 0 is therefore a real phase with a real gate: `pytest` runs green, `ruff` and `mypy` are clean, MediaMTX answers, a synthetic clip decodes, and the CI licence scan is configured.

**Cost:** one extra step. **Benefit:** no ambiguity between "broken code" and "broken environment" for the rest of the build.

### D17 — YOLOX-s ships as the provisional default; RT-DETR stays swappable

**Decided:** planning. **Status:** provisional, benchmark pending.

`memory.md` D2 defers the model choice to a Phase 3 benchmark that cannot run — no cameras are available, and the benchmark requires real footage.

Two options were considered:

| Option | Assessment |
|---|---|
| Build both decoders now | Rejected. Doubles Phase 3 inference work for a choice that is measurement-driven. RT-DETR's decoder would be written without ever having run it against a real export. |
| Mock detector until hardware exists | Rejected. Defers all inference work behind a blocked benchmark; Phase 3 would have no deliverable. |
| **YOLOX-s now, benchmark alongside** | **Chosen.** |

**Why YOLOX specifically:**

- All size variants share one I/O signature — input `[1,3,H,W]`, output `[1,8400,85]`. Tiering `nano → s → m` costs **zero** decoder changes, so the hardware tiering in `architecture.md` §6 is free.
- RT-DETR outputs a different structure and needs no NMS, so it is a genuinely separate decoder. Writing that blind is guesswork.

**The swap contract.** `Detector` is a Protocol. Swapping to RT-DETR later requires:

1. One new module `app/services/inference/rtdetr_post.py` implementing its decode.
2. One new `Detector` implementation bound in the same factory that Task 3.2 creates.
3. `models/LICENSE-MODEL-NOTICE` updated with the new model.
4. No change to `CameraPipeline`, `StreamManager`, the rules engine, the API, or the UI.

**What stays unvalidated until the benchmark:** night/IR accuracy, small-distant-object recall, and real latency on N100 silicon. These are recorded as risks in §10, not glossed over.

### D18 — Real RTSP is tested against MediaMTX in Docker

**Decided:** planning. **Status:** locked.

`memory.md` D14 establishes that no cameras are available, so every test must run from fixtures. A mock could satisfy that, but it would never exercise the code most likely to be wrong: PyAV RTSP option handling, handshake behaviour, and reconnection against a real server.

MediaMTX runs in a container, streams a local `.mp4` over real RTSP, and the existing `RtspSource` connects to it unmodified. Nothing is stubbed.

- Tests are marked `@pytest.mark.rtsp` and excluded by default locally: `pytest -m "not rtsp"`.
- The full suite including RTSP requires the Docker daemon running. Phase 0 starts it once and verifies reachability.
- If Docker is unavailable, RTSP tests skip with a clear message rather than fail — but they must never silently pass.

**The property this buys:** the production path is tested. Every other option tests a fiction.

### D19 — TDD per task, with test cases named in the plan

**Decided:** planning. **Status:** locked.

Every task in the plan names its test cases before it names its implementation. The two cases that matter most are specified up front because they are the canaries for whole bug classes:

- `test_memory_is_flat_across_reconnects` — 50 reconnect cycles, asserting resident memory plateaus. Catches the leak class that otherwise surfaces after a week of unattended uptime.
- `test_no_secret_in_log_output` — proves the redaction guarantee structurally.

Writing tests per-phase rather than per-task was rejected: memory and backpressure defects localise far better when the test lands with the code that causes them.

### D20 — Dependency version floors, then a generated lock

**Decided:** planning. **Status:** locked.

`requirements.txt` carries minimum-version floors (`av>=13.0.0`), not hand-written exact pins. Fabricating exact patch versions that may not resolve would break the install on first try — a self-inflicted Phase 0 failure.

The exact versions are captured in `requirements.lock.txt`, generated by `pip freeze` at install time. CI installs from the lock; local development may use the floors.

**This is a deliberate trade:** floors are more portable, the lock is more reproducible, and we get both by committing the generated lock.

### D21 — `opencv-python-headless`, not `opencv-python`

**Decided:** planning. **Status:** locked.

We need `cv2.createBackgroundSubtractorMOG2` and `cv2.VideoWriter`. The full `opencv-python` wheel bundles Qt GUI libraries, adding roughly 80MB to the Windows installer for a product whose entire UI renders in a web view.

Headless is the correct build. Documented here because a future contributor reaching for `opencv-python` out of habit would silently reintroduce 80MB.

---

## 5. Component contracts

The seams. `architecture.md` §2 names these units; this section fixes their **signatures**, because the plan's tasks depend on the exact names and types.

A component is unit-testable if it can be replaced by a conforming double without touching its consumers. That is the test applied to every boundary below.

### 5.1 `FrameSource` — the most important boundary

Because every source implements it, the entire pipeline is testable from a file on disk and CI needs no cameras. Because it is narrow, a new source is one class.

```python
@dataclass(frozen=True, slots=True)
class Frame:
    """One decoded frame.

    Frozen so a consumer cannot mutate a frame another consumer holds.
    `slots` because these are allocated continuously and per-instance
    __dict__ overhead is measurable at 8 cameras x 15fps.
    """
    data: np.ndarray          # (H, W, 3) uint8 RGB. Owned, never a borrowed view.
    timestamp: float          # monotonic seconds from capture
    width: int
    height: int


class FrameSource(Protocol):
    """Produces frames from something. The seam that removes hardware dependency."""

    async def frames(self) -> AsyncIterator[Frame]:
        """Yield frames until cancelled or the source is exhausted."""
        ...

    async def close(self) -> None:
        """Release every resource. Must be idempotent and safe after cancellation."""
        ...
```

**Contract requirements, all of which are tested:**

| Requirement | Why |
|---|---|
| `close()` is idempotent | `StreamManager.stop()` and pipeline self-cancellation can both call it |
| `close()` is safe mid-iteration | Cancellation arrives at an arbitrary `await` |
| `close()` runs in `finally` on every path | The leak class `test_memory_is_flat_across_reconnects` exists to catch |
| `Frame.data` is owned, not a view | A consumer retaining a borrowed view reads freed decoder memory |
| The iterator ends on cancellation | A pipeline awaiting a frame must unblock |

**Implementations:** `RtspSource` (PyAV container, backoff, stall watchdog), `FileSource` (local clip, loop or once).

### 5.2 Backpressure — `LatestFrameSlot`

The single most important streaming rule: **a full queue means replace the oldest frame. Never block, never accumulate.**

If inference falls behind reality, we want stale frames dropped — not a growing backlog that consumes RAM and adds latency to every alert.

```python
class LatestFrameSlot:
    """Single-slot mailbox. Newer frames overwrite older ones.

    Backs onto asyncio.Queue(maxsize=1) but drops rather than blocks, so a
    slow consumer never back-pressures the source.
    """
    async def put(self, frame: Frame) -> None: ...
    async def get(self, timeout: float | None = None) -> Frame | None: ...
    def close(self) -> None: ...
    @property
    def dropped(self) -> int: ...   # observability; the soak test asserts on this
```

The `dropped` counter is not instrumentation for its own sake. It is how a field report of "the image froze" is diagnosed without attaching a debugger to a customer's box.

### 5.3 `Detector` — the licensing boundary

```python
@dataclass(frozen=True, slots=True)
class Detection:
    class_name: str        # COCO name, never an index
    confidence: float      # 0.0-1.0
    bbox: tuple[int, int, int, int]   # (x1, y1, x2, y2) in frame pixels


class Detector(Protocol):
    async def infer(self, frame: Frame) -> list[Detection]: ...
    async def close(self) -> None: ...
```

**Classes are names, not indices.** YOLOX and RT-DETR do not share an output ordering. Storing indices would silently repoint every configured rule at the wrong class when D17 is resolved. This applies to the rules table as well as the detector output.

### 5.4 `MotionGate` — what makes cheap hardware viable

A 1080p camera at 15fps delivers 15 frames/sec. MOG2 background subtraction costs a few milliseconds; the detector costs tens. The gate is the entire reason 8 cameras fit on a 6-watt N100.

```python
class MotionGate:
    def update(self, frame: Frame) -> bool:
        """Return True when the frame warrants inference.

        Must handle the brightness-shift failure: a camera switching to IR at
        dusk changes every pixel at once. Without an explicit reset the
        background model treats the transition as motion and fires a burst of
        false alerts at exactly the hour the customer most needs trust.
        """
        ...
    def reset(self) -> None: ...
```

### 5.5 `RulesEngine` — pure, and the highest-value test surface

```python
@dataclass(frozen=True, slots=True)
class RuleOutcome:
    fired: bool
    checks: tuple[RuleCheck, ...]   # per-condition, for the debug endpoint


class RulesEngine:
    def evaluate(
        self,
        track: TrackedObject,
        config: RuleConfig,
        now: datetime,        # timezone-aware; the engine never calls utcnow()
    ) -> RuleOutcome:
        """Pure function. No IO, no clock reads, no notification side effects."""
        ...
```

**Purity is the requirement, not a style preference.** It is what makes table-driven testing possible across active-hours boundaries, timezones, and cooldown state — the conditions where false positives are actually generated. An engine that reads the clock internally cannot be tested at 02:30.

Per-condition `checks` exist because a binary "rule did not fire" is unactionable for the shop owner. `POST /api/v1/rules/{id}/test` returns them.

### 5.6 `Notifier` — where the product's promise is kept

```python
class Notifier(Protocol):
    async def send(self, event: Event) -> None: ...
```

Notification failure **must never** lose an event. Everything before `Notifier` is local and durable: clip on disk, rows in SQLite, broadcast to the dashboard. Telegram is the only egress path in the entire system, and it is allowed to fail.

---

## 6. Data contracts

Full schema in [`DATABASE.md`](../../DATABASE.md). Four constraints that shape the build:

1. **`site_id` on every domain table, always from the token.** Cross-tenant access returns **404, never 403** — a 403 confirms the row exists.
2. **ROI coordinates are normalised 0..1.** Pixels fail silently on a resolution change, alerting on the wrong area.
3. **`rtsp_url` stores no credentials.** Username and password are separate encrypted columns, so the URL is safe to log, display, and export.
4. **Clip paths are generated from `events.id`** — `clips/{id}.mp4` — never from `camera.name`, which is user input.

**SQLite, not PostgreSQL.** The deployment model decides the database: zero administration, one file, no service the customer maintains. WAL mode so dashboard reads never block pipeline writes; `foreign_keys=ON` because SQLite disables FK enforcement by default and the schema's integrity is decorative without it.

Access is confined to a repository layer, so a future fleet console can use PostgreSQL without touching the edge box.

---

## 7. Build sequence

Seven phases. Each ends with something demonstrable; no phase ends with work that cannot be shown working.

| Phase | Deliverable | Gate — what proves it |
|---|---|---|
| **0** | Bootstrap: env, deps, fixtures, RTSP harness, CI guard | Suite green, ruff/mypy clean, MediaMTX answers, synthetic clip decodes, licence scan wired |
| **1** | Streaming engine | Ingests, samples, gates motion, survives 50 reconnects with flat memory |
| **2** | Database + REST API | CRUD works, cross-tenant returns 404, OpenAPI matches `API.md` |
| **3** | Inference + ROI + rules | A real alert fires from a real clip, under 2s |
| **4** | Dashboard + ROI editor | A non-technical user configures a camera unaided |
| **5** | Alerting + event log | A Telegram photo arrives at 02:00 |
| **6** | Packaging + operations | Installs, survives reboot, survives 24h soak |

### 7.1 Dependency order

```
Phase 0 ──> Phase 1 ──> Phase 3 ──> Phase 5 ──> Phase 6
                │          ↑          │
                └─> Phase 2 ─────────┘
                     │
                     └─> Phase 4 ──> (needs 1, 2, 3 for a meaningful screen)
```

**Phase 2 runs parallel to Phase 1** — the database and API need no stream. **Phase 4 depends on 1, 2, and 3** because the ROI editor is meaningless without a camera, and the event log is empty without rules. **Phase 5 needs Phase 3** — there is nothing to alert on until detection works.

### 7.2 Why the gates are written this way

Each gate is a *demonstration*, not a status report:

- Phase 1's gate is a **memory measurement**, because the failure mode of a streaming engine is a slow leak invisible until a customer finds it after a week.
- Phase 3's gate is a **real alert from a real clip**, because a detector that runs without producing a correct alert has proven nothing about accuracy — only about plumbing.
- Phase 6's gate is a **24-hour soak**, because that is the only duration that matters to a customer who leaves it running unattended.

---

## 8. Test strategy

### 8.1 The hardware-free rule

**No test may require a camera.** No cameras are available (`memory.md` D14), and the dependency must not be allowed to form. Every test runs from one of:

- A generated synthetic clip via `FileSource`
- A `MockDetector` returning fixture detections
- MediaMTX in Docker, streaming a local file over real RTSP

This is why `FrameSource` exists. A boundary that exists only for testing is a boundary that rots; this one is load-bearing for the entire test strategy.

### 8.2 Fixture strategy

`tests/make_fixtures.py` generates clips programmatically, so they are reproducible and reviewable as code:

| Fixture | Content | Proves |
|---|---|---|
| `static.mp4` | Still frame, 300 frames | Gate stays closed — no false alerts |
| `motion.mp4` | Shape translating across frame | Gate opens |
| `brightness_shift.mp4` | Day → night cut at frame 150 | Gate resets instead of firing a burst |
| `low_light.mp4` | IR-lit, low contrast, person-sized blob | Night-path behaviour |
| `multi_object.mp4` | Three objects, one entering an ROI | ROI boundary logic |

Clips are **gitignored and rebuilt on demand** — binary test data in git is unreviewable and inflates the repo.

### 8.3 Test layers

| Layer | Location | Scope |
|---|---|---|
| Unit | `tests/test_*.py` | One component, no IO. Fastest, most numerous |
| Integration | `tests/test_pipeline.py`, `tests/test_api_*.py` | Components wired together, real SQLite, MockDetector |
| RTSP | `tests/rtsp/` — marked `rtsp` | Real PyAV against real MediaMTX |
| Soak | `tests/test_soak.py` — marked `slow` | 24h memory and handle stability |

**Default local run:** `pytest -m "not rtsp and not slow"`. **Full CI run:** `pytest`.

### 8.4 The canary tests

Two tests stand above the rest, because they cover whole bug classes rather than single functions:

**`test_memory_is_flat_across_reconnects`** — 50 reconnect cycles against MediaMTX, sampling RSS via `psutil`. Asserts the trend is flat, not that memory is low. A test asserting an absolute ceiling passes on a fast leak and fails on a slow one; a trend assertion catches both. This is the test that turns "customers find it broken after a week" into a CI failure.

**`test_no_secret_in_log_output`** — logs a struct containing every key in `REDACT_KEYS` plus an RTSP URL with embedded credentials, then asserts none of the values appear in captured output. Because redaction is a structlog processor rather than a call-site convention, this test verifies a *structural* property: there is no code path that bypasses the chain.

### 8.5 Coverage discipline

Coverage percentage is not a target. The three areas that must have near-complete branch coverage, because a gap there is a product failure:

1. `rtsp_source.py` — reconnect, stall, backoff. A bug here is a camera that silently stops.
2. `yolox_post.py` — decode and NMS. Wrong boxes mean alerts on the wrong thing.
3. `rules.py` — every branch. This is the false-positive surface.

---

## 9. Definition of done

A phase is done when **all** of the following hold. Not "code written."

1. Every test named in the plan's tasks for that phase exists and passes.
2. The phase's gate demonstration has been run and observed.
3. `ruff check` and `mypy` are clean.
4. Every new public function has a Google-style docstring; every module has a module docstring.
5. No secret is logged, returned by an API, or written to the database in plaintext — verified by test, not by inspection.
6. `git status` shows no weights, database files, clips, or `.env`.
7. The commit message explains **why**, per `CODE_STYLE.md` §7.

---

## 10. Risks

Carried forward from `tasks.md`, with the spec's own additions.

| Risk | Impact | Mitigation | Residual after this plan |
|---|---|---|---|
| **No cameras for testing** | Real RTSP quirks, vendor auth methods, sub-stream paths all unvalidated | `FrameSource` abstraction, synthetic fixtures, MediaMTX | **High** — MediaMTX is a conformant server, not a Hikvision. Vendor-specific behaviour remains unproven |
| **N100 throughput below target** | Fewer cameras per box, worse unit economics | Tier detection (D-tier fallback to nano @ 416) | **High** — unmeasurable without hardware |
| **False positives** | Customer disables alerts; product fails | ROI, cooldown, class filters, hours, dedupe | Medium — the rules engine is spec'd and tested, but tuned thresholds need field data |
| **Model choice unvalidated** | Wrong default for CCTV | YOLOX-s provisional, benchmark harness ships alongside (D17) | Medium — swap is one module; *which* model is right is unknown |
| **Night / IR accuracy** | Missed intrusions — the worst failure mode | `low_light.mp4` fixture, brightness-shift reset | **High** — a synthetic blob is not IR footage. Needs a real night test case |
| **Long unattended uptime** | Customers find it broken after a week | `test_memory_is_flat_across_reconnects` from Phase 1; 24h soak in Phase 6 | Low — the memory class is covered early |
| **Power-loss event loss** | Evidence lost at the worst moment | `synchronous=NORMAL` in WAL loses the last second | **Accepted** — clips on disk survive; orphan sweep reclaims. Revisit if a customer reports losing evidence |
| **Multi-process escape hatch vs SQLite** | Extra `SQLITE_BUSY` under contention | `busy_timeout=30000` already set | Low — not exercised unless the escape hatch is taken |

**The two High-residual risks are the same root cause: no hardware.** They are not mitigable by better engineering. They resolve when someone points a camera at the box.

---

## 11. Deferred decisions

Genuinely open. Each names what would close it.

| Question | Closes when | Current handling |
|---|---|---|
| YOLOX-s vs RT-DETR-r18 | Real footage benchmark on N100 | YOLOX-s ships as provisional default (D17); swap is one module |
| Night/IR accuracy | IR-lit night footage from a real camera | `low_light.mp4` synthetic fixture is a placeholder, not a substitute |
| Retention default (7 days) | Disk measurement on a real 128GB box | Configurable, default set per `DATABASE.md` |
| WhatsApp timing | Meta business verification lead time | `Notifier` Protocol reserved; adapter stubbed |
| Operators wanting smooth live video | Field feedback | MJPEG now; WebRTC deferred per `memory.md` |
| GUI vs Gujarati/Hindi localisation | Market input | Not started — likely valuable for Rajkot, unprompted so far |
| Model download vs bundled | Installer size and offline-install requirement | Download on first run with checksum verification |

---

## 12. Relationship to the living documents

This spec **adds** sequence, gates, contracts, and verification to the ten living documents. It does not override any of them.

**Conflicts are resolved in favour of the living documents.** Where this spec summarises, the living document is authoritative. If a summary here is wrong and the living document is right, the living document wins and this file gets corrected.

**This document is a spec, not a living document.** It describes the MVP as of 2026-10-05. When Phase 3's benchmark resolves D17, or a gate reveals a threshold needs adjusting, this file is updated and the plan revised — rather than the plan being improvised around.
