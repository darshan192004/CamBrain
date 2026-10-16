"""Event repository: filtered reads, acknowledge, and dashboard stats (API §Events).

Events are the durable record of what fired; acknowledge is a per-user flag
so two operators can independently clear their own view without deleting the
audit trail.
"""

from __future__ import annotations

import builtins
from datetime import datetime
from pathlib import Path
from typing import cast

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.core.logging import mask_url
from app.db.models.event import Event, EventDetection
from app.db.models.site import _utcnow
from app.db.repositories.base import TenantScopedRepository


class EventRepository(TenantScopedRepository[Event]):
    def __init__(self, session: Session, *, site_id: int) -> None:
        super().__init__(session, Event, site_id=site_id)

    def get(self, event_id: int) -> Event | None:
        return self._get_scoped(event_id)

    def list(
        self,
        *,
        camera_id: int | None = None,
        severity: str | None = None,
        from_: datetime | None = None,
        to: datetime | None = None,
        acknowledged: bool | None = None,
        q: str | None = None,
        limit: int = 50,
        offset: int = 0,
        sort: str = "-started_at",
    ) -> tuple[builtins.list[Event], int]:
        """Return (events, total) matching the filters.

        `limit` is capped at 200 (API §Events). `sort` is a column name
        optionally prefixed with `-` for descending.
        """
        query = self._scoped()
        if camera_id is not None:
            query = query.where(Event.camera_id == camera_id)
        if severity is not None:
            query = query.where(Event.severity == severity)
        if from_ is not None:
            query = query.where(Event.started_at >= from_)
        if to is not None:
            query = query.where(Event.started_at <= to)
        if acknowledged is not None:
            if acknowledged:
                query = query.where(Event.acknowledged_at.is_not(None))
            else:
                query = query.where(Event.acknowledged_at.is_(None))
        if q is not None:
            query = query.where(Event.summary.ilike(f"%{q}%"))

        total = self.session.execute(
            select(func.count()).select_from(query.subquery())
        ).scalar_one()

        descending = sort.startswith("-")
        column_name = sort.lstrip("-")
        column = getattr(Event, column_name, Event.started_at)
        order = column.desc() if descending else column.asc()

        events = list(
            self.session.execute(query.order_by(order).limit(limit).offset(offset)).scalars()
        )
        return events, int(total)

    def create_from_alert(
        self,
        *,
        camera_id: int,
        severity: str,
        summary: str,
        started_at: datetime,
        rule_id: int | None = None,
        detections: builtins.list[dict[str, object]] | None = None,
    ) -> Event:
        """Persist one fired alert with its detections. Delivery stays `pending`.

        The row is the durable record: Telegram may fail later, the event
        never vanishes (spec §5.6). Callers set clip paths afterwards —
        they need the id, which only exists after the flush.
        """
        event = Event(
            site_id=self.site_id,
            camera_id=camera_id,
            rule_id=rule_id,
            triggered_by="rule",
            started_at=started_at.replace(tzinfo=None),
            severity=severity,
            summary=summary,
        )
        self.session.add(event)
        self.session.flush()
        for det in detections or []:
            self.session.add(
                EventDetection(
                    event_id=event.id,
                    camera_id=camera_id,
                    class_name=str(det["class_name"]),
                    confidence=cast(float, det["confidence"]),
                    bbox=cast(builtins.list[float], det["bbox"]),
                    track_id=cast(int | None, det.get("track_id")),
                    zone_name=cast(str | None, det.get("zone_name")),
                    detected_at=started_at.replace(tzinfo=None),
                )
            )
        self.session.commit()
        self.session.refresh(event)
        return event

    def mark_sent(self, event_id: int) -> None:
        """Record a successful delivery. Missing id is a 404, never silent."""
        event = self.get(event_id)
        if event is None:
            raise NotFoundError("event not found")
        event.delivery_status = "sent"
        event.delivery_attempts += 1
        event.delivered_at = _utcnow().replace(tzinfo=None)
        self.session.commit()

    def mark_failed(self, event_id: int, error: str) -> None:
        """Record a failed delivery; the event row survives for retry."""
        event = self.get(event_id)
        if event is None:
            raise NotFoundError("event not found")
        event.delivery_status = "failed"
        event.delivery_attempts += 1
        event.last_delivery_error = mask_url(error)[:500]
        self.session.commit()

    def prune_older_than(self, days: int, media_root: Path, *, batch: int = 500) -> int:
        """Delete events past retention with their media, batched (DATABASE §8).

        One big DELETE would hold the write lock long enough to stall
        pipelines; 500 rows per transaction keeps writers unblocked. Files
        unlink before the row commits — a crash leaves an orphan the quota
        sweep in §9 reclaims.
        """
        from datetime import timedelta

        cutoff = _utcnow().replace(tzinfo=None) - timedelta(days=days)
        removed = 0
        while True:
            rows = list(
                self.session.execute(
                    self._scoped().where(Event.started_at < cutoff).limit(batch)
                ).scalars()
            )
            if not rows:
                return removed
            root = media_root.resolve()
            for event in rows:
                for raw in (event.clip_path, event.thumbnail_path):
                    if not raw:
                        continue
                    path = Path(raw)
                    resolved = path.resolve() if path.is_absolute() else (root / path).resolve()
                    if resolved.is_relative_to(root):
                        resolved.unlink(missing_ok=True)
                self.session.delete(event)
            self.session.commit()
            removed += len(rows)

    def acknowledge(self, event_id: int, user_id: int) -> bool:
        """Set acknowledged_at/by. Returns False if not found or already acked."""
        event = self.get(event_id)
        if event is None or event.acknowledged_at is not None:
            return False
        event.acknowledged_at = _utcnow().replace(tzinfo=None)
        event.acknowledged_by = user_id
        self.session.commit()
        return True

    def acknowledge_bulk(self, event_ids: builtins.list[int], user_id: int) -> int:
        """Acknowledge many events. Returns the number newly acknowledged."""
        count = 0
        for event_id in event_ids:
            if self.acknowledge(event_id, user_id):
                count += 1
        return count

    def detections(self, event_id: int) -> builtins.list[EventDetection]:
        """Per-detection rows for an event in the caller's site."""
        query = (
            select(EventDetection)
            .join(Event, EventDetection.event_id == Event.id)
            .where(Event.site_id == self.site_id, EventDetection.event_id == event_id)
        )
        return list(self.session.execute(query).scalars())

    def stats(self) -> dict[str, object]:
        """Counts by day, camera, and severity for the dashboard header."""
        by_severity = dict(
            self.session.execute(
                select(Event.severity, func.count())
                .where(Event.site_id == self.site_id)
                .group_by(Event.severity)
            ).all()
        )
        by_camera = dict(
            self.session.execute(
                select(Event.camera_id, func.count())
                .where(Event.site_id == self.site_id)
                .group_by(Event.camera_id)
            ).all()
        )
        total = self.session.execute(
            select(func.count()).select_from(Event).where(Event.site_id == self.site_id)
        ).scalar_one()
        return {
            "total": int(total),
            "by_severity": {k: int(v) for k, v in by_severity.items()},
            "by_camera": {str(k): int(v) for k, v in by_camera.items()},
        }
