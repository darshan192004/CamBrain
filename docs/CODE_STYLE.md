# CamBrain — Code Style Guide

> Living document. Formatting and naming conventions across Python, Vue, and Rust.
> Related: [rules.md](rules.md) · [architecture.md](architecture.md)

---

## 1. Principles

1. **The linter decides, not you.** If `ruff` and Prettier disagree with your preference, they win. Do not add formatting rules by hand.
2. **Explicit over implicit.** Type hints, named parameters, explicit lifetime control. The pipeline runs for months unattended; a reader should never have to infer ownership.
3. **Comments explain *why*.** The code already says *what*. A comment restating the code is noise; a comment recording a constraint is essential.
4. **Consistency across the stack.** Python, Vue, and Rust share naming and layering conventions so the codebase reads as one system.
5. **JavaScript, not TypeScript — with JSDoc.** See §5.

---

## 2. Tooling

| Tool | Purpose | Config |
|---|---|---|
| **Ruff** | Lint + format (Python) | `pyproject.toml` |
| **mypy** | Static types (Python) | `pyproject.toml` |
| **pytest** + pytest-asyncio | Tests | `pyproject.toml` |
| **ESLint** | Lint (JS/Vue) | `eslint.config.js` |
| **Prettier** | Format (JS/Vue/CSS) | `.prettierrc` |
| **rustfmt** + clippy | Rust/Tauri | `rustfmt.toml` |
| **pre-commit** | Run all of the above pre-commit | `.pre-commit-config.yaml` |

Ruff replaces flake8 + isort + black. Line length 100. Target Python 3.13.

---

## 3. Python

### 3.1 Layout

```python
# app/services/stream/stream_manager.py

"""Owns the lifecycle of every camera pipeline.

The manager creates pipelines, tracks their status, and guarantees that
stopping a camera releases every resource it holds. It deliberately contains
no inference or rules logic — see architecture.md §2.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.core.logging import get_logger
from app.services.stream.pipeline import CameraPipeline

if TYPE_CHECKING:
    from app.services.stream.source import FrameSource

logger = get_logger(__name__)
```

- **Module docstring always.** One or two lines on what the module owns and what it deliberately does not.
- `from __future__ import annotations` in every file.
- `if TYPE_CHECKING:` for import-only-typing dependencies — this avoids circular imports at runtime, which is endemic in pipeline code.

### 3.2 Imports

Grouped, one group per section, alphabetised within each. Ruff's isort does this; do not hand-order.

```python
from __future__ import annotations

# stdlib
import asyncio
from pathlib import Path

# third-party
import numpy as np
import onnxruntime as ort

# first-party
from app.core.config import settings
from app.services.stream.source import Frame
```

### 3.3 Naming

| Kind | Convention | Example |
|---|---|---|
| Module | `snake_case` | `stream_manager.py` |
| Class | `PascalCase` | `CameraPipeline`, `MotionGate` |
| Function / method | `snake_case` | `evaluate_rules()`, `close()` |
| Variable | `snake_case` | `frame_interval` |
| Constant | `UPPER_SNAKE` | `DEFAULT_BACKOFF_CAP_S` |
| Private | leading `_` | `_open_container()` |
| Type var | `PascalCase` optionally `_co` | `FrameT = TypeVar("FrameT")` |

**Interface classes get a `Protocol` suffix only when several implementations exist** — `FrameSource`, `Detector`, `Notifier`. Not decoration: it signals to a reader that a seam exists and more than one thing plugs into it.

### 3.4 Type hints

**Mandatory** on every function signature — parameters and return. No bare `dict`/`list`; parameterise them.

```python
# Good
def evaluate(
    track: TrackedObject,
    config: RuleConfig,
    now: datetime,
) -> RuleOutcome:

# Bad
def evaluate(track, config, now):
```

Optional only for trivial local closures. `Any` is banned outside test code and protocol boundaries — it means "I didn't think about this."

### 3.5 Docstrings

Google style. Every public function gets one.

```python
def compute_interval(sample_fps: float) -> float:
    """Return the minimum seconds between processed frames.

    Args:
        sample_fps: Target samples per second, clamped to (0, MAX_SAMPLE_FPS].

    Returns:
        Seconds between frames. At 5 FPS this is 0.2.
    """
```

Private helpers (`_`-prefixed) may omit docstrings; their signature should suffice.

### 3.6 Comments

