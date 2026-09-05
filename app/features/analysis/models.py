"""Database models for storing video analysis sessions and model results."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.database import Base


class AnalysisSession(Base):
    """Represent a video analysis session and its overall execution state."""

    __tablename__ = "analysis_sessions"

    # -------------------------------------------------------------------------
    # Identity and ownership
    # -------------------------------------------------------------------------
    # Unique identifier of the analysis session.
    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )

    # User who owns and initiated this analysis.
    owner_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )

    # Video being analyzed by this session.
    video_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("videos.id", ondelete="CASCADE"),
        index=True,
    )

    # -------------------------------------------------------------------------
    # Analysis configuration
    # -------------------------------------------------------------------------
    # Analysis profile determines which capabilities/features should run.
    profile_id: Mapped[str] = mapped_column(String(80))

    # Version of the selected analysis profile.
    profile_version: Mapped[str] = mapped_column(String(30))

    # AI model used to perform the analysis.
    model: Mapped[str] = mapped_column(String(160))

    # Version of the prompt/template used with the model.
    prompt_version: Mapped[str] = mapped_column(String(30), default="1.0")

    # Number of video frames sampled per second for analysis.
    sampling_fps: Mapped[Decimal] = mapped_column(Numeric(8, 3))

    # -------------------------------------------------------------------------
    # Execution state
    # -------------------------------------------------------------------------
    # High-level lifecycle state, such as pending, processing, completed,
    # or failed.
    status: Mapped[str] = mapped_column(String(20), default="pending")

    # Current internal processing phase, such as queued, frame extraction,
    # model analysis, or report generation.
    phase: Mapped[str] = mapped_column(String(40), default="queued")

    # -------------------------------------------------------------------------
    # Job progress tracking
    # -------------------------------------------------------------------------
    # Total number of processing jobs created for this analysis.
    total_jobs: Mapped[int] = mapped_column(Integer, default=1)

    # Number of jobs successfully completed.
    completed_jobs: Mapped[int] = mapped_column(Integer, default=0)

    # Number of jobs that failed.
    failed_jobs: Mapped[int] = mapped_column(Integer, default=0)

    # Final/displayable progress percentage for the session.
    terminal_progress_percent: Mapped[int] = mapped_column(Integer, default=0)

    # -------------------------------------------------------------------------
    # Analysis versioning and output
    # -------------------------------------------------------------------------
    # Revision number used when analysis results are regenerated or updated.
    analysis_revision: Mapped[int] = mapped_column(Integer, default=1)

    # Capabilities enabled or available during this analysis.
    capabilities: Mapped[dict] = mapped_column(JSON, default=dict)

    # Final aggregated summary/result for the analysis session.
    summary: Mapped[dict] = mapped_column(JSON, default=dict)

    # Error details when the analysis fails.
    error: Mapped[str | None] = mapped_column(Text)

    # -------------------------------------------------------------------------
    # Timestamps
    # -------------------------------------------------------------------------
    # Time when the analysis session record was created.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    # Time when processing actually started.
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Time when processing finished successfully or terminally.
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AnalysisFrame(Base):
    """Represent a sampled video frame belonging to an analysis session."""

    __tablename__ = "analysis_frames"

    # Optimizes queries that retrieve frames for a session ordered or filtered
    # by their timestamp in the source video.
    __table_args__ = (
        Index(
            "ix_analysis_frames_session_time",
            "session_id",
            "timestamp_seconds",
        ),
    )

    # -------------------------------------------------------------------------
    # Identity and relationships
    # -------------------------------------------------------------------------
    # Unique identifier of this sampled frame.
    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )

    # Analysis session this frame belongs to.
    session_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("analysis_sessions.id", ondelete="CASCADE"),
        index=True,
    )

    # Stored media asset containing the actual extracted frame image.
    asset_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("media_assets.id", ondelete="CASCADE"),
        unique=True,
    )

    # -------------------------------------------------------------------------
    # Frame position and dimensions
    # -------------------------------------------------------------------------
    # Position of this frame in the original video, expressed in seconds.
    timestamp_seconds: Mapped[Decimal] = mapped_column(Numeric(12, 3))

    # Width of the extracted frame in pixels.
    width: Mapped[int] = mapped_column(Integer)

    # Height of the extracted frame in pixels.
    height: Mapped[int] = mapped_column(Integer)

    # -------------------------------------------------------------------------
    # Timestamps
    # -------------------------------------------------------------------------
    # Time when this frame record was created.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class AnalysisObservation(Base):
    """Represent an observation extracted from a frame during analysis."""

    __tablename__ = "analysis_observations"

    # -------------------------------------------------------------------------
    # Identity and relationships
    # -------------------------------------------------------------------------
    # Unique identifier of the observation.
    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )

    # Analysis session that produced this observation.
    session_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("analysis_sessions.id", ondelete="CASCADE"),
        index=True,
    )

    # Primary sampled frame associated with this observation.
    frame_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("analysis_frames.id", ondelete="CASCADE"),
    )

    # -------------------------------------------------------------------------
    # Observation classification and timing
    # -------------------------------------------------------------------------
    # Observation category/type, such as person, action, object, scene,
    # emotion, event, or other analysis-specific classification.
    type: Mapped[str] = mapped_column(String(80))

    # Start time of the observed event or evidence window.
    start_seconds: Mapped[Decimal] = mapped_column(Numeric(12, 3))

    # End time of the observed event or evidence window.
    end_seconds: Mapped[Decimal] = mapped_column(Numeric(12, 3))

    # -------------------------------------------------------------------------
    # Model-generated analysis
    # -------------------------------------------------------------------------
    # Direct factual description of what was observed.
    observation: Mapped[str] = mapped_column(Text)

    # Higher-level meaning or interpretation of the observation.
    interpretation: Mapped[str | None] = mapped_column(Text)

    # Model confidence in the observation, typically represented from 0 to 1.
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4))

    # Relative importance of this observation for the final analysis/report.
    importance: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=0)

    # -------------------------------------------------------------------------
    # Evidence and limitations
    # -------------------------------------------------------------------------
    # IDs of additional frames that support this observation.
    evidence_frame_ids: Mapped[list] = mapped_column(JSON, default=list)

    # Known uncertainty, visibility problems, ambiguity, or other limitations.
    limitations: Mapped[list] = mapped_column(JSON, default=list)

    # -------------------------------------------------------------------------
    # Timestamps
    # -------------------------------------------------------------------------
    # Time when this observation was stored.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class ModelRequest(Base):
    """Record metadata, usage, cost, and outcome for a model request."""

    __tablename__ = "model_requests"

    # -------------------------------------------------------------------------
    # Identity and relationships
    # -------------------------------------------------------------------------
    # Unique identifier of the model request.
    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )

    # Analysis session that initiated this model request.
    session_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("analysis_sessions.id", ondelete="CASCADE"),
        index=True,
    )

    # User responsible for the request and its usage/cost.
    owner_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )

    # -------------------------------------------------------------------------
    # Request configuration
    # -------------------------------------------------------------------------
    # Logical task performed by the request, such as frame analysis,
    # summarization, aggregation, or report generation.
    task: Mapped[str] = mapped_column(String(80))

    # Request identifier returned by the external AI provider.
    provider_request_id: Mapped[str | None] = mapped_column(String(160))

    # AI model used for this request.
    model: Mapped[str] = mapped_column(String(160))

    # -------------------------------------------------------------------------
    # Token usage
    # -------------------------------------------------------------------------
    # Number of tokens sent to the model.
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)

    # Number of tokens generated by the model.
    completion_tokens: Mapped[int | None] = mapped_column(Integer)

    # Combined prompt and completion token count.
    total_tokens: Mapped[int | None] = mapped_column(Integer)

    # -------------------------------------------------------------------------
    # Cost and performance
    # -------------------------------------------------------------------------
    # Monetary cost of this individual model request.
    cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 8))

    # Total request execution duration in milliseconds.
    duration_ms: Mapped[int] = mapped_column(Integer)

    # -------------------------------------------------------------------------
    # Request result
    # -------------------------------------------------------------------------
    # Final request outcome, such as success or failure.
    outcome: Mapped[str] = mapped_column(String(20))

    # Error details when the provider request fails.
    error: Mapped[str | None] = mapped_column(Text)

    # -------------------------------------------------------------------------
    # Timestamps
    # -------------------------------------------------------------------------
    # Time when this model request record was created.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )