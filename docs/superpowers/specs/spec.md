# CamBrain — Full Specification

**Version:** 1.0
**Date:** 2026-10-05
**Status:** Approved for implementation planning
**Companion plan:** [`../plans/2026-10-05-cambrain-mvp-plan.md`](../plans/2026-10-05-cambrain-mvp-plan.md)

---

## How to read this document

This is the **complete technical specification for CamBrain MVP**. It is self-contained: an engineer can implement from this document plus the living documents in `docs/` without asking questions.

The ten living documents in `docs/` each own one concern and are authoritative for it. This file gathers the whole technical picture into one place and adds what none of them contain — build sequence, verification gates, and the acceptance criteria that define "done."

| Concern | Authoritative document |
|---|---|
| Product requirements, personas, NFRs | [`prd.md`](../../prd.md) |
| System architecture, component boundaries | [`architecture.md`](../../architecture.md) |
| Schema, indexes, retention | [`DATABASE.md`](../../DATABASE.md) |
| REST + WebSocket surface | [`API.md`](../../API.md) |
| Threat model, auth, secrets | [`SECURITY.md`](../../SECURITY.md) |
| Decision history and rationale | [`memory.md`](../../memory.md) |
| Style, conventions, git | [`CODE_STYLE.md`](../../CODE_STYLE.md) |
| Engineering laws | [`rules.md`](../../rules.md) |
| UI direction | [`design.md`](../../design.md) |
| Phase checklist | [`tasks.md`](../../tasks.md) |

**Where this document and a living document disagree, the living document wins** and this file is corrected.

---

## 1. Product specification

### 1.1 What CamBrain is

An edge AI sidecar for existing CCTV. It installs alongside the NVR or VMS software a customer already runs, opens its own RTSP connections to cameras they already own, detects objects, applies per-camera rules, saves short event clips, and delivers alerts to Telegram.

**The constraint that governs every decision:** the customer's existing recorder must keep working, untouched, whether CamBrain is running or not. CamBrain is a second, independent reader of the same RTSP endpoints — never a proxy, never a tap.

### 1.2 Personas

| Persona | Need | Success for them |
|---|---|---|
| **Ramesh** — retail owner, Rajkot | Know if someone walks in after hours | Alerts are real; setup takes one sitting |
| **Priya** — factory manager, GIDC | Alert on a person at the loading dock at 02:00 | False-positive rate is acceptable |
| **Arun** — installer | Hand over a box without a 40-page manual | No 6am call after a power cut |

Arun is the real channel in year one. Every "customer cannot configure this" defect is an Arun on-site visit.

### 1.3 MVP scope

**In scope:** RTSP camera management with connection testing · concurrent ingest (target 8) with auto-reconnect · 2–5 FPS sampling · motion pre-filter · object detection across all 80 COCO classes · polygon ROI per camera · per-camera rules (class allow-list, confidence, ROI, active hours, cooldown) · event clips with stills (10s pre-roll, 20s post-roll) · Telegram alerting · web dashboard with live grid, camera management, ROI editor, event log, rules editor · local accounts with admin/viewer roles · Windows tray app with autostart.

**Out of scope:** continuous recording · cloud sync · central fleet console · PPE/helmet detection · facial recognition · mobile app · per-camera billing · WebRTC · ONVIF discovery · Celery/Redis · Linux appliance.

### 1.4 MVP acceptance criterion

> A first-time user adds a camera, draws one ROI, sets one rule, and receives a real Telegram alert for an intruding person **without contacting support.**

Every phase exists to make this sentence more achievable.

### 1.5 Non-functional requirements

| Requirement | Target |
|---|---|
| Concurrent cameras | 8 per box (4 on low tier) |
| Hardware floor | Intel N100, 4-core, 6W, AVX2 + VNNI |
| Detection latency | < 2s from motion to alert |
| Sample rate | 2–5 FPS per camera, configurable |
| Reconnect, transient | ≤ 5s |
| Reconnect, persistent | jittered exponential backoff to 60s |
| Memory | flat across days — no per-frame or per-reconnect leak |
| Idle CPU | < 5% with no motion |
| Disk | event clips only, 7-day default, quota-capped |
| Resolution | works at 1080p input, downscale before inference |
| Uptime | survives 24h unattended |
| Offline | full function with internet down; only Telegram fails |
| Boot | starts on boot, no user login required |

Each is mapped to a proving test in §12.

---

## 2. Technology stack

**Mandated. Changes require a `memory.md` entry.**

| Layer | Technology | Licence |
|---|---|---|
| Language | Python 3.13 | — |
| Decode / transport | PyAV | BSD |
| Inference | ONNX Runtime (CPU) | MIT |
| Array maths | NumPy | MIT |
| Computer vision | opencv-python-headless | Apache-2.0 |
| API | FastAPI + Uvicorn | MIT / BSD |
| Validation | Pydantic + pydantic-settings | MIT |
| Database | SQLite (WAL) via SQLAlchemy 2.0 | MIT / Public Domain |
| Migrations | Alembic | MIT |
| Crypto | cryptography (Fernet, DPAPI) | Apache-2.0 / BSD-3 |
| Password hashing | argon2-cffi | MIT |
| HTTP client | httpx | BSD |
| Observability | structlog | MIT |
| Frontend framework | **Vue 3, JavaScript** | MIT |
| Build | Vite | MIT |
| Styling | Tailwind CSS | MIT |
| Components | shadcn-vue (Radix-Vue) | MIT |
| Shell | Tauri v2 | MIT / Apache-2.0 |
| Tests | pytest, pytest-asyncio, pytest-cov | MIT |
| RTSP test server | MediaMTX (Docker) | MIT |

