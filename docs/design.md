# CamBrain — UI/UX Direction

> Living document. Update as the interface evolves.
> Related: [prd.md](prd.md) · [architecture.md](architecture.md) · [CODE_STYLE.md](CODE_STYLE.md)

---

## 1. Two surfaces, two toolkits

This is the most important decision in this document, and it is a product decision, not a taste decision.

CamBrain has two completely different audiences with completely different needs, and they must not be designed with the same tools.

| | **Marketing site** | **The app** |
|---|---|---|
| Audience | A shop owner deciding whether to buy | An operator responding to an alert at 2am |
| Job | Convince, explain, look credible | Answer: what is happening, where, now |
| Emotional target | Delight, trust | Certainty and calm |
| Scroll behaviour | Long-form, scroll-driven | Fixed viewport, no page scroll |
| Animation | GSAP + Lenis, scroll effects | 150–300ms transitions only |
| Density | Airy, generous | Dense, information-first |

**The app is an operations console, not a website.** Everything below about the app follows from one premise: the person using it is probably standing in a noisy room at 2am, woken up by a phone buzz, and needs to know whether this is worth driving to the shop.

### Why the heavy animation libraries are not in the app

This deserves stating explicitly, because it will be questioned.

GSAP, Lenis, AniMaster, Skiper UI, and Vengeance UI are excellent libraries for marketing pages. They are wrong for this app for four concrete reasons — three engineering, one human:

1. **CPU contention.** The box runs 8 inference pipelines. A WebGL shader background or a cursor-trail effect competes for the exact silicon that detection needs. Every millisecond spent animating is a millisecond not spent on a customer's alert. Marketing-site performance budgets assume a dedicated GPU; we have a shared 6-watt CPU.

2. **Input precision.** ROI polygon drawing requires pixel-accurate clicking on a live video surface. Scroll-snap wrappers, `transform` layers, magnetic hover targets, and parallax ancestors all perturb the coordinate mapping between what the user clicks and what gets recorded. A ROI drawn 4px off is a zone that misses.

3. **Motion sensitivity.** The primary interaction is "click precisely, on a small target, under time pressure." Large movement, spring physics, and entrance animations are hostile to that. Every animation adds latency between intent and response.

4. **It is a security tool.** Operators scan for the one thing that matters: red. Visual noise dilutes the signal. Restraint communicates competence; a dashboard full of motion communicates a toy.

**What we take from the marketing surface instead:** the visual *taste* — considered typography, generous spacing in the marketing material, confident motion in the onboarding flow only. An onboarding walkthrough is marketing; a live view is not.

### What the app is allowed to animate

| Context | Allowed | Duration |
|---|---|---|
| Page/route change within console | Fade + 4px rise | 150ms |
| Panel open/close (drawer, modal) | Fade + scale from 0.98 | 150ms |
| Alert arriving in the live feed | Border flash + badge pulse | 400ms, once |
| Camera tile state change (connected/lost) | Colour cross-fade | 300ms |
| Button/row hover | Background + border | 120ms |
| Live video | **None** | — |

Live video never animates. A tile that scales on hover makes it harder to hit, and a moving image is harder to interpret than a still one. The ROI editor overlays do move — that is direct manipulation, and it must track the pointer exactly.

Easing is `cubic-bezier(0.2, 0, 0, 1)` throughout. Nothing overshoots, nothing bounces. Bounce reads as playful; this is a security tool.

### `prefers-reduced-motion`

All non-essential motion is disabled under `prefers-reduced-motion: reduce`. Framer motion is not used — Vue's `<Transition>` plus CSS is sufficient and avoids the dependency.

---

## 2. Design tokens

### Palette — dark by default

Operators run this at night, often in a dim room, sometimes on a cheap monitor with poor gamma. Dark-first is not aesthetic here, it reduces eye strain on long shifts and keeps the UI from lighting up a shop at 2am.

| Token | Value | Use |
|---|---|---|
| `--bg-base` | `#0B0D10` | App background |
| `--bg-surface` | `#14181D` | Cards, panels |
| `--bg-raised` | `#1C2126` | Hover, elevated elements |
| `--border` | `#252B32` | Default borders |
| `--text-primary` | `#E8EBEE` | Body text |
| `--text-secondary` | `#9BA5AF` | Labels, metadata |
| `--text-muted` | `#5F6873` | Disabled, hints |
| `--accent` | `#3B82F6` | Primary action, focus ring |
| `--accent-hover` | `#2F6FD0` | — |
| `--alert-critical` | `#E5484D` | Confirmed intrusion, emergency |
| `--alert-warning` | `#F5A524` | Suspicious, degraded camera |
| `--alert-success` | `#30A46C` | Healthy, connected |
| `--roi-fill` | `#3B82F660` | ROI polygon fill |
| `--roi-stroke` | `#3B82F6` | ROI polygon border |
| `--detect-box` | `#30A46C` | Detection bounding box |

