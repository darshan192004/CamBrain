# CamBrain — Product Requirements Document

> Living document. Update as the product evolves.
> Related: [architecture.md](architecture.md) · [tasks.md](tasks.md) · [memory.md](memory.md)

---

## 1. Problem

Indian MSME owners — retail shops, warehouses, small factories — already own Hikvision / CP Plus / Dahua cameras and a working NVR or VMS. Those cameras are "dumb": they record, and they record forever without telling anyone anything. Owners get their value only after an incident, if they find the footage at all.

The expensive options are all bad fits for this market:

| Option | Why it fails here |
|---|---|
| Replace cameras with AI cameras | The customer already owns working hardware. Capital cost plus disposal. |
| Cloud video AI SaaS | Monthly fees are high, multi-stream uplink eats bandwidth, latency makes alerts useless, and footage leaves the premises — a privacy problem for a security product. |
| Proprietary AI NVR appliance | Locks the customer into one vendor for a product they will want to run themselves. |

**CamBrain is the sidecar.** It installs alongside the NVR software the customer already runs, reuses the exact RTSP URLs the NVR already uses, adds the AI layer on top, and never asks the customer to replace anything or pay a cloud subscription.

---

## 2. Personas

### Ramesh — retail shop owner (primary)

Owns one shop in Rajkot. 4 cameras (Hikvision + CP Plus mix), an NVR already recording 24×7. Closes at 10pm. Cannot check footage from outside the shop. Wants: *know if someone walks in after hours.* Doesn't care how detection works. Will judge the product entirely on whether alerts are real and whether he can set it up in one sitting.

### Priya — factory manager, GIDC

150 workers, 12 cameras, perimeter + loading dock + worker-safety zones. Already pays for a Hikvision NVR with analytics she doesn't trust. Wants: *alert on a person in the loading dock at 2am, and on vehicles at the gate.* Cares about false-positive rate more than feature count — an alarm she learns to ignore is worse than no alarm.

### Arun — the installer / integrator

CamBrain's real channel in the first year. Installs boxes for Ramesh and Priya. Wants: *a build I can hand over without a 40-page manual,* credentials stored safely, and no requirement to stay on-site when something breaks at 11pm.

---

## 3. Product principles

1. **Add-on, never a replacement.** No feature may require the customer to disable, reconfigure, or replace their NVR.
2. **Local-first, unconditionally.** No video, no detection, no clip ever leaves the premises. The only network call that carries customer content is the alert the owner asked for.
3. **Runs on the hardware already in the shop.** If it needs a GPU server to work, it has failed at the price point.
4. **Zero cloud cost per customer.** No per-camera cloud fee. This is what lets us sell cheap or bundle hardware.
5. **Honest alerts.** A missed detection loses us nothing permanent; a false alarm at 2am loses us the customer. False positives are the primary engineering enemy.

---

## 4. MVP scope

### In scope

| # | Capability |
|---|---|
| 1 | Add, edit, remove RTSP cameras; test connection before saving |
| 2 | Multi-camera concurrent ingest (target 8) with automatic reconnect on drop |
| 3 | Dynamic frame sampling at 2–5 FPS per camera (configurable) |
| 4 | Motion pre-filter so inference runs only on movement |
| 5 | Object detection across all 80 COCO classes |
| 6 | Polygon Region of Interest per camera, drawn on a snapshot |
| 7 | Per-camera rules: class allow-list, confidence threshold, ROI, active hours, cooldown |
| 8 | Short event clips (10s pre-roll, 20s post-roll) saved with a still |
| 9 | Telegram alerting with a snapshot or clip; WhatsApp behind the same interface |
| 10 | Web dashboard: live grid, camera management, ROI editor, event log, rules editor |
| 11 | Local accounts with two roles: admin and viewer |
| 12 | Windows system-tray app that starts on boot |

### Explicitly out of scope (MVP)

Continuous recording (CamBrain is not an NVR) · cloud sync · central fleet console · PPE / helmet detection · facial recognition · mobile app (Telegram *is* the mobile app) · per-camera subscription billing.