```python
# Bad — restates the code
# Increment the retry counter
retry_count += 1

# Good — records a constraint that is not visible in the code
# Full jitter is essential: eight cameras behind a rebooting NVR would
# otherwise all retry in lockstep and hammer the camera that is still
# coming up. See rules.md §2.4.
delay = random.uniform(0, min(base * 2**attempts, cap))
```

### 3.7 Errors

- Never bare `except:`. Always `except SpecificError:`.
- Never `except Exception: pass`. Log at minimum.
- Re-raise with context: `raise StreamError(f"Failed to open {mask(url)}") from exc`.
- **Never leak secrets in an exception message.** `mask()` is applied to anything URL-shaped.
- Domain exceptions live in the module that raises them, and subclasses `CamBrainError`.

### 3.8 Async

- `async def` all the way down the pipeline. No `def` blocking the loop.
- Blocking work (ONNX `run()`, JPEG encode) goes to a bounded thread pool via `asyncio.to_thread` or an explicit pool — never inline.
- **Every** `await` in a resource-owning function needs a `finally` that closes the resource. See [rules.md §2.2](rules.md).
- `asyncio.CancelledError` is a normal exit path.

### 3.9 Comments on classes

Every service class gets a docstring stating what it owns and what it deliberately does not — that second half is what keeps the boundaries from eroding.

---

## 4. Vue

### 4.1 Components

- **`<script setup>`** always. Composition API, `<script setup>`.
- One component per file. Filename matches the component in PascalCase: `CameraTile.vue`.
- Component names are multi-word: `CameraTile`, not `Tile`. Required by Vue for future flexibility.

### 4.2 Structure

```vue
<script setup>
/**
 * A single camera tile in the live grid.
 *
 * Owns: rendering one MJPEG stream and its connection state.
 * Does not own: the stream itself (the backend does) or grid layout.
 */
import { computed, ref, onUnmounted } from 'vue'
import { useCamera } from '@/composables/useCamera'

const props = defineProps({
  /** @type {import('@/types/camera').Camera} */
  camera: { type: Object, required: true },
})

const status = computed(() => props.camera.status)
</script>

<template>
  <div class="tile" :data-status="status">
    <!-- video -->
  </div>
</template>

<style scoped>
.tile { aspect-ratio: 16 / 9; }
</style>
```

**Order: `<script setup>` → `<template>` → `<style scoped>`.** Always `scoped`.

### 4.3 Props and emits

- JSDoc `@type` on every prop, referencing a typedef from `@/types/`.
- Emits declared explicitly with `defineEmits`, never implicit `$emit`.
- `v-model` via `defineModel()` (Vue 3.4+).

### 4.4 Composables over mixins

`useCamera()`, `useAuth()`, `useEvents()`. All reusable state lives in a composable or a Pinia store — never duplicated in a component. Mixins are not used anywhere in this codebase.

### 4.5 State

| Kind | Goes in |
|---|---|
| Server state | Pinia store, fetched via the API |
| Shared UI state | Pinia store |
| Component-local state | `ref` / `reactive` in the component |
| Derived | `computed`, never a `watch` that assigns |

**No `watch` that only sets other state** — that is a `computed` written badly.

### 4.6 Naming

| Kind | Convention | Example |
|---|---|---|
| Component file | `PascalCase.vue` | `CameraTile.vue` |
| Composable | `useXxx.js` | `useCamera.js` |
| Store | `xxxStore.js` | `cameraStore.js` |
| Event handler | `handleXxx` | `handleTileClick` |
| Emit | Past tense | `@tile-click` |
| Prop | `camelCase` | `sampleFps` |
| CSS class | `kebab-case` | `camera-tile`, `is-offline` |
| Custom event modifier | kebab | `@key-up` |

### 4.7 Styling

Tailwind utilities. Custom CSS only for keyframes and ROI canvas internals.

- Design tokens via CSS variables — never hardcode a hex in a component.
- State via data attributes (`:data-status="status"`), styled with `[data-status='offline']`. Beats conditional class strings.
- No inline `style` for anything dynamic except genuine geometry (ROI coordinates, video dimensions).

### 4.8 JSDoc in place of TypeScript

Per the JavaScript decision, module boundaries and API payloads carry JSDoc typedefs:

