"""Tenant-scoped repositories (DATABASE §2, §4).

Each repository is bound to a site_id at construction; every query filters on
it, so a row belonging to another site resolves to None rather than being
returned. The API layer maps that None to a 404.
"""

from __future__ import annotations

from app.db.repositories.cameras import CameraRepository
from app.db.repositories.rois import RoiRepository
from app.db.repositories.rules import RuleRepository

__all__ = ["CameraRepository", "RoiRepository", "RuleRepository"]
