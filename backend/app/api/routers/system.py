"""System routes: health (unauthenticated), status, and config (API §System).

`GET /system/health` exposes only `{status, version, uptime_s}` and is for
the Tauri shell and the installer to poll; it needs no auth.
"""

from __future__ import annotations

import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import func, select

from app.api.deps import ClaimsDep, DbSessionDep, require_role_dep
from app.api.schemas import HealthOut
from app.core.config import settings
from app.db.models.camera import Camera
from app.db.models.site import Site

router = APIRouter(tags=["system"])

AdminDep = Annotated[dict[str, Any], Depends(require_role_dep("admin"))]

_VERSION = "0.1.0"

# Process start time, set at import; uptime_s = now - start.
_START = time.monotonic()


@router.get("/system/health", response_model=HealthOut)
def health() -> HealthOut:
    """Unauthenticated liveness probe. Exposes only status, version, uptime."""
    return HealthOut(status="ok", version=_VERSION, uptime_s=round(time.monotonic() - _START, 1))


@router.get("/system/status")
def status_route(claims: ClaimsDep, db: DbSessionDep) -> dict[str, Any]:
    """Hardware/model/camera summary for the dashboard.

    Phase 3/4 wire real hardware probing and model info; this returns the
    camera counts and a placeholder tier so the route contract is correct.
    """
    site_id = int(claims["site_id"])
    camera_count = int(
        db.execute(
            select(func.count()).select_from(Camera).where(Camera.site_id == site_id)
        ).scalar_one()
    )
    site = db.get(Site, site_id)
    return {
        "version": _VERSION,
        "hardware_tier": "unknown",
        "hardware": {},
        "model": {},
        "cameras": [],
        "stats": {
            "cameras_total": camera_count,
            "retention_days": site.retention_days if site else None,
        },
    }


@router.get("/system/config")
def get_config(claims: AdminDep) -> dict[str, Any]:  # noqa: ARG001
    """Read effective runtime configuration (no secrets). Admin only."""
    return {
        "bind_host": settings.bind_host,
        "bind_port": settings.bind_port,
        "cors_origins": settings.cors_origins,
    }


@router.post("/system/config", status_code=status.HTTP_200_OK)
def post_config(claims: AdminDep) -> Response:  # noqa: ARG001
    """Persist runtime config. Phase 4 wires hot-reload; explicit 501."""
    return Response(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        content='{"error": {"code": "NOT_IMPLEMENTED", "message": "hot-reload lands in Phase 4", "field": null, "correlation_id": "none"}}',
        media_type="application/json",
    )
