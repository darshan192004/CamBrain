"""Settings and notifiers API tests (API §Users, settings)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_get_settings(client: TestClient, admin_headers: dict[str, str]) -> None:
    resp = client.get("/api/v1/settings", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["timezone"] == "Asia/Kolkata"
    assert data["retention_days"] == 7
    assert data["disk_quota_pct"] == 80


def test_viewer_can_read_settings(client: TestClient, viewer_headers: dict[str, str]) -> None:
    assert client.get("/api/v1/settings", headers=viewer_headers).status_code == 200


def test_viewer_cannot_patch_settings(client: TestClient, viewer_headers: dict[str, str]) -> None:
    resp = client.patch("/api/v1/settings", json={"retention_days": 30}, headers=viewer_headers)
    assert resp.status_code == 403


def test_patch_settings(client: TestClient, admin_headers: dict[str, str]) -> None:
    resp = client.patch("/api/v1/settings", json={"retention_days": 30}, headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["retention_days"] == 30


def test_retention_out_of_range_rejected(client: TestClient, admin_headers: dict[str, str]) -> None:
    resp = client.patch("/api/v1/settings", json={"retention_days": 0}, headers=admin_headers)
    assert resp.status_code == 422


def test_notifiers_crud(client: TestClient, admin_headers: dict[str, str]) -> None:
    # Empty initially.
    assert client.get("/api/v1/notifiers", headers=admin_headers).json() == []
    # Create.
    resp = client.post(
        "/api/v1/notifiers",
        json={"kind": "telegram", "enabled": True, "config": {"bot_token": "x", "chat_id": "1"}},
        headers=admin_headers,
    )
    assert resp.status_code == 201, resp.text
    nid = resp.json()["id"]
    # List.
    data = client.get("/api/v1/notifiers", headers=admin_headers).json()
    assert len(data) == 1
    assert data[0]["kind"] == "telegram"
    # Patch.
    resp = client.patch(f"/api/v1/notifiers/{nid}", json={"enabled": False}, headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["enabled"] is False
    # Delete.
    assert client.delete(f"/api/v1/notifiers/{nid}", headers=admin_headers).status_code == 204
    assert client.get("/api/v1/notifiers", headers=admin_headers).json() == []


def test_notifier_test_is_501(client: TestClient, admin_headers: dict[str, str]) -> None:
    """Transport is Phase 4; the route exists and returns an explicit 501."""
    resp = client.post("/api/v1/notifiers/test", headers=admin_headers)
    assert resp.status_code == 501


def test_viewer_cannot_create_notifier(client: TestClient, viewer_headers: dict[str, str]) -> None:
    resp = client.post("/api/v1/notifiers", json={"kind": "telegram"}, headers=viewer_headers)
    assert resp.status_code == 403
