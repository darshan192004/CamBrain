"""Settings and notifiers routes (API §Users, settings, system).

Notifiers are stored as a JSON list on the site row; there is no separate
notifier table because the config is read and written whole and never
queried per-field.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response, status

from app.api.deps import ClaimsDep, DbSessionDep, require_role_dep
from app.api.schemas import (
    NotifierCreate,
    NotifierOut,
    NotifierPatch,
    SettingsOut,
    SettingsPatch,
)
from app.core.errors import NotFoundError, ValidationError
from app.db.models.site import Site
from app.services.alerts.telegram import notifiers_from_entries, public_config, seal_config

router = APIRouter(tags=["settings"])

AdminDep = Annotated[dict[str, Any], Depends(require_role_dep("admin"))]


def _site(db: Any, claims: dict[str, Any]) -> Site:
    """Fetch the caller's site row."""
    site: Site | None = db.get(Site, int(claims["site_id"]))
    if site is None:
        raise NotFoundError("site not found")
    return site


def _settings_out(site: Site) -> SettingsOut:
    """Map a Site row to the public settings shape (no notifier secrets)."""
    return SettingsOut(
        name=site.name,
        timezone=site.timezone,
        retention_days=site.retention_days,
        disk_quota_pct=site.disk_quota_pct,
    )


def _notifiers(site: Site) -> list[dict[str, Any]]:
    """The site's notifier list, defaulting to empty."""
    config: Any = site.notifier_config
    if isinstance(config, list):
        return [dict(e) for e in config]
    return []


def _notifier_out(index: int, entry: dict[str, Any]) -> NotifierOut:
    """Map a notifier_config entry to its public shape (secrets masked)."""
    return NotifierOut(
        id=index,
        kind=str(entry.get("kind", "telegram")),
        enabled=bool(entry.get("enabled", True)),
        config=public_config(entry),
    )


@router.get("/settings", response_model=SettingsOut)
def get_settings(claims: ClaimsDep, db: DbSessionDep) -> SettingsOut:
    """Read the site's configuration."""
    return _settings_out(_site(db, claims))


@router.patch("/settings", response_model=SettingsOut)
def patch_settings(body: SettingsPatch, claims: AdminDep, db: DbSessionDep) -> SettingsOut:
    """Update the site's configuration. Admin only."""
    site = _site(db, claims)
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(site, key, value)
    db.commit()
    db.refresh(site)
    return _settings_out(site)


@router.get("/notifiers", response_model=list[NotifierOut])
def list_notifiers(claims: ClaimsDep, db: DbSessionDep) -> list[NotifierOut]:
    """List configured notifiers."""
    return [_notifier_out(i, e) for i, e in enumerate(_notifiers(_site(db, claims)))]


@router.post("/notifiers", response_model=NotifierOut, status_code=status.HTTP_201_CREATED)
def create_notifier(body: NotifierCreate, claims: AdminDep, db: DbSessionDep) -> NotifierOut:
    """Add a notifier. Admin only."""
    site = _site(db, claims)
    entries = _notifiers(site)
    entry = {"kind": body.kind, "enabled": body.enabled, "config": seal_config(body.config)}
    entries.append(entry)
    site.notifier_config = entries  # type: ignore[assignment]
    db.commit()
    return _notifier_out(len(entries) - 1, entry)


@router.patch("/notifiers/{notifier_id}", response_model=NotifierOut)
def patch_notifier(
    notifier_id: int, body: NotifierPatch, claims: AdminDep, db: DbSessionDep
) -> NotifierOut:
    """Update a notifier. Admin only."""
    site = _site(db, claims)
    entries = _notifiers(site)
    if notifier_id < 0 or notifier_id >= len(entries):
        raise NotFoundError("notifier not found")
    entry = entries[notifier_id]
    updates = body.model_dump(exclude_unset=True)
    if "enabled" in updates:
        entry["enabled"] = updates["enabled"]
    if "config" in updates and updates["config"] is not None:
        config = updates["config"]
        entry["config"] = seal_config(config) if isinstance(config, dict) else config
    site.notifier_config = entries  # type: ignore[assignment]
    db.commit()
    return _notifier_out(notifier_id, entry)


@router.delete("/notifiers/{notifier_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_notifier(notifier_id: int, claims: AdminDep, db: DbSessionDep) -> Response:
    """Remove a notifier. Admin only."""
    site = _site(db, claims)
    entries = _notifiers(site)
    if notifier_id < 0 or notifier_id >= len(entries):
        raise NotFoundError("notifier not found")
    entries.pop(notifier_id)
    site.notifier_config = entries  # type: ignore[assignment]
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/notifiers/test")
async def test_notifier(claims: AdminDep, db: DbSessionDep) -> dict[str, Any]:
    """Send a real test message; return Telegram's response verbatim (API §System).

    A notifier config that never delivered is not a working notifier —
    this is the install-time proof. No configured sender is a 422.
    """
    entries = _notifiers(_site(db, claims))
    senders = notifiers_from_entries(entries)
    if not senders:
        raise ValidationError("no enabled telegram notifier configured")
    return await senders[0].send_text("CamBrain test message")
