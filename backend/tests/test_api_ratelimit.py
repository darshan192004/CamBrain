"""Fixed-window rate limiter: rows from API A6, exclusions honored."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.ratelimit import DEFAULT_LIMIT, _limit_for


def test_camera_test_route_limited_at_ten_per_minute(
    client: TestClient,
    admin_headers: dict[str, str],  # noqa: ARG001
) -> None:
    statuses = [
        client.post("/api/v1/cameras/test", json={"rtsp_url": "rtsp://127.0.0.1:1/x"}).status_code
        for _ in range(12)
    ]
    assert 429 in statuses, f"the 10/min camera-test cap must bite by request 12: {statuses}"


def test_login_never_rate_limited_by_middleware(client: TestClient) -> None:
    for _ in range(150):
        res = client.post("/api/v1/auth/login", json={"username": "nobody", "password": "x"})
        assert res.status_code != 429, "login has its own lockout (423), not 429"


def test_general_route_120_per_minute(client: TestClient, admin_headers: dict[str, str]) -> None:
    for _ in range(130):
        res = client.get("/api/v1/events", headers=admin_headers)
        if res.status_code == 429:
            assert "retry-after" in {k.lower() for k in res.headers}
            assert res.json()["error"]["code"] == "RATE_LIMITED"
            assert res.json()["error"]["correlation_id"] != ""
            break
    else:
        raise AssertionError("the 121st general request within a minute must be 429")


def test_health_never_rate_limited(client: TestClient) -> None:
    for _ in range(130):
        assert client.get("/api/v1/system/health").status_code == 200


def test_limit_for_rows_and_exclusions() -> None:
    """The table itself: exclusions, probe rows, default (D9/API A6)."""
    assert _limit_for("POST", "/api/v1/auth/login") is None  # lockout owns it
    assert _limit_for("GET", "/api/v1/system/health") is None  # liveness owns it
    assert _limit_for("GET", "/api/v1/cameras/1/stream") is None  # slot cap owns it
    assert _limit_for("GET", "/api/v1/ws/alerts") is None  # socket handshake
    assert _limit_for("GET", "/healthz") is None  # not under the API prefix
    assert _limit_for("POST", "/api/v1/auth/refresh") == 30
    assert _limit_for("POST", "/api/v1/cameras/test") == 10  # draft probe
    assert _limit_for("POST", "/api/v1/cameras/3/test") == 10  # saved-camera probe
    assert _limit_for("POST", "/api/v1/cameras") == DEFAULT_LIMIT  # create: not a probe
    assert _limit_for("GET", "/api/v1/events") == DEFAULT_LIMIT
