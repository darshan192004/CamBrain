"""Rule API tests: validation, soft delete, active_hours, tenancy (API §Rules)."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import Rule, Site

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


def test_test_endpoint_returns_rule(client: TestClient, admin_headers: dict[str, str]) -> None:
    """POST /rules/{id}/test returns the rule (engine wired in Phase 3)."""
    cid = _make_camera(client, admin_headers)
    rule = _create_rule(client, admin_headers, cid)
    rid = rule["id"]
    resp = client.post(f"/api/v1/rules/{rid}/test", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == rid