**Explicitly excluded:** any `ultralytics` package · Celery · Redis · React · TypeScript · PostgreSQL · `opencv-python` (full build) · Node-based video transcoding.

### 2.1 Environment baseline

Verified on the development machine, 2026-10-05.

| Component | State | Action |
|---|---|---|
| Python | 3.13.13 | ready |
| Node | 24.19.0 | ready |
| npm | 11.17.0 | ready |
| Cargo / Rust | **absent** | install for Phase 6 |
| Docker Desktop | installed, **daemon stopped** | start for RTSP tests |
| `ffmpeg` on PATH | absent | not required — PyAV bundles FFmpeg |
| `av`, `onnxruntime`, `sqlalchemy`, `alembic`, `cv2`, `cryptography`, `structlog`, `httpx` | **absent** | install |
| `fastapi` 0.140.0, `numpy` 2.4.6, `pytest` 9.1.1, `pytest-asyncio` 1.4.0 | present | satisfied |
| Model weights | none | fetched by script, checksum-pinned |
| Git | initialised, 1 commit `b2f886c` | — |

---

## 3. Licensing compliance — hard constraint

**The most serious constraint in the project.** The product is sold closed-source. Any AGPL dependency reachable from the shipped application obliges disclosure of the whole application's source, which defeats the business model.

### 3.1 Prohibited

| Package | Licence | Note |
|---|---|---|
| `ultralytics` (YOLOv5, v8, v11, v26) | AGPL-3.0 | **Prohibited in all forms, including ONNX exports** |

Exporting AGPL weights to ONNX changes the file format. It does not change the licence attached to the weights. Shipping an ONNX file derived from AGPL weights into a commercial product does not escape copyleft — it is the mechanism by which the licence is most frequently violated unknowingly.

Ultralytics' own terms additionally require an Enterprise License for closed-source software and for edge deployments, explicitly listing "cameras" and "appliances" as triggers — which is exactly what this product is.

### 3.2 Permitted

| Model family | Licence | Post-processing |
|---|---|---|
| **YOLOX** (Megvii) | Apache-2.0 | anchor-free decode + NMS |
| RT-DETR | Apache-2.0 | none — outputs final boxes |
| DAMO-YOLO | Apache-2.0 | NMS |
| NanoDet, YOLOF, PaddleDetection | Apache-2.0 | varies |

### 3.3 Enforcement

- CI licence scan **fails the build on any AGPL identifier**, including dev and experimental branches.
- `models/*.onnx` is gitignored. Weights are fetched by `scripts/fetch_model.py` with SHA-256 verification.
- `models/LICENSE-MODEL-NOTICE` records provenance and licence per shipped weight file. Apache-2.0 requires attribution — this is a legal obligation, not a nicety.
- A model file with a checksum mismatch is a hard failure, never a warning.

---

## 4. Architecture specification

### 4.1 Deployment topology

```
  Customer premises (shop / factory)
  ┌──────────────────────────────────────────────────────────────┐
  │  Cameras 1-8 (existing hardware)                             │
  │         │ RTSP sub-stream 640×360 @ 10-15fps                 │
  │  ┌──────┴───────┐      ┌─────┴────────────────────────┐     │
  │  Existing NVR  │      │       CAMBRAIN                │     │
  │  / VMS         │      │  Tauri shell (Rust)           │     │
  │  keeps all     │      │   ├─ tray icon                │     │
  │  recording     │      │   ├─ autostart on boot        │     │
  │  untouched     │      │   └─ localhost proxy          │     │
  └───────────────┘      │  Python engine                │     │
                         │   ├─ FastAPI 127.0.0.1:8765    │     │
                         │   ├─ per-camera pipelines (N)  │     │
                         │   ├─ inference pool            │     │
                         │   ├─ motion gates (N)          │     │
                         │   ├─ rules engine              │     │
                         │   └─ notifiers                 │     │
                         │  SQLite (WAL)                 │     │
                         │  Vue 3 dashboard              │     │
                         └──────────┬────────────────────┘     │
                                    │ HTTPS outbound only     │
                          ┌─────────┴──────────┐              │
                          │  Telegram Bot API  │ ← sole egress│
                          └────────────────────┘              │
  └──────────────────────────────────────────────────────────────┘
```

### 4.2 Two invariants

1. **CamBrain opens its own RTSP connections.** It never proxies or depends on the NVR's stream. If the NVR stops, CamBrain keeps working; if CamBrain stops, the NVR is untouched.
2. **Exactly one egress path** — the notifier — carrying only what the customer explicitly asked to receive. No video stream, no telemetry, no update ping, no licence phone-home. CamBrain works fully offline; only alert delivery fails.

### 4.3 Concurrency model

**Single process. One thread per camera.** Not process-per-camera.

