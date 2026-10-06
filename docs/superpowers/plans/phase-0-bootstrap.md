# Phase 0 — Bootstrap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a working development environment and the project's safety rails — structural log redaction, the domain error hierarchy, secret encryption, synthetic fixtures, a real RTSP harness, and an AGPL licence guard — before any feature code exists.

**Architecture:** No application architecture yet. This phase establishes the four boundaries every later phase depends on: a `structlog` processor chain no caller can bypass, an exception hierarchy catchable at two granularities, a DPAPI-wrapped secret key, and a test strategy in which **no test ever needs a camera**.

**Tech Stack:** Python 3.13 · pytest · pytest-asyncio · ruff · mypy · pre-commit · structlog · cryptography · PyAV · MediaMTX (Docker) · GitHub Actions · Vue 3 + Vite + Tailwind

**Spec:** [`../specs/spec.md`](../specs/spec.md) — §2 stack · §3 licensing · §8.2–8.3 secrets · §11 test specification · §12 verification matrix
**Index:** [`2026-10-05-cambrain-mvp-plan.md`](2026-10-05-cambrain-mvp-plan.md) — shared Global Constraints, whole-repo File Structure, full Verification Matrix, phase dependency graph

**Phase gate (spec §10):** `pytest` green on an empty suite · `ruff check` and `mypy` clean · MediaMTX answers on its RTSP port · a synthetic clip decodes · the CI licence scan fails on a planted AGPL dependency.

**Depends on:** nothing. This is the entry point. Phases 1 and 2 may run in parallel afterwards (spec §10.2).

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

## Quality bar for Phase 0

Every phase plan carries this section. The content here is specific to what *this* phase can break — later phases carry their own.

### Code quality
- `ruff check` and `mypy` must be clean from the **first commit**. Retrofitting lint onto a dirty tree is how lint gets disabled.
- `--strict-markers --strict-config` in `pyproject.toml` (`Task 0.1`). A mistyped marker like `@pytest.mark.rtsp` spelled `rtsp_` would otherwise silently deselect the test instead of failing the run — the exact failure mode that hides a red suite.
- The `ASYNC` ruff rule set is enabled. It flags a blocking call inside `async def`, which is the bug that stalls all eight camera pipelines at once on four cores. Catching it at lint time costs nothing; finding it at 02:00 costs a customer.
- Every module gets a module docstring; every public function a Google-style docstring (spec §13.4).
- No `Any` outside tests and protocol boundaries.

### Scalability
- Phase 0 adds no runtime path, but it installs the two switches that let the suite scale without hardware: markers `rtsp` (real transport, needs Docker) and `slow` (24h soak). Both are **registered**, so `--strict-markers` turns a typo into a failure rather than a quiet skip.
- Version *floors* in `requirements.txt`, exact pins in a generated `requirements.lock.txt`. CI installs from the lock; a developer machine and CI resolve the same graph. Hand-fabricated exact pins are prohibited — a pin that does not resolve is a self-inflicted failure in the phase whose entire job is removing self-inflicted failures.
- `structlog` processor-chain redaction is O(1) per event and applied centrally, so log volume can grow later without per-call-site cost or drift.

### Maintainability
- **Redaction is a processor, not a convention.** No future developer can leak a credential by omission, because every event passes through the chain before reaching a sink.
- **Errors are catchable at two granularities** — `CamBrainError` for "shut this camera down cleanly", the specific subclass for "this is a transport problem, retry". Callers choose without string-matching messages.
- **Fixtures are generated by code, never committed as binary.** `tests/make_fixtures.py` makes clips reproducible, reviewable in a diff, and free to git.
- `mask_url()` lives in one place and is re-exported where needed, so RTSP userinfo masking cannot diverge between logging and error paths.

### Testability
- The **hardware-free rule** starts here and is never relaxed: clips are generated, RTSP comes from MediaMTX, detections come from a mock. No test may require a camera (spec §11.1).
- RTSP tests are marked `rtsp`. When Docker is unavailable they **skip with a visible message — never silently pass.** A silently-passing skip is indistinguishable from a green suite.
- Phase 0's coverage bar is deliberately narrow: it is infrastructure, not logic. The near-complete *branch* coverage obligations belong to `rtsp_source.py`, `yolox_post.py`, and `rules.py` in Phases 1 and 3 (spec §11.5).

### Performance / resources
- No runtime path exists yet, so the resource under management is **feedback time**: the default command `pytest -m "not rtsp and not slow"` must stay fast enough to run after every edit.
- The clip generator writes 300-frame fixtures at modest resolution — enough to exercise decode and the motion gate, small enough to regenerate in seconds.

### Security / observability
- `test_no_secret_in_log_output` is a **canary covering a bug class, not a function**: it logs every `REDACT_KEYS` key plus a credentialed RTSP URL and asserts none survive.
- The licence scan is a **build-breaking CI step**, not a report. Its own test is planting a known-AGPL dependency and confirming the job fails.
- Master key is DPAPI-wrapped, so another OS user on the box cannot decrypt it. On non-Windows dev, `0600` plus a loud warning — never a silent fallback.

---

## File Structure — Phase 0 only

