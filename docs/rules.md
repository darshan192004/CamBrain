# CamBrain — Engineering Rules

> Living document. These are constraints, not suggestions.
> Related: [CODE_STYLE.md](CODE_STYLE.md) · [architecture.md](architecture.md) · [SECURITY.md](SECURITY.md)

---

## 1. The laws

These are the rules whose violation produces a bug that is expensive to find. Everything else is style and lives in [CODE_STYLE.md](CODE_STYLE.md).

---

## 2. Stream lifecycle rules

### 2.1 One `FrameSource` per camera. Always.

A camera has exactly one source. Sources are never shared between cameras, never shared between the pipeline and the dashboard's live view. The dashboard gets frames through the same pipeline that runs inference, not by opening its own connection.

Opening a second RTSP connection to the same camera is how we exhaust a customer's camera's connection limit and get blamed for breaking their NVR.

### 2.2 Every resource closes in `finally`

Containers, sockets, and files close in a `finally` block on **every** exit path, including `asyncio.CancelledError`. A reconnect loop without an unconditional close leaks one decoder per drop, and a camera that drops hourly leaks 8/day.

```python
# WRONG — leaks the container on exception
container = av.open(url)
for frame in container.decode(video=0):
    ...

# RIGHT
container = av.open(url)
try:
    for frame in container.decode(video=0):
        ...
finally:
    container.close()
```

### 2.3 Close the old source before opening the new one

On reconnect, teardown precedes re-open. Never hold two containers for one camera, even briefly.

### 2.4 Backoff is exponential, capped, and jittered

```
delay = min(base * 2**attempts, max_delay)   # base 1s, cap 60s
delay = random.uniform(0, delay)             # full jitter
```

Without jitter, eight cameras whose NVR reboots at 09:00 all retry at 09:00:01, 09:00:03, 09:00:07… and hammer the camera that is still coming up. The jitter spreads the herd. Cap is 60s: long enough not to spin, short enough that a fixed fault doesn't look like a dead camera to the customer.

The backoff counter resets only after a stream has been **stable for 60s**, not merely after one successful frame. Otherwise a camera that connects and immediately drops retries forever at the minimum delay.

### 2.5 A stalled stream is a dead stream

A TCP/RTSP connection can stay open while delivering no frames — the classic hung-camera failure. A watchdog treats *no frame for `stall_timeout`* (default 15s) as a failure and forces a reconnect. Without it, a camera that died at 3am shows "connected" in the dashboard forever, which is worse than showing an honest error.

---

## 3. Frame handling rules

### 3.1 Latest-frame slot. Never an unbounded queue.

Every hand-off between stages is `asyncio.Queue(maxsize=1)` with **replace-oldest** on full. This is not a style preference; it is the backpressure mechanism.

```python
# WRONG — producer blocks, or backlog grows without limit
await queue.put(frame)

# RIGHT — never blocks, drops the stale frame
try:
    queue.put_nowait(frame)
except asyncio.QueueFull:
    with queue_lock:
        queue.get_nowait()   # discard stale
        queue.put_nowait(frame)
```

If inference falls behind reality, we want to skip stale frames. A growing backlog adds latency to alerts and consumes RAM until the box dies.

### 3.2 Drop frames; don't decode and discard

Frame skipping happens **before** the expensive resize/colour conversion, by selecting which decoded frames to process. Decoding a frame to throw it away spends the CPU we were trying to save.

### 3.3 Ownership is explicit in the type hint

A frame passed to a callback is **borrowed** — valid only for the duration of the call. A consumer that retains one must `.copy()`.

```python
def on_frame(self, frame: NDArray[uint8]) -> None:
    self._still = frame.copy()   # retained beyond callback → must copy
```

Every leak of this shape looks identical: memory climbs slowly, restart fixes it, nobody finds it.

### 3.4 Downscale early

Motion detection runs on a downscaled greyscale copy (640×360 by default). Full-resolution frames are only materialised when a clip is being written. Resizing is cheap; doing it on a full 1080p frame for every frame is not.

---

## 4. Inference rules

### 4.1 One `InferenceSession` per model tier. Never per camera.

An ONNX session holds the weights plus an arena allocator — hundreds of megabytes. Eight sessions on an 8GB box is not a performance problem, it's an out-of-memory failure. Sessions are created once at startup, owned by a `DetectorPool`, and shared by all callers.

### 4.2 The inference pool is bounded

Concurrency is capped at `min(4, cpu_count - 1)`. N cameras must never spawn N threads. An unbounded pool on a 4-core box makes every camera slower simultaneously instead of some cameras fast and the rest slow.

### 4.3 Zero steady-state allocation

Use `io_binding` with preallocated input/output buffers. Per-call allocation in the hot path produces fragmentation that shows up as memory creep after days.

### 4.4 The detector is stateless with respect to cameras

`Detector.infer(frame)` may not know or care which camera the frame came from. Camera-specific parameters (ROI, thresholds, class filters) belong to `RulesEngine`, not the model wrapper. This keeps the detector trivially testable and prevents per-camera state leaking between callers.

### 4.5 Decode failures are contained

A malformed model output — NaNs, wrong shape, wrong rank — must raise a typed `InferenceError` and skip the frame. It must never propagate into the pipeline loop and kill the camera.

---

## 5. Motion gate rules

### 5.1 The gate must actually gate