| Decision | Rationale |
|---|---|
| Threads, not processes | PyAV decode and ONNX Runtime `run()` both release the GIL during actual compute — the usual GIL objection does not apply to precisely the two operations that dominate our cost |
| One `InferenceSession` per tier | A session holds hundreds of MB of weights plus an arena allocator. Eight sessions is an OOM on an 8GB box; one session with eight callers is correct |
| Not process-per-camera | ~200MB per camera for isolation we do not need |
| Not a shared inference queue | Better utilisation when saturated, but real scheduling/backpressure/priority complexity for a benefit that only appears under saturation |

**The escape hatch.** `CameraPipeline` holds no shared mutable state, receives collaborators by constructor injection, and reports through an injected sink. Moving pipelines to child processes touches one factory function. This seam must not be eroded by convenience shortcuts.

**Coupling to note:** the multi-process escape path adds `SQLITE_BUSY` contention. `busy_timeout=30000` is already configured, so this is a latency concern rather than a correctness one — but it is a real dependency between two decisions.

### 4.4 Backpressure — the single most important streaming rule

Between the source and every consumer sits a **latest-frame slot** backed by `asyncio.Queue(maxsize=1)`.

**A full queue means replace the oldest frame. Never block, never accumulate.**

If inference falls behind reality, stale frames must be dropped — not queued. A backlog consumes RAM and adds latency to every alert. Frames are dropped **before** resize, not after decode.

The slot exposes a `dropped` counter. It is not decoration: it is how "the image froze" is diagnosed from a customer's box without attaching a debugger.

### 4.5 Frame lifecycle and memory discipline

Frames are `numpy.ndarray`. Getting this wrong produces a slow leak invisible until days of uptime.

| Discipline | Reason |
|---|---|
| A frame is **owned by the pipeline** or **borrowed by a consumer**, never both | Explicit in type hints |
| Consumers receive a **copy** when retaining beyond the callback | A copy is a few hundred KB and lasts 30 seconds; a leak lasts forever |
| Decoder closed in `finally` on **every** path, including cancellation | A missed `finally` is a container handle leaked per reconnect |
| `io_binding` with preallocated output buffers | Inference allocates nothing per call in steady state |
| Inference pool is **bounded** | N cameras must not spawn N threads on a 4-core box |

`tests/test_stream_manager.py::test_memory_is_flat_across_reconnects` enforces all of it: 50 reconnect cycles, asserting resident memory **plateaus** — a trend assertion, not an absolute ceiling. A ceiling test passes on a slow leak and fails on a fast one; a trend assertion catches both.

### 4.6 Reconnection

Jittered exponential backoff, 1s → 60s cap, reset after 60s of stability.

**Full jitter is essential.** Eight cameras behind a rebooting NVR would otherwise retry in lockstep and hammer whichever camera is still coming up.

A stall watchdog closes a container that delivers no frames, because a TCP connection can survive while the stream is dead.

### 4.7 Hardware tiering

Detected at startup, never configured by hand.

| Tier | Trigger | Model | Input |
|---|---|---|---|
| `high` | ≥ 8 cores, AVX2 + VNNI | YOLOX-m | 640×640 |
| `medium` | ≥ 4 cores, AVX2 | YOLOX-s | 640×640 |
| `low` | 4 cores, no VNNI | YOLOX-nano | 416×416 |

All size variants share one I/O signature — input `[1,3,H,W]`, output `[1,8400,85]` — so `nano → s → m` tiering costs **zero** decoder changes.

The concrete default model is **provisional** pending a Phase 3 benchmark on real footage.

### 4.8 Detection and alerting are separate concerns

The detector reports what it sees. The rules engine decides what deserves an interruption.

All 80 COCO classes are detected on every tier — it is the same forward pass, so restricting the class set saves nothing at inference time. What costs money is *alerting* on all 80: a parked scooter must not wake a shop owner at 03:00.

This is what lets one box serve a shop owner (alert on `person`, 22:00–06:00) and a factory (`person` + `truck` at the loading dock, all hours) with no model change.

**Any code that filters by class before the rules engine is wrong.**

---

## 5. Component contracts

The seams that make the system testable and replaceable. Signatures are normative — the plan's tasks depend on these exact names.

### 5.1 `FrameSource` — the boundary that removes hardware dependency

The most important boundary in the codebase. Every source implements it, so the whole pipeline is testable from a file and CI needs no cameras. Because it is narrow, ONVIF discovery or a vendor SDK is one new class.

```python
@dataclass(frozen=True, slots=True)
class Frame:
    data: np.ndarray                     # (H, W, 3) uint8 RGB — owned, never a borrowed view
    timestamp: float                     # monotonic seconds from capture
    width: int
    height: int


class FrameSource(Protocol):
    async def frames(self) -> AsyncIterator[Frame]: ...
    async def close(self) -> None: ...
```

Contract requirements, each tested:

| Requirement | Why |
|---|---|
| `close()` is idempotent | Both `StreamManager.stop()` and pipeline self-cancellation call it |
| `close()` is safe mid-iteration | Cancellation arrives at an arbitrary `await` |
| `close()` runs in `finally` on every path | Otherwise a container handle leaks per reconnect |
| `Frame.data` is owned, not a view | A consumer retaining a borrowed view reads freed decoder memory |
| The iterator terminates on cancellation | A pipeline awaiting a frame must unblock |