Only what this phase creates. The whole-repo structure lives in the [index](2026-10-05-cambrain-mvp-plan.md#file-structure).

```
E:\CamBrain\
├── .gitignore                          # weights, .env, cambrain.db, clips, fixtures
├── .pre-commit-config.yaml             # ruff, mypy, eslint, prettier
├── pyproject.toml                      # ruff, mypy, pytest config (markers, addopts)
├── requirements.txt                    # runtime version floors
├── requirements-dev.txt                # test/lint floors
├── requirements.lock.txt               # GENERATED by pip freeze — never hand-edited
├── .github/
│   └── workflows/
│       └── ci.yml                      # pytest + ruff + mypy + AGPL licence scan
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   └── core/
│   │       ├── __init__.py
│   │   ├── logging.py              # structlog chain, REDACT_KEYS, mask_url()
│   │   ├── errors.py               # CamBrainError hierarchy
│   │   └── crypto.py               # Fernet + DPAPI master key
│   ├── scripts/
│   │   ├── __init__.py
│   │   ├── check_licences.py       # AGPL scan — CI job licence-scan
│   │   └── check_forbidden_files.py# commit guard: weights, secrets, DB, footage
│   └── tests/
│       ├── __init__.py
│       ├── conftest.py                 # shared fixtures (clip paths, tmp dirs)
│       ├── make_fixtures.py            # synthetic clip generator (gitignored output)
│       ├── fixtures/clips/             # GENERATED, gitignored
│       ├── test_logging.py             # CANARY: test_no_secret_in_log_output
│       ├── test_errors.py
│       ├── test_crypto.py
│       ├── test_make_fixtures.py       # proves PyAV decodes what we generate
│       ├── test_forbidden_files.py     # proves the commit guard fires
│       ├── test_licence_scan.py        # proves AGPL detection catches a plant
│       └── rtsp/
│           ├── __init__.py
│           ├── conftest.py                 # MediaMTX container fixture, skip-not-pass
│           └── test_harness.py             # @pytest.mark.rtsp — raw PyAV over RTSP
└── frontend/
    ├── package.json                    # npm-resolved deps; dev/build/lint/format scripts
    ├── package-lock.json               # exact npm resolution
    ├── vite.config.js                  # dev proxy → 127.0.0.1:8765
    ├── eslint.config.js                # jsdoc/require-jsdoc enforced
    ├── .prettierignore
    ├── index.html
    └── src/
        ├── main.js
        ├── App.vue
        └── style.css                   # Tailwind v4 CSS-first import
```

---

## Verification matrix — Phase 0 rows

Rows from [`spec.md` §12](../specs/spec.md) assigned to Phase 0, plus phase-local gates.

| Requirement | Proving test | Source |
|---|---|---|
| **No secret in logs** | `test_logging.py::test_no_secret_in_log_output` | spec §12 |
| Fernet roundtrip + DPAPI | `test_crypto.py` | spec §12 |
| Error hierarchy catchable | `test_errors.py` | spec §12 |
| **No AGPL anywhere** | CI licence scan step, proven by planted dependency | spec §12 |
| Synthetic clip decodes | `test_make_fixtures.py::test_generated_clip_decodes_with_pyav` | phase gate |
| RTSP harness reachable | `rtsp/test_harness.py::test_reads_frames_from_rtsp` | phase gate |
| Hardware-free default suite | `pytest -m "not rtsp and not slow"` passes with Docker stopped | spec §11.1 |

---

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
    "ASYNC",# flake8-async â€” catches blocking calls in async def
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

> **`ASYNC` in the lint set is load-bearing, not decoration.** It flags a blocking call inside `async def` â€” exactly the bug that would stall every camera pipeline at once. This codebase runs eight concurrent pipelines on four cores; a synchronous 200ms call in the wrong place is an outage.

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
  - `REDACTED: str` â€” the `"â€¢â€¢â€¢â€¢â€¢â€¢â€¢â€¢"` sentinel
  - `mask_url(url: str) -> str` â€” masks RTSP userinfo

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
        camera_name="Back door",  # not a secret â€” must survive
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

REDACTED = "â€¢â€¢â€¢â€¢â€¢â€¢â€¢â€¢"

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

    This is deliberately a no-op on the logger and method name â€” structlog
    processors take that signature â€” so it drops cleanly into the chain.
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

Written before the services because every later module raises from this set. Errors are part of a module's public interface â€” callers branch on them â€” so the set must be settled before ten modules start defining their own.

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

Expected: FAIL â€” `ModuleNotFoundError: No module named 'app.core.errors'`

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

    Sub-classing note: a transport failure is expected and recoverable â€” the
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
    """Alert delivery failed. Never fatal â€” the event is already persisted."""


class StorageError(CamBrainError):
    """Disk or database operation failed: quota exceeded, unwritable path, locked DB."""


class AuthError(CamBrainError):
    """Authentication or authorisation failed."""


class NotFoundError(CamBrainError):
    """A requested entity does not exist within the caller's tenant scope.

    Used for cross-tenant access too. See `docs/SECURITY.md` Â§4.3: a 403 would
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

## Task 0.4: Secret encryption — Fernet with a DPAPI-wrapped master key

**Files:**
- Create: `backend/app/core/crypto.py`
- Create: `backend/tests/test_crypto.py`

**Interfaces:**
- Consumes: `StorageError` from `app.core.errors` (Task 0.3)
- Produces:
  - `CryptoError(StorageError)` — defined here, so callers catch `CryptoError` for key problems or `StorageError` for any durability problem
  - `ensure_master_key(key_dir: Path | None = None) -> Path`
  - `get_fernet(key_dir: Path | None = None) -> Fernet`
  - `encrypt(plaintext: str, key_dir: Path | None = None) -> str`
  - `decrypt(token: str, key_dir: Path | None = None) -> str`
  - `ENV_KEY_DIR = "CAMBRAIN_KEY_DIR"`

Resolution order for the key directory: explicit `key_dir` → `$CAMBRAIN_KEY_DIR` → `%LOCALAPPDATA%\CamBrain` (Windows) or `~/.config/cambrain` (elsewhere).

- [ ] **Step 1: Write the failing test**

`backend/tests/test_crypto.py`:

```python
"""Prove secrets encrypt, decrypt, and fail loudly — never silently."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from app.core.crypto import (
    ENV_KEY_DIR,
    CryptoError,
    _load_raw,
    decrypt,
    encrypt,
    ensure_master_key,
)
from app.core.errors import StorageError

SAMPLE_URL = "rtsp://admin:hunter2@192.168.1.10:554/Streaming/Channels/101"


@pytest.fixture
def key_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolate the key store per test and force a fresh key."""
    monkeypatch.setenv(ENV_KEY_DIR, str(tmp_path))
    return tmp_path


def test_roundtrip_preserves_value_exactly(key_dir: Path) -> None:
    """Encrypt then decrypt must be byte-identical — no trimming, no re-encoding."""
    token = encrypt(SAMPLE_URL, key_dir)
    assert token != SAMPLE_URL
    assert decrypt(token, key_dir) == SAMPLE_URL


def test_token_is_url_safe_text(key_dir: Path) -> None:
    """A Fernet token must survive a TEXT column and a JSON round-trip."""
    token = encrypt(SAMPLE_URL, key_dir)
    assert token.isascii()
    assert all(c.isalnum() or c in "-_" for c in token)


def test_tampered_token_raises_crypto_error(key_dir: Path) -> None:
    """HMAC must reject modified ciphertext rather than returning garbage."""
    token = encrypt("secret", key_dir)
    tampered = ("A" * 8) + token[8:]
    with pytest.raises(CryptoError):
        decrypt(tampered, key_dir)


def test_wrong_key_raises_crypto_error(tmp_path: Path) -> None:
    """A key from another installation must not decrypt this ciphertext."""
    token = encrypt("secret", tmp_path / "site-a")
    with pytest.raises(CryptoError):
        decrypt(token, tmp_path / "site-b")


def test_crypto_error_is_catchable_at_both_granularities() -> None:
    """Callers may catch CryptoError for detail or StorageError for strategy."""
    assert issubclass(CryptoError, StorageError)


def test_key_directory_is_created_on_demand(key_dir: Path) -> None:
    """A fresh installation has no key directory yet."""
    nested = key_dir / "nested" / "deeper"
    path = ensure_master_key(nested)
    assert path.exists()
    assert path.parent == nested


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI is Windows-only")
def test_master_key_is_dpapi_wrapped(key_dir: Path) -> None:
    """Stored bytes must differ from the unwrapped key, proving DPAPI ran."""
    path = ensure_master_key(key_dir)
    assert path.read_bytes() != _load_raw(path)


@pytest.mark.skipif(sys.platform == "win32", reason="0600 fallback is POSIX-only")
def test_key_file_is_0600_on_posix(key_dir: Path) -> None:
    """The non-Windows fallback must be restrictive, never silently permissive."""
    import stat

    path = ensure_master_key(key_dir)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_same_key_is_reused_within_one_installation(key_dir: Path) -> None:
    """Two encryptions in one installation share a key; re-creating it must not
    orphan earlier ciphertext."""
    first = encrypt("keep-me", key_dir)
    ensure_master_key(key_dir)
    assert decrypt(first, key_dir) == "keep-me"
```

- [ ] **Step 2: Run the test to verify it fails**

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/test_crypto.py -v
```

Expected: **FAIL / collection error** — `ModuleNotFoundError: No module named 'app.core.crypto'`.

- [ ] **Step 3: Write the minimal implementation**

`backend/app/core/crypto.py`:

```python
"""Fernet encryption for secrets at rest, keyed by a DPAPI-wrapped master key.

The master key is generated once per installation. On Windows it is wrapped
with DPAPI so decryption is scoped to the OS user account — another user on
the box cannot decrypt it. DPAPI rather than a user passphrase because
installers hand these boxes to customers; a passphrase becomes a support
call when the owner forgets it.

On non-Windows development machines the key file falls back to 0600
permissions with a loud warning. Never a silent permissive fallback.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import logging
import os
import sys
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from app.core.errors import CryptoError, StorageError

log = logging.getLogger(__name__)

KEY_FILENAME = "master.key"
ENV_KEY_DIR = "CAMBRAIN_KEY_DIR"
CRYPTPROTECT_UI_FORBIDDEN = 0x1

_fernets: dict[str, Fernet] = {}


