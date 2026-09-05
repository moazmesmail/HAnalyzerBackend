import hashlib
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.features.identity.models import User
from app.features.videos.models import MediaAsset, Video
from app.features.videos.repository import get_owner_media, get_owner_video, list_owner_videos
from app.features.videos.schemas import PaginatedVideos, VideoResponse
from app.platform.config import Settings
from app.platform.errors import ApiError
from app.platform.media.video import assert_no_audio_stream, create_silent_preview, probe_video
from app.platform.storage.service import preview_path, resolve_private_path, save_upload


def video_response(video: Video) -> VideoResponse:
    return VideoResponse(
        id=video.id,
        original_filename=video.original_filename,
        created_at=video.created_at,
        duration_seconds=float(video.duration_seconds) if video.duration_seconds is not None else None,
        preparation_status=video.preparation_status,
        preparation_error=video.preparation_error,
        preparation_retryable=video.preparation_retryable,
        preview_asset_id=video.preview_asset_id,
    )


async def create_video(db: Session, owner: User, upload: UploadFile, settings: Settings) -> VideoResponse:
    video_id = uuid4()
    original_asset_id = uuid4()
    stored_file = await save_upload(settings, upload, owner.id, video_id, original_asset_id)
    source_path = resolve_private_path(settings, stored_file.relative_path)
    metadata = probe_video(source_path)

    video = Video(
        id=video_id,
        owner_id=owner.id,
        original_filename=Path(upload.filename or "uploaded-video").name,
        duration_seconds=metadata.duration_seconds,
        preparation_status="uploaded",
    )
    original_asset = MediaAsset(
        id=original_asset_id,
        video_id=video_id,
        owner_id=owner.id,
        kind="original",
        relative_path=stored_file.relative_path,
        content_type=upload.content_type or "application/octet-stream",
        size_bytes=stored_file.size_bytes,
        checksum_sha256=stored_file.checksum_sha256,
    )
    db.add(video)
    db.flush()
    db.add(original_asset)
    db.flush()
    video.original_asset_id = original_asset.id
    db.commit()
    db.refresh(video)

    prepare_video_preview(db, video, settings)
    db.refresh(video)
    return video_response(video)


def prepare_video_preview(db: Session, video: Video, settings: Settings) -> None:
    if not video.original_asset_id:
        raise ApiError(409, "ORIGINAL_MEDIA_MISSING", "Original media is missing.")

    original_asset = db.get(MediaAsset, video.original_asset_id)
    if not original_asset:
        raise ApiError(409, "ORIGINAL_MEDIA_MISSING", "Original media is missing.")

    video.preparation_status = "preparing"
    video.preparation_error = None
    video.preparation_retryable = False
    db.commit()

    preview_asset_id = uuid4()
    source = resolve_private_path(settings, original_asset.relative_path)
    target = preview_path(settings, video.owner_id, video.id, preview_asset_id)

    try:
        create_silent_preview(source, target)
        assert_no_audio_stream(target)
    except ApiError as exc:
        video.preparation_status = "failed"
        video.preparation_error = exc.message
        video.preparation_retryable = True
        db.commit()
        return

    relative_path = target.resolve().relative_to(settings.storage_root.resolve())
    preview_asset = MediaAsset(
        id=preview_asset_id,
        video_id=video.id,
        owner_id=video.owner_id,
        kind="preview",
        relative_path=str(relative_path),
        content_type="video/mp4",
        size_bytes=target.stat().st_size,
        checksum_sha256=file_sha256(target),
    )
    db.add(preview_asset)
    db.flush()
    video.preview_asset_id = preview_asset.id
    video.preparation_status = "ready"
    video.preparation_error = None
    video.preparation_retryable = False
    db.commit()


def list_videos(db: Session, owner: User) -> PaginatedVideos:
    return PaginatedVideos(items=[video_response(video) for video in list_owner_videos(db, owner.id)])


def get_video_detail(db: Session, owner: User, video_id: UUID) -> VideoResponse:
    video = get_owner_video(db, owner.id, video_id)
    if not video:
        raise ApiError(404, "VIDEO_NOT_FOUND", "Video was not found.")
    return video_response(video)


def retry_preparation(db: Session, owner: User, video_id: UUID, settings: Settings) -> VideoResponse:
    video = get_owner_video(db, owner.id, video_id)
    if not video:
        raise ApiError(404, "VIDEO_NOT_FOUND", "Video was not found.")

    if video.preparation_status != "failed" or not video.preparation_retryable:
        raise ApiError(409, "PREPARATION_NOT_RETRYABLE", "Video preparation cannot be retried.")

    prepare_video_preview(db, video, settings)
    db.refresh(video)
    return video_response(video)


def get_media_path(db: Session, owner: User, asset_id: UUID, settings: Settings) -> tuple[Path, str]:
    asset = get_owner_media(db, owner.id, asset_id)
    if not asset:
        raise ApiError(404, "MEDIA_NOT_FOUND", "Media was not found.")

    path = resolve_private_path(settings, asset.relative_path)
    if not path.exists():
        raise ApiError(404, "MEDIA_UNAVAILABLE", "Media is unavailable.")

    return path, asset.content_type


def file_sha256(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as input_file:
        for chunk in iter(lambda: input_file.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()
