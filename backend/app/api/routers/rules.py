"""Rule routes: CRUD, soft delete, and diagnostic test (API §Rules).

Rules soft-delete via `deleted_at` because events keep a reference to the
rule that fired them; a hard delete would orphan historical attributions.
`classes` stores COCO names, not indices, so a Phase 3 model swap cannot
silently repoint every rule.
"""

from __future__ import annotations

import base64
import io
from collections.abc import Callable
from datetime import UTC, datetime
from functools import lru_cache
from typing import Annotated, Any, cast

import av
from fastapi import APIRouter, Depends, Response, status

from app.api.deps import ClaimsDep, DbSessionDep, require_role_dep
from app.api.schemas import (
    RuleCheckOut,
    RuleCreate,
    RuleOut,
    RulePatch,
    RuleTestOut,
    RuleTestRequest,
)
from app.core.config import settings
from app.core.errors import NotFoundError, ValidationError
from app.db.models.rule import Rule
from app.db.repositories.cameras import CameraRepository
from app.db.repositories.events import EventRepository
from app.db.repositories.rois import RoiRepository
from app.db.repositories.rules import RuleRepository
from app.services.alerts.replay import (
    detections_to_tracked,
    evaluate_detections,
    replay,
    rule_config,
)
from app.services.alerts.rules import RuleOutcome, RulesEngine
from app.services.stream.source import Frame

router = APIRouter(tags=["rules"])

AdminDep = Annotated[dict[str, Any], Depends(require_role_dep("admin"))]


@lru_cache(maxsize=1)
def _open_rule_detector() -> Any:
    """Open the shared still-replay detector on first use."""
    from app.services.inference.detector import open_detector

    return open_detector(settings.model_path, input_size=settings.model_input_size)


def get_rule_detector() -> Callable[[], Any]:
    """Provider seam for still replay (D8); tests override this dependency."""
    return _open_rule_detector


DetectorProvider = Annotated[Callable[[], Any], Depends(get_rule_detector)]


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


def _test_out(rule: Rule, outcome: RuleOutcome) -> RuleTestOut:
    """Shape any evaluation (event or still) into the documented response."""
    return RuleTestOut(
        rule_id=rule.id,
        fired=outcome.fired,
        checks=[
            RuleCheckOut(condition=c.condition, passed=c.passed, detail=c.detail)
            for c in outcome.checks
        ],
    )


def _decode_still(image_b64: str) -> Frame:
    """Base64 JPEG -> RGB frame; bad input is a 422, never a 500."""
    try:
        data = base64.b64decode(image_b64, validate=True)
    except ValueError as exc:  # binascii.Error is a ValueError
        raise ValidationError(f"image_b64 is not valid base64: {exc}") from exc
    try:
        container = cast("av.container.InputContainer", av.open(io.BytesIO(data)))
        with container:
            raw = next(container.decode(video=0))
            rgb = raw.to_ndarray(format="rgb24")
    except (av.error.FFmpegError, StopIteration, OSError, ValueError) as exc:
        raise ValidationError(f"image_b64 is not a decodable image: {exc}") from exc
    return Frame(data=rgb, timestamp=0.0, width=raw.width, height=raw.height)


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


@router.post("/rules/{rule_id}/test", response_model=RuleTestOut)
async def test_rule(
    rule_id: int,
    claims: AdminDep,
    db: DbSessionDep,
    detector: DetectorProvider,
    body: RuleTestRequest | None = None,
) -> RuleTestOut:
    """Replay detections through the engine: a base64 still, or an event."""
    site_id = int(claims["site_id"])
    rule = _repo(db, claims).get(rule_id)
    if rule is None:
        raise NotFoundError("rule not found")
    camera = CameraRepository(db, site_id=site_id).get(rule.camera_id)
    if camera is None:
        raise NotFoundError("camera not found")
    roi = RoiRepository(db, site_id=site_id).get(rule.roi_id) if rule.roi_id else None
    engine = RulesEngine()
    config = rule_config(rule, roi)

    if body is not None and body.image_b64:
        # The still carries its own frame dims — no stored size required (D8).
        frame = _decode_still(body.image_b64)
        tracked = detections_to_tracked(await detector().infer(frame), frame.width, frame.height)
        return _test_out(rule, evaluate_detections(engine, config, tracked, datetime.now(UTC)))

    events = EventRepository(db, site_id=site_id)
    event_id = body.event_id if body else None
    if event_id is not None:
        event = events.get(event_id)
        if event is None or event.camera_id != rule.camera_id:
            raise NotFoundError("event not found")
    else:
        found, _total = events.list(camera_id=rule.camera_id, limit=1)
        if not found:
            raise NotFoundError("no event to replay yet")
        event = found[0]
    return _test_out(rule, replay(engine, config, camera, events.detections(event.id), event))
