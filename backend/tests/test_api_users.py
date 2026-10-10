"""Users API tests: admin CRUD, last-admin 409, cross-tenant 404 (API §Users)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_list_users_shape(client: TestClient, admin_headers: dict[str, str]) -> None:
    resp = client.get("/api/v1/users", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()
    usernames = {u["username"] for u in data}
    assert usernames == {"ramesh", "viewer"}
    # Password hash is never exposed.
    assert "password_hash" not in resp.text
    for u in data:
        assert set(u) == {"id", "username", "role", "is_active", "created_at", "last_login_at"}


def test_create_user(client: TestClient, admin_headers: dict[str, str]) -> None:
    resp = client.post(
        "/api/v1/users",
        json={"username": "operator", "password": "operator-pass-1", "role": "viewer"},
        headers=admin_headers,
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["username"] == "operator"
    assert data["role"] == "viewer"
    assert "password" not in data


def test_viewer_cannot_manage_users(client: TestClient, viewer_headers: dict[str, str]) -> None:
    for method, url, body in [
        ("get", "/api/v1/users", None),
        ("post", "/api/v1/users", {"username": "x", "password": "password1"}),
        ("patch", "/api/v1/users/1", {"role": "viewer"}),
        ("delete", "/api/v1/users/1", None),
    ]:
        kwargs = {"json": body} if body is not None else {}
        resp = getattr(client, method)(url, headers=viewer_headers, **kwargs)
        assert resp.status_code == 403, f"{method} {url} -> {resp.status_code}"


def test_cannot_delete_last_admin(
    client: TestClient, admin_headers: dict[str, str], db_session
) -> None:
    """The last remaining admin cannot be deleted (409)."""
    from app.db.models import User

    # Find the admin user id.
    admin = db_session.query(User).filter(User.username == "ramesh").one()
    resp = client.delete(f"/api/v1/users/{admin.id}", headers=admin_headers)
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "CONFLICT"


def test_cannot_demote_last_admin(
    client: TestClient, admin_headers: dict[str, str], db_session
) -> None:
    from app.db.models import User

    admin = db_session.query(User).filter(User.username == "ramesh").one()
    resp = client.patch(f"/api/v1/users/{admin.id}", json={"role": "viewer"}, headers=admin_headers)
    assert resp.status_code == 409


def test_can_delete_second_admin(client: TestClient, admin_headers: dict[str, str]) -> None:
    """With two admins, deleting one is allowed."""
    # Create a second admin.
    resp = client.post(
        "/api/v1/users",
        json={"username": "second", "password": "second-pass-1", "role": "admin"},
        headers=admin_headers,
    )
    assert resp.status_code == 201
    second_id = resp.json()["id"]
    # Now delete the second admin — should be allowed.
    resp = client.delete(f"/api/v1/users/{second_id}", headers=admin_headers)
    assert resp.status_code == 204


def test_cross_tenant_returns_404(
    client: TestClient, admin_headers: dict[str, str], db_session
) -> None:
    from app.db.models import Site, User

    admin = db_session.query(User).filter(User.username == "ramesh").one()
    other = Site(name="Other", timezone="UTC")
    db_session.add(other)
    db_session.flush()
    admin.site_id = other.id
    db_session.commit()
    db_session.expire_all()
    assert client.get(f"/api/v1/users/{admin.id}", headers=admin_headers).status_code == 404


def test_patch_password(client: TestClient, admin_headers: dict[str, str], db_session) -> None:
    from app.db.models import User

    viewer = db_session.query(User).filter(User.username == "viewer").one()
    resp = client.patch(
        f"/api/v1/users/{viewer.id}",
        json={"password": "new-password-99"},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    # Login with the new password.
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": "viewer", "password": "new-password-99"},
        headers={"X-CambBrain-Client": "tests"},
    )
    assert resp.status_code == 200
