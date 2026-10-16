"""Alert intake: persist, attach media, announce (Phase 5).

Owns: turning one fired `Alert` into a durable `Event` row with media.
Does not own: detection (Stage), transport (Notifier), or sockets (hub).

Order matters: the row commits first, so a quota refusal or a dead
network leaves a queryable event instead of a lost one (spec §5.6).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.api.ws.hub import broadcast
from app.core.errors import StorageError
from app.db.repositories.events import EventRepository
from app.services.alerts.stage import Alert
from app.services.events.clips import ClipWriter, RingBuffer
from app.services.stream.jpeg import encode_jpeg
from app.services.stream.source import Frame


def store_alert(
    session: Session,
    *,
    site_id: int,
    camera_id: int,
    alert: Alert,
    media_root: Path,
    pre_roll: list[Frame] | None = None,
    post_roll: list[Frame] | None = None,
    quota_pct: int = 80,
) -> tuple[Any, bytes]:
    """Persist `alert` with one detection row, media, and a hub announcement.

    Returns the event and the still bytes for delivery. Media failure
    (quota, no frames) leaves paths NULL — the row still survives.
    """
    repo = EventRepository(session, site_id=site_id)
    event = repo.create_from_alert(
        camera_id=camera_id,
        rule_id=alert.rule_id,
        severity=alert.severity,
        summary=alert.summary,
        started_at=alert.fired_at,
        detections=[
            {
                "class_name": alert.class_name,
                "confidence": alert.confidence,
                "bbox": [0, 0, 1, 1],
                "track_id": alert.track_id,
                "zone_name": alert.zone,
            }
        ],
    )
    still = b""
    frames = [*(pre_roll or []), *(post_roll or [])]
    if frames:
        try:
            paths = ClipWriter(media_root, quota_pct=quota_pct).write(
                event.id, pre_roll or [], post_roll or []
            )
            root = media_root.resolve()
            if paths.clip is not None:
                event.clip_path = str(paths.clip.resolve().relative_to(root))
            event.thumbnail_path = str(paths.still.resolve().relative_to(root))
            event.clip_bytes = paths.clip.stat().st_size if paths.clip is not None else None
            session.commit()
            still = paths.still.read_bytes()
        except StorageError:
            session.rollback()
            if frames:
                still = encode_jpeg(frames[0])
    broadcast(
        {
            "type": "event",
            "data": {"id": event.id, "severity": event.severity, "summary": event.summary},
        }
    )
    return event, still


def pre_roll_for(camera_buffers: dict[int, RingBuffer], camera_id: int) -> list[Frame]:
    """Snapshot one camera's ring buffer, tolerating a missing camera."""
    ring = camera_buffers.get(camera_id)
    return ring.snapshot() if ring is not None else []
