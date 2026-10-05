# CamBrain — Database Design

> Living document. SQLite, SQLAlchemy 2.0, Alembic.
> Related: [architecture.md](architecture.md) · [SECURITY.md](SECURITY.md) · [API.md](API.md) · [CODE_STYLE.md §6](CODE_STYLE.md)

---

## 1. Why SQLite

The box is a self-contained appliance on a customer's LAN with no server to depend on. SQLite is the correct answer for that: zero administration, one file, transactional, and fast enough for the write pattern here.

- **Writes:** event rows, detection rows, occasional clip metadata. A few dozen per minute at worst on a busy scene.
- **Reads:** event log pagination, rule evaluation lookups, dashboard queries. Cheap.
- **Writers:** one process. SQLite's single-writer model is not a constraint.

**WAL mode is mandatory.** It lets the API read while a pipeline writes, which is the difference between a responsive dashboard and one that blocks during a burst of events. `synchronous=NORMAL` in WAL is the right durability/throughput trade for this workload — we lose at most the last second of events on power loss, and the clip files on disk survive regardless.

```python
engine = create_engine(
    f"sqlite:///{db_path}",
    connect_args={"check_same_thread": False, "timeout": 30.0},
    poolclass=QueuePool,      # NOT the pysqlite default — we control reuse
    pool_size=5,
    max_overflow=5,
)

@event.listens_for(engine, "connect")
def _configure_sqlite(dbapi_conn, _record):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.execute("PRAGMA foreign_keys=ON")     # off by default in SQLite!
    cur.execute("PRAGMA busy_timeout=30000")
    cur.close()
```

**`foreign_keys=ON` is not optional.** SQLite ignores FK constraints by default. Leaving it off means the schema's referential integrity is decorative.

---

## 2. Tenancy

Every domain table carries `site_id`. One box typically serves one site, but the schema is tenant-aware from day one — retrofitting this later is one of the most painful migrations in a product like this (see [memory.md D6](memory.md)).

**`site_id` comes from the auth token, never from a request body.** See [SECURITY.md §4.3](SECURITY.md).

**`ON DELETE CASCADE` on every FK** to a `site_id` parent. Deleting a site must never leave orphaned cameras, rules, or events — an installer decommissioning a box expects one operation, not a cleanup script.

---

## 3. Entity relationships

```
  ┌──────────┐
  │  sites   │  timezone, retention_days, disk_quota_pct
  └────┬─────┘
       │ 1
       │
       └─────────────────────────────────────┘
       │ 1                                   │ 1
       │                                     │
  ┌────┬──────┐  1:N                    ┌────┬─────────┐
  │  cameras  │──────────────┐          │    users     │  username, argon2 hash
  │ site_id   │              │ 1:N      │  site_id     │  role: admin|viewer
  │ rtsp_url  │              │          └──────────────┘
  │ (enc pw)  │              │
  │ status    │              │
  └───────────┘              │
                             │
                    ┌────────┬────────┐        ┌──────────────┐
                    │     rois        │  1:N   │    rules     │
                    │ site_id         │◄───────┤  site_id     │
                    │ camera_id       │ zone   │  camera_id   │
                    │ points (JSON)   │        │  roi_id  (FK)│
                    │ normalised 0..1 │        │  class list  │
                    │ class filter    │        │  cooldown_s  │
                    └─────────────────┘        │  active_hours│
                                              │  severity    │
                                              └──────┬───────┘
                                                     │ 1:N
                                                     │
                                              ┌──────┬────────┐
                                              │    events     │
                                              │ site_id       │
                                              │ camera_id     │
                                              │ rule_id       │  (nullable — manual/auto)
                                              │ started_at    │
                                              │ ended_at      │
                                              │ severity      │
                                              │ thumbnail_path│
                                              │ clip_path     │
                                              │ delivery state│
                                              └──────┬───────┘
                                                     │ 1:N
                                              ┌──────┬────────────┐
                                              │ event_detections │
                                              │ bbox, class,     │
                                              │ confidence,      │
                                              │ track_id         │
                                              └───────────────────┘
```

---

## 4. Tables

### 4.1 `sites`

The tenant root.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `name` | TEXT NOT NULL | "Ramesh — Dhanraj Complex" |
| `timezone` | TEXT NOT NULL | IANA name: `Asia/Kolkata`. **Never** a fixed UTC offset |
| `retention_days` | INTEGER NOT NULL DEFAULT 7 | |
| `disk_quota_pct` | INTEGER NOT NULL DEFAULT 80 | Refuse clips past this % used |
| `notifier_config` | JSON NULL | Encrypted fields live as ciphertext inside; see §6 |
| `created_at` | DATETIME NOT NULL | UTC |

