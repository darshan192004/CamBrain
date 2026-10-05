# CamBrain — Project Context & Decision Log

> Living document. Append new decisions as they're made; do not rewrite history.
> Related: [prd.md](prd.md) · [architecture.md](architecture.md) · [rules.md](rules.md)

---

## Product

CamBrain is an edge AI sidecar that adds intelligence to existing Hikvision / CP Plus / Dahua CCTV. It installs alongside the customer's NVR or VMS, reuses the same RTSP URLs, detects objects, applies per-camera rules, and sends alerts to Telegram. It never replaces the recording software and never sends video anywhere.

Target market: Indian MSME — retail shops and GIDC factories, primarily Rajkot, Gujarat. Monetisation is a software-hardware bundle or a per-camera monthly subscription.

---

## Decisions

### D1 — Licensing: Apache-2.0 models only. No Ultralytics, ever.

**Decided:** Phase 1. **Status:** locked.

The product is sold closed-source. Any AGPL dependency reachable from the shipped application obliges disclosure of the whole application's source. That is not a cost to optimise — it defeats the business model.

**Rejected: YOLOv5.** `ultralytics/yolov5` is AGPL-3.0 (LICENSE file, 661 lines of AGPL text, header on every source file). Ultralytics' own FAQ names YOLOv5 explicitly.

**Rejected: YOLOv8, YOLOv11, YOLOv26.** Same owner, same licence. Their terms state an Enterprise License is required for any commercial product, closed-source software, SaaS platform, or embedded/edge deployment — and that this applies "even if you train your own model from scratch, do not use pretrained weights, or export to ONNX."

**This was the single highest-risk item in the project.** The initial brief proposed "YOLOv8 exported to `.onnx` … to avoid AGPL-3.0." Exporting to ONNX changes the file format; it does not change the licence attached to the weights. Shipping an ONNX file derived from AGPL weights into a commercial product does not escape copyleft — it is the mechanism by which the licence is most often violated unknowingly. Notably, those same terms list "embedded deployments in hardware, edge devices, robotics, cameras, or appliances" as an Enterprise trigger, which describes this product exactly.

**Accepted: Apache-2.0 family.**
- **YOLOX** (Megvii) — Apache-2.0, verified in `Megvii-BaseDetection/YOLOX/LICENSE`. Seven size variants (nano/tiny/s/m/l/x/darknet), all sharing one I/O signature: input `[1,3,H,W]`, output `[1,8400,85]` = 8400 anchor positions across the P3/P4/P5 grids, 85 values each = `(cx,cy,w,h,obj_conf, 80 class probs)`. Because the signature is identical across variants, `nano → s → m` tiering costs zero code changes.
- **RT-DETR** — Apache-2.0, no NMS post-processing, stronger on small/distant objects, which is most of what matters on a shopfront camera.
- Also viable: DAMO-YOLO, NanoDet, YOLOF, PaddleDetection.

**Enforcement:** CI runs a dependency licence scan and fails on any AGPL identifier, including in dev and experimental branches. `models/LICENSE-MODEL-NOTICE` records the provenance and licence of every shipped weight file. Apache-2.0 requires attribution, so this file is a legal obligation, not a nicety.

**YOLOX implementation caveat, recorded because it fails silently:** YOLOX is anchor-free and differs from Ultralytics in two ways that break ported decode code. Inputs are **not** scaled to 0–1 (raw 0–255, letterboxed), and outputs need grid/stride decoding rather than the Ultralytics layout. Reference implementation: upstream `demo/ONNXRuntime`.

### D2 — Model selection deferred to a Phase 3 benchmark

**Decided:** Phase 1 planning. **Status:** open, scheduled for Phase 3.

Rather than assume, both YOLOX-s and RT-DETR-r18 get benchmarked on real footage before one becomes the default. The `Detector` protocol makes this a swappable decision rather than a rewrite. Test footage must include IR-lit night scenes, which is where accuracy actually breaks for this use case.

### D3 — Detector is generic; the rules engine decides what matters

**Decided:** Phase 1 planning. **Status:** locked.

All 80 COCO classes are detected on every tier. It is the same forward pass, so restricting the class set saves nothing at inference time. What costs money is *alerting* on all 80 — a parked scooter triggers a shop owner's phone at 3am.

So: the detector reports what it sees; a per-camera rules engine decides what deserves an interruption. This is also what lets one box serve a retail owner (alert on `person`, 10pm–6am) and a factory (`person` + `truck` at the loading dock, all hours) with no model change.

Any code that filters by class before the rules engine is wrong.

### D4 — Concurrency: single process, one thread per camera

**Decided:** Phase 1 planning. **Status:** locked, with an escape hatch.

**Chosen:** one Python process; FastAPI/uvicorn for the API; one thread per camera running the pipeline; ONNX sessions pooled per model tier.

**Why threads work here:** PyAV's decoder and ONNX Runtime's `run()` both release the GIL during actual compute. The usual objection to threads does not apply to precisely the two operations that dominate our cost.

**Rejected: process-per-camera.** ~200MB extra per camera for the ONNX session and allocator. Eight cameras on an 8GB box is an out-of-memory failure, which directly conflicts with the low-grade-hardware requirement.