Implementations: `RtspSource`, `FileSource`.

### 5.2 `Detector` — the licensing boundary

```python
@dataclass(frozen=True, slots=True)
class Detection:
    class_name: str                                  # COCO name, never an index
    confidence: float                                # 0.0-1.0
    bbox: tuple[int, int, int, int]                  # (x1,y1,x2,y2) frame pixels


class Detector(Protocol):
    async def infer(self, frame: Frame) -> list[Detection]: ...
    async def close(self) -> None: ...
```

**Classes are names, never indices.** YOLOX and RT-DETR do not share output ordering; storing indices would silently repoint every configured rule at the wrong class when the model changes.

### 5.3 `MotionGate`

```python
class MotionGate:
    def update(self, frame: Frame) -> bool: ...
    def reset(self) -> None: ...
```

MOG2 background subtraction on a 640×360 greyscale downscale, costing milliseconds against the detector's tens of milliseconds.

**Must handle the brightness-shift failure.** A camera switching to IR at dusk changes every pixel at once. Without an explicit reset, the background model reads the transition as motion and fires a burst of false alerts at exactly the hour the customer most needs to trust the product.

### 5.4 `Tracker`

Assigns stable `track_id`s across frames via IoU matching. Cheap on CPU, and it pays for itself by suppressing duplicate alerts. Written for this project rather than copying BYTETracker, keeping the licensing chain clean and the dependency count at zero.

### 5.5 `RulesEngine` — pure, and the highest-value test surface

```python
@dataclass(frozen=True, slots=True)
class RuleOutcome:
    fired: bool
    checks: tuple[RuleCheck, ...]        # per-condition, for the debug endpoint


class RulesEngine:
    def evaluate(self, track: TrackedObject, config: RuleConfig, now: datetime) -> RuleOutcome:
        """Pure. No IO, no clock reads, no notification side effects."""
```

Conditions, in order: class in allow-list · confidence ≥ threshold · centroid in ROI (or bbox overlap) · inside active hours · outside per-rule per-track cooldown.

**Purity is the requirement, not a style preference.** It is what makes table-driven testing possible across active-hours boundaries, timezones, and cooldown state — the conditions where false positives actually originate. An engine that reads the clock internally cannot be tested at 02:30.

`checks` exists because a binary "rule did not fire" is unactionable for a shop owner. `POST /api/v1/rules/{id}/test` returns them.

### 5.6 `Notifier` — where the product's promise is kept

```python
class Notifier(Protocol):
    async def send(self, event: Event) -> None: ...
```

Notification failure **must never** lose an event. Everything before `Notifier` is local and durable. Telegram is the only egress path and is permitted to fail.

Telegram ships first: free, instant, no business verification, native photo and video. WhatsApp requires Meta business verification plus approved templates and becomes per-conversation billing past the free tier — days of setup friction that would stall the MVP. It ships later as an adapter behind this same interface.

### 5.7 `ClipWriter`

Writes a 10s pre-roll + 20s post-roll clip plus a still. Refuses to write past the site's disk quota, raising a critical system event rather than filling the customer's disk — filling it breaks the NVR holding their evidence, which is the one thing CamBrain promises not to do.

---

## 6. Database specification

Full detail in [`DATABASE.md`](../../DATABASE.md). Constraints that shape the build:

### 6.1 Why SQLite

The deployment model decides the database. The box is a self-contained appliance with no server to depend on, and the write pattern — a few dozen event rows per minute at worst — is well inside SQLite's envelope. Single-writer is not a constraint with one process.

Every server database (PostgreSQL, SQL Server, MongoDB) requires something the customer must install, secure, back up, and explain. SQLite requires nothing.

Access is confined to a repository layer, so a future fleet console can use PostgreSQL without touching the edge box.

### 6.2 Engine configuration

| Setting | Value | Reason |
|---|---|---|
| `journal_mode` | WAL | Dashboard reads never block pipeline writes |
| `synchronous` | NORMAL | Throughput/durability trade; clips survive power loss, orphan sweep reclaims |
| `foreign_keys` | **ON** | SQLite disables FK enforcement by default — without it the schema's integrity is decorative |
| `busy_timeout` | 30000 ms | Absorbs writer contention |

### 6.3 Tables

| Table | Purpose | Key constraint |
|---|---|---|
| `sites` | Tenant root | timezone as IANA name; retention_days; disk_quota_pct |
| `users` | Login | `UNIQUE(site_id, username)`; role CHECK admin\|viewer |
| `sessions` | Revocable JWT sessions | refresh token stored hashed, rotated on use |
| `cameras` | Camera config | `rtsp_url` holds **no credentials**; password in separate encrypted column |
| `rois` | Regions of interest | `points` JSON, **normalised 0..1**, ≥3 vertices |
| `rules` | Alerting rules | `classes` JSON of COCO **names**; `active_hours` windows may cross midnight |
| `events` | Alert instances | `clip_path`/`thumbnail_path` generated from `events.id`, never user input |
| `event_detections` | Per-detection detail | `bbox` in frame pixels at detection time |
| `audit_log` | Privileged actions | 90-day retention, separate from operational logs |

