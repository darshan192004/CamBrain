"""Notifier seam: delivery that can fail without losing the event (spec §5.6).

Owns: the `Notifier` protocol and the retry bookkeeping around it.
Does not own: any transport (see `telegram.py`) or persistence layout —
delivery state is recorded through `EventRepository`, never SQL here.

Notification failure must never lose an event: everything before this
module is local and durable, so `deliver_event` marks `failed` and returns
instead of raising.
"""

from __future__ import annotations

from typing import Protocol

from app.db.repositories.events import EventRepository


class Notifier(Protocol):
    """Deliver one rendered alert somewhere. WhatsApp plugs in here later."""

    async def send(self, *, photo: bytes, caption: str) -> None: ...


async def deliver_event(
    repo: EventRepository,
    event_id: int,
    *,
    photo: bytes,
    caption: str,
    notifiers: list[Notifier],
) -> None:
    """Try each notifier; record `sent`/`failed` on the event. Never raises."""
    errors: list[str] = []
    for notifier in notifiers:
        try:
            await notifier.send(photo=photo, caption=caption)
        except Exception as exc:  # noqa: BLE001 — delivery must not kill the pipeline
            errors.append(str(exc))
            continue
        repo.mark_sent(event_id)
        return
    repo.mark_failed(event_id, "; ".join(errors) if errors else "no notifiers configured")
