from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.database import Base


class Video(Base):
    __tablename__ = "videos"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    owner_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    duration_seconds: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    preparation_status: Mapped[str] = mapped_column(String(20), default="uploaded")
    preparation_error: Mapped[str | None] = mapped_column(Text)
    preparation_retryable: Mapped[bool] = mapped_column(Boolean, default=False)
    original_asset_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), ForeignKey("media_assets.id"))
    preview_asset_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), ForeignKey("media_assets.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MediaAsset(Base):
    __tablename__ = "media_assets"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    video_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("videos.id", ondelete="CASCADE"), index=True)
    owner_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    relative_path: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64))
    availability: Mapped[str] = mapped_column(String(20), default="available")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