class CryptoError(StorageError):
    """Raised when key access, encryption, or decryption fails."""


class _DataBlob(ctypes.Structure):
    """Win32 DATA_BLOB, laid out for CryptProtectData/CryptUnprotectData."""

    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _key_dir(key_dir: Path | None = None) -> Path:
    """Resolve the directory holding the master key."""
    if key_dir is not None:
        return Path(key_dir)
    env = os.environ.get(ENV_KEY_DIR)
    if env:
        return Path(env)
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "CamBrain"
    return Path.home() / ".config" / "cambrain"


def _dpapi(data: bytes, unprotect: bool) -> bytes:
    """Wrap or unwrap bytes through Windows DPAPI."""
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    buf = ctypes.create_string_buffer(data, len(data))
    source = _DataBlob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    target = _DataBlob()

    ctypes.set_last_error(0)
    call = kernel32.CryptUnprotectData if unprotect else kernel32.CryptProtectData
    if not call(ctypes.byref(source), None, None, None, None,
                CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(target)):
        raise CryptoError(f"DPAPI call failed (WinError {ctypes.get_last_error()})")
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        kernel32.LocalFree(target.pbData)


def _protect(raw: bytes) -> bytes:
    """Seal the raw key. DPAPI on Windows, file permissions elsewhere."""
    if sys.platform == "win32":
        return _dpapi(raw, unprotect=False)
    return raw


def _unprotect(stored: bytes) -> bytes:
    """Unseal the raw key."""
    if sys.platform == "win32":
        return _dpapi(stored, unprotect=True)
    return stored


def ensure_master_key(key_dir: Path | None = None) -> Path:
    """Create the master key if absent and return its path."""
    directory = _key_dir(key_dir)
    path = directory / KEY_FILENAME
    if path.exists():
        return path

    directory.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_protect(Fernet.generate_key()))
    if sys.platform != "win32":
        path.chmod(0o600)
        log.warning(
            "master key is not DPAPI-protected on this platform; "
            "restricted to file mode 0600 at %s",
            path,
        )
    log.info("generated a new master key at %s", path)
    return path


def _load_raw(path: Path) -> bytes:
    """Read and unseal the master key from disk."""
    try:
        return _unprotect(path.read_bytes())
    except OSError as exc:
        raise CryptoError(f"cannot read master key at {path}") from exc


def get_fernet(key_dir: Path | None = None) -> Fernet:
    """Return the cipher for this installation, cached by key path."""
    path = ensure_master_key(key_dir)
    cache_key = str(path)
    cipher = _fernets.get(cache_key)
    if cipher is None:
        cipher = Fernet(_load_raw(path))
        _fernets[cache_key] = cipher
    return cipher


def encrypt(plaintext: str, key_dir: Path | None = None) -> str:
    """Encrypt a secret into URL-safe token text safe for a TEXT column."""
    return get_fernet(key_dir).encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(token: str, key_dir: Path | None = None) -> str:
    """Decrypt a token, raising CryptoError rather than returning garbage."""
    try:
        return get_fernet(key_dir).decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeError) as exc:
        raise CryptoError("token failed authentication") from exc
```

`backend/app/core/__init__.py` already exists (Task 0.2). Nothing else changes.

- [ ] **Step 4: Run the test to verify it passes**

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/test_crypto.py -v
```

Expected: **PASS** — 9 tests.

- [ ] **Step 5: Lint and type-check**

```powershell
.\.venv\Scripts\python.exe -m ruff check backend
.\.venv\Scripts\python.exe -m mypy backend/app
```

Expected: clean. `# type: ignore[union-attr]` is **not** an acceptable escape here — narrow the type instead.

- [ ] **Step 6: Commit**

```powershell
git add backend/app/core/crypto.py backend/tests/test_crypto.py
git commit -m "feat: encrypt secrets at rest with a DPAPI-wrapped Fernet key

Secrets must be unreadable to another OS user on the box. DPAPI scopes
decryption to the account, which beats a passphrase that an installer
would have to remember and a customer would forget.

Non-Windows dev falls back to 0600 plus a warning — restrictive rather
than a silent permissive default."
```

---

## Task 0.5: Synthetic fixture generator

**Files:**
- Create: `backend/tests/make_fixtures.py`
- Create: `backend/tests/test_make_fixtures.py`
- Modify: `backend/tests/conftest.py` (create)

**Interfaces:**
- Consumes: nothing — this is test infrastructure, not application code
- Produces:
  - `CLIPS_DIR: Path` → `backend/tests/fixtures/clips` (gitignored)
  - `CLIP_NAMES: tuple[str, ...]` → `("static", "motion", "brightness_shift", "low_light", "multi_object")`
  - `ensure_clip(name: str) -> Path` — generates on demand, returns the path
  - conftest fixture `clip_path` → `Path` to the generated motion clip
  - conftest fixture `clips: dict[str, Path]` → all five, generated lazily

**Why code and not committed files:** binary test data is unreviewable in a diff and inflates the repo. Generated clips are reproducible from a one-line call and versioned with the generator that defines them (spec §11.2).

- [ ] **Step 1: Write the failing test**

`backend/tests/test_make_fixtures.py`:

```python
"""Prove the generator produces clips PyAV can actually decode."""

from __future__ import annotations

import av
import pytest

from tests.make_fixtures import CLIP_NAMES, ensure_clip


def test_every_named_clip_decodes_to_the_expected_frame_count() -> None:
    """A fixture that will not decode is worse than no fixture — it hides the
    real failure behind a decoder error."""
    expected_frames = {"static": 300, "motion": 300, "brightness_shift": 300}
    for name, count in expected_frames.items():
        path = ensure_clip(name)
        with av.open(str(path)) as container:
            decoded = list(container.decode(container.streams.video[0]))
        assert len(decoded) == count, f"{name} decoded {len(decoded)} frames"


def test_decoded_frames_are_1080p_safe_dimensions() -> None:
    """Fixtures run thousands of times; 640x360 keeps the suite fast while
    still exercising the same code paths as a real sub-stream."""
    path = ensure_clip("motion")
    with av.open(str(path)) as container:
        frame = next(container.decode(container.streams.video[0]))
    assert frame.width == 640
    assert frame.height == 360


def test_brightness_shift_changes_every_pixel_mid_clip() -> None:
    """The day→night cut is the whole point of this fixture: the motion gate
    must reset instead of firing a burst of false alerts."""
    path = ensure_clip("brightness_shift")
    with av.open(str(path)) as container:
        frames = list(container.decode(container.streams.video[0]))
    first_mean = float(frames[0].to_ndarray(format="gray").mean())
    last_mean = float(frames[-1].to_ndarray(format="gray").mean())
    assert last_mean - first_mean > 50


def test_ensure_clip_is_idempotent() -> None:
    """Generating twice must not rewrite — tests call this constantly."""
    first = ensure_clip("motion")
    first.write_bytes(first.read_bytes())
    stamp = first.stat().st_mtime_ns
    assert ensure_clip("motion") == first
    assert first.stat().st_mtime_ns == stamp


def test_unknown_clip_name_is_rejected() -> None:
    """A typo should fail loudly, not silently generate an empty file."""
    with pytest.raises(KeyError):
        ensure_clip("does_not_exist")


def test_clip_names_cover_every_fixture_documented_in_the_spec() -> None:
    """spec §11.2 lists five clips. Adding one there without adding it here
    means the scenario is silently untested."""
    assert set(CLIP_NAMES) == {
        "static",
        "motion",
        "brightness_shift",
        "low_light",
        "multi_object",
    }
```

