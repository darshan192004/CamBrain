"""ROI routes: CRUD under a camera (API §ROIs).

Coordinates are normalised 0..1 so a ROI survives a resolution change.
`coverage_pct` is computed from the polygon so the UI can flag a ROI that
covers nearly the whole frame — the common mistake that produces the alert
noise this product exists to prevent.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response, status

from app.api.deps import ClaimsDep, DbSessionDep, require_role_dep
from app.api.schemas import RoiCreate, RoiOut, RoiPatch
from app.core.errors import NotFoundError
from app.db.models.roi import Roi
from app.db.repositories.cameras import CameraRepository
from app.db.repositories.rois import RoiRepository

router = APIRouter(tags=["rois"])

AdminDep = Annotated[dict[str, Any], Depends(require_role_dep("admin"))]


def _repo(db: Any, claims: dict[str, Any]) -> RoiRepository:
    """Build a tenant-scoped ROI repository from the token's site_id."""
    return RoiRepository(db, site_id=int(claims["site_id"]))


def _coverage_pct(points: list[list[float]]) -> float:
    """Polygon area as a percentage of the unit frame (shoelace formula)."""
    area = 0.0
    n = len(points)
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        area += x1 * y2 - x2 * y1
    return round(abs(area) / 2.0 * 100.0, 1)


def _to_out(roi: Roi) -> RoiOut:
    """Map a Roi row to its public response shape."""
    points = roi.points
    return RoiOut(
        id=roi.id,
        camera_id=roi.camera_id,
        name=roi.name,
        points=points,
        coverage_pct=_coverage_pct(points),
        vertex_count=len(points),
        class_filter=roi.class_filter,
        active=roi.active,
        created_at=roi.created_at,
    )


def _ensure_camera(db: Any, claims: dict[str, Any], camera_id: int) -> None:
    """Raise 404 if the camera is not in the caller's tenant."""
    if CameraRepository(db, site_id=int(claims["site_id"])).get(camera_id) is None:
        raise NotFoundError("camera not found")


@router.get("/cameras/{camera_id}/rois", response_model=list[RoiOut])
def list_rois(camera_id: int, claims: ClaimsDep, db: DbSessionDep) -> list[RoiOut]:
    """List every ROI for a camera in the caller's site."""
    _ensure_camera(db, claims, camera_id)
    return [_to_out(r) for r in _repo(db, claims).list(camera_id=camera_id)]


@router.post(
    "/cameras/{camera_id}/rois",
    response_model=RoiOut,
    status_code=status.HTTP_201_CREATED,
)
def create_roi(camera_id: int, body: RoiCreate, claims: AdminDep, db: DbSessionDep) -> RoiOut:
    """Create an ROI on a camera. Admin only."""
    _ensure_camera(db, claims, camera_id)
    roi = _repo(db, claims).create(
        camera_id=camera_id,
        name=body.name,
        points=body.points,
        class_filter=body.class_filter,
        active=body.active,
    )
    return _to_out(roi)


@router.get("/rois/{roi_id}", response_model=RoiOut)
def get_roi(roi_id: int, claims: ClaimsDep, db: DbSessionDep) -> RoiOut:
    """Fetch one ROI. A cross-tenant id is a 404, never a 403."""
    roi = _repo(db, claims).get(roi_id)
    if roi is None:
        raise NotFoundError("roi not found")
    return _to_out(roi)


@router.patch("/rois/{roi_id}", response_model=RoiOut)
def patch_roi(roi_id: int, body: RoiPatch, claims: AdminDep, db: DbSessionDep) -> RoiOut:
    """Update an ROI. The full point list is required on every edit."""
    updates = body.model_dump(exclude_unset=True)
    roi = _repo(db, claims).update(roi_id, **updates)
    if roi is None:
        raise NotFoundError("roi not found")
    return _to_out(roi)


@router.delete("/rois/{roi_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_roi(roi_id: int, claims: AdminDep, db: DbSessionDep) -> Response:
    """Delete an ROI. Admin only."""
    if not _repo(db, claims).delete(roi_id):
        raise NotFoundError("roi not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
