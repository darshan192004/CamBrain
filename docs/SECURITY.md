# CamBrain — Security & Privacy Specification

> Living document. Review before every release.
> Related: [rules.md §8](rules.md) · [DATABASE.md](DATABASE.md) · [API.md](API.md)

---

## 1. Threat model

### What we are defending against

| # | Threat | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| T1 | Someone on the shop LAN reconfigures cameras or disables alerts | **High** | Critical | Authentication mandatory on every route; no trusted-LAN exemption |
| T2 | RTSP / camera / Telegram credentials leaking from disk | Medium | Critical | Encrypted at rest; OS-protected key; never logged |
| T3 | Secrets leaking into log files | **High** | High | Redaction enforced in the log formatter, not by discipline |
| T4 | Network attacker reading dashboard traffic on the LAN | Low | Critical | Bind localhost-only by default; TLS for non-localhost binding |
| T5 | Stolen laptop / disk image yields footage or config | Low | High | Full-disk encryption is the customer's OS job; secrets are DPAPI-wrapped regardless |
| T6 | Malicious RTSP server pushing crafted decoder payloads | Low | High | PyAV/FFmpeg kept patched; decode confined to a subprocess later |
| T7 | Path traversal via clip filename or camera name | Low | High | All filesystem paths constructed from IDs, never from user-supplied strings |
| T8 | Unbounded disk growth exhausting the box | Medium | Medium | Retention + quota; clip writer refuses past cap |
| T9 | Compromised update channel | Low | Critical | Model fetch is checksum-pinned; no auto-update in MVP |
| T10 | CSRF against the local API from a malicious web page | Medium | High | Same-origin enforcement + custom header requirement |

### Explicitly out of scope for MVP

Physical access to the box · local privilege escalation on the customer's Windows host · attacks on the customer's NVR · DDoS from the internet (no inbound exposure) · malware distribution.

---

## 2. The trust boundary

```
  INTERNET                    │  CUSTOMER LAN              │  THIS PROCESS
  ────────────────────────────┼───────────────────────────┼───────────────────
  Telegram Bot API  ──HTTPS──▶│                           │
                              │  Browser ──▶ 127.0.0.1    │
  Anything else      ✗ blocked │            :8765          │
                              │                           │
                              │   RTSP ──▶ cameras        │
                              │   (credentials in,       │
                              │    frames in)             │
```

**Exactly one outbound destination: the configured notifier.** No telemetry, no crash reporting, no update ping, no licence-check phone-home. CamBrain works fully offline; only alert delivery fails.

**Default bind: `127.0.0.1` only.** Binding to `0.0.0.0` requires an explicit `CAMBRAIN_BIND_ALL=1`, and doing so logs a WARN at startup. The Tauri shell proxies `localhost` → the local engine.

---

## 3. Credential storage

### 3.1 What is secret

RTSP usernames and passwords · camera/NVR passwords · Telegram bot tokens · WhatsApp tokens · JWT signing key · Fernet master key · any `notifier` API key.

### 3.2 Encryption at rest

**Fernet** (AES-128-CBC + HMAC-SHA256, authenticated) via the `cryptography` library.

```
master key (32B)  ──► DPAPI-wrapped  ──►  %LOCALAPPDATA%\CamBrain\keys\master.key
                            │
                            └── scoped to the Windows user account.
                                Another user on the box cannot decrypt it.
```

- Key generated once on first run via `cryptographic token_bytes(32)`.
- Wrapped with `CryptProtectData` (DPAPI, `CRYPTPROTECT_LOCAL_MACHINE` off).
- On non-Windows dev hosts, falls back to a `0600` file with a loud warning — a dev-machine fallback is not acceptable for production, so this is gated by an environment check.
- Database stores only ciphertext: `rtsp_password_enc`, `telegram_token_enc`, etc. Column types are `LargeBinary`.

**Why DPAPI rather than a user-supplied passphrase:** installers (Arun) hand these boxes over to customers. A passphrase means a support call if the owner forgets it. DPAPI ties decryption to the OS account, which is the correct scope — the box's operator is the box's administrator.

### 3.3 Never in logs

Redaction happens in the `structlog` processor chain, so it is structurally impossible to emit a secret by forgetting:

```python
REDACT_KEYS = {
    "password", "passwd", "rtsp_password", "token", "bot_token",
    "secret", "authorization", "api_key", "access_token",
    "rtsp_password_enc", "telegram_token_enc", "jwt_secret",
}

# URL userinfo is stripped entirely:
#   rtsp://admin:sup3rSecret@10.0.0.5:554/Streaming/Channels/101
#   rtsp://***:***@10.0.0.5:554/Streaming/Channels/101
```

Applied to every event, every exception message, and every log argument. Verified by a test that logs a struct containing every key above and asserts none of the values appear in captured output.

**RTSP URLs are never logged in full.** The mask preserves host, port, and path — enough for an installer to diagnose — and drops userinfo.

### 3.4 Secrets in the API surface

`GET` responses **never** return secret values. Camera and notifier endpoints return `"password": "••••••••"` plus a `has_password: true` flag. `PATCH` accepts an empty string meaning "unchanged"; the only way to clear a secret is explicit `null`.

