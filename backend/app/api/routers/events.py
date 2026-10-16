"""Event routes: filtered reads, acknowledge, stats (API §Events).

`thumbnail_url` and `clip_url` are opaque URLs resolved by event id — the
client never constructs or sends a filesystem path (SECURITY §6.2).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse

from app.api.deps import ClaimsDep, DbSessionDep
from app.api.schemas import (
    AcknowledgeBulkRequest,
    CameraRef,
    EventDetectionOut,
    EventListOut,
    EventOut,
    EventStatsOut,
    RuleRef,
)
from app.core.config import settings
from app.core.errors import NotFoundError
from app.db.models.event import Event
from app.db.repositories.cameras import CameraRepository
from app.db.repositories.events import EventRepository
from app.db.repositories.rules import RuleRepository

router = APIRouter(tags=["events"])


def _repo(db: Any, claims: dict[str, Any]) -> EventRepository:
    """Build a tenant-scoped event repository from the token's site_id."""
    return EventRepository(db, site_id=int(claims["site_id"]))


def _to_out(
    event: Event, detections: list[EventDetectionOut], camera_name: str, rule_name: str | None
) -> EventOut:
    """Map an Event row and its detections to the public response shape."""
    return EventOut(
        id=event.id,
        camera=CameraRef(id=event.camera_id, name=camera_name),
        rule=RuleRef(id=event.rule_id, name=rule_name) if event.rule_id and rule_name else None,
        severity=event.severity,
        summary=event.summary,
        started_at=event.started_at,
        ended_at=event.ended_at,
        duration_ms=event.duration_ms,
        acknowledged=event.acknowledged_at is not None,
        has_clip=event.clip_path is not None,
        thumbnail_url=f"/api/v1/events/{event.id}/thumbnail",
        clip_url=f"/api/v1/events/{event.id}/clip",
        detections=detections,
    )


def _camera_names(db: Any, claims: dict[str, Any]) -> dict[int, str]:
    """Map camera id -> name for cameras in the caller's site."""
    repo = CameraRepository(db, site_id=int(claims["site_id"]))
    return {c.id: c.name for c in repo.list()}


def _rule_names(db: Any, claims: dict[str, Any]) -> dict[int, str]:
    """Map rule id -> name for rules in the caller's site."""
    repo = RuleRepository(db, site_id=int(claims["site_id"]))
    return {r.id: r.name for r in repo.list()}


def _detections(repo: EventRepository, event_id: int) -> list[EventDetectionOut]:
    """Per-detection rows for an event."""
    return [
        EventDetectionOut(
            class_name=d.class_name, confidence=d.confidence, bbox=d.bbox, zone_name=d.zone_name
        )
        for d in repo.detections(event_id)
    ]


@router.get("/events", response_model=EventListOut)
def list_events(
    claims: ClaimsDep,
    db: DbSessionDep,
    camera_id: int | None = None,
    severity: str | None = None,
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: datetime | None = None,
    acknowledged: bool | None = None,
    q: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    sort: str = "-started_at",
) -> EventListOut:
    """Filtered, offset-paginated event list."""
    repo = _repo(db, claims)
    events, total = repo.list(
        camera_id=camera_id,
        severity=severity,
        from_=from_,
        to=to,
        acknowledged=acknowledged,
        q=q,
        limit=limit,
        offset=offset,
        sort=sort,
    )
    cam_names = _camera_names(db, claims)
    rule_names = _rule_names(db, claims)
    items = [
        _to_out(
            e,
            _detections(repo, e.id),
            cam_names.get(e.camera_id, f"camera-{e.camera_id}"),
            rule_names.get(e.rule_id) if e.rule_id else None,
        )
        for e in events
    ]
    return EventListOut(items=items, total=total, limit=limit, offset=offset)


@router.get("/events/stats", response_model=EventStatsOut)
def event_stats(claims: ClaimsDep, db: DbSessionDep) -> EventStatsOut:
    """Dashboard counts by severity and camera."""
    stats = _repo(db, claims).stats()
    return EventStatsOut(**stats)


@router.get("/events/{event_id}", response_model=EventOut)
def get_event(event_id: int, claims: ClaimsDep, db: DbSessionDep) -> EventOut:
    """Fetch one event. Cross-tenant id is a 404."""
    repo = _repo(db, claims)
    event = repo.get(event_id)
    if event is None:
        raise NotFoundError("event not found")
    cam_names = _camera_names(db, claims)
    rule_names = _rule_names(db, claims)
    return _to_out(
        event,
        _detections(repo, event.id),
        cam_names.get(event.camera_id, f"camera-{event.camera_id}"),
        rule_names.get(event.rule_id) if event.rule_id else None,
    )


@router.post("/events/{event_id}/acknowledge", response_model=EventOut)
def acknowledge_event(event_id: int, claims: ClaimsDep, db: DbSessionDep) -> EventOut:
    """Acknowledge one event. Idempotent: already-acked returns the event."""
    repo = _repo(db, claims)
    event = repo.get(event_id)
    if event is None:
        raise NotFoundError("event not found")
    user_id = int(claims["sub"])
    repo.acknowledge(event_id, user_id)
    cam_names = _camera_names(db, claims)
    rule_names = _rule_names(db, claims)
    return _to_out(
        event,
        _detections(repo, event.id),
        cam_names.get(event.camera_id, f"camera-{event.camera_id}"),
        rule_names.get(event.rule_id) if event.rule_id else None,
    )


@router.post("/events/acknowledge-bulk")
def acknowledge_bulk(
    body: AcknowledgeBulkRequest, claims: ClaimsDep, db: DbSessionDep
) -> dict[str, int]:
    """Acknowledge many events; returns the count newly acknowledged."""
    count = _repo(db, claims).acknowledge_bulk(body.event_ids, int(claims["sub"]))
    return {"acknowledged": count}


@router.get("/events/{event_id}/thumbnail")
def get_thumbnail(event_id: int, claims: ClaimsDep, db: DbSessionDep) -> FileResponse:
    """Serve the event's still. 404 when never written or pruned.

    Phase 5 writes stills; the route exists now so `thumbnail_url` (D8)
    never 404s for a reason other than "no image". `thumbnail_path` is
    resolved inside the media root only — an escaping path is 404, never
    served (SECURITY §6.2).
    """
    event = _repo(db, claims).get(event_id)
    if event is None or event.thumbnail_path is None:
        raise NotFoundError("thumbnail not found")
    root = settings.media_root.resolve()
    path = Path(event.thumbnail_path)
    resolved = path.resolve() if path.is_absolute() else (root / path).resolve()
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise NotFoundError("thumbnail not found")
    return FileResponse(resolved, media_type="image/jpeg")


@router.get("/events/{event_id}/clip")
def get_clip(event_id: int, claims: ClaimsDep, db: DbSessionDep) -> FileResponse:
    """Serve the event's clip. 404 when never written, quota-refused, or pruned.

    Same traversal defence as the thumbnail: the path resolves inside the
    media root only, looked up by id from the database (SECURITY §6.2).
    """
    event = _repo(db, claims).get(event_id)
    if event is None or event.clip_path is None:
        raise NotFoundError("clip not found")
    root = settings.media_root.resolve()
    path = Path(event.clip_path)
    resolved = path.resolve() if path.is_absolute() else (root / path).resolve()
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise NotFoundError("clip not found")
    return FileResponse(resolved, media_type="video/mp4")
