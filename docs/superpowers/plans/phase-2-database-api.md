# CamBrain Phase 2 — Database + REST API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Note for this repo:** SDD is suspended (human directive, recorded in the Phase 0/1 ledger). Execution is performed directly by the controller with review between tasks.

**Goal:** Build the persistence and REST layers — SQLite (WAL) engine, SQLAlchemy 2.0 models for all nine tables, Alembic migration, tenant-scoped repositories, Argon2+JWT auth, and the FastAPI surface for auth/cameras/ROIs/rules/events/users/settings/system — so CRUD works, cross-tenant access returns 404, and the OpenAPI spec matches `API.md`.

**Architecture:** One process. Every table carries `site_id` taken from the auth token, never the request. SQLAlchemy 2.0 `select()` only; access is confined to a repository layer so a future fleet console can swap in PostgreSQL without touching the edge box (spec §6.1). FastAPI on `127.0.0.1:8765`, base path `/api/v1`. Errors share one envelope. Secrets encrypted at rest via Fernet/DPAPI (`app.core.crypto`); `rtsp_url` stores no credentials; clip/thumbnail paths derive from `events.id`, never user input. Everything is testable with a temp SQLite file and no cameras (spec §11.1); the OpenAPI contract is generated from the implementation and asserted against `API.md`.

**Tech Stack:** Python 3.13 · SQLAlchemy 2.0 (`SQLAlchemy==2.1.4`) · Alembic (`alembic==1.20.0`) · SQLite (WAL) · argon2-cffi (`argon2-cffi==25.1.0`) · cryptography/Fernet (already present) · FastAPI + Uvicorn (`fastapi==0.143.0`, `uvicorn==0.54.0`) · Pydantic + pydantic-settings (`pydantic==2.14.0`, `pydantic-settings==2.15.0`) · structlog · httpx (test client). **No dependency changes — `requirements.lock.txt` is untouched in this phase** (every package above is already in the lock).

**Spec:** [`docs/superpowers/specs/spec.md`](../specs/spec.md) — §6 (database), §7 (API), §8 (security), §10.2 (build order), §11 (tests), §12 (verification matrix). Living docs: [`docs/DATABASE.md`](../../DATABASE.md) (schema), [`docs/API.md`](../../API.md) (endpoints), [`docs/SECURITY.md`](../../SECURITY.md) (auth, secrets, CSRF), [`docs/CODE_STYLE.md`](../../CODE_STYLE.md) (SQLAlchemy 2.0 style).

**Execution note:** implement this on a new branch `phase-2-database-api` off `phase-1-streaming` (or off `main` once the Phase 0 PR merges — the Phase 1 branch ends at commit `8cf4377`; do not mix Phase 2 onto `phase-1-streaming`).

---

## Global Constraints

These apply to every task; each task's requirements implicitly include this block.