- [ ] **Step 2: Run the test to verify it fails**

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/test_make_fixtures.py -v
```

Expected: **FAIL** — `ModuleNotFoundError: No module named 'tests.make_fixtures'`.

- [ ] **Step 3: Write the minimal implementation**

`backend/tests/make_fixtures.py`:

```python
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
        frame[140:220, x:x + 80] = (230, 230, 230)
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
        frame[120:300, x:x + 70] = 45
        yield frame


def _multi_object() -> Iterator[np.ndarray]:
    """Three candidates; only one crosses into the right-hand zone."""
    for i in range(FRAME_COUNT):
        frame = np.full((HEIGHT, WIDTH, 3), 25, dtype=np.uint8)
        frame[40:100, 20 + i:80 + i] = (180, 180, 180)
        frame[150:210, 400:460] = (160, 160, 160)
        if i > 150:
            frame[250:320, 320 + (i - 150):380 + (i - 150)] = (235, 235, 235)
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
```

`backend/tests/conftest.py`:

```python
"""Fixtures shared by every backend test.

Clips are generated on demand and never committed (spec §11.2).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.make_fixtures import CLIP_NAMES, ensure_clip


@pytest.fixture
def clip_path() -> Path:
    """Path to the generated motion clip — the default input for stream tests."""
    return ensure_clip("motion")


@pytest.fixture
def clips() -> dict[str, Path]:
    """Every documented fixture clip, generated lazily on first access."""
    return {name: ensure_clip(name) for name in CLIP_NAMES}
```

- [ ] **Step 4: Run the test to verify it passes**

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/test_make_fixtures.py -v
```

Expected: **PASS** — 6 tests. First run takes a few seconds while clips are encoded.

- [ ] **Step 5: Confirm the clips are ignored**

```powershell
git check-ignore -v backend/tests/fixtures/clips/motion.mp4
```

Expected: a `.gitignore` rule matches (added in Task 0.1 under `# Generated test fixtures`).

- [ ] **Step 6: Commit**

```powershell
git add backend/tests/make_fixtures.py backend/tests/test_make_fixtures.py backend/tests/conftest.py
git commit -m "test: generate synthetic clips instead of committing binaries

Binary fixtures are unreviewable in a diff and never shrink. The suite
must run with no camera attached, so the five scenarios from spec 11.2
are produced from NumPy arrays and encoded with PyAV on demand."
```

---

## Task 0.6: MediaMTX RTSP harness

**Files:**
- Create: `backend/tests/rtsp/__init__.py` (empty)
- Create: `backend/tests/rtsp/conftest.py`
- Create: `backend/tests/rtsp/test_harness.py`
- Modify: `.gitignore` (append one rule)

**Interfaces:**
- Consumes: `ensure_clip("motion")` from Task 0.5
- Produces:
  - session fixture `mediamtx_url: str` → `rtsp://127.0.0.1:8554/cambbrain`
  - `docker_available() -> bool` — daemon reachable, not merely installed
  - `RTSP_URL: str`, `RTSP_PORT: int`, `STREAM_NAME: str`

**Scope note:** `RtspSource` does not exist yet — it is written in Phase 1, Task 1.4. This task proves the **harness**: that MediaMTX serves a real generated clip over a real RTSP handshake, and that the failure mode for a bad path is observable rather than a hang. Phase 1's `test_rtsp_source.py` then tests the application class against this same fixture.

A mock would never exercise the code most likely to be wrong: PyAV RTSP option handling, handshake behaviour, and reconnection against a real server (spec §11.1).

- [ ] **Step 1: Write the failing test**

`backend/tests/rtsp/test_harness.py`:

```python
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
    with pytest.raises((av.error.FFmpegError, OSError)):
        with av.open(bad_url, options={"rtsp_transport": "tcp"}) as container:
            next(container.decode(container.streams.video[0]))
```

- [ ] **Step 2: Run the test to verify it fails**

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/rtsp -v
```

Expected: **FAIL** — `fixture 'mediamtx_url' not found`.

- [ ] **Step 3: Write the harness**

`backend/tests/rtsp/conftest.py`:

```python
"""MediaMTX container fixture for real-RTSP tests.

Spec §11.1: RTSP tests are marked `rtsp`. When Docker is unavailable they
skip with a visible message — never silently pass. A silently-passing skip
is indistinguishable from a green suite, which is how a broken transport
layer survives to production.
"""

from __future__ import annotations

import shutil
import subprocess
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import av
import pytest

from tests.make_fixtures import ensure_clip

MEDIAMTX_IMAGE = "bluenviron/mediamtx:1.11"
RTSP_HOST = "127.0.0.1"
RTSP_PORT = 8554
STREAM_NAME = "cambbrain"
RTSP_URL = f"rtsp://{RTSP_HOST}:{RTSP_PORT}/{STREAM_NAME}"
STARTUP_TIMEOUT_S = 60
CONFIG_DIR = Path(__file__).parent / ".mediamtx"

CONFIG = f"""\
logLevel: warn
rtsp: yes
rtspAddress: :{RTSP_PORT}
gopCache: no
paths:
  {STREAM_NAME}:
