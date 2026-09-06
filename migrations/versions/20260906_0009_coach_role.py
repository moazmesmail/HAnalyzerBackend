"""allow the coach user role

Revision ID: 20260906_0009
Revises: 20260906_0008
Create Date: 2026-09-06
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260906_0009"
down_revision: Union[str, None] = "20260906_0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("users_role_check", "users", type_="check")
    op.create_check_constraint(
        "users_role_check",
        "users",
        "role in ('user', 'coach', 'admin')",
    )


def downgrade() -> None:
    op.execute("UPDATE users SET role = 'user' WHERE role = 'coach'")
    op.drop_constraint("users_role_check", "users", type_="check")
    op.create_check_constraint(
        "users_role_check",
        "users",
        "role in ('user', 'admin')",
    )
