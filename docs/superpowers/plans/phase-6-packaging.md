# Phase 6 — Packaging & Operations

**Goal:** Features 0–5 are proven. Phase 6 makes the box an appliance: installs,
survives reboot, survives a 24-hour soak. Spec §10.3 phrase: *"Installs ·
survives reboot · survives 24h soak"* — the 24h soak is the only duration that
matters to a customer who leaves it running unattended.

**Stack added this phase:** Tauri v2 shell (Rust), NSIS bundling via Tauri's
NSIS installer target, Windows scheduled-task/autostart, `psutil`-based soak.

**Branch:** `phase-6-packaging` · Conventional Commits · no `Co-Authored-By`.

---

## Global Constraints

These apply to every task in every phase file; the MVP plan's copy is
authoritative on any divergence.

**Licensing — hard constraint, CI-enforced:**
- No AGPL dependency in any form. `ultralytics` (YOLOv5, v8, v11, v26) is **prohibited**, including ONNX exports.
- Detector models must be Apache-2.0 or equivalent. Permitted family: **YOLOX** (default), **RT-DETR**, DAMO-YOLO, NanoDet.
- `models/*.onnx` is gitignored. Weights are fetched by script with SHA-256 verification.
- `models/LICENSE-MODEL-NOTICE` records provenance + licence for every shipped weight file. Apache-2.0 requires attribution — legal obligation.
- CI runs a licence scan and **fails the build on any AGPL identifier**.

**Language and stack:**
- Frontend is **JavaScript, not TypeScript**. JSDoc typedefs on every exported function and API boundary. ESLint enforces `jsdoc/require-jsdoc`.
- Frontend framework is **Vue 3**, never React.
- Python line length 100. Target Python 3.13.
- Type hints on every function signature. No `Any` outside tests and protocol boundaries.
- Google-style docstrings on every public function.

**Concurrency:**
- Single process. One thread per camera. **Not** process-per-camera.
- PyAV decode and ONNX Runtime `run()` both release the GIL.
- One `InferenceSession` per model tier, shared across cameras.
- `CameraPipeline` holds no shared mutable state; collaborators are constructor-injected; outward communication via injected sink. **This seam must not be eroded.**

**Backpressure:**
- Between source and every consumer sits a latest-frame slot (`asyncio.Queue(maxsize=1)`).
- **Full queue means replace the oldest frame.** Never block, never accumulate.
- Drop frames **before** resize, not after decode.

**Tenancy:**
- Every domain table carries `site_id`.
- `site_id` is taken from the **auth token**, never from a request body or query parameter.
- Cross-tenant access returns **404, never 403**.
- Every FK has an explicit `ON DELETE` behaviour.

**Secrets:**
- Fernet-encrypted at rest. Master key DPAPI-wrapped (Windows), 0600 file on non-Windows dev with a loud warning.
- `rtsp_url` in the database stores **no credentials** — username and password are separate columns.
- `REDACT_KEYS` redaction happens in the structlog processor chain.
- RTSP URLs are masked (`rtsp://***:***@host:port/path`) everywhere.
- Secrets are **never** returned by any `GET`.

**Conventions:**
- Components always `<script setup>`, order script → template → style, always `scoped`.
- Hardcoded hex colours in components: never. Design tokens as CSS variables only.
- A `watch` that only sets other state is forbidden — use `computed`.
- SQLAlchemy 2.0 `select()` style. No string-built SQL.
- Alembic only for migrations. Never edit a shipped migration.
- Conventional Commits. Scope is the module.
- Never commit: model weights, `.env`, `cambrain.db`, clips, `node_modules/`, build output, credentials.

---

## Starting state (verified 2026-10-17)

Already in place from earlier phases — Phase 6 builds on, does not rebuild:

- `backend/app/services/inference/tiers.py` — `probe_capabilities()` /
  `resolve_tier()` / `tier_for()`: high→`yolox_m.onnx@640`, medium→`yolox_s.onnx@640`,
  low→`yolox_nano.onnx@416`; the System page already surfaces
  "Hardware tier · Model · Storage used" via `/system/status` (T6 verification only).
