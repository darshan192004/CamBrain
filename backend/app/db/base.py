"""SQLAlchemy 2.0 declarative base shared by every model."""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Common base for all mapped classes."""