**Colour is never the only signal.** Detection state also carries a text label; camera health carries an icon and a word. Roughly 1 in 12 men has a red-green deficiency, and this audience includes shop owners who will hit exactly that wall.

### Typography

Inter for UI text, JetBrains Mono for timestamps, RTSP URLs, and IPs. Monospace on technical identifiers is not decoration — it makes `192.168.1.104` distinguishable from `192.168.1.1O4` at a glance.

```
Display      Inter 600, 28px/34px, -0.02em
Heading      Inter 600, 18px/24px, -0.01em
Body         Inter 400, 14px/20px
Label        Inter 500, 12px/16px, +0.02em, uppercase
Mono         JetBrains Mono 400, 12px/18px
```

14px body rather than 16px: this is a dense console where more rows on screen is the point.

### Spacing & radius

4px base grid (`4 8 12 16 24 32 48`). Radius `6px` for controls, `10px` for cards, `999px` for pills. Consistent radii across a component set are what make a hand-rolled system feel like a coherent product rather than assembled parts.

### Motion tokens

```
--dur-fast:   120ms
--dur-base:   150ms
--dur-slow:   300ms
--dur-alert:  400ms
--ease:       cubic-bezier(0.2, 0, 0, 1)
```

---

## 3. App information architecture

```
/login                   → sign in
/                        → redirect to /cameras
/cameras                 → live grid (default landing)
/cameras/:id             → single camera detail + ROI editor + rules
/events                  → event log, filterable
/events/:id              → event detail: still, clip, detections
/settings/users          → admin only
/settings/system         → hardware tier, model, storage, notifiers
```

The landing page is the live grid, not a dashboard of charts. Operators want to see cameras. Analytics is secondary and lives under `/events` where it belongs.

### Navigation

Persistent left sidebar, 232px, icon + label. Four items in MVP: Cameras, Events, Users (admin), System. Collapses to icons below 1024px.

A **tray** is always present. Right-click → Open dashboard, Pause detection, Restart service, Quit. "Pause detection" is the panic button when a customer is testing a camera and does not want 40 alerts — without it, every installer will quit the app instead.

---

## 4. The live grid — primary screen

```
┌─────────────────────────────────────────────────────────────────────┐
│ ◉ CamBrain      Rajkot — Shop 1              ● 8 online    ⚙  ◐  ⋯  │
├────────┬────────────────────────────────────────────────────────────────┤
│        │ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐         │
│ 📹 Cam │ │              │ │              │ │              │         │
│ 🔔 Eve │ │   CAM 01     │ │   CAM 02     │ │   CAM 03     │         │
│ 👤 Use │ │              │ │              │ │              │         │
│ ⚙ Sett │ │   [live]     │ │   [live]     │ │   ⚠ offline  │         │
│        │ │              │ │              │ │   last 4m ago │         │
│        │ ├──────────────┤ ├──────────────┤ ├──────────────┤         │
│        │ │              │ │              │ │              │         │
│        │ │   CAM 04     │ │   CAM 05     │ │   CAM 06     │         │
│        │ │  ▢ ROI       │ │   [live]     │ │   [live]     │         │
│        │ │              │ │              │ │              │         │
│        │ └──────────────┘ └──────────────┘ └──────────────┘         │
│        │ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐         │
│        │ │   CAM 07     │ │   CAM 08     │ │  + Add cam   │         │
│        │ └──────────────┘ └──────────────┘ └──────────────┘         │
│        │                                                              │
│        │  ── 14:32:07  ▸ person 0.94  CAM 02 ▸ view                   │
├────────┴────────────────────────────────────────────────────────────────┤
│ ● 8 online · 2 offline   3.1 FPS avg   2% CPU   ▸ system tray          │
└─────────────────────────────────────────────────────────────────────┘
```

