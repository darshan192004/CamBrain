"""Cameras API tests: CRUD, secret masking, PATCH semantics, tenancy (API §Cameras).

Covers the Phase 2 verification-matrix rows: `test_get_never_returns_password`,
`test_cannot_pass_site_id`, viewer read-only, and the CSRF client-header gate.
"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import Camera, Site, User

_URL = "rtsp://10.0.0.5:554/Streaming/Channels/101"


def _create(client: TestClient, headers: dict[str, str], **overrides: object) -> dict:
    body: dict = {
        "name": "Back door",
        "rtsp_url": _URL,
        "username": "admin",
        "password": "secret123",
        "enabled": True,
        "sample_fps": 2.0,
        "motion_threshold": 0.02,
    }
    body.update(overrides)
    resp = client.post("/api/v1/cameras", json=body, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_create_returns_masked_password(client: TestClient, admin_headers: dict[str, str]) -> None:
    data = _create(client, admin_headers)
    assert data["has_password"] is True
    assert data["password"] == "••••••••"
    assert "secret123" not in resp_text(data)
    assert "username" not in data


def resp_text(data: dict) -> str:
    import json

    return json.dumps(data)


def test_get_never_returns_password(client: TestClient, admin_headers: dict[str, str]) -> None:
    created = _create(client, admin_headers)
    resp = client.get(f"/api/v1/cameras/{created['id']}", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.text
    assert "secret123" not in body
    assert "••••••••" in body
    data = resp.json()
    assert data["has_password"] is True
    assert "username" not in data


def test_list_masks_passwords(client: TestClient, admin_headers: dict[str, str]) -> None:
    _create(client, admin_headers)
    resp = client.get("/api/v1/cameras", headers=admin_headers)
    assert resp.status_code == 200
    assert "secret123" not in resp.text
    assert len(resp.json()) == 1


def test_cannot_pass_site_id(
    client: TestClient, admin_headers: dict[str, str], seeded: tuple[Site, User, User]
) -> None:
    """A body-supplied site_id is ignored; the token's site_id wins (IDOR)."""
    site, _admin, _viewer = seeded
    data = _create(client, admin_headers, site_id=99999)
    camera_id = data["id"]
    # The row is owned by the token's site, not the body's.
    resp = client.get(f"/api/v1/cameras/{camera_id}", headers=admin_headers)
    assert resp.status_code == 200


def test_create_requires_admin(client: TestClient, viewer_headers: dict[str, str]) -> None:
    resp = client.post(
        "/api/v1/cameras",
        json={"name": "x", "rtsp_url": _URL},
        headers=viewer_headers,
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"


def test_viewer_is_read_only(
    client: TestClient, admin_headers: dict[str, str], viewer_headers: dict[str, str]
) -> None:
    created = _create(client, admin_headers)
    cid = created["id"]
    # Viewer can read.
    assert client.get(f"/api/v1/cameras/{cid}", headers=viewer_headers).status_code == 200
    assert client.get("/api/v1/cameras", headers=viewer_headers).status_code == 200
    # Viewer cannot write. (delete takes no json body.)
    writes: list[tuple[str, str, dict | None]] = [
        ("post", "/api/v1/cameras", {}),
        ("patch", f"/api/v1/cameras/{cid}", {}),
        ("delete", f"/api/v1/cameras/{cid}", None),
        ("post", f"/api/v1/cameras/{cid}/test", {}),
    ]
    for method, url, body in writes:
        kwargs = {"json": body} if body is not None else {}
        resp = getattr(client, method)(url, headers=viewer_headers, **kwargs)
        assert resp.status_code == 403, f"{method} {url} -> {resp.status_code}"


def test_mutating_requires_client_header(
    db_session: Session,
    seeded: tuple[Site, User, User],  # noqa: ARG001
) -> None:
    """A mutating request without X-CambBrain-Client is blocked (CSRF)."""
    from app.api.deps import get_db
    from app.main import create_app

    app = create_app()

    def _override_db() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    # This client has no default X-CambBrain-Client header.
    with TestClient(app, base_url="http://testserver") as bare:
        # Missing client header -> rejected.
        resp = bare.post(
            "/api/v1/auth/login",
            json={"username": "ramesh", "password": "correct-horse-battery"},
        )
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "FORBIDDEN"
        # Wrong content-type -> rejected even with the client header.
        resp = bare.post(
            "/api/v1/auth/login",
            content=b"{}",
            headers={"Content-Type": "text/plain", "X-CambBrain-Client": "tests"},
        )
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "FORBIDDEN"
    app.dependency_overrides.clear()


def test_patch_password_semantics(
    client: TestClient, admin_headers: dict[str, str], db_session: Session
) -> None:
    """Omit = unchanged, null = clears, empty string = 422."""
    created = _create(client, admin_headers)
    cid = created["id"]

    # Omit password -> unchanged (still masked).
    resp = client.patch(
        f"/api/v1/cameras/{cid}", json={"name": "Front door"}, headers=admin_headers
    )
    assert resp.status_code == 200
    assert resp.json()["has_password"] is True

    # Empty string -> 422.
    resp = client.patch(f"/api/v1/cameras/{cid}", json={"password": ""}, headers=admin_headers)
    assert resp.status_code == 422

    # null -> clears.
    resp = client.patch(f"/api/v1/cameras/{cid}", json={"password": None}, headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["has_password"] is False

    row = db_session.get(Camera, cid)
    assert row is not None and row.rtsp_password_enc is None


def test_delete_removes_camera(client: TestClient, admin_headers: dict[str, str]) -> None:
    created = _create(client, admin_headers)
    cid = created["id"]
    assert client.delete(f"/api/v1/cameras/{cid}", headers=admin_headers).status_code == 204
    assert client.get(f"/api/v1/cameras/{cid}", headers=admin_headers).status_code == 404


def test_cross_tenant_returns_404(
    client: TestClient, admin_headers: dict[str, str], db_session: Session
) -> None:
    """A camera id from another site is a 404, never a 403 (SECURITY 4.3)."""
    created = _create(client, admin_headers)
    cid = created["id"]
    # Re-home the row to a different site directly.
    other = Site(name="Other", timezone="UTC")
    db_session.add(other)
    db_session.flush()
    row = db_session.get(Camera, cid)
    assert row is not None
    row.site_id = other.id
    db_session.commit()
    resp = client.get(f"/api/v1/cameras/{cid}", headers=admin_headers)
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "NOT_FOUND"


def test_test_endpoint_returns_ok_false_with_code(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    """A failed probe is 200 with a typed error_code, not an HTTP error."""
    created = _create(client, admin_headers)
    resp = client.post(f"/api/v1/cameras/{created['id']}/test", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert data["error_code"] in {
        "AUTH_FAILED",
        "CONNECT_TIMEOUT",
        "HOST_UNREACHABLE",
        "NO_SUCH_STREAM",
        "DECODE_FAILED",
        "CANCELLED",
    }


def test_stream_is_501_until_wired(client: TestClient, admin_headers: dict[str, str]) -> None:
    created = _create(client, admin_headers)
    resp = client.get(f"/api/v1/cameras/{created['id']}/stream", headers=admin_headers)
    assert resp.status_code == 501