**Deployment shape for MVP:** one edge box per site. The schema is tenant-aware from day one — every table is keyed by `site_id` — so a future central console or a multi-site box needs no migration, but one box serving several sites concurrently is not an MVP feature. See [memory.md D6](memory.md).

These are not rejected — they are sequenced. See [tasks.md](tasks.md).

### MVP success criteria

A first-time user adds a camera, draws one ROI, sets one rule, and receives a real Telegram alert for an intruding person **without contacting support**.

---

## 5. User stories

**As Ramesh**, I want to add my shop's four cameras and see live view immediately, so I know the install worked.

**As Ramesh**, I want to draw a polygon over the back door on a screenshot, so I stop getting alerts about people passing on the road outside.

**As Ramesh**, I want an alert only after 10pm, so the shop isn't shouting at me at 3pm when my brother walks in.

**As Ramesh**, I want the alert to include a picture, so I know whether it's a person or a cat before I drive over.

**As Priya**, I want to allow-list specific classes per camera, so a truck at the gate alerts me but a parked scooter does not.

**As Priya**, I want to see a log of every alert this week with thumbnails, so I can show my GM what happened on Tuesday.

**As Priya**, I want per-rule cooldowns, so one person standing in the yard doesn't produce 200 alerts overnight.

**As Arun**, I want to type a camera's RTSP URL with a password and know the password is encrypted at rest, so I can read the customer's config on the handover sheet.

**As Arun**, I want the app to come back on its own after a power cut, so I don't get a call at 6am.

**As Arun**, I want the add-camera wizard to tell me *which* thing is wrong — wrong password vs wrong sub-stream path vs camera unreachable — so I can fix it on site instead of guessing.

---

## 6. Non-functional requirements

| Requirement | Target | Notes |
|---|---|---|
| Concurrent cameras | 8 per box | With motion gating; 4 on low tier |
| Hardware floor | Intel N100 (Alder Lake-N, AVX2 + VNNI) | Graceful degradation below this |
| Detection latency | < 2s from motion to alert | Measured motion → Telegram send |
| Sample rate | 2–5 FPS per camera | Configurable, not hardcoded |
| Reconnect after drop | ≤ 5s for a transient drop; exponential backoff to 60s for persistent failure | Jittered to avoid thundering herd |
| Memory growth | Flat across days | No per-frame or per-reconnect leak |
| Idle CPU | < 5% with no motion | Motion gating must actually gate |
| Disk | Event clips only, configurable retention | Default 7 days, quota-capped |
| Resolution | Works at 1080p input | Downscale before inference |
| Uptime | Survives 24h unattended | Verified by soak test |
| Offline | Full function with internet down; only Telegram delivery fails | |
| Uptime of service | Starts on boot, no user login | Tray app |

---

## 7. Constraints

**Licensing is a hard constraint, not a preference.** The product is sold closed-source. No dependency may carry copyleft that would oblige source disclosure of the whole application. This rules out every Ultralytics YOLO release (v5, v8, v11, v26) — AGPL-3.0, including when exported to ONNX. The detector must be Apache-2.0 or equivalent. See [memory.md](memory.md) for the full reasoning.

**Bandwidth is not a constraint on the LAN, but it is on disk and uplink.** Video stays local. Only alerts are sent out.

**Trust boundary.** The box sits on a customer's LAN with their NVR. Anyone on that LAN can reach CamBrain's port. Authentication is therefore mandatory, not optional, even though it is a trusted network.

---

## 8. Out of scope, restated as questions we are deliberately not asking yet

- Should we detect behaviour (loitering, fall, mask removal)? *Not yet. Requires tracking maturity and per-site thresholds.*
- Should we sell per-camera subscriptions in-app? *Not yet. Needs a payment provider and a server; conflicts with the zero-cloud-cost principle at launch.*
- Should the mini-PC bundle be optional? *Yes, eventually — the software-only install is the primary path and the box is an upsell.*