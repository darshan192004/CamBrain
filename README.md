<div align="center">

# CamBrain

**Offline edge AI for the CCTV you already own.**

Detect people and vehicles, define per-camera rules, and get alerts on Telegram —
without touching your existing NVR or its recordings.

</div>

---

## Status

> **Specification complete. Implementation not started.**
>
> This repository currently contains **documentation only**. There is no runnable
> build yet — no `backend/` source, no `frontend/` app, no installer. The empty
> directories are reserved targets, not partial work.
>
> See [`docs/tasks.md`](docs/tasks.md) for the build sequence and
> [`docs/superpowers/specs/spec.md`](docs/superpowers/specs/spec.md) for the full
> technical specification.

| Phase | Deliverable | State |
|---|---|---|
| 0 | Bootstrap, safety rails, test harness | Not started |
| 1 | Streaming engine | Not started |
| 2 | Database + REST API | Not started |
| 3 | Inference + ROI + rules | Not started |
| 4 | Dashboard + ROI editor | Not started |
| 5 | Alerting + event log | Not started |
| 6 | Packaging + operations | Not started |

---

## What CamBrain is

An edge AI sidecar for existing CCTV installations.

CamBrain runs **alongside** the NVR or VMS software you already use. It opens its
own RTSP connections to cameras you already own, detects objects, applies
per-camera rules, saves short event clips, and sends alerts to Telegram.

**Two invariants govern every design decision:**

1. **Your existing recording is never touched.** CamBrain is a second,
   independent reader of the same RTSP endpoints — never a proxy, never a tap.
   If CamBrain stops, your NVR is unaffected. If your NVR stops, CamBrain keeps
   working.
2. **No cloud, no telemetry, no phone-home.** One egress path — the notifier —
   carrying only what you explicitly configured. CamBrain works fully offline;
   only alert delivery fails.

### Who it is for

| Persona | Need |
|---|---|
| **Retail owner** | Know if someone walks in after hours |
| **Factory manager** | Alert on a person at the loading dock at 02:00 |
| **Installer** | Hand over a box without a 40-page manual |

The installer is the real channel in year one. Every "customer cannot configure
this" defect is an on-site visit.

---

## MVP scope

**In:** RTSP camera management with connection testing · concurrent ingest (target
8 cameras) · 2–5 FPS sampling · motion pre-filter · object detection across all
80 COCO classes · polygon ROI per camera · per-camera rules (class allow-list,
confidence, ROI, active hours, cooldown) · event clips with stills (10s pre-roll,
20s post-roll) · Telegram alerting · web dashboard · local accounts with
admin/viewer roles · Windows tray app with autostart.

**Out:** continuous recording · cloud sync · central fleet console ·
PPE/helmet detection · facial recognition · mobile app · WebRTC · ONVIF
discovery · Linux appliance.

### The acceptance criterion

> A first-time user adds a camera, draws one ROI, sets one rule, and receives a
> real Telegram alert for an intruding person **without contacting support.**

Every phase exists to make this sentence more achievable.

---

## How it works

```
  Cameras ──RTSP──┬──► Existing NVR (keeps recording, untouched)
                  └──► CamBrain ──► rules ──► clips ──► Telegram
                        FastAPI + SQLite + Vue 3 dashboard
                              │
                              └──► 127.0.0.1:8765 (dashboard)
```

One Python process. One thread per camera. A single shared inference session per
model tier. Frames flow through latest-frame slots that **drop stale frames
rather than queue them**, so a slow detector costs freshness rather than RAM.

Detection and alerting are separate concerns: the detector reports all 80 COCO
classes, and the rules engine decides what deserves an interruption. One box
therefore serves both a shop owner (alert on `person`, 22:00–06:00) and a factory
(`person` + `truck` at the loading dock, all hours) with no model change.

Full detail: [`docs/architecture.md`](docs/architecture.md).

---

## Hardware

Target floor is an **Intel N100** — 4 cores, 6W, AVX2 + VNNI — with 8GB RAM and
a 128GB SSD. Hardware tiers are detected at startup, never configured by hand.

| Tier | Trigger | Model (provisional) | Input |
|---|---|---|---|
| `high` | ≥ 8 cores, AVX2 + VNNI | YOLOX-m | 640×640 |
| `medium` | ≥ 4 cores, AVX2 | YOLOX-s | 640×640 |
| `low` | 4 cores, no VNNI | YOLOX-nano | 416×416 |

> **The model choice is provisional.** YOLOX-s is the working default pending a
> benchmark on real footage and real hardware. RT-DETR remains swappable behind
> a single module boundary — see [`docs/memory.md`](docs/memory.md).

Cameras are read at their **sub-stream** (typically 640×360) while your NVR keeps
the full-resolution main stream. CamBrain downscales further before inference, so
it never competes with your recorder for bandwidth or disk.

---

## Licensing — a hard constraint

CamBrain is intended for closed-source commercial sale. **No AGPL dependency may
reach the shipped application.**

The specific trap: `ultralytics` (YOLOv5/v8/v11/v26) is AGPL-3.0, and exporting
its weights to ONNX **does not change the licence**. Shipping an ONNX file derived
from AGPL weights into a commercial product does not escape copyleft — it is the
most common way copyleft gets violated unknowingly.