- **Licensing — hard constraint, CI-enforced:** no AGPL dependency in any form. This phase adds no packages, so the licence scan is unaffected.
- **Stack floors (from the lock, already installed):** SQLAlchemy 2.0, Alembic, argon2-cffi, cryptography, FastAPI, Uvicorn, Pydantic, pydantic-settings, structlog, httpx. Python 3.13.
- **Language/type rules:** Python line length 100; type hints on every signature; **no `Any` outside tests and protocol boundaries**; Google-style docstrings on every public function; every module has a module docstring. `mypy --strict` runs on `backend/app` only (Alembic `migrations/` is excluded by `pyproject.toml`).
- **SQLAlchemy 2.0 style (CODE_STYLE §6.1):** `select()` / `Session` API only. No legacy `Query`, no string-built SQL. Parameterise every `dict`/`list` type.
- **Migrations (DATABASE §10, CODE_STYLE §6.3):** Alembic only. Forward-only. Never edit a shipped migration; add a new one. Every migration gets a tested `downgrade()` or an explicit irreversibility comment. Tested against a **populated** copy, not an empty DB.
- **Tenancy (spec §6.4, SECURITY §4.3):** every domain table carries `site_id` with `ON DELETE CASCADE`. `site_id` comes from the auth token, never the body or query. Cross-tenant access returns **404, never 403**. Enforced at the repository base class. Every FK has an explicit `ON DELETE`.
- **Secrets:** Fernet-encrypted at rest, DPAPI-wrapped master key (`app.core.crypto`). `rtsp_url` stores **no credentials** (separate `rtsp_username` / `rtsp_password_enc` columns). No secret is ever returned by a `GET` (use `has_password` + masked `••••••••`). RTSP URLs masked (`rtsp://***:***@host:port/path`) in logs, errors, and responses. `REDACT_KEYS` redaction lives in the structlog chain and cannot be bypassed.
- **CSRF (API §1, SECURITY §4.5):** every route requires auth. Mutating requests require `Content-Type: application/json` **and** `X-CambBrain-Client`. No CORS wildcard; localhost allowlist only. Origin/Referer validated.
- **Error envelope (API §4):** one shape — `{"error": {"code", "message", "field", "correlation_id"}}`. Codes: `BAD_REQUEST`, `UNAUTHENTICATED`, `FORBIDDEN`, `NOT_FOUND`, `CONFLICT`, `VALIDATION_ERROR`, `ACCOUNT_LOCKED`, `RATE_LIMITED`, `INTERNAL`, `NO_CAPACITY`.
- **No cameras (spec §11.1):** no test may require a camera. Repository and API tests use a temp SQLite file and `httpx.ASGITransport` / FastAPI `TestClient`. Long-running tests marked `slow`.
- **Conventions:** Conventional Commits, scope `db`/`api`/`auth` (not `stream`); commit messages explain *why*. Never commit: weights, `.env`, `cambrain.db`, clips, `node_modules/`, build output. The `test_no_secret_in_log_output` canary stays green.
- **Async:** the API layer is async; SQLAlchemy work runs via `asyncio.to_thread` or the sync `Session` bound to a per-request session factory. Blocking DB calls are wrapped so the linter's `ASYNC` rules stay clean.

---

## File Structure (Phase 2 slice)

