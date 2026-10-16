"""WhatsApp transport stub behind the `Notifier` protocol (memory D9).

Owns: nothing yet — Meta business verification plus approved templates
stall the MVP, so this raises until the adapter lands. The seam (one class,
same `send`) means swapping it in touches no caller.
"""

from __future__ import annotations

from app.core.errors import NotificationError


class WhatsappNotifier:
    """Placeholder. `send` always declines so events fall back, never vanish."""

    def __init__(self, token: str = "", phone_id: str = "") -> None:
        """Accept the future config shape so call sites don't change."""
        self._token = token
        self._phone_id = phone_id

    async def send(self, *, photo: bytes, caption: str) -> None:  # noqa: ARG002
        """Always decline — `deliver_event` records `failed`, the event survives."""
        raise NotificationError("whatsapp is not wired yet")
