"""replace email identity with username identity

Revision ID: 20260905_0004
Revises: 20260905_0003
Create Date: 2026-09-05
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260905_0004"
down_revision: Union[str, None] = "20260905_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("uq_users_email_normalized", "users", type_="unique")
    op.alter_column(
        "users",
        "email_normalized",
        new_column_name="identity_normalized",
        existing_type=sa.String(length=320),
        type_=sa.String(length=64),
        existing_nullable=False,
    )
    op.create_unique_constraint("uq_users_identity_normalized", "users", ["identity_normalized"])


def downgrade() -> None:
    op.drop_constraint("uq_users_identity_normalized", "users", type_="unique")
    op.alter_column(
        "users",
        "identity_normalized",
        new_column_name="email_normalized",
        existing_type=sa.String(length=64),
        type_=sa.String(length=320),
        existing_nullable=False,
    )
    op.create_unique_constraint("uq_users_email_normalized", "users", ["email_normalized"])
