"""WhatsApp adapter stub behind the same interface (spec A5.6).

Deferred deliberately: Meta business verification plus approved templates
would stall the MVP on setup friction. The protocol is what ships now, so
adding WhatsApp later touches one file.
"""

from __future__ import annotations

from app.db.models import Event


class WhatsAppNotifier:
    """Not implemented (Phase 5+). Present so the seam is real, not planned."""

    async def send(self, event: Event) -> None:
        """Raise: WhatsApp delivery does not exist yet."""
        raise NotImplementedError("WhatsApp ships after MVP verification (spec A5.6)")
