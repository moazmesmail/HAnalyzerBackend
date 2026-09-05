import hashlib
import logging
import shutil
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from pydantic import ValidationError

from app.features.analysis.models import AnalysisFrame, AnalysisObservation, AnalysisSession, ModelRequest
from app.features.analysis.profiles import PROFILES
from app.features.analysis.repository import (
    get_owner_session,
    list_frames,
    list_model_requests,
    list_observations,
    list_video_sessions,
)
from app.features.analysis.schemas import (
    AnalysisBatchResult,
    AnalysisFrameResponse,
    AnalysisObservationResponse,
    AnalysisReportResponse,
    AnalysisResultsResponse,
    AnalysisSessionResponse,
    ModelUsageResponse,
    ObservationProposal,
    StartAnalysisRequest,
)
from app.features.identity.models import User
from app.features.videos.models import MediaAsset, Video
from app.features.videos.repository import get_owner_video
from app.platform.config import Settings
from app.platform.database import SessionLocal
from app.platform.errors import ApiError
from app.platform.media.video import extract_sampled_frames, probe_image_dimensions
from app.platform.ai.openrouter import ProviderUsage, analyze_images
from app.platform.storage.service import analysis_frames_dir, resolve_private_path

logger = logging.getLogger(__name__)


def session_response(session: AnalysisSession) -> AnalysisSessionResponse:
    return AnalysisSessionResponse(
        id=session.id,
        video_id=session.video_id,
        profile_id=session.profile_id,
        profile_version=session.profile_version,
        model=session.model,
        prompt_version=session.prompt_version,
        sampling_fps=float(session.sampling_fps),
        status=session.status,
        phase=session.phase,
        total_jobs=session.total_jobs,
        completed_jobs=session.completed_jobs,
        failed_jobs=session.failed_jobs,
        terminal_progress_percent=session.terminal_progress_percent,
        analysis_revision=session.analysis_revision,
        capabilities=session.capabilities,
        summary=session.summary,
        error=session.error,
        created_at=session.created_at,
        started_at=session.started_at,
        completed_at=session.completed_at,
    )


