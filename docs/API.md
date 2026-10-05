# CamBrain — API Specification

> Living document. FastAPI REST + WebSocket, served on `127.0.0.1:8765`.
> Related: [architecture.md](architecture.md) · [SECURITY.md](SECURITY.md) · [DATABASE.md](DATABASE.md)

---

## 1. Design rules

| Rule | Rationale |
|---|---|
| Base path `/api/v1` | Versioning without breaking the Tauri shell |
| **Every route requires auth** | Anyone on the LAN can reach the port — see [prd.md §7](prd.md) |
| `site_id` never accepted from the client | Taken from the token; client-supplied is an IDOR — [SECURITY.md §4.3](SECURITY.md) |
| Secrets never returned | `password` is always masked; `GET` cannot leak |
| Mutating requests need `Content-Type: application/json` + `X-CambBrain-Client` | Forces a CORS preflight, blocking CSRF from a malicious page |
| Errors share one envelope | Frontend handles one shape instead of six |
| Soft delete for rules; hard delete for sites | Config must survive a mistaken rule deletion |
| Bulk endpoints capped | One request must not pin the box |

**No CORS wildcard, ever.** The allowlist is localhost origins only, and is configured, not inferred.

---

## 2. Endpoints

### Auth

| Method | Path | Role | Purpose |
|---|---|---|---|
| `POST` | `/api/v1/auth/login` | — | Exchange credentials for tokens |
| `POST` | `/api/v1/auth/refresh` | — | Rotate refresh token |
| `POST` | `/api/v1/auth/logout` | any | Revoke session |
| `GET` | `/api/v1/auth/me` | any | Current user, site, permissions |
| `POST` | `/api/v1/auth/change-password` | any | |

`POST /api/v1/auth/login`

```json
// Request
{
  "username": "ramesh",
  "password": "correct-horse-battery"
}

// Response 200
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "refresh_token": "b8f2...  ",
  "token_type": "bearer",
  "expires_in": 43200,
  "user": {
    "id": 1,
    "username": "ramesh",
    "role": "admin",
    "site": { "id": 1, "name": "Dhanraj Complex", "timezone": "Asia/Kolkata" }
  }
}
```

| Status | Meaning |
|---|---|
| `401` | Bad credentials |
| `423` | Locked out after repeated failures — distinct from `401` so the UI can say "try again in 12 minutes" |
| `429` | Rate limited |
| `200` | Token **never** echoes the site list; one site per session |

**`POST /api/v1/auth/refresh`** rotates the refresh token and returns a new pair. Presenting an already-rotated token revokes the entire family — that is how token theft is detected.

---

### Cameras

| Method | Path | Role |
|---|---|---|
| `GET` | `/api/v1/cameras` | any |
| `POST` | `/api/v1/cameras` | admin |
| `GET` | `/api/v1/cameras/{id}` | any |
| `PATCH` | `/api/v1/cameras/{id}` | admin |
| `DELETE` | `/api/v1/cameras/{id}` | admin |
| `POST` | `/api/v1/cameras/{id}/test` | admin |
| `POST` | `/api/v1/cameras/{id}/snapshot` | any |
| `GET` | `/api/v1/cameras/{id}/stream` | any |

`POST /api/v1/cameras`

```json
// Request
{
  "name": "Back door",
  "rtsp_url": "rtsp://10.0.0.5:554/Streaming/Channels/101",
  "username": "admin",
  "password": "secret123",
  "enabled": true,
  "sample_fps": 2.0,
  "motion_threshold": 0.02
}

// Response 201
{
  "id": 4,
  "name": "Back door",
  "rtsp_url": "rtsp://10.0.0.5:554/Streaming/Channels/101",
  "has_password": true,
  "password": "••••••••",
  "enabled": true,
  "sample_fps": 2.0,
  "motion_threshold": 0.02,
  "frame_width": 640,
  "frame_height": 360,
  "status": "starting",
  "last_error": null,
  "created_at": "2026-10-05T14:02:11Z"
}
```

**The response never contains `username` or the real password.** `has_password` drives the UI's "configured / not set" indicator without exposing anything.

