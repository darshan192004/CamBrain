# Phase 4 — Dashboard & ROI Editor Implementation Plan

**Goal:** a non-technical user configures a camera unaided — log in, add a camera with a diagnostic test-connection, watch live tiles, draw ROI zones on a frozen snapshot, and manage rules and the event log from a keyboard-accessible dashboard.

**Spec:** [`docs/superpowers/specs/spec.md`](../../specs/spec.md) — §3 (auth/roles), §7.3 (rules test endpoint), §9.3 (ROI editor is the make-or-break screen), §10.3 (verification matrix rows assigned to Phase 4), §11 (tests, hardware-free rule), §12 gate row **"A non-technical user configures a camera unaided."**
Design: [`docs/superpowers/specs/2026-10-05-cambrain-mvp-design.md`](../../specs/2026-10-05-cambrain-mvp-design.md) and living [`docs/design.md`](../../../design.md) §2 (tokens), §3 (IA), §4 (live grid), §5 (ROI editor), §6 (event log), §7 (login), §9 (frontend stack), §10 (component inventory), §11 (accessibility).
Living docs: [`docs/API.md`](../../../API.md), [`docs/tasks.md`](../../../tasks.md) (Phase 4 section mirrors this plan).

## Conventions (this plan differs from Phase 3's)

- **Test-first per task.** Backend: failing pytest → green. Frontend: failing Vitest → green.
- **Contract-critical code is written out** in this plan: backend routes, pure math (`roi/geometry`), byte-level parsers (MJPEG client), and every test vector for them.
- **Vue SFCs are specified as test names + acceptance criteria**, not pasted whole — SFC code drifts during implementation and the tests are the contract. Each task names the test file and the tests it must contain.
- **Loop:** failing test → watch fail → implement → watch pass → gate (backend: `ruff format backend; ruff check backend; ruff format --check backend; mypy backend/app`; frontend: `npm run lint; npm run format:check; npm test; npm run build`) → stage exact files → commit → push. Plan blocks are synced to corrected code as discoveries land (Phase 3 discipline).

## Scope

**In (maps to `docs/tasks.md` Phase 4):**

