"""Durable event writes: fired alerts become rows, never memory (spec A4.8).

Owns the events/event_detections insert paths and the delivery-status updates.
Deliberately does not own: files (ClipWriter), transport (notifier), or
broadcasts (hub) — each is a separate collaborator the handler composes.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.db.models import Camera, Event
from app.db.models.event import AuditLog, EventDetection
from app.services.alerts.stage import Alert


def _naive_utc(when: datetime) -> datetime:
    """DB columns are naive UTC; aware inputs are converted, naive kept."""
    return when.astimezone(UTC).replace(tzinfo=None) if when.tzinfo else when


def create_event(db: Session, alert: Alert) -> Event:
    """Insert the event and its first detection row; commits once.

    Raises:
        ValueError: The alert's camera does not exist — a programming error
            in the runtime wiring, not a recoverable condition.
    """
    camera = db.get(Camera, alert.camera_id)
    if camera is None:
        raise ValueError(f"alert references unknown camera {alert.camera_id}")
    fired = _naive_utc(alert.fired_at)
    event = Event(
        site_id=camera.site_id,
        camera_id=alert.camera_id,
        rule_id=alert.rule_id,
        triggered_by="rule",
        started_at=fired,
        severity=alert.severity,
        summary=alert.summary,
        delivery_status="pending" if alert.notify else "skipped",
    )
    db.add(event)
    db.flush()
    db.add(
        EventDetection(
            event_id=event.id,
            camera_id=alert.camera_id,
            class_name=alert.class_name,
            confidence=alert.confidence,
            bbox=list(alert.bbox),
            track_id=alert.track_id,
            zone_name=alert.zone,
            detected_at=fired,
        )
    )
    db.commit()
    db.refresh(event)
    return event


def create_system_event(
    db: Session,
    *,
    site_id: int,
    severity: str,
    summary: str,
    delivery_status: str = "pending",
) -> Event:
    """A site-level event with no camera: quota refusals, runtime faults (D5)."""
    event = Event(
        site_id=site_id,
        camera_id=None,
        rule_id=None,
        triggered_by="system",
        started_at=datetime.now(tz=UTC).replace(tzinfo=None),
        severity=severity,
        summary=summary,
        delivery_status=delivery_status,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def attach_media(
    db: Session,
    event_id: int,
    *,
    thumbnail_path: str | None,
    clip_path: str | None,
    clip_bytes: int | None,
    duration_ms: int | None,
) -> Event:
    """Attach id-derived media paths (and optional clip stats) to an event."""
    event = db.get(Event, event_id)
    if event is None:
        raise ValueError(f"event {event_id} not found")
    event.thumbnail_path = thumbnail_path
    event.clip_path = clip_path
    event.clip_bytes = clip_bytes
    event.duration_ms = duration_ms
    db.commit()
    db.refresh(event)
    return event


def write_audit(
    db: Session,
    *,
    site_id: int,
    user_id: int | None,
    action: str,
    details: dict[str, object] | None = None,
) -> AuditLog:
    """A privileged-action audit row (SECURITY 7.5); first writer for pause.

    Credential-free by contract: ``details`` carries state, never tokens.
    """
    row = AuditLog(
        site_id=site_id,
        user_id=user_id,
        action=action,
        details=details,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def mark_delivery(
    db: Session,
    event_id: int,
    *,
    status: str,
    attempts: int | None = None,
    error: str | None = None,
    delivered: datetime | None = None,
    attempted: datetime | None = None,
) -> None:
    """Update the durable delivery record for an event.

    ``error`` is assigned unconditionally: a retry that eventually succeeds
    must clear the previous failure message, not leave it as stale scar tissue.
    """
    event = db.get(Event, event_id)
    if event is None:
        return
    event.delivery_status = status
    event.last_delivery_error = error
    if attempts is not None:
        event.delivery_attempts = attempts
    if delivered is not None:
        event.delivered_at = _naive_utc(delivered)
    if attempted is not None:
        event.last_attempt_at = _naive_utc(attempted)
    db.commit()
