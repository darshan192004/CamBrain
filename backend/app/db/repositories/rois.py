"""Roi repository (API §4, DATABASE §4.5).

An ROI is scoped to both site_id and camera_id; the repository scopes on site
and lets the API layer verify camera ownership before calling in, so a caller
cannot attach an ROI to another tenant's camera by guessing its id.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.db.models import Roi
from app.db.repositories.base import TenantScopedRepository


class RoiRepository(TenantScopedRepository[Roi]):
    def __init__(self, session: Session, *, site_id: int) -> None:
        super().__init__(session, Roi, site_id=site_id)

    def get(self, roi_id: int) -> Roi | None:
        return self._get_scoped(roi_id)

    def list(self, *, camera_id: int | None = None) -> list[Roi]:
        query = self._scoped()
        if camera_id is not None:
            query = query.where(Roi.camera_id == camera_id)
        return list(self.session.execute(query).scalars())

    def create(self, **fields: Any) -> Roi:
        roi = Roi(site_id=self.site_id, **fields)
        self.session.add(roi)
        self.session.commit()
        self.session.refresh(roi)
        return roi

    def update(self, roi_id: int, **fields: Any) -> Roi | None:
        roi = self.get(roi_id)
        if roi is None:
            return None
        for key, value in fields.items():
            setattr(roi, key, value)
        self.session.commit()
        self.session.refresh(roi)
        return roi

    def delete(self, roi_id: int) -> bool:
        roi = self.get(roi_id)
        if roi is None:
            return False
        self.session.delete(roi)
        self.session.commit()
        return True