```
backend/app/__init__.py                       EXISTING (empty)
backend/app/core/config.py                    CREATE  Settings (pydantic-settings): db path, bind, key dir, secret
backend/app/db/__init__.py                    CREATE  (empty)
backend/app/db/base.py                        CREATE  DeclarativeBase
backend/app/db/session.py                     CREATE  engine (WAL pragmas), SessionLocal, get_session dependency
backend/app/db/models/__init__.py             CREATE  re-export every model
backend/app/db/models/site.py                 CREATE  Site
backend/app/db/models/user.py                 CREATE  User, Session (login sessions)
backend/app/db/models/camera.py               CREATE  Camera
backend/app/db/models/roi.py                  CREATE  Roi
backend/app/db/models/rule.py                 CREATE  Rule
backend/app/db/models/event.py                CREATE  Event, EventDetection, AuditLog
backend/app/db/repositories/__init__.py       CREATE  (empty)
backend/app/db/repositories/base.py           CREATE  TenantScopedRepository (site_id required)
backend/app/db/repositories/cameras.py        CREATE  CameraRepository
backend/app/db/repositories/rois.py           CREATE  RoiRepository
backend/app/db/repositories/rules.py          CREATE  RuleRepository
backend/app/db/repositories/events.py         CREATE  EventRepository
backend/app/api/__init__.py                   CREATE  (empty)
backend/app/api/deps.py                       CREATE  auth dependency, require_role, get_session
backend/app/api/schemas.py                    CREATE  Pydantic request/response models
backend/app/api/routers/__init__.py           CREATE  (empty)
backend/app/api/routers/auth.py               CREATE  login, refresh, logout, me, change-password
backend/app/api/routers/cameras.py            CREATE  list, create, get, patch, delete, test, snapshot, stream
backend/app/api/routers/rois.py               CREATE  list, create, get, patch, delete
backend/app/api/routers/rules.py              CREATE  list, create, get, patch, delete (soft), test
backend/app/api/routers/events.py             CREATE  list, get, acknowledge, bulk-ack, clip, stats
backend/app/api/routers/users.py              CREATE  list, create, patch, delete (last-admin guard)
backend/app/api/routers/settings.py           CREATE  get, patch settings + notifiers CRUD + test
backend/app/api/routers/system.py             CREATE  status, health, config
backend/app/api/errors.py                     CREATE  exception handlers -> error envelope
backend/app/api/middleware.py                 CREATE  CSRF (X-CambBrain-Client + Content-Type + Origin), correlation id
backend/app/main.py                           CREATE  app factory, lifespan, CORS, routers, OpenAPI at /api/v1

backend/tests/conftest.py                     MODIFY  add db fixtures (tmp engine, seeded site/users, TestClient)
backend/tests/test_config.py                  CREATE  Settings defaults + env override
backend/tests/test_db_session.py              CREATE  WAL/pragma wiring, FK enforcement
backend/tests/test_repositories.py            CREATE  cross-tenant 404, CRUD, soft delete
backend/tests/test_api_auth.py                CREATE  login/refresh/logout/me/lockout, Argon2 verify
backend/tests/test_api_cameras.py             CREATE  CRUD, secret masking, PATCH semantics, site_id not accepted
backend/tests/test_api_rois.py                CREATE  CRUD, normalised coords validation, viewer read-only
backend/tests/test_api_rules.py               CREATE  CRUD, soft delete, active_hours wrap, roi_id same-camera
backend/tests/test_api_events.py              CREATE  list/filter/paginate, acknowledge, stats
backend/tests/test_api_users.py               CREATE  CRUD, last-admin protection 409
backend/tests/test_api_system.py              CREATE  health (no auth), status, openapi_matches_spec
backend/tests/test_api_settings.py            CREATE  settings + notifier CRUD
backend/tests/test_errors.py                  MODIFY  (existing) keep green
backend/tests/test_crypto.py                  MODIFY  (existing) keep green
backend/tests/test_logging.py                 MODIFY  (existing) keep green

backend/alembic.ini                           CREATE  Alembic config (script_location = migrations)
backend/migrations/env.py                     CREATE  target_metadata = Base.metadata, offline/online runners
backend/migrations/script.py.mako             CREATE  standard template
backend/migrations/versions/0001_initial.py   CREATE  all nine tables, indexes, downgrade
```

One responsibility per file. Models are split by table; repositories by entity; routers by the `API.md` section headers.

---

## Verification matrix (Phase 2 rows from spec §12)

| Requirement | Proving test (this phase) | Markers |
|---|---|---|
| **Cross-tenant 404** | `test_repositories.py::test_cross_tenant_read_returns_404` | — |
| Tenant scoping on every route | `test_api_cameras.py::test_cannot_pass_site_id` | — |
| Auth — Argon2, JWT, revocation | `test_api_auth.py` (login, refresh rotation, logout revokes, reuse detection) | — |
| Last-admin protection | `test_api_users.py::test_cannot_delete_last_admin` | — |
| Secrets never in API responses | `test_api_cameras.py::test_get_never_returns_password` | — |
| `viewer` cannot write | `test_api_rois.py::test_viewer_is_read_only` | — |
| OpenAPI matches `API.md` | `test_api_system.py::test_openapi_matches_spec` | — |
| Error envelope shape | `test_errors.py` + every API test asserting `{"error": ...}` | — |
| CSRF / mutating headers | `test_api_cameras.py::test_mutating_requires_client_header` | — |
| WAL + FK pragmas | `test_db_session.py::test_wal_and_foreign_keys_enabled` | — |
| Alembic migrate up/down on populated DB | `test_db_session.py::test_migration_up_down_on_populated` | `slow` |
| CRUD works (cameras, rois, rules, events, users) | each `test_api_*.py` happy-path create/read/update/delete | — |

---

## Definition of done (spec §13)

1. Every test named above exists and passes.
2. The gate is demonstrated: CRUD works, cross-tenant 404 observed, OpenAPI endpoint list matches `API.md` (not assumed).
3. `ruff check` and `mypy backend/app` are clean; `ruff format --check backend` passes.
4. Every new public function has a Google-style docstring; every module has a module docstring.
5. No secret is logged, returned by an API, or stored in plaintext — verified by test, not inspection.
6. `git status` shows no weights, database files, clips, or `.env`.
7. Commit messages explain **why**.