**PATCH semantics:** omitting `password` leaves it unchanged; `"password": null` clears it. `""` is rejected — an empty password on a camera is almost always a mistake, not an intent.

`POST /api/v1/cameras/{id}/test`

Opens a short-lived connection, reads up to 10 frames, closes it.

```json
// Response 200
{
  "ok": true,
  "message": "Connected. 640×360 @ 10 fps.",
  "latency_ms": 42,
  "frame_width": 640,
  "frame_height": 360,
  "fps": 10.2
}

// Response 200 — reachable but not usable
{
  "ok": false,
  "message": "Authentication failed. Check the username and password.",
  "error_code": "AUTH_FAILED"
}

// Response 200 — unreachable
{
  "ok": false,
  "message": "Could not connect on rtsp://10.0.0.5:554/… after 5 attempts over 12s.",
  "error_code": "CONNECT_TIMEOUT"
}
```

**This endpoint returns `200` with `ok: false`, not an HTTP error.** Failing to reach a camera is an expected outcome of a diagnostic, not a client error — and the whole value of the endpoint is the `error_code` telling the installer which of six problems they have.

`error_code` ∈ `AUTH_FAILED` · `CONNECT_TIMEOUT` · `HOST_UNREACHABLE` · `NO_SUCH_STREAM` · `DECODE_FAILED` · `CANCELLED`

> The brief anticipated "easy setup wizard … that tells the user exactly what's wrong." This endpoint is where that lives. **Add-camera is the product's first impression** — it has to fail usefully.

`GET /api/v1/cameras/{id}/stream`

`multipart/x-mixed-replace; boundary=frame`. On stream error, emits a zero-length part so the client re-reads the next header. Rate limited to 4 concurrent streams per session. See [memory.md](memory.md) for why MJPEG and not WebRTC.

---

### ROIs

| Method | Path | Role |
|---|---|---|
| `GET` | `/api/v1/cameras/{id}/rois` | any |
| `POST` | `/api/v1/cameras/{id}/rois` | admin |
| `GET` | `/api/v1/rois/{id}` | any |
| `PATCH` | `/api/v1/rois/{id}` | admin |
| `DELETE` | `/api/v1/rois/{id}` | admin |

```json
// Request — normalised coordinates
{
  "name": "Loading dock",
  "points": [[0.62, 0.41], [0.88, 0.38], [0.91, 0.74], [0.59, 0.77]],
  "class_filter": ["person", "truck"],
  "active": true
}

// Response 201
{
  "id": 3,
  "camera_id": 4,
  "name": "Loading dock",
  "points": [[0.62, 0.41], [0.88, 0.38], [0.91, 0.74], [0.59, 0.77]],
  "coverage_pct": 11.4,
  "vertex_count": 4,
  "class_filter": ["person", "truck"],
  "active": true,
  "created_at": "2026-10-05T14:09:02Z"
}
```

`coverage_pct` is computed from the polygon's area against frame area, so the UI can warn about a ROI that is nearly the whole frame — a common mistake that produces exactly the alert noise the product exists to prevent.

Coordinates must be `0.0 ≤ x,y ≤ 1.0`. Out-of-range is `422`. **Normalised, not pixels** — a ROI drawn on one resolution must stay correct if the stream changes. See [DATABASE.md §4.5](DATABASE.md).

**Destructive edit:** shrinking a polygon can orphan vertices. The API requires the full point list on every `PATCH` — partial vertex edits are rejected, so the client always holds the authoritative shape.

---

### Rules

| Method | Path | Role |
|---|---|---|
| `GET` | `/api/v1/cameras/{id}/rules` | any |
| `GET` | `/api/v1/rules` | any — site-wide, filtered |
| `POST` | `/api/v1/cameras/{id}/rules` | admin |
| `GET` | `/api/v1/rules/{id}` | any |
| `PATCH` | `/api/v1/rules/{id}` | admin |
| `DELETE` | `/api/v1/rules/{id}` | admin | Soft — `deleted_at` set |
| `POST` | `/api/v1/rules/{id}/test` | admin |

