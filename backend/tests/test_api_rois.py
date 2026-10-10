"""ROI API tests: normalised coordinates, coverage, camera scoping, tenancy (API §ROIs)."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import Roi, Site

_URL = "rtsp://10.0.0.5:554/Streaming/Channels/101"

# Unit square coverage is 100%.
_FULL = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]


def _make_camera(client: TestClient, headers: dict[str, str]) -> int:
    resp = client.post(
        "/api/v1/cameras",
        json={"name": "c1", "rtsp_url": _URL},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _create_roi(
    client: TestClient, headers: dict[str, str], camera_id: int, **overrides: object
) -> dict:
    body: dict = {
        "name": "Dock",
        "points": [[0.1, 0.1], [0.5, 0.1], [0.5, 0.5], [0.1, 0.5]],
        "class_filter": ["person"],
        "active": True,
    }
    body.update(overrides)
    resp = client.post(f"/api/v1/cameras/{camera_id}/rois", json=body, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_create_roi_computes_coverage(client: TestClient, admin_headers: dict[str, str]) -> None:
    cid = _make_camera(client, admin_headers)
    data = _create_roi(client, admin_headers, cid)
    # 0.4 x 0.4 unit square = 16% of frame.
    assert data["coverage_pct"] == 16.0
    assert data["vertex_count"] == 4
    assert data["class_filter"] == ["person"]
    assert data["active"] is True


def test_full_frame_roi_coverage(client: TestClient, admin_headers: dict[str, str]) -> None:
    cid = _make_camera(client, admin_headers)
    data = _create_roi(client, admin_headers, cid, points=_FULL)
    assert data["coverage_pct"] == 100.0


def test_out_of_range_coordinates_rejected(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    cid = _make_camera(client, admin_headers)
    resp = client.post(
        f"/api/v1/cameras/{cid}/rois",
        json={"name": "bad", "points": [[1.5, 0.2], [0.3, 0.4], [0.5, 0.5]]},
        headers=admin_headers,
    )
    assert resp.status_code == 422


def test_too_few_vertices_rejected(client: TestClient, admin_headers: dict[str, str]) -> None:
    cid = _make_camera(client, admin_headers)
    resp = client.post(
        f"/api/v1/cameras/{cid}/rois",
        json={"name": "bad", "points": [[0.1, 0.1], [0.2, 0.2]]},
        headers=admin_headers,
    )
    assert resp.status_code == 422


def test_list_scoped_to_camera(client: TestClient, admin_headers: dict[str, str]) -> None:
    cid = _make_camera(client, admin_headers)
    _create_roi(client, admin_headers, cid)
    resp = client.get(f"/api/v1/cameras/{cid}/rois", headers=admin_headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_get_and_patch(client: TestClient, admin_headers: dict[str, str]) -> None:
    cid = _make_camera(client, admin_headers)
    roi = _create_roi(client, admin_headers, cid)
    rid = roi["id"]

    resp = client.get(f"/api/v1/rois/{rid}", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["name"] == "Dock"

    resp = client.patch(f"/api/v1/rois/{rid}", json={"name": "Gate"}, headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["name"] == "Gate"


def test_viewer_cannot_write(
    client: TestClient, admin_headers: dict[str, str], viewer_headers: dict[str, str]
) -> None:
    cid = _make_camera(client, admin_headers)
    _create_roi(client, admin_headers, cid)
    # Viewer can read.
    assert client.get(f"/api/v1/cameras/{cid}/rois", headers=viewer_headers).status_code == 200
    # Viewer cannot write.
    resp = client.post(
        f"/api/v1/cameras/{cid}/rois",
        json={"name": "x", "points": [[0, 0], [1, 0], [1, 1]]},
        headers=viewer_headers,
    )
    assert resp.status_code == 403


def test_delete_roi(client: TestClient, admin_headers: dict[str, str]) -> None:
    cid = _make_camera(client, admin_headers)
    roi = _create_roi(client, admin_headers, cid)
    rid = roi["id"]
    assert client.delete(f"/api/v1/rois/{rid}", headers=admin_headers).status_code == 204
    assert client.get(f"/api/v1/rois/{rid}", headers=admin_headers).status_code == 404


def test_cross_tenant_returns_404(
    client: TestClient, admin_headers: dict[str, str], db_session: Session
) -> None:
    cid = _make_camera(client, admin_headers)
    roi = _create_roi(client, admin_headers, cid)
    rid = roi["id"]
    other = Site(name="Other", timezone="UTC")
    db_session.add(other)
    db_session.flush()
    row = db_session.get(Roi, rid)
    assert row is not None
    row.site_id = other.id
    db_session.commit()
    db_session.expire_all()
    assert client.get(f"/api/v1/rois/{rid}", headers=admin_headers).status_code == 404


def test_unknown_class_rejected(client: TestClient, admin_headers: dict[str, str]) -> None:
    cid = _make_camera(client, admin_headers)
    resp = client.post(
        f"/api/v1/cameras/{cid}/rois",
        json={"name": "bad", "points": [[0, 0], [1, 0], [1, 1]], "class_filter": ["unicorn"]},
        headers=admin_headers,
    )
    assert resp.status_code == 422
