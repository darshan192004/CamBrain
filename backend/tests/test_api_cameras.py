"""Cameras API tests: CRUD, secret masking, PATCH semantics, tenancy (API §Cameras).

Covers the Phase 2 verification-matrix rows: `test_get_never_returns_password`,
`test_cannot_pass_site_id`, viewer read-only, and the CSRF client-header gate.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.errors import StreamError
from app.db.models import Camera, Site, User
from app.services.stream.factory import get_source_factory
from app.services.stream.file_source import FileSource
from app.services.stream.source import FrameSource

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


def _override_factory(client: TestClient, factory: Callable[[Camera], FrameSource]):
    """Context manager: point the API's frame-source seam at a test double."""

    @contextmanager
    def _ctx() -> Iterator[None]:
        client.app.dependency_overrides[get_source_factory] = lambda: factory
        try:
            yield
        finally:
            client.app.dependency_overrides.pop(get_source_factory, None)

    return _ctx()


def test_probe_ok_reports_dims_and_fps(
    client: TestClient, admin_headers: dict[str, str], gate_clip_path: Path
) -> None:
    """A reachable source reports real dimensions, fps, and a human message."""
    clip = Path(str(gate_clip_path))
    created = _create(client, admin_headers)
    with _override_factory(client, lambda _cam: FileSource(clip, loop=False)):
        resp = client.post(f"/api/v1/cameras/{created['id']}/test", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["error_code"] is None
    assert data["frame_width"] and data["frame_width"] > 0
    assert data["frame_height"] and data["frame_height"] > 0
    assert data["fps"] and data["fps"] > 0
    assert data["latency_ms"] is not None and data["latency_ms"] >= 0
    assert data["message"].startswith("Connected.")


def test_probe_transport_failure_is_200_with_code(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    """A failed probe is data, not an HTTP error (API Cameras /test)."""

    class _Refused:
        async def frames(self) -> AsyncIterator[object]:
            raise ConnectionRefusedError("connection refused")
            yield  # pragma: no cover - makes this an async generator

        async def close(self) -> None:
            return None

    created = _create(client, admin_headers)
    with _override_factory(client, lambda _cam: _Refused()):
        resp = client.post(f"/api/v1/cameras/{created['id']}/test", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert data["error_code"] == "HOST_UNREACHABLE"
    assert data["message"]
    # Never leak the camera password in a diagnostic message.
    assert "secret123" not in resp.text


def test_probe_stream_error_reason_is_honoured(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    """A StreamError raised by the source carries its typed reason through."""

    class _Auth:
        async def frames(self) -> AsyncIterator[object]:
            raise StreamError("AUTH_FAILED: rtsp://10.0.0.5:554/… (401 Unauthorized)")
            yield  # pragma: no cover

        async def close(self) -> None:
            return None

    created = _create(client, admin_headers)
    with _override_factory(client, lambda _cam: _Auth()):
        resp = client.post(f"/api/v1/cameras/{created['id']}/test", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert data["error_code"] == "AUTH_FAILED"
    assert "Authentication failed" in data["message"]


def test_probe_unknown_camera_404(client: TestClient, admin_headers: dict[str, str]) -> None:
    resp = client.post("/api/v1/cameras/999999/test", headers=admin_headers)
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "NOT_FOUND"


def test_snapshot_returns_jpeg_magic(
    client: TestClient, admin_headers: dict[str, str], gate_clip_path: Path
) -> None:
    """Snapshot is a real JPEG with no-store, not a JSON envelope (D2)."""
    created = _create(client, admin_headers)
    with _override_factory(client, lambda _cam: FileSource(Path(str(gate_clip_path)), loop=False)):
        resp = client.post(f"/api/v1/cameras/{created['id']}/snapshot", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"
    assert resp.headers["cache-control"] == "no-store"
    assert resp.content.startswith(b"\xff\xd8")
    assert b"secret123" not in resp.content


def test_snapshot_404_unknown_camera(client: TestClient, admin_headers: dict[str, str]) -> None:
    resp = client.post("/api/v1/cameras/999999/snapshot", headers=admin_headers)
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "NOT_FOUND"


def test_snapshot_viewer_allowed(
    client: TestClient,
    admin_headers: dict[str, str],
    viewer_headers: dict[str, str],
    gate_clip_path: Path,
) -> None:
    """Snapshot is role `any` — the ROI editor must not need admin."""
    created = _create(client, admin_headers)
    with _override_factory(client, lambda _cam: FileSource(Path(str(gate_clip_path)), loop=False)):
        resp = client.post(f"/api/v1/cameras/{created['id']}/snapshot", headers=viewer_headers)
    assert resp.status_code == 200


def test_snapshot_source_failure_is_error_envelope(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    """An unreadable camera fails with the standard envelope, never a half-JPEG."""

    class _Refused:
        async def frames(self) -> AsyncIterator[object]:
            raise ConnectionRefusedError("connection refused")
            yield  # pragma: no cover

        async def close(self) -> None:
            return None

    created = _create(client, admin_headers)
    with _override_factory(client, lambda _cam: _Refused()):
        resp = client.post(f"/api/v1/cameras/{created['id']}/snapshot", headers=admin_headers)
    assert resp.status_code == 500
    body = resp.json()
    assert body["error"]["code"] == "INTERNAL"
    assert "Could not connect" in body["error"]["message"]
    assert "secret123" not in resp.text


def test_stream_sends_multipart_frames(
    client: TestClient, admin_headers: dict[str, str], gate_clip_path: Path
) -> None:
    """The stream is multipart JPEG parts, ending with the close boundary."""
    created = _create(client, admin_headers)
    with _override_factory(client, lambda _cam: FileSource(Path(str(gate_clip_path)), loop=False)):
        resp = client.get(f"/api/v1/cameras/{created['id']}/stream", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("multipart/x-mixed-replace; boundary=frame")
    body = resp.content
    jpeg_parts = [p for p in body.split(b"--frame\r\n") if b"Content-Length" in p]
    assert len(jpeg_parts) >= 2
    assert b"secret123" not in body
    assert body.endswith(b"--frame--\r\n")


def test_stream_404_unknown_camera(client: TestClient, admin_headers: dict[str, str]) -> None:
    resp = client.get("/api/v1/cameras/999999/stream", headers=admin_headers)
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "NOT_FOUND"


def test_stream_slot_cap_returns_503(
    client: TestClient, admin_headers: dict[str, str], gate_clip_path: Path
) -> None:
    """D1: cap 12 concurrent per client IP; a full slot is 503 NO_CAPACITY."""
    from app.services.stream.mjpeg import StreamSlots, get_stream_slots

    slots = StreamSlots(per_ip=1)
    client.app.dependency_overrides[get_stream_slots] = lambda: slots
    try:
        assert slots.try_acquire("testclient")  # hold the only slot
        resp = client.get(
            f"/api/v1/cameras/{_create(client, admin_headers)['id']}/stream", headers=admin_headers
        )
        assert resp.status_code == 503
        assert resp.json()["error"]["code"] == "NO_CAPACITY"

        slots.release("testclient")
        created = _create(client, admin_headers)
        with _override_factory(
            client, lambda _cam: FileSource(Path(str(gate_clip_path)), loop=False)
        ):
            resp = client.get(f"/api/v1/cameras/{created['id']}/stream", headers=admin_headers)
        assert resp.status_code == 200
        # The slot is released when the stream generator finishes.
        assert slots.try_acquire("testclient")
        slots.release("testclient")
    finally:
        client.app.dependency_overrides.pop(get_stream_slots, None)


def test_draft_probe_ok_never_persists(
    client: TestClient, admin_headers: dict[str, str], gate_clip_path: Path
) -> None:
    """POST /cameras/test probes unsaved credentials without creating a row
    (PRD: "test connection before saving")."""
    clip = Path(str(gate_clip_path))
    body = {"name": "Draft", "rtsp_url": _URL, "username": "admin", "password": "secret123"}
    with _override_factory(client, lambda _cam: FileSource(clip, loop=False)):
        resp = client.post("/api/v1/cameras/test", json=body, headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["frame_width"] and data["frame_width"] > 0
    assert data["message"].startswith("Connected.")
    assert client.get("/api/v1/cameras", headers=admin_headers).json() == []


def test_draft_probe_failure_is_200_with_code(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    """A draft probe failure is data with a typed code, never an HTTP error."""

    class _Refused:
        async def frames(self) -> AsyncIterator[object]:
            raise ConnectionRefusedError("connection refused")
            yield  # pragma: no cover

        async def close(self) -> None:
            return None

    body = {"name": "Draft", "rtsp_url": _URL, "password": "secret123"}
    with _override_factory(client, lambda _cam: _Refused()):
        resp = client.post("/api/v1/cameras/test", json=body, headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert data["error_code"] == "HOST_UNREACHABLE"
    assert "secret123" not in resp.text


def test_draft_probe_requires_admin(client: TestClient, viewer_headers: dict[str, str]) -> None:
    body = {"name": "Draft", "rtsp_url": _URL}
    resp = client.post("/api/v1/cameras/test", json=body, headers=viewer_headers)
    assert resp.status_code == 403
