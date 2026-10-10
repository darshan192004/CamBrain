"""System API tests: health (no auth), status, config (API §System)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_is_unauthenticated(client: TestClient) -> None:
    """Health must not require a token so the Tauri shell and installer can poll it."""
    resp = client.get("/api/v1/system/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "version" in data
    assert "uptime_s" in data
    # The three fields are the entire surface — no hardware, no config.
    assert set(data) == {"status", "version", "uptime_s"}


def test_status_requires_auth(client: TestClient) -> None:
    assert client.get("/api/v1/system/status").status_code == 401


def test_status_shape(
    client: TestClient, admin_headers: dict[str, str], viewer_headers: dict[str, str]
) -> None:
    for headers in (admin_headers, viewer_headers):
        resp = client.get("/api/v1/system/status", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "hardware_tier" in data
        assert "cameras" in data
        assert "stats" in data


def test_config_requires_admin(client: TestClient, viewer_headers: dict[str, str]) -> None:
    assert client.get("/api/v1/system/config", headers=viewer_headers).status_code == 403


def test_config_read(client: TestClient, admin_headers: dict[str, str]) -> None:
    resp = client.get("/api/v1/system/config", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "bind_host" in data
    assert "cors_origins" in data
    # Secrets are never exposed.
    assert "jwt_secret" not in data
    assert "db_path" not in data


def test_config_write_is_501(client: TestClient, admin_headers: dict[str, str]) -> None:
    """Hot-reload is Phase 4; the route exists and returns an explicit 501."""
    resp = client.post("/api/v1/system/config", headers=admin_headers)
    assert resp.status_code == 501