---

## Task 2.1: Config and the SQLite engine (WAL, FK, busy_timeout)

**Files:**
- Create: `backend/app/core/config.py`
- Create: `backend/app/db/__init__.py`, `backend/app/db/session.py`
- Create: `backend/tests/test_config.py`, `backend/tests/test_db_session.py`
- Modify: `backend/tests/conftest.py` (add `settings` / `engine` / `session` fixtures)

**Interfaces:**
- Consumes: `app.core.errors.StorageError`; existing `app.core.crypto` for key-dir resolution.
- Produces:
  - `Settings` (pydantic-settings): `db_path`, `bind_host`, `bind_port`, `key_dir`, `secret_key_file`, `cors_origins`, `access_token_ttl_s`, `refresh_token_ttl_s`.
  - `create_engine_for(db_path) -> Engine` — WAL, `synchronous=NORMAL`, `foreign_keys=ON`, `busy_timeout=30000`, `QueuePool` size 5 / overflow 5, `check_same_thread=False`.
  - `SessionLocal` factory, `get_session()` FastAPI dependency.
  - Test fixtures: `settings` (tmp path), `engine` (fresh per test), `db_session`, `client` (TestClient with seeded site + admin/viewer users).

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_config.py`:
```python
"""Settings defaults and environment overrides (spec §8.1)."""
from __future__ import annotations
from app.core.config import Settings
import os

def test_defaults_bind_localhost() -> None:
    s = Settings(_env_file=None)
    assert s.bind_host == "127.0.0.1"
    assert s.bind_port == 8765

def test_env_override(monkeypatch) -> None:
    monkeypatch.setenv("CAMBRAIN_BIND_ALL", "1")
    monkeypatch.setenv("CAMBRAIN_DB_PATH", ":memory:")
    s = Settings()
    assert s.bind_host == "0.0.0.0" or s.bind_all is True
```

`backend/tests/test_db_session.py`:
```python
"""Engine pragmas and migration up/down (DATABASE §1, §10)."""
from __future__ import annotations
import pytest
from sqlalchemy import text
from app.db.session import create_engine_for, SessionLocal

def test_wal_and_foreign_keys_enabled(tmp_path) -> None:
    eng = create_engine_for(tmp_path / "t.db")
    with eng.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
        assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
        assert conn.exec_driver_sql("PRAGMA busy_timeout").scalar() == 30000
    eng.dispose()

def test_fk_enforcement_rejects_orphan(tmp_path) -> None:
    # Insert a camera with a bogus site_id -> IntegrityError (spec §2: FK ON).
    ...
```

- [ ] **Step 2: Run to verify they fail** — `pytest backend/tests/test_config.py backend/tests/test_db_session.py -v` → `ModuleNotFoundError: No module named 'app.core.config'`.
- [ ] **Step 3: Implement**

`backend/app/core/config.py`:
```python
"""Runtime settings (pydantic-settings). Binds, paths, TTLs.

Owns: where the DB and keys live, how the server binds. Does not own:
domain defaults like retention (those live on the Site row).
"""
from __future__ import annotations
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CAMBRAIN_", env_file=".env", extra="ignore")

    bind_host: str = "127.0.0.1"
    bind_port: int = 8765
    bind_all: bool = False  # CAMBRAIN_BIND_ALL=1 -> 0.0.0.0 + WARN at startup
    db_path: Path = Path("%LOCALAPPDATA%/CamBrain/cambrain.db")
    key_dir: Path | None = None
    cors_origins: list[str] = ["http://127.0.0.1:5173", "http://localhost:5173"]
    access_token_ttl_s: int = 43200
    refresh_token_ttl_s: int = 604800
    jwt_secret_file: Path | None = None

