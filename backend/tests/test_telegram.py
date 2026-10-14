"""Telegram transport: photo/video/text, masked errors, offline survival."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from app.db.models import Camera, Event
from app.services.alerts.telegram import TelegramError, TelegramNotifier


def _event(db_session, seeded, tmp_path: Path, *, with_media: bool) -> Event:
    site, _admin, _viewer = seeded
    camera = Camera(site_id=site.id, name="Back door", rtsp_url="rtsp://10.0.0.6/ch1")
    db_session.add(camera)
    db_session.commit()
    if with_media:
        (tmp_path / "stills").mkdir()
        (tmp_path / "stills" / "1.jpg").write_bytes(b"\xff\xd8still")
        (tmp_path / "clips").mkdir()
        (tmp_path / "clips" / "1.mp4").write_bytes(b"\x00clip")
    event = Event(
        site_id=site.id,
        camera_id=camera.id,
        rule_id=None,
        triggered_by="rule",
        started_at=datetime(2026, 10, 6, 22, 0, tzinfo=UTC).replace(tzinfo=None),
        severity="critical",
        summary="1 person in Loading dock",
        thumbnail_path="stills/1.jpg" if with_media else None,
        clip_path="clips/1.mp4" if with_media else None,
    )
    db_session.add(event)
    db_session.commit()
    return event


def _recording_client(
    responses: list[httpx.Response], captured: list[httpx.Request]
) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return (
            responses.pop(0) if responses else httpx.Response(200, json={"ok": True, "result": {}})
        )

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_sends_video_when_clip_exists(db_session, seeded, tmp_path: Path) -> None:
    event = _event(db_session, seeded, tmp_path, with_media=True)
    captured: list[httpx.Request] = []
    notifier = TelegramNotifier(
        bot_token="SECRET-TOKEN",
        chat_id="42",
        client=_recording_client([], captured),
        media_root=tmp_path,
    )
    await notifier.send(event)
    request = captured[0]
    assert "sendVideo" in str(request.url)
    assert "SECRET-TOKEN" in str(request.url)
    assert b"42" in request.content  # chat_id travels as a form field


async def test_sends_photo_when_only_still(db_session, seeded, tmp_path: Path) -> None:
    event = _event(db_session, seeded, tmp_path, with_media=False)
    (tmp_path / "stills").mkdir()
    (tmp_path / "stills" / "1.jpg").write_bytes(b"\xff\xd8still")
    event.thumbnail_path = "stills/1.jpg"
    captured: list[httpx.Request] = []
    notifier = TelegramNotifier(
        bot_token="SECRET-TOKEN",
        chat_id="42",
        client=_recording_client([], captured),
        media_root=tmp_path,
    )
    await notifier.send(event)
    assert "sendPhoto" in str(captured[0].url)


async def test_sends_text_when_no_media(db_session, seeded, tmp_path: Path) -> None:
    event = _event(db_session, seeded, tmp_path, with_media=False)
    captured: list[httpx.Request] = []
    notifier = TelegramNotifier(
        bot_token="SECRET-TOKEN",
        chat_id="42",
        client=_recording_client([], captured),
        media_root=tmp_path,
    )
    await notifier.send(event)
    assert "sendMessage" in str(captured[0].url)


async def test_api_failure_raises_masked_error(db_session, seeded, tmp_path: Path) -> None:
    event = _event(db_session, seeded, tmp_path, with_media=False)
    failing = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _r: httpx.Response(200, json={"ok": False, "description": "chat not found"})
        )
    )
    notifier = TelegramNotifier(
        bot_token="SECRET-TOKEN", chat_id="42", client=failing, media_root=tmp_path
    )
    with pytest.raises(TelegramError) as excinfo:
        await notifier.send(event)
    assert "SECRET-TOKEN" not in str(excinfo.value)
    assert "chat not found" in str(excinfo.value)


async def test_transport_error_never_leaks_the_token(db_session, seeded, tmp_path: Path) -> None:
    event = _event(db_session, seeded, tmp_path, with_media=False)

    def boom(_r: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=_r)

    failing = httpx.AsyncClient(transport=httpx.MockTransport(boom))
    notifier = TelegramNotifier(
        bot_token="SECRET-TOKEN", chat_id="42", client=failing, media_root=tmp_path
    )
    with pytest.raises(TelegramError) as excinfo:
        await notifier.send(event)
    assert "SECRET-TOKEN" not in str(excinfo.value)


async def test_offline_event_survives(db_session, seeded, tmp_path: Path) -> None:
    """Matrix row: Telegram down -> the event row is still durable (spec A5.6)."""
    from app.services.alerts.stage import Alert
    from app.services.events.persist import create_event

    camera = Camera(site_id=seeded[0].id, name="C", rtsp_url="rtsp://x/ch1")
    db_session.add(camera)
    db_session.commit()
    alert = Alert(
        rule_id=1,
        rule_name="r",
        severity="critical",
        track_id=1,
        class_name="person",
        confidence=0.9,
        zone=None,
        fired_at=datetime.now(tz=UTC),
        summary="1 person in frame",
        camera_id=camera.id,
        bbox=(1, 2, 3, 4),
        notify=True,
    )
    event = create_event(db_session, alert)

    def boom(_r: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("network is down", request=_r)

    failing = httpx.AsyncClient(transport=httpx.MockTransport(boom))
    notifier = TelegramNotifier(bot_token="T", chat_id="1", client=failing, media_root=tmp_path)
    with pytest.raises(TelegramError):
        await notifier.send(event)
    db_session.expire_all()
    row = db_session.get(Event, event.id)
    assert row is not None, "an offline delivery must never lose the event"
    assert row.summary == "1 person in frame"


async def test_test_message_returns_telegram_response() -> None:
    captured: list[httpx.Request] = []
    client = _recording_client(
        [httpx.Response(200, json={"ok": True, "result": {"message_id": 7}})], captured
    )
    notifier = TelegramNotifier(bot_token="T", chat_id="1", client=client)
    result = await notifier.test_message()
    assert result == {"ok": True, "result": {"message_id": 7}}
    assert "sendMessage" in str(captured[0].url)
