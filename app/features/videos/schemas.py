from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class VideoResponse(BaseModel):
    id: UUID
    original_filename: str
    created_at: datetime
    duration_seconds: float | None = None
    preparation_status: str
    preparation_error: str | None = None
    preparation_retryable: bool = False
    original_asset_id: UUID | None = None
    preview_asset_id: UUID | None = None


class PaginatedVideos(BaseModel):
    items: list[VideoResponse]
    next_cursor: str | None = None