"""


def docker_available() -> bool:
    """True when the daemon answers — `docker` on PATH alone proves nothing."""
    if shutil.which("docker") is None:
        return False
    try:
        result = subprocess.run(
            ["docker", "info"], capture_output=True, timeout=30, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _publish(clip: Path, stop: threading.Event) -> None:
    """Push the clip to MediaMTX in a loop so readers always have a source."""
    while not stop.is_set():
        try:
            _publish_once(clip, stop)
        except (av.error.FFmpegError, OSError, ConnectionError, TimeoutError):
            if stop.is_set():
                return
            time.sleep(1.0)


def _publish_once(clip: Path, stop: threading.Event) -> None:
    """One continuous publish of the clip."""
    with av.open(str(clip)) as source:
        in_stream = source.streams.video[0]
        with av.open(
            RTSP_URL, mode="w", format="rtsp", options={"rtsp_transport": "tcp"}
        ) as sink:
            out_stream = sink.add_stream("libx264", rate=15)
            out_stream.width = in_stream.codec_context.width
            out_stream.height = in_stream.codec_context.height
            out_stream.pix_fmt = "yuv420p"
            for frame in source.decode(in_stream):
                if stop.is_set():
                    return
                rgb = av.VideoFrame.from_ndarray(
                    frame.to_ndarray(format="rgb24"), format="rgb24"
                )
                for packet in out_stream.encode(rgb):
                    sink.mux(packet)
            for packet in out_stream.encode():
                sink.mux(packet)


def _await_frames(timeout: int) -> None:
    """Block until the stream really delivers, or fail loudly with a reason."""
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with av.open(RTSP_URL, options={"rtsp_transport": "tcp"}) as probe:
                next(probe.decode(probe.streams.video[0]))
            return
        except (av.error.FFmpegError, OSError, StopIteration) as exc:
            last_error = exc
            time.sleep(1.0)
    raise RuntimeError(f"MediaMTX served no frame within {timeout}s: {last_error}")


@pytest.fixture(scope="session")
def mediamtx_url() -> Iterator[str]:
    """Start MediaMTX and a clip publisher once for the whole session."""
    if not docker_available():
        pytest.skip(
            "Docker is not available — RTSP tests need MediaMTX (spec §11.1). "
            "Start Docker Desktop, then re-run with: pytest -m rtsp"
        )

    CONFIG_DIR.mkdir(exist_ok=True)
    (CONFIG_DIR / "mediamtx.yml").write_text(CONFIG, encoding="utf-8")

    container = subprocess.Popen(
        [
            "docker", "run", "--rm",
            "-p", f"{RTSP_PORT}:{RTSP_PORT}",
            "-v", f"{CONFIG_DIR}:/etc/mediamtx:ro",
            MEDIAMTX_IMAGE,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    stop = threading.Event()
    publisher = threading.Thread(
        target=_publish, args=(ensure_clip("motion"), stop), daemon=True
    )
    publisher.start()
    try:
        _await_frames(STARTUP_TIMEOUT_S)
        yield RTSP_URL
    finally:
        stop.set()
        publisher.join(timeout=10)
        container.terminate()
        try:
            container.wait(timeout=15)
        except subprocess.TimeoutExpired:
            container.kill()
            container.wait(timeout=5)
```

`backend/tests/rtsp/__init__.py`: empty file.

- [ ] **Step 4: Run with Docker unavailable — it must skip, not fail**

Stop the Docker daemon, then:

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/rtsp -v -rs
```

Expected: **3 skipped**, with the message `Docker is not available — RTSP tests need MediaMTX (spec §11.1). Start Docker Desktop, then re-run with: pytest -m rtsp`.

A silent skip here is a failure of this task.

- [ ] **Step 5: Run with Docker running — it must pass**

Start Docker Desktop, then:

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/rtsp -v -rs
```

Expected: **3 passed**. First run pulls `bluenviron/mediamtx:1.11`.

- [ ] **Step 6: Confirm the default suite still ignores RTSP tests**

```powershell
.\.venv\Scripts\python.exe -m pytest -m "not rtsp and not slow"
```

Expected: RTSP tests **deselected**, everything else green, no Docker required.

- [ ] **Step 7: Ignore the harness state directory**

Append to `.gitignore`:

```
# RTSP harness state — regenerated per test session
backend/tests/rtsp/.mediamtx/
```

- [ ] **Step 8: Commit**

```powershell
git add backend/tests/rtsp .gitignore
git commit -m "test: stand up MediaMTX so RTSP is tested against a real server

A mock would never exercise the code most likely to break: PyAV option
handling, the handshake, and reconnect behaviour. MediaMTX is conformant,
not a mock. Skips loudly when Docker is down rather than passing quietly."
```

---

## Task 0.7: CI workflow with an AGPL licence scan

**Files:**
- Create: `backend/scripts/__init__.py` (empty)
- Create: `backend/scripts/check_licences.py`
- Create: `backend/tests/test_licence_scan.py`
- Create: `.github/workflows/ci.yml`
- Modify: `requirements-dev.txt` (append `pyyaml`)

**Interfaces:**
- Consumes: `requirements-dev.txt` (Task 0.1)
- Produces:
  - `DENIED_PACKAGES: frozenset[str]` — packages banned by name regardless of metadata
  - `find_agpl_violations(records: Iterable[tuple[str, str]]) -> list[str]`
  - `python_records() -> list[tuple[str, str]]` — from installed distribution metadata
  - `frontend_records(lock_path: Path) -> list[tuple[str, str]]` — from `package-lock.json`
  - CLI `check_licences.py`: exit `0` clean, exit `1` with a per-line report on any hit
  - CI job `licence-scan`

**Why a name deny-list as well as metadata scanning:** a package whose metadata is absent, stale, or wrong would slip past a licence-string check. `ultralytics` is banned by name (spec §3.1), so it fails even with empty metadata.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_licence_scan.py`:

```python
"""Prove the licence scan fails on AGPL — including a planted dependency."""

from __future__ import annotations

from scripts.check_licences import DENIED_PACKAGES, find_agpl_violations


def test_detects_agpl_in_licence_expression() -> None:
    assert find_agpl_violations([("somepkg", "AGPL-3.0-or-later")])


def test_detects_agpl_in_classifier_text() -> None:
    hits = find_agpl_violations(
        [("somepkg", "License :: OSI Approved :: GNU Affero General Public License v3")]
    )
    assert len(hits) == 1


def test_allows_every_permitted_licence() -> None:
    """Permissive licences must never trip the gate — a noisy gate gets disabled."""
    for licence in ("MIT", "Apache-2.0", "BSD-3-Clause", "BSD", "MPL-2.0", ""):
        assert find_agpl_violations([("somepkg", licence)]) == [], licence


def test_plain_gpl_is_not_flagged_as_agpl() -> None:
    """GPL and AGPL are different obligations. Conflating them would either
    block permitted dependencies or, worse, teach us to ignore the gate."""
    assert find_agpl_violations([("lgplv3", "LGPL-3.0-or-later")]) == []
    assert find_agpl_violations([("gplpkg", "GPL-3.0-only")]) == []


def test_ultralytics_is_denied_even_with_empty_metadata() -> None:
    """The known offender is banned by name; metadata cannot clear it."""
    assert "ultralytics" in DENIED_PACKAGES
    assert find_agpl_violations([("ultralytics", "")]) == [
        "ultralytics (denied by name)"
    ]


def test_case_insensitive_detection() -> None:
    assert find_agpl_violations([("somepkg", "agpl-3.0")])


def test_reports_every_violation_not_just_the_first() -> None:
    """A one-line-at-a-time report turns a licence audit into a guessing game."""
    hits = find_agpl_violations([("a", "AGPL-3.0"), ("b", "MIT"), ("c", "Affero GPL")])
    assert len(hits) == 2
```

- [ ] **Step 2: Run the test to verify it fails**

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/test_licence_scan.py -v
```

Expected: **FAIL** — `ModuleNotFoundError: No module named 'scripts.check_licences'`.

- [ ] **Step 3: Write the minimal implementation**

`backend/scripts/check_licences.py`:

```python
"""Fail the build if any dependency carries an AGPL obligation.

The product is sold closed-source. Any AGPL dependency reachable from the
shipped application obliges disclosure of the whole application's source,
which defeats the business model (spec §3).

Exporting AGPL weights to ONNX changes the file format. It does not change
the licence attached to the weights — that is exactly how copyleft gets
violated unknowingly. This gate is the last line of defence.

Usage:
    python backend/scripts/check_licences.py