### 6.4 Four constraints that shape code

1. **`site_id` on every domain table, always from the auth token.** Cross-tenant access returns **404, never 403**.
2. **ROI coordinates are normalised 0..1.** Pixels fail *silently* on a resolution change, alerting on the wrong area.
3. **`rtsp_url` stores no credentials**, so it is safe to log, display, and export.
4. **Clip paths derive from `events.id`** — `clips/{id}.mp4` — never from `camera.name`, which is user input.

### 6.5 Retention

Default 7 days. Deletions run in **batches** — a single `DELETE` matching tens of thousands of rows holds a write lock long enough to stall pipelines. 500 rows per transaction with a short sleep between batches.

### 6.6 Migrations

Alembic only. Forward-only. **Never edit a shipped migration** — add a new one. Every migration gets a tested downgrade or an explicit note that it is irreversible. Every migration is tested against a populated copy, not an empty database.

---

## 7. API specification

Full detail in [`API.md`](../../API.md).

### 7.1 Surface

Base path `/api/v1`, bound to `127.0.0.1:8765` by default.

| Group | Endpoints | Role |
|---|---|---|
| Auth | login, refresh, logout, me, change-password | mixed |
| Cameras | list, create, get, patch, delete, **test**, snapshot, stream | CRUD any; writes admin |
| ROIs | list, create, get, patch, delete | CRUD any; writes admin |
| Rules | list, create, get, patch, delete (soft), **test** | CRUD any; writes admin |
| Events | list, get, acknowledge, bulk-acknowledge, clip, stats | any |
| Users | list, create, patch, delete | admin |
| Settings / Notifiers | get, patch; notifier CRUD + test | any / admin |
| System | status, health, config | any / admin |
| WebSocket | `/ws/alerts`, `/ws/frames` | any |

### 7.2 The endpoint that matters most

`POST /api/v1/cameras/{id}/test` opens a short-lived connection, reads up to 10 frames, closes it, and returns a typed `error_code` ∈ `AUTH_FAILED` · `CONNECT_TIMEOUT` · `HOST_UNREACHABLE` · `NO_SUCH_STREAM` · `DECODE_FAILED` · `CANCELLED`.

**It returns HTTP 200 with `ok: false`, not an error status.** Failing to reach a camera is an expected outcome of a diagnostic, not a client error, and the entire value is which of six problems the installer has.

Add-camera is the product's first impression. It has to fail usefully, or Arun is on site for every install.

### 7.3 The endpoint that makes rules debuggable

`POST /api/v1/rules/{id}/test` replays a still or recent event and returns per-condition results:

```json
{
  "fired": false,
  "checks": [
    { "condition": "class_in_allowlist", "passed": true,  "detail": "'car' not in ['person']" },
    { "condition": "confidence",        "passed": true,  "detail": "0.71 >= 0.55" },
    { "condition": "in_roi",            "passed": false, "detail": "centroid (0.41,0.62) outside Loading dock" },
    { "condition": "active_hours",      "passed": false, "detail": "14:32 is outside 22:00–06:00" }
  ]
}
```

This is the debug view the rules engine is designed to have.

### 7.4 Protocol rules

| Rule | Reason |
|---|---|
| Every route requires auth | Anyone on the LAN can reach the port — the LAN is not trusted |
| `site_id` never accepted from the client | From the token only; client-supplied is an IDOR |
| Secrets never returned by `GET` | `password` masked, `has_password` flag instead |
| Mutating requests need `Content-Type: application/json` **and** `X-CambBrain-Client` | Both force a CORS preflight, blocking CSRF from a malicious page |
| No CORS wildcard, ever | Allowlist is localhost origins only |
| Cross-tenant → `404` | `403` confirms the row exists — enumeration oracle |
| Server → client WebSocket only | All mutations go over HTTP where they are authed, validated, rate-limited, audited |
| Soft delete for rules | Events reference the rule that fired them; a hard delete orphans attributions |

### 7.5 Rate limits

| Route | Limit | Reason |
|---|---|---|
| `POST /auth/login` | 5/min per username, then exponential lockout | Brute force |
| `POST /cameras/{id}/test` | 10/min | Each opens a real RTSP connection — hardware protection, not security |
| `GET /cameras/{id}/stream` | 4 concurrent per session | Bandwidth + decode |
| `GET /ws/frames` | 10 fps subscribe | CPU |
| Everything else | 120/min | — |

---

## 8. Security specification

Full detail in [`SECURITY.md`](../../SECURITY.md).

### 8.1 Trust boundary

The box sits on the customer's LAN with their NVR. **Anyone on that LAN can reach the port.** There is no trusted-LAN exemption. Default bind is `127.0.0.1`; binding to `0.0.0.0` requires explicit configuration and logs a WARN at startup.

### 8.2 Secrets at rest

Fernet (AES-128-CBC + HMAC-SHA256) via `cryptography`. Master key generated once, wrapped with Windows **DPAPI** so decryption is scoped to the OS user account — another user on the box cannot decrypt it.

DPAPI rather than a user-supplied passphrase because Arun hands these boxes to customers; a passphrase means a support call when the owner forgets it.

### 8.3 Secrets in logs — a structural guarantee

