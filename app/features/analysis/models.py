from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.database import Base


class AnalysisSession(Base):
    __tablename__ = "analysis_sessions"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    owner_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    video_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("videos.id", ondelete="CASCADE"), index=True)
    profile_id: Mapped[str] = mapped_column(String(80))
    profile_version: Mapped[str] = mapped_column(String(30))
    model: Mapped[str] = mapped_column(String(160))
    prompt_version: Mapped[str] = mapped_column(String(30), default="1.0")
    sampling_fps: Mapped[Decimal] = mapped_column(Numeric(8, 3))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    phase: Mapped[str] = mapped_column(String(40), default="queued")
    total_jobs: Mapped[int] = mapped_column(Integer, default=1)
    completed_jobs: Mapped[int] = mapped_column(Integer, default=0)
    failed_jobs: Mapped[int] = mapped_column(Integer, default=0)
    terminal_progress_percent: Mapped[int] = mapped_column(Integer, default=0)
    analysis_revision: Mapped[int] = mapped_column(Integer, default=1)
    capabilities: Mapped[dict] = mapped_column(JSON, default=dict)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AnalysisFrame(Base):
    __tablename__ = "analysis_frames"
    __table_args__ = (Index("ix_analysis_frames_session_time", "session_id", "timestamp_seconds"),)

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    session_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("analysis_sessions.id", ondelete="CASCADE"), index=True)
    asset_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("media_assets.id", ondelete="CASCADE"), unique=True)
    timestamp_seconds: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AnalysisObservation(Base):
    __tablename__ = "analysis_observations"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    session_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("analysis_sessions.id", ondelete="CASCADE"), index=True)
    frame_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("analysis_frames.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String(80))
    start_seconds: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    end_seconds: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    observation: Mapped[str] = mapped_column(Text)
    interpretation: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    importance: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=0)
    evidence_frame_ids: Mapped[list] = mapped_column(JSON, default=list)
    limitations: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ModelRequest(Base):
    __tablename__ = "model_requests"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    session_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("analysis_sessions.id", ondelete="CASCADE"), index=True)
    owner_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    task: Mapped[str] = mapped_column(String(80))
    provider_request_id: Mapped[str | None] = mapped_column(String(160))
    model: Mapped[str] = mapped_column(String(160))
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    total_tokens: Mapped[int | None] = mapped_column(Integer)
    cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 8))
    duration_ms: Mapped[int] = mapped_column(Integer)
    outcome: Mapped[str] = mapped_column(String(20))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
