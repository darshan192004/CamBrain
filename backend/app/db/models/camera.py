"""Camera model (DATABASE §4.4).

Credentials are separate columns, not embedded in the URL, so the URL can be
logged, displayed, and used as a stable identifier without carrying a password
— the encryption boundary covers exactly two fields.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import LargeBinary

from app.db.base import Base
from app.db.models.site import _utcnow


class Camera(Base):
    __tablename__ = "cameras"
    __table_args__ = (
        CheckConstraint("sample_fps >= 0.1 AND sample_fps <= 10", name="ck_cameras_sample_fps"),
        CheckConstraint(
            "status IN ('starting','live','offline','error')", name="ck_cameras_status"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String, nullable=False)  # display only, never a path
    # Credentials stripped — stored in the two columns below.
    rtsp_url: Mapped[str] = mapped_column(String, nullable=False)
    rtsp_username: Mapped[str | None] = mapped_column(String, nullable=True)
    rtsp_password_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sample_fps: Mapped[float] = mapped_column(Float, nullable=False, default=2.0)
    motion_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.02)
    frame_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    frame_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="starting")
    last_error: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow, onupdate=_utcnow, server_default=func.now()
    )
