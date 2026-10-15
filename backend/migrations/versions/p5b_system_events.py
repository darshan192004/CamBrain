"""events.camera_id goes nullable: site-level system events (phase 5).

Revision ID: p5b_system_events
Revises: p5a_delivery_retry
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "p5b_system_events"
down_revision: str | None = "p5a_delivery_retry"
branch_labels: str | list[str] | None = None
depends_on: str | list[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("events") as batch:
        batch.alter_column("camera_id", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    with op.batch_alter_table("events") as batch:
        batch.alter_column("camera_id", existing_type=sa.Integer(), nullable=False)
