"""add user workspaces and video attachments

Revision ID: 20260907_0010
Revises: 20260906_0009
Create Date: 2026-09-07
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260907_0010"
down_revision: Union[str, None] = "20260906_0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "workspaces",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_workspaces_owner_id", "workspaces", ["owner_id"])
    op.create_index("ix_workspaces_owner_created", "workspaces", ["owner_id", "created_at"])
    op.create_table(
        "workspace_videos",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("video_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["video_id"], ["videos.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "video_id"),
    )
    op.create_index("ix_workspace_videos_workspace_id", "workspace_videos", ["workspace_id"])
    op.create_index("ix_workspace_videos_video_id", "workspace_videos", ["video_id"])
    op.create_index("ix_workspace_videos_workspace_added", "workspace_videos", ["workspace_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_workspace_videos_workspace_added", table_name="workspace_videos")
    op.drop_index("ix_workspace_videos_video_id", table_name="workspace_videos")
    op.drop_index("ix_workspace_videos_workspace_id", table_name="workspace_videos")
    op.drop_table("workspace_videos")
    op.drop_index("ix_workspaces_owner_created", table_name="workspaces")
    op.drop_index("ix_workspaces_owner_id", table_name="workspaces")
    op.drop_table("workspaces")
