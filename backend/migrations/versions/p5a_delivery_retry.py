"""Add events.last_attempt_at for durable delivery backoff (phase 5).

Revision ID: p5a_delivery_retry
Revises: b0d9844cf940
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "p5a_delivery_retry"
down_revision: str | None = "b0d9844cf940"
branch_labels: str | list[str] | None = None
depends_on: str | list[str] | None = None


def upgrade() -> None:
    op.add_column("events", sa.Column("last_attempt_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("events") as batch:
        batch.drop_column("last_attempt_at")
