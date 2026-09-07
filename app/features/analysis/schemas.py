from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AnalysisProfileResponse(BaseModel):
    id: str
    version: str
    display_name: str
    description: str
    minimum_fps: float
    maximum_fps: float
    default_fps: float
    capabilities: dict[str, bool]


class StartAnalysisRequest(BaseModel):
    profile_id: str = "generic"
    sampling_fps: float = Field(default=3, ge=3, le=15)


class AnalysisSessionResponse(BaseModel):
    id: UUID
    video_id: UUID
    profile_id: str
    profile_version: str
    model: str
    prompt_version: str
    sampling_fps: float
    status: str
    phase: str
    total_jobs: int
    completed_jobs: int
    failed_jobs: int
    terminal_progress_percent: int
    analysis_revision: int
    capabilities: dict[str, bool]
    summary: dict
    error: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


class AnalysisFrameResponse(BaseModel):
    id: UUID
    asset_id: UUID
    timestamp_seconds: float
    width: int
    height: int


class AnalysisObservationResponse(BaseModel):
    id: UUID
    frame_id: UUID
    type: str
    start_seconds: float
    end_seconds: float
    observation: str
    interpretation: str | None = None
    confidence: float
    importance: float
    evidence_frame_ids: list[UUID]
    limitations: list[str]


class AnalysisResultsResponse(BaseModel):
    frames: list[AnalysisFrameResponse]
    observations: list[AnalysisObservationResponse]


class ObservationProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = Field(min_length=1, max_length=80)
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(ge=0)
    observation: str = Field(min_length=1, max_length=1000)
    interpretation: str | None = Field(default=None, max_length=1000)
    confidence: float = Field(ge=0, le=1)
    importance: float = Field(default=0.5, ge=0, le=1)
    evidence_frame_ids: list[UUID] = Field(min_length=1, max_length=8)
    limitations: list[str] = Field(default_factory=list, max_length=8)


class AnalysisBatchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=2000)
    observations: list[ObservationProposal] = Field(default_factory=list, max_length=3)
    domain_records: list["DomainRecordProposal"] = Field(default_factory=list, max_length=15)


DomainCategory = Literal[
    "segment",
    "participant",
    "run",
    "obstacle",
    "jump",
    "fault",
    "scoreboard",
    "assessment",
    "movement",
    "causal_hypothesis",
]


class DomainAttributes(BaseModel):
    """Stable union of allowed domain attributes; irrelevant fields stay null/absent."""

    model_config = ConfigDict(extra="forbid")

    segment_type: str | None = None
    description: str | None = None
    participant_type: str | None = None
    name: str | None = None
    rider_name: str | None = None
    horse_name: str | None = "Valentino"
    country: str | None = None
    team: str | None = None
    bib_number: str | None = None
    uniform_colors: list[str] | None = None
    horse_color: str | None = None
    identifying_features: list[str] | None = None
    starting_order: int | None = None
    official_faults: float | None = None
    official_time: str | None = None
    official_rank: int | None = None
    obstacle_number: str | None = None
    obstacle_type: str | None = None
    combination_label: str | None = None
    color: str | list[str] | None = None
    position: str | None = None
    approach_direction: str | None = None
    difficulty: str | None = None
    difficulty_reason: str | None = None
    jump_number: str | None = None
    approach: dict[str, Any] | None = None
    takeoff: dict[str, Any] | None = None
    airborne: dict[str, Any] | None = None
    landing: dict[str, Any] | None = None
    recovery: dict[str, Any] | None = None
    rail_contact: bool | None = None
    rail_down: bool | None = None
    refusal: bool | None = None
    event_type: str | None = None
    severity: str | None = None
    possible_causes: list[Any] | None = None
    official_consequence: str | None = None
    raw_text: str | None = None
    rank: int | None = None
    faults: float | None = None
    time: str | None = None
    team_score: str | None = None
    assessment_category: str | None = None
    balance: str | None = None
    control: str | None = None
    rhythm: str | None = None
    posture: str | None = None
    rein_control: str | None = None
    turn_efficiency: str | None = None
    landing_recovery: str | None = None
    synchronization: str | None = None
    strategy: str | None = None
    metrics: dict[str, Any] | None = None
    from_obstacle: str | None = None
    to_obstacle: str | None = None
    duration_seconds: float | None = None
    movement: str | None = None
    turn: str | None = None
    rhythm_change: str | None = None
    acceleration_change: str | None = None
    event: str | None = None
    consequence: str | None = None


class DomainRecordProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: DomainCategory
    subtype: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=200)
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(ge=0)
    observation: str = Field(min_length=1, max_length=1200)
    interpretation: str | None = Field(default=None, max_length=1200)
    attributes: DomainAttributes = Field(default_factory=DomainAttributes)
    confidence: float = Field(ge=0, le=1)
    importance: float = Field(default=0.5, ge=0, le=1)
    evidence_frame_ids: list[UUID] = Field(min_length=1, max_length=12)
    limitations: list[str] = Field(default_factory=list, max_length=8)


class AnalysisBatchJobResponse(BaseModel):
    id: UUID
    batch_number: int
    start_seconds: float
    end_seconds: float
    source_frame_count: int
    status: str
    attempt_count: int
    error_code: str | None = None
    error_message: str | None = None


class AnalysisArtifactResponse(BaseModel):
    id: UUID
    batch_job_id: UUID | None = None
    category: str
    subtype: str
    title: str
    start_seconds: float
    end_seconds: float
    observation: str
    interpretation: str | None = None
    attributes: dict[str, Any]
    confidence: float
    importance: float
    evidence_frame_ids: list[UUID]
    limitations: list[str]


class StructuredAnalysisResponse(BaseModel):
    batch_jobs: list[AnalysisBatchJobResponse]
    artifacts: list[AnalysisArtifactResponse]
    coverage: dict[str, Any]


class ModelUsageResponse(BaseModel):
    request_count: int
    successful_requests: int
    failed_requests: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    total_cost: float | None
    model: str


class AnalysisReportResponse(BaseModel):
    session_id: UUID
    status: str
    profile_id: str
    model: str
    report_status: str
    report_version: str
    content: dict[str, Any]
    limitations: list[str]


class SummaryVideoSegmentResponse(BaseModel):
    start_seconds: float
    end_seconds: float
    artifact_ids: list[UUID]
    titles: list[str]


class SummaryVideoResponse(BaseModel):
    id: UUID
    session_id: UUID
    status: str
    asset_id: UUID | None = None
    selected_segments: list[SummaryVideoSegmentResponse]
    duration_seconds: float | None = None
    analysis_revision: int
    error: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


class DeepReportProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    executive_summary: str = Field(min_length=1, max_length=4000)
    video_features: dict[str, Any] = Field(default_factory=dict)
    competition_context: dict[str, Any] = Field(default_factory=dict)
    key_moments: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    run_summaries: list[dict[str, Any]] = Field(default_factory=list, max_length=30)
    course_analysis: dict[str, Any] = Field(default_factory=dict)
    technique_analysis: dict[str, Any] = Field(default_factory=dict)
    synchronization_analysis: dict[str, Any] = Field(default_factory=dict)
    scoreboard_results: list[dict[str, Any]] = Field(default_factory=list, max_length=30)
    comparisons: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    causal_hypotheses: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    strengths: list[str] = Field(default_factory=list, max_length=20)
    weaknesses: list[str] = Field(default_factory=list, max_length=20)
    recommendations: list[str] = Field(default_factory=list, max_length=20)
    limitations: list[str] = Field(default_factory=list, max_length=30)
