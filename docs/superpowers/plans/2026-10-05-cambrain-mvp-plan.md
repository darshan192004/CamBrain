# CamBrain MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the CamBrain MVP — an edge AI sidecar that adds object detection, ROI rules, event clips, and Telegram alerting to existing NVR/CCTV systems, running offline on an Intel N100 Windows box.

**Architecture:** Single Python process. One thread per camera running an async pipeline (source → motion gate → detector → tracker → rules engine). FastAPI on `127.0.0.1:8765` for REST and WebSocket. SQLite in WAL mode for persistence. Vue 3 + Tauri v2 shell for the dashboard. Every async step is testable from a file fixture via the `FrameSource` protocol, so CI needs no cameras.

**Tech Stack:** Python 3.13 · FastAPI · PyAV · ONNX Runtime · SQLAlchemy 2.0 · Alembic · SQLite (WAL) · Vue 3 (JavaScript) · Vite · Tailwind · shadcn-vue · Tauri v2 · pytest · MediaMTX (Docker)

**Canonical spec:** [`docs/superpowers/specs/spec.md`](../specs/spec.md) — the complete technical specification: product scope, environment baseline, component contracts, build sequence, test specification, and the full requirement-to-test verification matrix.

**Living documents:** [`docs/prd.md`](../../prd.md) · [`docs/architecture.md`](../../architecture.md) · [`docs/memory.md`](../../memory.md) · [`docs/DATABASE.md`](../../DATABASE.md) · [`docs/API.md`](../../API.md) · [`docs/SECURITY.md`](../../SECURITY.md) · [`docs/CODE_STYLE.md`](../../CODE_STYLE.md) · [`docs/rules.md`](../../rules.md) · [`docs/design.md`](../../design.md)

> Where a living document and `spec.md` disagree, the living document wins and `spec.md` is corrected.

---

## Global Constraints

These apply to every task in this plan. Copied verbatim from the spec documents.

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

Everything this plan creates. One responsibility per file.

