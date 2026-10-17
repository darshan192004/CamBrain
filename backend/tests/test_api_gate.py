"""Phase 2 gate tests: error envelope, CSRF, OpenAPI reachable, 500 path (Task 2.9)."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import Site, User


def test_openapi_reachable(client: TestClient) -> None:
    assert client.get("/api/v1/openapi.json").status_code == 200


def test_docs_reachable(client: TestClient) -> None:
    assert client.get("/api/v1/docs").status_code == 200


def test_unknown_route_returns_envelope(client: TestClient) -> None:
    """An unknown path is a 404 with the error envelope, not a stack trace."""
    resp = client.get("/api/v1/does-not-exist")
    assert resp.status_code == 404
    body = resp.json()
    assert body["error"]["code"] == "NOT_FOUND"
    assert "correlation_id" in body["error"]


def test_csrf_blocks_missing_header(
    db_session: Session,
    seeded: tuple[Site, User, User],  # noqa: ARG001
) -> None:
    """A mutating request without X-CamBrain-Client is 403 with the envelope."""
    from app.api.deps import get_db
    from app.main import create_app

    app = create_app()

    def _override_db() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    with TestClient(app, base_url="http://testserver") as bare:
        resp = bare.post(
            "/api/v1/auth/login",
            json={"username": "ramesh", "password": "correct-horse-battery"},
        )
        assert resp.status_code == 403
        body = resp.json()
        assert body["error"]["code"] == "FORBIDDEN"
        assert "correlation_id" in body["error"]
    app.dependency_overrides.clear()


def test_csrf_blocks_bad_content_type(
    db_session: Session,
    seeded: tuple[Site, User, User],  # noqa: ARG001
) -> None:
    """A mutating request with a non-JSON content type is 403."""
    from app.api.deps import get_db
    from app.main import create_app

    app = create_app()

    def _override_db() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    with TestClient(app, base_url="http://testserver") as bare:
        resp = bare.post(
            "/api/v1/auth/login",
            content=b"{}",
            headers={"Content-Type": "text/plain", "X-CamBrain-Client": "tests"},
        )
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "FORBIDDEN"
    app.dependency_overrides.clear()


def test_health_is_unauthenticated(client: TestClient) -> None:
    """The only route with no auth; the Tauri shell and installer poll it."""
    resp = client.get("/api/v1/system/health")
    assert resp.status_code == 200
    assert set(resp.json()) == {"status", "version", "uptime_s"}


def test_unauthenticated_rejected_everywhere_else(client: TestClient) -> None:
    """Every other route requires a token."""
    for path in ("/api/v1/cameras", "/api/v1/events", "/api/v1/users", "/api/v1/settings"):
        assert client.get(path).status_code == 401, path


def test_500_returns_envelope_without_stack_trace(
    db_session: Session,
    seeded: tuple[Site, User, User],  # noqa: ARG001
    admin_headers: dict[str, str],
) -> None:
    """An unexpected error is a 500 envelope with a correlation id, no traceback."""
    from app.api.deps import get_db
    from app.db.repositories.cameras import CameraRepository
    from app.main import create_app

    def _boom(self: CameraRepository, camera_id: int) -> object:  # noqa: ARG001
        raise RuntimeError("secret internal detail")

    app = create_app()

    def _override_db() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    original_get = CameraRepository.get
    CameraRepository.get = _boom  # type: ignore[method-assign]
    try:
        # raise_server_exceptions=False lets the Exception handler respond.
        with TestClient(app, base_url="http://testserver", raise_server_exceptions=False) as raw:
            resp = raw.get("/api/v1/cameras/1", headers=admin_headers)
        assert resp.status_code == 500
        body = resp.json()
        assert body["error"]["code"] == "INTERNAL"
        assert "correlation_id" in body["error"]
        assert "secret internal detail" not in resp.text
        assert "Traceback" not in resp.text
    finally:
        CameraRepository.get = original_get  # type: ignore[method-assign]
        app.dependency_overrides.clear()
