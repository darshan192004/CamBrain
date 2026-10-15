"""Retention: events age out in batches, files die with their rows (A6.5, A9).

Batches of 500 ids keep write locks short on a busy box; each file is
unlinked before its row commits, so a crash leaves an orphan the sweep
reclaims rather than a row pointing at nothing.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models.event import Event
from app.db.models.site import Site
from app.db.session import SessionLocal

DEFAULT_INTERVAL_S = 86_400.0
ORPHAN_MIN_AGE_S = 86_400.0


def _now(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(tz=UTC).replace(tzinfo=None)
    return now.astimezone(UTC).replace(tzinfo=None) if now.tzinfo else now


def _unlink(root: Path, relative: str | None) -> None:
    if not relative:
        return
    path = Path(relative)
    resolved = path.resolve() if path.is_absolute() else (root / path).resolve()
    with contextlib.suppress(OSError):
        if resolved.is_relative_to(root.resolve()) and resolved.is_file():
            resolved.unlink()


def prune_events(
    db: Session,
    *,
    site_id: int,
    now: datetime | None = None,
    batch: int = 500,
    media_root: Path | None = None,
) -> int:
    """Delete this site's events older than its retention; return rows removed."""
    site = db.get(Site, site_id)
    if site is None or site.retention_days <= 0:
        return 0
    root = (media_root or settings.media_root).resolve()
    cutoff = _now(now) - timedelta(days=site.retention_days)
    total = 0
    while True:
        ids = (
            db.execute(
                select(Event.id)
                .where(Event.site_id == site_id, Event.started_at < cutoff)
                .order_by(Event.id)
                .limit(batch)
            )
            .scalars()
            .all()
        )
        if not ids:
            break
        for event_id in ids:
            event = db.get(Event, event_id)
            if event is None:
                continue
            _unlink(root, event.clip_path)
            _unlink(root, event.thumbnail_path)
        db.execute(delete(Event).where(Event.id.in_(ids)))
        db.commit()
        total += len(ids)
        if len(ids) < batch:
            break
        time.sleep(0.05)
    return total


def sweep_orphans(
    db: Session,
    *,
    site_id: int,
    media_root: Path | None = None,
    min_age_s: float = ORPHAN_MIN_AGE_S,
    now: datetime | None = None,
) -> int:
    """Remove media files older than min_age with no matching event row."""
    root = (media_root or settings.media_root).resolve()
    stamp = _now(now).timestamp() - min_age_s
    referenced = {p for folder in ("clips", "stills") for p in _referenced(db, site_id, folder)}
    removed = 0
    for folder in ("clips", "stills"):
        directory = root / folder
        if not directory.is_dir():
            continue
        for path in directory.iterdir():
            if not path.is_file() or path.name in referenced:
                continue
            try:
                if path.stat().st_mtime > stamp:
                    continue
                path.unlink()
                removed += 1
            except OSError:
                continue
    return removed


def _referenced(db: Session, site_id: int, folder: str) -> set[str]:
    """Basename set of clip/still paths this site's events still point at."""
    rows = db.execute(
        select(Event.clip_path, Event.thumbnail_path).where(Event.site_id == site_id)
    ).all()
    names: set[str] = set()
    prefix = f"{folder}/"
    for clip, thumb in rows:
        for value in (clip, thumb):
            if value and value.startswith(prefix):
                names.add(value.removeprefix(prefix))
    return names


class RetentionRunner:
    """Daily prune + orphan sweep for one site (started by the runtime, T13)."""

    def __init__(
        self,
        *,
        site_id: int,
        session_factory: Callable[[], Session] = SessionLocal,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        interval_s: float = DEFAULT_INTERVAL_S,
        media_root: Path | None = None,
    ) -> None:
        self._site_id = site_id
        self._session_factory = session_factory
        self._sleep = sleep
        self._interval_s = interval_s
        self._media_root = media_root
        self._stopped = asyncio.Event()

    async def sweep_once(self) -> int:
        """One prune + one orphan sweep; returns rows deleted."""
        db = self._session_factory()
        try:
            deleted = prune_events(db, site_id=self._site_id, media_root=self._media_root)
            sweep_orphans(db, site_id=self._site_id, media_root=self._media_root)
            return deleted
        finally:
            db.close()

    async def run(self) -> None:
        """Loop until close(); the first sweep runs immediately."""
        while not self._stopped.is_set():
            with contextlib.suppress(Exception):
                await self.sweep_once()
            try:
                await asyncio.wait_for(self._stopped.wait(), timeout=self._interval_s)
            except TimeoutError:
                continue
            except asyncio.CancelledError:
                break

    async def close(self) -> None:
        """Stop after the current sweep."""
        self._stopped.set()
