"""Site — the tenant root (DATABASE §4.1).

Owns per-site configuration (timezone, retention, disk quota, notifier config).
Does not own: cameras, rules, or users — those hang off it via site_id.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Site(Base):
    __tablename__ = "sites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    # IANA name, never a fixed UTC offset — "after hours" is local time.
    timezone: Mapped[str] = mapped_column(String, nullable=False)
    retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=7)
    disk_quota_pct: Mapped[int] = mapped_column(Integer, nullable=False, default=80)
    notifier_config: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow, server_default=func.now()
    )
