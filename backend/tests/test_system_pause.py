"""System pause API + runtime lifecycle tests (D6-6, phase-6-packaging).

"Pause detection" is the installer's panic button (design.md §tray): one
endpoint stops every runtime chain (sources, rings, alert stages, delivery
worker), resume brings it all back, and repeated cycles must not leak loops
or handlers. Admin-only; every transition leaves a per-site system event for
the audit trail.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import numpy as np
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import AuditLog, Camera, Site, User
from app.services.runtime import Runtime
from app.services.stream.source import Frame


class FakeDetector:
    async def close(self) -> None:
        return


class FakeSource:
    """An indefinite stream whose yield count proves liveness deterministically."""

    def __init__(self) -> None:
        self.yielded = 0
        self.closed = False

    async def frames(self) -> Any:
        try:
            tick = 0.0
            while True:
                tick += 1.0
                yield Frame(
                    data=np.zeros((36, 64, 3), dtype=np.uint8),
                    timestamp=tick,
                    width=64,
                    height=36,
                )
                self.yielded += 1
                await asyncio.sleep(0.005)
        finally:
            self.closed = True

    async def close(self) -> None:
        self.closed = True


def _factory(db_session: Session) -> Callable[[], Session]:
    return sessionmaker(bind=db_session.get_bind(), autoflush=False, expire_on_commit=False)


async def _wait_until(cond: Callable[[], bool], *, timeout_s: float = 5.0) -> bool:
    """Poll until cond or the timeout; fixed sleeps flake under suite load."""
    deadline = asyncio.get_running_loop().time() + timeout_s
    while asyncio.get_running_loop().time() < deadline:
        if cond():
            return True
        await asyncio.sleep(0.05)
    return cond()


def _camera(db_session: Session, seeded: tuple[Site, User, User]) -> Camera:
    site, _admin, _viewer = seeded
    camera = Camera(
        site_id=site.id,
        name="Pause cam",
        rtsp_url="rtsp://example.invalid/stream",
        sample_fps=5.0,
        enabled=True,
    )
    db_session.add(camera)
    db_session.commit()
    return camera


# -- Runtime lifecycle ------------------------------------------------------


async def test_pause_resume_cycles_without_leak(
    db_session: Session, seeded: tuple[Site, User, User]
) -> None:
    _camera(db_session, seeded)
    sources: list[FakeSource] = []

    def make(_config: object) -> FakeSource:
        source = FakeSource()
        sources.append(source)
        return source

    runtime = Runtime(
        session_factory=_factory(db_session),
        enabled=True,
        detector_factory=lambda **_kw: FakeDetector(),
        source_factory=make,
    )
    await asyncio.wait_for(runtime.start(), timeout=10)
    assert await _wait_until(lambda: len(sources) == 1 and sources[0].yielded >= 3), (
        f"no flow: counts={[(s.yielded, s.closed) for s in sources]} "
        f"status={runtime._manager.status_all() if runtime._manager else None}"
    )

    await asyncio.wait_for(runtime.pause(), timeout=10)
    await asyncio.sleep(0.05)  # a frame mid-cycle at pause time may tick once
    settled = sources[0].yielded
    assert sources[0].closed is True, "pause leaves the source closed, not mid-flight"
    await asyncio.sleep(0.3)  # a live pipeline would have pushed more frames
    assert sources[0].yielded == settled, "pause freezes the frame flow"
    assert runtime.paused is True
    assert runtime._manager is None, "pause closes pipelines"
    assert runtime._handlers == {} and runtime._tasks == [], "pause frees chain parts"

    await asyncio.wait_for(runtime.resume(), timeout=10)
    assert await _wait_until(lambda: len(sources) == 2 and sources[1].yielded >= 3)
    assert runtime.paused is False and runtime._handlers, "chains are rebuilt"

    await asyncio.wait_for(runtime.pause(), timeout=10)
    await asyncio.wait_for(runtime.stop(), timeout=10)
    assert runtime.paused is False, "stop clears the pause state"


async def test_pause_resume_idempotent(
    db_session: Session, seeded: tuple[Site, User, User]
) -> None:
    _camera(db_session, seeded)
    sources: list[FakeSource] = []

    def make(_config: object) -> FakeSource:
        source = FakeSource()
        sources.append(source)
        return source

    runtime = Runtime(
        session_factory=_factory(db_session),
        enabled=True,
        detector_factory=lambda **_kw: FakeDetector(),
        source_factory=make,
    )
    await runtime.start()
    assert await _wait_until(lambda: len(sources) == 1 and sources[0].yielded >= 3)
    await runtime.pause()
    await asyncio.sleep(0.05)  # a frame mid-cycle at pause time may tick once
    settled = sources[0].yielded
    await runtime.pause()  # no second stop, no crash, still paused
    await asyncio.sleep(0.3)
    assert sources[0].yielded == settled, "chain is frozen after pause"
    assert runtime._manager is None, "first pause stopped the chain"
    assert runtime.paused is True
    assert len(sources) == 1, "second pause does not spawn anything"

    await runtime.resume()
    assert await _wait_until(lambda: len(sources) == 2 and sources[1].yielded >= 3)
    await runtime.resume()
    assert len(sources) == 2, "second resume does not duplicate chains"
    assert runtime._handlers, "chains remain open"
    await runtime.stop()


# -- HTTP surface ------------------------------------------------------------


def test_admin_pause_and_resume_roundtrip(
    client: TestClient, admin_headers: dict[str, str], db_session
) -> None:
    resp = client.post("/api/v1/system/pause", json={"paused": True}, headers=admin_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"paused": True}

    data = client.get("/api/v1/system/status", headers=admin_headers).json()
    assert data["paused"] is True

    # Audit: a privileged-action row (SECURITY 7.5), non-notifiable — the
    # delivery worker scans pending/failed events only, and pausing must
    # never page the customer. No system Event row is written: the event log
    # is customer-facing, the audit trail is operator-facing.
    audits = (
        db_session.execute(
            select(AuditLog).where(AuditLog.action == "system.pause").order_by(AuditLog.id)
        )
        .scalars()
        .all()
    )
    assert len(audits) == 1
    assert audits[0].site_id is not None and audits[0].user_id is not None
    assert audits[0].details == {"paused": True}

    resp = client.post("/api/v1/system/pause", json={"paused": False}, headers=admin_headers)
    assert resp.status_code == 200 and resp.json() == {"paused": False}
    resume_rows = (
        db_session.execute(
            select(AuditLog).where(AuditLog.action == "system.resume").order_by(AuditLog.id)
        )
        .scalars()
        .all()
    )
    assert len(resume_rows) == 1, "resume leaves its own audit row"


def test_pause_is_idempotent_no_error(client: TestClient, admin_headers: dict[str, str]) -> None:
    first = client.post("/api/v1/system/pause", json={"paused": True}, headers=admin_headers)
    second = client.post("/api/v1/system/pause", json={"paused": True}, headers=admin_headers)
    assert (first.status_code, second.status_code) == (200, 200)
    assert client.post(
        "/api/v1/system/pause", json={"paused": False}, headers=admin_headers
    ).json() == {"paused": False}


def test_viewer_cannot_pause(client: TestClient, viewer_headers: dict[str, str]) -> None:
    assert (
        client.post(
            "/api/v1/system/pause", json={"paused": True}, headers=viewer_headers
        ).status_code
        == 403
    )


def test_pause_body_validation(client: TestClient, admin_headers: dict[str, str]) -> None:
    # Pydantic bools coerce "yes"/1 in lax mode; garbage stays a 422.
    assert (
        client.post(
            "/api/v1/system/pause", json={"paused": "maybe"}, headers=admin_headers
        ).status_code
        == 422
    )
    assert client.post("/api/v1/system/pause", headers=admin_headers).status_code == 422


def test_status_unpaused_by_default(client: TestClient, admin_headers: dict[str, str]) -> None:
    data = client.get("/api/v1/system/status", headers=admin_headers).json()
    assert data["paused"] is False
