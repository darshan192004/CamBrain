"""Tenant-scoped fan-out for /ws/alerts (API A3).

Owns: the subscriber sets and the cross-thread marshal from camera loops onto
the API event loop. Deliberately does not own: authentication (the route
verifies the token) or payload shape policy beyond the two builders here.
"""

from __future__ import annotations

import asyncio
import threading
from datetime import UTC
from typing import Any

from starlette.websockets import WebSocket

from app.db.models import Event


class AlertHub:
    """Thread-safe broadcaster: camera worker threads -> API loop -> sockets."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subs: dict[int, set[WebSocket]] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    def subscribe(self, site_id: int, ws: WebSocket) -> None:
        """Register a socket; records the API loop on first subscribe."""
        with self._lock:
            if self._loop is None:
                self._loop = asyncio.get_running_loop()
            self._subs.setdefault(site_id, set()).add(ws)

    def unsubscribe(self, site_id: int, ws: WebSocket) -> None:
        """Drop a socket; never raises when already gone."""
        with self._lock:
            subs = self._subs.get(site_id)
            if subs is not None:
                subs.discard(ws)
                if not subs:
                    self._subs.pop(site_id, None)

    def broadcast(self, site_id: int, message: dict[str, Any]) -> None:
        """Send ``message`` to every socket of ``site_id``; no-op with none.

        Safe from any thread: same-loop callers create a task, foreign threads
        marshal onto the API loop. Send failures drop that socket only.
        """
        with self._lock:
            subs = list(self._subs.get(site_id, ()))
            loop = self._loop
        if not subs or loop is None:
            return

        async def _dispatch() -> None:
            for ws in subs:
                try:
                    await ws.send_json(message)
                except Exception:  # noqa: BLE001 - a dead socket must not break fan-out
                    self.unsubscribe(site_id, ws)

        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            loop.create_task(_dispatch())
        else:
            asyncio.run_coroutine_threadsafe(_dispatch(), loop)


_HUB = AlertHub()


def get_alert_hub() -> AlertHub:
    """The process-wide hub (tests reset it via the conftest fixture)."""
    return _HUB


def event_message(event: Event, camera_name: str | None) -> dict[str, Any]:
    """The API.md `event` frame; idempotent — clients upsert by id (D6)."""
    started = event.started_at
    if started.tzinfo is None:
        started = started.replace(tzinfo=UTC)
    return {
        "type": "event",
        "data": {
            "id": event.id,
            "camera": {"id": event.camera_id, "name": camera_name or "System"},
            "severity": event.severity,
            "summary": event.summary,
            "started_at": started.isoformat().replace("+00:00", "Z"),
            "has_clip": event.clip_path is not None,
        },
    }