Exit codes: 0 clean · 1 violation found · 2 could not determine
"""

from __future__ import annotations

import importlib.metadata
import json
import sys
from collections.abc import Iterable
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_LOCK = REPO_ROOT / "frontend" / "package-lock.json"

DENIED_PACKAGES: frozenset[str] = frozenset(
    {
        "ultralytics",
        "ultralytics-thop",
    }
)

Record = tuple[str, str]


def _is_agpl(licence: str) -> bool:
    """Match AGPL specifically — never plain GPL or LGPL."""
    lowered = licence.lower()
    return "agpl" in lowered or "affero" in lowered


def find_agpl_violations(records: Iterable[Record]) -> list[str]:
    """Return one readable line per offending package."""
    violations: list[str] = []
    for name, licence in records:
        if not name:
            continue
        if name.lower() in DENIED_PACKAGES:
            violations.append(f"{name} ({licence or 'denied by name'})")
        elif _is_agpl(licence):
            violations.append(f"{name} ({licence})")
    return violations


def python_records() -> list[Record]:
    """Licence text for every installed distribution, from its own metadata."""
    records: list[Record] = []
    for dist in importlib.metadata.distributions():
        meta = dist.metadata
        name = (meta.get("Name") or "").strip()
        expression = (meta.get("License-Expression") or "").strip()
        legacy = (meta.get("License") or "").strip()
        classifiers = " ".join(
            c for c in (meta.get_all("Classifier") or []) if c.startswith("License ::")
        )
        records.append((name, " ".join(x for x in (expression, legacy, classifiers) if x)))
    return records


def frontend_records(lock_path: Path = FRONTEND_LOCK) -> list[Record]:
    """Licence text for every locked npm package. Absent lock = no records."""
    if not lock_path.exists():
        return []
    data = json.loads(lock_path.read_text(encoding="utf-8"))
    records: list[Record] = []
    for path, meta in data.get("packages", {}).items():
        if not path:
            continue
        name = path.split("node_modules/")[-1]
        licence = meta.get("license", "")
        if isinstance(licence, dict):
            licence = str(licence.get("type", ""))
        records.append((name, str(licence)))
    return records


def main() -> int:
    """Scan and report. Never warn — a warning nobody reads is not a gate."""
    records = python_records() + frontend_records()
    violations = find_agpl_violations(records)
    if violations:
        print("AGPL dependency detected — prohibited (spec §3):", file=sys.stderr)
        for line in violations:
            print(f"  - {line}", file=sys.stderr)
        return 1
    print(f"Licence scan clean ({len(records)} packages).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the test to verify it passes**

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/test_licence_scan.py -v
```

Expected: **PASS** — 7 tests.

- [ ] **Step 5: Run the scan itself**

```powershell
.\.venv\Scripts\python.exe backend\scripts\check_licences.py
```

Expected: `Licence scan clean (N packages).` and exit code `0`.

- [ ] **Step 6: Write the CI workflow**

`.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

jobs:
  backend:
    name: Backend checks
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"
          cache: pip

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          python -m pip install -r requirements.txt
          python -m pip install -r requirements-dev.txt

      - name: Ruff
        run: ruff check backend

      - name: Mypy
        run: mypy backend/app

      - name: Unit and integration tests
        run: pytest -m "not rtsp and not slow" --cov=app --cov-report=term-missing

      - name: Licence scan (fails on AGPL)
        run: python backend/scripts/check_licences.py

  licence-scan:
    name: Licence gate
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"
      - run: python -m pip install -r requirements.txt
      - run: python backend/scripts/check_licences.py
```

- [ ] **Step 7: Add PyYAML and verify the workflow parses**

Append to `requirements-dev.txt`:

```
pyyaml>=6.0.1
```

Then install and validate — a malformed workflow silently never runs, which for a licence gate means the gate does not exist:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -c "import yaml; d=yaml.safe_load(open('.github/workflows/ci.yml',encoding='utf-8')); assert 'jobs' in d and {'backend','licence-scan'} <= set(d['jobs']); print('ok')"
```

Expected: `ok`

- [ ] **Step 8: Prove the gate fires — one-time manual check**

Temporarily add `ultralytics>=8.0.0` to `requirements.txt`, install nothing, and run the scan against a planted record:

```powershell
.\.venv\Scripts\python.exe -c "from scripts.check_licences import find_agpl_violations; import sys; sys.exit(1 if find_agpl_violations([('ultralytics','')]) else 0)"
```

Expected: exit code `1`. Revert the change.

This is repeated as a gate checklist item at the end of the phase.

- [ ] **Step 9: Commit**

```powershell
git add backend/scripts backend/tests/test_licence_scan.py .github/workflows/ci.yml requirements-dev.txt
git commit -m "ci: fail the build on any AGPL dependency

An AGPL package in the shipped app obliges source disclosure, which
kills a closed-source product. Metadata scanning alone is not enough —
ultralytics is banned by name so empty or stale metadata cannot clear
it. Runs as its own job so the gate cannot be skipped by a lint failure."
```

---

## Task 0.8: Frontend scaffold with enforced JSDoc

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/vite.config.js`
- Create: `frontend/eslint.config.js`
- Create: `frontend/.prettierignore`
- Create: `frontend/index.html`
- Create: `frontend/src/main.js`
- Create: `frontend/src/App.vue`
- Create: `frontend/src/style.css`

**Interfaces:**
- Consumes: nothing — the frontend is independent of the backend until Phase 4
- Produces:
  - npm scripts: `dev`, `build`, `preview`, `lint`, `lint:fix`, `format`, `format:check`
  - `frontend/package.json` with **npm-resolved versions** (never hand-written — a fabricated major version is an install failure on day one)
  - Vite dev proxy for `/api` → `http://127.0.0.1:8765` and `/ws` → the same origin, matching the API bind in `spec.md` §7.1

**Why npm resolves the versions:** `requirements.txt` uses floors for the same reason. We know what we depend on; we do not know today's latest patch, and writing one we have not verified is how a scaffold fails before it runs.

- [ ] **Step 1: Write `frontend/package.json` with scripts only**

```json
{
  "name": "cambrain-dashboard",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview",
    "lint": "eslint .",
    "lint:fix": "eslint . --fix",
    "format": "prettier --write .",
    "format:check": "prettier --check ."
  }
}
```

- [ ] **Step 2: Let npm resolve real versions**

```powershell
cd E:\CamBrain\frontend
npm install vue vue-router pinia
npm install -D vite @vitejs/plugin-vue tailwindcss @tailwindcss/vite eslint @eslint/js eslint-plugin-vue eslint-plugin-jsdoc globals prettier
cd E:\CamBrain
```

Expected: `frontend/package.json` now carries a `dependencies` and `devDependencies` block with concrete, resolvable versions.

- [ ] **Step 3: Write the failing check — prove JSDoc is enforced**

`frontend/eslint.config.js`:

```js
import js from '@eslint/js'
import pluginVue from 'eslint-plugin-vue'
import pluginJsdoc from 'eslint-plugin-jsdoc'
import globals from 'globals'

/**
 * Flat ESLint config for the CamBrain dashboard.
 *
 * `jsdoc/require-jsdoc` is load-bearing, not stylistic: with no TypeScript,
 * JSDoc is the only machine-checked contract on module boundaries
 * (spec.md §9.2). It must fail loudly when absent.
 */
export default [
  { ignores: ['dist/**', 'node_modules/**'] },
  js.configs.recommended,
  ...pluginVue.configs['flat/recommended'],
  pluginJsdoc.configs['flat/recommended'],
  {
    files: ['**/*.js'],
    languageOptions: {
      sourceType: 'module',
      globals: { ...globals.browser, ...globals.node },
    },
    rules: {
      'jsdoc/require-jsdoc': [
        'error',
        {
          require: {
            FunctionDeclaration: true,
            FunctionExpression: false,
            ArrowFunctionExpression: true,
            ClassDeclaration: false,
            ClassExpression: false,
            MethodDefinition: false,
          },
          publicOnly: true,
        },
      ],
      'vue/multi-word-component-names': 'off',
    },
  },
]
```

`frontend/lint_probe.js` — a deliberately violating file, deleted after the check:

```js
/**
 * Temporary probe. Proves jsdoc/require-jsdoc actually fails the build
 * before we rely on it for the next six phases.
 *
 * @param {string} id camera id
 * @returns {Promise<Response>} raw response
 */
export const missingJSDoc = (id) => fetch(`/api/v1/cameras/${id}`)
```

Wait — that probe *has* JSDoc. Write it **without** the doc block:

```js
export const missingJSDoc = (id) => fetch(`/api/v1/cameras/${id}`)
```

- [ ] **Step 4: Run lint to verify it fails**

```powershell
cd E:\CamBrain\frontend
npm run lint
cd E:\CamBrain
```

Expected: **FAIL** — `frontend/lint_probe.js:1:1 Missing JSDoc comment @jsdoc/require-jsdoc`.

If this passes, the constraint from Global Constraints is not enforced and the whole rationale for choosing JavaScript over TypeScript has silently evaporated.

- [ ] **Step 5: Delete the probe and write the scaffold**

Delete `frontend/lint_probe.js`.

`frontend/vite.config.js`:

```js
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'

/**
 * Vite config for the dashboard.
 *
 * The dev proxy exists so the browser never talks to a second origin:
 * same-origin means no CORS preflight and no CSRF exemption to reason
 * about in Phase 2.
 *
 * @returns {object} Vite configuration
 */
export default defineConfig({
  plugins: [vue(), tailwindcss()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8765', changeOrigin: false },
      '/ws': { target: 'ws://127.0.0.1:8765', ws: true },
    },
  },
})
```

`frontend/index.html`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>CamBrain</title>
  </head>
  <body>
    <div id="app"></div>
    <script type="module" src="/src/main.js"></script>
  </body>
</html>
```

`frontend/src/style.css`:

```css
/* Tailwind v4 is CSS-first: the utility layer is imported, not generated
   from a JS config. Design tokens arrive in Phase 4 as CSS variables —
   hardcoded hex in components is prohibited (Global Constraints). */
@import 'tailwindcss';
```

`frontend/src/main.js`:

```js
import { createApp } from 'vue'
import App from './App.vue'
import './style.css'

createApp(App).mount('#app')
```

`frontend/src/App.vue`:

```vue
<script setup>
// Scaffold root. The real shell — sidebar, top bar, status bar, router —
// is built in Phase 4. This exists so `npm run build` produces a real bundle.
</script>

<template>
  <main class="p-8">
    <h1 class="text-2xl font-semibold">CamBrain</h1>
    <p class="text-sm opacity-70">Dashboard scaffold — Phase 4 builds the shell.</p>
  </main>
</template>
```

`frontend/.prettierignore`:

```
dist
node_modules
package-lock.json
```

- [ ] **Step 6: Lint and build — both must pass**

```powershell
cd E:\CamBrain\frontend
npm run format
npm run lint
npm run build
cd E:\CamBrain
```

Expected: `lint` exits 0 with no findings; `build` emits `frontend/dist/index.html` and exits 0.

- [ ] **Step 7: Commit**

```powershell
git add frontend
git commit -m "chore: scaffold the Vue dashboard with JSDoc enforcement

npm resolves the dependency versions so a fabricated major cannot break
the install. jsdoc/require-jsdoc is the only machine-checked contract
we get without TypeScript, so it is proven to fail before we rely on it.

The dev proxy targets 127.0.0.1:8765 so the browser stays same-origin —
no CORS wildcard, no CSRF exemption, later."
```

---

## Task 0.9: Pre-commit hooks and a structural guard against committing the wrong things

**Files:**
- Create: `backend/scripts/check_forbidden_files.py`
- Create: `backend/tests/test_forbidden_files.py`
- Create: `.pre-commit-config.yaml`

**Interfaces:**
- Consumes: `requirements-dev.txt` already carries `pre-commit>=4.0.0` (Task 0.1); ruff/mypy config (Task 0.1); eslint config (Task 0.8)
- Produces:
  - `FORBIDDEN: tuple[re.Pattern[str], ...]`
  - `ALLOWED: tuple[re.Pattern[str], ...]`
  - `find_forbidden(paths: Iterable[str]) -> list[str]`
  - CLI `check_forbidden_files.py [paths...]`: exit `0` clean, exit `1` listing every hit
  - `.pre-commit-config.yaml` with six local hooks

**Why local hooks and not a remote mirror:** ruff, mypy, and eslint versions are owned by this repo's dependency files. A pre-commit mirror pins its own version and would fight them. Local hooks run exactly what CI runs.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_forbidden_files.py`:

```python
"""Prove the things we must never commit are blocked structurally."""

from __future__ import annotations

from scripts.check_forbidden_files import find_forbidden


def test_blocks_model_weights() -> None:
    assert find_forbidden(["models/yolox_s.onnx"])
    assert find_forbidden(["models/yolox_nano.onnx"])


def test_blocks_env_and_key_material() -> None:
    assert find_forbidden([".env"])
    assert find_forbidden(["backend/.env.local"])
    assert find_forbidden(["master.key"])


def test_blocks_database_and_its_wal_sidecars() -> None:
    """A committed WAL can contain production secrets."""
    assert find_forbidden(["cambrain.db"])
    assert find_forbidden(["backend/cambrain.db-wal"])


def test_blocks_generated_media() -> None:
    assert find_forbidden(["backend/tests/fixtures/clips/motion.mp4"])


def test_blocks_frontend_build_output() -> None:
    assert find_forbidden(["frontend/node_modules/vue/index.js"])
    assert find_forbidden(["frontend/dist/index.html"])


def test_permits_the_model_licence_notice() -> None:
    """Apache-2.0 attribution is a legal obligation, not repo tidiness."""
    assert find_forbidden(["models/LICENSE-MODEL-NOTICE"]) == []


def test_permits_gitkeep_and_source() -> None:
    assert find_forbidden(["models/.gitkeep"]) == []
    assert find_forbidden(["backend/app/core/crypto.py"]) == []
    assert find_forbidden([".github/workflows/ci.yml"]) == []


def test_permits_a_clips_directory_without_media_in_it() -> None:
    """The directory is fine; the footage inside it is not."""
    assert find_forbidden(["backend/tests/fixtures/clips/"]) == []


def test_reports_every_path_not_just_the_first() -> None:
    hits = find_forbidden(["models/a.onnx", "ok.py", "cambrain.db"])
    assert len(hits) == 2


def test_normalises_windows_separators() -> None:
    """Git reports POSIX paths; a dev may pass Windows ones."""
    assert find_forbidden(["models\\yolox_s.onnx"])
```

- [ ] **Step 2: Run the test to verify it fails**

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/test_forbidden_files.py -v
```

Expected: **FAIL** — `ModuleNotFoundError: No module named 'scripts.check_forbidden_files'`.

- [ ] **Step 3: Write the minimal implementation**

`backend/scripts/check_forbidden_files.py`:

```python
"""Refuse to commit model weights, credentials, databases, or footage.

