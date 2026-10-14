"""The delivery seam where the product's promise is kept (spec A5.6).

Notification failure must never lose an event: everything before this
protocol is local and durable, and Telegram is the one permitted failure.
"""

from __future__ import annotations

from typing import Protocol

from app.db.models import Event


class Notifier(Protocol):
    """Send one persisted event. Implementations raise on failure."""

    async def send(self, event: Event) -> None: ...
