"""analysis sessions, evidence frames, and observations

Revision ID: 20260905_0002
Revises: 20260905_0001
Create Date: 2026-09-05
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260905_0002"
down_revision: Union[str, None] = "20260905_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("media_assets_kind_check", "media_assets", type_="check")
    op.create_check_constraint(
        "media_assets_kind_check",
        "media_assets",
        "kind in ('original', 'preview', 'analysis_frame')",
    )

    op.create_table(
        "analysis_sessions",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("video_id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.String(length=80), nullable=False),
        sa.Column("profile_version", sa.String(length=30), nullable=False),
        sa.Column("sampling_interval_seconds", sa.Numeric(8, 3), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("phase", sa.String(length=40), server_default="queued", nullable=False),
        sa.Column("total_jobs", sa.Integer(), server_default="1", nullable=False),
        sa.Column("completed_jobs", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failed_jobs", sa.Integer(), server_default="0", nullable=False),
        sa.Column("terminal_progress_percent", sa.Integer(), server_default="0", nullable=False),
        sa.Column("analysis_revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("capabilities", sa.JSON(), server_default=sa.text("'{}'::json"), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["video_id"], ["videos.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("status in ('pending', 'running', 'completed', 'partial', 'failed')", name="analysis_sessions_status_check"),
        sa.CheckConstraint("sampling_interval_seconds between 2 and 60", name="analysis_sessions_interval_check"),
    )
    op.create_index("ix_analysis_sessions_owner_id", "analysis_sessions", ["owner_id"])
    op.create_index("ix_analysis_sessions_video_id", "analysis_sessions", ["video_id"])

    op.create_table(
        "analysis_frames",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("timestamp_seconds", sa.Numeric(12, 3), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["media_assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["analysis_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("asset_id"),
    )
    op.create_index("ix_analysis_frames_session_id", "analysis_frames", ["session_id"])
    op.create_index("ix_analysis_frames_session_time", "analysis_frames", ["session_id", "timestamp_seconds"])

    op.create_table(
        "analysis_observations",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("frame_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(length=80), nullable=False),
        sa.Column("start_seconds", sa.Numeric(12, 3), nullable=False),
        sa.Column("end_seconds", sa.Numeric(12, 3), nullable=False),
        sa.Column("observation", sa.Text(), nullable=False),
        sa.Column("interpretation", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column("importance", sa.Numeric(5, 4), server_default="0", nullable=False),
        sa.Column("limitations", sa.JSON(), server_default=sa.text("'[]'::json"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["frame_id"], ["analysis_frames.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["analysis_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("confidence between 0 and 1", name="analysis_observations_confidence_check"),
        sa.CheckConstraint("importance between 0 and 1", name="analysis_observations_importance_check"),
        sa.CheckConstraint("end_seconds >= start_seconds", name="analysis_observations_time_check"),
    )
    op.create_index("ix_analysis_observations_session_id", "analysis_observations", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_analysis_observations_session_id", table_name="analysis_observations")
    op.drop_table("analysis_observations")
    op.drop_index("ix_analysis_frames_session_time", table_name="analysis_frames")
    op.drop_index("ix_analysis_frames_session_id", table_name="analysis_frames")
    op.drop_table("analysis_frames")
    op.drop_index("ix_analysis_sessions_video_id", table_name="analysis_sessions")
    op.drop_index("ix_analysis_sessions_owner_id", table_name="analysis_sessions")
    op.drop_table("analysis_sessions")
    op.drop_constraint("media_assets_kind_check", "media_assets", type_="check")
    op.create_check_constraint(
        "media_assets_kind_check", "media_assets", "kind in ('original', 'preview')"
    )