These are the Global Constraints of every commit, enforced rather than
remembered. Redaction in `app.core.logging` follows the same reasoning:
a rule that depends on discipline is a rule that will be broken at 3am.

Usage:
    python backend/scripts/check_forbidden_files.py [paths...]
With no arguments it reads `git diff --cached --name-only`.
Exit codes: 0 clean · 1 violation found
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Iterable
from re import Pattern

FORBIDDEN: tuple[Pattern[str], ...] = (
    re.compile(r"\.onnx$", re.IGNORECASE),
    re.compile(r"\.(pt|pth|weights|engine)$", re.IGNORECASE),
    re.compile(r"(^|/)\.env(\.[^/]+)?$", re.IGNORECASE),
    re.compile(r"(^|/)master\.key$", re.IGNORECASE),
    re.compile(r"(^|/)cambrain\.db", re.IGNORECASE),
    re.compile(r"(^|/)node_modules/", re.IGNORECASE),
    re.compile(r"^frontend/dist/", re.IGNORECASE),
    re.compile(r"(^|/)clips/.+\.(mp4|mkv|avi|jpg|jpeg|png)$", re.IGNORECASE),
)

ALLOWED: tuple[Pattern[str], ...] = (
    re.compile(r"LICENSE-MODEL-NOTICE$"),
    re.compile(r"\.gitkeep$"),
)


def find_forbidden(paths: Iterable[str]) -> list[str]:
    """Return every path that must not be committed, one per line."""
    hits: list[str] = []
    for raw in paths:
        path = raw.replace("\\", "/")
        if path.startswith("./"):
            path = path[2:]
        if not path:
            continue
        if any(allowed.search(path) for allowed in ALLOWED):
            continue
        if any(forbidden.search(path) for forbidden in FORBIDDEN):
            hits.append(path)
    return hits


def _staged_paths() -> list[str]:
    """Paths currently staged, as git reports them."""
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


