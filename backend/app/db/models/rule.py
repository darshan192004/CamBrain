"""Rule model (DATABASE §4.6).

classes stores COCO *names*, not indices — YOLOX and RT-DETR do not share
output ordering, so storing indices would silently repoint every rule at the
wrong class when the model changes (spec §6.4).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.db.base import Base
from app.db.models.site import _utcnow


class Rule(Base):
    __tablename__ = "rules"
    __table_args__ = (
        CheckConstraint(
            "confidence_threshold >= 0 AND confidence_threshold <= 1", name="ck_rules_confidence"
        ),
        CheckConstraint("severity IN ('info','warning','critical')", name="ck_rules_severity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    camera_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # NULL roi = whole frame.
    roi_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("rois.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    classes: Mapped[list[str]] = mapped_column(JSON, nullable=False)  # COCO names
    confidence_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    cooldown_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    # {"timezone": "...", "windows": [{"start": "22:00", "end": "06:00"}]}
    active_hours: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    severity: Mapped[str] = mapped_column(String, nullable=False, default="warning")
    notify: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Soft delete — events reference the rule that fired them (API §2).
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow, onupdate=_utcnow, server_default=func.now()
    )