```
E:\CamBrain\
├── README.md
├── .gitignore
├── .pre-commit-config.yaml
├── pyproject.toml                      # ruff, mypy, pytest config
├── requirements.txt                    # runtime deps, locked
├── requirements-dev.txt                # test deps
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                      # FastAPI app factory, lifespan
│   │   ├── core/
│   │   │   ├── config.py                # pydantic-settings, env + file
│   │   │   ├── logging.py               # structlog + REDACT_KEYS processor
│   │   │   ├── crypto.py                # Fernet + DPAPI key management
│   │   │   └── errors.py                # CamBrainError hierarchy
│   │   ├── db/
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
│   │   │       ├── base.py              # TenantScopedRepository — site_id required
│   │   │       ├── cameras.py
│   │   │       ├── rois.py
│   │   │       ├── rules.py
│   │   │       └── events.py
│   │   ├── services/
│   │   │   ├── stream/
│   │   │   │   ├── source.py            # FrameSource Protocol, Frame dataclass
│   │   │   │   ├── file_source.py       # FileSource
│   │   │   │   ├── rtsp_source.py       # RtspSource, backoff, stall watchdog
│   │   │   │   ├── motion.py            # MotionGate (MOG2)
│   │   │   │   ├── slot.py              # LatestFrameSlot (backpressure)
│   │   │   │   ├── pipeline.py          # CameraPipeline
│   │   │   │   └── stream_manager.py    # StreamManager (lifecycle owner)
│   │   │   ├── inference/
│   │   │   │   ├── tiers.py             # hardware capability detection
│   │   │   │   ├── detector.py          # Detector Protocol, ONNX wrapper
│   │   │   │   ├── yolox_post.py        # anchor-free decode + NMS
│   │   │   │   └── pool.py              # bounded thread pool
│   │   │   ├── tracker/
│   │   │   │   └── tracker.py           # IoU tracker
│   │   │   ├── alerts/
│   │   │   │   ├── roi.py               # point-in-polygon, centroid
│   │   │   │   ├── rules.py             # pure evaluate()
│   │   │   │   └── notifier.py          # Notifier Protocol
│   │   │   └── events/
│   │   │       ├── ring_buffer.py       # pre-roll ring buffer
│   │   │       └── clip_writer.py       # ClipWriter
│   │   └── api/
│   │       ├── deps.py                  # auth dependency, tenant scope
│   │       ├── schemas.py               # Pydantic request/response models
│   │       ├── routers/
│   │       │   ├── auth.py
│   │       │   ├── cameras.py
│   │       │   ├── rois.py
│   │       │   ├── rules.py
│   │       │   ├── events.py
│   │       │   ├── users.py
│   │       │   ├── settings.py
│   │       │   └── system.py
│   │       └── ws/
│   │           ├── alerts.py            # alerts topic
│   │           └── frames.py            # frames topic
│   ├── alembic.ini
│   ├── migrations/
│   │   ├── env.py
│   │   ├── script.py.mako
│   │   └── versions/
│   │       └── 0001_initial.py
│   ├── scripts/
│   │   ├── fetch_model.py               # checksum-pinned weight download
│   │   └── benchmark_detector.py        # YOLOX-s vs RT-DETR-r18
│   └── tests/
│       ├── conftest.py                  # fixtures: tmp db, MockDetector, sources
│       ├── fixtures/
│       │   └── clips/                   # generated .mp4 (gitignored, built in Task 0.4)
│       ├── make_fixtures.py             # synthetic clip generator
│       ├── rtsp/
│       │   ├── conftest.py              # MediaMTX container fixture
│       │   └── test_rtsp_source.py      # marked @pytest.mark.rtsp
│       ├── test_logging.py              # redaction proof
│       ├── test_crypto.py               # Fernet roundtrip + DPAPI
│       ├── test_source.py               # protocol conformance, both sources
│       ├── test_motion.py
│       ├── test_slot.py                 # backpressure semantics
│       ├── test_pipeline.py
│       ├── test_stream_manager.py       # memory-flatness, backoff
│       ├── test_tiers.py
│       ├── test_detector.py
│       ├── test_yolox_post.py
│       ├── test_pool.py
│       ├── test_roi.py
│       ├── test_tracker.py
│       ├── test_rules.py                # table-driven
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
│       └── test_soak.py                 # 24h soak, marked slow
├── frontend/
│   ├── package.json
│   ├── vite.config.js
│   ├── tailwind.config.js
│   ├── eslint.config.js
│   ├── index.html
│   ├── src/
│   │   ├── main.js
│   │   ├── App.vue
│   │   ├── router/index.js
│   │   ├── stores/{auth,cameras,rois,rules,events,system}.js
│   │   ├── api/client.js               # fetch wrapper, token handling
│   │   ├── types/index.js              # JSDoc typedefs
│   │   ├── styles/tokens.css           # CSS variables
│   │   ├── components/
│   │   │   ├── ui/                     # shadcn-vue primitives, restyled
│   │   │   ├── AppShell.vue  Sidebar.vue  TopBar.vue  StatusBar.vue
│   │   │   ├── CameraGrid.vue  CameraTile.vue
│   │   │   ├── AddCameraDialog.vue
│   │   │   ├── RoiEditor.vue
│   │   │   ├── EventTable.vue  EventThumb.vue
│   │   │   └── RulesEditor.vue
│   │   └── views/
│   │       ├── LoginView.vue  CamerasView.vue  EventsView.vue
│   │       ├── SettingsView.vue
│   └── src-tauri/
│       ├── Cargo.toml  tauri.conf.json
│       └── src/{main.rs,lib.rs,tray.rs}
└── models/
    ├── .gitkeep
    └── LICENSE-MODEL-NOTICE
```

---

## Verification Matrix

Every non-functional requirement in `prd.md` §6 mapped to the test that proves it. If a row has no test, the NFR is unproven.

