from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class CreateWorkspaceRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class UpdateWorkspaceRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class WorkspaceSummaryVideoResponse(BaseModel):
    id: UUID
    status: str
    asset_id: UUID | None = None
    duration_seconds: float | None = None
    error: str | None = None


class WorkspaceAnalysisResponse(BaseModel):
    session_id: UUID
    status: str
    summary_video: WorkspaceSummaryVideoResponse | None = None


class WorkspaceVideoResponse(BaseModel):
    id: UUID
    original_filename: str
    created_at: datetime
    duration_seconds: float | None = None
    preparation_status: str
    original_asset_id: UUID | None = None
    preview_asset_id: UUID | None = None
    analysis: WorkspaceAnalysisResponse | None = None


class WorkspaceResponse(BaseModel):
    id: UUID
    name: str
    created_at: datetime
    updated_at: datetime
    video_count: int


class WorkspaceDetailResponse(WorkspaceResponse):
    videos: list[WorkspaceVideoResponse]
