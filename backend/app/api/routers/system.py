"""System routes: health (unauthenticated), status, and config (API §System).

`GET /system/health` exposes only `{status, version, uptime_s}` and is for
the Tauri shell and the installer to poll; it needs no auth.
"""

from __future__ import annotations

import shutil
import time
from datetime import UTC, datetime
from typing import Annotated, Any

import psutil
from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import func, select

from app.api.deps import ClaimsDep, DbSessionDep, require_role_dep
from app.api.schemas import HealthOut
from app.core.config import settings
from app.db.models.camera import Camera
from app.db.models.event import Event
from app.db.models.site import Site
from app.services.inference.tiers import probe_capabilities, resolve_tier
from app.services.stream.stats import StreamStats, get_stream_stats

router = APIRouter(tags=["system"])

AdminDep = Annotated[dict[str, Any], Depends(require_role_dep("admin"))]
StreamStatsDep = Annotated[StreamStats, Depends(get_stream_stats)]

_VERSION = "0.1.0"

# Process start time, set at import; uptime_s = now - start.
_START = time.monotonic()


def _probe_hardware() -> dict[str, Any]:
    """One-shot hardware snapshot for /system/status (API §System rows)."""
    caps = probe_capabilities()
    vm = psutil.virtual_memory()
    # media_root may not exist yet; probe its nearest existing ancestor.
    probe = settings.media_root
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    disk = shutil.disk_usage(probe)
    return {
        "cpu_cores": caps.cores,
        "avx2": caps.avx2,
        "vnni": caps.vnni,
        "ram_total_mb": round(vm.total / 1_048_576),
        "ram_used_mb": round((vm.total - vm.available) / 1_048_576),
        "disk_total_gb": round(disk.total / 1_073_741_824),
        "disk_used_pct": round(disk.used / disk.total * 100),
    }


def _resolve_model() -> tuple[str, dict[str, Any]]:
    """(tier, model row); a probe failure reports "unknown" + empty model."""
    try:
        tier, model_path, input_size = resolve_tier()
    except OSError:
        return "unknown", {}
    return tier, {"name": model_path.name, "tier": tier, "input": [input_size, input_size]}


# Cached at import: the tier never changes mid-process, and the dashboard
# polls this endpoint — re-probing per request would buy nothing. A probe
# failure degrades to "unknown"/empty rather than taking the API down.
_HARDWARE: dict[str, Any] = {}
try:
    _HARDWARE = _probe_hardware()
except Exception:  # noqa: BLE001 — dashboard must render whatever we can read
    _HARDWARE = {}
_TIER, _MODEL = _resolve_model()


@router.get("/system/health", response_model=HealthOut)
def health() -> HealthOut:
    """Unauthenticated liveness probe. Exposes only status, version, uptime."""
    return HealthOut(status="ok", version=_VERSION, uptime_s=round(time.monotonic() - _START, 1))


@router.get("/system/status")
def status_route(claims: ClaimsDep, db: DbSessionDep, stats: StreamStatsDep) -> dict[str, Any]:
    """Hardware/model/camera summary for the dashboard.

    Camera rows join the stored row with live MJPEG stream stats: `live`
    means a consumer is connected and frames are fresh (stats.py), while
    anything else falls back to the stored `status`. Fields with no data
    yet (`fps`, `frames_processed`, `last_error`) are omitted, not zeroed —
    an absent number reads as "unknown", a zero reads as "measured none".
    """
    site_id = int(claims["site_id"])
    today = (
        datetime.now(tz=UTC).replace(tzinfo=None).replace(hour=0, minute=0, second=0, microsecond=0)
    )
    events_today = db.execute(
        select(func.count(Event.id)).where(Event.site_id == site_id, Event.started_at >= today)
    ).scalar_one()
    alerts_sent = db.execute(
        select(func.count(Event.id)).where(
            Event.site_id == site_id, Event.started_at >= today, Event.delivery_status == "sent"
        )
    ).scalar_one()
    alerts_failed = db.execute(
        select(func.count(Event.id)).where(
            Event.site_id == site_id, Event.started_at >= today, Event.delivery_status == "failed"
        )
    ).scalar_one()
    cameras = (
        db.execute(select(Camera).where(Camera.site_id == site_id).order_by(Camera.id))
        .scalars()
        .all()
    )
    camera_count = len(cameras)
    site = db.get(Site, site_id)
    rows: list[dict[str, Any]] = []
    for camera in cameras:
        snapshot = stats.row(camera.id)
        entry: dict[str, Any] = {
            "id": camera.id,
            "name": camera.name,
            "status": "live" if snapshot["active"] else camera.status,
        }
        if snapshot["frames"]:
            entry["frames_processed"] = snapshot["frames"]
        if snapshot["fps"] is not None:
            entry["fps"] = snapshot["fps"]
        if snapshot["last_frame_at"] is not None:
            entry["last_frame_at"] = snapshot["last_frame_at"]
        if camera.last_error:
            entry["last_error"] = camera.last_error
        rows.append(entry)
    return {
        "version": _VERSION,
        "hardware_tier": _TIER,
        "hardware": _HARDWARE,
        "model": _MODEL,
        "cameras": rows,
        "stats": {
            "cameras_total": camera_count,
            "retention_days": site.retention_days if site else None,
            "events_today": events_today,
            "alerts_sent": alerts_sent,
            "alerts_failed": alerts_failed,
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