`timezone` as IANA name matters more than it looks: "after hours" means 10pm in the shop's local time. A UTC-offset approach breaks the moment the region observes DST — India does not, but customers in other markets will.

### 4.2 `users`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `site_id` | INTEGER FK → sites ON DELETE CASCADE | |
| `username` | TEXT NOT NULL | Unique per site |
| `password_hash` | TEXT NOT NULL | Argon2id |
| `role` | TEXT NOT NULL | `admin` \| `viewer` — CHECK constraint |
| `is_active` | BOOLEAN NOT NULL DEFAULT 1 | Disabling blocks new logins |
| `created_at` | DATETIME NOT NULL | UTC |
| `last_login_at` | DATETIME NULL | |

`UNIQUE(site_id, username)` — two different sites may each have an `admin`.

CHECK constraint on `role` so an invalid value can't reach the application layer.

### 4.3 `sessions`

Server-side session records, so a JWT can be revoked before `exp` (see [SECURITY.md §4.2](SECURITY.md)).

| Column | Type | Notes |
|---|---|---|
| `id` | TEXT PK | UUID; also the JWT `jti` |
| `user_id` | INTEGER FK → users ON DELETE CASCADE | |
| `site_id` | INTEGER FK → sites ON DELETE CASCADE | Denormalised for scoping without a join |
| `refresh_token_hash` | TEXT NOT NULL | Rotated on use |
| `created_at` | DATETIME NOT NULL | |
| `expires_at` | DATETIME NOT NULL | Indexed |
| `revoked_at` | DATETIME NULL | |
| `ip` | TEXT NULL | |
| `user_agent` | TEXT NULL | |

### 4.4 `cameras`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `site_id` | INTEGER FK → sites ON DELETE CASCADE | |
| `name` | TEXT NOT NULL | "Back door". Display only, never a path |
| `rtsp_url` | TEXT NOT NULL | **Credentials stripped** — see §6 |
| `rtsp_username` | TEXT NULL | Encrypted at rest |
| `rtsp_password_enc` | BLOB NULL | Encrypted at rest |
| `enabled` | BOOLEAN NOT NULL DEFAULT 1 | Disabled cameras don't connect |
| `sample_fps` | REAL NOT NULL DEFAULT 2.0 | CHECK 0.1–10 |
| `motion_threshold` | REAL NOT NULL DEFAULT 0.02 | MOG2 sensitivity |
| `frame_width` | INTEGER NULL | Actual decoded, for ROI scale info |
| `frame_height` | INTEGER NULL | |
| `status` | TEXT NOT NULL DEFAULT 'starting' | `starting`\|`live`\|`offline`\|`error` |
| `last_error` | TEXT NULL | **Credential-masked** |
| `created_at` / `updated_at` | DATETIME NOT NULL | UTC |

**Credentials are separate columns, not embedded in the URL.** This is deliberate: it means the URL can be logged, displayed, and used as a stable identifier without ever carrying a password, and the encryption boundary covers exactly two fields.

### 4.5 `rois`

Regions of interest. **Coordinates are normalised 0..1** relative to frame width/height.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `site_id` | INTEGER FK → sites ON DELETE CASCADE | |
| `camera_id` | INTEGER FK → cameras ON DELETE CASCADE | |
| `name` | TEXT NOT NULL | "Loading dock" |
| `points` | JSON NOT NULL | `[[x,y], ...]` normalised, ≥3 vertices |
| `class_filter` | JSON NULL | Restrict the ROI to specific classes; NULL = all |
| `active` | BOOLEAN NOT NULL DEFAULT 1 | |
| `created_at` / `updated_at` | DATETIME NOT NULL | |

**Why normalised coordinates:** cameras get replaced and resolutions change. Storing absolute pixels means a ROI drawn on a 1920×1080 stream is silently wrong on a 1280×720 one — and it fails *quietly*, alerting on the wrong area. Normalised coordinates survive any resolution change and can be validated against a different frame size without migration.

`points` is JSON rather than a child table because it is always read and written whole; a `roi_points` table would add a join and a transaction for no query benefit. This is the one place JSON columns are right — see §7.

### 4.6 `rules`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `site_id` | INTEGER FK → sites ON DELETE CASCADE | |
| `camera_id` | INTEGER FK → cameras ON DELETE CASCADE | |
| `roi_id` | INTEGER FK → rois ON DELETE SET NULL | NULL = whole frame |
| `name` | TEXT NOT NULL | |
| `enabled` | BOOLEAN NOT NULL DEFAULT 1 | |
| `classes` | JSON NOT NULL | `["person"]` — COCO names, not indices |
| `confidence_threshold` | REAL NOT NULL DEFAULT 0.5 | CHECK 0–1 |
| `cooldown_seconds` | INTEGER NOT NULL DEFAULT 60 | Per rule, per track |
| `active_hours` | JSON NULL | See below |
| `severity` | TEXT NOT NULL DEFAULT 'warning' | `info`\|`warning`\|`critical` |
| `notify` | BOOLEAN NOT NULL DEFAULT 1 | FALSE = record only, no Telegram |
| `created_at` / `updated_at` | DATETIME NOT NULL | |

