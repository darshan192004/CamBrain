"""System API tests: health (no auth), status, config, OpenAPI spec gate (API §System)."""

from __future__ import annotations

from pathlib import Path

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
    ("post", "/api/v1/system/pause"),
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


def test_status_reports_hardware_and_model(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    """The dashboard's tier/model/hardware rows come from the real probe (T13)."""
    resp = client.get("/api/v1/system/status", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["hardware_tier"] in ("low", "medium", "high", "unknown")
    hardware = data["hardware"]
    for key in (
        "cpu_cores",
        "avx2",
        "vnni",
        "ram_total_mb",
        "ram_used_mb",
        "disk_total_gb",
        "disk_used_pct",
    ):
        assert key in hardware, key
    if data["hardware_tier"] != "unknown":
        model = data["model"]
        assert model["name"].endswith(".onnx")
        assert model["tier"] == data["hardware_tier"]
        assert model["input"][0] == model["input"][1]


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


def _create_camera(client: TestClient, headers: dict[str, str], name: str) -> dict:
    resp = client.post(
        "/api/v1/cameras",
        json={
            "name": name,
            "rtsp_url": "rtsp://10.0.0.5:554/Streaming/Channels/101",
            "enabled": True,
            "sample_fps": 2.0,
            "motion_threshold": 0.02,
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_stream_stats_row_measures_liveness_and_fps() -> None:
    """Live = connected consumer with fresh frames; fps measures between polls."""
    from app.services.stream.stats import StreamStats

    clock = [0.0]
    stats = StreamStats(now=lambda: clock[0])
    stats.begin(1)
    for _ in range(5):
        stats.frame(1)
    first = stats.row(1)
    assert first["active"] is True
    assert first["frames"] == 5
    assert first["last_frame_at"] is not None
    assert first["fps"] is None  # the first poll only sets the rate baseline
    clock[0] = 1.0
    for _ in range(5):
        stats.frame(1)
    second = stats.row(1)
    assert second["fps"] == 5.0
    stats.end(1)
    assert stats.row(1)["active"] is False


def test_status_cameras_report_recorded_frames(
    client: TestClient, admin_headers: dict[str, str], gate_clip_path: Path
) -> None:
    """After a stream runs, /system/status lists the camera with real counts."""
    from app.services.stream.factory import get_source_factory
    from app.services.stream.file_source import FileSource
    from app.services.stream.stats import StreamStats, get_stream_stats

    camera = _create_camera(client, admin_headers, "Back door")
    stats = StreamStats()
    client.app.dependency_overrides[get_stream_stats] = lambda: stats
    client.app.dependency_overrides[get_source_factory] = lambda: (
        lambda _cam: FileSource(Path(str(gate_clip_path)), loop=False)
    )
    try:
        resp = client.get(f"/api/v1/cameras/{camera['id']}/stream", headers=admin_headers)
        assert resp.status_code == 200
        jpeg_parts = [p for p in resp.content.split(b"--frame\r\n") if b"Content-Length" in p]
        assert len(jpeg_parts) >= 2

        status = client.get("/api/v1/system/status", headers=admin_headers).json()
        rows = {r["id"]: r for r in status["cameras"]}
        row = rows[camera["id"]]
        assert row["name"] == "Back door"
        assert row["status"] != "live"  # the viewer disconnected; totals remain
        assert row["frames_processed"] >= 2

        other = _create_camera(client, admin_headers, "Front counter")
        status = client.get("/api/v1/system/status", headers=admin_headers).json()
        rows = {r["id"]: r for r in status["cameras"]}
        assert rows[other["id"]]["status"] == "starting"
        assert "fps" not in rows[other["id"]]
        # Second poll for the streamed camera: no frames since the first, so
        # the measured rate is a real number, not a placeholder.
        assert rows[camera["id"]]["fps"] == 0.0
    finally:
        client.app.dependency_overrides.pop(get_stream_stats, None)
        client.app.dependency_overrides.pop(get_source_factory, None)


async def test_tracked_parts_brackets_stats_with_the_consumer(
    gate_clip_path: Path,
) -> None:
    """The tracked generator marks the camera live mid-stream and off after.

    TestClient buffers a whole stream before anyone can observe it, so the
    live latch is proven against the generator directly: first part in =>
    consumer registered + frame counted; close => consumer gone.
    """
    from app.services.stream.file_source import FileSource
    from app.services.stream.mjpeg import tracked_parts
    from app.services.stream.stats import StreamStats

    stats = StreamStats()
    gen = tracked_parts(FileSource(Path(str(gate_clip_path)), loop=False), stats, 7)
    first = await gen.__anext__()
    assert b"Content-Length" in first
    row = stats.row(7)
    assert row["active"] is True
    assert row["frames"] >= 1
    assert row["last_frame_at"] is not None
    await gen.aclose()
    assert stats.row(7)["active"] is False
    assert stats.row(7)["frames"] >= 1  # totals survive the disconnect


def test_status_reports_delivery_stats(
    client: TestClient, admin_headers: dict[str, str], db_session, seeded
) -> None:
    """At 2am the owner asks 'did it send?' — the status page answers (D4)."""
    from datetime import UTC, datetime

    from app.db.models import Camera, Event

    site, _a, _v = seeded
    camera = Camera(site_id=site.id, name="Dock", rtsp_url="rtsp://10.0.0.9/ch1")
    db_session.add(camera)
    db_session.flush()
    today = datetime.now(tz=UTC).replace(tzinfo=None)
    for delivery in ("sent", "sent", "pending", "failed"):
        db_session.add(
            Event(
                site_id=site.id,
                camera_id=camera.id,
                rule_id=None,
                triggered_by="system",
                started_at=today,
                severity="warning",
                summary="s",
                delivery_status=delivery,
            )
        )
    db_session.commit()
    res = client.get("/api/v1/system/status", headers=admin_headers)
    stats = res.json()["stats"]
    assert stats["events_today"] == 4
    assert stats["alerts_sent"] == 2
    assert stats["alerts_failed"] == 1
