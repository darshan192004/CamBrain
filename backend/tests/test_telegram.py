"""Telegram delivery: failure never loses the event (spec §5.6)."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy.orm import Session

from app.db.models import Event, Site
from app.db.repositories.events import EventRepository
from app.services.alerts.notifier import deliver_event
from app.services.alerts.telegram import TelegramNotifier


def _seed_event(db: Session, site: Site, camera_id: int) -> Event:
    event = Event(
        site_id=site.id,
        camera_id=camera_id,
        triggered_by="rule",
        started_at=datetime.now(UTC).replace(tzinfo=None),
        severity="critical",
        summary="1 person in frame",
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def _camera_id(db: Session, site: Site) -> int:
    from app.db.models import Camera

    camera = Camera(site_id=site.id, name="c1", rtsp_url="rtsp://10.0.0.5:554/s")
    db.add(camera)
    db.commit()
    db.refresh(camera)
    return camera.id


class _OkResponse:
    status_code = 200

    def json(self) -> dict[str, object]:
        return {"ok": True}

    def raise_for_status(self) -> None:
        return None


class _FailResponse:
    status_code = 400

    def json(self) -> dict[str, object]:
        return {"ok": False, "description": "bad request"}

    def raise_for_status(self) -> None:
        raise httpx.HTTPStatusError("bad", request=None, response=None)  # type: ignore[arg-type]


async def test_offline_event_survives(
    db_session: Session, seeded: tuple[Site, object, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A dead network marks the event failed; the row and clip intent survive."""
    site, _, _ = seeded
    event = _seed_event(db_session, site, _camera_id(db_session, site))

    async def _down(*_args: object, **_kwargs: object) -> object:
        raise httpx.ConnectError("network unreachable")

    monkeypatch.setattr(httpx.AsyncClient, "post", _down)
    repo = EventRepository(db_session, site_id=site.id)
    notifier = TelegramNotifier(bot_token="TOKEN", chat_id="1")

    await deliver_event(repo, event.id, photo=b"jpeg", caption="intruder", notifiers=[notifier])

    db_session.refresh(event)
    assert event.delivery_status == "failed"
    assert event.delivery_attempts == 1
    assert db_session.get(Event, event.id) is not None


async def test_success_marks_sent(
    db_session: Session, seeded: tuple[Site, object, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    site, _, _ = seeded
    event = _seed_event(db_session, site, _camera_id(db_session, site))

    async def _ok(*_args: object, **_kwargs: object) -> object:
        return _OkResponse()

    monkeypatch.setattr(httpx.AsyncClient, "post", _ok)
    repo = EventRepository(db_session, site_id=site.id)
    await deliver_event(
        repo, event.id, photo=b"jpeg", caption="hi", notifiers=[TelegramNotifier("T", "1")]
    )
    db_session.refresh(event)
    assert event.delivery_status == "sent"
    assert event.delivered_at is not None


async def test_failure_hides_token_in_error(
    db_session: Session, seeded: tuple[Site, object, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    site, _, _ = seeded
    event = _seed_event(db_session, site, _camera_id(db_session, site))

    async def _fail(*_args: object, **_kwargs: object) -> object:
        return _FailResponse()

    monkeypatch.setattr(httpx.AsyncClient, "post", _fail)
    repo = EventRepository(db_session, site_id=site.id)
    await deliver_event(
        repo, event.id, photo=b"j", caption="c", notifiers=[TelegramNotifier("SECRET-TOKEN", "1")]
    )
    db_session.refresh(event)
    assert event.delivery_status == "failed"
    assert event.last_delivery_error is not None
    assert "SECRET-TOKEN" not in event.last_delivery_error