`classes` stores COCO **names**, not indices. Indices are model-specific and YOLOX and RT-DETR do not necessarily agree on ordering — storing names means switching models in the Phase 3 decision cannot silently repoint every rule at the wrong class.

`active_hours` shape:

```json
{"timezone": "Asia/Kolkata", "windows": [{"start": "22:00", "end": "06:00"}]}
```

Windows may cross midnight. The timezone is stored with the rule so a site's hours survive a global timezone change and can be inspected per rule.

### 4.7 `events`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `site_id` | INTEGER FK → sites ON DELETE CASCADE | |
| `camera_id` | INTEGER FK → cameras ON DELETE CASCADE | |
| `rule_id` | INTEGER FK → rules ON DELETE SET NULL | NULL = auto/manual, survives rule deletion |
| `triggered_by` | TEXT NOT NULL DEFAULT 'rule' | `rule`\|`manual`\|`system` |
| `started_at` | DATETIME NOT NULL | UTC, event open time |
| `ended_at` | DATETIME NULL | NULL = still open |
| `severity` | TEXT NOT NULL | Copied from the rule at trigger time |
| `summary` | TEXT NULL | "2 persons in Loading dock" |
| `thumbnail_path` | TEXT NULL | **Generated, not user input** |
| `clip_path` | TEXT NULL | **Generated, not user input** |
| `clip_bytes` | INTEGER NULL | For quota accounting |
| `duration_ms` | INTEGER NULL | |
| `delivery_status` | TEXT NOT NULL DEFAULT 'pending' | `pending`\|`sent`\|`failed`\|`skipped` |
| `delivery_attempts` | INTEGER NOT NULL DEFAULT 0 | |
| `delivered_at` | DATETIME NULL | |
| `last_delivery_error` | TEXT NULL | Credential-masked |
| `acknowledged_at` | DATETIME NULL | NULL = unacknowledged |
| `acknowledged_by` | INTEGER FK → users ON DELETE SET NULL | |
| `created_at` | DATETIME NOT NULL | UTC |

`thumbnail_path` and `clip_path` are **always constructed from `events.id`** — `clips/{id}.mp4`. Never from `camera.name`, which is user input. See [SECURITY.md §6.2](SECURITY.md).

`delivery_status` is durable and separate from the event itself. Telegram being down must never lose the event — that is exactly the "footage leaves only when the owner asked" promise in [prd.md §3](prd.md).

### 4.8 `event_detections`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `event_id` | INTEGER FK → events ON DELETE CASCADE | |
| `camera_id` | INTEGER FK → cameras ON DELETE CASCADE | |
| `class_name` | TEXT NOT NULL | COCO name |
| `confidence` | REAL NOT NULL | |
| `bbox` | JSON NOT NULL | `[x1,y1,x2,y2]` in **frame pixels** at detection time |
| `track_id` | INTEGER NULL | From the tracker |
| `zone_name` | TEXT NULL | ROI name at trigger time |
| `detected_at` | DATETIME NOT NULL | UTC |

`bbox` is stored in frame pixels, not normalised, because it is written once for display at the recorded resolution and never re-projected onto a different frame size.

### 4.9 `audit_log`

Separate from operational logs, 90-day retention. See [SECURITY.md §7.5](SECURITY.md).

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `site_id` | INTEGER FK → sites ON DELETE CASCADE | |
| `user_id` | INTEGER FK → users ON DELETE SET NULL | NULL = system |
| `action` | TEXT NOT NULL | `user.login`, `camera.update`, `roi.delete`, … |
| `entity_type` / `entity_id` | TEXT / INTEGER | |
| `details` | JSON NULL | Change summary, credential-free |
| `ip` | TEXT NULL | |
| `created_at` | DATETIME NOT NULL | Indexed |

---

## 5. Indexes

Indexes exist for the actual query patterns, not for decoration.

| Table | Index | Serves |
|---|---|---|
| `users` | `UNIQUE(site_id, username)` | Login |
| `sessions` | `expires_at` | Cleanup sweep |
| `sessions` | `user_id` | Revoke-all |
| `cameras` | `site_id` | Grid render |
| `rois` | `(camera_id, active)` | Rules evaluation |
| `rules` | `(camera_id, enabled)` | Rules evaluation |
| `events` | `(site_id, started_at DESC)` | **Event log — the hot query** |
| `events` | `(site_id, acknowledged_at)` | Unacknowledged badge |
| `events` | `(site_id, severity, started_at DESC)` | Filtered log |
| `events` | `delivery_status` | Retry sweep for `pending`/`failed` |
| `event_detections` | `event_id` | Event detail |
| `audit_log` | `(site_id, created_at DESC)` | Audit view |
| `audit_log` | `created_at` | Retention sweep |

