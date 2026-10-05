# CamBrain — Architecture

> Living document. Update as the system evolves.
> Related: [prd.md](prd.md) · [rules.md](rules.md) · [DATABASE.md](DATABASE.md) · [API.md](API.md)

---

## 1. Deployment model — the sidecar

CamBrain is an **add-on**, never a replacement. The customer's existing NVR or VMS keeps doing what it already does: connecting to cameras, recording to its own storage, serving its own live view. CamBrain is a second, independent reader of the same RTSP endpoints.

```
        ┌──────────────── Customer premises (shop / factory) ────────────────┐
        │                                                                   │
        │   ┌──────────────┐        ┌──────────────┐                        │
        │   │  Camera 1 ───┼──┐  ┌──┼── Camera 5   │   (existing hardware)   │
        │   └──────────────┘  │  │  └──────────────┘                        │
        │   ┌──────────────┐  │  │  ┌──────────────┐                        │
        │   │  Camera 2 ───┼──┼──┼── Camera 6   │                        │
        │   └──────────────┘  │  │  └──────────────┘                        │
        │   ┌──────────────┐  │  │  ┌──────────────┐                        │
        │   │  Camera 3 ───┼──┼──┼── Camera 7   │                        │
        │   └──────────────┘  │  │  └──────────────┘                        │
        │   ┌──────────────┐  │  │  ┌──────────────┐                        │
        │   │  Camera 4 ───┼──┘  └──┼── Camera 8   │                        │
        │   └──────────────┘        └──────────────┘                        │
        │         │  RTSP (sub-stream, 640×360 @ 10–15fps)                  │
        │         │                    │                                    │
        │   ┌─────┴────────────────────┴─────┐                              │
        │   │            LAN                 │                              │
        │   └─────┬────────────────────┬─────┘                              │
        │         │                    │                                    │
        │  ┌──────┴───────┐      ┌─────┴────────────────────────┐           │
        │  │ Existing NVR │      │       CAMBRAIN              │           │
        │  │ / VMS        │      │  ┌───────────────────────┐  │           │
        │  │              │      │  │ Tauri shell (Rust)   │  │           │
        │  │ keeps doing  │      │  │  ├─ tray icon        │  │           │
        │  │ all the      │      │  │  ├─ autostart on boot│  │           │
        │  │ recording    │      │  │  └─ localhost proxy  │  │           │
        │  └──────────────┘      │  ├───────────────────────┤  │           │
        │                        │  │ Python engine        │  │           │
        │                        │  │  ├─ FastAPI  :8765   │  │           │
        │                        │  │  ├─ per-camera       │  │           │
        │                        │  │  │  pipelines (N)     │  │           │
        │                        │  │  ├─ inference pool   │  │           │
        │                        │  │  ├─ motion gates (N) │  │           │
        │                        │  │  ├─ rules engine     │  │           │
        │                        │  │  └─ notifiers        │  │           │
        │                        │  ├───────────────────────┤  │           │
        │                        │  │ Vue 3 dashboard      │  │           │
        │                        │  └───────────────────────┘  │           │
        │                        └─────┬────────────────────────┘           │
        │                              │ HTTPS (outbound only)               │
        └──────────────────────────────┼────────────────────────────────────┘
                                       │
                            ┌──────────┴──────────┐
                            │  Telegram Bot API   │  ← the ONLY egress
                            └─────────────────────┘
```

**Two invariants that must never be violated:**

1. **CamBrain opens its own RTSP connections.** It never proxies, taps, or depends on the NVR's stream. If the NVR stops, CamBrain keeps working; if CamBrain stops, the NVR is untouched.
2. **Exactly one egress path**, the notifier, and it carries only what the customer explicitly asked to receive. No video stream, no telemetry, no update check that phones home.

---

## 2. Component boundaries

Each unit below has one job and an interface that lets it be replaced or tested without touching its consumers.