| NFR | Target | Proving test | Phase |
|---|---|---|---|
| Concurrent cameras | 8 per box | `test_pipeline.py::test_eight_pipelines_concurrently` | 1 |
| Hardware floor | N100, graceful below | `test_tiers.py::test_tier_falls_back_on_low_capability` | 3 |
| Detection latency | < 2s motion → alert | `test_pipeline.py::test_motion_to_alert_under_2s` | 3 |
| Sample rate | 2–5 FPS configurable | `test_pipeline.py::test_sample_fps_is_honoured` | 1 |
| Reconnect transient | ≤ 5s | `test_stream_manager.py::test_transient_drop_recovers_fast` | 1 |
| Reconnect persistent | backoff to 60s | `test_stream_manager.py::test_backoff_reaches_cap` | 1 |
| **Memory flat** | no growth across days | `test_stream_manager.py::test_memory_is_flat_across_reconnects` | 1 |
| **Jitter** | no thundering herd | `test_stream_manager.py::test_backoff_has_jitter` | 1 |
| Idle CPU | < 5% no motion | `test_pipeline.py::test_idle_cpu_under_5_percent` | 1 |
| Disk | clips only, quota-capped | `test_clip_writer.py::test_quota_refuses_writes` | 5 |
| Resolution | works at 1080p | `test_source.py::test_1080p_input_downscaled` | 1 |
| Uptime | 24h unattended | `test_soak.py::test_24h_soak` (marked slow) | 6 |
| Offline | full function, Telegram fails | `test_telegram.py::test_offline_event_survives` | 5 |
| Boot | starts without login | manual, Phase 6 gate | 6 |
| Tenant isolation | 404 cross-tenant | `test_repositories.py::test_cross_tenant_read_returns_404` | 2 |
| No AGPL | licence scan | CI step, Task 0.6 | 0 |
| Secret redaction | never logged | `test_logging.py::test_no_secret_in_log_output` | 0 |

---

# Phase 0 — Bootstrap

**Purpose:** produce a working dev environment and the project's safety rails before any feature work. Install failures discovered inside Phase 1 masquerade as code bugs; this phase removes that ambiguity.

**Gate:** `pytest` runs green on an empty suite, `ruff` clean, MediaMTX reachable, a synthetic clip decodes, CI licence scan configured.

## Task 0.1: Python project scaffold

**Files:**
- Create: `requirements.txt`
- Create: `requirements-dev.txt`
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `backend/app/__init__.py`
- Create: `backend/tests/__init__.py`

**Interfaces:**
- Consumes: nothing (first task)
- Produces: `requirements.txt` (runtime floors), `pyproject.toml` (`[tool.pytest.ini_options]` with `asyncio_mode = "auto"` and marker registration), virtualenv at `E:\CamBrain\.venv`

- [ ] **Step 1: Create the virtualenv and install dev tools**

```powershell
cd E:\CamBrain
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

Expected: pip reports a version and no error.

- [ ] **Step 2: Write `requirements.txt`**

Version floors, not fabricated pins. The lock is generated in Step 5.

```
# Runtime dependencies for CamBrain.
# Licence gate: NO AGPL packages. See docs/memory.md D1.

# --- Core engine ---
av>=13.0.0                      # RTSP decode. BSD. Bundles its own FFmpeg.
onnxruntime>=1.19.0            # CPU inference. MIT.
numpy>=2.0.0                   # MIT.
opencv-python-headless>=4.10.0 # MOG2 background subtraction. Apache-2.0.
                                # headless build: no Qt, smaller on the box.

# --- API ---
fastapi>=0.115.0                # MIT.
uvicorn[standard]>=0.32.0       # BSD.
pydantic>=2.9.0                 # MIT.
pydantic-settings>=2.6.0        # MIT.
websockets>=13.0                # BSD.

# --- Persistence ---
sqlalchemy>=2.0.35              # MIT.
alembic>=1.14.0                 # MIT.

# --- Security ---
cryptography>=43.0.0            # Apache-2.0 OR BSD-3-Clause. Fernet + DPAPI.
argon2-cffi>=23.1.0             # MIT. Password hashing.

# --- Networking / notifications ---
httpx>=0.27.0                   # BSD. Telegram client + async-capable.
psutil>=6.1.0                   # BSD. RSS, disk usage, CPU. Soak test needs it.

# --- Observability ---
structlog>=24.4.0               # MIT. Structured logs with a redaction chain.
```

> **Why `opencv-python-headless` and not `opencv-python`:** the full build bundles Qt, adding ~80MB to the installer for a product that renders its UI in a web view. Headless gives us `cv2.createBackgroundSubtractorMOG2` and `cv2.VideoWriter` with none of that.

- [ ] **Step 3: Write `requirements-dev.txt`**

```
-r requirements.txt