Redaction is a **processor in the structlog chain**, not a convention at call sites. A developer cannot leak a credential by forgetting to mask one, because every event passes through the processor before reaching a sink.

`REDACT_KEYS` covers password, token, secret, api_key, authorization, and `_enc`-suffixed columns, matched case-insensitively. `mask_url()` strips RTSP userinfo while preserving host, port, and path — an installer diagnosing a failed camera needs to know which channel failed.

Proven by `test_no_secret_in_log_output`.

### 8.4 Authentication

Argon2id (`m=64MB, t=3, p=4`). JWT `HS256` signed with a per-installation random DPAPI-wrapped key, 12h expiry, plus a server-side `sessions` table so a session can be revoked before `exp` — a purely stateless JWT cannot be, and for a security product that matters.

Refresh tokens are stored hashed, rotated on use, with reuse detection revoking the family.

The frontend holds the access token **in memory, never `localStorage`**, so an XSS bug cannot exfiltrate a persistent credential.

### 8.5 Authorisation

Two roles. `admin` configures everything; `viewer` is read-only. Enforcement is server-side on every route — hiding a nav item is presentation, not a control.

A user cannot demote or delete the last remaining admin; that would lock the owner out of their own box.

### 8.6 Privacy posture

| Stored | Never stored | Never transmitted |
|---|---|---|
| Event still, short clip, detection metadata (class, confidence, box, track_id, timestamp, camera, zone, rule) | Continuous footage · audio · faces · biometric templates · identity · licence plate text as text | Any video, except the specific clip the owner configured for their own Telegram |

No facial recognition or biometric identifier appears anywhere in the design — deliberately, since it creates a category of DPDP Act exposure a security product does not need.

There is **no telemetry, no crash reporting, no update ping, no licence phone-home.** CamBrain works fully offline.

---

## 9. UI specification

Full detail in [`design.md`](../../design.md).

### 9.1 Two surfaces, deliberately different toolkits

| Surface | Stack | Animation policy |
|---|---|---|
| Marketing site | GSAP + Lenis | Full. GSAP became free including former Club plugins in April 2025; Lenis is MIT |
| Application | Vue 3 + Tauri, restrained | 120–400ms transitions only |

**The app deliberately does not use the heavy animation libraries.** Four reasons: CPU contention with 8 inference pipelines on shared silicon; input-accuracy degradation when transform/scroll-snap ancestors sit between a pointer and the ROI canvas; motion sensitivity in a time-pressured precision task; and diluting red-on-screen signal in a security tool.

**Skiper UI and Vengeance UI are eliminated by construction** — both are shadcn/ui **React** registries, and React is not in the stack. Independently, both are documented as marketing-site libraries.

**AniMaster is flagged and excluded.** Sold via Google Drive and a private Telegram channel, which implies personal-use terms. Copying its components into software installed at a customer's site is redistribution. Free to study; **not safe to ship.**

### 9.2 Why JavaScript, not TypeScript

A deliberate call to reduce build friction for a solo founder. The type-safety value is retained where it matters — module boundaries and API payloads — via JSDoc typedefs, enforced by ESLint `jsdoc/require-jsdoc`. Revisit past ~40 source files or on a second developer.

### 9.3 The ROI editor is the make-or-break screen

Draw a polygon over a **frozen snapshot**, draggable vertices, live coverage percentage, per-zone class filter. This screen determines alert quality: poor ROI UX converts directly into alert fatigue, which is why it gets disproportionate design attention.

Normalised coordinate storage must be verified against a resolution change, because the failure mode is silent — a ROI that alerts on the wrong area still *looks* like it works.

---

## 10. Build sequence

Seven phases. Each ends with something demonstrable.

| Phase | Deliverable | Gate |
|---|---|---|
| **0** | Bootstrap: environment, dependencies, fixtures, RTSP harness, CI guard | Suite green · ruff + mypy clean · MediaMTX reachable · synthetic clip decodes · licence scan wired |
| **1** | Streaming engine | Ingests, samples, gates motion, survives 50 reconnects with flat memory |
| **2** | Database + REST API | CRUD works · cross-tenant 404 · OpenAPI matches `API.md` |
| **3** | Inference + ROI + rules | A real alert fires from a real clip, under 2s |
| **4** | Dashboard + ROI editor | A non-technical user configures a camera unaided |
| **5** | Alerting + event log | A Telegram photo arrives at 02:00 |
| **6** | Packaging + operations | Installs · survives reboot · survives 24h soak |

### 10.1 Phase 0 rationale

Bootstrap is a numbered phase rather than an implicit prerequisite. Eight missing runtime packages and a stopped Docker daemon are exactly the conditions under which a Phase 1 failure is ambiguous — is the streaming code broken, or is ONNX Runtime not installed?

One extra step, bought: after Phase 0, every later failure is unambiguously a code failure.

### 10.2 Dependency order

```
Phase 0 ──> Phase 1 ──> Phase 3 ──> Phase 5 ──> Phase 6
                │          ↑          │
                └─> Phase 2 ─────────┘
                     │
                     └─> Phase 4
```

Phase 2 runs **parallel** to Phase 1 — the database and API need no stream. Phase 4 needs 1, 2, and 3: the ROI editor is meaningless without a camera, and the event log is empty without rules. Phase 5 needs Phase 3 — there is nothing to alert on until detection works.