**Tiles.** Auto-fill grid, `minmax(320px, 1fr)`, so it adapts from a 1366px shop PC to a 4K monitor without breakpoints. Aspect ratio 16:9 locked via `aspect-ratio` so the grid never reflows when video dimensions differ.

**Live video is MJPEG**, downscaled to 640×360 at ~3 FPS per tile on the LAN. Not H.264, not WebRTC. Rationale: MJPEG needs no transcoding, no codec negotiation, and no browser codec support; on a LAN the bandwidth is irrelevant (8 × 640×360 × 3fps ≈ 40 Mbps on gigabit); and it is trivially debuggable with `curl`. Adding WebRTC for smooth video is a Phase 6 candidate once we know whether operators actually want it — and note the desktop shell means we control the browser engine, which makes it feasible later.

**Tile states.** `live` (MJPEG playing), `offline` (dimmed, last-seen timestamp, retry state), `starting` (skeleton + spinner), `error` (masked URL, the actual reason, and a Retry button).

**The event ticker** at the bottom shows alerts as they fire, newest first, capped at 5 visible. Clicking one opens the event detail. It is deliberately small — the grid is the point.

---

## 5. ROI editor — the most important interaction

This is where a wrong 4px offset silently breaks the customer's alerts. It gets the most design attention.

```
┌──────────────────────────────────────────────────────────────┐
│ CAM 02 — Back entrance                    [Save]  [Cancel]   │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│     ┌────────────────────────────────────────┐  ZONES        │
│     │                                        │  ┌──────────┐ │
│     │            live snapshot               │  │✓ Back d. │ │
│     │                                       ╱│  │  8.2%    │ │
│     │         ┌─────────────────┐           ╱ │  │  Person  │ │
│     │         │╱╲              │          ╱  │  │  Both    │ │
│     │         │  ▢ ZONE 1  ←───│── polygon │  │  └──────────┘ │
│     │         │  back door     │          ╱   │  ┌──────────┐ │
│     │         │╲               │         ╱    │  │+ Add     │ │
│     │         └─────────────────┘        ╱     │  └──────────┘ │
│     │     ╱‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾╱          │
│     └────────────────────────────────────────┘  CLASSES      │
│                                                      ☑ person │
│  ──●────────────── 0.47  sensitive                       ...  │
│      motion sensitivity                                 RULES  │
│                                                         ☑ alert│
└──────────────────────────────────────────────────────────────┘
```

**Interaction rules**, each of which exists because its absence produces a wrong zone:

1. **Draw from a frozen snapshot, not live video.** The user draws against a still. Drawing against moving video means the polygon is placed against a scene that has since changed, and they cannot see what they are doing.
2. **Snap to nothing.** No grid snapping, no angle constraint. Freehand vertex placement. Imposed constraints produce polygons the user did not intend.
3. **Vertices are draggable after creation.** The common case is a polygon that is nearly right. Requiring a delete-and-redraw to move one vertex is punitive.
4. **Minimum 3 vertices.** Enforced at draw time, not at save time with an error.
5. **Minimum area threshold.** A polygon under ~500px² at source resolution is almost certainly an accidental double-click; block it with an explanation.
6. **Zone list on the right, always visible.** Not hidden behind an "edit" mode. Managing several zones is normal.
7. **Per-zone class filter**, defaulting to `person`. This is where the alert noise is actually controlled — see [architecture.md §6](architecture.md).
8. **Show coverage percentage.** "8.2% of frame" is meaningful feedback and it teaches the concept in one glance.
9. **Nothing commits until Save.** Cancel restores. Destructive-on-blur is unacceptable when the action is expensive to redo.
10. **The polygon is stored in normalised coordinates (0.0–1.0), not pixels.** Camera resolution changes between a sub-stream and a main-stream, and pixel coordinates would silently misplace every zone. This is a correctness requirement, not a preference.

**Sensitivity slider** maps to the motion gate threshold. Live label ("sensitive" / "balanced" / "relaxed") rather than raw numbers — the user is not calibrating a detector, they are trading false alarms against missed intrusions.

---

## 6. Event log

Filterable table: camera, time range, class, severity, zone. Rows expand to show the still with bounding boxes drawn. Thumbnail column, since a shop owner recognising "that's the delivery guy" from a thumbnail is the actual workflow.

Severity is the primary sort and colour: `critical` (armed hours + intrusion), `warning` (suspicious / off-hours), `info` (permitted hours, logged not alerted).

Bulk acknowledge, so a night of false positives is one click to clear rather than thirty.

