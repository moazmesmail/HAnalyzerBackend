import logging
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.features.analysis.models import AnalysisArtifact, AnalysisReport, AnalysisSession, SummaryVideo
from app.features.analysis.schemas import SummaryVideoResponse
from app.features.identity.models import User
from app.features.videos.models import MediaAsset, Video
from app.platform.config import Settings
from app.platform.database import SessionLocal
from app.platform.errors import ApiError
from app.platform.media.video import create_silent_summary
from app.platform.storage.service import resolve_private_path, summary_video_path

logger = logging.getLogger(__name__)

PRE_ROLL_SECONDS = 3.0
POST_ROLL_SECONDS = 5.0
MERGE_GAP_SECONDS = 1.0


def _response(item: SummaryVideo) -> SummaryVideoResponse:
    return SummaryVideoResponse(
        id=item.id,
        session_id=item.session_id,
        status=item.status,
        asset_id=item.asset_id,
        selected_segments=item.selected_segments,
        duration_seconds=float(item.duration_seconds) if item.duration_seconds is not None else None,
        analysis_revision=item.analysis_revision,
        error=item.error,
        created_at=item.created_at,
        started_at=item.started_at,
        completed_at=item.completed_at,
    )


def _owner_session(db: Session, owner_id: UUID, session_id: UUID) -> AnalysisSession:
    session = db.scalar(
        select(AnalysisSession).where(
            AnalysisSession.id == session_id, AnalysisSession.owner_id == owner_id
        )
    )
    if not session:
        raise ApiError(404, "ANALYSIS_NOT_FOUND", "Analysis was not found.")
    return session


def select_highlight_segments(
    artifacts: list[AnalysisArtifact], report: AnalysisReport | None, video_duration: float
) -> list[dict]:
    """Select clips with fixed rules so identical analysis data gives identical output."""
    del report  # Kept in the signature for compatibility with existing callers.
    candidates = []
    for artifact in artifacts:
        # Jump artifacts carry the model-selected start/end timestamps. Excluding
        # every other category prevents general competition footage entering the reel.
        if artifact.category != "jump":
            continue
        candidates.append((float(artifact.start_seconds), str(artifact.id), artifact))

    # Keep every detected jump and make ordering reproducible.
    selected = sorted(candidates, key=lambda item: (item[0], item[1]))
    intervals = [
        {
            "start_seconds": max(0.0, float(item.start_seconds) - PRE_ROLL_SECONDS),
            "end_seconds": min(video_duration, max(float(item.end_seconds), float(item.start_seconds)) + POST_ROLL_SECONDS),
            "artifact_ids": [str(item.id)],
            "titles": [item.title],
        }
        for _, _, item in selected
    ]
    intervals.sort(key=lambda item: (item["start_seconds"], item["end_seconds"]))

    merged: list[dict] = []
    for interval in intervals:
        if merged and interval["start_seconds"] <= merged[-1]["end_seconds"] + MERGE_GAP_SECONDS:
            merged[-1]["end_seconds"] = max(merged[-1]["end_seconds"], interval["end_seconds"])
            merged[-1]["artifact_ids"].extend(interval["artifact_ids"])
            merged[-1]["titles"].extend(interval["titles"])
        else:
            merged.append(interval)

    return merged


def start_summary_video(
    db: Session, owner: User, session_id: UUID, settings: Settings
) -> SummaryVideoResponse:
    session = _owner_session(db, owner.id, session_id)
    if session.status not in {"completed", "partial"}:
        raise ApiError(409, "ANALYSIS_NOT_READY", "The analysis must finish before creating a summary video.")

    video = db.get(Video, session.video_id)
    artifacts = list(db.scalars(select(AnalysisArtifact).where(AnalysisArtifact.session_id == session.id)))
    report = db.scalar(select(AnalysisReport).where(AnalysisReport.session_id == session.id))
    segments = select_highlight_segments(artifacts, report, float(video.duration_seconds or 0))
    if not segments:
        raise ApiError(422, "NO_HIGHLIGHTS", "No detected horse jumps were found.")

    existing = db.scalar(select(SummaryVideo).where(SummaryVideo.session_id == session.id))
    if existing and existing.status in {"pending", "processing"}:
        return _response(existing)
    if existing:
        existing.status = "pending"
        existing.selected_segments = segments
        existing.duration_seconds = sum(
            item["end_seconds"] - item["start_seconds"] for item in segments
        )
        existing.analysis_revision = session.analysis_revision
        existing.error = None
        existing.started_at = None
        existing.completed_at = None
        db.commit()
        db.refresh(existing)
        return _response(existing)

    summary = SummaryVideo(
        id=uuid4(),
        session_id=session.id,
        owner_id=owner.id,
        status="pending",
        selected_segments=segments,
        duration_seconds=sum(item["end_seconds"] - item["start_seconds"] for item in segments),
        analysis_revision=session.analysis_revision,
    )
    db.add(summary)
    db.commit()
    db.refresh(summary)
    return _response(summary)


def get_summary_video(db: Session, owner: User, session_id: UUID) -> SummaryVideoResponse:
    session = _owner_session(db, owner.id, session_id)
    summary = db.scalar(select(SummaryVideo).where(SummaryVideo.session_id == session.id))
    if not summary:
        raise ApiError(404, "SUMMARY_VIDEO_NOT_FOUND", "A summary video has not been created.")
    return _response(summary)


def run_summary_video(summary_id: UUID, settings: Settings) -> None:
    with SessionLocal() as db:
        summary = db.get(SummaryVideo, summary_id)
        if not summary or summary.status not in {"pending", "processing"}:
            return
        target = None
        try:
            summary.status = "processing"
            summary.started_at = datetime.now(UTC)
            db.commit()

            session = db.get(AnalysisSession, summary.session_id)
            video = db.get(Video, session.video_id)
            original = db.get(MediaAsset, video.original_asset_id)
            if not original:
                raise ApiError(409, "ORIGINAL_MEDIA_MISSING", "Original media is missing.")
            source = resolve_private_path(settings, original.relative_path)
            target = summary_video_path(settings, summary.owner_id, video.id, summary.id)
            create_silent_summary(source, target, summary.selected_segments)

            asset = db.get(MediaAsset, summary.asset_id) if summary.asset_id else None
            if asset:
                asset.relative_path = str(
                    target.resolve().relative_to(settings.storage_root.resolve())
                )
                asset.size_bytes = target.stat().st_size
                asset.checksum_sha256 = _sha256(target)
                asset.availability = "available"
            else:
                asset = MediaAsset(
                    id=uuid4(),
                    video_id=video.id,
                    owner_id=summary.owner_id,
                    kind="summary_video",
                    relative_path=str(target.resolve().relative_to(settings.storage_root.resolve())),
                    content_type="video/mp4",
                    size_bytes=target.stat().st_size,
                    checksum_sha256=_sha256(target),
                )
                db.add(asset)
                db.flush()
                summary.asset_id = asset.id
            summary.status = "completed"
            summary.completed_at = datetime.now(UTC)
            summary.error = None
            db.commit()
        except Exception as exc:
            logger.exception("summary_video_failed summary_id=%s", summary_id)
            db.rollback()
            failed = db.get(SummaryVideo, summary_id)
            if failed:
                failed.status = "failed"
                failed.error = exc.message if isinstance(exc, ApiError) else "Summary video generation failed."
                failed.completed_at = datetime.now(UTC)
                db.commit()
            if target:
                target.unlink(missing_ok=True)


def _sha256(path) -> str:
    import hashlib

    checksum = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()
