"""One alarm per crossing (D12): a persistent quota breach must not spam.

A disk that sits over quota would otherwise fire a system event on every
refused clip; the latch fires once per site until something clears it (the
sweep that frees space calls clear()).
"""

from __future__ import annotations

from collections.abc import Callable


class QuotaLatch:
    """Fire at most once per site until clear() is called."""

    def __init__(self, *, site_id: int, on_fire: Callable[[str], None] | None = None) -> None:
        self.site_id = site_id
        self._on_fire = on_fire
        self._fired = False

    @property
    def fired(self) -> bool:
        return self._fired

    def fire(self, summary: str) -> None:
        """Invoke on_fire the first time only."""
        if self._fired:
            return
        self._fired = True
        if self._on_fire is not None:
            self._on_fire(summary)

    def clear(self) -> None:
        """Re-arm after the disk pressure is resolved."""
        self._fired = False
