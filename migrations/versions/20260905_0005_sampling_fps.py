"""replace sampling interval with frames per second

Revision ID: 20260905_0005
Revises: 20260905_0004
Create Date: 2026-09-05
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260905_0005"
down_revision: Union[str, None] = "20260905_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("analysis_sessions_interval_check", "analysis_sessions", type_="check")
    op.alter_column(
        "analysis_sessions",
        "sampling_interval_seconds",
        new_column_name="sampling_fps",
        existing_type=sa.Numeric(8, 3),
        type_=sa.Numeric(8, 3),
        existing_nullable=False,
        postgresql_using="3::numeric",
    )
    op.create_check_constraint(
        "analysis_sessions_fps_check",
        "analysis_sessions",
        "sampling_fps between 3 and 10",
    )


def downgrade() -> None:
    op.drop_constraint("analysis_sessions_fps_check", "analysis_sessions", type_="check")
    op.alter_column(
        "analysis_sessions",
        "sampling_fps",
        new_column_name="sampling_interval_seconds",
        existing_type=sa.Numeric(8, 3),
        type_=sa.Numeric(8, 3),
        existing_nullable=False,
        postgresql_using="10::numeric",
    )
    op.create_check_constraint(
        "analysis_sessions_interval_check",
        "analysis_sessions",
        "sampling_interval_seconds between 2 and 60",
    )
