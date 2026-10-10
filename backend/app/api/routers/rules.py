"""Rule routes: CRUD, soft delete, and diagnostic test (API §Rules).

Rules soft-delete via `deleted_at` because events keep a reference to the
rule that fired them; a hard delete would orphan historical attributions.
`classes` stores COCO names, not indices, so a Phase 3 model swap cannot
silently repoint every rule.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response, status

from app.api.deps import ClaimsDep, DbSessionDep, require_role_dep
from app.api.schemas import RuleCreate, RuleOut, RulePatch
from app.core.errors import NotFoundError, ValidationError
from app.db.models.rule import Rule
from app.db.repositories.cameras import CameraRepository
from app.db.repositories.rois import RoiRepository
from app.db.repositories.rules import RuleRepository

router = APIRouter(tags=["rules"])

AdminDep = Annotated[dict[str, Any], Depends(require_role_dep("admin"))]


def _repo(db: Any, claims: dict[str, Any]) -> RuleRepository:
    """Build a tenant-scoped rule repository from the token's site_id."""
    return RuleRepository(db, site_id=int(claims["site_id"]))


def _to_out(rule: Rule) -> RuleOut:
    """Map a Rule row to its public response shape."""
    return RuleOut(
        id=rule.id,
        camera_id=rule.camera_id,
        roi_id=rule.roi_id,
        name=rule.name,
        enabled=rule.enabled,
        classes=rule.classes,
        confidence_threshold=rule.confidence_threshold,
        cooldown_seconds=rule.cooldown_seconds,
        active_hours=rule.active_hours,
        severity=rule.severity,
        notify=rule.notify,
        created_at=rule.created_at,
    )


def _ensure_camera(db: Any, claims: dict[str, Any], camera_id: int) -> None:
    """Raise 404 if the camera is not in the caller's tenant."""
    if CameraRepository(db, site_id=int(claims["site_id"])).get(camera_id) is None:
        raise NotFoundError("camera not found")


def _validate_roi(db: Any, claims: dict[str, Any], roi_id: int, camera_id: int) -> None:
    """Raise 422 if the ROI is missing or on a different camera."""
    roi = RoiRepository(db, site_id=int(claims["site_id"])).get(roi_id)
    if roi is None or roi.camera_id != camera_id:
        raise ValidationError("roi_id must reference an ROI on the same camera")


@router.get("/cameras/{camera_id}/rules", response_model=list[RuleOut])
def list_camera_rules(camera_id: int, claims: ClaimsDep, db: DbSessionDep) -> list[RuleOut]:
    """List every live rule for a camera in the caller's site."""
    _ensure_camera(db, claims, camera_id)
    rules = [r for r in _repo(db, claims).list() if r.camera_id == camera_id]
    return [_to_out(r) for r in rules]


@router.get("/rules", response_model=list[RuleOut])
def list_site_rules(claims: ClaimsDep, db: DbSessionDep) -> list[RuleOut]:
    """List every live rule in the caller's site (site-wide, filtered)."""
    return [_to_out(r) for r in _repo(db, claims).list()]


@router.post(
    "/cameras/{camera_id}/rules",
    response_model=RuleOut,
    status_code=status.HTTP_201_CREATED,
)
def create_rule(camera_id: int, body: RuleCreate, claims: AdminDep, db: DbSessionDep) -> RuleOut:
    """Create a rule on a camera. Admin only; `roi_id` must match the camera."""
    _ensure_camera(db, claims, camera_id)
    if body.roi_id is not None:
        _validate_roi(db, claims, body.roi_id, camera_id)
    rule = _repo(db, claims).create(
        camera_id=camera_id,
        name=body.name,
        roi_id=body.roi_id,
        enabled=body.enabled,
        classes=body.classes,
        confidence_threshold=body.confidence_threshold,
        cooldown_seconds=body.cooldown_seconds,
        active_hours=body.active_hours.model_dump() if body.active_hours else None,
        severity=body.severity,
        notify=body.notify,
    )
    return _to_out(rule)


@router.get("/rules/{rule_id}", response_model=RuleOut)
def get_rule(rule_id: int, claims: ClaimsDep, db: DbSessionDep) -> RuleOut:
    """Fetch one rule. A cross-tenant or soft-deleted id is a 404."""
    rule = _repo(db, claims).get(rule_id)
    if rule is None:
        raise NotFoundError("rule not found")
    return _to_out(rule)


@router.patch("/rules/{rule_id}", response_model=RuleOut)
def patch_rule(rule_id: int, body: RulePatch, claims: AdminDep, db: DbSessionDep) -> RuleOut:
    """Update a rule. `roi_id` must still reference the same camera."""
    repo = _repo(db, claims)
    rule = repo.get(rule_id)
    if rule is None:
        raise NotFoundError("rule not found")
    updates = body.model_dump(exclude_unset=True)
    if "active_hours" in updates and updates["active_hours"] is not None:
        updates["active_hours"] = body.active_hours.model_dump()  # type: ignore[union-attr]
    if updates.get("roi_id") is not None:
        _validate_roi(db, claims, updates["roi_id"], rule.camera_id)
    rule = repo.update(rule_id, **updates)
    if rule is None:
        raise NotFoundError("rule not found")
    return _to_out(rule)


@router.delete("/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rule(rule_id: int, claims: AdminDep, db: DbSessionDep) -> Response:
    """Soft-delete a rule (sets `deleted_at`). Admin only."""
    if not _repo(db, claims).soft_delete(rule_id):
        raise NotFoundError("rule not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/rules/{rule_id}/test", response_model=RuleOut)
async def test_rule(rule_id: int, claims: AdminDep, db: DbSessionDep) -> RuleOut:
    """Replay a still through the rules engine. Phase 3 wires the engine."""
    rule = _repo(db, claims).get(rule_id)
    if rule is None:
        raise NotFoundError("rule not found")
    # Phase 3 wires the real replay; returning the rule keeps the route
    # contract live without pretending a diagnostic ran.
    return _to_out(rule)