```json
// Request
{
  "name": "Back door after hours",
  "roi_id": 3,
  "classes": ["person"],
  "confidence_threshold": 0.55,
  "cooldown_seconds": 60,
  "active_hours": {
    "timezone": "Asia/Kolkata",
    "windows": [{ "start": "22:00", "end": "06:00" }]
  },
  "severity": "critical",
  "notify": true
}
```

Validation:

| Field | Rule |
|---|---|
| `classes` | Non-empty; each must be a valid COCO name; **names not indices** |
| `confidence_threshold` | `0.0–1.0` |
| `cooldown_seconds` | `5–86400` |
| `active_hours.windows` | `start < end` within a window, or `end < start` for a wrap past midnight; max 4 windows |
| `roi_id` | Must belong to the same camera; otherwise `422` |

Class names rather than indices, because YOLOX and RT-DETR do not share an output ordering — storing indices would silently repoint every rule at the wrong class when the model changes in Phase 3. See [DATABASE.md §4.6](DATABASE.md).

**Windows crossing midnight** (`22:00` → `06:00`) are explicitly supported. The naive `start < end` check would reject exactly the rule a shop owner actually needs.

`DELETE` is soft. **Events reference the rule that fired them** — a hard delete would leave an event log with orphaned attributions, and the owner's history would quietly lose meaning.

`POST /api/v1/rules/{id}/test`

Replays a supplied still or the most recent event through the rules engine and returns the outcome with per-condition results, so a rule that isn't firing can be diagnosed without waiting for real motion.

```json
{
  "rule_id": 3,
  "fired": false,
  "checks": [
    { "condition": "class_in_allowlist", "passed": true,  "detail": "'car' not in ['person']" },
    { "condition": "confidence",        "passed": true,  "detail": "0.71 >= 0.55" },
    { "condition": "in_roi",            "passed": false, "detail": "centroid (0.41,0.62) outside Loading dock" },
    { "condition": "active_hours",      "passed": false, "detail": "14:32 is outside 22:00–06:00" },
    { "condition": "cooldown",          "passed": true,  "detail": "no recent trigger on this track" }
  ]
}
```

**This is the debug view the rules engine is designed to have.** A binary "rule didn't fire" is unactionable; per-condition reasons tell the owner whether to widen the ROI, lower the threshold, or accept that it is 2:30pm.

---

### Events

| Method | Path | Role |
|---|---|---|
| `GET` | `/api/v1/events` | any |
| `GET` | `/api/v1/events/{id}` | any |
| `POST` | `/api/v1/events/{id}/acknowledge` | any |
| `POST` | `/api/v1/events/acknowledge-bulk` | any |
| `GET` | `/api/v1/events/{id}/clip` | any |
| `GET` | `/api/v1/events/stats` | any |

`GET /api/v1/events`

```
?camera_id=4&severity=critical&from=2026-10-01T00:00:00Z
&to=2026-10-08T00:00:00Z&acknowledged=false&q=loading
&limit=50&offset=0&sort=-started_at
```

```json
// Response 200
{
  "items": [
    {
      "id": 812,
      "camera": { "id": 4, "name": "Back door" },
      "rule": { "id": 3, "name": "Back door after hours" },
      "severity": "critical",
      "summary": "1 person in Loading dock",
      "started_at": "2026-10-05T21:14:33Z",
      "ended_at": "2026-10-05T21:14:51Z",
      "duration_ms": 18400,
      "acknowledged": false,
      "has_clip": true,
      "thumbnail_url": "/api/v1/events/812/thumbnail",
      "clip_url": "/api/v1/events/812/clip",
      "detections": [
        { "class_name": "person", "confidence": 0.71,
          "bbox": [412, 188, 468, 366], "zone_name": "Loading dock" }
      ]
    }
  ],
  "total": 137,
  "limit": 50,
  "offset": 0
}
```

`limit` capped at 200. Pagination is offset-based, which suits an event log that is read forwards and bounded at a few thousand rows by retention — a cursor would be more correct at unbounded scale, and it isn't a problem here.

