"""structured domain analysis and deep reports

Revision ID: 20260906_0007
Revises: 20260905_0006
Create Date: 2026-09-06
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260906_0007"
down_revision: Union[str, None] = "20260905_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "analysis_batch_jobs",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("batch_number", sa.Integer(), nullable=False),
        sa.Column("start_seconds", sa.Numeric(12, 3), nullable=False),
        sa.Column("end_seconds", sa.Numeric(12, 3), nullable=False),
        sa.Column("source_frame_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["analysis_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "batch_number"),
        sa.CheckConstraint("status in ('pending', 'running', 'completed', 'failed', 'skipped')", name="analysis_batch_jobs_status_check"),
    )
    op.create_index("ix_analysis_batch_jobs_session_id", "analysis_batch_jobs", ["session_id"])

    op.create_table(
        "analysis_artifacts",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("batch_job_id", sa.Uuid(), nullable=True),
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column("subtype", sa.String(80), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("start_seconds", sa.Numeric(12, 3), nullable=False),
        sa.Column("end_seconds", sa.Numeric(12, 3), nullable=False),
        sa.Column("observation", sa.Text(), nullable=False),
        sa.Column("interpretation", sa.Text(), nullable=True),
        sa.Column("attributes", sa.JSON(), server_default=sa.text("'{}'::json"), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column("importance", sa.Numeric(5, 4), server_default="0", nullable=False),
        sa.Column("evidence_frame_ids", sa.JSON(), server_default=sa.text("'[]'::json"), nullable=False),
        sa.Column("limitations", sa.JSON(), server_default=sa.text("'[]'::json"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["batch_job_id"], ["analysis_batch_jobs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["session_id"], ["analysis_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("confidence between 0 and 1", name="analysis_artifacts_confidence_check"),
        sa.CheckConstraint("importance between 0 and 1", name="analysis_artifacts_importance_check"),
        sa.CheckConstraint("end_seconds >= start_seconds", name="analysis_artifacts_time_check"),
    )
    op.create_index("ix_analysis_artifacts_session_id", "analysis_artifacts", ["session_id"])
    op.create_index("ix_analysis_artifacts_session_category_time", "analysis_artifacts", ["session_id", "category", "start_seconds"])

    op.create_table(
        "analysis_reports",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.String(30), server_default="2.0", nullable=False),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("content", sa.JSON(), server_default=sa.text("'{}'::json"), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["analysis_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id"),
        sa.CheckConstraint("status in ('pending', 'completed', 'partial', 'failed')", name="analysis_reports_status_check"),
    )
    op.create_index("ix_analysis_reports_session_id", "analysis_reports", ["session_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_analysis_reports_session_id", table_name="analysis_reports")
    op.drop_table("analysis_reports")
    op.drop_index("ix_analysis_artifacts_session_category_time", table_name="analysis_artifacts")
    op.drop_index("ix_analysis_artifacts_session_id", table_name="analysis_artifacts")
    op.drop_table("analysis_artifacts")
    op.drop_index("ix_analysis_batch_jobs_session_id", table_name="analysis_batch_jobs")
    op.drop_table("analysis_batch_jobs")
