"""One fired alert, carried from stage to disk to dashboard (arch A7).

Owns the ordering: persist first (an event exists before any IO can fail),
still and broadcast next (the operator sees it instantly), clip after the
20s post-roll (a task the handler tracks and cancels on shutdown).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

from sqlalchemy.orm import Session

from app.db.models import Event, Site
from app.db.session import SessionLocal
from app.services.alerts.hub import AlertHub, event_message
from app.services.alerts.stage import Alert
from app.services.events.clips import ClipWriter, FrameRingBuffer, QuotaExceededError
from app.services.events.persist import attach_media, create_event


class AlertHandler:
    """The per-camera AlertSink: persist, snap, announce, finish the clip."""

    def __init__(
        self,
        *,
        camera_id: int,
        site_id: int,
        camera_name: str,
        ring: FrameRingBuffer,
        writer: ClipWriter,
        hub: AlertHub,
        session_factory: Callable[[], Session] = SessionLocal,
        post_roll_s: float = 20.0,
        pre_roll_s: float = 10.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        now: Callable[[], float] = time.monotonic,
        quota_pct: Callable[[], float] | None = None,
        on_quota_exceeded: Callable[[str], None] | None = None,
    ) -> None:
        self._camera_id = camera_id
        self._site_id = site_id
        self._camera_name = camera_name
        self._ring = ring
        self._writer = writer
        self._hub = hub
        self._session_factory = session_factory
        self._post_roll_s = post_roll_s
        self._pre_roll_s = pre_roll_s
        self._sleep = sleep
        self._now = now
        self._quota_pct = quota_pct or self._site_quota
        self._on_quota_exceeded = on_quota_exceeded
        self._tasks: set[asyncio.Task[None]] = set()

    def set_quota_hook(self, hook: Callable[[str], None] | None) -> None:
        """Attach the quota-refusal hook after construction (runtime wiring)."""
        self._on_quota_exceeded = hook

    def _site_quota(self) -> float:
        """The site's disk quota percentage (default 80 when unreadable)."""
        db = self._session_factory()
        try:
            site = db.get(Site, self._site_id)
            return float(site.disk_quota_pct) if site else 80.0
        finally:
            db.close()

    async def __call__(self, alert: Alert) -> None:
        """Persist immediately, then schedule the post-roll clip (AlertSink)."""
        fire_at = self._now()
        db = self._session_factory()
        try:
            event = create_event(db, alert)
            event_id, site_id = event.id, event.site_id
        finally:
            db.close()

        # The operator sees the event even when the ring held nothing (a
        # camera that fired on its first sampled frame).
        still = self._ring.latest_jpeg()
        db = self._session_factory()
        try:
            if still is not None:
                thumb = self._writer.write_still(event_id, still)
                attach_media(
                    db,
                    event_id,
                    thumbnail_path=thumb,
                    clip_path=None,
                    clip_bytes=None,
                    duration_ms=None,
                )
            stored = db.get(Event, event_id)
            if stored is not None:
                self._hub.broadcast(site_id, event_message(stored, self._camera_name))
        finally:
            db.close()

        task = asyncio.create_task(self._finish(event_id, fire_at))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _finish(self, event_id: int, fire_at: float) -> None:
        """After the post-roll: assemble the slice and attach the clip."""
        await self._sleep(self._post_roll_s)
        frames = self._ring.slice(fire_at - self._pre_roll_s, fire_at + self._post_roll_s)
        db = self._session_factory()
        try:
            try:
                path, size, duration_ms = self._writer.write_clip(
                    event_id, frames, quota_pct=self._quota_pct()
                )
            except QuotaExceededError as exc:
                if self._on_quota_exceeded is not None:
                    self._on_quota_exceeded(str(exc))
                return
            except ValueError:
                return  # fewer than two buffered frames — still and event stand
            current = db.get(Event, event_id)
            event = attach_media(
                db,
                event_id,
                thumbnail_path=current.thumbnail_path if current else None,
                clip_path=path,
                clip_bytes=size,
                duration_ms=duration_ms,
            )
            self._hub.broadcast(event.site_id, event_message(event, self._camera_name))
        finally:
            db.close()

    async def close(self) -> None:
        """Cancel in-flight post-roll tasks on shutdown."""
        for task in list(self._tasks):
            task.cancel()
