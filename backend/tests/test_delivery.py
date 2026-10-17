"""DeliveryWorker: durable retry, capped backoff, notifier plumbing."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any

from app.services.alerts.delivery import DeliveryWorker, backoff_s


def _pending_event(db_session, seeded, *, attempts: int = 0, last_attempt: datetime | None = None):
    from app.db.models import Camera, Event

    site, _admin, _viewer = seeded
    camera = Camera(site_id=site.id, name="Dock", rtsp_url="rtsp://10.0.0.9/ch1")
    db_session.add(camera)
    db_session.flush()
    event = Event(
        site_id=site.id,
        camera_id=camera.id,
        rule_id=None,
        triggered_by="system",
        started_at=datetime(2026, 10, 6, 22, 0),
        severity="critical",
        summary="1 person in Loading dock",
        delivery_status="pending",
        delivery_attempts=attempts,
        last_attempt_at=last_attempt,
    )
    db_session.add(event)
    db_session.commit()
    return event


class FakeNotifier:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.sent: list[int] = []

    async def send(self, event) -> None:  # noqa: ANN001
        if self.fail:
            raise RuntimeError("telegram network is down")
        self.sent.append(event.id)


def test_backoff_grows_and_caps() -> None:
    """Matrix: exponential backoff capped at one hour (D4)."""
    assert backoff_s(0) == 5.0
    assert backoff_s(1) == 10.0
    assert backoff_s(2) == 20.0
    assert backoff_s(20) == 3600.0


async def test_sweep_delivers_due_event(db_session, seeded) -> None:
    event = _pending_event(db_session, seeded)
    notifier = FakeNotifier()
    worker = DeliveryWorker(
        session_factory=lambda: db_session,
        notifier_for=lambda _site_id: [notifier],
    )
    delivered = await worker.sweep_once()
    assert delivered == 1 and notifier.sent == [event.id]
    db_session.expire_all()
    row = db_session.get(type(event), event.id)
    assert row.delivery_status == "sent" and row.delivery_attempts == 1
    assert row.delivered_at is not None and row.last_attempt_at is not None


async def test_backoff_slots_do_not_starve_a_fresh_event(db_session, seeded) -> None:
    """25 old events in backoff must not occupy the batch: a new pending row delivers."""
    now = datetime(2026, 10, 6, 22, 0)
    for _i in range(25):
        _pending_event(
            db_session,
            seeded,
            attempts=5,
            last_attempt=now - timedelta(minutes=2),  # backoff 160s, not yet due
        )
    fresh = _pending_event(db_session, seeded)
    notifier = FakeNotifier()
    worker = DeliveryWorker(
        session_factory=lambda: db_session,
        notifier_for=lambda _site_id: [notifier],
        now=lambda: now,
    )
    assert await worker.sweep_once() == 1
    assert notifier.sent == [fresh.id], "backoff rows wedged the batch"


async def test_failed_delivery_retries_forever_with_backoff(db_session, seeded) -> None:
    event = _pending_event(db_session, seeded, attempts=3)
    worker = DeliveryWorker(
        session_factory=lambda: db_session,
        notifier_for=lambda _site_id: [FakeNotifier(fail=True)],
    )
    assert await worker.sweep_once() == 0
    db_session.expire_all()
    row = db_session.get(type(event), event.id)
    assert row.delivery_status == "pending", "offline retries forever (D4)"
    assert row.delivery_attempts == 4
    assert "network is down" in (row.last_delivery_error or "")
    assert row.last_attempt_at is not None


async def test_backoff_delays_the_next_attempt(db_session, seeded) -> None:
    now = datetime(2026, 10, 6, 22, 0)
    _pending_event(db_session, seeded, attempts=1, last_attempt=now)
    calls: list[Any] = []
    worker = DeliveryWorker(
        session_factory=lambda: db_session,
        notifier_for=lambda _site_id: calls.append("x") or [FakeNotifier()],
        now=lambda: now,
    )
    assert await worker.sweep_once() == 0, "attempt 1 backs off 10s; only 3s elapsed"
    assert calls == []
    worker_now = lambda: now + timedelta(seconds=11)  # noqa: E731
    worker = DeliveryWorker(
        session_factory=lambda: db_session,
        notifier_for=lambda _site_id: calls.append("x") or [FakeNotifier()],
        now=worker_now,
    )
    assert await worker.sweep_once() == 1


async def test_no_notifier_marks_failed(db_session, seeded) -> None:
    event = _pending_event(db_session, seeded)
    worker = DeliveryWorker(
        session_factory=lambda: db_session,
        notifier_for=lambda _site_id: [],
    )
    await worker.sweep_once()
    db_session.expire_all()
    row = db_session.get(type(event), event.id)
    assert row.delivery_status == "failed"
    assert row.last_delivery_error and "notifier" in row.last_delivery_error


async def test_run_loop_stops_on_close(db_session, seeded) -> None:
    _pending_event(db_session, seeded)
    worker = DeliveryWorker(
        session_factory=lambda: db_session,
        notifier_for=lambda _site_id: [FakeNotifier()],
        interval_s=0.01,
    )
    task = asyncio.create_task(worker.run())
    await asyncio.sleep(0.05)
    await worker.close()
    await asyncio.wait_for(task, timeout=1.0)  # close() must end the loop