**The `(site_id, started_at DESC)` composite matters most.** The event log is the only query that runs at scale, and its natural access pattern is "this site's events, newest first." Leading `site_id` serves the tenant scope; trailing `started_at DESC` lets SQLite read the index backwards for pagination without a temp b-tree.

---

## 6. Encrypted columns

Fernet ciphertext, DPAPI-wrapped master key. See [SECURITY.md §3](SECURITY.md).

| Column | Plaintext |
|---|---|
| `cameras.rtsp_username` | Camera username |
| `cameras.rtsp_password_enc` | Camera password |
| `sites.notifier_config` → `bot_token_enc` | Telegram bot token |

**`rtsp_url` stores no credentials.** The full URL is assembled in memory only when a source connects, and masked everywhere else. So the column is safe to select, display, export, and log.

Ciphertext is ~1.35× plaintext plus 22 bytes of nonce and tag — negligible at this scale.

---

## 7. JSON columns

JSON is used for exactly two shapes, both of which are read and written whole:

- `rois.points` — a vertex list
- `rules.classes`, `rules.active_hours` — small config objects

**Justification:** a `roi_points` table would need a join on every rules evaluation and a transaction on every drag of a vertex, to serve no query that doesn't want the whole list. Everything else is a proper column or a child table — `event_detections` gets a real table because detections are queried by event and grow unboundedly.

**SQLite JSON functions (1.38+) are available** if filtering inside a JSON array is ever needed, but such a filter should be a signal to add a column, not a clever query.

---

## 8. Retention

**Deletions are batched.** A `DELETE FROM events WHERE site_id = ? AND started_at < ?` on a busy box can match tens of thousands of rows and hold a write lock long enough to stall the pipelines. Batching — `LIMIT 500` per transaction, with a short sleep between batches — keeps the dashboard responsive and the writers unblocked.

Order matters: deleting an event cascades to its detections, so detection rows go with it and are never orphaned.

Clip files are removed alongside their rows, with the file unlinked before the row is committed. A crash between the two leaves an orphaned file, which the quota sweep in §9 reclaims.

---

## 9. Disk quota

Clips are the only unbounded consumer of disk on a 128GB box.

```
used_pct = used_bytes / total_bytes * 100
if used_pct >= site.disk_quota_pct:
    → refuse new clip writes
    → emit a system event of severity 'critical'
    → notify admin via Telegram
```

**The refusal path is deliberate.** Filling the customer's disk breaks the NVR that records their evidence — the exact failure CamBrain exists to prevent. Losing an event clip is recoverable; losing the recording is not.

An orphan sweep deletes files older than 24h with no matching row.

---

## 10. Migrations

**Alembic only.** No `CREATE TABLE` outside a migration, no hand-edited SQLite.

```bash
alembic revision --autogenerate -m "add event_detections"
alembic upgrade head
```

Rules:

- Forward-only. Every migration must apply cleanly to a populated database.
- **Never edit a shipped migration** — add a new one. Editing breaks any customer already on the old revision.
- Every migration gets a tested `downgrade()`, or an explicit comment saying why it is irreversible.
- Schema changes that touch `sites`, `cameras`, or `users` are reviewed for tenant-scope implications before merge. A missing `site_id` on a new table is the highest-impact schema mistake available here.

---

## 11. Backups

A `.db` file plus its `-wal` and `-shm` siblings. Copy all three, or use `sqlite3 cambrain.db ".backup"`.

**Video is not backed up** — the customer's NVR already holds that, and duplicating it is out of scope. A CamBrain backup restores configuration (cameras, ROIs, rules, users, notifier tokens) and the event index, which is what makes re-provisioning a replacement box fast. That's the real value for the installer: config portability, not footage portability.

Config export over the API is the installer-facing version of this and ships in Phase 2.

---

## 12. Schema change checklist

- [ ] New table has `site_id` with `ON DELETE CASCADE`
- [ ] New FK has an explicit `ON DELETE` behaviour — never left to default
- [ ] Index added for the actual query, with `site_id` leading
- [ ] No secret stored in plaintext
- [ ] Coordinates normalised, not absolute pixels
- [ ] Classes stored as names, not indices
- [ ] Downgrade written or irreversibility documented
- [ ] Migration tested against a populated copy, not an empty DB
- [ ] Retention applies to the new table
- [ ] Cross-tenant access returns `404`, tested
