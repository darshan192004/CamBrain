# CamBrain MVP Implementation Plan — Index

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the CamBrain MVP — an edge AI sidecar that adds object detection, ROI rules, event clips, and Telegram alerting to existing NVR/CCTV systems, running offline on an Intel N100 Windows box.

**Architecture:** Single Python process. One thread per camera running an async pipeline (source → motion gate → detector → tracker → rules engine). FastAPI on `127.0.0.1:8765` for REST and WebSocket. SQLite in WAL mode for persistence. Vue 3 + Tauri v2 shell for the dashboard. Every async step is testable from a file fixture via the `FrameSource` protocol, so CI needs no cameras.

**Tech Stack:** Python 3.13 · FastAPI · PyAV · ONNX Runtime · SQLAlchemy 2.0 · Alembic · SQLite (WAL) · Vue 3 (JavaScript) · Vite · Tailwind · shadcn-vue · Tauri v2 · pytest · MediaMTX (Docker)

**Canonical spec:** [`docs/superpowers/specs/spec.md`](../specs/spec.md) — the complete technical specification: product scope, environment baseline, component contracts, build sequence, test specification, and the full requirement-to-test verification matrix.

**Living documents:** [`docs/prd.md`](../../prd.md) · [`docs/architecture.md`](../../architecture.md) · [`docs/memory.md`](../../memory.md) · [`docs/DATABASE.md`](../../DATABASE.md) · [`docs/API.md`](../../API.md) · [`docs/SECURITY.md`](../../SECURITY.md) · [`docs/CODE_STYLE.md`](../../CODE_STYLE.md) · [`docs/rules.md`](../../rules.md) · [`docs/design.md`](../../design.md)

> Where a living document and `spec.md` disagree, the living document wins and `spec.md` is corrected.

---

## How to use this plan

The plan is split into an index plus **one file per phase**. Each phase file is self-contained: it repeats the Global Constraints below, carries its own quality bar, its own file-structure slice, and its own verification rows, so an agent working on a single phase never has to read the others.