If inference is running on more than ~20% of sampled frames in a static scene, the gate is broken. This is an assertion with a metric behind it, not a hope — see the `motion_gate_ratio` metric in [architecture.md](architecture.md).

### 5.2 Cooldown is mandatory

Without a cooldown, a person standing still in frame re-triggers inference every cycle forever. Default 5s per track.

### 5.3 The gate is a filter, never a trigger source

The gate may only *permit* inference. Alerts are decided by `RulesEngine` on detections. Never raise an alert from a motion event — motion is not an object and means nothing to the customer.

### 5.4 Train MOG2 on real frames, and reset on scene change

The background model needs a few seconds of the actual scene. On a genuine lighting change (lights switch on at dusk), a naive MOG2 flags every pixel as foreground and floods the pipeline with inference. Detect a large global brightness shift and reset the background model.

---

## 6. Rules engine rules

### 6.1 The detector never decides what matters

All 80 classes are detected in every tier. The rules engine decides which classes, which zones, which hours raise an alert. Any code that filters by class before the rules engine is wrong.

### 6.2 Evaluation is pure

`evaluate(track, config, now) -> RuleOutcome` has no side effects and no IO. It reads config, returns a decision. Side effects (write clip, send alert) happen in the caller. This makes every rule independently testable and makes the whole alerting policy inspectable.

### 6.3 Every event is de-duplicated

An event carries a `dedupe_key` of `(track_id, rule_id, time_bucket)`. Without it, one person standing in an ROI produces one alert per sample — and the customer uninstalls.

### 6.4 Active hours are timezone-aware and evaluated with a single clock

Rule windows are stored as local wall-clock time plus an IANA timezone, and compared in that zone. Server UTC vs shop-local is a bug that only appears when a customer is outside UTC — i.e. always, eventually.

---

## 7. Error handling rules

### 7.1 A camera failure never touches another camera

One bad camera must not degrade, stall, or kill the others. Every pipeline owns its own exception handling and reports status upward; `StreamManager` observes and logs but never lets one child's failure propagate.

### 7.2 Fail loud into logs, fail quiet into the UI

Stream drops get retried and logged at WARN with the URL **masked**. The dashboard shows status, not stack traces. A customer cannot act on a traceback and a log they will never read is useless to them.

### 7.3 Credentials never appear in a log line

Enforced by the logging filter in [SECURITY.md](SECURITY.md), not by discipline. Passwords, tokens, and RTSP userinfo are redacted at the formatter so it is impossible to emit them by accident.

### 7.4 Cancellation is a normal exit path

`asyncio.CancelledError` is not exceptional. Shutdown must close sources and unregister tasks without logging errors or masking the original cause.

---

## 8. Security rules

Summarised here, specified in [SECURITY.md](SECURITY.md).

- Secrets are encrypted at rest, never stored in plaintext, never logged.
- Every API route requires authentication. There is no "trusted LAN" exemption.
- SQLite files and clip directories get restrictive permissions at creation.
- Inbound HTTP is localhost-only by default. Binding to `0.0.0.0` requires an explicit config flag and a warning in the log.

---

## 9. Testing rules

### 9.1 No test may require a camera

Every test runs from a file source or a synthetic frame. CI has no cameras and neither should your laptop.

### 9.2 The leak test is mandatory, not optional

Memory correctness is asserted, not eyeballed:

```python
def test_memory_is_flat_across_reconnects(...):
    # 50 cycles, assert RSS plateau rather than "didn't crash"
```

### 9.3 Test the reconnect timing, don't just the reconnect

Assert the backoff *sequence and jitter distribution*. A reconnect loop that works but retries every 100ms will flatten a customer's camera.

### 9.4 Mock only at protocol boundaries

Mock `FrameSource` and `Detector`. Do not mock `cv2`, PyAV, or ONNX Runtime internals — that tests the mock, not the code.

### 9.5 Rules engine tests are table-driven

One row per rule combination. This is the highest-value test surface in the codebase, because alert behaviour is what the customer actually experiences.

---

## 10. Licensing rules

**No AGPL-licensed code or weights, ever, in any branch — including throwaway experiments.**

The product is sold closed-source. An AGPL dependency reachable from the shipped application obliges source disclosure of the whole thing. This is not a "we'll fix it later" situation; it is a reason the company cannot exist.

This specifically rules out **every Ultralytics YOLO release** — v5, v8, v11, v26 — including weights exported to ONNX, including self-trained weights, and including use purely during experimentation. Export format does not change the license on the weights.

Enforcement: CI runs a dependency-license scan and fails the build on any AGPL identifier. Approved licenses are Apache-2.0, MIT, BSD, ISC, and PSF for Python; the same plus MPL-2.0 for the frontend. Full reasoning and citations in [memory.md](memory.md).

---

## 11. Rules that exist because of a specific failure

| Rule | Failure it prevents |
|---|---|
| Latest-frame slot | Backlog growth → OOM after days |
| One ONNX session per tier | 8 sessions → OOM on 8GB box |
| Close in `finally` | Decoder leak per reconnect |
| Jittered backoff | Thundering herd on camera reboot |
| Stall watchdog | Phantom "connected" state on dead camera |
| Cooldown on motion | Alert flood → uninstall |
| Detached IoU tracker | Licensing entanglement from copied BYTETracker code |
| Memory test in CI | All of the above, silently, in production |

New rules get added to this table with the failure they prevent. A rule with no failure behind it is a preference and belongs in [CODE_STYLE.md](CODE_STYLE.md).