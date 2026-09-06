import hashlib
import shutil
from pathlib import Path
from uuid import UUID

from fastapi import UploadFile

from app.platform.config import Settings
from app.platform.errors import ApiError


class StoredFile:
    def __init__(self, relative_path: str, size_bytes: int, checksum_sha256: str):
        self.relative_path = relative_path
        self.size_bytes = size_bytes
        self.checksum_sha256 = checksum_sha256


def user_video_dir(settings: Settings, user_id: UUID, video_id: UUID) -> Path:
    return settings.storage_root / "users" / str(user_id) / "videos" / str(video_id)


def resolve_private_path(settings: Settings, relative_path: str) -> Path:
    root = settings.storage_root.resolve()
    candidate = (root / relative_path).resolve()

    if root not in candidate.parents and candidate != root:
        raise ApiError(400, "INVALID_MEDIA_PATH", "Invalid media path.")

    return candidate


async def save_upload(
    settings: Settings,
    upload: UploadFile,
    user_id: UUID,
    video_id: UUID,
    asset_id: UUID,
) -> StoredFile:
    suffix = Path(upload.filename or "video").suffix.lower() or ".mp4"
    target_dir = user_video_dir(settings, user_id, video_id) / "original"
    target_dir.mkdir(parents=True, exist_ok=True)
    temporary_dir = settings.storage_root / "temporary"
    temporary_dir.mkdir(parents=True, exist_ok=True)
    temporary_path = temporary_dir / f"{asset_id}.upload"
    target_path = target_dir / f"{asset_id}{suffix}"

    size = 0
    checksum = hashlib.sha256()

    with temporary_path.open("wb") as output:
        while chunk := await upload.read(1024 * 1024):
            size += len(chunk)
            if size > settings.upload_max_bytes:
                temporary_path.unlink(missing_ok=True)
                raise ApiError(413, "UPLOAD_TOO_LARGE", "Upload is larger than the configured limit.")
            checksum.update(chunk)
            output.write(chunk)

    shutil.move(str(temporary_path), target_path)
    relative_path = target_path.resolve().relative_to(settings.storage_root.resolve())
    return StoredFile(str(relative_path), size, checksum.hexdigest())


def preview_path(settings: Settings, user_id: UUID, video_id: UUID, asset_id: UUID) -> Path:
    target_dir = user_video_dir(settings, user_id, video_id) / "preview"
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir / f"{asset_id}.mp4"


def summary_video_path(
    settings: Settings, user_id: UUID, video_id: UUID, summary_video_id: UUID
) -> Path:
    target_dir = user_video_dir(settings, user_id, video_id) / "summaries"
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir / f"{summary_video_id}.mp4"


def analysis_frames_dir(
    settings: Settings, user_id: UUID, video_id: UUID, analysis_session_id: UUID
) -> Path:
    target = (
        user_video_dir(settings, user_id, video_id)
        / "analyses"
        / str(analysis_session_id)
        / "frames"
    )
    target.mkdir(parents=True, exist_ok=True)
    return target
