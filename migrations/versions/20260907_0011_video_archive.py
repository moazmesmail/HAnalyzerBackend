"""add video archive state

Revision ID: 20260907_0011
Revises: 20260907_0010
Create Date: 2026-09-07
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260907_0011"
down_revision: Union[str, None] = "20260907_0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("videos", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_videos_owner_archived_created", "videos", ["owner_id", "archived_at", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_videos_owner_archived_created", table_name="videos")
    op.drop_column("videos", "archived_at")
