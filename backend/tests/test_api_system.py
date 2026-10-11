"""System API tests: health (no auth), status, config, OpenAPI spec gate (API §System)."""

from __future__ import annotations

from fastapi.testclient import TestClient

# Endpoints documented in docs/API.md (auth + cameras + rois + rules + events +
# users/settings/system). The list is the gate: a route added or removed without
# updating API.md fails this test, which is the point — the spec is trusted.
DOCUMENTED_PATHS = {
    ("post", "/api/v1/auth/login"),
    ("post", "/api/v1/auth/refresh"),
    ("post", "/api/v1/auth/logout"),
    ("get", "/api/v1/auth/me"),
    ("post", "/api/v1/auth/change-password"),
    ("get", "/api/v1/cameras"),
    ("post", "/api/v1/cameras"),
    ("get", "/api/v1/cameras/{camera_id}"),
    ("patch", "/api/v1/cameras/{camera_id}"),
    ("delete", "/api/v1/cameras/{camera_id}"),
    ("post", "/api/v1/cameras/{camera_id}/test"),
    ("post", "/api/v1/cameras/test"),
    ("post", "/api/v1/cameras/{camera_id}/snapshot"),
    ("get", "/api/v1/cameras/{camera_id}/stream"),
    ("get", "/api/v1/cameras/{camera_id}/rois"),
    ("post", "/api/v1/cameras/{camera_id}/rois"),
    ("get", "/api/v1/rois/{roi_id}"),
    ("patch", "/api/v1/rois/{roi_id}"),
    ("delete", "/api/v1/rois/{roi_id}"),
    ("get", "/api/v1/cameras/{camera_id}/rules"),
    ("get", "/api/v1/rules"),
    ("post", "/api/v1/cameras/{camera_id}/rules"),
    ("get", "/api/v1/rules/{rule_id}"),
    ("patch", "/api/v1/rules/{rule_id}"),
    ("delete", "/api/v1/rules/{rule_id}"),
    ("post", "/api/v1/rules/{rule_id}/test"),
    ("get", "/api/v1/events"),
    ("get", "/api/v1/events/stats"),
    ("get", "/api/v1/events/{event_id}"),
    ("post", "/api/v1/events/{event_id}/acknowledge"),
    ("post", "/api/v1/events/acknowledge-bulk"),
    ("get", "/api/v1/events/{event_id}/clip"),
    ("get", "/api/v1/events/{event_id}/thumbnail"),
    ("get", "/api/v1/users"),
    ("post", "/api/v1/users"),
    ("get", "/api/v1/users/{user_id}"),
    ("patch", "/api/v1/users/{user_id}"),
    ("delete", "/api/v1/users/{user_id}"),
    ("get", "/api/v1/settings"),
    ("patch", "/api/v1/settings"),
    ("get", "/api/v1/notifiers"),
    ("post", "/api/v1/notifiers"),
    ("patch", "/api/v1/notifiers/{notifier_id}"),
    ("delete", "/api/v1/notifiers/{notifier_id}"),
    ("post", "/api/v1/notifiers/test"),
    ("get", "/api/v1/system/health"),
    ("get", "/api/v1/system/status"),
    ("get", "/api/v1/system/config"),
    ("post", "/api/v1/system/config"),
}


def test_openapi_matches_spec(client: TestClient) -> None:
    """The generated OpenAPI path list must equal API.md's endpoint table.

    A route added or removed without updating API.md fails here — the spec is
    trusted more than the code, and this test is what keeps them honest.
    """
    resp = client.get("/api/v1/openapi.json")
    assert resp.status_code == 200
    paths = resp.json()["paths"]
    actual = set()
    for path, methods in paths.items():
        for method in methods:
            actual.add((method.lower(), path))
    assert actual == DOCUMENTED_PATHS, (
        f"missing from OpenAPI (documented but not implemented): "
        f"{DOCUMENTED_PATHS - actual}\n"
        f"extra in OpenAPI (implemented but not documented): "
        f"{actual - DOCUMENTED_PATHS}"
    )


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
