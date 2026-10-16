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


def test_notifier_test_delivers(
    client: TestClient, admin_headers: dict[str, str], monkeypatch, seeded
) -> None:
    """A configured notifier delivers; the endpoint returns Telegram verbatim."""
    import httpx

    site, _admin, _viewer = seeded

    async def _ok(*_args: object, **_kwargs: object) -> object:
        class _R:
            status_code = 200

            def json(self) -> dict[str, object]:
                return {"ok": True, "result": {"message_id": 1}}

        return _R()

    monkeypatch.setattr(httpx.AsyncClient, "post", _ok)
    create = client.post(
        "/api/v1/notifiers",
        json={"kind": "telegram", "enabled": True, "config": {"bot_token": "T", "chat_id": "1"}},
        headers=admin_headers,
    )
    assert create.status_code == 201, create.text
    resp = client.post("/api/v1/notifiers/test", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["ok"] is True


def test_notifier_test_without_sender_is_422(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    """No configured sender is a validation error, not a silent pass."""
    resp = client.post("/api/v1/notifiers/test", headers=admin_headers)
    assert resp.status_code == 422


def test_notifier_secrets_sealed_and_masked(
    client: TestClient, admin_headers: dict[str, str], db_session, seeded
) -> None:
    """The token is encrypted at rest and never returned by GET."""
    site, _admin, _viewer = seeded
    client.post(
        "/api/v1/notifiers",
        json={
            "kind": "telegram",
            "enabled": True,
            "config": {"bot_token": "hunter2", "chat_id": "1"},
        },
        headers=admin_headers,
    )
    db_session.expire_all()
    from app.db.models.site import Site

    row = db_session.get(Site, site.id)
    assert row is not None
    stored = row.notifier_config
    assert stored is not None and "hunter2" not in str(stored)
    listed = client.get("/api/v1/notifiers", headers=admin_headers).json()
    assert "hunter2" not in str(listed)
    assert listed[0]["config"]["bot_token"] == "••••••••"


def test_viewer_cannot_create_notifier(client: TestClient, viewer_headers: dict[str, str]) -> None:
    resp = client.post("/api/v1/notifiers", json={"kind": "telegram"}, headers=viewer_headers)
    assert resp.status_code == 403