**Order.** Execute phases in the dependency order shown [below](#dependency-order). Within a phase, execute tasks in the written order — later tasks import earlier ones.

**Checkpointing.** A phase is not "done" until every line of its **gate checklist** has been *observed*, not assumed (spec §13). Stop there, report, and get confirmation before starting the next phase.

**TDD.** Every task writes its failing test first, runs it to watch it fail, then writes the minimum code that makes it pass, then refactors. Steps use `- [ ]` checkboxes so progress is visible.

**What "full code" means here.** Every code step contains the complete file or function body to paste. There are no `# ...` elisions, no "implement validation here", and no references to code that does not exist in this plan.

---

## Phase plans

| Phase | Plan file | Deliverable | Gate (spec §10) |
|---|---|---|---|
| **0** | [`phase-0-bootstrap.md`](phase-0-bootstrap.md) | Bootstrap: environment, dependencies, fixtures, RTSP harness, CI guard | Suite green · ruff + mypy clean · MediaMTX reachable · synthetic clip decodes · licence scan wired |
| **1** | [`phase-1-streaming.md`](phase-1-streaming.md) | Streaming engine | Ingests, samples, gates motion, survives 50 reconnects with flat memory |
| **2** | [`phase-2-database-api.md`](phase-2-database-api.md) | Database + REST API | CRUD works · cross-tenant 404 · OpenAPI matches `API.md` |
| **3** | [`phase-3-inference-rules.md`](phase-3-inference-rules.md) | Inference + ROI + rules | A real alert fires from a real clip, under 2s |
| **4** | [`phase-4-dashboard-roi.md`](phase-4-dashboard-roi.md) | Dashboard + ROI editor | A non-technical user configures a camera unaided |
| **5** | [`phase-5-alerting-events.md`](phase-5-alerting-events.md) | Alerting + event log | A Telegram photo arrives at 02:00 |
| **6** | [`phase-6-packaging.md`](phase-6-packaging.md) | Packaging + operations | Installs · survives reboot · survives 24h soak |

**Why Phase 0 is numbered rather than implicit** (spec §10.1): eight missing runtime packages and a stopped Docker daemon are exactly the conditions under which a Phase 1 failure is ambiguous — is the streaming code broken, or is ONNX Runtime not installed? One extra step, bought: after Phase 0, every later failure is unambiguously a code failure.

---

## Dependency order

From spec §10.2:

```
Phase 0 ──> Phase 1 ──> Phase 3 ──> Phase 5 ──> Phase 6
                │          ↑          │
                └─> Phase 2 ─────────┘
                     │
                     └─> Phase 4
```

Phase 2 runs **parallel** to Phase 1 — the database and API need no stream. Phase 4 needs 1, 2, and 3: the ROI editor is meaningless without a camera, and the event log is empty without rules. Phase 5 needs Phase 3 — there is nothing to alert on until detection works.

**Why these gates** (spec §10.3): each is a demonstration, not a status report.

- **Phase 1 → memory measurement.** The failure mode of a streaming engine is a slow leak invisible until a customer finds it after a week.
- **Phase 3 → a real alert from a real clip.** A detector that runs without producing a correct alert has proven plumbing, not accuracy.
- **Phase 6 → 24-hour soak.** That is the only duration that matters to a customer who leaves it running unattended.

---

## Global Constraints

These apply to every task in every phase file. Each phase file repeats this block verbatim — if a phase file's copy and this one ever differ, this one is correct.

**Licensing — hard constraint, CI-enforced:**
- No AGPL dependency in any form. `ultralytics` (YOLOv5, v8, v11, v26) is **prohibited**, including ONNX exports.
- Detector models must be Apache-2.0 or equivalent. Permitted family: **YOLOX** (default), **RT-DETR**, DAMO-YOLO, NanoDet.
- `models/*.onnx` is gitignored. Weights are fetched by script with SHA-256 verification.
- `models/LICENSE-MODEL-NOTICE` records provenance + licence for every shipped weight file. Apache-2.0 requires attribution — legal obligation.
- CI runs a licence scan and **fails the build on any AGPL identifier**.

**Language and stack:**
- Frontend is **JavaScript, not TypeScript**. JSDoc typedefs on every exported function and API boundary. ESLint enforces `jsdoc/require-jsdoc`.
- Frontend framework is **Vue 3**, never React. This eliminates Skiper UI and Vengeance UI by construction.
- Python line length 100. Target Python 3.13.
- Type hints on every function signature. No `Any` outside tests and protocol boundaries.
- Google-style docstrings on every public function.

**Concurrency:**
- Single process. One thread per camera. **Not** process-per-camera.
- PyAV decode and ONNX Runtime `run()` both release the GIL.
- One `InferenceSession` per model tier, shared across cameras.
- `CameraPipeline` holds no shared mutable state; collaborators are constructor-injected; outward communication via injected sink. **This seam must not be eroded.**

**Backpressure — the single most important streaming rule:**
- Between source and every consumer sits a latest-frame slot (`asyncio.Queue(maxsize=1)`).
- **Full queue means replace the oldest frame.** Never block, never accumulate.
- Drop frames **before** resize, not after decode.

**Tenancy:**
- Every domain table carries `site_id`.
- `site_id` is taken from the **auth token**, never from a request body or query parameter.
- Cross-tenant access returns **404, never 403** (403 confirms the row exists — enumeration oracle).
- Every FK has an explicit `ON DELETE` behaviour.

**Secrets:**
- Fernet-encrypted at rest. Master key DPAPI-wrapped (Windows), 0600 file on non-Windows dev with a loud warning.
- `rtsp_url` in the database stores **no credentials** — username and password are separate columns.
- `REDACT_KEYS` redaction happens in the structlog processor chain, so it cannot be bypassed by forgetting.
- RTSP URLs are masked (`rtsp://***:***@host:port/path`) everywhere — logs, errors, API responses.
- Secrets are **never** returned by any `GET`.

**Conventions:**
- Components always `<script setup>`, order script → template → style, always `scoped`.
- Hardcoded hex colours in components: never. Design tokens as CSS variables only.
- A `watch` that only sets other state is forbidden — use `computed`.
- SQLAlchemy 2.0 `select()` style. No string-built SQL.
- Alembic only for migrations. Never edit a shipped migration.
- Conventional Commits. Scope is the module: `stream`, `inference`, `rules`, `ui`.
- Never commit: model weights, `.env`, `cambrain.db`, clips, `node_modules/`, build output, credentials.

---

## File Structure

Everything this plan creates, across all seven phases. One responsibility per file. Each phase file repeats only its own slice.

```
E:\CamBrain\
├── README.md
├── .gitignore
├── .pre-commit-config.yaml              # ruff, mypy, eslint, prettier, forbidden-files
├── pyproject.toml                       # ruff, mypy, pytest config
├── requirements.txt                     # runtime version floors
├── requirements-dev.txt                 # test/lint version floors
├── requirements.lock.txt                # GENERATED by pip freeze — never hand-edited
├── .github/
│   └── workflows/
│       └── ci.yml                       # pytest + ruff + mypy + AGPL licence scan
├── backend/
│   ├── alembic.ini
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                      # FastAPI app factory, lifespan
│   │   ├── core/
│   │   │   ├── __init__.py
│   │   │   ├── config.py                # pydantic-settings, env + file
│   │   │   ├── logging.py               # structlog + REDACT_KEYS processor
│   │   │   ├── crypto.py                # Fernet + DPAPI key management
│   │   │   └── errors.py                # CamBrainError hierarchy
│   │   ├── db/
│   │   │   ├── __init__.py
│   │   │   ├── base.py                  # DeclarativeBase
│   │   │   ├── session.py               # engine, WAL pragmas, factory
│   │   │   ├── models/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── site.py              # sites
│   │   │   │   ├── user.py              # users, sessions
│   │   │   │   ├── camera.py            # cameras
│   │   │   │   ├── roi.py               # rois
│   │   │   │   ├── rule.py              # rules
│   │   │   │   └── event.py             # events, event_detections, audit_log
│   │   │   └── repositories/
│   │   │       ├── __init__.py
│   │   │       ├── base.py              # TenantScopedRepository — site_id required
│   │   │       ├── cameras.py
│   │   │       ├── rois.py
│   │   │       ├── rules.py
│   │   │       └── events.py
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── stream/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── source.py            # FrameSource Protocol, Frame dataclass
│   │   │   │   ├── file_source.py       # FileSource
│   │   │   │   ├── rtsp_source.py       # RtspSource, backoff, stall watchdog
│   │   │   │   ├── motion.py            # MotionGate (MOG2)
│   │   │   │   ├── slot.py              # LatestFrameSlot (backpressure)
│   │   │   │   ├── pipeline.py          # CameraPipeline
│   │   │   │   └── stream_manager.py    # StreamManager (lifecycle owner)
│   │   │   ├── inference/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── tiers.py             # hardware capability detection
│   │   │   │   ├── detector.py          # Detector Protocol, ONNX wrapper
│   │   │   │   ├── yolox_post.py        # anchor-free decode + NMS
│   │   │   │   └── pool.py              # bounded thread pool
│   │   │   ├── tracker/
│   │   │   │   ├── __init__.py
│   │   │   │   └── tracker.py           # IoU tracker
│   │   │   ├── alerts/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── roi.py               # point-in-polygon, centroid
│   │   │   │   ├── rules.py             # pure evaluate()
│   │   │   │   └── notifier.py          # Notifier Protocol
│   │   │   └── events/
│   │   │       ├── __init__.py
│   │   │       ├── ring_buffer.py       # pre-roll ring buffer
│   │   │       └── clip_writer.py       # ClipWriter
│   │   └── api/
│   │       ├── __init__.py
│   │       ├── deps.py                  # auth dependency, tenant scope
│   │       ├── schemas.py               # Pydantic request/response models
│   │       ├── routers/
│   │       │   ├── __init__.py
│   │       │   ├── auth.py
│   │       │   ├── cameras.py
│   │       │   ├── rois.py
│   │       │   ├── rules.py
│   │       │   ├── events.py
│   │       │   ├── users.py
│   │       │   ├── settings.py
│   │       │   └── system.py
│   │       └── ws/
│   │           ├── __init__.py
│   │           ├── alerts.py            # alerts topic
│   │           └── frames.py            # frames topic
│   ├── migrations/
│   │   ├── env.py
│   │   ├── script.py.mako
│   │   └── versions/
│   │       └── 0001_initial.py
│   ├── scripts/
│   │   ├── __init__.py
│   │   ├── check_licences.py            # AGPL scan — CI job licence-scan
│   │   ├── check_forbidden_files.py     # commit guard: weights, secrets, DB, footage
│   │   ├── fetch_model.py               # checksum-pinned weight download
│   │   └── benchmark_detector.py        # YOLOX-s vs RT-DETR-r18
│   └── tests/
│       ├── __init__.py
│       ├── conftest.py                  # fixtures: tmp db, MockDetector, sources
│       ├── fixtures/
│       │   └── clips/                   # GENERATED, gitignored
│       ├── make_fixtures.py             # synthetic clip generator
│       ├── test_logging.py              # CANARY: test_no_secret_in_log_output
│       ├── test_errors.py
│       ├── test_crypto.py
│       ├── test_make_fixtures.py        # proves PyAV decodes what we generate
│       ├── test_forbidden_files.py      # proves the commit guard fires
│       ├── test_licence_scan.py         # proves AGPL detection catches a plant
│       ├── rtsp/
│       │   ├── __init__.py
│       │   ├── conftest.py              # MediaMTX container fixture, skip-not-pass
│       │   └── test_harness.py          # marked @pytest.mark.rtsp
│       ├── test_source.py               # protocol conformance, both sources
│       ├── test_motion.py
│       ├── test_slot.py                 # backpressure semantics
│       ├── test_pipeline.py
│       ├── test_stream_manager.py       # memory-flatness, backoff, jitter
│       ├── test_tiers.py
│       ├── test_detector.py
│       ├── test_yolox_post.py
│       ├── test_pool.py
│       ├── test_roi.py                  # pure geometry: point-in-polygon, edges
│       ├── test_rois.py                 # normalised ROI survives resolution change
│       ├── test_tracker.py
│       ├── test_rules.py                # table-driven, every branch
│       ├── test_clip_writer.py
│       ├── test_ring_buffer.py
│       ├── test_repositories.py         # cross-tenant 404
│       ├── test_api_auth.py
│       ├── test_api_cameras.py
│       ├── test_api_rois.py
│       ├── test_api_rules.py
│       ├── test_api_events.py
│       ├── test_api_users.py
│       ├── test_api_system.py
│       ├── test_ws.py
│       ├── test_telegram.py             # offline event survives a send failure
│       └── test_soak.py                 # 24h soak, marked slow
├── frontend/
│   ├── package.json                     # npm-resolved deps; dev/build/lint/format
│   ├── package-lock.json                # exact npm resolution
│   ├── vite.config.js                   # dev proxy → 127.0.0.1:8765
│   ├── eslint.config.js                 # jsdoc/require-jsdoc enforced
│   ├── .prettierignore
│   ├── index.html
│   ├── src/
│   │   ├── main.js
│   │   ├── App.vue
│   │   ├── style.css                    # Tailwind v4 CSS-first import
│   │   ├── router/index.js
│   │   ├── stores/{auth,cameras,rois,rules,events,system}.js
│   │   ├── api/client.js                # fetch wrapper, token handling
│   │   ├── types/index.js               # JSDoc typedefs
│   │   ├── styles/tokens.css            # CSS variables
│   │   ├── components/
│   │   │   ├── ui/                      # shadcn-vue primitives, restyled
│   │   │   ├── AppShell.vue  Sidebar.vue  TopBar.vue  StatusBar.vue
│   │   │   ├── CameraGrid.vue  CameraTile.vue
│   │   │   ├── AddCameraDialog.vue
│   │   │   ├── RoiEditor.vue
│   │   │   ├── EventTable.vue  EventThumb.vue
│   │   │   └── RulesEditor.vue
│   │   └── views/
│   │       ├── LoginView.vue  CamerasView.vue  EventsView.vue
│   │       └── SettingsView.vue
│   └── src-tauri/
│       ├── Cargo.toml  tauri.conf.json
│       └── src/{main.rs,lib.rs,tray.rs}
└── models/
    ├── .gitkeep
    └── LICENSE-MODEL-NOTICE
```

---

## Verification matrix

Copied verbatim from [`spec.md` §12](../specs/spec.md). Every NFR from §1.5 and every hard constraint, mapped to the test that proves it. **A row with no test is an unproven requirement.**

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

### Phase 0 gate rows (not in spec §12)

The Phase 0 plan carries these as phase-local verification rows. They were missing from spec §12 because they are gate demonstrations rather than NFRs; they are recorded here so they are not lost.

| Requirement | Proving test | Phase |
|---|---|---|
| Synthetic clip decodes with real PyAV | `test_make_fixtures.py::test_generated_clip_decodes_with_pyav` | 0 |
| RTSP harness reaches MediaMTX | `rtsp/test_harness.py::test_reads_frames_from_rtsp` | 0 |
| Default suite is hardware-free | `pytest -m "not rtsp and not slow"` passes with Docker stopped | 0 |
| Forbidden files blocked structurally | `test_forbidden_files.py` + planted `.onnx` fails the commit | 0 |

---

## Definition of done

Verbatim from spec §13. A phase is done when **all** hold. Not "code written."

1. Every test named in the plan for that phase exists and passes.
2. The phase's gate demonstration has been run and observed.
3. `ruff check` and `mypy` are clean.
4. Every new public function has a Google-style docstring; every module has a module docstring.
5. No secret is logged, returned by an API, or stored in plaintext — verified by test, not inspection.
6. `git status` shows no weights, database files, clips, or `.env`.
7. Commit messages explain **why**, per `CODE_STYLE.md` §7.

---

## Known open contradictions

Recorded rather than silently resolved. Each must be fixed in the living document (which wins) or in `spec.md`, not by guessing.

| Where | Conflict | Resolution |
|---|---|---|
| `docs/memory.md`, `docs/tasks.md` | Still say detector selection is deferred; `spec.md` §10.4 names YOLOX-s as the provisional default | Living document wins — update `memory.md`/`tasks.md`, or re-defer in `spec.md` |
| `docs/API.md` | Says every route requires auth, then exempts `/api/v1/system/health` | Resolve explicitly: health is unauthenticated by design |
