"""deterministic silent summary videos

Revision ID: 20260906_0008
Revises: 20260906_0007
Create Date: 2026-09-06
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260906_0008"
down_revision: Union[str, None] = "20260906_0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("media_assets_kind_check", "media_assets", type_="check")
    op.create_check_constraint(
        "media_assets_kind_check",
        "media_assets",
        "kind in ('original', 'preview', 'analysis_frame', 'summary_video')",
    )
    op.create_table(
        "summary_videos",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("selected_segments", sa.JSON(), server_default=sa.text("'[]'::json"), nullable=False),
        sa.Column("duration_seconds", sa.Numeric(12, 3), nullable=True),
        sa.Column("analysis_revision", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["session_id"], ["analysis_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["asset_id"], ["media_assets.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id"),
        sa.CheckConstraint(
            "status in ('pending', 'processing', 'completed', 'failed')",
            name="summary_videos_status_check",
        ),
    )
    op.create_index("ix_summary_videos_session_id", "summary_videos", ["session_id"], unique=True)
    op.create_index("ix_summary_videos_owner_id", "summary_videos", ["owner_id"])


def downgrade() -> None:
    op.drop_index("ix_summary_videos_owner_id", table_name="summary_videos")
    op.drop_index("ix_summary_videos_session_id", table_name="summary_videos")
    op.drop_table("summary_videos")
    op.drop_constraint("media_assets_kind_check", "media_assets", type_="check")
    op.create_check_constraint(
        "media_assets_kind_check",
        "media_assets",
        "kind in ('original', 'preview', 'analysis_frame')",
    )
