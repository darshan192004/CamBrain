"""Rule API tests: validation, soft delete, active_hours, tenancy (API §Rules)."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import Camera, Event, EventDetection, Rule, Site

_URL = "rtsp://10.0.0.5:554/Streaming/Channels/101"


def _make_camera(client: TestClient, headers: dict[str, str]) -> int:
    resp = client.post(
        "/api/v1/cameras",
        json={"name": "c1", "rtsp_url": _URL},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _create_rule(
    client: TestClient, headers: dict[str, str], camera_id: int, **overrides: object
) -> dict:
    body: dict = {
        "name": "Back door after hours",
        "classes": ["person"],
        "confidence_threshold": 0.55,
        "cooldown_seconds": 60,
        "severity": "critical",
        "notify": True,
    }
    body.update(overrides)
    resp = client.post(f"/api/v1/cameras/{camera_id}/rules", json=body, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_create_rule_roundtrip(client: TestClient, admin_headers: dict[str, str]) -> None:
    cid = _make_camera(client, admin_headers)
    data = _create_rule(client, admin_headers, cid)
    assert data["classes"] == ["person"]
    assert data["confidence_threshold"] == 0.55
    assert data["cooldown_seconds"] == 60
    assert data["severity"] == "critical"
    assert data["notify"] is True
    assert data["roi_id"] is None


def test_list_site_and_camera(client: TestClient, admin_headers: dict[str, str]) -> None:
    cid = _make_camera(client, admin_headers)
    _create_rule(client, admin_headers, cid)
    # Site-wide.
    resp = client.get("/api/v1/rules", headers=admin_headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    # Per-camera.
    resp = client.get(f"/api/v1/cameras/{cid}/rules", headers=admin_headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_invalid_confidence_rejected(client: TestClient, admin_headers: dict[str, str]) -> None:
    cid = _make_camera(client, admin_headers)
    resp = client.post(
        f"/api/v1/cameras/{cid}/rules",
        json={"name": "bad", "classes": ["person"], "confidence_threshold": 1.5},
        headers=admin_headers,
    )
    assert resp.status_code == 422


def test_invalid_cooldown_rejected(client: TestClient, admin_headers: dict[str, str]) -> None:
    cid = _make_camera(client, admin_headers)
    resp = client.post(
        f"/api/v1/cameras/{cid}/rules",
        json={"name": "bad", "classes": ["person"], "cooldown_seconds": 1},
        headers=admin_headers,
    )
    assert resp.status_code == 422


def test_empty_classes_rejected(client: TestClient, admin_headers: dict[str, str]) -> None:
    cid = _make_camera(client, admin_headers)
    resp = client.post(
        f"/api/v1/cameras/{cid}/rules",
        json={"name": "bad", "classes": []},
        headers=admin_headers,
    )
    assert resp.status_code == 422


def test_unknown_class_rejected(client: TestClient, admin_headers: dict[str, str]) -> None:
    cid = _make_camera(client, admin_headers)
    resp = client.post(
        f"/api/v1/cameras/{cid}/rules",
        json={"name": "bad", "classes": ["unicorn"]},
        headers=admin_headers,
    )
    assert resp.status_code == 422


def test_active_hours_wrap_accepted(client: TestClient, admin_headers: dict[str, str]) -> None:
    """A 22:00 -> 06:00 window (past midnight) is valid, not a 422."""
    cid = _make_camera(client, admin_headers)
    data = _create_rule(
        client,
        admin_headers,
        cid,
        active_hours={
            "timezone": "Asia/Kolkata",
            "windows": [{"start": "22:00", "end": "06:00"}],
        },
    )
    assert data["active_hours"]["windows"][0]["start"] == "22:00"


def test_active_hours_too_many_windows_rejected(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    cid = _make_camera(client, admin_headers)
    windows = [{"start": f"{i:02d}:00", "end": f"{i:02d}:30"} for i in range(5)]
    resp = client.post(
        f"/api/v1/cameras/{cid}/rules",
        json={
            "name": "bad",
            "classes": ["person"],
            "active_hours": {"timezone": "UTC", "windows": windows},
        },
        headers=admin_headers,
    )
    assert resp.status_code == 422


def test_roi_must_belong_to_same_camera(client: TestClient, admin_headers: dict[str, str]) -> None:
    cid = _make_camera(client, admin_headers)
    other_cid = _make_camera(client, admin_headers)
    # ROI on other camera.
    roi_resp = client.post(
        f"/api/v1/cameras/{other_cid}/rois",
        json={"name": "r", "points": [[0, 0], [1, 0], [1, 1]]},
        headers=admin_headers,
    )
    assert roi_resp.status_code == 201, roi_resp.text
    rid = roi_resp.json()["id"]
    # Rule on cid referencing ROI on other_cid -> 422.
    resp = client.post(
        f"/api/v1/cameras/{cid}/rules",
        json={"name": "bad", "classes": ["person"], "roi_id": rid},
        headers=admin_headers,
    )
    assert resp.status_code == 422


def test_roi_on_same_camera_accepted(client: TestClient, admin_headers: dict[str, str]) -> None:
    cid = _make_camera(client, admin_headers)
    roi_resp = client.post(
        f"/api/v1/cameras/{cid}/rois",
        json={"name": "r", "points": [[0, 0], [1, 0], [1, 1]]},
        headers=admin_headers,
    )
    assert roi_resp.status_code == 201
    rid = roi_resp.json()["id"]
    data = _create_rule(client, admin_headers, cid, roi_id=rid)
    assert data["roi_id"] == rid


def test_delete_is_soft(
    client: TestClient, admin_headers: dict[str, str], db_session: Session
) -> None:
    cid = _make_camera(client, admin_headers)
    rule = _create_rule(client, admin_headers, cid)
    rid = rule["id"]
    assert client.delete(f"/api/v1/rules/{rid}", headers=admin_headers).status_code == 204
    assert client.get(f"/api/v1/rules/{rid}", headers=admin_headers).status_code == 404
    # Hidden from list.
    assert len(client.get("/api/v1/rules", headers=admin_headers).json()) == 0
    # Row remains for forensics.
    row = db_session.get(Rule, rid)
    assert row is not None and row.deleted_at is not None


def test_viewer_cannot_write(
    client: TestClient, admin_headers: dict[str, str], viewer_headers: dict[str, str]
) -> None:
    cid = _make_camera(client, admin_headers)
    rule = _create_rule(client, admin_headers, cid)
    rid = rule["id"]
    # Viewer can read.
    assert client.get(f"/api/v1/rules/{rid}", headers=viewer_headers).status_code == 200
    # Viewer cannot write.
    for method, url, body in [
        ("post", f"/api/v1/cameras/{cid}/rules", {"name": "x", "classes": ["person"]}),
        ("patch", f"/api/v1/rules/{rid}", {"name": "x"}),
        ("delete", f"/api/v1/rules/{rid}", None),
    ]:
        kwargs = {"json": body} if body is not None else {}
        resp = getattr(client, method)(url, headers=viewer_headers, **kwargs)
        assert resp.status_code == 403, f"{method} {url}"


def test_patch_rule(client: TestClient, admin_headers: dict[str, str]) -> None:
    cid = _make_camera(client, admin_headers)
    rule = _create_rule(client, admin_headers, cid)
    rid = rule["id"]
    resp = client.patch(
        f"/api/v1/rules/{rid}",
        json={"name": "New", "severity": "info"},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "New"
    assert data["severity"] == "info"


def test_cross_tenant_returns_404(
    client: TestClient, admin_headers: dict[str, str], db_session: Session
) -> None:
    cid = _make_camera(client, admin_headers)
    rule = _create_rule(client, admin_headers, cid)
    rid = rule["id"]
    other = Site(name="Other", timezone="UTC")
    db_session.add(other)
    db_session.flush()
    row = db_session.get(Rule, rid)
    assert row is not None
    row.site_id = other.id
    db_session.commit()
    db_session.expire_all()
    assert client.get(f"/api/v1/rules/{rid}", headers=admin_headers).status_code == 404


def _seed_detection_event(
    db: Session, site_id: int, camera_id: int, *, confidence: float = 0.71
) -> Event:
    """Event + one person detection at a known pixel bbox (no create API until Phase 4)."""
    from datetime import UTC, datetime

    now = datetime.now(UTC).replace(tzinfo=None)  # naive UTC, as _seed_event does
    event = Event(
        site_id=site_id,
        camera_id=camera_id,
        triggered_by="rule",
        started_at=now,
        severity="critical",
        summary="1 person in Loading dock",
    )
    db.add(event)
    db.flush()
    db.add(
        EventDetection(
            event_id=event.id,
            camera_id=camera_id,
            class_name="person",
            confidence=confidence,
            bbox=[100, 200, 300, 400],
            track_id=1,
            detected_at=now,
        )
    )
    db.commit()
    db.refresh(event)
    return event


def _set_frame_size(db: Session, camera_id: int) -> None:
    """Pixel bboxes need a frame size before they can be normalised."""
    camera = db.get(Camera, camera_id)
    assert camera is not None
    camera.frame_width, camera.frame_height = 768, 432
    db.commit()


def test_rule_test_returns_api_shaped_checks(
    client: TestClient, admin_headers: dict[str, str], db_session: Session, seeded
) -> None:
    """API.md's documented response, down to the condition order."""
    site, _admin, _viewer = seeded
    cid = _make_camera(client, admin_headers)
    rule = _create_rule(client, admin_headers, cid)
    _set_frame_size(db_session, cid)
    _seed_detection_event(db_session, site.id, cid)

    resp = client.post(f"/api/v1/rules/{rule['id']}/test", json={}, headers=admin_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["rule_id"] == rule["id"]
    assert body["fired"] is True
    assert [c["condition"] for c in body["checks"]] == [
        "class_in_allowlist",
        "confidence",
        "in_roi",
        "active_hours",
        "cooldown",
    ]
    assert all(isinstance(c["passed"], bool) and c["detail"] for c in body["checks"])
    # person 0.71 >= 0.55, no ROI -> whole frame, no hours, no cooldown history.
    roi_check = next(c for c in body["checks"] if c["condition"] == "in_roi")
    assert "whole frame" in roi_check["detail"]


def test_rule_test_replays_a_supplied_event_id(
    client: TestClient, admin_headers: dict[str, str], db_session: Session, seeded
) -> None:
    site, _admin, _viewer = seeded
    cid = _make_camera(client, admin_headers)
    rule = _create_rule(client, admin_headers, cid)
    _set_frame_size(db_session, cid)
    event = _seed_detection_event(db_session, site.id, cid)

    resp = client.post(
        f"/api/v1/rules/{rule['id']}/test",
        json={"event_id": event.id},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["fired"] is True


def test_rule_test_unknown_event_id_is_404(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    cid = _make_camera(client, admin_headers)
    rule = _create_rule(client, admin_headers, cid)
    resp = client.post(
        f"/api/v1/rules/{rule['id']}/test", json={"event_id": 999999}, headers=admin_headers
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "NOT_FOUND"


def test_rule_test_event_on_another_camera_is_404(
    client: TestClient, admin_headers: dict[str, str], db_session: Session, seeded
) -> None:
    """A replayed event must belong to the rule's own camera."""
    site, _admin, _viewer = seeded
    cid = _make_camera(client, admin_headers)
    other_cid = _make_camera(client, admin_headers)
    rule = _create_rule(client, admin_headers, cid)
    event = _seed_detection_event(db_session, site.id, other_cid)

    resp = client.post(
        f"/api/v1/rules/{rule['id']}/test",
        json={"event_id": event.id},
        headers=admin_headers,
    )
    assert resp.status_code == 404


def test_rule_test_404s_with_no_event_to_replay(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    cid = _make_camera(client, admin_headers)
    rule = _create_rule(client, admin_headers, cid)
    resp = client.post(f"/api/v1/rules/{rule['id']}/test", json={}, headers=admin_headers)
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "NOT_FOUND"


def test_rule_test_422_when_frame_size_unknown(
    client: TestClient, admin_headers: dict[str, str], db_session: Session, seeded
) -> None:
    """No frame size means no ROI interpretation — a loud 422, not a pass."""
    site, _admin, _viewer = seeded
    cid = _make_camera(client, admin_headers)
    rule = _create_rule(client, admin_headers, cid)
    _seed_detection_event(db_session, site.id, cid)  # camera dims intentionally NULL

    resp = client.post(f"/api/v1/rules/{rule['id']}/test", json={}, headers=admin_headers)
    assert resp.status_code == 422
    body = resp.json()["error"]
    assert body["code"] == "VALIDATION_ERROR"
    assert "frame size" in body["message"]


def test_rule_test_cross_tenant_event_is_404(
    client: TestClient, admin_headers: dict[str, str], db_session: Session, seeded
) -> None:
    site, _admin, _viewer = seeded
    cid = _make_camera(client, admin_headers)
    rule = _create_rule(client, admin_headers, cid)
    _set_frame_size(db_session, cid)
    event = _seed_detection_event(db_session, site.id, cid)
    other = Site(name="Other", timezone="UTC")
    db_session.add(other)
    db_session.flush()
    event.site_id = other.id
    db_session.commit()
    db_session.expire_all()

    resp = client.post(
        f"/api/v1/rules/{rule['id']}/test",
        json={"event_id": event.id},
        headers=admin_headers,
    )
    assert resp.status_code == 404


def test_rule_test_with_base64_still_runs_detector(
    client: TestClient, admin_headers: dict[str, str], db_session: Session, seeded
) -> None:
    """Spec A7.3 still-or-event: the still path needs no weights and no stored dims."""
    import base64

    import numpy as np

    from app.api.routers.rules import get_rule_detector
    from app.services.inference.types import Detection
    from app.services.stream.jpeg import encode_jpeg
    from app.services.stream.source import Frame

    site, _admin, _viewer = seeded
    camera = Camera(
        site_id=site.id, name="Front", rtsp_url=_URL, frame_width=None, frame_height=None
    )
    db_session.add(camera)
    db_session.commit()
    rule = Rule(
        site_id=site.id,
        camera_id=camera.id,
        roi_id=None,
        name="r",
        severity="critical",
        classes=["person"],
        confidence_threshold=0.5,
        cooldown_seconds=0,
        notify=True,
    )
    db_session.add(rule)
    db_session.commit()

    class FakeDetector:
        async def infer(self, frame: Frame) -> list[Detection]:
            assert (frame.width, frame.height) == (64, 36), "image carries its own dims"
            return [Detection(class_name="person", confidence=0.91, bbox=(4, 4, 40, 30))]

        async def close(self) -> None:
            return None

    jpeg = encode_jpeg(
        Frame(data=np.zeros((36, 64, 3), dtype=np.uint8), timestamp=0.0, width=64, height=36)
    )
    client.app.dependency_overrides[get_rule_detector] = lambda: lambda: FakeDetector()
    try:
        resp = client.post(
            f"/api/v1/rules/{rule.id}/test",
            json={"image_b64": base64.b64encode(jpeg).decode()},
            headers=admin_headers,
        )
    finally:
        client.app.dependency_overrides.pop(get_rule_detector, None)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["fired"] is True
    assert any(c["condition"] == "in_roi" for c in body["checks"])
