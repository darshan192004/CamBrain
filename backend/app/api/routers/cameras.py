"""Camera routes: CRUD, connectivity test, snapshot, stream (API §Cameras).

`site_id` always comes from the verified token — a body-supplied `site_id`
is ignored (IDOR defence, SECURITY §4.3). Credentials are written to the
dedicated columns and never returned; the response carries `has_password`
and a masked placeholder instead.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response, status
from fastapi.responses import JSONResponse

from app.api.deps import ClaimsDep, DbSessionDep, require_role_dep
from app.api.schemas import CameraCreate, CameraOut, CameraPatch, CameraTestResult
from app.core.crypto import encrypt
from app.core.errors import NotFoundError
from app.db.models.camera import Camera
from app.db.repositories.cameras import CameraRepository

router = APIRouter(prefix="/cameras", tags=["cameras"])

_MASK = "••••••••"
# Authz runs as a dependency, which FastAPI solves before validating the
# request body — so a viewer's malformed write is a 403, not a 422.
AdminDep = Annotated[dict[str, Any], Depends(require_role_dep("admin"))]


def _repo(db: Any, claims: dict[str, Any]) -> CameraRepository:
    """Build a tenant-scoped repository from the verified token's site_id."""
    return CameraRepository(db, site_id=int(claims["site_id"]))


def _to_out(camera: Camera) -> CameraOut:
    """Map a Camera row to its public response shape."""
    return CameraOut(
        id=camera.id,
        name=camera.name,
        rtsp_url=camera.rtsp_url,
        has_password=camera.rtsp_password_enc is not None,
        password=_MASK if camera.rtsp_password_enc is not None else None,
        enabled=camera.enabled,
        sample_fps=camera.sample_fps,
        motion_threshold=camera.motion_threshold,
        frame_width=camera.frame_width,
        frame_height=camera.frame_height,
        status=camera.status,
        last_error=camera.last_error,
        created_at=camera.created_at,
    )


@router.get("", response_model=list[CameraOut])
def list_cameras(claims: ClaimsDep, db: DbSessionDep) -> list[CameraOut]:
    """List every camera in the caller's site."""
    return [_to_out(c) for c in _repo(db, claims).list()]


@router.post("", response_model=CameraOut, status_code=status.HTTP_201_CREATED)
def create_camera(body: CameraCreate, claims: AdminDep, db: DbSessionDep) -> CameraOut:
    """Create a camera. Admin only; `site_id` is taken from the token."""
    fields: dict[str, Any] = {
        "name": body.name,
        "rtsp_url": body.rtsp_url,
        "enabled": body.enabled,
        "sample_fps": body.sample_fps,
        "motion_threshold": body.motion_threshold,
    }
    if body.username is not None:
        fields["rtsp_username"] = body.username
    if body.password is not None:
        # Encrypt at rest; the plaintext is never stored or returned.
        fields["rtsp_password_enc"] = encrypt(body.password).encode()
    camera = _repo(db, claims).create(**fields)
    return _to_out(camera)


@router.get("/{camera_id}", response_model=CameraOut)
def get_camera(camera_id: int, claims: ClaimsDep, db: DbSessionDep) -> CameraOut:
    """Fetch one camera. A cross-tenant id is a 404, never a 403."""
    camera = _repo(db, claims).get(camera_id)
    if camera is None:
        raise NotFoundError("camera not found")
    return _to_out(camera)


@router.patch("/{camera_id}", response_model=CameraOut)
def patch_camera(
    camera_id: int, body: CameraPatch, claims: AdminDep, db: DbSessionDep
) -> CameraOut:
    """Update a camera. Omitted `password` is unchanged; `null` clears it."""
    repo = _repo(db, claims)
    camera = repo.get(camera_id)
    if camera is None:
        raise NotFoundError("camera not found")
    updates = body.model_dump(exclude_unset=True)
    password = updates.pop("password", "__unset__")
    if password == "__unset__":
        pass  # omitted — leave unchanged
    elif password is None:
        camera.rtsp_password_enc = None
    else:
        camera.rtsp_password_enc = encrypt(password).encode()
    username = updates.pop("username", "__unset__")
    if username != "__unset__":
        camera.rtsp_username = username
    for key, value in updates.items():
        setattr(camera, key, value)
    db.commit()
    db.refresh(camera)
    return _to_out(camera)


@router.delete("/{camera_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_camera(camera_id: int, claims: AdminDep, db: DbSessionDep) -> Response:
    """Delete a camera. Admin only."""
    if not _repo(db, claims).delete(camera_id):
        raise NotFoundError("camera not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{camera_id}/test", response_model=CameraTestResult)
async def test_camera(camera_id: int, claims: AdminDep, db: DbSessionDep) -> CameraTestResult:
    """Probe the RTSP endpoint. Always 200 — a failed probe is data, not an error."""
    camera = _repo(db, claims).get(camera_id)
    if camera is None:
        raise NotFoundError("camera not found")
    # Phase 4 wires the real probe; until then a diagnostic cannot claim a
    # camera it has never reached is live, so surface an explicit not-wired code.
    return CameraTestResult(
        ok=False,
        message="RTSP probe is not wired yet (Phase 4).",
        error_code="CANCELLED",
    )


@router.post("/{camera_id}/snapshot", response_model=CameraTestResult)
async def snapshot_camera(camera_id: int, claims: ClaimsDep, db: DbSessionDep) -> CameraTestResult:
    """Capture a single JPEG. Phase 4 wires the real frame source."""
    camera = _repo(db, claims).get(camera_id)
    if camera is None:
        raise NotFoundError("camera not found")
    return CameraTestResult(
        ok=False,
        message="Snapshot is not wired yet (Phase 4).",
        error_code="CANCELLED",
    )


@router.get("/{camera_id}/stream")
async def stream_camera(camera_id: int, claims: ClaimsDep, db: DbSessionDep) -> Response:
    """MJPEG live stream. Phase 5 wires real frames; until then 501.

    Returning a 501 (not a placeholder JPEG) keeps the stub from being
    mistaken for a working stream in the dashboard.
    """
    camera = _repo(db, claims).get(camera_id)
    if camera is None:
        raise NotFoundError("camera not found")
    return JSONResponse(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        content={
            "error": {
                "code": "NOT_IMPLEMENTED",
                "message": "stream endpoint is not wired yet (Phase 5)",
                "field": None,
                "correlation_id": "not-wired",
            }
        },
    )
