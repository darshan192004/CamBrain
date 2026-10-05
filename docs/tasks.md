# CamBrain — Tasks & Progress

> Living document. `[ ]` open · `[~]` in progress · `[x]` done · `[!]` blocked
> Related: [prd.md](prd.md) · [architecture.md](architecture.md) · [memory.md](memory.md)

---

## Status legend

Phases are sequenced so that **each phase ends with something demonstrable**. No phase ends with work that cannot be shown working.

| Phase | Deliverable | Gate |
|---|---|---|
| 1 | Docs, scaffold, core streaming engine | Stream ingests, samples, filters motion, survives reconnects without leaking |
| 2 | Database + REST API | CRUD works, tenant-scoped |
| 3 | Inference + ROI + rules | Real alert fires from a real clip |
| 4 | Dashboard + ROI editor | Non-technical user configures it unaided |
| 5 | Alerting + event log | Telegram photo arrives at 2am |
| 6 | Packaging, tray, autostart | Installer + reboot survival |

---

## Phase 1 — Docs, scaffold, streaming engine

### Documentation

- [x] `docs/prd.md` — personas, MVP scope, non-functional targets
- [x] `docs/architecture.md` — deployment model, pipeline, concurrency
- [x] `docs/rules.md` — engineering laws
- [x] `docs/design.md` — two-surface UI direction
- [x] `docs/tasks.md` — this file
- [x] `docs/memory.md` — decision log
- [x] `docs/SECURITY.md` — security and privacy specification
- [x] `docs/CODE_STYLE.md` — code style guide
- [x] `docs/DATABASE.md` — schema and ER design
- [x] `docs/API.md` — REST and WebSocket specification

### Scaffold