### 10.3 Why these gates

Each gate is a demonstration, not a status report.

- **Phase 1 → memory measurement.** The failure mode of a streaming engine is a slow leak invisible until a customer finds it after a week.
- **Phase 3 → a real alert from a real clip.** A detector that runs without producing a correct alert has proven plumbing, not accuracy.
- **Phase 6 → 24-hour soak.** That is the only duration that matters to a customer who leaves it running unattended.

### 10.4 Detector decision — provisional

**YOLOX-s ships as the provisional default.** The model choice is measurement-driven and cannot yet be made — no cameras are available.

Building both decoders now was rejected: it would write RT-DETR's decoder without ever running it against a real export. A mocked detector was rejected: it defers all inference work behind a blocked benchmark.

**The swap contract when the benchmark runs:** one new module implementing RT-DETR decode, one new `Detector` implementation bound in the existing factory, `LICENSE-MODEL-NOTICE` updated. **No change** to `CameraPipeline`, `StreamManager`, the rules engine, the API, or the UI.

---

## 11. Test specification

### 11.1 The hardware-free rule

**No test may require a camera.** No cameras are available, and that dependency must not be allowed to form. Every test runs from one of:

- A generated synthetic clip via `FileSource`
- A `MockDetector` returning fixture detections
- **MediaMTX in Docker**, streaming a local file over real RTSP

MediaMTX is used rather than a mock because a mock would never exercise the code most likely to be wrong: PyAV RTSP option handling, handshake behaviour, and reconnection against a real server. MediaMTX is a conformant RTSP server, not a mock.

RTSP tests are marked `@pytest.mark.rtsp`, excluded locally with `pytest -m "not rtsp"`. If Docker is unavailable they **skip with a clear message — never silently pass.**

### 11.2 Fixture strategy

`tests/make_fixtures.py` generates clips programmatically, so they are reproducible and reviewable as code. Clips are **gitignored and rebuilt on demand** — binary test data in git is unreviewable and inflates the repo.

| Fixture | Content | Proves |
|---|---|---|
| `static.mp4` | Still frame, 300 frames | Gate stays closed — no false alerts |
| `motion.mp4` | Shape translating across frame | Gate opens |
| `brightness_shift.mp4` | Day → night cut at frame 150 | Gate resets instead of firing a burst |
| `low_light.mp4` | IR-lit, low contrast, person-sized blob | Night-path behaviour |
| `multi_object.mp4` | Three objects, one entering an ROI | ROI boundary logic |

### 11.3 Layers

| Layer | Location | Scope |
|---|---|---|
| Unit | `tests/test_*.py` | One component, no IO |
| Integration | `test_pipeline.py`, `test_api_*.py` | Wired together, real SQLite, MockDetector |
| RTSP | `tests/rtsp/` — marked `rtsp` | Real PyAV against real MediaMTX |
| Soak | `test_soak.py` — marked `slow` | 24h memory and handle stability |

**Default local:** `pytest -m "not rtsp and not slow"` · **Full:** `pytest`

### 11.4 Canary tests

Two cover whole bug classes rather than single functions.

**`test_memory_is_flat_across_reconnects`** — 50 reconnect cycles against MediaMTX, sampling RSS via `psutil`. Asserts a **flat trend**, not a low absolute value. A ceiling test passes on a slow leak and fails on a fast one. This turns "customers find it broken after a week" into a CI failure.

**`test_no_secret_in_log_output`** — logs a struct containing every `REDACT_KEYS` entry plus an RTSP URL with embedded credentials, asserts none appear in captured output. Verifies a structural property: there is no code path that bypasses the redaction chain.

### 11.5 Coverage discipline

Coverage percentage is not a target. Three areas need near-complete **branch** coverage, because a gap in each is a product failure:

| Module | Gap consequence |
|---|---|
| `rtsp_source.py` | A camera silently stops |
| `yolox_post.py` | Alerts fire on the wrong thing |
| `rules.py` | False positives — the primary engineering enemy |

---

## 12. Verification matrix

Every NFR from §1.5 and every hard constraint, mapped to the test that proves it. A row with no test is an unproven requirement.