- Backend wiring explicitly stubbed for Phase 4/5: **real probe** (`POST /cameras/{id}/test`), **snapshot** (`POST /cameras/{id}/snapshot`), **MJPEG stream** (`GET /cameras/{id}/stream`), **event thumbnail** (`GET /events/{id}/thumbnail` — referenced by `thumbnail_url` but not yet routed).
- Frontend foundation: design tokens → CSS variables, Vitest, API client, router + Pinia stores, login + AuthGuard + RoleGate, AppShell · Sidebar · TopBar · StatusBar.
- `CameraGrid` · `CameraTile` (MJPEG live view, four tile states, add-camera tile, event ticker).
- `AddCameraDialog` with real **test connection** failure reasons (six `error_code`s).
- Camera detail with **rules editor** (spec §1 in-scope; tasks.md gains a row) and rule diagnostics (Phase 3's replay endpoint, rendered).
- `RoiEditor`: frozen snapshot, freehand vertices, drag, min-3/min-area, zone list, class filter, coverage %, save/cancel, keyboard operation, normalised storage (verification-matrix row `test_rois.py::test_roi_survives_resolution_change`).
- Event log: filters, table, thumbnails, bulk acknowledge, detail with detection overlay.
- Settings pages reachable from the sidebar: Users (admin) + System status (tasks.md gains a row).
- Accessibility pass: focus rings, `aria-live`, reduced-motion, contrast (design §11).

**Out (locked):**

- WebSocket `/ws/alerts` + `/ws/frames` (Phase 5 — ticker/grid poll instead; one swap later).
- Event/still persistence from the pipeline, clips, ring buffer, notifiers (Phase 5). Clip player renders only when `has_clip` — always false until then, hidden behind a note.
- Tauri tray, autostart, installer (Phase 6).
- Playwright E2E suite (candidate Phase 6; the gate demo uses the MCP browser once, manually).
- Generic API rate limiter (see D4), ONVIF, WebRTC, i18n.

## Locked decisions & deviations (D1–D9)

| # | Decision | Rationale |
|---|---|---|
| D1 | **MJPEG concurrency cap 4 → 12 per client IP**, implemented with the stream route | The grid shows up to 8 tiles; API.md's "4 concurrent per session" would 503 the fifth tile. Cap stays (bounded RTSP pressure); API.md rate-limit row updated. Revisit with the shared pipeline in Phase 5. |
| D2 | **`POST /cameras/{id}/snapshot` returns `image/jpeg` bytes**, not `CameraTestResult` | The ROI editor needs an image, and the stub's JSON shape was never documented in API.md. API.md gains the response contract. |
| D3 | **Grid tiles read MJPEG with `fetch` + a byte-stream multipart parser** | The access token lives in memory and rides `Authorization: Bearer` — an `<img src>` cannot send it, and a token in the query string is what API.md §3 forbids for WS. One parser, unit-tested against crafted byte chunks; `AbortController` tears tiles down. |
| D4 | **Generic rate limiter stays deferred** | Phase 2 shipped login lockout (`423`) but no fixed-window limiter; the §6 table is documented-but-unimplemented. Phase 4 implements only the stream slot cap (resource protection for what it builds). Remaining rows → Phase 5. |
| D5 | **Rules editor + Users/System pages are Phase 4 scope** | Spec in-scope text names a "rules editor"; design §3 routes `/cameras/:id` → rules and lists `/settings/users`, `/settings/system`. tasks.md Phase 4 gains two rows (doc-sync in 4.18). |
| D6 | **No WS, no clips** | Ticker polls `GET /events?limit=5&sort=-started_at` every 10s; detail page hides the clip player until `has_clip` is ever true. Phase 5 replaces polling with `/ws/alerts`. |
| D7 | **Vitest + @vue/test-utils + jsdom; CI frontend job gains `npm test`** | No test framework exists under `frontend/`; the gate needs evidence. jsdom + mocked fetch keeps tests hardware-free (spec §11.1 applies to the frontend too). |
| D8 | **`GET /events/{id}/thumbnail` is added now** | `EventOut.thumbnail_url` already points at it; today it 404s at runtime. Serves `thumbnail_path` (nullable until Phase 5) or 404 → UI placeholder. API.md endpoint table gains a row. |
| D9 | **Probe, snapshot, and MJPEG share one injectable `FrameSource` factory dependency** | Default builds an `RtspSource` from `rtsp_url` + decrypted credentials; tests override it with `FileSource` (spec §11.1 — no camera, no network). |

## Task list (dependency order)

Backend contract first (it is what the UI consumes), then foundation, then vertical slices.

| # | Task | Primary files | Size |
|---|---|---|---|
| 4.1 | Real probe wired — `POST /cameras/{id}/test` | `routers/cameras.py`, `stream/probe.py` | M |
| 4.2 | Snapshot — `POST /cameras/{id}/snapshot` → `image/jpeg` | `routers/cameras.py`, API.md | S |
| 4.3 | MJPEG stream + slot cap (D1) — `GET /cameras/{id}/stream` | `routers/cameras.py`, `stream/mjpeg.py`, API.md | M |
| 4.4 | Event thumbnail route (D8) | `routers/events.py`, API.md | S |
| 4.5 | ROI survives resolution change (verification-matrix row) | `tests/test_rois.py` | S |
| 4.6 | Tokens + Vitest + CI `npm test` (D7) | `style.css`, `package.json`, `ci.yml` | S |
| 4.7 | API client — envelope, Bearer, refresh | `src/api/client.js` + test | M |
| 4.8 | Auth store, router guards, Login, RoleGate | `src/stores/auth.js`, `router.js`, `LoginForm` | M |
| 4.9 | AppShell · Sidebar · TopBar · StatusBar | `src/layout/*` | M |
| 4.10 | MJPEG client + CameraGrid + CameraTile + ticker (D3, D6) | `src/api/mjpeg.js`, `src/camera/*` | L |
| 4.11 | AddCameraDialog + ConnectionTest (six error codes) | `src/camera/AddCameraDialog.vue` | M |
| 4.12 | Camera detail + rules editor | `src/camera/CameraDetail.vue`, `src/rules/*` | L |
| 4.13 | Rule diagnostics panel (Phase 3 replay endpoint) | `src/rules/RuleDiagnostics.vue` | S |
| 4.14 | ROI geometry + RoiCanvas (draw/drag/keyboard) | `src/roi/geometry.js`, `RoiCanvas.vue` | L |
| 4.15 | ZoneList + coverage + class filter + save/cancel | `src/roi/*` | M |
| 4.16 | Event log + detail + detection overlay | `src/events/*` | L |
| 4.17 | Settings pages — Users + System (D5) | `src/settings/*` | M |
| 4.18 | Accessibility pass, full gate, living docs, PR | `docs/tasks.md`, API.md, plan ledger | M |

**Checkpoints:** after **4.3** the backend contract (probe/snapshot/MJPEG) is green and API.md synced; after **4.11** the core path (login → grid → add camera with diagnostics) works end-to-end; after **4.15** the make-or-break screen (ROI editor) is done; **4.18** is the gate.

## Backend design notes (contract-critical)

### Shared frame-source factory (D9)

```python
# backend/app/services/stream/factory.py
"""Injectable FrameSource construction for API routes (spec 11.1 / plan D9)."""

from collections.abc import Callable
from urllib.parse import quote, urlsplit, urlunsplit

from app.db.models import Camera
from app.services.stream.rtsp_source import RtspSource
from app.services.stream.source import FrameSource


def connect_url(camera: Camera, *, decrypt: Callable[[str], str]) -> str:
    """Build a credentials-bearing RTSP URL from columns.

    Credentials live in `rtsp_username` / `rtsp_password_enc` (DATABASE §4.4);
    this is the single place they enter a URL, and that URL never touches a
    log or a response. The stored token is Fernet text stored as bytes.
    """
    parts = urlsplit(camera.rtsp_url)
    if camera.rtsp_username:
        userinfo = quote(camera.rtsp_username, safe="")
        if camera.rtsp_password_enc is not None:
            password = decrypt(camera.rtsp_password_enc.decode("ascii"))
            userinfo += ":" + quote(password, safe="")
        netloc = f"{userinfo}@{parts.netloc}"
    else:
        netloc = parts.netloc
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def default_source_factory(camera: Camera) -> FrameSource:
    """Production factory: a fresh RTSP source per request-scoped consumer."""
    from app.core.crypto import decrypt  # imported lazily: DPAPI touch only when used

    return RtspSource(connect_url(camera, decrypt=decrypt))


def get_source_factory() -> SourceFactory:
    """FastAPI dependency; tests override it with a FileSource/fake factory."""
    return default_source_factory
```

Routes depend on `SourceFactory = Callable[[Camera], FrameSource]` via an `Annotated` `SourceFactoryDep` (B008); tests override `get_source_factory` with a `FileSource` factory (and with fakes whose `async def frames()` raises, for error paths). Probe, snapshot, and MJPEG all consume this one factory — no route opens a connection its own way.

### Probe (4.1) — semantics (as shipped)

Always `200`; failure is data. `probe_source(source, url=…, budget_s=3.0, max_frames=10)` in `stream/probe.py` returns a frozen `ProbeOutcome` dataclass the route maps to `CameraTestResult` via `asdict`. Success: `latency_ms` (probe start → first frame), `frame_width/height` (first frame), `fps` ((count−1)/span). Failure path: exception from `frames()` → `classify_code` (honours `StreamError` `"CODE: …"` message prefix first, then `classify_rtsp_error`, else fallback); budget expiry with zero frames → the source's `last_error` if typed, else `CONNECT_TIMEOUT`. Human messages come from API.md's examples, URLs via `mask_url`. Uses `AdminDep` (API.md: role admin).

### JPEG encoding (4.2 / 4.3) — as shipped (PyAV 19)

`Frame.data` is a raw RGB ndarray (`source.py`) — snapshot and MJPEG both need an encoder. PyAV 19 has **no `VideoFrame.encode`**; the encoder is a `CodecContext` with geometry/options set before the first `encode` (which lazily opens the codec). PyAV re-formats rgb24 → yuvj420p itself:

```python
# backend/app/services/stream/jpeg.py
"""RGB ndarray -> JPEG bytes for snapshot and MJPEG (API Cameras)."""

import av
from av.codec import CodecContext

from app.services.stream.source import Frame

DEFAULT_QUALITY = 5


def encode_jpeg(frame: Frame, *, quality: int = DEFAULT_QUALITY) -> bytes:
    """Encode one frame as JPEG (quality = FFmpeg mjpeg qscale, 2 best..31 worst)."""
    ctx = CodecContext.create("mjpeg", "w")
    ctx.width, ctx.height = frame.width, frame.height
    ctx.pix_fmt = "yuvj420p"
    ctx.options = {"qscale": str(quality)}
    vf = av.VideoFrame.from_ndarray(frame.data, format="rgb24")
    packets = ctx.encode(vf)
    return b"".join(bytes(packet) for packet in packets)
```

Probe reads `frame.width/height` (no encoding); snapshot encodes frame 1; MJPEG encodes every frame it forwards.

### MJPEG (4.3) — semantics

`multipart/x-mixed-replace; boundary=frame` — parts `Content-Type: image/jpeg`, `Content-Length`, body = JPEG bytes from `encode_jpeg`. Per API.md: on stream error emit a **zero-length part** (no headers beyond the boundary) so the client re-reads the next header; generator exits when the client disconnects or the source ends. Slot cap (D1): per-client-IP counter, acquire before starting the generator, release in `finally`; full → `503 NO_CAPACITY` envelope.

```python
# backend/app/services/stream/mjpeg.py
"""Multipart/x-mixed-replace writer for MJPEG (API Cameras /stream)."""

from collections.abc import AsyncIterator

from app.services.stream.source import FrameSource

BOUNDARY = b"frame"


def mjpeg_parts(source: FrameSource) -> AsyncIterator[bytes]:
    """Yield multipart bytes for one camera stream.

    An empty part (just the boundary line) is emitted when the source raises,
    per API: the client re-reads the next header instead of dying with us.
    """
    prefix = b"--" + BOUNDARY + b"\r\nContent-Type: image/jpeg\r\nContent-Length: "

    async def frames() -> AsyncIterator[bytes]:
        it = source.frames()
        while True:
            try:
                frame = await it.__anext__()
            except StopAsyncIteration:
                yield b"--" + BOUNDARY + b"--\r\n"
                return
            except Exception:  # noqa: BLE001 - one bad frame must not kill the view
                yield b"--" + BOUNDARY + b"\r\n\r\n"
                continue
            jpeg = encode_jpeg(frame)
            yield prefix + str(len(jpeg)).encode() + b"\r\n\r\n" + jpeg + b"\r\n"
```

(Final shape may differ — e.g. wrapping the iterator per request — but the test contract below is fixed.)

### Tests this plan requires (backend)

| Test file | Tests |
|---|---|
| `test_api_cameras.py` (edit) | `test_probe_ok_reports_dims_and_fps` (FileSource), `test_probe_transport_failure_is_200_with_code`, `test_probe_stream_error_reason_is_honoured`, `test_probe_unknown_camera_404`, `test_snapshot_returns_jpeg_magic`, `test_snapshot_404_unknown_camera`, `test_stream_sends_multipart_frames`, `test_stream_404_unknown_camera`, `test_stream_slot_cap_returns_503` (cap dependency overridden to 1, slot held) — replaces `test_stream_is_501_until_wired` |
| `test_api_events.py` (edit) | `test_thumbnail_serves_file`, `test_thumbnail_404_when_absent`, `test_thumbnail_cross_tenant_404` |
| `test_rois.py` (new) | `test_roi_survives_resolution_change` (verification matrix row) |
| `test_mjpeg.py` (new) | `test_part_headers_and_jpeg_body`, `test_error_emits_empty_part_then_recovers`, `test_source_end_emits_close_boundary` |
| `test_stream_factory.py` (new) | `test_connect_url_embeds_credentials_encoded`, `test_connect_url_without_username_is_unchanged`, `test_connect_url_username_only_has_no_colon`, `test_connect_url_decrypts_the_stored_token` |

### Contract amendments to API.md (synced in the task that lands them)

1. **4.2** — snapshot response: `200` `image/jpeg` (single frame, `Cache-Control: no-store`), errors `404`.
2. **4.3** — rate-limit row: `GET /cameras/{id}/stream` → "12 concurrent per client IP → `503 NO_CAPACITY`" (was 4 per session).
3. **4.4** — endpoints table gains `GET /api/v1/events/{id}/thumbnail` (role `any`): serves the stored still, `404` when absent (Phase 5 writes stills).

## Frontend design notes

### Token map (task 4.6, from design §2)

`style.css` gains `:root { --background, --foreground, --card, --muted, --muted-foreground, --border, --input, --primary, --primary-foreground, --accent, --destructive, --ring, --radius, --sidebar-* }` plus motion tokens `--dur-fast/base/slow/alert`, `--ease`; Tailwind v4 `@theme` maps each to a utility (`bg-background`, `text-foreground`, `ring-ring`…). **Hardcoded hex in components stays prohibited.** Focus ring: `outline: 2px solid var(--accent); outline-offset: 2px`.

### API client shape (task 4.7)

```js
// Authorization header from an in-memory token module (never localStorage).
// X-CambBrain-Client on every request; Content-Type on bodies (CSRF middleware).
// 401 → single-flight POST /auth/refresh → retry once → else onAuthError().
// Error envelope { error: { code, message, field, correlation_id } } → ApiError.
```

### Guards (task 4.8)

`router.beforeEach`: no token → `/login` (except `/login`); token → `GET /auth/me` once per reload to hydrate user; `/settings/*` requires `role === "admin"` else redirect `/cameras` (nav hidden too — API is the control, RoleGate is presentation, API.md §5).

### MJPEG client (task 4.10, D3) — test vectors fixed here

```js
// openMjpeg(url, { onFrame, onError, signal }): fetch(url, { signal }) →
// reader on body stream → Uint8Array buffer → split on "\r\n\r\n" header /
// boundary markers → each JPEG = Uint8Array slice → onFrame(blobUrl), revoke
// previous URL. Tests feed hand-built byte chunks where the boundary and JPEG
// header are split across chunk boundaries; a dropped chunk must not stall the
// parser or emit a truncated frame. 503 NO_CAPACITY → onError("capacity").
```

## Verification matrix additions (spec §10.4 / §12 rows owned by Phase 4)

| Requirement | Proving test | Task |
|---|---|---|
| Normalised ROI survives resolution change | `test_rois.py::test_roi_survives_resolution_change` | 4.5 |
| Test-connection reports the real failure reason | `test_api_cameras.py::test_probe_transport_failure_is_200_with_code` (+ `…stream_error_reason_is_honoured`) | 4.1 |
| Live view needs no codec negotiation | `test_api_cameras.py::test_stream_sends_multipart_frames` | 4.3 |
| No secret in API responses (snapshot/stream) | probe/snapshot tests assert body has no password | 4.1–4.2 |
| Viewer cannot write | `src/settings` + guards: `viewer is blocked from /settings/*` (Vitest) | 4.8 |
| Hardware-free tests | every backend test above injects `FileSource`; every frontend test mocks `fetch` | all |

## Gate (task 4.18)

1. Backend: `ruff check/format --check backend`, `mypy backend/app`, `pytest -m "not rtsp and not slow" --ignore=backend/tests/rtsp`, `pytest -m slow`, `pytest -m rtsp`.
2. Frontend: `npm run lint`, `npm run format:check`, `npm test`, `npm run build` (all under `frontend/`).
3. `git status --porcelain` clean except `.tmp/`.
4. Living docs: tasks.md Phase 4 ticks (+ the two new rows), API.md amendments verified, this plan's ledger filled.
5. **Human gate (spec §12):** the non-technical-user walkthrough, demonstrated once via the MCP browser — login, add camera (test-connection failure reason visible), draw a zone, see a rule, browse events.
6. PR → PR-Agent must pass (apply its suggestions) → merge → delete branches on GitHub.

## Risks

| Risk | Impact | Mitigation |
|---|---|---|
| MJPEG parser byte-boundary bugs | Live view stalls or tears | Fixed test vectors with chunk splits (4.10); abort path tested |
| jsdom can't do layout (canvas/pointer) | ROI editor tests flaky | Geometry is a pure module tested separately; component tests assert state + emitted events, not pixels |
| No backend events yet (Phase 5 writes them) | Event log always empty | Seed rows in tests; empty state is a designed state |
| 8 concurrent RTSP sessions from the grid | Weak camera/switch limits | D1 cap 12 total, one session per tile, documented; shared pipeline is Phase 5's fix |
| Scope balloon (L-sized UI tasks) | Slow landing | Checkpoints after 4.3 / 4.11 / 4.15; tasks split at component seams |

## Execution ledger (filled during Task 4.18)

| Gate step | Evidence | Result |
|---|---|---|
| ruff check / format --check backend | | |
| mypy backend/app | | |
| backend default suite | | |
| backend slow | | |
| backend rtsp | | |
| frontend lint / format:check | | |
| frontend tests | | |
| frontend build | | |
| `git status --porcelain` | | |
| commits | task → SHA list | |


---

# Task detail

## Task 4.1 — Real probe wired

**Modify:** `backend/app/services/stream/factory.py` (new), `backend/app/api/routers/cameras.py`, `backend/tests/test_api_cameras.py`.

**Steps:**
1. Add `factory.py` as specified above (`connect_url`, `default_source_factory`, `get_source_factory`) + `tests/test_stream_factory.py` (credential embedding, no-username, username-only, decrypt-token path; password never in `rtsp_url` of any response).
2. Failing tests: `test_probe_ok_reports_dims_and_fps` (override factory → `FileSource(gate_clip_path)`), `test_probe_transport_failure_is_200_with_code` (fake whose **`async def frames()`** raises `ConnectionRefusedError` → `HOST_UNREACHABLE`; a sync generator yields `TypeError` → `DECODE_FAILED`), `test_probe_stream_error_reason_is_honoured` (`StreamError("AUTH_FAILED: …")` → prefix wins), `test_probe_unknown_camera_404`.
3. Implement `probe_source(source, *, url, budget_s=3.0, max_frames=10) -> ProbeOutcome` in `stream/probe.py` (`failure_outcome`, `classify_code` exported); replace the stub body in `test_camera` — factory call wrapped (decrypt failure → `DECODE_FAILED`), route maps outcome via `asdict`.

**Acceptance:**
- [x] Probe on a FileSource factory reports real dims/fps/latency; always 200; failure carries one of the six `error_code`s.
- [x] Response never contains credentials (assert on JSON dump).
- [x] `test_stream_factory.py` proves credentials are percent-encoded into the netloc and absent when no username.

**Gate:** backend loop. **Commit:** `feat(api): real RTSP probe with the six documented error codes`

## Task 4.2 — Snapshot returns JPEG

**Modify:** `routers/cameras.py`, `docs/API.md`, tests.

**Steps:** add `stream/jpeg.py` (`encode_jpeg`); failing tests `test_snapshot_returns_jpeg_magic` (`FF D8` prefix, `Content-Type: image/jpeg`), `test_snapshot_404_unknown_camera`; implement: first frame from the same factory → `Response(encode_jpeg(frame), media_type="image/jpeg")` with `Cache-Control: no-store`. API.md: document the response under the cameras table.

**Acceptance:**
- [x] `POST /cameras/{id}/snapshot` → `200 image/jpeg`, one frame, no-store.
- [x] API.md documents the binary contract (D2).
- [x] Viewer role allowed (API.md: `any`).

**Gate:** backend loop + openapi spec test still green. **Commit:** `feat(api): snapshot captures a real JPEG frame for the roi editor`

## Task 4.3 — MJPEG stream + slot cap

**Modify:** `stream/mjpeg.py` (new), `routers/cameras.py`, `docs/API.md`, tests (`test_mjpeg.py`, `test_api_cameras.py`).

**Steps:**
1. Failing `test_mjpeg.py`: part headers + JPEG body; source raises mid-stream → empty part then next frame (recovery); source exhausted → close boundary.
2. Failing API tests: `test_stream_sends_multipart_frames` (FileSource, ≥2 JPEG parts), `test_stream_404_unknown_camera`, `test_stream_slot_cap_returns_503` (override cap→1, hold slot via the slots object, route returns `503 NO_CAPACITY`). Delete `test_stream_is_501_until_wired`.
3. Implement route: acquire slot per client IP (`request.client.host`), `StreamingResponse(mjpeg_parts(...), media_type="multipart/x-mixed-replace; boundary=frame")`, release in `finally`.
4. API.md rate-limit row: 4 → 12 concurrent per client IP (D1).

**Acceptance:**
- [ ] Multipart parts parse to intact JPEGs; error recovery per API.md.
- [ ] Cap returns the standard `503 NO_CAPACITY` envelope, slot released after close.
- [ ] 501 stub and its test are gone.

**Checkpoint A:** backend contract (4.1–4.3) green, API.md synced. **Commit:** `feat(api): mjpeg live stream with a bounded per-ip slot cap`

## Task 4.4 — Event thumbnail route

**Modify:** `routers/events.py`, `docs/API.md`, `test_api_events.py`.

**Steps:** failing tests (`test_thumbnail_serves_file` — write bytes to the event's `thumbnail_path` under the events dir first; `test_thumbnail_404_when_absent`; `test_thumbnail_cross_tenant_404`); implement `GET /events/{event_id}/thumbnail` → `FileResponse` when path exists **and** resolves inside the configured events root (path-traversal defence, SECURITY §6.2), else 404. API.md table gains the row (D8).

**Acceptance:**
- [ ] Serves the stored still; 404 when Phase 5 hasn't written one; cross-tenant 404.
- [ ] A `thumbnail_path` pointing outside the events root is 404, not served.

**Gate:** backend loop. **Commit:** `feat(api): serve event thumbnails through the opaque url contract`

## Task 4.5 — ROI survives resolution change

**New:** `backend/tests/test_rois.py`.

**Steps:** failing test `test_roi_survives_resolution_change`: create a camera (640×360) + ROI with normalised points; simulate a sub-stream switch by updating `frame_width/height` **through the repository** (`CameraPatch` deliberately excludes these pipeline-written fields); assert the stored `points` are byte-identical, `coverage_pct` unchanged, and a physical point at the same relative position still evaluates `in_roi` the same through `rules.evaluate` at both frame sizes (centroid computed from each size's pixels).

**Acceptance:**
- [ ] Verification-matrix row exists and passes (spec §12: Phase 4).
- [ ] Test fails only if normalisation regressions are introduced (mutation check: temporarily denormalise → red).

**Gate:** backend loop. **Commit:** `test(rois): normalised zones survive a resolution change`

## Task 4.6 — Tokens + Vitest + CI

**Modify:** `frontend/src/style.css`, `frontend/package.json`, `frontend/vitest.config.js` (new), `frontend/src/__tests__/` (new), `.github/workflows/ci.yml`.

**Steps:**
1. Port design §2 tokens into `:root` (colours, radius, motion) + Tailwind v4 `@theme` mapping; keep `App.vue` scaffold rendering.
2. `npm i -D vitest @vue/test-utils jsdom`; script `"test": "vitest run"`; first test: token presence + a mount smoke of `App.vue`.
3. CI frontend job: add `npm run test` step after lint (before build).

**Acceptance:**
- [ ] `npm test` green locally and in CI; no hardcoded hex added.
- [ ] `npm run build` still green.

**Gate:** frontend loop. **Commit:** `chore(frontend): design tokens and vitest wired into the gate`

## Task 4.7 — API client

**New:** `frontend/src/api/client.js`, `frontend/src/api/token.js`, `frontend/src/__tests__/client.spec.js`.

**Tests (mocked `fetch`):**
- every request carries `X-CambBrain-Client` + `Authorization` when a token is set; bodies are JSON.
- error envelope → `ApiError` with `code/message/field/status/correlationId`.
- `401` → one refresh (single-flight: two parallel 401s trigger one refresh) → retried request succeeds.
- refresh rejected → `onAuthError` fired, token cleared.
- `raw()` returns bytes for snapshot/thumbnail (no JSON parse).

**Acceptance:**
- [ ] Token module holds access/refresh in module memory only (grep: no `localStorage`).
- [ ] Every API-boundary function has a JSDoc typedef (design §9 mitigation).

**Gate:** frontend loop. **Commit:** `feat(frontend): api client with envelope errors and single-flight refresh`

## Task 4.8 — Auth store, guards, Login, RoleGate

**New/modify:** `src/stores/auth.js`, `src/router.js`, `src/auth/LoginForm.vue`, `src/auth/AuthGuard.js`, `src/auth/RoleGate.vue`, tests.

**Tests:**
- unauthenticated navigation → `/login`; authenticated `/login` → `/cameras`.
- `role=viewer` on `/settings/users` → redirected to `/cameras`; `admin` passes.
- login success stores user + tokens; `401` shows "Check your username and password."; `423` shows the lockout message; `429` rate-limit message — **never which field was wrong** (design §7).
- reload hydration: `/auth/me` failure → logout to `/login`.

**Acceptance:**
- [ ] Routes per design §3 (all eight paths registered; placeholder views allowed until their tasks).
- [ ] Viewer: nav item absent **and** guard rejects (defence in depth, API.md §5).

**Gate:** frontend loop. **Commit:** `feat(frontend): login, session hydration, and route guards`

## Task 4.9 — AppShell · Sidebar · TopBar · StatusBar

**New:** `src/layout/AppShell.vue`, `Sidebar.vue`, `TopBar.vue`, `StatusBar.vue`, tests.

**Tests:**
- sidebar renders Cameras/Events + Users/System only for admin; collapse class below 1024px (matchMedia mock).
- StatusBar polls `/system/status` on an interval, renders online·offline counts + avg FPS; interval cleared on unmount.
- AppShell exposes a persistent `aria-live="polite"` region (used by 4.10's ticker).
- TopBar shows site name from the auth store.

**Acceptance:**
- [ ] Shell wraps `router-view`; reduced-motion media query disables transitions.

**Gate:** frontend loop. **Commit:** `feat(frontend): app shell with role-aware nav and status polling`

## Task 4.10 — MJPEG client + CameraGrid + CameraTile + ticker

**New:** `src/api/mjpeg.js`, `src/camera/CameraGrid.vue`, `CameraTile.vue`, `EventTicker.vue`, `src/stores/cameras.js`, `src/stores/events.js`, tests.

**Tests — `mjpeg.spec.js` (byte vectors fixed in plan):**
- single-chunk frame → one `onFrame`; boundary split across chunks → still one frame; JPEG split across chunks → buffered until complete; garbage between parts → skipped, parser resyncs; `503` → `onError("capacity")`; `AbortController` abort stops reads (no further callbacks).

**Tests — components:**
- grid: N cameras → N tiles + add tile (admin only); `grid-template-columns: repeat(auto-fill, minmax(320px, 1fr))` class present; 16:9 aspect class present.
- tile state machine: `starting` until first frame → `live`; stream `onError` → `error` with Retry button (retry re-opens the stream); `camera.enabled=false` or `last_error` → `offline` dimmed + last-seen; **text status in every state** (design §11: colour never sole signal).
- ticker: polls `/events?limit=5&sort=-started_at` every 10s, newest first, cap 5, click → `/events/:id`, renders into the shell's `aria-live` region; poll stops on unmount.

**Acceptance:**
- [ ] Live tiles play through the fetch parser with the in-memory Bearer (D3) — demo via MCP browser at the checkpoint.
- [ ] Opening 5+ tiles: cap 12 means no `NO_CAPACITY`; a forced 503 shows the error state, not a blank tile.

**Checkpoint B:** login → grid → add camera → live tile works (needs 4.11). **Gate:** frontend loop. **Commit:** `feat(frontend): live mjpeg grid with per-tile states and event ticker`

## Task 4.11 — AddCameraDialog + ConnectionTest

**New:** `src/camera/AddCameraDialog.vue`, `src/camera/ConnectionTest.vue`, tests.

**Tests:**
- form fields match `CameraCreate` payload (`name, rtsp_url, username, password, enabled, sample_fps, motion_threshold`); `sample_fps` bounded 2–5.
- test button disabled until URL present; shows spinner state; success renders `Connected. 640×360 @ 10 fps.` style line with dims/fps/latency.
- `error_code` → copy table (all six): `AUTH_FAILED` "Check the username and password." etc; `ok:false` never treated as HTTP failure.
- create → dialog closes, tile appears in grid; `422` field error renders inline on the offending field; envelope `404/403` surfaces message.
- viewer: add tile hidden (RoleGate), dialog not reachable.

**Acceptance:**
- [ ] A failing connection shows the actual reason (spec §8 / design §8 — the load-bearing diagnostic).
- [ ] Password never echoed back (response has `has_password` only).

**Checkpoint B (done with 4.10):** core "configure a camera" path live. **Gate:** frontend loop. **Commit:** `feat(frontend): add-camera dialog with real connection diagnostics`

## Task 4.12 — Camera detail + rules editor

**New:** `src/camera/CameraDetail.vue`, `CameraCard.vue`, `src/rules/RulesList.vue`, `RuleForm.vue`, `src/data/coco.js` (80 names, ordered), tests.

**Tests:**
- CameraCard: enabled switch → `PATCH {enabled}`; edit name/sample_fps; delete confirm → `DELETE`, navigate back; viewer sees no mutating controls.
- RuleForm validation mirrors API.md: classes non-empty + COCO names only; confidence 0–1; cooldown 5–86400; ≤4 active-hours windows; `start<end` or wrap (`end<start`); `roi_id` must be one of the camera's ROIs.
- payload shape equals the API.md request example (deep-equal on a filled form).
- windows editor: add/remove rows; a `22:00 → 06:00` row saves unchanged (midnight wrap survives round-trip).
- RulesList: per-camera rules with severity badge; create/patch/delete happy paths (mocked client); soft delete note ("rule kept for history").

**Acceptance:**
- [ ] A rule can be created end-to-end against the real API contract (mocked fetch, payload asserted).
- [ ] Default classes = `["person"]` (design §5.7 — noise control by default).

**Gate:** frontend loop. **Commit:** `feat(frontend): camera detail and per-camera rules editor`

## Task 4.13 — Rule diagnostics panel

**New:** `src/rules/RuleDiagnostics.vue`, tests.

**Tests:**
- "Run test" → `POST /rules/{id}/test` (no body → most recent event); optional event picker (`GET /events?camera_id=`).
- renders `fired` banner + all `checks` rows: condition name, pass/fail **icon + text** (not colour alone), `detail` verbatim (e.g. `centroid (0.41,0.62) outside Loading dock`).
- `404` (no event yet) → empty-state copy "No detections recorded yet — run the camera and try again."
- `422` frame-size message shown as-is.

**Acceptance:**
- [ ] The Phase 3 endpoint is reachable from the UI with per-condition reasons visible.

**Gate:** frontend loop. **Commit:** `feat(frontend): rule diagnostics from the replay endpoint`

## Task 4.14 — ROI geometry + RoiCanvas

**New:** `src/roi/geometry.js`, `src/roi/RoiCanvas.vue`, `src/roi/VertexHandle.vue`, tests.

**`geometry.js` (pure, plan-fixed tests):**
- `toPixels(pt, w, h)` / `fromPixels(px, w, h)` round-trip within 1e-9; clamp to [0,1].
- `coveragePct(points)` — shoelace; unit square = 100; known quad = expected.
- `minAreaPx(points, w, h)` — 500px² threshold helper (design §5.5).
- `pointInPolygon` (edge-inclusive, matching backend `roi.py`) for drag hit-testing.

**`RoiCanvas.vue` tests:**
- renders the frozen snapshot (blob URL from `POST /snapshot`) + SVG overlay scaled to displayed size; aspect mismatch letterboxes (display matrix mirrors `LetterboxMeta` semantics).
- draw: click adds vertex; `<3` vertices → Enter does nothing (min-3 at draw time, design §5.4); 4th click on first vertex or Enter closes; Esc cancels whole draft.
- drag: pointerdown on vertex moves it; coordinates converted through `fromPixels` — emitted polygon is normalised.
- min-area: closing under 500px² at source resolution → blocked with explanation, draft stays open.
- keyboard: Tab/arrow-focus a vertex, arrows nudge 1px, Shift+arrows 10px, Enter closes, Esc cancels (design §11).

**Acceptance:**
- [ ] Only normalised coordinates ever leave the component (assert emitted payload ∈ [0,1]).
- [ ] Geometry unit tests cover round-trip, coverage, min-area, edge-inclusive containment.

**Gate:** frontend loop. **Commit:** `feat(frontend): roi canvas draws on a frozen snapshot in normalised space`

## Task 4.15 — ZoneList + coverage + class filter + save/cancel

**New:** `src/roi/ZoneList.vue`, `src/roi/ClassFilter.vue`, `src/roi/RoiEditor.vue`, tests.

**Tests:**
- ZoneList always visible (not behind an edit mode); select/duplicate/delete zone; coverage % per zone from `coveragePct`; >80% coverage → warning (nearly-the-whole-frame mistake, API.md).
- ClassFilter: COCO checkbox list, default `person`; disabled zone still saves filter.
- Save: `POST`/`PATCH` with **full** point list (API.md destructive-edit rule); normalised round-trip unchanged; success replaces local draft state.
- Cancel/blur: restores last-saved state; dirty marker while unsaved (design §5.9: nothing commits until Save).
- Resolution-change sanity: opening the editor at 640×360 vs 1920×1080 snapshot emits identical normalised points for the same clicks (component-level companion to 4.5).

**Acceptance:**
- [ ] Save/Cancel semantics hold (no destructive-on-blur).
- [ ] Coverage + class filter visible per zone without entering a mode.

**Checkpoint C (with 4.14):** ROI editor complete — gate demo candidate. **Gate:** frontend loop. **Commit:** `feat(frontend): zone list, coverage, and explicit save/cancel for roi`

## Task 4.16 — Event log + detail

**New:** `src/events/EventTable.vue`, `EventRow.vue`, `EventDetail.vue`, `DetectionOverlay.vue`, `EventFilters.vue`, `src/views/EventsView.vue`, `EventDetailView.vue`, tests.

**Tests:**
- filters build the API query exactly (`camera_id, severity, from, to, acknowledged, q, limit, offset, sort=-started_at`); reset clears.
- table: severity badge colour **+** text; thumbnail `img` src = `thumbnail_url`; `404` on thumbnail → placeholder icon (Phase 5 writes stills).
- bulk acknowledge: checkbox selection → `POST /events/acknowledge-bulk` payload `{event_ids}`; row reflects `acknowledged`.
- pagination: offset stepping against `total`.
- detail: detections overlay draws each `bbox` scaled onto the still using `camera.frame_width/height`; detection list (class, confidence, zone); ack button; `has_clip=false` → clip section hidden with "Clip available after recording (Phase 5)" note; `has_clip=true` → `<video>` with `clip_url`.
- empty state copy (designed state — no events until Phase 5).

**Acceptance:**
- [ ] Every filter maps to its documented query param; overlay coordinates scale correctly at two frame sizes.
- [ ] Cross-check: `thumbnail_url`/`clip_url` used verbatim (opaque URLs — client never builds paths).

**Gate:** frontend loop. **Commit:** `feat(frontend): event log with filters, bulk acknowledge, and detection overlay`

## Task 4.17 — Settings pages

**New:** `src/settings/UsersView.vue`, `SystemView.vue`, tests.

**Tests:**
- Users: list from `GET /users`; create form (username/email/role) → `POST`; delete confirm → `DELETE`; `409` last-admin → inline conflict message (API.md); role select admin/viewer only; viewer never reaches the view (guard already proven in 4.8 — assert nav hidden here).
- System: renders `/system/status` fixture — tier, hardware rows, model, disk %, per-camera stats; `GET /system/health` unauthenticated ping shown as service status.
- Notifiers UI **not** built (Phase 5 — Telegram wiring); System page shows model/tier/storage only.

**Acceptance:**
- [ ] Both sidebar destinations render real data; last-admin protection is visible in the UI, not just the API.

**Gate:** frontend loop. **Commit:** `feat(frontend): users admin and system status pages`

## Task 4.18 — Accessibility pass, full gate, living docs, PR

**Steps:**
1. **A11y sweep** (design §11) with tests where cheap: every button/input reachable + visible focus ring class; ticker `aria-live`; `prefers-reduced-motion` disables transitions (CSS test); severity/status never colour-only (assert text present); contrast: audit token pairs against 4.5:1 / 3:1, adjust tokens if needed.
2. **docs/tasks.md:** tick every delivered Phase 4 row; **add two rows** under Phase 4 — `[ ] Rules editor on camera detail` and `[ ] Settings pages — Users (admin) + System status` — and tick them (D5).
3. **API.md:** confirm amendments 1–3 (snapshot, cap row, thumbnail) match shipped code; openapi spec test green.
4. **Full gate:** backend four commands + frontend four commands; record every row in the execution ledger above with evidence + commit SHAs.
5. Commit `docs(phase-4): record gate evidence and tick phase 4 tasks`; push; open PR → **wait for PR-Agent; apply its suggestions; merge only after it passes**; delete the branch on GitHub (and merged leftovers).
6. **Human gate demo** via MCP browser: login → add camera (watch a real failure reason) → live tile → draw zone → rule with diagnostics → event log. Record walkthrough in the ledger.

**Acceptance:**
- [ ] Everything in the Gate section green with recorded evidence.
- [ ] PR-Agent passes with suggestions applied; PR merged; branch deleted.

**Commit:** `docs(phase-4): record gate evidence and tick phase 4 tasks`