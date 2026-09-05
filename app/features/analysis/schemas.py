from datetime import datetime
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
    observations: list[ObservationProposal] = Field(max_length=30)


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
    summary: dict
    findings: list[AnalysisObservationResponse]
    limitations: list[str]