| Unit | Responsibility | Interface |
|---|---|---|
| `FrameSource` | Produce frames from *something* | `async frames() -> Frame`, `close()` |
| `RtspSource` | PyAV RTSP transport, reconnect, transport options | implements `FrameSource` |
| `FileSource` | Decode a local clip, loop or once | implements `FrameSource` |
| `CameraPipeline` | Own one camera end to end: source → motion → infer → rules | `start()`, `stop()`, `status` |
| `StreamManager` | Create/stop/observe pipelines, own their lifecycle | `add_camera()`, `remove()`, `status_all()` |
| `MotionGate` | Decide "is there motion?" cheaply | `update(frame) -> bool` |
| `Detector` | Turn a frame into detections | `infer(frame) -> list[Detection]` |
| `Tracker` | Assign stable IDs across frames | `update(detections) -> list[TrackedObject]` |
| `RulesEngine` | Decide whether a detection becomes an event | `evaluate(track, camera_cfg, now) -> RuleOutcome` |
| `Notifier` | Deliver an event somewhere | `send(event) -> None` |
| `ClipWriter` | Write pre/post-roll clip + still to disk | `write(event) -> ClipPaths` |

The `FrameSource` seam is the single most important boundary in the codebase. Because *every* source implements it, the entire pipeline is testable from a file on disk, and CI needs no cameras. Because it is a narrow interface, a new source (ONVIF discovery, USB webcam, a vendor SDK) is one new class.

---

## 3. The per-camera pipeline

This is the hot path. It runs once per camera, continuously, for the lifetime of the installation.

```
RTSPSource           MotionGate          Detector           Tracker        RulesEngine      Notifier
    │                    │                   │                 │                │              │
    │  frame @ 10-15fps  │                   │                 │                │              │
    ├───────────────────►│                   │                 │                │              │
    │                    │                   │                 │                │              │
    │              downscale to            │                 │                │              │
    │              640×360 grey            │                 │                │              │
    │                    │                   │                 │                │              │
    │              MOG2 diff ──► motion?    │                 │                │              │
    │                    │                   │                 │                │              │
    │              NO ─────┴─ skip. 0 ms.    │                 │                │              │
    │                    │                   │                 │                │              │
    │              YES ───┐                 │                 │                │              │
    │                    │                   │                 │                │              │
    │             honour sample_fps         │                 │                │              │
    │             + cooldown window         │                 │                │              │
    │                    │                   │                 │                │              │
    │                    └──────────────────►│                 │                │              │
    │                                        │ letterbox       │                │              │
    │                                        │ to model input  │                │              │
    │                                        │                 │                │              │
    │                                        │ ONNX Runtime ───►│                │              │
    │                                        │ (bounded pool)  │                │              │
    │                                        │                 │                │              │
    │                                        │ decode+NMS ─────►│                │              │
    │                                        │                 │                │              │
    │                                        │            IoU match,           │              │
    │                                        │            stable track_id      │              │
    │                                        │                 │                │              │
    │                                        │                 └────────────────►│              │
    │                                        │                                  │              │
    │                                        │           class allow-list?      │              │
    │                                        │           conf >= threshold?    │              │
    │                                        │           centroid in ROI?      │              │
    │                                        │           inside active hours?   │              │
    │                                        │           outside cooldown?      │              │
    │                                        │                                  │              │
    │                                        │                            ALERT │              │
    │                                        │                                  ├─────────────►│
    │                                        │                                  │              │
    │◄───────────────────────────────────────┴──────────────────────────────────┤              │
    │                    pre-roll ring buffer (10s)                             │
    │                    + post-roll (20s) ─────────────────────────────────────┤
```

**The motion gate is what makes this run on cheap hardware.** A 1080p camera at 15fps delivers 15 frames/sec. CamBrain looks at each one with MOG2 background subtraction — a few milliseconds of CPU — and only wakes the detector on maybe 5% of them. Inference cost collapses from "continuous" to "occasional", which is what buys 8 cameras on a 6-watt N100.

---

## 4. Concurrency model

### Why threads in one process (the decision)

The alternative was one worker *process* per camera. We chose a single process with a thread per camera. The reasoning, recorded so it isn't relitigated:

- **PyAV's decoder and ONNX Runtime's `run()` both release the GIL** during their actual compute. Threads are therefore genuinely parallel for exactly the two operations that dominate our cost. The usual GIL objection does not apply here.
- **One ONNX session per model tier, shared across cameras.** An `InferenceSession` holds hundreds of MB of weights and an arena allocator. Eight sessions would cost gigabytes on a box with 8GB total. One session, eight callers, is the correct arrangement.
- Process-per-camera would add ~200MB per camera for isolation we don't yet need.

### The escape hatch