settings = Settings()
```

`backend/app/db/session.py`:
```python
"""Engine, session factory, and the connect-time pragmas that matter (DATABASE §1).

WAL lets the API read while a pipeline writes. foreign_keys=ON is mandatory —
SQLite disables FK enforcement by default, leaving the schema decorative.
"""
from __future__ import annotations
from collections.abc import Iterator
from pathlib import Path
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import QueuePool
from app.core.config import settings

def create_engine_for(db_path: Path | str):
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 30.0},
        poolclass=QueuePool, pool_size=5, max_overflow=5,
    )
    @event.listens_for(engine, "connect")
    def _configure(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.close()
    return engine

engine = create_engine_for(settings.db_path)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

def get_session() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
```

- [ ] **Step 4: Run to verify they pass.**
- [ ] **Step 5: Static checks + commit.** `ruff check backend; ruff format --check backend; mypy backend/app`. Commit: `feat(db): add settings and the WAL SQLite engine` (body: WAL + FK + busy_timeout are the three pragmas that make a single-file DB usable under concurrent read/write; documented DATABASE §1).

---

## Task 2.2: SQLAlchemy models for all nine tables

**Files:**
- Create: `backend/app/db/base.py`, `backend/app/db/models/{__init__,site,user,camera,roi,rule,event}.py`
- Modify: `backend/tests/test_repositories.py` (schema assertions, CHECK constraints, JSON columns)

**Interfaces:**
- Consumes: `DeclarativeBase` pattern; `app.core.crypto.encrypt/decrypt` for secret columns.
- Produces: `Site`, `User`, `Session` (login), `Camera`, `Roi`, `Rule`, `Event`, `EventDetection`, `AuditLog` — each with mapped columns, `Mapped[...]` types, `ON DELETE` behaviours, and the indexes from DATABASE §5.

Key constraints encoded in the models (DATABASE §4):
- `users`: `UNIQUE(site_id, username)`, `role` CHECK `admin|viewer`.
- `cameras`: `sample_fps` CHECK 0.1–10; `rtsp_url` TEXT (no creds); `rtsp_username`/`rtsp_password_enc` separate; `status` CHECK `starting|live|offline|error`.
- `rois`: `points` JSON normalised 0..1, ≥3 vertices (validated in API); `class_filter` JSON nullable.
- `rules`: `classes` JSON of COCO **names**; `confidence_threshold` CHECK 0–1; `active_hours` JSON (windows may cross midnight); `roi_id` FK SET NULL.
- `events`: `rule_id` FK SET NULL; `triggered_by` CHECK `rule|manual|system`; `thumbnail_path`/`clip_path` generated from `events.id`; `delivery_status` CHECK; `acknowledged_by` FK SET NULL.
- `event_detections`: `bbox` JSON pixels; `event_id` FK CASCADE.
- `audit_log`: `details` JSON credential-free; indexed `(site_id, created_at DESC)`.

- [ ] **Step 1: Write failing tests** — create each model, assert column presence, assert `UNIQUE(site_id, username)` rejects a duplicate, assert role CHECK rejects `'root'`, assert JSON round-trips for `points`/`classes`/`active_hours`.
- [ ] **Step 2: Verify fail.**
- [ ] **Step 3: Implement models** (full column definitions per DATABASE §4; each model class docstring states what it owns and what it deliberately does not — e.g. `Camera` "owns config and status; deliberately does not own the RTSP connection — that is `RtspSource`").
- [ ] **Step 4: Verify pass.**
- [ ] **Step 5: Static checks + commit.** `feat(db): add the nine-table SQLAlchemy schema` (body: every domain table carries site_id + explicit ON DELETE; classes stored as names not indices so a model change cannot repoint rules).

---

## Task 2.3: Alembic initial migration

**Files:**
- Create: `backend/alembic.ini`, `backend/migrations/env.py`, `backend/migrations/script.py.mako`, `backend/migrations/versions/0001_initial.py`
- Modify: `backend/tests/test_db_session.py` (add up/down on populated DB)

**Interfaces:**
- Consumes: `Base.metadata` from Task 2.2.
- Produces: a single `0001_initial` revision creating all tables + indexes; `downgrade()` drops them (tested on a **populated** DB — seed a site/camera/rule/event, downgrade, re-upgrade, assert data intact).

- [ ] **Step 1: Write failing test** `test_migration_up_down_on_populated` (marked `slow`): upgrade head, seed, downgrade base, upgrade head again, assert empty then re-seedable.
- [ ] **Step 2: Verify fail.**
- [ ] **Step 3: Generate + review the migration.** Run `alembic revision --autogenerate -m "initial schema"`, then `alembic upgrade head`. Verify every table, every FK `ondelete`, every CHECK, every index matches DATABASE §4–5. Hand-correct the autogenerate output where it diverges (SQLite CHECK/JSON nuances).
- [ ] **Step 4: Verify pass.**
- [ ] **Step 5: Static checks + commit.** `feat(db): add the initial Alembic migration` (body: forward-only baseline; downgrade is a clean drop because no customer data exists yet).

---

## Task 2.4: Tenant-scoped repositories

**Files:**
- Create: `backend/app/db/repositories/{__init__,base,cameras,rois,rules,events}.py`
- Create/Modify: `backend/tests/test_repositories.py`

**Interfaces:**
- Consumes: models from Task 2.2; `NotFoundError` from `app.core.errors`.
- Produces:
  - `TenantScopedRepository[T](session, site_id)` — base; every method requires `site_id`; `_get_or_404(model, id)` raises `NotFoundError` on miss **or** wrong tenant (the 404-not-403 rule, SECURITY §4.3).
  - `CameraRepository`, `RoiRepository`, `RuleRepository` (soft-delete `deleted_at` for rules), `EventRepository`.

- [ ] **Step 1: Write failing tests** — `test_cross_tenant_read_returns_404` (the matrix row), CRUD round-trips, soft-delete hides from default list, `get_or_404` never leaks existence across tenants.
- [ ] **Step 2: Verify fail.**
- [ ] **Step 3: Implement** base + four repositories.
- [ ] **Step 4: Verify pass.**
- [ ] **Step 5: Static checks + commit.** `feat(db): add tenant-scoped repositories` (body: site_id is required on every query so a fleet console can reuse the same repositories; a 403 would confirm a row exists, so tenancy violations surface as NotFoundError).

---

## Task 2.5: Auth — Argon2, JWT, sessions, refresh rotation

**Files:**
- Create: `backend/app/api/deps.py`, `backend/app/api/routers/auth.py`, `backend/app/api/schemas.py` (auth portion)
- Create: `backend/tests/test_api_auth.py`
- Modify: `backend/tests/conftest.py` (seed users, expose `auth_headers` fixtures for admin and viewer)

**Interfaces:**
- Consumes: repositories; `app.core.crypto` (JWT signing key via DPAPI); `argon2-cffi` for hashing.
- Produces:
  - `hash_password` / `verify_password` (Argon2id, m=64MB t=3 p=4).
  - JWT access token (HS256, 12h) with claims `sub`, `site_id`, `role`, `jti`, `exp`.
  - Opaque refresh token (7d), stored **hashed**, rotated on use, reuse detection revokes the family.
  - `POST /auth/login` (5/min per username, then lockout → 423), `/auth/refresh`, `/auth/logout`, `GET /auth/me`, `POST /auth/change-password`.
  - `require_role("admin")` dependency for admin-only routes.

- [ ] **Step 1: Write failing tests** — login happy path, wrong password → 401, lockout after 5 → 423, refresh rotates and returns new pair, presenting an already-rotated refresh revokes the family, `me` returns site+role, logout revokes session, `viewer` cannot call admin route → 403.
- [ ] **Step 2: Verify fail.**
- [ ] **Step 3: Implement** deps + schemas + auth router + middleware (CSRF header/content-type/origin + correlation id).
- [ ] **Step 4: Verify pass.**
- [ ] **Step 5: Static checks + commit.** `feat(auth): add Argon2+JWT auth with revocable sessions` (body: a stateless JWT cannot be revoked before exp; for a security product that matters — the sessions table is what makes "sign out everywhere" real).

---

## Task 2.6: Cameras API

**Files:**
- Modify: `backend/app/api/schemas.py` (camera schemas)
- Create: `backend/app/api/routers/cameras.py`
- Create/Modify: `backend/tests/test_api_cameras.py`

**Interfaces:**
- Consumes: `CameraRepository`; `app.services.stream.rtsp_source.probe_rtsp` (Task 1.4, for `/test`); `app.core.crypto` for encrypting `password` on create/patch.
- Produces: `GET/POST /cameras`, `GET/PATCH/DELETE /cameras/{id}`, `POST /cameras/{id}/test` (200 + `ok:false` on failure with `error_code`), `POST /cameras/{id}/snapshot`, `GET /cameras/{id}/stream` (MJPEG; Phase 5 wires real frames — for now a stub that 501s or streams a placeholder JPEG, clearly marked). PATCH semantics: omit `password` = unchanged, `null` = clear, `""` = 422. Responses never include `username` or the real password (`has_password` flag instead).

- [ ] **Step 1: Write failing tests** — create returns 201 with masked password and `has_password`; `GET` never leaks password (`test_get_never_returns_password`); `test_cannot_pass_site_id` (body-supplied `site_id` is ignored, token's wins); PATCH omit/`null`/`""` semantics; `/test` returns 200+`ok:false`+`error_code` for an unreachable URL; viewer read-only on writes; mutating request without `X-CambBrain-Client` → 403.
- [ ] **Step 2: Verify fail.**
- [ ] **Step 3: Implement** schemas + router.
- [ ] **Step 4: Verify pass.**
- [ ] **Step 5: Static checks + commit.** `feat(api): add cameras CRUD with secret masking` (body: the URL is safe to log/display because credentials live in separate encrypted columns; /test is the installer's first impression and must fail usefully with a typed error_code).

---

## Task 2.7: ROIs + Rules APIs

**Files:**
- Modify: `backend/app/api/schemas.py`
- Create: `backend/app/api/routers/{rois,rules}.py`
- Create: `backend/tests/test_api_rois.py`, `backend/tests/test_api_rules.py`

**Interfaces:**
- Consumes: `RoiRepository`, `RuleRepository`.
- Produces: full CRUD for ROIs (normalised 0..1 validation, ≥3 vertices, `coverage_pct` computed) and rules (soft delete, `classes` COCO-name validation, `active_hours` midnight-wrap validation, `roi_id` must belong to the same camera else 422, `POST /rules/{id}/test` returning per-condition `checks`).

- [ ] **Step 1: Write failing tests** — ROI out-of-range → 422; `coverage_pct` matches polygon area; rule with wrap window (22:00→06:00) accepted; `start==end` rejected; `roi_id` from another camera → 422; soft-deleted rule hidden from list but still referenced by events; `test_viewer_is_read_only`.
- [ ] **Step 2: Verify fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Verify pass.**
- [ ] **Step 5: Static checks + commit.** `feat(api): add ROIs and rules with normalised geometry` (body: normalised coordinates survive a resolution change; class names not indices so a Phase 3 model swap cannot silently repoint every rule).

---

## Task 2.8: Events + Users + Settings/System APIs

**Files:**
- Modify: `backend/app/api/schemas.py`
- Create: `backend/app/api/routers/{events,users,settings,system}.py`
- Create: `backend/tests/{test_api_events,test_api_users,test_api_system,test_api_settings}.py`

**Interfaces:**
- Consumes: repositories; `probe_rtsp` for status; `app.core.config`.
- Produces:
  - Events: `GET /events` with filters (`camera_id`, `severity`, `from`/`to`, `acknowledged`, `q`, `limit`≤200, `offset`, `sort`), `GET /events/{id}`, `POST /events/{id}/acknowledge`, `POST /events/acknowledge-bulk`, `GET /events/{id}/clip` (404 when absent), `GET /events/stats`.
  - Users: admin-only CRUD; `test_cannot_delete_last_admin` (409).
  - Settings: `GET/PATCH /settings`, notifiers CRUD + `POST /notifiers/test`.
  - System: `GET /system/health` (**no auth**, `{status, version, uptime_s}`), `GET /system/status`, `GET/POST /system/config`. `test_openapi_matches_spec` asserts the generated `/api/v1/openapi.json` path list equals `API.md`'s endpoint table.

- [ ] **Step 1: Write failing tests** (matrix rows: last-admin 409, openapi match, health unauthenticated, event pagination caps, acknowledge).
- [ ] **Step 2: Verify fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Verify pass.**
- [ ] **Step 5: Static checks + commit.** `feat(api): add events, users, settings, and system routes` (body: last-admin protection is two lines that prevent locking the owner out of their own box; health stays unauthenticated so the Tauri shell and installer can poll it).

---

## Task 2.9: Error envelope, middleware, app factory, and the full-suite gate

**Files:**
- Create: `backend/app/api/{errors,middleware}.py`, `backend/app/main.py`
- Modify: `backend/tests/conftest.py` (wired app), add `backend/tests/test_csrf.py` if not covered above
- Re-run: full `pytest -m "not rtsp and not slow"`; `pytest -m rtsp` (must stay green); `pytest -m slow`

**Interfaces:**
- Consumes: every router; `configure_logging`; `Settings`.
- Produces: `create_app()` factory with lifespan (init logging, ensure master key, run migration if needed), CORS localhost allowlist, correlation-id middleware, global exception handler mapping `CamBrainError` subclasses → the error envelope, routers mounted under `/api/v1`, OpenAPI served at `/api/v1/openapi.json` and docs at `/api/v1/docs`.

- [ ] **Step 1: Write failing tests** — 500 paths return the envelope with a correlation id and no stack trace; 404 unknown route returns envelope; CSRF middleware blocks a mutating request missing `X-CambBrain-Client` or with a non-JSON content type; OpenAPI reachable.
- [ ] **Step 2: Verify fail.**
- [ ] **Step 3: Implement** errors.py, middleware.py, main.py.
- [ ] **Step 4: Verify pass.**
- [ ] **Step 5: Full gate** — observe every row of the verification matrix and Definition of done; append the Phase 2 ledger to `.superpowers/sdd/phase-2-database-api/progress.md` (gitignored); report the gate demonstration before any Phase 3 work.

---

## Checkpoint: After Tasks 2.1–2.4 (persistence foundation)

- [ ] `pytest backend/tests/test_db_session.py backend/tests/test_repositories.py` green
- [ ] Alembic `upgrade head` + `downgrade base` clean on a populated DB
- [ ] ruff + mypy clean
- [ ] Review with human before the API layer

## Checkpoint: After Task 2.9 (full Phase 2 gate)

- [ ] `pytest -m "not rtsp and not slow"` fully green (all Phase 0+1+2 tests)
- [ ] `pytest -m rtsp` green (Phase 1 canaries unaffected)
- [ ] CRUD demonstrated end-to-end via the OpenAPI docs page
- [ ] Cross-tenant 404 observed on every entity route
- [ ] `test_openapi_matches_spec` observed passing
- [ ] Human confirms gate before Phase 3

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| SQLite CHECK/JSON not fully expressed by Alembic autogenerate | Schema drift between models and migration | Review `0001_initial.py` by hand against DATABASE §4–5; assert in a test that `Base.metadata` and the migrated DB agree on table/column names |
| Argon2 m=64MB is slow in tests | Slow suite | Hash once in a module-scoped fixture for the seeded users; never re-hash per test |
| Async SQLAlchemy vs sync `Session` confusion | ASYNC lint failures, blocking the loop | Wrap sync `Session` work in `asyncio.to_thread` at the dependency boundary; keep repositories sync and pure |
| `/cameras/{id}/stream` MJPEG not wired to real frames | Misleading stub | Implement as an explicit `501` with a clear message until Phase 5, so it cannot be mistaken for a working stream |
| OpenAPI drift from `API.md` | Spec trusted more than code | `test_openapi_matches_spec` is a matrix row — it fails the gate if any route is added/removed without updating `API.md` |

## Open Questions

- None blocking. The `POST /cameras/{id}/snapshot` and `GET .../stream` real-frame sources are Phase 4/5 concerns; this phase ships the route contracts with a documented stub.