**Rejected: shared inference pool with queued tasks.** Better utilisation on saturated hardware, but real complexity in scheduling, backpressure, and priority — significant for an MVP, and the benefit only appears when a box is actually saturated.

**Escape hatch:** `CameraPipeline` holds no shared mutable state, receives collaborators by constructor injection, and reports through an injected sink. Moving pipelines to child processes touches one factory function. This seam must not be eroded by convenience shortcuts.

### D5 — Windows x64 first, OS-agnostic engine

**Decided:** Phase 1 planning. **Status:** locked.

The "sidecar alongside existing NVR software, runs in the system tray, starts on boot" framing means Windows. It also means the customer needs no new hardware at all, which is a stronger sales story than a required mini-PC purchase.

Constraint accepted: ONNX Runtime wheels, PyAV wheels, and installer packaging must all hold up on Windows x64, and the Intel N100 tiering story becomes "Windows on a N100 mini-PC" rather than a Linux appliance. The engine contains no platform-specific code; only the tray shell is Windows-bound, so a Linux build is a packaging exercise rather than a port.

### D6 — Multi-site tenant-aware schema; edge box per site

**Decided:** Phase 1 planning. **Status:** locked.

Every table is keyed by `site_id` and auth/alerting are tenant-aware from day one, even though one box typically serves one site. Retrofitting tenancy later is one of the most painful migrations in a product like this.

Deployment is one box per site with no central console in MVP — that avoids needing a hosted server at all, which is consistent with the zero-cloud-cost principle. A central console is later; the API is designed so it can be added without changing the edge box.

### D7 — Event clips only. CamBrain is not an NVR.

**Decided:** Phase 1 planning. **Status:** locked.

The customer's NVR keeps doing full continuous recording. CamBrain saves only short clips (10s pre-roll, 20s post-roll) for events it alerts on, plus a still.

Rejected "full continuous recording": requires a video encoder, storage sizing, retention/loop logic, and a playback UI, and it competes with recording the customer already pays for. Rejected "clips + optional archive": the recording path would have to be designed and tested up front, for a feature nobody has asked for. Disk-light design also matters on a 128GB box.

### D8 — No Celery/Redis in V1

**Decided:** Phase 1 planning. **Status:** locked, reversible.

The only async work is "write a clip" and "POST to Telegram" — seconds of IO each. A broker plus worker costs ~150MB RAM on an 8GB box, adds a second installable/keepalive component on a customer's machine, and buys backpressure semantics already provided by bounded queues.

The brief offered "Celery with Redis … or lightweight `BackgroundTasks` for V1." `BackgroundTasks` wins.

If clip writing ever grows to minutes, the seam is `ClipWriter` and swapping in a Celery task is contained.

### D9 — Telegram first; WhatsApp behind the same interface

**Decided:** Phase 1 planning. **Status:** locked.

Telegram Bot API is free, instant, needs no business verification, and supports photo and video natively. WhatsApp requires Meta business verification plus approved message templates, and becomes per-conversation billing past the free tier — days of setup friction that would stall the MVP.

WhatsApp is what most Indian business owners actually use day to day, so it matters for the demo. It ships as a `Notifier` adapter in a later phase, behind the protocol defined in Phase 1.

### D10 — Auth: multi-user, two roles. Required, not optional

**Decided:** Phase 1 planning. **Status:** locked.

`admin` (configure cameras, draw ROIs, manage users) and `viewer` (live view and events only), with password login and hashed sessions. Covers owner + manager/guard without much extra work.

The box sits on a customer's LAN. That is a trust boundary, not a safe harbour — anyone on the shop Wi-Fi can reach the port. There is no "trusted LAN, skip auth" exemption. Single-owner was rejected because staff would end up sharing the owner's credentials, which is worse in a business with employees.

### D11 — Two UI surfaces with different toolkits

**Decided:** Phase 1 planning. **Status:** locked.

- **Marketing site** — GSAP + Lenis + AniMaster-style effects. GSAP became 100% free including formerly Club-only plugins (SplitText, MorphSVG) in April 2025 under a standard "no charge" licence that covers commercial use. Lenis is MIT. All appropriate for a marketing page.
- **App** — Vue 3 + Tauri, restrained UI, animations limited to 120–400ms transitions. Deliberately *not* the heavy animation libraries. Reasons: CPU contention with 8 inference pipelines on shared silicon; input-accuracy breakage for ROI drawing under transformed/scroll-snapped ancestors; motion sensitivity for a time-pressured precision task; and diluting red-on-screen signal in a security tool.

**Rejected: Skiper UI and Vengeance UI.** Both are shadcn/ui **React** registries. React was removed from the stack, which eliminates them by construction. Independently, both are documented as marketing-site/landing-page libraries.

**Flagged: AniMaster.** $3–$20 delivered via Google Drive and a private Telegram channel. That delivery model implies personal-use terms. Copying its components into software installed at a customer's site is redistribution. **Do not use AniMaster source in shipped product code.** Free to study for inspiration; not safe to ship.

### D12 — React → Vue 3, JavaScript not TypeScript