`CameraPipeline` holds no shared mutable state — it receives its collaborators by constructor injection and communicates outward through an injected sink. If a decoder wedges hard enough to need OS-level isolation, moving each pipeline into a child process touches **one factory function** and nothing else. This seam is deliberate and must not be eroded by convenience shortcuts.

### Backpressure

Between the source and every consumer sits a **latest-frame slot**: an `asyncio.Queue(maxsize=1)` where a full queue means *replace the oldest frame*, never block and never accumulate. If inference is running behind reality, we want stale frames dropped, not a growing backlog that eats RAM and adds latency to alerts. This is the single most important rule in the streaming layer.

---

## 5. Frame lifecycle and memory discipline

Frames are `numpy.ndarray` views into decoded buffers. Every discipline below exists because getting it wrong produces a slow leak that only shows up after days of uptime:

- A frame is either **owned by the pipeline** or **borrowed by a consumer**, never both. Ownership is explicit in type hints.
- Consumers receive a **copy** when they retain a frame beyond the callback (clip writer, snapshot saver). A copy is a few hundred KB and lasts 30 seconds; a leak lasts forever.
- The decoder is closed in a `finally` on **every** path, including cancellation. Every reconnect closes the old container before opening a new one.
- `io_binding` with preallocated output buffers means inference allocates nothing per call in steady state.
- The inference pool is **bounded**. N cameras must not be able to spawn N threads and thrash the scheduler on a 4-core box.

`tests/test_stream_manager.py::test_memory_is_flat_across_reconnects` enforces this by running 50 reconnect cycles and asserting resident memory does not trend upward. It is the canary for the whole class of bug.

---

## 6. Model tiering

Hardware varies wildly in the field, so capability is **detected at startup** rather than configured by hand.

| Tier | Trigger | Model | Input |
|---|---|---|---|
| `high` | ≥ 8 cores, AVX2 + VNNI | YOLOX-m or RT-DETR (Phase 3 decision) | 640×640 |
| `medium` | ≥ 4 cores, AVX2 | YOLOX-s | 640×640 |
| `low` | 4 cores, no VNNI | YOLOX-nano | 416×416 |

Detection covers all 80 COCO classes in every tier — it's the same forward pass, so restricting the class set costs nothing at inference time. What costs money is *alerting* on all 80, which is why the rules engine rather than the detector decides what matters.

**Detection and alerting are separate concerns.** The detector reports what it sees; the rules engine decides what deserves an interruption. This is what lets one box serve a shop owner (alert on `person`, 10pm–6am) and a factory (alert on `person` + `truck` at the loading dock, all hours) without different models.

The concrete default model is **deferred to Phase 3** and chosen by measurement on real footage — see [memory.md](memory.md).

---

## 7. Data flow for one alert

```
detection → tracker assigns track_id → rules engine evaluates
         → ALERT
         → ├─ write still (JPEG)            ─┐
         → ├─ write clip (10s pre + 20s post)│─→ event + detections rows in SQLite
         → ├─ publish WS event to dashboard ─┘
         └─ hand to Notifier → Telegram sendPhoto / sendVideo
```

Everything before `Notifier` is local and durable. If the internet is down, the event is still in the database and appears in the dashboard the moment the box is reachable again. Telegram failure never loses data.

---

## 8. Why no Celery/Redis

Considered and rejected for V1. The only asynchronous work is "write a clip" and "POST to Telegram" — a few seconds of IO each. A broker plus a worker process costs ~150MB of RAM on an 8GB box, adds a second thing to install and keep alive on a customer's machine, and buys backpressure semantics we already have via bounded queues.

If clip writing ever grows to minutes (video export, batch processing), the seam is `ClipWriter` and swapping in a Celery task is a contained change. Recorded in [memory.md](memory.md) as a deliberate deferral, not an oversight.

---

## 9. Extension points

| Extension | Where it attaches | Cost |
|---|---|---|
| New model family | `Detector` protocol | Benchmark + one decoder module |
| WhatsApp alerts | `Notifier` protocol | One adapter; already stubbed in design |
| ONVIF camera discovery | New `FrameSource` | One class |
| Linux appliance | Nothing in the engine | Tray shell is the only platform-specific piece |
| Central fleet console | New service reading the same API | No change to the edge box |

The test of a good architecture here is whether the last four rows are plausible. They are, and that is why the boundaries above are drawn where they are.