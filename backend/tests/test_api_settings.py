"""Settings and notifiers API tests (API §Users, settings)."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.core.crypto import decrypt
from app.db.models.site import Site


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


def test_notifier_token_is_encrypted_and_masked(
    client: TestClient, admin_headers: dict[str, str], db_session, seeded
) -> None:
    res = client.post(
        "/api/v1/notifiers",
        json={
            "kind": "telegram",
            "enabled": True,
            "config": {"chat_id": "42", "bot_token": "SECRET-TOKEN"},
        },
        headers=admin_headers,
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert '"bot_token"' not in json.dumps(body)
    assert "SECRET-TOKEN" not in json.dumps(body)
    assert body["has_token"] is True

    got = client.get("/api/v1/notifiers", headers=admin_headers)
    assert "SECRET-TOKEN" not in got.text
    assert '"bot_token"' not in got.text
    assert got.json()[0]["has_token"] is True

    db_session.expire_all()
    site, _admin, _viewer = seeded
    raw = db_session.get(Site, site.id).notifier_config
    assert raw[0]["config"]["bot_token_enc"] != "SECRET-TOKEN"
    assert decrypt(raw[0]["config"]["bot_token_enc"]) == "SECRET-TOKEN"


def test_notifier_patch_without_token_keeps_existing(
    client: TestClient, admin_headers: dict[str, str], db_session, seeded
) -> None:
    client.post(
        "/api/v1/notifiers",
        json={
            "kind": "telegram",
            "enabled": True,
            "config": {"chat_id": "42", "bot_token": "SECRET-TOKEN"},
        },
        headers=admin_headers,
    )
    res = client.patch(
        "/api/v1/notifiers/0",
        json={"enabled": False, "config": {"chat_id": "43"}},
        headers=admin_headers,
    )
    assert res.status_code == 200
    assert res.json()["has_token"] is True, "a config without a token must not wipe the old one"

    db_session.expire_all()
    site, _admin, _viewer = seeded
    raw = db_session.get(Site, site.id).notifier_config
    assert decrypt(raw[0]["config"]["bot_token_enc"]) == "SECRET-TOKEN"
    assert raw[0]["config"]["chat_id"] == "43"


def test_notifier_test_endpoint_sends_real_message(
    client: TestClient, admin_headers: dict[str, str], monkeypatch
) -> None:
    from app.api.routers import settings as settings_router

    class FakeNotifier:
        async def send(self, event):  # noqa: ANN001, ARG002
            return None

        async def test_message(self):
            return {"ok": True, "result": {"message_id": 7}}

    monkeypatch.setattr(settings_router, "_build_notifier", lambda _entry: FakeNotifier())
    client.post(
        "/api/v1/notifiers",
        json={
            "kind": "telegram",
            "enabled": True,
            "config": {"chat_id": "42", "bot_token": "T"},
        },
        headers=admin_headers,
    )
    res = client.post("/api/v1/notifiers/test", headers=admin_headers)
    assert res.status_code == 200 and res.json()["ok"] is True
    assert res.json()["response"] == {"ok": True, "result": {"message_id": 7}}


def test_notifier_test_endpoint_reports_failure(
    client: TestClient, admin_headers: dict[str, str], monkeypatch
) -> None:
    from app.api.routers import settings as settings_router
    from app.services.alerts.telegram import TelegramError

    def boom(_entry):
        raise TelegramError("telegram sendMessage rejected: chat not found")

    monkeypatch.setattr(settings_router, "_build_notifier", boom)
    client.post(
        "/api/v1/notifiers",
        json={
            "kind": "telegram",
            "enabled": True,
            "config": {"chat_id": "42", "bot_token": "T"},
        },
        headers=admin_headers,
    )
    res = client.post("/api/v1/notifiers/test", headers=admin_headers)
    assert res.status_code == 200 and res.json()["ok"] is False
    assert "chat not found" in res.json()["error"]


def test_viewer_cannot_create_notifier(client: TestClient, viewer_headers: dict[str, str]) -> None:
    resp = client.post("/api/v1/notifiers", json={"kind": "telegram"}, headers=viewer_headers)
    assert resp.status_code == 403


def test_notifier_test_without_stored_token_is_handled(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    """A token-less entry must not 500 (PR-Agent review finding, 2026-10-17)."""
    client.post(
        "/api/v1/notifiers",
        json={"kind": "telegram", "enabled": True, "config": {"chat_id": "42"}},
        headers=admin_headers,
    )
    res = client.post("/api/v1/notifiers/test", headers=admin_headers)
    assert res.status_code == 200 and res.json()["ok"] is False
    assert "stored token" in res.json()["error"]


def test_notifier_test_skips_unusable_kinds(
    client: TestClient, admin_headers: dict[str, str], monkeypatch
) -> None:
    """A webhook entry first in the list must not break testing the telegram one."""
    from app.api.routers import settings as settings_router

    class FakeNotifier:
        async def test_message(self):
            return {"ok": True, "result": {"message_id": 9}}

    monkeypatch.setattr(settings_router, "_build_notifier", lambda _entry: FakeNotifier())
    client.post(
        "/api/v1/notifiers",
        json={"kind": "webhook", "enabled": True, "config": {"url": "https://x.invalid"}},
        headers=admin_headers,
    )
    client.post(
        "/api/v1/notifiers",
        json={
            "kind": "telegram",
            "enabled": True,
            "config": {"chat_id": "42", "bot_token": "T"},
        },
        headers=admin_headers,
    )
    res = client.post("/api/v1/notifiers/test", headers=admin_headers)
    assert res.status_code == 200 and res.json()["ok"] is True
    assert res.json()["response"]["result"]["message_id"] == 9