pytest>=8.3.0
pytest-asyncio>=0.24.0
pytest-cov>=6.0.0
psutil>=6.1.0
ruff>=0.8.0
mypy>=1.13.0
pre-commit>=4.0.0
types-psutil>=6.1.0
```

- [ ] **Step 4: Write `pyproject.toml`**

```toml
[project]
name = "cambrain"
version = "0.1.0"
description = "Edge AI sidecar for existing CCTV systems"
requires-python = ">=3.13"

[tool.pytest.ini_options]
testpaths = ["backend/tests"]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
markers = [
    "rtsp: requires the MediaMTX Docker container (deselect with '-m \"not rtsp\"')",
    "slow: long-running; soak and benchmark tests (deselect with '-m \"not slow\"')",
]
addopts = "-ra --strict-markers --strict-config"
filterwarnings = ["error::DeprecationWarning:app.*"]

[tool.ruff]
line-length = 100
target-version = "py313"
src = ["backend"]

[tool.ruff.lint]
select = [
    "E",    # pycodestyle errors
    "W",    # warnings
    "F",    # pyflakes
    "I",    # isort
    "N",    # pep8-naming
    "UP",   # pyupgrade
    "ASYNC",# flake8-async — catches blocking calls in async def
    "B",    # flake8-bugbear
    "C4",   # comprehensions
    "SIM",  # simplify
    "RET",  # return consistency
    "PTH",  # pathlib
    "TID",  # tidy imports
    "ARG",  # unused arguments
]
ignore = [
    "E501",  # line length is handled by the formatter
]

[tool.ruff.lint.per-file-ignores]
# Tests may use asserts, magic numbers, and private access.
"backend/tests/*" = ["S101", "PLR2004", "SLF001"]

[tool.mypy]
python_version = "3.13"
strict = true
warn_unreachable = true
plugins = ["pydantic.mypy"]
exclude = ["backend/migrations/"]

[[tool.mypy.overrides]]
module = ["av.*", "onnxruntime.*", "cv2.*"]
ignore_missing_imports = true

