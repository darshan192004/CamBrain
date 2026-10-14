"""/ws/alerts: subprotocol auth, tenant isolation, event delivery (API A3)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.db.models import Camera, Event
from app.services.alerts.hub import event_message, get_alert_hub


def _token(
    client: TestClient, username: str = "ramesh", password: str = "correct-horse-battery"
) -> str:
    res = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


def _event(db_session, site) -> Event:
    camera = Camera(site_id=site.id, name="Back door", rtsp_url="rtsp://10.0.0.6/ch1")
    db_session.add(camera)
    db_session.commit()
    event = Event(
        site_id=site.id,
        camera_id=camera.id,
        rule_id=None,
        triggered_by="rule",
        started_at=datetime.now(tz=UTC).replace(tzinfo=None),
        severity="critical",
        summary="1 person in Loading dock",
    )
    db_session.add(event)
    db_session.commit()
    return event


def test_connects_with_jwt_subprotocol(client: TestClient, db_session, seeded) -> None:
    site, _admin, _viewer = seeded
    token = _token(client)
    with client.websocket_connect(
        "/api/v1/ws/alerts", subprotocols=[f"cambrain.jwt.{token}"]
    ) as ws:
        event = _event(db_session, site)
        get_alert_hub().broadcast(event.site_id, event_message(event, "Back door"))
        frame = ws.receive_json()
        assert frame["type"] == "event"
        assert frame["data"]["camera"]["name"] == "Back door"
        assert frame["data"]["has_clip"] is False


def test_rejects_bad_token(client: TestClient) -> None:
    with (
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect("/api/v1/ws/alerts", subprotocols=["cambrain.jwt.nope"]),
    ):
        pass


def test_first_message_auth_fallback(client: TestClient, seeded) -> None:
    site, _admin, _viewer = seeded
    token = _token(client)
    with client.websocket_connect("/api/v1/ws/alerts") as ws:
        ws.send_json({"type": "auth", "token": token})
        get_alert_hub().broadcast(
            site.id, {"type": "heartbeat", "data": {"ts": "2026-10-06T22:00:00Z"}}
        )
        assert ws.receive_json()["type"] == "heartbeat"


def test_cross_site_broadcast_never_arrives(client: TestClient, seeded) -> None:
    """Ordering proof: a wrong-site event must not precede the right-site beat."""
    site, _admin, _viewer = seeded
    token = _token(client)
    with client.websocket_connect(
        "/api/v1/ws/alerts", subprotocols=[f"cambrain.jwt.{token}"]
    ) as ws:
        hub = get_alert_hub()
        hub.broadcast(site.id + 999, {"type": "event", "data": {"id": 999}})
        hub.broadcast(site.id, {"type": "heartbeat", "data": {"ts": "t"}})
        frame = ws.receive_json()
        assert frame["type"] == "heartbeat", "cross-site event leaked ahead of the beat"