- [ ] Repo layout: `docs/`, `backend/app/{core,db,services,api}`, `backend/tests/`, `frontend/`, `models/`
- [ ] `requirements.txt` — pyav, onnxruntime, fastapi, uvicorn, pydantic, sqlalchemy, alembic, httpx, cryptography, structlog
- [ ] `pyproject.toml` — Ruff, mypy, pytest config
- [ ] `package.json` — Vue 3 + Vite + Tailwind + Pinia + Vue Router + shadcn-vue
- [ ] `frontend/src-tauri/` — Tauri v2 scaffold, tray + autostart stubs
- [ ] `.gitignore` — models/*.onnx excluded, weights fetched by script
- [ ] CI workflow: pytest + license scan (fails on AGPL)

### Stream layer

- [ ] `services/stream/source.py` — `FrameSource` protocol, `Frame` dataclass
- [ ] `services/stream/rtsp_source.py` — PyAV container, transport options, backoff, stall watchdog
- [ ] `services/stream/file_source.py` — clip decode, loop/once
- [ ] `services/stream/motion.py` — MOG2 gate, cooldown, brightness-shift reset
- [ ] `services/stream/pipeline.py` — per-camera orchestration
- [ ] `services/stream/stream_manager.py` — lifecycle ownership, status aggregation
- [ ] Latest-frame slot with replace-oldest backpressure
- [ ] Jittered exponential backoff, 1s → 60s, reset after 60s stable
- [ ] Frame dropping before resize (not decode-then-discard)

### Test layer

- [ ] `tests/fixtures/` — synthetic clips (moving shapes, brightness change, static)
- [ ] `conftest.py` — mocked `Detector`, tmp SQLite, fixtures
- [ ] Mock RTSP server (MediaMTX container) exercising the real RTSP path in CI
- [ ] `test_source.py` — protocol conformance for both sources
- [ ] `test_motion.py` — gate behaviour, cooldown, brightness-change reset
- [ ] `test_stream_manager.py` — **`test_memory_is_flat_across_reconnects`** (50 cycles, RSS plateau)
- [ ] `test_stream_manager.py` — backoff sequence and jitter distribution
- [ ] `test_pipeline.py` — end-to-end from clip to sink callback

---

## Phase 2 — Database & REST API

### Schema

- [ ] `core/config.py` — pydantic-settings, env + file
- [ ] `db/base.py` — declarative base
- [ ] `db/session.py` — engine, WAL, session factory
- [ ] `db/models/` — sites, users, cameras, rois, rules, events, event_detections, clips
- [ ] Alembic init + initial migration
- [ ] Indexes per [DATABASE.md](DATABASE.md)
- [ ] Credential encryption columns + Fernet key from DPAPI (Windows)

### API

- [ ] `api/deps.py` — auth dependency, tenant scoping
- [ ] `api/routers/cameras.py` — CRUD + test-connection
- [ ] `api/routers/rois.py` — CRUD, normalised coordinates
- [ ] `api/routers/rules.py` — CRUD, timezone validation
- [ ] `api/routers/events.py` — paginated, filtered
- [ ] `api/routers/users.py` — admin only
- [ ] `api/routers/system.py` — hardware tier, health
- [ ] `api/ws/` — `alerts` and `frames` topics
- [ ] OpenAPI schema matches [API.md](API.md)

### Auth

- [ ] Argon2 password hashing
- [ ] JWT issue/verify, session table
- [ ] `admin` / `viewer` role enforcement on every route
- [ ] Rate limit login attempts

---

## Phase 3 — Inference, ROI, rules

### Detector

- [ ] **Benchmark YOLOX-s vs RT-DETR-r18** on real footage — this is the deferred decision, see [memory.md](memory.md)
- [ ] `inference/tiers.py` — capability detection (AVX2/VNNI/core count)
- [ ] `inference/detector.py` — protocol, ONNX wrapper, `io_binding`, preallocated buffers
- [ ] `inference/pool.py` — bounded threadpool, one session per tier
- [ ] `inference/yolox_post.py` — anchor-free decode, letterbox inverse, NMS
- [ ] `models/` fetch script + `LICENSE-MODEL-NOTICE` + licence inventory
- [ ] `inference/detector.py` — model output validation, typed `InferenceError`

### ROI + rules

- [ ] `alerts/roi.py` — point-in-polygon, centroid rule, bounding-box overlap
- [ ] `tracker/tracker.py` — detached IoU tracker (own implementation, no BYTETracker copy)
- [ ] `alerts/rules.py` — pure `evaluate()`, class list, confidence, ROI, active hours, cooldown, dedupe key
- [ ] Table-driven rule tests — highest-value test surface in the codebase
- [ ] Timezone handling verified against a non-UTC zone

---

## Phase 4 — Dashboard & ROI editor

- [ ] Vue app shell, router, Pinia stores
- [ ] Design tokens → CSS variables
- [ ] `ui/` primitives copied from shadcn-vue, restyled to tokens
- [ ] Login + AuthGuard + RoleGate
- [ ] `AppShell` · `Sidebar` · `TopBar` · `StatusBar`
- [ ] `CameraGrid` + `CameraTile` — MJPEG live view, states per [design.md](design.md)
- [ ] `AddCameraDialog` with **test connection** and real failure reasons
- [ ] `RoiEditor` — frozen snapshot, draggable vertices, coverage %, zone list, class filter
- [ ] Normalised coordinate storage verified against a resolution change
- [ ] Event log — table, filters, thumbnails, bulk acknowledge
- [ ] Reduced-motion honoured; keyboard operability of ROI editor
- [ ] Accessibility pass — contrast, focus rings, `aria-live` for alerts

---

## Phase 5 — Alerting & events

- [ ] `events/clips.py` — 10s pre-roll ring buffer, 20s post-roll
- [ ] `alerts/notifier.py` — protocol
- [ ] `alerts/telegram.py` — sendPhoto / sendVideo, token encrypted at rest
- [ ] `alerts/whatsapp.py` — stub behind the same interface (Phase 5+)
- [ ] Event + detection persistence
- [ ] WS `alerts` broadcast
- [ ] Offline behaviour — event stored, retried when connectivity returns
- [ ] Retention enforcement, disk quota cap

---

## Phase 6 — Packaging & operations

- [ ] Tauri v2 — tray icon, autostart on boot, single instance
- [ ] Windows installer (NSIS or MSI) + silent install for integrators
- [ ] Service starts without user login
- [ ] Recovery after power loss
- [ ] Model download on first run with checksum verification
- [ ] `capabilities.py` — tier detection surfaced in System settings
- [ ] 24h soak test — flat memory, stable FPS, no leaked handles
- [ ] Installer handover guide for Arun

---

## Deferred — explicitly not now

- [ ] Central fleet console (post-MVP; reads the same API, no edge-box change)
- [ ] Linux appliance build (engine is OS-agnostic; only the tray shell differs)
- [ ] WebRTC live view (deferred pending evidence operators need it)
- [ ] Behavioural detection — loitering, fall
- [ ] PPE / helmet detection
- [ ] Per-camera subscription billing
- [ ] ONVIF discovery
- [ ] Mobile app (Telegram is the mobile app)
- [ ] Celery/Redis — only if clip writing grows past seconds

---

## Open risks

| Risk | Impact | Mitigation |
|---|---|---|
| **No cameras available for testing** | Cannot validate real RTSP quirks, auth methods, sub-stream paths | `FrameSource` abstraction + mock RTSP server in CI. Real-hardware bring-up isolated as an explicit task, not hidden in Phase 3 |
| **N100 throughput below target** | Fewer cameras per box, worse unit economics | Tier detection; measure in Phase 3 benchmark; `low` tier is nano at 416×416 |
| **False positives** | Customer disables alerts; product fails | Cooldown, ROI, class filters, hours, dedupe — Phase 3 is the battleground |
| **Model choice unvalidated** | Wrong default for CCTV | Deferred to measured Phase 3 benchmark, not assumption |
| **Night / low-light accuracy** | Missed intrusions — the worst failure mode | Explicit Phase 3 test case using IR-lit night footage |
| **Long unattended uptime** | Customers find it broken after a week | 24h soak test in Phase 6; memory test is mandatory from Phase 1 |

---

## Progress log

| Date | Phase | Notes |
|---|---|---|
| — | 1 | Repository initialised, zero commits. Brainstorming complete: multi-site tenant-aware schema, edge box per site, Windows x64 first, event-clips-only, admin/viewer auth, Telegram first, all-80-COCO detection gated by rules engine, concurrency = single process + thread per camera, model decision deferred. All ten documents written. |