Permitted detector families are Apache-2.0: **YOLOX** (default), RT-DETR,
DAMO-YOLO, NanoDet. CI fails the build on any AGPL identifier, including dev
branches. Model weights are gitignored, fetched with SHA-256 verification, and
recorded in `models/LICENSE-MODEL-NOTICE` — Apache-2.0 attribution is a legal
obligation, not a nicety.

Full detail: [`docs/rules.md`](docs/rules.md) §1.

---

## Privacy posture

| Stored | Never stored | Never transmitted |
|---|---|---|
| Event stills, short clips, detection metadata (class, confidence, box, track id, timestamp, camera, zone, rule) | Continuous footage · audio · faces · biometric templates · identity · licence-plate text as text | Any video except the specific clip you configured for your own Telegram |

Facial recognition and biometric identifiers are **deliberately absent** — they
create a category of regulatory exposure a security product does not need.

---

## Documentation

| Document | Contents |
|---|---|
| [`spec.md`](docs/superpowers/specs/spec.md) | **Full technical specification** — scope, environment baseline, component contracts, build sequence, test spec, verification matrix |
| [`prd.md`](docs/prd.md) | Product requirements, personas, non-functional requirements |
| [`architecture.md`](docs/architecture.md) | System design, concurrency model, backpressure, tiering |
| [`DATABASE.md`](docs/DATABASE.md) | SQLite schema, indexes, retention, quota |
| [`API.md`](docs/API.md) | REST and WebSocket surface, auth, error codes |
| [`SECURITY.md`](docs/SECURITY.md) | Threat model, encryption, sessions, CSRF, release checklist |
| [`design.md`](docs/design.md) | Dashboard and ROI editor direction |
| [`tasks.md`](docs/tasks.md) | Phase checklist and gates |
| [`memory.md`](docs/memory.md) | Decision history and rationale |
| [`CODE_STYLE.md`](docs/CODE_STYLE.md) | Python, Vue, Rust, SQL, and Git conventions |
| [`rules.md`](docs/rules.md) | Engineering laws |
| [Implementation plan](docs/superpowers/plans/2026-10-05-cambrain-mvp-plan.md) | Index: global constraints, file structure, verification matrix, dependency order |
| [Phase 0 — Bootstrap](docs/superpowers/plans/phase-0-bootstrap.md) | First phase plan: environment, fixtures, RTSP harness, licence guard |

---

## Development setup

**Not yet runnable.** Prerequisites and exact commands are specified in
[`spec.md`](docs/superpowers/specs/spec.md) §2.1 and Phase 0 of the
[implementation plan](docs/superpowers/plans/2026-10-05-cambrain-mvp-plan.md).

Current baseline on the development machine:

| Component | State |
|---|---|
| Python 3.13.13 · Node 24.19.0 · npm 11.17.0 | Ready |
| `av`, `onnxruntime`, `sqlalchemy`, `alembic`, `cv2`, `cryptography` | **Absent** |
| Docker Desktop | Installed, **daemon stopped** |
| Cargo / Rust | **Absent** |

Intended stack: Python 3.13 · FastAPI · PyAV · ONNX Runtime · SQLAlchemy 2.0 ·
Alembic · SQLite (WAL) · Vue 3 (JavaScript) · Vite · Tailwind · shadcn-vue ·
Tauri v2 · pytest · MediaMTX.

---

## Testing approach

**No test may require a camera.** No cameras are available, and that dependency
must not be allowed to form. Every test runs from a generated synthetic clip, a
mock detector, or **MediaMTX in Docker** streaming a local file over real RTSP —
because a mock would never exercise the transport code most likely to be wrong.

```bash
pytest -m "not rtsp and not slow"   # default local, no Docker required
pytest                               # full suite, Docker required
```

Two canary tests cover whole bug classes rather than single functions:

- **Memory flatness across 50 reconnects** — asserts a flat *trend*, not a low
  absolute value, because a ceiling test passes on a slow leak. Turns "customers
  find it broken after a week" into a CI failure.
- **No secret in log output** — verifies a structural property: redaction happens
  in the structlog processor chain, so there is no code path that bypasses it.

Full detail: [`spec.md`](docs/superpowers/specs/spec.md) §11.

---

## Known risks

| Risk | Residual | Why |
|---|---|---|
| No cameras available for testing | **High** | MediaMTX is conformant RTSP, but vendor quirks, auth methods, and sub-stream paths remain unvalidated |
| N100 throughput unmeasured | **High** | Cameras-per-box and unit economics are unknown without hardware |
| Night / IR accuracy | **High** | A synthetic low-light fixture is not IR footage; this is the worst failure mode — a missed intrusion |
| False positives | Medium | Engine is fully tested, but thresholds need field data |
| Model choice unvalidated | Medium | YOLOX-s is provisional; the swap is one module |
| Power-loss event loss | Accepted | Clips survive; orphan sweep reclaims. Revisit if a customer reports lost evidence |

The two High risks share one root cause: **no hardware**. They are not mitigable
by better engineering — they resolve when someone points a camera at the box.

---

## Licence

Source code licence is **not yet decided.** The dependency licence position is
decided and CI-enforced (no AGPL); the project's own licence is an open
decision that should be settled before Phase 6 packaging.

---

<div align="center">

**CamBrain** — offline edge AI for the CCTV you already own.

*Specification complete · implementation not started · no hardware validated yet*

</div>