def start_analysis(
    db: Session,
    owner: User,
    video_id: UUID,
    request: StartAnalysisRequest,
    settings: Settings,
) -> AnalysisSessionResponse:
    video = get_owner_video(db, owner.id, video_id)
    if not video:
        raise ApiError(404, "VIDEO_NOT_FOUND", "Video was not found.")
    if not video.original_asset_id:
        raise ApiError(409, "ORIGINAL_MEDIA_MISSING", "Original media is missing.")
    if video.duration_seconds is None or float(video.duration_seconds) >= settings.video_max_duration_seconds:
        raise ApiError(
            422,
            "VIDEO_TOO_LONG",
            "Only videos under 2 minutes can be analyzed.",
        )

    profile = PROFILES.get(request.profile_id)
    if not profile:
        raise ApiError(422, "ANALYSIS_PROFILE_INVALID", "The selected analysis profile is unavailable.")

    active = db.scalar(
        select(AnalysisSession).where(
            AnalysisSession.owner_id == owner.id,
            AnalysisSession.video_id == video_id,
            AnalysisSession.status.in_(("pending", "running")),
        )
    )
    if active:
        if active.profile_id == request.profile_id and float(active.sampling_fps) == request.sampling_fps:
            return session_response(active)
        raise ApiError(409, "ANALYSIS_ALREADY_ACTIVE", "This video already has an active analysis with different settings.")

    if video.duration_seconds and float(video.duration_seconds) * request.sampling_fps > 1200:
        raise ApiError(422, "TOO_MANY_ANALYSIS_FRAMES", "Choose a lower frame rate; an analysis is limited to 1,200 frames.")

    session = AnalysisSession(
        id=uuid4(),
        owner_id=owner.id,
        video_id=video.id,
        profile_id=profile.id,
        profile_version=profile.version,
        model=settings.openrouter_model,
        prompt_version="1.0",
        sampling_fps=request.sampling_fps,
        status="pending",
        phase="queued",
        capabilities=profile.capabilities,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session_response(session)


def run_analysis(session_id: UUID, settings: Settings) -> None:
    try:
        _run_analysis(session_id, settings)
    except Exception as exc:
        logger.exception(
            "analysis_unhandled_failure session_id=%s error_type=%s",
            session_id,
            type(exc).__name__,
        )
        with SessionLocal() as db:
            db.rollback()
            session = db.get(AnalysisSession, session_id)
            if session and session.status in ("pending", "running"):
                has_evidence = bool(list_frames(db, session.id))
                session.status = "partial" if has_evidence else "failed"
                session.phase = "failed"
                session.terminal_progress_percent = 100
                session.error = (
                    "Analysis stopped because of an unexpected pipeline error. "
                    f"Check backend logs using session {session_id}."
                )
                session.completed_at = datetime.now(UTC)
                db.commit()


def _run_analysis(session_id: UUID, settings: Settings) -> None:
    with SessionLocal() as db:
        session = db.get(AnalysisSession, session_id)
        if not session or session.status != "pending":
            return
        session.status = "running"
        session.phase = "extracting_frames"
        session.started_at = datetime.now(UTC)
        session.terminal_progress_percent = 10
        session.error = None
        db.commit()
        logger.info(
            "analysis_started session_id=%s video_id=%s profile=%s model=%s sampling_fps=%s",
            session.id,
            session.video_id,
            session.profile_id,
            session.model,
            session.sampling_fps,
        )

        output_dir: Path | None = None
        stage = "loading_source"
        try:
            video = db.get(Video, session.video_id)
            original = db.get(MediaAsset, video.original_asset_id) if video and video.original_asset_id else None
            if not video or not original:
                raise ApiError(409, "ORIGINAL_MEDIA_MISSING", "Original media is missing.")

            source = resolve_private_path(settings, original.relative_path)
            output_dir = analysis_frames_dir(settings, session.owner_id, session.video_id, session.id)
            stage = "extracting_frames"
            logger.info("analysis_stage_started session_id=%s stage=%s", session.id, stage)
            extracted = extract_sampled_frames(
                source, output_dir, float(session.sampling_fps), 1200
            )
            logger.info(
                "analysis_stage_completed session_id=%s stage=%s frame_count=%d",
                session.id,
                stage,
                len(extracted),
            )
            stage = "probing_frames"
            width, height = probe_image_dimensions(extracted[0].path)

            frame_paths: dict[UUID, Path] = {}
            stage = "persisting_frames"
            logger.info("analysis_stage_started session_id=%s stage=%s", session.id, stage)
            for extracted_frame in extracted:
                asset_id = uuid4()
                relative_path = extracted_frame.path.resolve().relative_to(settings.storage_root.resolve())
                asset = MediaAsset(
                    id=asset_id,
                    video_id=session.video_id,
                    owner_id=session.owner_id,
                    kind="analysis_frame",
                    relative_path=str(relative_path),
                    content_type="image/jpeg",
                    size_bytes=extracted_frame.path.stat().st_size,
                    checksum_sha256=_sha256(extracted_frame.path),
                )
                frame = AnalysisFrame(
                    id=uuid4(),
                    session_id=session.id,
                    asset_id=asset_id,
                    timestamp_seconds=extracted_frame.timestamp_seconds,
                    width=width,
                    height=height,
                )
                frame_paths[frame.id] = extracted_frame.path
                # Flush the asset first because videos and media_assets have a foreign-key cycle;
                # SQLAlchemy cannot reliably infer this insert order when a frame is also pending.
                db.add(asset)
                db.flush()
                db.add(frame)

            db.flush()
            frames = list_frames(db, session.id)
            batches = [frames[index : index + 8] for index in range(0, len(frames), 8)]
            session.phase = "analyzing_frames"
            session.total_jobs = 1 + len(batches)
            session.completed_jobs = 1
            session.terminal_progress_percent = 30
            db.commit()
            logger.info(
                "analysis_stage_completed session_id=%s stage=%s frame_count=%d batch_count=%d",
                session.id,
                stage,
                len(frames),
                len(batches),
            )
        except Exception as exc:
            logger.exception(
                "analysis_stage_failed session_id=%s stage=%s error_type=%s",
                session_id,
                stage,
                type(exc).__name__,
            )
            db.rollback()
            failed = db.get(AnalysisSession, session_id)
            if failed:
                failed.status = "failed"
                failed.phase = "failed"
                failed.failed_jobs = 1
                failed.terminal_progress_percent = 100
                failed.error = (
                    exc.message
                    if isinstance(exc, ApiError)
                    else f"Analysis failed during {stage.replace('_', ' ')}. Check backend logs using session {session_id}."
                )
                failed.completed_at = datetime.now(UTC)
                db.commit()
            if output_dir:
                shutil.rmtree(output_dir, ignore_errors=True)
            return

        summaries: list[str] = []
        successful_batches = 0
        failed_batches = 0
        skipped_batches = 0
        for batch_number, batch in enumerate(batches, start=1):
            stop_provider_batches = False
            response = None
            session = db.get(AnalysisSession, session_id)
            session.phase = f"analyzing_batch_{batch_number}_of_{len(batches)}"
            session.terminal_progress_percent = 30 + round(
                70 * (batch_number - 0.5) / len(batches)
            )
            db.commit()
            logger.info(
                "analysis_batch_started session_id=%s batch=%d total_batches=%d frame_count=%d",
                session.id,
                batch_number,
                len(batches),
                len(batch),
            )
            try:
                response = analyze_images(
                    settings,
                    _analysis_prompt(session.profile_id),
                    [frame_paths[frame.id] for frame in batch],
                    AnalysisBatchResult.model_json_schema(),
                    image_labels=[
                        f"Frame {index + 1}: frame_id={frame.id}, "
                        f"timestamp={float(frame.timestamp_seconds):.3f}s"
                        for index, frame in enumerate(batch)
                    ],
                )
                result, structurally_dropped = _validate_batch_result(
                    response.content, session.id, batch_number
                )
                stored_observations, evidence_dropped = _store_batch_result(
                    db, session, batch, result, batch_number
                )
                _store_usage(db, session, response.usage, "completed", None)
                session = db.get(AnalysisSession, session_id)
                session.completed_jobs = 2 + successful_batches
                session.failed_jobs = failed_batches
                session.terminal_progress_percent = 30 + round(70 * batch_number / len(batches))
                db.commit()
                successful_batches += 1
                summaries.append(result.summary)
                logger.info(
                    "analysis_batch_completed session_id=%s batch=%d observations=%d dropped_observations=%d provider_request_id=%s",
                    session.id,
                    batch_number,
                    stored_observations,
                    structurally_dropped + evidence_dropped,
                    response.usage.provider_request_id,
                )
            except Exception as exc:
                if isinstance(exc, (ApiError, ValidationError, ValueError)):
                    logger.warning(
                        "analysis_batch_failed session_id=%s batch=%d error_type=%s error=%s",
                        session.id,
                        batch_number,
                        type(exc).__name__,
                        (
                            exc.message if isinstance(exc, ApiError) else str(exc)
                        ).replace("\n", " ")[:1000],
                    )
                else:
                    logger.exception(
                        "analysis_batch_failed session_id=%s batch=%d error_type=%s",
                        session.id,
                        batch_number,
                        type(exc).__name__,
                    )
                db.rollback()
                session = db.get(AnalysisSession, session_id)
                if isinstance(exc, ApiError):
                    message = exc.message
                elif isinstance(exc, (ValidationError, ValueError)):
                    message = "The model returned results that failed validation."
                else:
                    message = "The analysis result could not be saved."
                _store_usage(db, session, response.usage if response else None, "failed", message)
                failed_batches += 1
                stop_provider_batches = (
                    isinstance(exc, ApiError)
                    and exc.code in {"AI_NOT_CONFIGURED", "AI_AUTHENTICATION_FAILED"}
                ) or not isinstance(exc, (ApiError, ValidationError, ValueError))
                session.completed_jobs = 1 + successful_batches
                session.failed_jobs = failed_batches
                session.terminal_progress_percent = 30 + round(70 * batch_number / len(batches))
                db.commit()
            if stop_provider_batches:
                skipped_batches = len(batches) - batch_number
                logger.error(
                    "analysis_provider_aborted session_id=%s skipped_batches=%d",
                    session.id,
                    skipped_batches,
                )
                break

        session = db.get(AnalysisSession, session_id)
        session.summary = {
            "overview": " ".join(summaries),
            "frame_count": len(frames),
            "successful_batches": successful_batches,
            "failed_batches": failed_batches,
            "skipped_batches": skipped_batches,
        }
        session.status = "completed" if failed_batches == 0 else "partial"
        session.phase = "completed" if failed_batches == 0 else "partial"
        session.terminal_progress_percent = 100
        session.completed_at = datetime.now(UTC)
        session.error = (
            None
            if failed_batches == 0
            else f"{failed_batches} visual analysis batch failed; {skipped_batches} remaining batches were skipped."
        )
        db.commit()
        logger.info(
            "analysis_completed session_id=%s status=%s successful_batches=%d failed_batches=%d",
            session.id,
            session.status,
            successful_batches,
            failed_batches,
        )


def recover_interrupted_analyses() -> None:
    with SessionLocal() as db:
        interrupted = list(
            db.scalars(
                select(AnalysisSession).where(
                    AnalysisSession.status.in_(("pending", "running"))
                )
            )
        )
        for session in interrupted:
            frame_count = len(list_frames(db, session.id))
            session.status = "partial" if frame_count else "failed"
            session.phase = "interrupted"
            session.terminal_progress_percent = 100
            session.completed_at = datetime.now(UTC)
            session.error = (
                "Analysis was interrupted by a backend restart. Extracted evidence remains available; retry to continue."
                if frame_count
                else "Analysis was interrupted before evidence extraction completed. Retry the analysis."
            )
            logger.warning(
                "analysis_recovered_after_restart session_id=%s status=%s frame_count=%d",
                session.id,
                session.status,
                frame_count,
            )
        if interrupted:
            db.commit()


def get_session(db: Session, owner: User, session_id: UUID) -> AnalysisSessionResponse:
    session = get_owner_session(db, owner.id, session_id)
    if not session:
        raise ApiError(404, "ANALYSIS_NOT_FOUND", "Analysis was not found.")
    return session_response(session)


def retry_analysis(
    db: Session, owner: User, session_id: UUID, settings: Settings
) -> AnalysisSessionResponse:
    previous = get_owner_session(db, owner.id, session_id)
    if not previous:
        raise ApiError(404, "ANALYSIS_NOT_FOUND", "Analysis was not found.")
    if previous.status not in ("failed", "partial"):
        raise ApiError(409, "ANALYSIS_NOT_RETRYABLE", "Only failed or partial analyses can be retried.")
    active = db.scalar(
        select(AnalysisSession).where(
            AnalysisSession.owner_id == owner.id,
            AnalysisSession.video_id == previous.video_id,
            AnalysisSession.status.in_(("pending", "running")),
        )
    )
    if active:
        return session_response(active)
    retry = AnalysisSession(
        id=uuid4(),
        owner_id=owner.id,
        video_id=previous.video_id,
        profile_id=previous.profile_id,
        profile_version=previous.profile_version,
        model=settings.openrouter_model,
        prompt_version="1.0",
        sampling_fps=previous.sampling_fps,
        status="pending",
        phase="queued",
        analysis_revision=previous.analysis_revision + 1,
        capabilities=previous.capabilities,
    )
    db.add(retry)
    db.commit()
    db.refresh(retry)
    return session_response(retry)


def get_video_sessions(db: Session, owner: User, video_id: UUID) -> list[AnalysisSessionResponse]:
    if not get_owner_video(db, owner.id, video_id):
        raise ApiError(404, "VIDEO_NOT_FOUND", "Video was not found.")
    return [session_response(item) for item in list_video_sessions(db, owner.id, video_id)]


def get_results(db: Session, owner: User, session_id: UUID) -> AnalysisResultsResponse:
    session = get_owner_session(db, owner.id, session_id)
    if not session:
        raise ApiError(404, "ANALYSIS_NOT_FOUND", "Analysis was not found.")
    frames = [
        AnalysisFrameResponse(
            id=item.id,
            asset_id=item.asset_id,
            timestamp_seconds=float(item.timestamp_seconds),
            width=item.width,
            height=item.height,
        )
        for item in list_frames(db, session.id)
    ]
    observations = [
        AnalysisObservationResponse(
            id=item.id,
            frame_id=item.frame_id,
            type=item.type,
            start_seconds=float(item.start_seconds),
            end_seconds=float(item.end_seconds),
            observation=item.observation,
            interpretation=item.interpretation,
            confidence=float(item.confidence),
            importance=float(item.importance),
            evidence_frame_ids=item.evidence_frame_ids,
            limitations=item.limitations,
        )
        for item in list_observations(db, session.id)
    ]
    return AnalysisResultsResponse(frames=frames, observations=observations)


def get_usage(db: Session, owner: User, session_id: UUID) -> ModelUsageResponse:
    session = get_owner_session(db, owner.id, session_id)
    if not session:
        raise ApiError(404, "ANALYSIS_NOT_FOUND", "Analysis was not found.")
    requests = list_model_requests(db, session.id)
    known_costs = [float(item.cost) for item in requests if item.cost is not None]
    return ModelUsageResponse(
        request_count=len(requests),
        successful_requests=sum(item.outcome == "completed" for item in requests),
        failed_requests=sum(item.outcome == "failed" for item in requests),
        prompt_tokens=sum(item.prompt_tokens or 0 for item in requests),
        completion_tokens=sum(item.completion_tokens or 0 for item in requests),
        total_tokens=sum(item.total_tokens or 0 for item in requests),
        total_cost=sum(known_costs) if known_costs else None,
        model=session.model,
    )


def get_report(db: Session, owner: User, session_id: UUID) -> AnalysisReportResponse:
    session = get_owner_session(db, owner.id, session_id)
    if not session:
        raise ApiError(404, "ANALYSIS_NOT_FOUND", "Analysis was not found.")
    observations = [_observation_response(item) for item in list_observations(db, session.id)]
    limitations = []
    if session.status == "partial":
        limitations.append(session.error or "Some analysis batches did not complete.")
    if not observations:
        limitations.append("No visually supported semantic findings were produced.")
    return AnalysisReportResponse(
        session_id=session.id,
        status=session.status,
        profile_id=session.profile_id,
        model=session.model,
        summary=session.summary,
        findings=sorted(observations, key=lambda item: item.importance, reverse=True),
        limitations=limitations,
    )


def _analysis_prompt(profile_id: str) -> str:
    profile_instruction = (
        "Focus on riders, horses, competition runs, obstacle numbers, approach, takeoff, "
        "clearance, landing, recovery, rail contact, refusal, run-out, falls, visible technique, "
        "and displayed official results. Keep official displayed values separate from inferred events."
        if profile_id == "equestrian_show_jumping"
        else "Identify visible subjects, actions, scene changes, readable text, and notable events."
    )
    return f"""Analyze these silent video frames in chronological order.
{profile_instruction}

Use only details visible in the supplied images. Do not infer from audio. Every observation must
reference one or more supplied frame_id values and use timestamps within this batch. Separate a
directly visible observation from any interpretation. Use null when no interpretation is justified.
Treat confidence as confidence in the visible claim, not a calibrated probability. Do not claim an
event was absent merely because sampled frames did not show it. Return concise, non-duplicate findings.
"""


def _store_batch_result(
    db: Session,
    session: AnalysisSession,
    batch: list[AnalysisFrame],
    result: AnalysisBatchResult,
    batch_number: int,
) -> tuple[int, int]:
    frame_by_id = {frame.id: frame for frame in batch}
    minimum_time = min(float(frame.timestamp_seconds) for frame in batch)
    maximum_time = max(float(frame.timestamp_seconds) for frame in batch)
    tolerance = 1 / float(session.sampling_fps)
    stored = 0
    dropped = 0
    for observation_number, proposal in enumerate(result.observations, start=1):
        reason = None
        if proposal.end_seconds < proposal.start_seconds:
            reason = "time range is reversed"
        elif proposal.start_seconds < max(0, minimum_time - tolerance) or proposal.end_seconds > maximum_time + tolerance:
            reason = "time is outside the supplied frame batch"
        elif any(frame_id not in frame_by_id for frame_id in proposal.evidence_frame_ids):
            reason = "evidence references a frame outside the supplied batch"
        if reason:
            dropped += 1
            logger.warning(
                "analysis_observation_dropped session_id=%s batch=%d observation=%d reason=%s",
                session.id,
                batch_number,
                observation_number,
                reason,
            )
            continue
        primary_frame = frame_by_id[proposal.evidence_frame_ids[0]]
        db.add(
            AnalysisObservation(
                id=uuid4(),
                session_id=session.id,
                frame_id=primary_frame.id,
                type=proposal.type,
                start_seconds=proposal.start_seconds,
                end_seconds=proposal.end_seconds,
                observation=proposal.observation,
                interpretation=proposal.interpretation,
                confidence=Decimal(str(proposal.confidence)),
                importance=Decimal(str(proposal.importance)),
                evidence_frame_ids=[str(frame_id) for frame_id in proposal.evidence_frame_ids],
                limitations=proposal.limitations,
            )
        )
        stored += 1
    return stored, dropped


def _validate_batch_result(
    content: dict, session_id: UUID, batch_number: int
) -> tuple[AnalysisBatchResult, int]:
    summary = content.get("summary")
    raw_observations = content.get("observations")
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("The model response has no summary.")
    if not isinstance(raw_observations, list):
        raise ValueError("The model response has no observations list.")

    observations: list[ObservationProposal] = []
    dropped = 0
    for observation_number, raw_observation in enumerate(raw_observations, start=1):
        try:
            observations.append(ObservationProposal.model_validate(raw_observation))
        except ValidationError as exc:
            dropped += 1
            logger.warning(
                "analysis_observation_dropped session_id=%s batch=%d observation=%d reason=%s",
                session_id,
                batch_number,
                observation_number,
                str(exc).replace("\n", " ")[:1000],
            )
    if len(observations) > 30:
        dropped += len(observations) - 30
        observations = observations[:30]
    return AnalysisBatchResult(summary=summary.strip()[:2000], observations=observations), dropped


def _store_usage(
    db: Session,
    session: AnalysisSession,
    usage: ProviderUsage | None,
    outcome: str,
    error: str | None,
) -> None:
    db.add(
        ModelRequest(
            id=uuid4(),
            session_id=session.id,
            owner_id=session.owner_id,
            task="visual_analysis_batch",
            provider_request_id=usage.provider_request_id if usage else None,
            model=usage.model if usage else session.model,
            prompt_tokens=usage.prompt_tokens if usage else None,
            completion_tokens=usage.completion_tokens if usage else None,
            total_tokens=usage.total_tokens if usage else None,
            cost=Decimal(str(usage.cost)) if usage and usage.cost is not None else None,
            duration_ms=usage.duration_ms if usage else 0,
            outcome=outcome,
            error=error,
        )
    )


def _observation_response(item: AnalysisObservation) -> AnalysisObservationResponse:
    return AnalysisObservationResponse(
        id=item.id,
        frame_id=item.frame_id,
        type=item.type,
        start_seconds=float(item.start_seconds),
        end_seconds=float(item.end_seconds),
        observation=item.observation,
        interpretation=item.interpretation,
        confidence=float(item.confidence),
        importance=float(item.importance),
        evidence_frame_ids=item.evidence_frame_ids,
        limitations=item.limitations,
    )


def _sha256(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()
