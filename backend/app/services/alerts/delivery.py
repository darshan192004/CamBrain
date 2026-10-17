"""Durable delivery sweep: DB poll, exponential backoff capped at 1h (D4, A5.6).

Work is discovered in the database, never a queue — an asyncio.Queue dies
with the process and is not thread-safe from the camera loops, while a
pending row survives restarts exactly as the event itself does.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from app.db.models.event import Event
from app.db.models.site import Site
from app.db.session import SessionLocal
from app.services.alerts.notifier import Notifier
from app.services.events.persist import mark_delivery

RetryableStatus = ("pending", "failed")


def backoff_s(attempts: int, *, cap_s: float = 3600.0) -> float:
    """min(5 * 2**attempts, cap) — 5s, 10s, 20s … capped at one hour."""
    return float(min(5 * (2 ** max(attempts, 0)), cap_s))


def _utcnow() -> datetime:
    return datetime.now(tz=UTC).replace(tzinfo=None)


def _build_notifiers(config: Any) -> list[Notifier]:
    """Notifiers from one stored site config (a list of entries); Telegram only."""
    from app.core.crypto import decrypt
    from app.services.alerts.telegram import TelegramNotifier
    from app.services.alerts.whatsapp import WhatsAppNotifier

    out: list[Notifier] = []
    entries = config if isinstance(config, list) else []
    for entry in entries:
        if not entry.get("enabled", True):
            continue
        if entry.get("kind") == "telegram":
            token = (entry.get("config") or {}).get("bot_token_enc")
            if token:
                out.append(
                    TelegramNotifier(
                        bot_token=decrypt(token),
                        chat_id=str((entry.get("config") or {}).get("chat_id", "")),
                    )
                )
        elif entry.get("kind") == "whatsapp":
            out.append(WhatsAppNotifier())
    return out


class DeliveryWorker:
    """Sweeps due events to their site's notifiers (spec A5.6, arch A7)."""

    def __init__(
        self,
        *,
        session_factory: Callable[[], Any] = SessionLocal,
        notifier_for: Callable[[int], list[Notifier]] | None = None,
        now: Callable[[], datetime] = _utcnow,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        interval_s: float = 10.0,
        backoff_cap_s: float = 3600.0,
        batch: int = 25,
    ) -> None:
        self._session_factory = session_factory
        self._notifier_for = notifier_for or self._default_notifiers
        self._now = now
        self._sleep = sleep
        self._interval_s = interval_s
        self._cap_s = backoff_cap_s
        self._batch = batch
        self._stopped = asyncio.Event()

    def _default_notifiers(self, site_id: int) -> list[Notifier]:
        db = self._session_factory()
        try:
            site = db.get(Site, site_id)
            return _build_notifiers(site.notifier_config) if site else []
        finally:
            db.close()

    async def sweep_once(self) -> int:
        """Deliver every due pending/failed event once; returns delivered count.

        The scan looks past the first `batch` rows (8× window) because rows in
        backoff keep occupying the oldest slots; delivering stops at `batch`
        due events per sweep.
        """
        db = self._session_factory()
        try:
            now = self._now()
            events = (
                db.execute(
                    select(Event)
                    .where(Event.delivery_status.in_(RetryableStatus))
                    .order_by(Event.id)
                    .limit(self._batch * 8)
                )
                .scalars()
                .all()
            )
            delivered = 0
            for event in events:
                if delivered >= self._batch:
                    break
                if event.last_attempt_at is not None:
                    elapsed = (now - event.last_attempt_at).total_seconds()
                    if elapsed < backoff_s(event.delivery_attempts, cap_s=self._cap_s):
                        continue
                notifiers = self._notifier_for(event.site_id)
                if not notifiers:
                    mark_delivery(
                        db,
                        event.id,
                        status="failed",
                        attempts=event.delivery_attempts + 1,
                        error="no enabled notifier configured for this site",
                        attempted=now,
                    )
                    continue
                try:
                    for notifier in notifiers:
                        await notifier.send(event)
                except Exception as exc:  # noqa: BLE001 - one failure, durable retry
                    mark_delivery(
                        db,
                        event.id,
                        status="pending",
                        attempts=event.delivery_attempts + 1,
                        error=f"{type(exc).__name__}: {exc}",
                        attempted=now,
                    )
                else:
                    mark_delivery(
                        db,
                        event.id,
                        status="sent",
                        attempts=event.delivery_attempts + 1,
                        error=None,
                        delivered=now,
                        attempted=now,
                    )
                    delivered += 1
        finally:
            db.close()
        return delivered

    async def run(self) -> None:
        """Poll loop until close() is called (started by the runtime, T13)."""
        while not self._stopped.is_set():
            with contextlib.suppress(Exception):  # noqa: BLE001 - the loop must survive
                await self.sweep_once()
            try:
                await self._wait()
            except asyncio.CancelledError:
                break

    async def _wait(self) -> None:
        try:
            await asyncio.wait_for(self._stopped.wait(), timeout=self._interval_s)
        except TimeoutError:
            return

    async def close(self) -> None:
        """Stop the loop; pending rows stay pending for the next run."""
        self._stopped.set()
