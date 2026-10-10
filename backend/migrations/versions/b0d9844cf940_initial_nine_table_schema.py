"""initial nine-table schema

Revision ID: b0d9844cf940
Revises:
Create Date: 2026-10-10 16:21:10.572110

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b0d9844cf940"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sites",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("timezone", sa.String(), nullable=False),
        sa.Column("retention_days", sa.Integer(), nullable=False),
        sa.Column("disk_quota_pct", sa.Integer(), nullable=False),
        sa.Column("notifier_config", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "cameras",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("site_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("rtsp_url", sa.String(), nullable=False),
        sa.Column("rtsp_username", sa.String(), nullable=True),
        sa.Column("rtsp_password_enc", sa.LargeBinary(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("sample_fps", sa.Float(), nullable=False),
        sa.Column("motion_threshold", sa.Float(), nullable=False),
        sa.Column("frame_width", sa.Integer(), nullable=True),
        sa.Column("frame_height", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("last_error", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('starting','live','offline','error')", name="ck_cameras_status"
        ),
        sa.CheckConstraint("sample_fps >= 0.1 AND sample_fps <= 10", name="ck_cameras_sample_fps"),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_cameras_site_id"), "cameras", ["site_id"], unique=False)
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("site_id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(), nullable=False),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("role IN ('admin','viewer')", name="ck_users_role"),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("site_id", "username", name="uq_users_site_username"),
    )
    op.create_index(op.f("ix_users_site_id"), "users", ["site_id"], unique=False)
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("site_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("entity_type", sa.String(), nullable=True),
        sa.Column("entity_id", sa.Integer(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("ip", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_audit_log_created_at"), "audit_log", ["created_at"], unique=False)
    op.create_index(op.f("ix_audit_log_site_id"), "audit_log", ["site_id"], unique=False)
    op.create_table(
        "rois",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("site_id", sa.Integer(), nullable=False),
        sa.Column("camera_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("points", sa.JSON(), nullable=False),
        sa.Column("class_filter", sa.JSON(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["camera_id"], ["cameras.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_rois_camera_id"), "rois", ["camera_id"], unique=False)
    op.create_index(op.f("ix_rois_site_id"), "rois", ["site_id"], unique=False)
    op.create_table(
        "sessions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("site_id", sa.Integer(), nullable=False),
        sa.Column("refresh_token_hash", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("ip", sa.String(), nullable=True),
        sa.Column("user_agent", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_sessions_expires_at"), "sessions", ["expires_at"], unique=False)
    op.create_index(op.f("ix_sessions_user_id"), "sessions", ["user_id"], unique=False)
    op.create_table(
        "rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("site_id", sa.Integer(), nullable=False),
        sa.Column("camera_id", sa.Integer(), nullable=False),
        sa.Column("roi_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("classes", sa.JSON(), nullable=False),
        sa.Column("confidence_threshold", sa.Float(), nullable=False),
        sa.Column("cooldown_seconds", sa.Integer(), nullable=False),
        sa.Column("active_hours", sa.JSON(), nullable=True),
        sa.Column("severity", sa.String(), nullable=False),
        sa.Column("notify", sa.Boolean(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint("severity IN ('info','warning','critical')", name="ck_rules_severity"),
        sa.CheckConstraint(
            "confidence_threshold >= 0 AND confidence_threshold <= 1", name="ck_rules_confidence"
        ),
        sa.ForeignKeyConstraint(["camera_id"], ["cameras.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["roi_id"], ["rois.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_rules_camera_id"), "rules", ["camera_id"], unique=False)
    op.create_index(op.f("ix_rules_site_id"), "rules", ["site_id"], unique=False)
    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("site_id", sa.Integer(), nullable=False),
        sa.Column("camera_id", sa.Integer(), nullable=False),
        sa.Column("rule_id", sa.Integer(), nullable=True),
        sa.Column("triggered_by", sa.String(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("severity", sa.String(), nullable=False),
        sa.Column("summary", sa.String(), nullable=True),
        sa.Column("thumbnail_path", sa.String(), nullable=True),
        sa.Column("clip_path", sa.String(), nullable=True),
        sa.Column("clip_bytes", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("delivery_status", sa.String(), nullable=False),
        sa.Column("delivery_attempts", sa.Integer(), nullable=False),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
        sa.Column("last_delivery_error", sa.String(), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(), nullable=True),
        sa.Column("acknowledged_by", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "delivery_status IN ('pending','sent','failed','skipped')",
            name="ck_events_delivery_status",
        ),
        sa.CheckConstraint(
            "triggered_by IN ('rule','manual','system')", name="ck_events_triggered_by"
        ),
        sa.ForeignKeyConstraint(["acknowledged_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["camera_id"], ["cameras.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["rule_id"], ["rules.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_events_camera_id"), "events", ["camera_id"], unique=False)
    op.create_index(op.f("ix_events_site_id"), "events", ["site_id"], unique=False)
    op.create_table(
        "event_detections",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("camera_id", sa.Integer(), nullable=False),
        sa.Column("class_name", sa.String(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("bbox", sa.JSON(), nullable=False),
        sa.Column("track_id", sa.Integer(), nullable=True),
        sa.Column("zone_name", sa.String(), nullable=True),
        sa.Column("detected_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["camera_id"], ["cameras.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_event_detections_event_id"), "event_detections", ["event_id"], unique=False
    )


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(op.f("ix_event_detections_event_id"), table_name="event_detections")
    op.drop_table("event_detections")
    op.drop_index(op.f("ix_events_site_id"), table_name="events")
    op.drop_index(op.f("ix_events_camera_id"), table_name="events")
    op.drop_table("events")
    op.drop_index(op.f("ix_rules_site_id"), table_name="rules")
    op.drop_index(op.f("ix_rules_camera_id"), table_name="rules")
    op.drop_table("rules")
    op.drop_index(op.f("ix_sessions_user_id"), table_name="sessions")
    op.drop_index(op.f("ix_sessions_expires_at"), table_name="sessions")
    op.drop_table("sessions")
    op.drop_index(op.f("ix_rois_site_id"), table_name="rois")
    op.drop_index(op.f("ix_rois_camera_id"), table_name="rois")
    op.drop_table("rois")
    op.drop_index(op.f("ix_audit_log_site_id"), table_name="audit_log")
    op.drop_index(op.f("ix_audit_log_created_at"), table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_index(op.f("ix_users_site_id"), table_name="users")
    op.drop_table("users")
    op.drop_index(op.f("ix_cameras_site_id"), table_name="cameras")
    op.drop_table("cameras")
    op.drop_table("sites")
