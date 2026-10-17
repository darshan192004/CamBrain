# CamBrain Deployment & Operations

> Living document: sections grow with each phase task (installer T5, soak
> runbook T6, full handover for Arun in T7). Current sections cover the boot
> sequence, recovery semantics, and troubleshooting entry points proven in
> the phase-6 ledger.

## Architecture in one paragraph

A Tauri shell (`cambrian-shell.exe`) owns a supervised Python engine
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
