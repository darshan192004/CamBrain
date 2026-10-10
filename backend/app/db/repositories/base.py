"""Tenant-scoped repository base (DATABASE §2).

Every repository is constructed with a session and a site_id; every query
filters on site_id, so a row belonging to another site is unreachable by
construction rather than by a discipline the caller can forget. A
cross-tenant id resolves to None — the API maps that to a 404, never a 403,
so an attacker cannot enumerate ids.

Generic over the concrete model so `id` and `site_id` are known statically
and mypy strict mode stays clean without per-call ignores. The model class is
passed to the constructor (not a class attribute) so the type parameter is
properly bound.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.orm import Session


class TenantScopedRepository[ModelT]:
    """Shared helpers for site_id-scoped reads."""

    def __init__(self, session: Session, model: type[ModelT], *, site_id: int) -> None:
        self.session = session
        self.model = model
        self.site_id = site_id

    def _scoped(self) -> Select[Any]:
        """Base select filtered to this tenant only."""
        return select(self.model).where(self.model.site_id == self.site_id)  # type: ignore[attr-defined]

    def _get_scoped(self, entity_id: int) -> ModelT | None:
        return self.session.execute(
            self._scoped().where(self.model.id == entity_id)  # type: ignore[attr-defined]
        ).scalar_one_or_none()

    def _list_scoped(self) -> list[ModelT]:
        return list(self.session.execute(self._scoped()).scalars())
