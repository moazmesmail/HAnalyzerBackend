from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.features.identity.dependencies import csrf_protect, require_approved_user
from app.features.identity.models import User
from app.features.videos.schemas import PaginatedVideos, VideoResponse
from app.features.videos.service import (
    create_video,
    get_media_path,
    get_video_detail,
    list_videos,
    retry_preparation,
)
from app.platform.config import Settings, get_settings
from app.platform.database import get_db

router = APIRouter(tags=["videos"])


@router.post("/videos", response_model=VideoResponse, status_code=201, dependencies=[Depends(csrf_protect)])
async def upload_video_route(
    owner: Annotated[User, Depends(require_approved_user)],
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    file: UploadFile = File(...),
) -> VideoResponse:
    return await create_video(db, owner, file, settings)


@router.get("/videos", response_model=PaginatedVideos)
def list_videos_route(
    owner: Annotated[User, Depends(require_approved_user)],
    db: Annotated[Session, Depends(get_db)],
) -> PaginatedVideos:
    return list_videos(db, owner)


@router.get("/videos/{video_id}", response_model=VideoResponse)
def get_video_route(
    video_id: UUID,
    owner: Annotated[User, Depends(require_approved_user)],
    db: Annotated[Session, Depends(get_db)],
) -> VideoResponse:
    return get_video_detail(db, owner, video_id)


@router.post(
    "/videos/{video_id}/retry-preparation",
    response_model=VideoResponse,
    dependencies=[Depends(csrf_protect)],
)
def retry_preparation_route(
    video_id: UUID,
    owner: Annotated[User, Depends(require_approved_user)],
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> VideoResponse:
    return retry_preparation(db, owner, video_id, settings)


@router.get("/media/{asset_id}")
def get_media_route(
    asset_id: UUID,
    owner: Annotated[User, Depends(require_approved_user)],
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> FileResponse:
    path, content_type = get_media_path(db, owner, asset_id, settings)
    return FileResponse(path, media_type=content_type)


@router.head("/media/{asset_id}")
def head_media_route(
    asset_id: UUID,
    owner: Annotated[User, Depends(require_approved_user)],
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> FileResponse:
    path, content_type = get_media_path(db, owner, asset_id, settings)
    return FileResponse(path, media_type=content_type)