---

## 7. Login

Single centred card, no marketing chrome. Username + password, error states that never reveal *which* of the two was wrong. No "forgot password" in MVP — the installer resets it; a self-service reset on an air-gapped-ish box is a dead end for the user anyway.

`admin` and `viewer` roles. Viewers cannot reach `/settings/*`; the nav item is absent and the route guard rejects.

---

## 8. Onboarding

First run walks through: create admin → add first camera (with a built-in **test connection** button that reports the actual failure reason — wrong password vs unreachable vs codec unsupported) → capture snapshot → draw first zone → connect Telegram.

This is the difference between a five-minute install and a support call. The test-connection diagnostic in particular is load-bearing: "failed" with no reason is the single most common installer complaint in this category.

---

## 9. Frontend stack

| Concern | Choice | Note |
|---|---|---|
| Framework | **Vue 3, Composition API, JavaScript** | No TypeScript — deliberate, per project decision |
| Build | Vite | |
| Desktop shell | **Tauri v2** | Tray, autostart, small binary |
| State | Pinia | |
| Router | Vue Router | |
| Primitives | **shadcn-vue** (Radix-Vue) | MIT, React-free; we own the source |
| Styling | Tailwind CSS | Tokens in §2 as CSS variables |
| Icons | Lucide | |
| Data | `fetch` + a thin WebSocket client | No axios needed |
| Charts | (deferred) | Nothing in MVP needs a chart |

Hand-rolled component source is a feature, not a limitation — we own it, no vendor, no license risk, and it is copied into `frontend/src/components/ui/`.

**JavaScript, not TypeScript.** A deliberate project decision to reduce build friction for a solo founder. Mitigation: JSDoc typedefs on every exported function and every API boundary, and strict ESLint with `jsdoc/require-jsdoc`. The documentation value of types is retained where it matters — at module boundaries and API payloads — without the compiler step. Revisit if the codebase passes ~40 source files or a second developer joins.

---

## 10. Component inventory (MVP)

```
layout/    AppShell · Sidebar · TopBar · StatusBar · TrayMenu
camera/    CameraGrid · CameraTile · CameraCard · AddCameraDialog
           ConnectionTest · CameraSettings · MotionSensitivity
roi/       RoiEditor · RoiCanvas · RoiPolygon · VertexHandle · ZoneList · ClassFilter
events/    EventTable · EventRow · EventDetail · DetectionOverlay · EventFilters · AckButton
auth/      LoginForm · AuthGuard · RoleGate
ui/        Button · Input · Select · Switch · Slider · Dialog · Drawer · Table
           Badge · Tooltip · Toast · Spinner · Skeleton · EmptyState · AlertBanner
```

All in `ui/` follow the shadcn-vue pattern: copied source, owned by us, modified freely.

---

## 11. Accessibility

Non-negotiable, and cheap to hold if done from the start:

- Every interactive element reachable by keyboard, visible focus ring (`--accent`, 2px, offset 2px)
- ROI editor fully keyboard-operable: arrows nudge the selected vertex, `Enter` closes the polygon, `Esc` cancels
- Live video tiles have text status; colour is never sole signal
- `prefers-reduced-motion` honoured throughout
- Contrast ≥ 4.5:1 for text, ≥ 3:1 for borders and icons
- Alerts announced via an `aria-live="polite"` region — a viewer who is not watching the screen still learns an alert arrived
- Full WCAG 2.1 AA target

---

## 12. Marketing site direction

The surface where the heavy libraries belong.

**Stack:** Vite + GSAP (free including SplitText and MorphSVG since Webflow's April 2025 change) + Lenis (MIT). Tailwind.

**Voice:** plain, specific, Indian SME. Not "AI-powered security solutions". "Know if someone walks in after you close." Lead with the economics — no cloud fee, no camera replacement — because that is the actual differentiator against an imported competitor.

**Structure:** hero (live ROI demo, not a stock image) → how it works (three steps) → what it detects → pricing (per-camera, local) → the no-cloud argument, stated plainly → install → FAQ.

**Motion:** scroll-driven reveals, the ROI-drawing demo animating itself, counters, and one genuinely delightful section. Restraint even here — a security product that looks like a toy undercuts its own pitch.

**Assets:** no stock photography of smiling Indian shopkeepers. Screenshots of the real product, real footage from test clips, real screenshots of the dashboard. In this market the imagery *is* the credibility.