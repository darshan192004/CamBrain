"""/ws/alerts — server-to-client only (API A3).

Token travels via Sec-WebSocket-Protocol (`cambrain.jwt.<token>`) because URLs
leak into logs and history; a first-message fallback covers clients that cannot
set subprotocols. Mutations never ride this socket.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.api.auth import AuthError, verify_access_token
from app.api.deps import DbSessionDep
from app.services.alerts.hub import get_alert_hub

router = APIRouter()

HEARTBEAT_S = 30.0
_PROTOCOL_PREFIX = "cambrain.jwt."


def _token_from(websocket: WebSocket) -> str | None:
    """Pull the JWT out of the subprotocol list, if present."""
    for proto in websocket.headers.get("sec-websocket-protocol", "").split(","):
        value = proto.strip()
        if value.startswith(_PROTOCOL_PREFIX):
            return value[len(_PROTOCOL_PREFIX) :]
    return None


def _authenticate(db: DbSessionDep, token: str) -> int | None:
    """Verify the token; return site_id or None (route then closes 4401)."""
    try:
        claims = verify_access_token(db, token)
    except AuthError:
        return None
    site_id = claims["site_id"]
    return site_id if isinstance(site_id, int) else None


async def _heartbeat(websocket: WebSocket) -> None:
    """Send the API.md heartbeat every HEARTBEAT_S until cancelled."""
    while True:
        await asyncio.sleep(HEARTBEAT_S)
        await websocket.send_json(
            {
                "type": "heartbeat",
                "data": {
                    "ts": datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
                },
            }
        )


@router.websocket("/ws/alerts")
async def ws_alerts(websocket: WebSocket, db: DbSessionDep) -> None:
    """Authenticated per-site alert stream (API A3)."""
    token = _token_from(websocket)
    if token is not None:
        site_id = _authenticate(db, token)
        if site_id is None:
            # A supplied-but-invalid token is rejected at the handshake.
            await websocket.close(code=4401)
            return
        offered = websocket.headers.get("sec-websocket-protocol", "")
        chosen = f"{_PROTOCOL_PREFIX}{token}"
        await websocket.accept(subprotocol=chosen if chosen in offered else None)
    else:
        # No subprotocol: accept, allow one auth message, else 4401.
        await websocket.accept()
        try:
            message = await asyncio.wait_for(websocket.receive_json(), timeout=5.0)
        except (TimeoutError, WebSocketDisconnect, ValueError):
            await websocket.close(code=4401)
            return
        token = message.get("token") if isinstance(message, dict) else None
        site_id = _authenticate(db, token) if token else None
        if site_id is None:
            await websocket.close(code=4401)
            return

    hub = get_alert_hub()
    hub.subscribe(site_id, websocket)
    heartbeat = asyncio.create_task(_heartbeat(websocket))
    try:
        while True:
            await websocket.receive_text()  # client frames ignored (server->client only)
    except WebSocketDisconnect:
        pass
    finally:
        heartbeat.cancel()
        hub.unsubscribe(site_id, websocket)
