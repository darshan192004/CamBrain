"""Camera repository (API §3, DATABASE §4.4).

Credentials are written only through the dedicated columns; the repository never
accepts a combined URL so there is no path for a password to leak into rtsp_url,
which is logged and returned to the client.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.db.models import Camera
from app.db.repositories.base import TenantScopedRepository


class CameraRepository(TenantScopedRepository[Camera]):
    def __init__(self, session: Session, *, site_id: int) -> None:
        super().__init__(session, Camera, site_id=site_id)

    def get(self, camera_id: int) -> Camera | None:
        return self._get_scoped(camera_id)

    def list(self) -> list[Camera]:
        return self._list_scoped()

    def create(self, **fields: Any) -> Camera:
        camera = Camera(site_id=self.site_id, **fields)
        self.session.add(camera)
        self.session.commit()
        self.session.refresh(camera)
        return camera

    def update(self, camera_id: int, **fields: Any) -> Camera | None:
        camera = self.get(camera_id)
        if camera is None:
            return None
        for key, value in fields.items():
            setattr(camera, key, value)
        self.session.commit()
        self.session.refresh(camera)
        return camera

    def delete(self, camera_id: int) -> bool:
        camera = self.get(camera_id)
        if camera is None:
            return False
        self.session.delete(camera)
        self.session.commit()
        return True