[tool.ruff.format]
quote-style = "double"
indent-style = "space"
```

> **`ASYNC` in the lint set is load-bearing, not decoration.** It flags a blocking call inside `async def` — exactly the bug that would stall every camera pipeline at once. This codebase runs eight concurrent pipelines on four cores; a synchronous 200ms call in the wrong place is an outage.

- [ ] **Step 5: Write `.gitignore`**

```gitignore
# --- Model weights: fetched by scripts/fetch_model.py, never committed ---
models/*.onnx
models/*.bin
models/*.pt

# --- Runtime data ---
*.db
*.db-wal
*.db-shm
data/
clips/
logs/
keys/

# --- Generated test fixtures: rebuilt by tests/make_fixtures.py ---
backend/tests/fixtures/clips/*.mp4

# --- Python ---
.venv/
__pycache__/
*.py[cod]
*.egg-info/
.mypy_cache/
.ruff_cache/
.pytest_cache/
htmlcov/
.coverage
coverage.xml

# --- Node ---
node_modules/
frontend/dist/
.vite/

# --- Rust / Tauri ---
frontend/src-tauri/target/
frontend/src-tauri/gen/

# --- Secrets: never, under any circumstance ---
.env
.env.*
!.env.example
*.pem
*.key

# --- Editors / OS ---
.vscode/
.idea/
Thumbs.db
desktop.ini
.DS_Store
```

> **`*.key` is ignored deliberately.** The Fernet master key lives at `%LOCALAPPDATA%\CamBrain\keys\master.key`; if a developer ever points the app at a repo-local key path, git must refuse it.

- [ ] **Step 6: Create package markers**

```powershell
New-Item -ItemType File -Force -Path "backend\app\__init__.py"
New-Item -ItemType File -Force -Path "backend\tests\__init__.py"
```

- [ ] **Step 7: Install dependencies**

```powershell
python -m pip install -r requirements-dev.txt
```

Expected: installs cleanly. On Windows this can take several minutes (onnxruntime and opencv are large wheels).

- [ ] **Step 8: Verify the toolchain**

```powershell
python -c "import av, onnxruntime, numpy, cv2, sqlalchemy, cryptography, structlog; print('runtime deps OK')"
python -m pytest --collect-only
python -m ruff check backend
python -m mypy backend
```

Expected: `runtime deps OK`; pytest exits 5 (no tests collected) which is success at this stage; ruff and mypy report no errors.

- [ ] **Step 9: Generate the lock file**

```powershell
python -m pip freeze > requirements.lock.txt
```

- [ ] **Step 10: Commit**

```powershell
git add .gitignore pyproject.toml requirements.txt requirements-dev.txt requirements.lock.txt backend/app/__init__.py backend/tests/__init__.py
git commit -m "chore(deps): bootstrap Python project with pinned dependency floors

pyproject.toml pins the lint rules the whole codebase depends on. ASYNC is
included deliberately: a blocking call inside async def would stall all
eight camera pipelines at once on a 4-core box.

opencv-python-headless avoids pulling Qt (~80MB) for a product whose UI
renders in a web view.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 0.2: Structured logging with structural redaction

**Files:**
- Create: `backend/app/core/__init__.py`
- Create: `backend/app/core/logging.py`
- Create: `backend/tests/test_logging.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `get_logger(name: str) -> structlog.stdlib.BoundLogger`
  - `configure_logging(level: str = "INFO", json_output: bool | None = None) -> None`
  - `REDACTED: str` — the `"••••••••"` sentinel
  - `mask_url(url: str) -> str` — masks RTSP userinfo

This module is the **structural** guarantee that secrets cannot be logged. Redaction is a processor in the chain, so it applies to every event regardless of what a caller passes. A developer cannot leak a password by forgetting, because there is no code path that bypasses the chain.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_logging.py`:

```python
"""Prove secrets cannot reach the log, regardless of caller discipline."""

from __future__ import annotations

import io
import logging

import pytest

from app.core.logging import REDACTED, configure_logging, get_logger, mask_url

SECRET = "sup3rSecretValue123"


def _capture_logs(caplog: pytest.LogCaptureFixture) -> str:
    return caplog.text


def test_no_secret_in_log_output(caplog: pytest.LogCaptureFixture) -> None:
    """Every REDACT_KEY must be stripped from emitted log records."""
    configure_logging(level="DEBUG")

    logger = get_logger("test")
    logger.info(
        "camera config",
        rtsp_password=SECRET,
        password=SECRET,
        token=SECRET,
        bot_token=SECRET,
        api_key=SECRET,
        secret=SECRET,
        authorization=SECRET,
        camera_name="Back door",  # not a secret — must survive
    )

    output = _capture_logs(caplog)
    assert SECRET not in output, "a secret leaked into the log"
    assert "Back door" in output, "non-secret fields must not be redacted"
    assert REDACTED in output


def test_rtsp_url_userinfo_is_masked(caplog: pytest.LogCaptureFixture) -> None:
    """An RTSP URL in a log must not carry credentials."""
    configure_logging(level="DEBUG")

    url = f"rtsp://admin:{SECRET}@10.0.0.5:554/Streaming/Channels/101"
    logger = get_logger("test")
    logger.warning("camera unreachable", rtsp_url=url, detail=url)

    output = _capture_logs(caplog)
    assert SECRET not in output
    assert "10.0.0.5" in output, "host is needed to diagnose"
    assert "Streaming/Channels/101" in output, "path is needed to diagnose"
    assert "***" in output


def test_redaction_is_case_insensitive() -> None:
    """A caller using RTSP_PASSWORD must still be redacted."""
    from app.core.logging import redact_event

    event = {"RTSP_PASSWORD": SECRET, "Bot_Token": SECRET, "safe": "keep-me"}
    redacted = redact_event(event)

    assert redacted["RTSP_PASSWORD"] == REDACTED
    assert redacted["Bot_Token"] == REDACTED
    assert redacted["safe"] == "keep-me"


def test_exception_messages_are_redacted() -> None:
    """A secret inside an exception message must not survive."""
    from app.core.logging import redact_value

    result = redact_value(f"failed to connect with password {SECRET}")
    assert SECRET not in str(result)


@pytest.mark.parametrize(
    ("raw", "expected_contains", "expected_excludes"),
    [
        ("rtsp://admin:pw@10.0.0.5:554/stream", "10.0.0.5", "admin"),
        ("rtsp://10.0.0.5:554/stream", "10.0.0.5", "@"),
        ("not a url at all", "not a url at all", "\0"),
    ],
)
def test_mask_url(
    raw: str, expected_contains: str, expected_excludes: str
) -> None:
    masked = mask_url(raw)
    assert expected_contains in masked
    assert expected_excludes not in masked
```

- [ ] **Step 2: Run the test to verify it fails**

```powershell
python -m pytest backend/tests/test_logging.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app'`

> **If you get that import error**, the package is not on the path. `pyproject.toml` sets `src = ["backend"]` for ruff, which is not the same as a runtime path. Add to `pyproject.toml` under `[tool.pytest.ini_options]`:
> ```toml
> pythonpath = ["backend"]
> ```

- [ ] **Step 3: Write the implementation**

`backend/app/core/logging.py`:

```python
"""Structured logging with structural secret redaction.

Owns: log formatting and the guarantee that secrets never reach a log sink.
Does not own: what gets logged (callers decide that) or where logs go.

Redaction lives in the structlog processor chain rather than at call sites.
That placement is the whole point: a developer cannot leak a credential by
forgetting to mask it, because every event passes through this processor.
"""

from __future__ import annotations

import logging
import re
import sys
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import structlog

REDACTED = "••••••••"

# Keys whose values are secret regardless of context.
# Matching is case-insensitive and substring-based, so `RTSP_PASSWORD` and
# `telegram_bot_token_enc` are both caught by the entries below.
REDACT_KEYS: frozenset[str] = frozenset(
    {
        "password",
        "passwd",
        "pwd",
        "secret",
        "token",
        "bot_token",
        "api_key",
        "apikey",
        "access_token",
        "refresh_token",
        "authorization",
        "auth",
        "credential",
        "credentials",
        "private_key",
        "session_token",
        "jwt_secret",
        "master_key",
        "signature",
        "salt",
    }
)

# Encrypted-at-rest columns: the ciphertext is not a secret, but logging it
# is pointless noise and invites confusion during debugging.
_REDACT_SUFFIXES = ("_enc", "_encrypted", "_ciphertext")

# rtsp://user:password@host:port/path  ->  rtsp://***:***@host:port/path
_URL_CREDENTIALS = re.compile(r"(?P<scheme>[a-zA-Z][a-zA-Z0-9+.-]*://)(?P<creds>[^/@\s]+)@")

# A secret pasted into free text ("failed with password hunter2").
# Catches keyword-prefixed values without over-matching ordinary prose.
_INLINE_SECRET = re.compile(
    r"(?i)\b(password|passwd|pwd|token|secret|api[_-]?key|authorization)"
    r"(?:=|:|\s+)"
    r"(?P<value>[^\s,;'\"}]{3,})"
)


def mask_url(url: str) -> str:
    """Strip credentials from a URL, preserving host, port, and path.

    Preserving the host and path matters: an installer reading a log needs to
    know *which* camera and *which* channel failed. Only userinfo is removed.

    Args:
        url: Any string. Non-URLs pass through with inline secrets masked.

    Returns:
        The URL with userinfo replaced by `***:***`.

    Examples:
        >>> mask_url("rtsp://admin:pw@10.0.0.5:554/stream")
        'rtsp://***:***@10.0.0.5:554/stream'
    """
    masked = _URL_CREDENTIALS.sub(r"\g<scheme>***:***@", url)
    return _INLINE_SECRET.sub(_replace_inline_secret, masked)


def _replace_inline_secret(match: re.Match[str]) -> str:
    keyword = match.group(1)
    return f"{keyword}={REDACTED}"


def _is_secret_key(key: str) -> bool:
    """Return True when a field name indicates the value must not be logged."""
    normalised = key.lower()
    if normalised in REDACT_KEYS:
        return True
    return any(normalised.endswith(suffix) for suffix in _REDACT_SUFFIXES)


def redact_value(value: Any) -> Any:
    """Recursively redact a single value.

    Strings get inline masking. Mappings and sequences are walked so a secret
    nested inside an exception dict is still caught.
    """
    if isinstance(value, str):
        return _INLINE_SECRET.sub(_replace_inline_secret, value)
    if isinstance(value, dict):
        return redact_event(value)
    if isinstance(value, (list, tuple)):
        return type(value)(redact_value(item) for item in value)
    return value


def redact_event(
    _logger: Any, _method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """structlog processor: redact secrets from an event before formatting.

    This is deliberately a no-op on the logger and method name — structlog
    processors take that signature — so it drops cleanly into the chain.
    """
    return {
        key: (REDACTED if _is_secret_key(key) else redact_value(value))
        for key, value in event_dict.items()
    }


def redact_exc_info(_logger: Any, _method_name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """structlog processor: scrub secret URLs from exception text.

    An exception message is the single most common leak vector, because it
    is often built by string interpolation at the raise site rather than
    passed as a structured field.
    """
    exc_info = event_dict.get("exc_info")
    if exc_info and event_dict.get("exception"):
        event_dict["exception"] = mask_url(str(event_dict["exception"]))
    return event_dict


def configure_logging(level: str = "INFO", json_output: bool | None = None) -> None:
    """Configure structlog + stdlib logging.

    Args:
        level: Standard logging level name.
        json_output: Force JSON (`logs/`) or console (`--dev`) format. `None`
            means JSON when not in a TTY, which is the production default.
    """
    if json_output is None:
        json_output = not sys.stdout.isatty()

    numeric_level = getattr(logging, level.upper(), logging.INFO)

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=numeric_level,
        force=True,
    )
    # uvicorn and httpx are chatty at INFO and we have nothing to learn from them.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("watchfiles").setLevel(logging.WARNING)

    renderer = (
        structlog.processors.JSONRenderer()
        if json_output
        else structlog.dev.ConsoleRenderer(colors=sys.stdout.isatty())
    )

    structlog.configure(
        processors=[
            # Order matters. Context is bound first so request/camera ids are
            # available; redaction runs last so nothing reaches a sink.
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            redact_event,
            redact_exc_info,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=[],
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )
    logging.getLogger().handlers[0].setFormatter(formatter)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a bound logger.

    Args:
        name: Usually `__name__`.

    Returns:
        A logger that has already passed through the redaction chain.
    """
    return structlog.get_logger(name)
```

- [ ] **Step 4: Run the test to verify it passes**

```powershell
python -m pytest backend/tests/test_logging.py -v
```

Expected: PASS, 8 tests.

- [ ] **Step 5: Run the full quality gate**

```powershell
python -m ruff check backend/app/core/logging.py
python -m mypy backend/app/core/logging.py
```

Expected: clean.

- [ ] **Step 6: Commit**

```powershell
git add backend/app/core/__init__.py backend/app/core/logging.py backend/tests/test_logging.py
git commit -m "feat(core): structured logging with structural secret redaction

Redaction is a processor in the structlog chain rather than a convention at
call sites. A developer cannot leak a credential by forgetting to mask one,
because every event passes through the processor before reaching a sink.

mask_url preserves host, port and path because an installer diagnosing a
failed camera needs to know which channel failed; only userinfo is stripped.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 0.3: Domain error hierarchy

**Files:**
- Create: `backend/app/core/errors.py`
- Create: `backend/tests/test_errors.py`

**Interfaces:**
- Consumes: nothing
- Produces: `CamBrainError` (base), `StreamError`, `DetectionError`, `InferenceError`, `RuleError`, `NotificationError`, `StorageError`, `AuthError`, `NotFoundError`, `ValidationError`, and `mask()` re-exported from `app.core.logging`

Written before the services because every later module raises from this set. Errors are part of a module's public interface — callers branch on them — so the set must be settled before ten modules start defining their own.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_errors.py`:

```python
"""The error hierarchy must be catchable at three levels of specificity."""

from __future__ import annotations

import pytest

from app.core.errors import (
    CamBrainError,
    DetectionError,
    InferenceError,
    NotFoundError,
    StreamError,
)


def test_all_errors_subclass_base() -> None:
    """Catching CamBrainError must catch every domain error."""
    for error_type in (StreamError, InferenceError, DetectionError, NotFoundError):
        assert issubclass(error_type, CamBrainError)


def test_catch_by_specific_type() -> None:
    """A caller can branch on the narrow type where it matters."""
    with pytest.raises(StreamError) as excinfo:
        raise StreamError("RTSP handshake failed")
    assert "handshake" in str(excinfo.value)


def test_catch_by_family() -> None:
    """A caller handling all inference problems uses one except clause."""
    with pytest.raises(CamBrainError):
        raise InferenceError("model output shape mismatch")


def test_error_message_never_contains_url_credentials() -> None:
    """Raising with a URL must not leak credentials through the message."""
    from app.core.errors import safe_error

    message = safe_error("cannot reach rtsp://admin:hunter2@10.0.0.5:554/stream")
    assert "hunter2" not in message
    assert "10.0.0.5" in message


def test_cause_is_preserved() -> None:
    """`from exc` chaining must survive so tracebacks stay diagnosable."""
    original = ValueError("low level failure")
    with pytest.raises(StreamError) as excinfo:
        raise StreamError("container open failed") from original

    assert excinfo.value.__cause__ is original
```

- [ ] **Step 2: Run it to verify it fails**

```powershell
python -m pytest backend/tests/test_errors.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'app.core.errors'`

- [ ] **Step 3: Write the implementation**

`backend/app/core/errors.py`:

```python
"""Domain exception hierarchy.

Owns: the set of failures callers may branch on.
Does not own: recovery logic. Raising a domain error is a statement about
what failed; deciding what to do next belongs to the caller.

Every module raises from this set rather than defining its own exception.
That gives two catch granularities that both matter in practice:
`except CamBrainError` for "shut this camera down cleanly", and
`except StreamError` for "this is a transport problem, retry".
"""

from __future__ import annotations

from app.core.logging import mask_url


class CamBrainError(Exception):
    """Base for every CamBrain domain error.

    Catching this means "something in this process failed in a way we
    anticipated". Anything not deriving from it is a bug.
    """


class StreamError(CamBrainError):
    """Frame acquisition failed: transport, decode, or source lifecycle.

    Sub-classing note: a transport failure is expected and recoverable — the
    pipeline reconnects. This is the single most frequently raised error in
    the codebase, which is why it has its own type rather than sharing one.
    """


class DetectionError(CamBrainError):
    """Detection output could not be interpreted.

    Raised when a model returns something structurally unexpected. Distinct
    from InferenceError because the model ran fine; the result was unusable.
    """


class InferenceError(CamBrainError):
    """Inference could not run: model missing, session creation failed, bad input."""


class RuleError(CamBrainError):
    """A rule could not be evaluated or is structurally invalid."""


class NotificationError(CamBrainError):
    """Alert delivery failed. Never fatal — the event is already persisted."""


class StorageError(CamBrainError):
    """Disk or database operation failed: quota exceeded, unwritable path, locked DB."""


class AuthError(CamBrainError):
    """Authentication or authorisation failed."""


class NotFoundError(CamBrainError):
    """A requested entity does not exist within the caller's tenant scope.

    Used for cross-tenant access too. See `docs/SECURITY.md` §4.3: a 403 would
    confirm the row exists, so tenancy violations surface as not-found.
    """


class ValidationError(CamBrainError):
    """Input failed domain validation, beyond what Pydantic already checked."""


def safe_error(message: str) -> str:
    """Scrub credentials from a message before it becomes an exception string.

    Call this whenever building an exception message from a URL or from text
    that might interpolate one. The logging layer redacts *emitted* events,
    but an exception message can be captured and re-raised elsewhere before
    it ever reaches a log.

    Args:
        message: Raw message.

    Returns:
        The message with URL credentials and inline secrets masked.
    """
    return mask_url(message)
```

- [ ] **Step 4: Run the test to verify it passes**

```powershell
python -m pytest backend/tests/test_errors.py -v
```

Expected: PASS, 5 tests.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/core/errors.py backend/tests/test_errors.py
git commit -m "feat(core): domain error hierarchy

Two catch granularities that both matter in practice: CamBrainError for
'shut this camera down cleanly', and the specific subclass for 'this is a
transport problem, retry'. StreamError is separate because transport failure
is the most frequently raised error here by design.

safe_error exists because log redaction protects emitted events, but an
exception message can be re-raised elsewhere before it ever reaches a log.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---