**`thumbnail_url` and `clip_url` are opaque URLs resolved by event id.** The client never constructs or sends a filesystem path — that is the path-traversal defence in [SECURITY.md §6.2](SECURITY.md).

`GET /api/v1/events/{id}/clip` streams with `Content-Disposition: inline` and supports `Range`, so the browser can seek without downloading the whole file. Returns `404` when the clip was deleted by retention or never written because the disk quota refused it.

`GET /api/v1/events/stats` returns counts by day, camera, and severity for the dashboard header.

---

### Users, settings, system

| Method | Path | Role |
|---|---|---|
| `GET` `POST` | `/api/v1/users` | admin |
| `PATCH` `DELETE` | `/api/v1/users/{id}` | admin |
| `GET` `PATCH` | `/api/v1/settings` | any / admin |
| `GET` `POST` `PATCH` `DELETE` | `/api/v1/notifiers` | any / admin |
| `POST` | `/api/v1/notifiers/test` | admin |
| `GET` | `/api/v1/system/status` | any |
| `GET` | `/api/v1/system/health` | any |
| `GET` `POST` | `/api/v1/system/config` | admin |

**A user cannot demote or delete the last remaining admin** — `409`. Locking yourself out of your own box is a support call, and it is preventable in two lines.

`GET /api/v1/system/health` needs no auth: it exposes only `{status, version, uptime_s}` and is for the Tauri shell and the installer to poll.

`GET /api/v1/system/status`

```json
{
  "version": "0.1.0",
  "hardware_tier": "medium",
  "hardware": {
    "cpu_cores": 4,
    "avx2": true,
    "vnni": true,
    "ram_total_mb": 8002,
    "ram_used_mb": 1740,
    "disk_total_gb": 119,
    "disk_used_pct": 31
  },
  "model": { "name": "yolox_s.onnx", "tier": "medium", "input": [640, 640] },
  "cameras": [
    { "id": 4, "name": "Back door", "status": "live", "fps": 10.2,
      "frames_processed": 184203, "inferences": 9120, "last_frame_at": "2026-10-05T21:14:51Z" },
    { "id": 5, "name": "Front counter", "status": "offline",
      "last_error": "Could not connect to rtsp://10.0.0.6:554/… — authentication failed",
      "last_frame_at": "2026-10-05T19:02:14Z" }
  ],
  "stats": { "events_today": 6, "alerts_sent": 6, "alerts_failed": 1 }
}
```

`hardware_tier` is what [architecture.md §6](architecture.md) calls the detected capability tier. Surfacing it removes "why is it slow?" as a support question.

`POST /api/v1/notifiers/test` sends a real test message and returns Telegram's response verbatim. A notifier config that has never delivered is not a working notifier.

---

## 3. WebSocket

### `GET /api/v1/ws/alerts`

Token via `Sec-WebSocket-Protocol` (`cambrain.jwt.<token>`) or the first `message`, **not** a query parameter — URLs leak into logs, proxy caches, and browser history.

```json
// Server → client
{
  "type": "event",
  "data": {
    "id": 812,
    "camera": { "id": 4, "name": "Back door" },
    "severity": "critical",
    "summary": "1 person in Loading dock",
    "started_at": "2026-10-05T21:14:33Z",
    "has_clip": true
  }
}

// Server → client
{ "type": "camera_status", "data": { "camera_id": 5, "status": "offline",
                                     "last_error": "…authentication failed" } }

// Server → client
{ "type": "heartbeat", "data": { "ts": "2026-10-05T21:14:55Z" } }
```

Server → client only. The socket carries alerts and status; all mutations go over HTTP, where they are authenticated, validated, rate-limited, and auditable. A WebSocket that mutates state is a WebSocket nobody tests.

Heartbeat every 30s keeps proxies from idling the connection out. Client reconnects with jittered backoff, 1s → 30s, and **resyncs via a full `GET /events?since=` on reconnect** rather than trusting the socket for completeness — a dropped socket must not silently lose events, since the durable record is in the database.

### `GET /api/v1/ws/frames`

Per-camera JPEG frames for the live grid, multiplexed:

```json
{ "type": "frame", "camera_id": 4, "seq": 18422,
  "jpeg": "<base64>", "ts": "2026-10-05T21:14:55Z" }
```

`seq` is monotonic per camera; the client drops out-of-order frames. **At 8 cameras this stream is the main CPU cost in the dashboard** — capture throttles to the configured `sample_fps` (2–5), not the camera's native 10–15.

`GET /api/v1/cameras/{id}/stream` (MJPEG multipart) remains the default for the focused single-camera view. MJPEG does not require WebRTC (see [memory.md](memory.md)), and the base64-in-JSON framing above is deliberately simple to avoid pulling a codec into the frontend.

---

## 4. Error envelope

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "confidence_threshold must be between 0 and 1.",
    "field": "confidence_threshold",
    "correlation_id": "a3f9c2e1"
  }
}
```

| Status | `code` | When |
|---|---|---|
| `400` | `BAD_REQUEST` | Malformed request |
| `401` | `UNAUTHENTICATED` | Missing or invalid token |
| `403` | `FORBIDDEN` | Authenticated, insufficient role |
| `404` | `NOT_FOUND` | Missing, **or belongs to another site** |
| `409` | `CONFLICT` | Duplicate username; last-admin protection |
| `422` | `VALIDATION_ERROR` | Pydantic validation failure |
| `423` | `ACCOUNT_LOCKED` | Login lockout |
| `429` | `RATE_LIMITED` | Includes `Retry-After` |
| `500` | `INTERNAL` | Correlation id, no detail |
| `503` | `NO_CAPACITY` | Too many concurrent streams |

**Cross-tenant access returns `404`, never `403`.** A `403` confirms the row exists — an enumeration oracle. Tests assert this on every entity route.

Internal errors return a generic message plus a correlation id; the full trace goes to the log under the same id. See [SECURITY.md §7.4](SECURITY.md).

---

## 5. Auth mechanism

- **Access token:** JWT `HS256`, 12h, sent as `Authorization: Bearer <token>`.
- **Refresh token:** 7d opaque string, stored hashed in `sessions`, rotated on use, reuse detection revokes the family.
- **The access token lives in memory in the frontend, never `localStorage`.** An XSS bug should not yield a persistent credential.
- **Requests require `X-CambBrain-Client`; mutating requests require `Content-Type: application/json`.** Both force a CORS preflight, so a malicious page on the LAN cannot drive the API. See [SECURITY.md §4.5](SECURITY.md).
- **Origin/Referer validated** against a localhost allowlist. No wildcard, ever.
- **`403` on insufficient role; the UI's `RoleGate` is presentation, not a control.**

---

## 6. Rate limits

Per client IP, fixed window.

| Route | Limit |
|---|---|
| `POST /auth/login` | 5/min per username, then exponential lockout |
| `POST /auth/refresh` | 30/min |
| `POST /cameras/{id}/test` | 10/min — each opens a real RTSP connection |
| `GET /cameras/{id}/stream` | 4 concurrent per session |
| `GET /ws/frames` | 10 fps subscribe rate |
| Everything else | 120/min |

A camera-test rate limit is a hardware-protection limit, not a security formality: ten concurrent RTSP probes on a weak customer switch is a self-inflicted outage.

---

## 7. OpenAPI

Served at `/api/v1/openapi.json` with docs at `/api/v1/docs`.

**The spec is generated from the implementation and must match it.** Phase 2 has a test asserting the endpoint list and the [DATABASE.md](DATABASE.md) schema agree; a spec that describes endpoints the code doesn't have is worse than none, because it is trusted.

---

## 8. API checklist per endpoint

- [ ] Auth dependency applied
- [ ] Role requirement declared
- [ ] `site_id` scoped from the token, never the body
- [ ] Cross-tenant access returns `404`
- [ ] No secret in any response
- [ ] Pydantic bounds on every numeric and collection field
- [ ] Tenant-scoped index supports the query
- [ ] Rate limit where the endpoint is expensive
- [ ] Audit-logged if it changes configuration
- [ ] Listed in the OpenAPI spec and the endpoint-list test
- [ ] Works offline, with no internet reachable