---

## 4. Authentication & authorisation

### 4.1 Passwords

- **Argon2id** via `argon2-cffi`: `m=64MB, t=3, p=4`. Memory-hard, no GPU attack surface.
- No MD5, SHA1, or unsalted SHA256 — not even in legacy migration paths.
- Per-user random salt, stored with the hash.
- Minimum 10 characters. No composition rules (they push users toward `Password1!`).
- Optional breach-list check against a local wordlist; no network call.

### 4.2 Sessions

JWT, `HS256`, signed with a per-installation random key stored DPAPI-wrapped.

| Claim | Purpose |
|---|---|
| `sub` | user id |
| `site_id` | **tenant scope — enforced on every query** |
| `role` | `admin` \| `viewer` |
| `exp` | 12h |
| `jti` | for revocation |

Plus a server-side `sessions` table so a session can be revoked (sign-out-all, user disabled, password changed). A pure stateless JWT cannot be revoked before `exp`; for a security product that matters.

Refresh tokens are stored **hashed** in the database, rotated on use, with reuse detection — presenting an already-rotated refresh token revokes the whole family, which detects a stolen token.

### 4.3 Authorisation

Two roles:

| Role | May |
|---|---|
| `admin` | Everything, including users, system settings, notifier tokens |
| `viewer` | Live view, event log, event detail. **Read-only.** |

**Enforcement is server-side, on every route, always.** Hiding a nav item in the frontend is presentation, not a control. Each router declares its required role via a dependency; `viewer` hitting an admin route gets `403`.

**Every query is scoped by `site_id` taken from the token, never from the request body.** Accepting a `site_id` from the client is the classic multi-tenant IDOR, and it is the highest-impact bug class in this design. Enforced by a repository-layer base class that requires `site_id` on every query, plus a test asserting cross-tenant reads return `404` (not `403` — `403` confirms the row exists).

### 4.4 Brute force

Login: 5 attempts per username per minute, then exponential backoff to 15 min. Per-IP cap as well, since usernames are guessable. Successful login resets the counter. Lockout state is stored, so it survives a restart — otherwise restart-to-bypass.

### 4.5 CSRF

The API is consumed by our own first-party frontend over localhost, not by third-party sites — but a malicious page in the operator's browser can reach `127.0.0.1:8765`. Defences:

- State-changing requests require `Content-Type: application/json`, which forces a CORS preflight for cross-origin attempts.
- A custom `X-CambBrain-Client` header is required on all mutating requests; custom headers also force preflight.
- `Origin`/`Referer` validated against an allowlist.
- No CORS wildcard, ever. The allowlist is localhost origins only.
- `SameSite=Strict` on the refresh-token cookie; the access token is held in memory, never `localStorage`, so XSS cannot exfiltrate a persistent credential.

---

## 5. Network & transport

**LAN.** Traffic to the dashboard is plaintext HTTP on localhost only. For a non-localhost bind, TLS is required — self-signed with a locally-generated cert, pinned by the Tauri shell. Plaintext on an exposed interface would put camera credentials on the wire.

**Outbound.** Telegram over HTTPS with certificate verification on, hostname checking on, and no verification-disabling flag anywhere. A `certifi` CA bundle is pinned rather than relying on the system store, so a compromised root cannot silently intercept alerts.

**RTSP.** Camera credentials travel in the RTSP URL. Where the camera supports it, prefer digest/ephemeral auth; where a URL must embed credentials, the source masks it before logging. Prefer the sub-stream (640×360 @ 10–15fps) — it reduces the customer's bandwidth and our decode load, and is the difference between 8 cameras and 3 on a weak link.

**No inbound ports.** Nothing listens from the internet. Alert delivery is outbound-initiated, so no port forwarding is ever required at a customer's site.

---

## 6. Filesystem security

### 6.1 Directory permissions