def main(argv: list[str]) -> int:
    """Check and report. Every hit, not just the first."""
    paths = argv[1:] or _staged_paths()
    hits = find_forbidden(paths)
    if not hits:
        return 0
    print("Refusing to commit files that must never be committed:", file=sys.stderr)
    for hit in hits:
        print(f"  - {hit}", file=sys.stderr)
    print(
        "\nWeights are fetched by scripts/fetch_model.py; clips and fixtures are "
        "generated; .env and master.key are machine-local.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
```

- [ ] **Step 4: Run the test to verify it passes**

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/test_forbidden_files.py -v
```

Expected: **PASS** — 10 tests.

- [ ] **Step 5: Prove the CLI fires**

```powershell
.\.venv\Scripts\python.exe backend\scripts\check_forbidden_files.py models\fake.onnx ok.py
echo "exit: $LASTEXITCODE"
```

Expected: a two-line report and `exit: 1`.

- [ ] **Step 6: Write the pre-commit config**

`.pre-commit-config.yaml`:

```yaml
# Local hooks only. ruff, mypy, and eslint versions are owned by this repo's
# dependency files; a remote mirror would pin its own and fight them.
# Run with the virtualenv activated so `python` resolves to .venv.
repos:
  - repo: local
    hooks:
      - id: ruff
        name: ruff
        entry: python -m ruff check
        language: system
        types: [python]
        files: ^backend/

      - id: ruff-format
        name: ruff format
        entry: python -m ruff format --check
        language: system
        types: [python]
        files: ^backend/

      - id: mypy
        name: mypy
        entry: python -m mypy backend/app
        language: system
        types: [python]
        pass_filenames: false

      - id: forbidden-files
        name: no weights, secrets, databases, or footage
        entry: python backend/scripts/check_forbidden_files.py
        language: system
        pass_filenames: true

      - id: eslint
        name: eslint
        entry: npm --prefix frontend run lint
        language: system
        files: ^frontend/.*\.(js|vue)$
        pass_filenames: false

      - id: prettier
        name: prettier
        entry: npm --prefix frontend run format:check
        language: system
        files: ^frontend/
        pass_filenames: false
```

- [ ] **Step 7: Normalise existing code so the format hook can pass**

```powershell
.\.venv\Scripts\python.exe -m ruff format backend
.\.venv\Scripts\python.exe -m ruff check --fix backend
cd frontend; npm run format; cd E:\CamBrain
```

Expected: some files reformatted. Re-run the suite — it must still pass:

```powershell
.\.venv\Scripts\python.exe -m pytest -m "not rtsp and not slow"
```

Expected: **PASS**. A formatter that changes behaviour means the tests were wrong, not the formatter.

- [ ] **Step 8: Install and run every hook over every file**

```powershell
.\.venv\Scripts\python.exe -m pre_commit install
.\.venv\Scripts\python.exe -m pre_commit run --all-files
```

Expected: all six hooks **passed**. A non-zero exit here is a real finding — fix it before committing this task.

- [ ] **Step 9: Commit**

```powershell
git add .pre-commit-config.yaml backend/scripts/check_forbidden_files.py backend/tests/test_forbidden_files.py
git commit -m "chore: enforce commit hygiene with local pre-commit hooks

Weights, credentials, databases, and footage are forbidden by policy in
seven documents. A hook is the only version of that rule which survives
a tired author. Local hooks keep ruff, mypy, and eslint running the same
versions CI does instead of a mirror's pinned copy."
```

---

## Phase 0 gate checklist

Run in order. The phase is not done until every line is observed, not assumed (spec §13).

**Test suite**
- [ ] `pytest -m "not rtsp and not slow"` — green **with the Docker daemon stopped**, proving the hardware-free rule (spec §11.1)
- [ ] `pytest -m rtsp` — green **with Docker running**, 3 passed
- [ ] Stop Docker, re-run `pytest backend/tests/rtsp -rs` — **3 skipped with the visible MediaMTX message**, never a silent pass
- [ ] `pytest -m "not rtsp and not slow"` still green after reformatting (Task 0.9 Step 7)

**Static analysis**
- [ ] `ruff check backend` — clean
- [ ] `ruff format --check backend` — clean
- [ ] `mypy backend/app` — clean, no `# type: ignore` used to silence an error that could be narrowed
- [ ] `npm run lint` — clean
- [ ] `npm run build` — exit 0

**Gate demonstrations**
- [ ] `python backend/scripts/check_licences.py` — `Licence scan clean`, exit `0`
- [ ] **Planted-AGPL drill:** add `ultralytics` to `requirements.txt`, install it, run the scan — must exit `1` and name the package. Revert. (One-time proof the gate is not decorative; re-run whenever the scan script changes.)
- [ ] `python backend/scripts/check_forbidden_files.py models/fake.onnx` — exit `1`
- [ ] `pre-commit run --all-files` — all six hooks pass
- [ ] `test_no_secret_in_log_output` present in `backend/tests/test_logging.py` and passing
- [ ] `test_memory_is_flat_across_reconnects` **does not exist yet** — confirm it is scheduled for Phase 1, not silently dropped

**Repository hygiene**
- [ ] `git status` — clean; no weights, `.env`, `cambrain.db`, clips, `node_modules`, or `dist` staged
- [ ] `git check-ignore backend/tests/fixtures/clips/motion.mp4` returns a matching rule
- [ ] Every commit body explains *why*, per `CODE_STYLE.md` §7

---

## Self-review against the spec

Run after the phase file is written, before handing it over (writing-plans skill checklist).

**1. Spec coverage — can every Phase 0 row point at a task?**

| Spec requirement | Task |
|---|---|
| §2 stack, version floors, no fabricated pins | 0.1 |
| §2.1 environment baseline (venv, missing packages) | 0.1 |
| §3.3 CI licence scan fails on AGPL; weights gitignored; notice file | 0.7 |
| §8.2 Fernet + DPAPI master key | 0.4 |
| §8.3 redaction as a processor, `test_no_secret_in_log_output` | 0.2 |
| §5 domain error hierarchy catchable at two granularities | 0.3 |
| §11.1 hardware-free rule, RTSP marked, skip-never-pass | 0.5, 0.6 |
| §11.2 five named fixtures, generated not committed | 0.5 |
| §12 `test_errors.py`, `test_crypto.py`, `test_logging.py`, CI licence step | 0.3, 0.4, 0.2, 0.7 |
| Phase 0 gate: suite green, ruff+mypy clean, MediaMTX reachable, clip decodes | checklist |

**Gap found and closed:** `spec.md` §12 assigns `test_make_fixtures.py` and the RTSP harness to the phase gate but does not list them as numbered NFR rows. They are recorded in this file's *phase-local* verification rows so they are not lost.

**2. Placeholder scan** — no `TBD`, `TODO`, `implement later`, `add validation`, or `similar to Task N` appears. Every code step carries a code block.

**3. Type consistency across tasks**

| Symbol | Defined | Consumed |
|---|---|---|
| `StorageError` | 0.3 (`errors.py`) | 0.4 (`CryptoError(StorageError)`) |
| `ensure_clip(name: str) -> Path`, `CLIP_NAMES` | 0.5 | 0.6 (publisher source) |
| `tests/__init__.py` on `sys.path` | 0.1 | 0.5, 0.6, 0.7, 0.9 (`from tests.…`, `from scripts.…`) |
| markers `rtsp`, `slow` registered | 0.1 | 0.6, gate checklist |
| `requirements-dev.txt` | 0.1 (`pre-commit` already present) | 0.7 (appends `pyyaml`) |
| `.gitignore` fixtures rule | 0.1 | 0.5 Step 5 verification, 0.6 Step 7 |
| `frontend` npm scripts `lint`, `format:check` | 0.8 | 0.9 pre-commit hooks |

**4. Corrections made during review**

- The RTSP gate test is `test_harness.py`, not `test_rtsp_source.py` — `RtspSource` is a Phase 1 deliverable (Task 1.4). Phase 0 proves the harness with raw PyAV.
- Task ordering: the frontend scaffold moved to **0.8** and pre-commit to **0.9**, because the eslint and prettier hooks cannot run before the files they check exist.
- `pyyaml` is not in `requirements-dev.txt`; Task 0.7 appends it rather than assuming it.

---
