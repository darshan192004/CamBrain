"""In-memory alert ledger for the dashboard ticker (API §WebSocket).

Owns: the last broadcast events so a future `/ws/alerts` endpoint has
something to replay on connect. Does not own: sockets — polling
`GET /events` stays correct meanwhile, and the durable record is the DB.
"""

from __future__ import annotations

from collections import deque
from typing import Any

_HISTORY = 50

_ledger: deque[dict[str, Any]] = deque(maxlen=_HISTORY)


def broadcast(event: dict[str, Any]) -> None:
    """Record one alert payload. Never blocks, never raises."""
    _ledger.append(event)


def recent() -> list[dict[str, Any]]:
    """Newest-last ledger for reconnect resync (`GET /events?since=` covers gaps)."""
    return list(_ledger)


def clear() -> None:
    """Test hook: empty the ledger."""
    _ledger.clear()