**Decided:** Phase 1 planning. **Status:** locked.

Vue 3 chosen for single-file components, ecosystem depth, official Tauri examples, and `shadcn-vue` giving MIT-licensed Radix-Vue primitives that are React-free.

JavaScript rather than TypeScript is a deliberate call to reduce build friction for a solo founder. Mitigation: JSDoc typedefs on every export and API boundary, strict ESLint with `jsdoc/require-jsdoc`, hand-rolled UI primitives we own outright. Revisit past ~40 source files or on the second developer.

### D13 — Hardware floor: Intel N100, with graceful degradation

**Decided:** Phase 1 planning. **Status:** locked.

Requirement was explicit: it must run on low-grade hardware. N100 (Alder Lake-N, 4-core, 6W) has AVX2 + VNNI, so INT8 ONNX is genuinely fast, and it is cheap and widely available in India — which keeps the bundle margin workable.

Capability is **detected at startup**, not configured by hand. Tiers: `high` (≥8 cores + VNNI → larger model at 640), `medium` (≥4 cores + AVX2 → YOLOX-s at 640), `low` (4 cores no VNNI → YOLOX-nano at 416).

The motion pre-filter is what actually buys "low-grade PC" — inference rarely runs. Idle CPU target is under 5%.

### D14 — Hardware-free testing is mandatory

**Decided:** Phase 1 planning. **Status:** locked.

No cameras are available yet. Every test must therefore run from a file source or synthetic frame, and CI must exercise the *real* RTSP path via a mock RTSP server (MediaMTX container) serving test clips.

Real-hardware bring-up is isolated as an explicit task and risk, not hidden inside Phase 3. The `FrameSource` abstraction is what makes this possible, and it is the most important boundary in the codebase.

### D15 — Detached tracker, own implementation

**Decided:** Phase 1 planning. **Status:** locked.

Tracking is cheap on CPU and pays for itself by suppressing duplicate alerts and enabling loitering logic later. Implemented as a small IoU tracker written for this project rather than copying BYTETracker, to keep the licensing chain clean and the dependency count at zero.

---

## Hardware constraints

| Constraint | Value |
|---|---|
| Target | Intel N100, 4-core, 6W, AVX2 + VNNI |
| RAM | 8GB typical (8 cameras must fit) |
| Storage | 128GB typical → event clips only, quota-capped |
| Network | Gigabit LAN; RTSP sub-stream 640×360 @ 10–15fps preferred |
| Inference | ONNX Runtime CPU; INT8 where available |
| Target cameras | 8 per box (`low` tier: 4) |
| Idle CPU | < 5% with no motion |
| Detection latency | < 2s motion → alert |

---

## Dependencies

**Backend (runtime):** pyav, onnxruntime, fastapi, uvicorn, pydantic, pydantic-settings, sqlalchemy, alembic, httpx, cryptography, structlog, numpy, opencv-python (headless preferred for MOG2)

**Backend (dev):** pytest, pytest-asyncio, pytest-cov, ruff, mypy, respx, psutil

**Frontend:** vue 3, vue-router, pinia, vite, tailwindcss, shadcn-vue, radix-vue, lucide-vue-next, gsap, lenis
**Shell:** tauri v2

**Explicitly absent:** anything from `ultralytics`; celery, redis (see D8).

---

## Ongoing trade-offs

**Cameras per box vs accuracy.** Motion gating is what lets 8 cameras fit on a N100. The cost is that a slow-moving object in a low-motion scene can be sampled less often and missed. Accepted for MVP; revisit if missed intrusions show up in the field.

**Detecting all 80 classes vs alert noise.** D3 solves this with the rules engine, but it depends on ROI drawing being genuinely easy. Poor ROI UX converts directly into alert fatigue, which is why the ROI editor gets disproportionate design attention in [design.md](design.md).

**MJPEG vs WebRTC for live view.** MJPEG uses bandwidth on the LAN and is not smooth, but needs no transcoding, no codec negotiation, and is debuggable with `curl`. On gigabit LAN the bandwidth argument is irrelevant. WebRTC deferred pending evidence operators need it.

**Windows-first vs bundle hardware.** Windows-first avoids asking the customer to buy anything, but the mini-PC bundle is a better margin story. Both remain viable; Windows-first is the lower-friction entry point.

---

## Open questions

- [ ] YOLOX-s vs RT-DETR-r18 — Phase 3 benchmark, measured on real footage
- [ ] Night/IR accuracy on real GIDC footage — must be an explicit Phase 3 test case
- [ ] Whether operators actually want smooth live video (decides WebRTC)
- [ ] WhatsApp adapter timing, given Meta verification lead time
- [ ] GUI vs Gujarati/Hindi localisation — likely valuable for the Rajkot market, unprompted so far
- [ ] Retention default (7 days proposed) — validate against real disk usage on a 128GB box
- [ ] Model download at first run vs bundled — affects installer size and offline install

---

## Progress log

| Date | Phase | Notes |
|---|---|---|
| — | 1 | Repo initialised, zero commits. Brainstorming complete. All ten documents written. D1–D15 recorded above. |