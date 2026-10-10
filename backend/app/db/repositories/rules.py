"""Rule repository (API §5, DATABASE §4.6).

Rules soft-delete via deleted_at because events keep a reference to the rule
that fired them; a hard delete would orphan historical events or force a
cascade that erases the audit trail. get/list hide soft-deleted rows so the
API behaves as if they are gone while the data stays for forensics.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.db.models import Rule
from app.db.models.site import _utcnow
from app.db.repositories.base import TenantScopedRepository


class RuleRepository(TenantScopedRepository[Rule]):
    def __init__(self, session: Session, *, site_id: int) -> None:
        super().__init__(session, Rule, site_id=site_id)

    def get(self, rule_id: int) -> Rule | None:
        rule = self._get_scoped(rule_id)
        if rule is None or rule.deleted_at is not None:
            return None
        return rule

    def list(self) -> list[Rule]:
        query = self._scoped().where(Rule.deleted_at.is_(None))
        return list(self.session.execute(query).scalars())

    def create(self, **fields: Any) -> Rule:
        rule = Rule(site_id=self.site_id, **fields)
        self.session.add(rule)
        self.session.commit()
        self.session.refresh(rule)
        return rule

    def update(self, rule_id: int, **fields: Any) -> Rule | None:
        rule = self.get(rule_id)
        if rule is None:
            return None
        for key, value in fields.items():
            setattr(rule, key, value)
        self.session.commit()
        self.session.refresh(rule)
        return rule

    def soft_delete(self, rule_id: int) -> bool:
        """Mark deleted_at. Returns False if not found or already deleted."""
        rule = self.get(rule_id)
        if rule is None:
            return False
        # Column is naive DateTime; _utcnow is aware, so drop tzinfo.
        rule.deleted_at = _utcnow().replace(tzinfo=None)
        self.session.commit()
        return True
