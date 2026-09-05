"""AI analysis configuration and usage accounting

Revision ID: 20260905_0003
Revises: 20260905_0002
Create Date: 2026-09-05
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260905_0003"
down_revision: Union[str, None] = "20260905_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "analysis_sessions",
        sa.Column(
            "model",
            sa.String(length=160),
            server_default="qwen/qwen3-vl-32b-instruct",
            nullable=False,
        ),
    )
    op.add_column(
        "analysis_sessions",
        sa.Column("prompt_version", sa.String(length=30), server_default="1.0", nullable=False),
    )
    op.add_column(
        "analysis_sessions",
        sa.Column("summary", sa.JSON(), server_default=sa.text("'{}'::json"), nullable=False),
    )
    op.add_column(
        "analysis_observations",
        sa.Column(
            "evidence_frame_ids",
            sa.JSON(),
            server_default=sa.text("'[]'::json"),
            nullable=False,
        ),
    )

    op.create_table(
        "model_requests",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("task", sa.String(length=80), nullable=False),
        sa.Column("provider_request_id", sa.String(length=160), nullable=True),
        sa.Column("model", sa.String(length=160), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("cost", sa.Numeric(14, 8), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["analysis_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("outcome in ('completed', 'failed')", name="model_requests_outcome_check"),
    )
    op.create_index("ix_model_requests_owner_id", "model_requests", ["owner_id"])
    op.create_index("ix_model_requests_session_id", "model_requests", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_model_requests_session_id", table_name="model_requests")
    op.drop_index("ix_model_requests_owner_id", table_name="model_requests")
    op.drop_table("model_requests")
    op.drop_column("analysis_observations", "evidence_frame_ids")
    op.drop_column("analysis_sessions", "summary")
    op.drop_column("analysis_sessions", "prompt_version")
    op.drop_column("analysis_sessions", "model")