| Path (under `%LOCALAPPDATA%\CamBrain\`) | Permission |
|---|---|
| `cambrain.db` | Owner read/write only |
| `keys/master.key` | Owner read/write only |
| `clips/` | Owner read/write only |
| `logs/` | Owner read/write only |

On Windows, an ACL granting the installing user and `SYSTEM` full control, denying inheritance, and denying `Users` read. Without this, a `Users`-group-readable DB means every person at the shop can read footage.

### 6.2 Path traversal

**Every** filesystem path is built from an internal integer ID or a UUID — never from a user-supplied string.

```python
# WRONG — camera name is user input
path = CLIPS / f"{event.camera_name}_{ts}.mp4"

# RIGHT
path = CLIPS / f"{event.id}.mp4"
```

`camera.name`, `roi.name`, and any note field are treated as hostile. Clip serving goes through an API endpoint that looks the path up by ID from the database — the client never constructs or sends a filesystem path.

### 6.3 Retention

- Default 7 days, configurable per site.
- Hard disk quota (default 80% of free space) — the clip writer refuses to write past the cap and raises a `site` alert rather than filling the customer's disk and breaking their NVR.
- Deletion is a background task, batched to avoid a single transaction deleting 100k rows.
- Deleting an event deletes its clips and detections in the same transaction.

**Filling the customer's disk is our bug, not theirs.** It takes down their NVR, which is the one thing we promised not to do.

---

## 7. Application security

### 7.1 Dependencies

- Locked versions in `requirements.txt` / `package.json`.
- Automated scanning for known CVEs on every CI run.
- **Licence scanning fails the build on any AGPL identifier** — see [memory.md D1](memory.md). This is a security control as much as a legal one: an AGPL dependency in a shipped artifact is a latent disclosure obligation.
- No runtime dependency fetches code. The one network fetch (model weights) is checksum-pinned.

### 7.2 Model files

Weights are fetched over HTTPS and **verified against a pinned SHA-256** before being loaded. A model file is executable-in-effect: a tampered `.onnx` can contain malicious operators. ONNX Runtime executes a graph; it does not run arbitrary native code by default, but the loader is hardened and any checksum mismatch is a hard failure, never a warning.

`models/LICENSE-MODEL-NOTICE` records provenance and licence per file. Apache-2.0 requires attribution; this is a legal obligation and a supply-chain record in one.

### 7.3 Input validation

Pydantic validates every request body with strict types and explicit bounds. `confidence` is clamped to `[0,1]`; `sample_fps` to `[0.1,10]`; ROI vertex counts and coordinates are range-checked. Oversized bodies are rejected at the proxy.

### 7.4 Error responses

Internal errors return a generic message plus a correlation id. Stack traces, SQL, file paths, and RTSP URLs with credentials never reach a client. Full detail goes to the log, correlated by that same id.

### 7.5 Audit log

Distinct from operational logs and retained 90 days. Records: login success/failure/lockout, user create/update/delete, role change, camera add/edit/delete, ROI change, rule change, notifier config change, export, retention deletion. Includes actor, site, IP, timestamp, and a change summary.

An audit trail is the difference between "someone was on the network" and "nobody changed anything" when a shop owner disputes what their system did.

---

## 8. Privacy

### 8.1 Data minimisation

CamBrain stores what it needs to answer "what happened, when":

- **Stored:** event still, short event clip, detection metadata (class, confidence, box, track id, timestamp, camera, zone, rule)
- **Never stored:** continuous footage, audio, faces or biometric templates, identity, licence plates read as text
- **Never transmitted:** any video, except the specific clip the owner configured to be delivered to their own Telegram

There is no facial recognition and no biometric identifier anywhere in the design, deliberately — it creates a category of legal exposure under the DPDP Act that a security product does not need.

### 8.2 DPDP Act 2023 posture

India's Digital Personal Protection Act applies to footage of identifiable people. Posture:

- **Purpose limitation** — processed solely for the security purpose the site owner configured.
- **Retention limits** — 7 days default, shorter available, deletion automatic.
- **No cross-border transfer** — footage never leaves the premises by default. Telegram delivery is an explicit, user-initiated transfer of a specific clip to a destination the user chose; it is documented in the install guide, and configurable off.
- **Data-subject requests** — for on-premise footage the owner *is* the controller and answers requests directly. CamBrain's contribution is the deletion tooling.
- **Security safeguards** — this document.

### 8.3 What we tell the customer

The install guide states plainly: footage stays on their box, we cannot see it, and the only thing leaving is an alert they configured. That sentence is a selling point, not a compliance formality — privacy is one of the strongest reasons to prefer this over cloud AI, and it should be said out loud.

---

## 9. Secure defaults

| Default | Rationale |
|---|---|
| Bind `127.0.0.1` | Not exposed unless deliberately |
| Auth required on every route | LAN is not trusted |
| TLS required for non-localhost bind | Credentials on the wire |
| Secrets encrypted at rest | Disk/backup theft is real |
| Secrets redacted in logs | Logs get emailed and pasted in chat |
| `viewer` is read-only | Least privilege |
| Retention 7 days | Minimisation |
| Disk quota 80% | Won't break the customer's NVR |
| No outbound calls but notifier | Privacy and no running cost |
| Model checksum verification | Supply-chain integrity |

---

## 10. Release checklist

- [ ] Dependency CVE scan clean
- [ ] Licence scan clean — **zero AGPL**
- [ ] Secret-redaction test passing for all `REDACT_KEYS`
- [ ] Cross-tenant access tests returning `404`
- [ ] Authz tests covering every route × every role
- [ ] Rate limiting verified, including across restart
- [ ] File permissions verified on a fresh install
- [ ] Path-traversal tests on every endpoint accepting an ID
- [ ] Retention and quota verified under a disk-pressure simulation
- [ ] Model checksum mismatch fails hard
- [ ] Audit log records every privileged action
- [ ] Installer makes no unexpected network calls
- [ ] Offline mode verified — full function with no internet
- [ ] Second developer has reviewed the auth and tenancy paths

---

## 11. Reporting a vulnerability

Security issues go to a private address, not a public issue tracker. Acknowledge within 3 business days. Triage within 10. No public disclosure until a fix ships. Given the customer base, a credential-leak or auth-bypass bug is a launch blocker — not a patch-in-the-next-release item.