- `models/manifest.json` + `backend/scripts/fetch_models.py` — digest-pinned
  assets (YOLOX nano/s/m, gate fixture), `--verify` offline mode, atomic
  download scratch gitignored. The *fetch-and-verify* half of T1 is done; T1
  wires it into first-run bootstrap.
- `frontend/src-tauri/` exists but is **empty** — T2 scaffolds for real.
- Rust toolchain present: cargo/rustc 1.99.0.
- Engine entrypoint: `uvicorn app.main:app` from `backend/`; runtime is gated
  by `CAMBRAIN_RUNTIME_ENABLED`; DB + media root resolve from env (`CAMBRAIN_DB_PATH`,
  `CAMBRAIN_MEDIA_ROOT`) — the packaged app must set them under `%PROGRAMDATA%`
  / `LOCALAPPDATA`, not the repo layout.
- Billing/tray design source: `docs/design.md` §tray ("Open dashboard, Pause
  detection, Restart service, Quit"), `docs/architecture.md` §shell.

---

## Decisions

Locked before implementation; revision requires a note in the Execution ledger.

- **D6-1 — Process model.** The Tauri shell spawns the Python engine as a
  **supervised child process** (`uvicorn app.main:app` via an embedded
  interpreter), proxying `localhost:8765`. A crash in the engine is the shell's
  problem: the shell restarts the child with the same exponential backoff the
  reconnect path uses (1s → 2s → … capped 60s), logged to a rotating file.
  Rationale: one supervisor, no second watchdog to maintain; matches
  architecture.md §shell ("Python engine" as the shell's manageable cargo).
- **D6-2 — "Without user login" = autostart on user session, not a Windows
  service (MVP).** The installer enables autostart (Run-key) and the setup guide
  optionally enables Windows auto-logon for the kiosk user. A true
  `sc.exe`-managed service is documented as the alternative in the handover
  guide but is not shipped — a service account changes the profile that owns
  `%LOCALAPPDATA%`, DPAPI keys, and the tray, which is a Phase-7-class risk.
- **D6-3 — App data layout.** All writes (%PROGRAMDATA%-equivalent):
  `CAMBRAIN_APPDATA = %LOCALAPPDATA%\CamBrain` (existing dev default). DB at
  `<appdata>\cambrain.db`, media root at `<appdata>\media`, master.key at
  `<appdata>\master.key` (already the dev layout — zero migration).
- **D6-4 — Model first-run.** On lifespan start, before detectors open, the
  engine ensures the **resolved tier's** asset exists and matches its pinned
  SHA-256 (reusing `fetch_models.py` logic; no network when `--verify` passes).
  Missing + unreachable network → engine logs loudly and **starts with runtime
  disabled** rather than crashing the API (the dashboard and settings stay up;
  the System page shows the reason). Checksum mismatch → re-download once →
  still wrong → fail the same degraded-but-up way.
- **D6-5 — Tauri window.** One window, 1280×800, loads the built dashboard
  (`dist/`) in production and vite devUrl in dev. No menu bar; window closes
  to tray (never quits the engine). "Quit" lives only in the tray menu.
- **D6-6 — Tray menu spec (design.md §tray is normative).** Right-click:
  **Open dashboard**, **Pause detection** (`POST /system/runtimes`-style toggle
  → implemented as `CAMBRAIN_RUNTIME` pause via `/system/pause` — see T4),
  **Restart service** (engine child restart, not a machine reboot),
  ** Quit**. Pause needs a small backend endpoint (T4, admin-gated, audited).
- **D6-7 — Single instance.** Two shells never run at once
  (tauri-plugin-single-instance or lock-file fallback with pid evidence).
- **D6-8 — Installer.** Tauri NSIS bundler, per-user install under
  `%LOCALAPPDATA%\Programs\CamBrain` (no UAC elevation needed to install or
  update). Silent install = documented `installer.exe /S` for Arun. The
  handover guide (T7) is the integration artifact, not the installer itself.
- **D6-9 — Soak gate.** `test_soak.py::test_24h_soak` is `@pytest.mark.slow`,
  runs only when `CAMBRAIN_SOAK_HOURS` is set (default in CI-deselected runs;
  24h on the gate box). It asserts: RSS drift < 10% after warmup, per-camera
  FPS within ±20% of its window median, handle count growth < 5/h, zero
  unexpected engine restarts, events delivered on schedule throughout.
- **D6-10 — Rust side is small and dumb.** No Rust business logic: spawn,
  supervise, clipboard-clean tray menu, proxy path via localhost. Everything
  server-side stays Python-tested; everything Rust is covered by
  `cargo`-layout conventions + the T2/T3 manual gate checklist.

---

## File structure (phase-6 slice only)

```
backend/
  app/
    core/
      bootstrap.py            # T1: first-run model ensure + data-dir hygiene
    api/routers/
      system.py               # T4 adds POST /system/pause (admin, audited)
  tests/
    test_bootstrap.py         # T1: fetch/verify/degrade, no-network path
    test_system_pause.py      # T4: pause gate (admin 403/404 rules per tenancy)
    test_soak.py              # T1 of this phase: D6-9 assertions, marked slow
    fixtures/clips/soak.mp4   # reuse gate.mp4 — no new asset
  pyproject.toml              # (test marker already registered)
frontend/
  src-tauri/
    Cargo.toml                # T2
    tauri.conf.json           # T2 + T5 bundler config (NSIS product, paths)
    build.rs
    icons/                    # generated icon set (tray + window + installer)
    src/
      main.rs                 # T2: window + engine child spawn/supervise (D6-1)
      tray.rs                 # T4: tray menu wiring (D6-6)
      engine.rs               # T2/T6: child spawn, backoff-restart, log tail
      pause.rs                # T4: pause toggle calls backend endpoint with stored creds
docs/
  DEPLOYMENT.md               # T7: the Arun handover guide (install, service, diagnostics)
  tasks.md                    # tick Phase 6 row-by-row
  superpowers/plans/phase-6-packaging.md
```

---

## Tasks

### Task 1: First-run bootstrap (model ensure + data-dir hygiene)

**Files:** `backend/app/core/bootstrap.py`, `backend/tests/test_bootstrap.py`,
`backend/app/main.py` (lifespan call), `backend/app/core/config.py`
(`ensure_models` knob `CAMBRAIN_FETCH_MODELS`, default on).

- [ ] **Step 1 (TDD).** `test_ensure_model_downloads_and_verifies`: tmp data-dir
  without an `.onnx` → `ensure_models()` fetches the **resolved tier's** asset
  via manifest URL, verifies SHA-256, writes a `LICENSE-MODEL-NOTICE` provenance
  line — network mocked at the requests layer (no fixture weights in-repo).
- [ ] **Step 2 (TDD).** `test_checksum_mismatch_redownloads_once_then_degrades`:
  corrupt the file with wrong hash → one re-download, then engine degrades (runtime
  off, API up) with a reason string.
- [ ] **Step 3 (TDD).** `test_no_network_starts_api_with_runtime_disabled`:
  reason surfaces in `/system/status` (`runtime_reason`) — System page already
  renders `status`; add the field.
- [ ] **Step 4.** Wire `ensure_models()` into lifespan *before* pipelines open
  (colubrid: failure returns a reason, never raises past the lifespan).
- [ ] **Step 5.** Loops green; `feat(core): first-run model bootstrap with checksum`.

**Acceptance:** engine with an empty models dir + no network still serves
`/system/health`; with network it self-heals to a working detector.

### Task 2: Tauri scaffold — shell + supervised engine child

**Files:** `frontend/src-tauri/{Cargo.toml,tauri.conf.json,build.rs,src/main.rs,src/engine.rs}`,
tray icon set, `frontend/package.json` (`tauri` dev script).

- [ ] **Step 1.** Scaffold Tauri v2 (`npm create tauri-app` equivalent, adapted
  to the existing Vue app); `tauri.conf.json`:
  buildDir `../dist`, devUrl `http://localhost:5173`, no menu bar (D6-5).
- [ ] **Step 2.** `engine.rs`: spawn `python -m uvicorn app.main:app` from the
  package layout (dev: repo venv; packaged: `%LOCALAPPDATA%\Programs\CamBrain\engine\`
  — see T5), env `CAMBRAIN_*` set per D6-3, stdout/stderr → rotating file
  (`\logs\engine.log`), exponential backoff restart (1–60 s, jittered).
- [ ] **Step 3 (evidence).** Manual checklist in the plan ledger: kill `python.exe`
  while the shell runs → shell logs the restart → API health returns; ledger
  keeps the log excerpt path.
- [ ] **Step 4.** Loops green; `feat(shell): tauri v2 shell with supervised engine child`.

**Acceptance:** starting the shell produces a window showing the dashboard with
the engine's data (cameras render), and killing the engine self-heals within the
backoff budget.

### Task 3: Tray, single instance, autostart

**Files:** `src/tray.rs`, `src/main.rs` (single-instance plugin / lock file),
`tauri.conf.json` (autostart plugin config / installer Run-key step),
`backend/app/api/routers/system.py` (pause), `backend/app/api/schemas.py`,
`backend/tests/test_system_pause.py`, `docs/API.md` (endpoint documented).

- [ ] **Step 1 (TDD, Python).** `POST /system/pause` — admin-only, audited, idempotent
  (`{"paused": true|false}`); pause stops all runtime pipelines (sources closed,
  ring disposed) and unpause re-opens them; repeated pause/unpause never leaks a
  loop. Uses the runtime registry — no new supervision logic.
- [ ] **Step 2 (TDD, tenancy).** viewer → 403-shaped (projection: **404** per
  tenancy rule if endpoints are site-scoped); cross-site claims → 404.
- [ ] **Step 3.** Tray menu (D6-6): four items, Pause detection flips the
  endpoint with stored admin creds (fallback: stop child for pause if creds
  absent — documented degraded behaviour), state badge on the tray label.
- [ ] **Step 4.** Single instance (D6-7): second launch focuses the existing
  window.
- [ ] **Step 5.** Autostart (D6-2): Run-key set by installer postinstall;
  verify after a full log-out/log-in cycle (gate evidence in the ledger).
- [ ] **Step 6.** Loops green; `feat(shell): tray, pause, single instance, autostart`.

**Acceptance:** reboot → tray reappears and engine child is up without login
session change; Pause stops alert flow (no new events for its duration).

### Task 4: Recovery after power loss

**Files:** `backend/tests/test_recovery.py` (kills the uvicorn process mid-write,
restarts engine process-client in-process and asserts invariants), handover
checklist in `docs/DEPLOYMENT.md`.

- [ ] **Step 1 (TDD).** WAL survival: populate DB, hard-kill the server
  process (simulate power cut) mid-sweep, restart engine → sqlite integrity
  check passes, no partially-written event rows (WAL atomicity).
- [ ] **Step 2 (TDD).** Ring/clip state: a clip being written during the kill
  leaves at most one orphan file; `sweep_orphans` claims it later (already
  shipped in retention — assert).
- [ ] **Step 3 (TDD).** Delivery queue survives: pending events retry after
  restart (D4 contract — assert attempts/last_attempt_at preserved).
- [ ] **Step 4.** Document the boot sequence + what the API shows during
  recovery in `DEPLOYMENT.md`.
- [ ] **Step 5.** Loops green; `feat(ops): power-loss recovery invariants`.

**Acceptance:** WAL atomicity + orphan-sweep + delivery-pending assertions all pass;
a killed engine restarts and converges.

### Task 5: Windows installer (NSIS) + silent install

**Files:** `tauri.conf.json` (bundler NSIS config, per-user, icon, friendly
name), `docs/DEPLOYMENT.md` (silent flags), release name templating.

- [ ] **Step 1.** `npm run tauri build` → NSIS `CamBrain_<version>_x64-setup.exe`
  under `src-tauri/target/release/bundle/`.
- [ ] **Step 2.** Per-user install (D6-8) — Run-key postinstall step; app data
  D6-3 paths proven in a proxy test cycle.
- [ ] **Step 3.** Silent: `setup.exe /S` unattended evidence in the gate.
- [ ] **Step 4.** `chore(installer): nsis per-user bundling`.

**Acceptance:** installer runs, dashboard loads fresh, reboot keeps autostart.

### Task 6: Soak test + runbook

**Files:** `backend/tests/test_soak.py` (marked slow, scaled —
`CAMBRAIN_SOAK_HOURS`), `backend/tests/fixtures/` reuse of gate.mp4 loop,
`docs/DEPLOYMENT.md` soak runbook section.

- [ ] **Step 1 (TDD).** Invariants asserted by D6-9; scaled runs green.
- [ ] **Step 2.** Gate run: 24h with 1+ camera streaming, machine logged in,
  `CAMBRAIN_RUNTIME_ENABLED=1`; capture: RSS min/max/median at N-minute ticks,
  FPS ticks in the ledger, handle count, delivery count.
- [ ] **Step 3.** `test(ops): soak invariants with scaled env`.

**Acceptance:** skill §6 NFR rows measured, evidence in the ledger.

### Task 7: Handover guide for Arun

**Files:** `docs/DEPLOYMENT.md` — install (interactive + silent), autostart,
service semantics (D6-2 + true-service alternative), pause, logs, collection,
DB/media locations, model provenance + re-fetch, camera add troubleshooting
(checkout diagnosis matrix from design.md §5.1), soak runbook escalation path.

- [ ] **Step 1.** Write, review manually against the installed build.
- [ ] **Step 2.** `docs(ops): deployment + handover guide`.

**Acceptance:** a fresh operator can install → first camera → first Telegram alert
using only this document (fit the persona story list).

### Task 8: Docs, gate, PR — the phase gate

- [ ] **Step 1: Doc sync** — `tasks.md` Phase-6 rows ticked at the end.
- [ ] **Step 2: Loops green** — backend non-rtsp/non-slow suite; ruff; mypy;
  frontend suite; `npm run build`; `cargo` clippy -- no warnings (T2-T5).
- [ ] **Step 3: Gate run — the three-phase demonstration:**
  1. **Install + reboot** — install on a clean VM/box, reboot, verify tray +
     engine up without touching the keyboard (screenshot `gate-6-1.png`).
  2. **Alert flow through the shell** — person clip live as gate-5 did, but
     through the packaged shell: Telegram sendPhoto lands in the capture mock
     (`gate-6-2.png`).
  3. **24h soak** — D6-9 evidence, no restarts (ledger table + `gate-6-3`).
- [ ] **Step 4: PR + review + merge** — conventional body; PR-Agent `/review`;
  disposition; merge; delete branch; ledger filled.

---

## Plan of record — this file

The `docs/` contract from Phase 5 carries over: `docs/API.md` needs the pause
endpoint; `docs/DATABASE.md` gets audit rows for pause if any; `DEPLOYMENT.md`
is new and load-bearing.

---

## Execution ledger

| Task | Status | Date | Evidence | Notes |
|---|---|---|---|---|
| 1 First-run bootstrap | pending | | | |
| 2 Tauri scaffold + child | pending | | | |
| 3 Tray/pause/instance/autostart | pending | | | |
| 4 Power-loss recovery | pending | | | |
| 5 NSIS installer | pending | | | |
| 6 Soak + runbook | pending | | | |
| 7 Handover guide | pending | | | |
| 8 Docs + gate + PR | pending | | | |

## Gates

**Phase 6 gate — "installs · survives reboot · survives 24h soak":** a clean
box installs silently, reboots into the tray + engine unattended, serves an
alert through the shell (Telegram capture mock), and survives a 24-hour soak
with flat memory/fps + zero unexpected restarts.

| Row | Test |
|---|---|
| Model self-heal | `test_bootstrap.py` rows |
| Pause is admin-only + idempotent | `test_system_pause.py` |
| WAL/orphan/delivery recovery | `test_recovery.py` |
| Pause admin-only + idempotent, tenancy 404 | `test_system_pause.py` |
| Soak 24h | `test_soak.py::test_24h_soak` (marked slow) |
| Installs + reboots | gate screenshots |

## Definition of done

- [ ] Every task's acceptance checkboxes ticked in this file; ledger complete.
- [ ] Backend: `pytest -m "not rtsp and not slow"` green; ruff + mypy clean; `cargo` clippy clean; frontend suite green.
- [ ] `docs/DEPLOYMENT.md` current; `docs/API.md` documents `/system/pause`; `tasks.md` Phase 6 ticked.
- [ ] Gate evidence recorded (three screenshots + soak table); matrix rows pass.
- [ ] PR reviewed by PR-Agent `/review`, findings dispositioned, merged; branch deleted.
