# CamBrain Deployment & Operations

> Living document: sections grow with each phase task (installer T5, soak
> runbook T6, full handover for Arun in T7). Current sections cover the boot
> sequence, recovery semantics, and troubleshooting entry points proven in
> the phase-6 ledger.

## Architecture in one paragraph

A Tauri shell (installed as `CamBrain.exe`; dev builds are
`cambrian-shell.exe`) owns a supervised Python engine
(`uvicorn app.main:app`) as a child process. The shell renders the Vue
dashboard in a WebView2 window, keeps a tray icon with
Open dashboard / Pause detection / Restart service / Quit, and restarts the
engine child automatically with a jittered exponential backoff (1 s → 60 s,
reset after a stable 60 s run — D6-1). Both processes write logs to
`%LOCALAPPDATA%\CamBrain\logs\`; the engine's uvicorn stderr is mirrored
there as `engine.log`.

## Boot sequence

1. Shell starts, takes the single-instance mutex
   (`CamBrainShellSingleInstanceMutex`), writes its pid to
   `%LOCALAPPDATA%\CamBrain\shell.pid` (D6-7). A second launch raises the
   first instance's window and exits.
2. Shell spawns the engine child with resolved paths
   (`CAMBRAIN_DB_PATH`, `CAMBRAIN_MEDIA_ROOT` → `%LOCALAPPDATA%\CamBrain`),
   `CAMBRAIN_RUNTIME_ENABLED=1`, CREATE_NO_WINDOW, stderr → `engine.log`.
   Inherited `CAMBRAIN_*` variables (dev/test) always win over shell defaults.
   Two engine layouts share this contract: dev spawns the repo venv's
   `python -m uvicorn app.main:app`; the packaged app spawns
   `<install dir>\engine\cambrian-engine.exe` (PyInstaller **onedir** — the
   onefile variant was rejected after it filled users' `%TEMP%` with ~200 MB
   of extraction per boot and died "No space left on device"; the onedir
   layout ships plain files, boots in seconds, extracts nothing). The frozen
   entry runs `alembic upgrade head` on every start
   before serving — schema creation on first boot, no-op afterwards — and
   resolves the model path under app data (see D6-4 below).
3. Engine lifespan runs **model bootstrap** before pipelines open
   (`CAMBRAIN_FETCH_MODELS`, default on): ensures the resolved tier's ONNX
   weights exist and match their pinned SHA-256, re-downloading once on
   mismatch. Degraded bootstrap degrades runtime, never the API.
4. Engine serves `127.0.0.1:8765`; `/system/health` is the installer/parent
   liveness probe. The shell window loads the dashboard from the built
   assets; the engine binds to localhost only.
5. The shutdown path is: tray Quit → supervisor flag + `taskkill /T /F` on
   the engine; closing the *window* only hides to tray (D6-5).

## Recovery semantics (after engine death or power loss)

- **Engine process death** (`taskkill` mid-run, crash, power cut): the
  supervisor notices the child exit (`engine.log` line `engine exited:
  exit code ...`), waits `1 s × 2^n + jitter` seconds, and respawns. The
  window keeps its last render; the dashboard reconnects when `/system/health`
  answers again. Proven in the phase-6 ledger (+2.0 s recovery observed).
- **SQLite durability** (test: `backend/tests/test_recovery.py`): the DB runs
  in WAL mode with `synchronous=NORMAL`. A process killed mid-transaction
  leaves the committed prefix intact and invisibly rolls back uncommitted
  work. The first connection after the kill replays/rolls back the WAL —
  `PRAGMA integrity_check` stays `ok`. Operator action: none.
- **Media artifacts**: a clip encode killed mid-write strands at most one
  unreferenced partial file under `media\clips\`; the daily orphan sweep
  (`sweep_orphans`) removes it once older than the minimum age. Referenced
  media is never swept.
- **Alert delivery**: pending/failed rows survive the restart with their
  attempt counters and backoff intact (D4). No event is lost to a restart;
  delivery resumes automatically.
- **Operators do not read logs to decide this**: if `/system/health`
  responds, the engine recovered. `engine.log` carries the timeline
  (`engine started (pid ...)`, `engine exited: ...`) for postmortems.

## Install, update, and remove

The installer is the Tauri NSIS bundle (`CamBrain_<version>_x64-setup.exe`
under `src-tauri/target/release/bundle/nsis/`). It is **per-user**: no admin
rights, `%LOCALAPPDATA%` only.

| What | Where |
|---|---|
| Install dir (binaries) | `%LOCALAPPDATA%\Programs\CamBrain` |
| App data (D6-3) | `%LOCALAPPDATA%\CamBrain` (DB, media, keys, logs) |
| Bundled engine | `<install dir>\engine\` (PyInstaller onedir: `cambrian-engine.exe` + `_internal\`) |
| Autostart Run key | `HKCU\...\CurrentVersion\Run` → `CamBrain` |

- **Interactive install**: run the setup exe, per-user defaults, done. The
  postinstall hook writes the autostart Run key (D6-2) pointing at
  `<install dir>\CamBrain.exe`. First run downloads the model weights into
  `%LOCALAPPDATA%\CamBrain\models\` (D6-4); after that no network is needed.
- **Silent install** (Arun's handover path): `CamBrain_0.1.0_x64-setup.exe /S`
  — same locations, same Run key, no prompts. Verified on the gate box.
- **Update**: run the newer setup exe; it replaces the binaries and leaves
  `%LOCALAPPDATA%\CamBrain` data untouched (NSIS replaces only its payload).
- **Remove**: uninstall deletes the named payload (exe, WebView2Loader,
  bundled engine, uninstaller), unpins/cleans shortcuts, removes the Run
  key (the template does this itself for non-update uninstalls) and only
  then attempts `RMDir` on `<install dir>` — non-recursive, so any non-empty
  directory survives. `%LOCALAPPDATA%\CamBrain` is app data, never install
  payload: DB, media, and keys survive uninstall so a reinstall never loses
  footage (the uninstaller's optional "Delete app data" checkbox clears
  `$LOCALAPPDATA\{bundle-id}`, not this folder). Manual purge: delete that
  folder.

## Logs, DB, and media locations

| Item | Path |
|---|---|
| Logs (shell + engine) | `%LOCALAPPDATA%\CamBrain\logs\engine.log` |
| SQLite database (WAL) | `%LOCALAPPDATA%\CamBrain\cambrain.db` |
| Media (clips/stills) | `%LOCALAPPDATA%\CamBrain\media\` |
| Model weights + notice | `%LOCALAPPDATA%\CamBrain\models\` |
| Shell pid (single instance) | `%LOCALAPPDATA%\CamBrain\shell.pid` |

## Model provenance & re-fetch

Weights download once at first boot from the URL pinned in the model
manifest, are verified against a pinned SHA-256, and re-download once on a
checksum mismatch before degrading to a no-detector runtime with a machine-
readable reason on `/system/status` (`runtime_reason`). To force a re-fetch:
stop the engine (tray → Pause detection), delete the `.onnx` under
`models\`, resume detection; the shell relaunches and bootstrap fetches again.
`CAMBRAIN_FETCH_MODELS=0` disables the fetch entirely (offline installs,
tests).

## First run: install → first camera → first alert

The onboarding path a fresh operator follows (design §8). Everything below
happens in the dashboard; no terminal needed.

1. **Install** (previous section), launch CamBrain, log in as
   `admin / cambrain-demo` (seeded on first boot — change it in Settings).
2. **Add the camera** (Cameras → Add): paste the RTSP URL and credentials.
   The **test connection** button runs the real failure diagnostics — it
   tells you *which* of the three failed (see the table below) instead of
   saying "failed".
3. **Draw a zone** on the frozen snapshot the add-dialog captured (Zones
   panel on the right is always visible; polygons store normalised
   coordinates; Save commits — Cancel restores).
4. **Connect Telegram**: Settings → notifiers, add a *telegram* notifier
   (bot token + chat id); press its test action and confirm the message
   lands.
5. **Arm the rule**: add a rule for that camera with `classes=[person]`,
   `notify=true`. No rule ⇒ no events ⇒ no deliveries — the alert chain is
   rule-driven by design.
6. Walk into the frame. The event appears in the log with a clip; the Telegram
   bot receives the photo + clip inside the cooldown window.

### Camera add troubleshooting

The add-dialog test connection distinguishes the failure modes an installer
actually hits:

| Symptom | Cause | Fix |
|---|---|---|
| Connect timed out / unreachable | wrong IP, camera on another VLAN, RTSP port closed | ping the host; check `:554` (or the port in the URL); Windows Defender firewall rarely blocks outbound |
| 401 / authentication failed | wrong user or password (ONVIF credentials ≠ RTSP credentials on some cameras) | re-enter; try the RTSP-specific user |
| 404 / stream not found | wrong path (main vs sub stream, channel number) | copy the exact path from the camera's web UI; try `.../Streaming/Channels/101` (Hikvision pattern) |
| codec unsupported | H.265 or mjpeg stream | switch the camera's stream profile to **H.264** (MVP decoders) |
| works in test, black tiles later | camera dropped offline since add | see replay/offline state on the tile; check PoE/network |

### Soak runbook (24h gate)

`backend/tests/test_soak.py` is environment-gated: with `CAMBRAIN_SOAK_HOURS`
unset it skips (`CAMBRAIN_SOAK_HOURS is not set (slow, gate-only suite)`).
The gate run is a scheduled desktop task, not a live operator session:

```powershell
$env:PATH = "E:\CamBrain\.venv\Scripts;" + $env:PATH
$env:CAMBRAIN_SOAK_HOURS = "24"
$env:CAMBRAIN_RUNTIME_ENABLED = "1"
$env:TEMP = "D:\CamBrain-gate\temp"; $env:TMP = $env:TEMP
python -m pytest backend/tests/test_soak.py -q -m slow
```

- The harness starts its own bundled MediaMTX RTSP server on a private port
  (`backend\tests\rtsp\.tools\mediamtx.exe`) — **no real camera needed**, but
  the box must stay logged in (interactive session) for the full duration.
- What it proves and records: RSS/handle growth over the engine process tree,
  MJPEG-viewer FPS trend (half-median window ±20%), Telegram capture
  deliveries, zero unexpected engine restarts. Output is a single pytest run;
  the ledger row (row 6) gets the final numbers.
- **Escalation path**: if the soak fails, archive
  `%LOCALAPPDATA%\CamBrain\logs\engine.log` + the pytest output; the failure
  names the invariant (RSS ceiling, handle cap, FPS trend, restart, delivery).
  A restart row with `exit code: 3` points at bind conflicts on `:8765`
  (another engine instance running); `No space left on device` points at the
  system drive, not the engine (and cannot happen in packaged mode — onedir).

### Windows service (post-MVP alternative)

D6-2's Run-key autostart requires a logged-in session — that is the MVP
contract (tray + dashboard are the product). If an unattended/before-login
mode is ever required, the engine is already a well-behaved service candidate
(localhost-only uvicorn, supervised by the shell today); wrapping the shell
in a task-scheduler job at logon is the intermediate step, with a true
`windows-service` crate integration as the full upgrade — decision deferred
by D6-2, recorded here for Arun.

## Tray and pause semantics

- **Close** hides the window to tray; the shell keeps supervising the engine.
- **Pause detection** (tray) is a *degraded* pause per SECURITY §7.5: the
  supervisor holds the engine DOWN (respawn suppressed + child killed), so
  no detection runs and nothing is written. Resuming unchecks → the
  supervisor respawns the engine within ~1 s. Both directions are recorded
  in the audit log (`system.pause` / `system.resume`). Deliberate MVP
  trade-off: a paused capture must lose footage by design, not silently —
  the tray icon shows the paused state. An HTTP pause toggle that pauses
  *pipelines* while the API stays up is post-MVP.
- **Restart service** respawns the child only (1 s, backoff ladder untouched).
- **Quit** tears down shell + engine child.

## API contract notes for handover

- Every mutating request (POST / PATCH / DELETE) must carry the CSRF header
  `x-cambrain-client` plus `Content-Type: application/json`; login included.
  GETs need only the `Authorization: Bearer` token (except
  `GET /api/v1/system/health`, which is anonymous). History: the header
  originally shipped with a `cambbrain` double-"b" misspelling; it was
  renamed deliberately post-T8 in a backend+frontend contract fix (docs,
  tests, and CORS allow-header renamed together). Bundles built before that
  fix still expect the old spelling — an old installed app talks only to its
  own bundled engine, so there is no cross-version client mismatch. The
  constant lives in `backend/app/api/middleware.py` (`_CLIENT_HEADER`).
- Auth: seeded admin `admin / cambrain-demo` on fresh DBs (installer first
  boot). Argon2id hashes; sessions are bearer tokens.
- Notifier kinds are `telegram` and `whatsapp` only; capture/regression
  tooling stands in for the Telegram API via `CAMBRAIN_TELEGRAM_API_BASE`.
