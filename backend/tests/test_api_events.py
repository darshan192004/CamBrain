"""Events API tests: filters, pagination, acknowledge, stats (API §Events)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import Event, Site

_URL = "rtsp://10.0.0.5:554/Streaming/Channels/101"


def _make_camera(client: TestClient, headers: dict[str, str]) -> int:
    resp = client.post("/api/v1/cameras", json={"name": "c1", "rtsp_url": _URL}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _seed_event(db: Session, site_id: int, camera_id: int, **overrides: object) -> Event:
    """Insert an event row directly (no API for creating events until Phase 4)."""
    from datetime import UTC, datetime

    fields: dict = {
        "site_id": site_id,
        "camera_id": camera_id,
        "triggered_by": "rule",
        "started_at": datetime.now(UTC).replace(tzinfo=None),
        "severity": "critical",
        "summary": "1 person in Loading dock",
        "clip_path": "/tmp/clip.mp4",
    }
    fields.update(overrides)
    event = Event(**fields)
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def test_list_events_empty(client: TestClient, admin_headers: dict[str, str]) -> None:
    resp = client.get("/api/v1/events", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["items"] == []
    assert data["total"] == 0


def test_list_events_with_rows(
    client: TestClient, admin_headers: dict[str, str], db_session: Session, seeded
) -> None:
    site, _admin, _viewer = seeded
    cid = _make_camera(client, admin_headers)
    _seed_event(db_session, site.id, cid)
    _seed_event(db_session, site.id, cid, severity="info", summary="info event")
    db_session.expire_all()
    resp = client.get("/api/v1/events", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert len(data["items"]) == 2
    # Response shape.
    first = data["items"][0]
    assert first["camera"]["id"] == cid
    assert first["acknowledged"] is False
    assert first["has_clip"] is True
    assert first["thumbnail_url"] == f"/api/v1/events/{first['id']}/thumbnail"


def test_pagination_limit_cap(
    client: TestClient, admin_headers: dict[str, str], db_session: Session, seeded
) -> None:
    site, _admin, _viewer = seeded
    cid = _make_camera(client, admin_headers)
    for _ in range(5):
        _seed_event(db_session, site.id, cid)
    db_session.expire_all()
    # limit > 200 is a 422 (query validator).
    resp = client.get("/api/v1/events?limit=201", headers=admin_headers)
    assert resp.status_code == 422
    # limit=2, offset=1 returns the second page.
    resp = client.get("/api/v1/events?limit=2&offset=1", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["limit"] == 2
    assert resp.json()["offset"] == 1
    assert len(resp.json()["items"]) == 2


def test_severity_filter(
    client: TestClient, admin_headers: dict[str, str], db_session: Session, seeded
) -> None:
    site, _admin, _viewer = seeded
    cid = _make_camera(client, admin_headers)
    _seed_event(db_session, site.id, cid, severity="critical")
    _seed_event(db_session, site.id, cid, severity="info")
    db_session.expire_all()
    resp = client.get("/api/v1/events?severity=critical", headers=admin_headers)
    assert resp.json()["total"] == 1
    assert resp.json()["items"][0]["severity"] == "critical"


def test_acknowledge(
    client: TestClient, admin_headers: dict[str, str], db_session: Session, seeded
) -> None:
    site, _admin, _viewer = seeded
    cid = _make_camera(client, admin_headers)
    event = _seed_event(db_session, site.id, cid)
    db_session.expire_all()
    resp = client.post(f"/api/v1/events/{event.id}/acknowledge", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["acknowledged"] is True
    # Idempotent.
    resp = client.post(f"/api/v1/events/{event.id}/acknowledge", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["acknowledged"] is True


def test_acknowledge_bulk(
    client: TestClient, admin_headers: dict[str, str], db_session: Session, seeded
) -> None:
    site, _admin, _viewer = seeded
    cid = _make_camera(client, admin_headers)
    e1 = _seed_event(db_session, site.id, cid)
    e2 = _seed_event(db_session, site.id, cid)
    db_session.expire_all()
    resp = client.post(
        "/api/v1/events/acknowledge-bulk",
        json={"event_ids": [e1.id, e2.id]},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["acknowledged"] == 2


def test_stats(
    client: TestClient, admin_headers: dict[str, str], db_session: Session, seeded
) -> None:
    site, _admin, _viewer = seeded
    cid = _make_camera(client, admin_headers)
    _seed_event(db_session, site.id, cid, severity="critical")
    _seed_event(db_session, site.id, cid, severity="info")
    db_session.expire_all()
    resp = client.get("/api/v1/events/stats", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert data["by_severity"]["critical"] == 1


def test_clip_404_when_absent(
    client: TestClient, admin_headers: dict[str, str], db_session: Session, seeded
) -> None:
    site, _admin, _viewer = seeded
    cid = _make_camera(client, admin_headers)
    event = _seed_event(db_session, site.id, cid, clip_path=None)
    db_session.expire_all()
    resp = client.get(f"/api/v1/events/{event.id}/clip", headers=admin_headers)
    assert resp.status_code == 404


def test_thumbnail_serves_file(
    client: TestClient,
    admin_headers: dict[str, str],
    db_session: Session,
    seeded,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """thumbnail_url resolves to image/jpeg bytes (D8; Phase 5 writes stills)."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "media_root", tmp_path)
    site, _admin, _viewer = seeded
    cid = _make_camera(client, admin_headers)
    payload = b"\xff\xd8\xff\xe0tiny-jpeg-bytes\xff\xd9"
    event = _seed_event(db_session, site.id, cid)  # id known before the file lands
    still = tmp_path / "stills" / f"{event.id}.jpg"
    still.parent.mkdir()
    still.write_bytes(payload)
    row = db_session.get(Event, event.id)
    assert row is not None
    row.thumbnail_path = f"stills/{event.id}.jpg"  # relative, as DATABASE.md §4.7
    db_session.commit()
    db_session.expire_all()
    resp = client.get(f"/api/v1/events/{event.id}/thumbnail", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"
    assert resp.content == payload


def test_thumbnail_outside_root_is_404(
    client: TestClient,
    admin_headers: dict[str, str],
    db_session: Session,
    seeded,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A thumbnail_path escaping the media root is 404, never served (SECURITY §6.2)."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "media_root", tmp_path)
    site, _admin, _viewer = seeded
    cid = _make_camera(client, admin_headers)
    outside = tmp_path.parent / "evil.jpg"
    outside.write_bytes(b"\xff\xd8evil\xff\xd9")
    event = _seed_event(db_session, site.id, cid, thumbnail_path=str(outside))
    db_session.expire_all()
    resp = client.get(f"/api/v1/events/{event.id}/thumbnail", headers=admin_headers)
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "NOT_FOUND"


def test_thumbnail_404_when_absent(
    client: TestClient, admin_headers: dict[str, str], db_session: Session, seeded
) -> None:
    site, _admin, _viewer = seeded
    cid = _make_camera(client, admin_headers)
    event = _seed_event(db_session, site.id, cid)  # thumbnail_path defaults to None
    db_session.expire_all()
    resp = client.get(f"/api/v1/events/{event.id}/thumbnail", headers=admin_headers)
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "NOT_FOUND"


def test_thumbnail_cross_tenant_404(
    client: TestClient, admin_headers: dict[str, str], db_session: Session, seeded
) -> None:
    """A still from another site is a 404, never a 403 (IDOR defence)."""
    site, _admin, _viewer = seeded
    cid = _make_camera(client, admin_headers)
    event = _seed_event(db_session, site.id, cid)
    other = Site(name="Other", timezone="UTC")
    db_session.add(other)
    db_session.flush()
    row = db_session.get(Event, event.id)
    assert row is not None
    row.site_id = other.id
    db_session.commit()
    db_session.expire_all()
    resp = client.get(f"/api/v1/events/{event.id}/thumbnail", headers=admin_headers)
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "NOT_FOUND"


def test_cross_tenant_returns_404(
    client: TestClient, admin_headers: dict[str, str], db_session: Session, seeded
) -> None:
    site, _admin, _viewer = seeded
    cid = _make_camera(client, admin_headers)
    event = _seed_event(db_session, site.id, cid)
    other = Site(name="Other", timezone="UTC")
    db_session.add(other)
    db_session.flush()
    row = db_session.get(Event, event.id)
    assert row is not None
    row.site_id = other.id
    db_session.commit()
    db_session.expire_all()
    assert client.get(f"/api/v1/events/{event.id}", headers=admin_headers).status_code == 404


def test_unauthenticated_rejected(client: TestClient) -> None:
    resp = client.get("/api/v1/events")
    assert resp.status_code == 401
