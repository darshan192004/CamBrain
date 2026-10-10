"""Event repository: filtered reads, acknowledge, and dashboard stats (API §Events).

Events are the durable record of what fired; acknowledge is a per-user flag
so two operators can independently clear their own view without deleting the
audit trail.
"""

from __future__ import annotations

import builtins
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

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