```javascript
/**
 * @typedef {Object} Camera
 * @property {number} id
 * @property {string} name
 * @property {string} rtspUrl        Masked. Never contains credentials.
 * @property {'live'|'offline'|'error'|'starting'} status
 * @property {number|null} sampleFps
 */

/**
 * Fetch one page of events.
 * @param {Object} params
 * @param {number} [params.siteId]
 * @param {'critical'|'warning'|'info'} [params.severity]
 * @param {number} [params.limit=50]
 * @param {number} [params.offset=0]
 * @returns {Promise<{items: Event[], total: number}>}
 */
export async function fetchEvents({ siteId, severity, limit = 50, offset = 0 } = {}) {
  // ...
}
```

ESLint runs `jsdoc/require-jsdoc` on exported functions. The type-safety value is retained exactly where it matters — module boundaries and API payloads — without the compiler step.

---

## 5. Rust / Tauri

Tauri is a thin shell: tray, autostart, single-instance, proxy. Business logic stays in Python. Keep it that way; the boundary is what makes the engine portable.

- `#![deny(warnings)]` in `main.rs`.
- Every command handler returns `Result<T, String>` — never panics across the FFI boundary.
- `anyhow` for application errors, `thiserror` for library errors.
- Clippy pedantic, with the documented allowances listed in `clippy.toml` rather than scattered `#[allow]`s.

---

## 6. SQL

### 6.1 Queries

**SQLAlchemy 2.0 style.** No `Query` API, no string-built SQL.

```python
# Good
stmt = select(Camera).where(Camera.site_id == site_id, Camera.enabled.is_(True))
cameras = (await session.execute(stmt)).scalars().all()

# Bad — string interpolation is an injection vector
session.execute(f"SELECT * FROM cameras WHERE name = '{name}'")
```

### 6.2 Tenant scoping

**Every** query filters by `site_id`, and it comes from the auth token, never a request parameter. See [SECURITY.md §4.3](SECURITY.md). Repository base classes enforce this.

### 6.3 Migrations

- **Alembic only.** No manual `CREATE TABLE` outside a migration.
- Every schema change is a migration, reviewed before merge.
- Migrations are forward-only and must work on a populated database. Never edit a shipped migration; add a new one.
- Every migration gets a tested downgrade, or an explicit comment saying why it is irreversible.

---

## 7. Git

**Conventional Commits.**

```
feat(stream): add jittered exponential backoff to RTSP reconnect

Retry without jitter caused all eight cameras to reconnect in lockstep
after an NVR restart, hammering the camera still coming up. Full jitter
spreads the herd.

Refs: rules.md §2.4
```

| Type | Use |
|---|---|
| `feat` | New capability |
| `fix` | Bug fix — the body must state the *cause*, not just the symptom |
| `perf` | Performance |
| `refactor` | No behaviour change |
| `test` | Tests only |
| `docs` | Documentation only |
| `chore` | Build, deps, config |

Scope is the module (`stream`, `inference`, `rules`, `ui`).

### Branches

`main` · `feat/<slug>` · `fix/<slug>`.

### Commit discipline

- One logical change per commit. A refactor and a behaviour change are two commits.
- Never commit: model weights, `.env`, `cambrain.db`, clips, `node_modules/`, build output, or any real credential.
- `models/*.onnx` is gitignored — weights are fetched by a script with checksum verification.

---

## 8. Comments policy

**Comments are for constraints and rationale, not narration.**

Good: why the jitter is there, why INT8 is forced, why the ROI is in normalised coordinates, what breaks if this changes.

Bad: restating the next line, section banners, commented-out code (delete it — git remembers), "TODO" without an owner or an issue link.

Every non-obvious decision has a `Refs: docs/...md §N` comment. Future readers get the *why* without archaeology.

---

## 9. Pre-commit

Runs on every commit, blocks on failure:

```
ruff check          — lint
ruff format --check — formatting
mypy                — types
eslint --fix        — JS lint
prettier --check    — JS format
```

Full suite (`pytest`, `cargo clippy`) runs in CI, not pre-commit — a 60-second test suite is not worth taxing every commit.

---

## 10. Quick reference

| Rule | Value |
|---|---|
| Python line length | 100 |
| Python target | 3.13 |
| Import order | stdlib → third-party → first-party |
| Type hints | Every signature, no `Any` |
| Docstrings | Google style, all public functions |
| Quotes | Double |
| Bare `except` | Never |
| Component order | script → template → style |
| Vue style | Always `scoped` |
| Hardcoded hex in components | Never — tokens only |
| Watch that sets state | Never — use `computed` |
| SQL injection via f-string | Never |
| Migrations | Alembic, forward-only |
| Commits | Conventional Commits |
| Weights / DB / clips in git | Never |
| Animation in app UI | 120–400ms, no overshoot |