"""Roi model (DATABASE §4.5).

Coordinates are normalised 0..1 relative to frame width/height. Absolute pixels
fail *quietly* on a resolution change, alerting on the wrong area.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.db.base import Base
from app.db.models.site import _utcnow


class Roi(Base):
    __tablename__ = "rois"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    camera_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    # [[x,y], ...] normalised, >= 3 vertices. JSON, not a child table — always
    # read and written whole; a roi_points table would add a join for no query
    # benefit (DATABASE §7).
    points: Mapped[list[list[float]]] = mapped_column(JSON, nullable=False)
    class_filter: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow, onupdate=_utcnow, server_default=func.now()
    )
