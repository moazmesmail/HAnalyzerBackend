from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.features.videos.models import MediaAsset, Video


def list_owner_videos(db: Session, owner_id: UUID, archived: bool = False, limit: int = 50) -> list[Video]:
    return list(
        db.scalars(
            select(Video)
            .where(Video.owner_id == owner_id, Video.archived_at.is_not(None) if archived else Video.archived_at.is_(None))
            .order_by(Video.created_at.desc())
            .limit(limit)
        )
    )


def get_owner_video(db: Session, owner_id: UUID, video_id: UUID) -> Video | None:
    return db.scalar(select(Video).where(Video.id == video_id, Video.owner_id == owner_id))


def get_owner_media(db: Session, owner_id: UUID, asset_id: UUID) -> MediaAsset | None:
    return db.scalar(
        select(MediaAsset).where(
            MediaAsset.id == asset_id,
            MediaAsset.owner_id == owner_id,
            MediaAsset.availability == "available",
        )
    )
