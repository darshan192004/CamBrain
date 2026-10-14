"""Auth identity projection: GET /auth/me carries the site name for the top bar (Task 4.9)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_me_requires_auth(client: TestClient) -> None:
    """An anonymous call is 401 with the standard envelope."""
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "UNAUTHENTICATED"


def test_me_returns_identity_and_site_name(
    client: TestClient,
    admin_headers: dict[str, str],
) -> None:
    """The dashboard boot payload: who you are, your role, and your site's name."""
    resp = client.get("/api/v1/auth/me", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert set(data) == {"user_id", "username", "role", "site_id", "site_name"}
    assert data["username"] == "ramesh"
    assert data["role"] == "admin"
    assert data["site_id"] == 1
    assert data["site_name"] == "Test Site"
