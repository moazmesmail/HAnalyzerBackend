"""allow analysis sampling up to 15 fps

Revision ID: 20260905_0006
Revises: 20260905_0005
Create Date: 2026-09-05
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260905_0006"
down_revision: Union[str, None] = "20260905_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("analysis_sessions_fps_check", "analysis_sessions", type_="check")
    op.create_check_constraint(
        "analysis_sessions_fps_check",
        "analysis_sessions",
        "sampling_fps between 3 and 15",
    )


def downgrade() -> None:
    op.execute("UPDATE analysis_sessions SET sampling_fps = 10 WHERE sampling_fps > 10")
    op.drop_constraint("analysis_sessions_fps_check", "analysis_sessions", type_="check")
    op.create_check_constraint(
        "analysis_sessions_fps_check",
        "analysis_sessions",
        "sampling_fps between 3 and 10",
    )