| Requirement | Proving test | Phase |
|---|---|---|
| Concurrent cameras — 8 | `test_pipeline.py::test_eight_pipelines_concurrently` | 1 |
| Sample rate 2–5 FPS configurable | `test_pipeline.py::test_sample_fps_is_honoured` | 1 |
| Reconnect transient ≤ 5s | `test_stream_manager.py::test_transient_drop_recovers_fast` | 1 |
| Reconnect backoff to 60s | `test_stream_manager.py::test_backoff_reaches_cap` | 1 |
| **No thundering herd** | `test_stream_manager.py::test_backoff_has_jitter` | 1 |
| **Memory flat** | `test_stream_manager.py::test_memory_is_flat_across_reconnects` | 1 |
| Idle CPU < 5% | `test_pipeline.py::test_idle_cpu_under_5_percent` | 1 |
| Works at 1080p | `test_source.py::test_1080p_input_downscaled` | 1 |
| **Hardware-free tests** | `test_pipeline.py` runs with Docker down | 1 |
| Hardware floor / graceful degradation | `test_tiers.py::test_tier_falls_back_on_low_capability` | 3 |
| Detection latency < 2s | `test_pipeline.py::test_motion_to_alert_under_2s` | 3 |
| Model output validated | `test_detector.py::test_rejects_malformed_output` | 3 |
| Rules correctness | `test_rules.py` — table-driven, every branch | 3 |
| ROI boundary logic | `test_roi.py::test_centroid_on_edge_counts_inside` | 3 |
| **Cross-tenant 404** | `test_repositories.py::test_cross_tenant_read_returns_404` | 2 |
| Tenant scoping on every route | `test_api_cameras.py::test_cannot_pass_site_id` | 2 |
| Auth — Argon2, JWT, revocation | `test_api_auth.py` | 2 |
| Last-admin protection | `test_api_users.py::test_cannot_delete_last_admin` | 2 |
| **No secret in logs** | `test_logging.py::test_no_secret_in_log_output` | 0 |
| Secrets never in API responses | `test_api_cameras.py::test_get_never_returns_password` | 2 |
| Fernet roundtrip + DPAPI | `test_crypto.py` | 0 |
| Error hierarchy catchable | `test_errors.py` | 0 |
| OpenAPI matches `API.md` | `test_api_system.py::test_openapi_matches_spec` | 2 |
| Disk quota refuses writes | `test_clip_writer.py::test_quota_refuses_writes` | 5 |
| Pre/post roll lengths | `test_ring_buffer.py::test_holds_ten_seconds` | 5 |
| **Telegram failure loses nothing** | `test_telegram.py::test_offline_event_survives` | 5 |
| Normalised ROI survives resolution change | `test_rois.py::test_roi_survives_resolution_change` | 4 |
| `viewer` cannot write | `test_api_rois.py::test_viewer_is_read_only` | 2 |
| 24h soak | `test_soak.py::test_24h_soak` (marked slow) | 6 |
| Boot without login | Phase 6 manual gate | 6 |
| **No AGPL anywhere** | CI licence scan step | 0 |

---

## 13. Definition of done

A phase is done when **all** hold. Not "code written."

1. Every test named in the plan for that phase exists and passes.
2. The phase's gate demonstration has been run and observed.
3. `ruff check` and `mypy` are clean.
4. Every new public function has a Google-style docstring; every module has a module docstring.
5. No secret is logged, returned by an API, or stored in plaintext — verified by test, not inspection.
6. `git status` shows no weights, database files, clips, or `.env`.
7. Commit messages explain **why**, per `CODE_STYLE.md` §7.

---

## 14. Risks

| Risk | Impact | Mitigation | Residual |
|---|---|---|---|
| **No cameras for testing** | Vendor RTSP quirks, auth methods, sub-stream paths all unvalidated | `FrameSource`, synthetic fixtures, MediaMTX | **High** — MediaMTX is conformant, not a Hikvision |
| **N100 throughput unmeasured** | Fewer cameras per box, worse unit economics | Tier detection; nano @ 416 fallback | **High** — unmeasurable without hardware |
| **False positives** | Customer disables alerts; product fails | ROI, cooldown, class filters, hours, dedupe | Medium — engine tested, thresholds need field data |
| **Model choice unvalidated** | Wrong default for CCTV | YOLOX-s provisional; benchmark harness ships alongside | Medium — swap is one module |
| **Night/IR accuracy** | Missed intrusions — the worst failure mode | `low_light.mp4` fixture; brightness-shift reset | **High** — a synthetic blob is not IR footage |
| **Long unattended uptime** | Broken after a week | Memory test from Phase 1; 24h soak in Phase 6 | Low — covered early |
| Power-loss event loss | Evidence lost at the worst moment | `synchronous=NORMAL`; clips survive; orphan sweep | **Accepted** — revisit if a customer reports lost evidence |
| Multi-process escape vs SQLite | `SQLITE_BUSY` contention | `busy_timeout=30000` | Low — not exercised unless escape hatch taken |

**The two High-residual risks share one root cause: no hardware.** They are not mitigable by better engineering. They resolve when someone points a camera at the box.

---

## 15. Deferred decisions

| Question | Closes when | Current handling |
|---|---|---|
| YOLOX-s vs RT-DETR-r18 | Benchmark on real N100 footage | YOLOX-s provisional; swap is one module |
| Night/IR accuracy | IR-lit night footage from a real camera | `low_light.mp4` is a placeholder, not a substitute |
| Retention default (7 days) | Disk measurement on a real 128GB box | Configurable |
| WhatsApp timing | Meta business verification lead time | `Notifier` Protocol reserved |
| Operators wanting smooth live video | Field feedback | MJPEG; WebRTC deferred |
| Gujarati/Hindi localisation | Market input | Not started — likely valuable for Rajkot |
| Model download vs bundled | Installer size, offline-install need | Download on first run, checksum-verified |

---

## 16. Document status

This is a **specification**, not a living document. It describes CamBrain MVP as of 2026-10-05.

When the Phase 3 benchmark resolves the model choice, or a gate reveals a threshold needs adjusting, **this file is updated and the plan revised** — rather than the plan being improvised around.

The ten documents in `docs/` remain living documents, updated as the product evolves.
