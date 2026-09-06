import asyncio
import hashlib
import logging
import shutil
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from pydantic import ValidationError

from app.features.analysis.models import AnalysisArtifact, AnalysisBatchJob, AnalysisFrame, AnalysisObservation, AnalysisReport, AnalysisSession, ModelRequest
from app.features.analysis.prompts import extraction_prompt, report_prompt
from app.features.analysis.profiles import PROFILES
from app.features.analysis.repository import (
    get_owner_session,
    get_analysis_report,
    list_artifacts,
    list_batch_jobs,
    list_frames,
    list_model_requests,
    list_observations,
    list_video_sessions,
)
from app.features.analysis.schemas import (
    AnalysisBatchResult,
    AnalysisArtifactResponse,
    AnalysisBatchJobResponse,
    AnalysisFrameResponse,
    AnalysisObservationResponse,
    AnalysisReportResponse,
    AnalysisResultsResponse,
    AnalysisSessionResponse,
    DeepReportProposal,
    DomainRecordProposal,
    ModelUsageResponse,
    ObservationProposal,
    StartAnalysisRequest,
    StructuredAnalysisResponse,
)
from app.features.identity.models import User
from app.features.videos.models import MediaAsset, Video
from app.features.videos.repository import get_owner_video
from app.platform.config import Settings
from app.platform.database import SessionLocal
from app.platform.errors import ApiError
from app.platform.media.video import extract_sampled_frames, probe_image_dimensions
from app.platform.ai.openrouter import ProviderUsage, StructuredResponse, analyze_images
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
    if video.duration_seconds is None:
        raise ApiError(422, "VIDEO_DURATION_UNAVAILABLE", "The video duration is unavailable.")

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

    # if video.duration_seconds and float(video.duration_seconds) * request.sampling_fps > 1200:
    #     raise ApiError(422, "TOO_MANY_ANALYSIS_FRAMES", "Choose a lower frame rate; an analysis is limited to 1,200 frames.")

    session = AnalysisSession(
        id=uuid4(),
        owner_id=owner.id,
        video_id=video.id,
        profile_id=profile.id,
        profile_version=profile.version,
        model=settings.openrouter_model,
        prompt_version="2.0",
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
                source,
                output_dir,
                float(session.sampling_fps),
                max(1, round(float(video.duration_seconds) * float(session.sampling_fps)) + 1),
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
            batches = _build_time_batches(frames, settings.analysis_batch_seconds)
            batch_jobs: list[AnalysisBatchJob] = []
            for batch_number, batch in enumerate(batches, start=1):
                job = AnalysisBatchJob(
                    id=uuid4(),
                    session_id=session.id,
                    batch_number=batch_number,
                    start_seconds=batch[0].timestamp_seconds,
                    end_seconds=batch[-1].timestamp_seconds,
                    source_frame_count=len(batch),
                    status="pending",
                )
                db.add(job)
                batch_jobs.append(job)
            session.phase = "analyzing_batches"
            session.total_jobs = 2 + len(batches)
            session.completed_jobs = 1
            session.terminal_progress_percent = 15
            db.commit()
            logger.info(
                "analysis_stage_completed session_id=%s stage=%s frame_count=%d batch_count=%d batch_seconds=%.1f",
                session.id,
                stage,
                len(frames),
                len(batches),
                settings.analysis_batch_seconds,
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

        summaries, successful_batches, failed_batches, skipped_batches = asyncio.run(
            _process_visual_batches(
                db,
                session_id,
                batches,
                batch_jobs,
                frame_paths,
                settings,
            )
        )

        session = db.get(AnalysisSession, session_id)
        session.phase = "reconciling_results"
        session.terminal_progress_percent = 82
        db.commit()
        merged_artifacts = _reconcile_artifacts(db, session.id)
        logger.info(
            "analysis_reconciliation_completed session_id=%s merged_artifacts=%d",
            session.id,
            merged_artifacts,
        )

        session = db.get(AnalysisSession, session_id)
        session.phase = "generating_report"
        session.terminal_progress_percent = 85
        session.summary = {
            "overview": " ".join(summaries),
            "frame_count": len(frames),
            "successful_batches": successful_batches,
            "failed_batches": failed_batches,
            "skipped_batches": skipped_batches,
            "coverage": _coverage_summary(batch_jobs),
        }
        db.commit()

        report_generated = _generate_deep_report(db, session, batch_jobs, failed_batches, settings)
        session = db.get(AnalysisSession, session_id)
        session.completed_jobs = 1 + successful_batches + (1 if report_generated else 0)
        session.status = "completed" if failed_batches == 0 and report_generated else "partial"
        session.phase = "completed" if session.status == "completed" else "partial"
        session.terminal_progress_percent = 100
        session.completed_at = datetime.now(UTC)
        session.error = (
            None
            if failed_batches == 0 and report_generated
            else _completion_error(failed_batches, skipped_batches, report_generated)
        )
        db.commit()
        logger.info(
            "analysis_completed session_id=%s status=%s successful_batches=%d failed_batches=%d",
            session.id,
            session.status,
            successful_batches,
            failed_batches,
        )


@dataclass(frozen=True)
class _BatchAttemptFailure:
    usage: ProviderUsage | None
    message: str
    error_code: str
    permanent: bool


@dataclass(frozen=True)
class _BatchCallOutcome:
    batch_number: int
    attempts: int
    response: StructuredResponse | None = None
    result: AnalysisBatchResult | None = None
    structurally_dropped: int = 0
    failures: tuple[_BatchAttemptFailure, ...] = ()
    skipped: bool = False


async def _process_visual_batches(
    db: Session,
    session_id: UUID,
    batches: list[list[AnalysisFrame]],
    batch_jobs: list[AnalysisBatchJob],
    frame_paths: dict[UUID, Path],
    settings: Settings,
) -> tuple[list[str], int, int, int]:
    """Run provider-bound batch work concurrently and serialize database writes."""
    session = db.get(AnalysisSession, session_id)
    profile_id = session.profile_id
    concurrency = max(1, settings.analysis_batch_concurrency)
    launch_interval = max(0.0, settings.analysis_batch_launch_interval_seconds)
    semaphore = asyncio.Semaphore(concurrency)
    launch_lock = asyncio.Lock()
    abort_pending = asyncio.Event()
    last_launch = [0.0]

    logger.info(
        "analysis_parallel_batches_started session_id=%s batch_count=%d concurrency=%d launch_interval_seconds=%.1f",
        session_id,
        len(batches),
        concurrency,
        launch_interval,
    )

    async def run_one(batch_number: int, batch: list[AnalysisFrame]) -> _BatchCallOutcome:
        async with semaphore:
            if abort_pending.is_set():
                return _BatchCallOutcome(batch_number=batch_number, attempts=0, skipped=True)
            async with launch_lock:
                delay = max(0.0, last_launch[0] + launch_interval - time.monotonic())
                if delay:
                    await asyncio.sleep(delay)
                if abort_pending.is_set():
                    return _BatchCallOutcome(batch_number=batch_number, attempts=0, skipped=True)
                last_launch[0] = time.monotonic()

            batch_job = batch_jobs[batch_number - 1]
            batch_job.status = "running"
            batch_job.started_at = batch_job.started_at or datetime.now(UTC)
            batch_job.error_code = None
            batch_job.error_message = None
            db.commit()

            paths = [frame_paths[frame.id] for frame in batch]
            labels = [
                f"Frame {index + 1}: frame_id={frame.id}, timestamp={float(frame.timestamp_seconds):.3f}s"
                for index, frame in enumerate(batch)
            ]
            return await asyncio.to_thread(
                _request_visual_batch,
                settings,
                session_id,
                profile_id,
                batch_number,
                len(batches),
                float(batch[0].timestamp_seconds),
                float(batch[-1].timestamp_seconds),
                paths,
                labels,
            )

    tasks = [
        asyncio.create_task(run_one(batch_number, batch))
        for batch_number, batch in enumerate(batches, start=1)
    ]
    summaries_by_batch: dict[int, str] = {}
    successful_batches = 0
    failed_batches = 0
    skipped_batches = 0
    processed_batches = 0

    for task in asyncio.as_completed(tasks):
        outcome = await task
        batch_number = outcome.batch_number
        batch = batches[batch_number - 1]
        batch_job = batch_jobs[batch_number - 1]
        session = db.get(AnalysisSession, session_id)

        if outcome.skipped:
            skipped_batches += 1
            batch_job.status = "skipped"
            batch_job.error_code = "PROVIDER_ABORTED"
            batch_job.error_message = "Skipped after a permanent provider failure."
            batch_job.completed_at = datetime.now(UTC)
        else:
            batch_job.attempt_count = outcome.attempts
            for failure in outcome.failures:
                _store_usage(
                    db,
                    session,
                    failure.usage,
                    "failed",
                    failure.message,
                    "visual_analysis_batch",
                )

            if outcome.response is not None and outcome.result is not None:
                try:
                    stored_observations, stored_artifacts, evidence_dropped = _store_batch_result(
                        db, session, batch, outcome.result, batch_job
                    )
                    _store_usage(
                        db,
                        session,
                        outcome.response.usage,
                        "completed",
                        None,
                        "visual_analysis_batch",
                    )
                    batch_job.status = "completed"
                    batch_job.completed_at = datetime.now(UTC)
                    successful_batches += 1
                    summaries_by_batch[batch_number] = outcome.result.summary
                    logger.info(
                        "analysis_batch_completed session_id=%s batch=%d attempt=%d observations=%d artifacts=%d dropped_records=%d provider_request_id=%s",
                        session_id,
                        batch_number,
                        outcome.attempts,
                        stored_observations,
                        stored_artifacts,
                        outcome.structurally_dropped + evidence_dropped,
                        outcome.response.usage.provider_request_id,
                    )
                except Exception as exc:
                    logger.exception(
                        "analysis_batch_persistence_failed session_id=%s batch=%d error_type=%s",
                        session_id,
                        batch_number,
                        type(exc).__name__,
                    )
                    db.rollback()
                    session = db.get(AnalysisSession, session_id)
                    batch_job = db.get(AnalysisBatchJob, batch_job.id)
                    failed_batches += 1
                    batch_job.status = "failed"
                    batch_job.error_code = type(exc).__name__
                    batch_job.error_message = "The analysis result could not be saved."
                    batch_job.completed_at = datetime.now(UTC)
            else:
                failed_batches += 1
                failure = outcome.failures[-1]
                batch_job.status = "failed"
                batch_job.error_code = failure.error_code
                batch_job.error_message = failure.message
                batch_job.completed_at = datetime.now(UTC)
                if failure.permanent:
                    abort_pending.set()
                    logger.error(
                        "analysis_provider_abort_requested session_id=%s failed_batch=%d",
                        session_id,
                        batch_number,
                    )

        processed_batches += 1
        session = db.get(AnalysisSession, session_id)
        session.phase = f"analyzing_batches_{processed_batches}_of_{len(batches)}_finished"
        session.completed_jobs = 1 + successful_batches
        session.failed_jobs = failed_batches
        session.terminal_progress_percent = 15 + round(65 * processed_batches / len(batches))
        db.commit()

    logger.info(
        "analysis_parallel_batches_completed session_id=%s successful=%d failed=%d skipped=%d",
        session_id,
        successful_batches,
        failed_batches,
        skipped_batches,
    )
    summaries = [summaries_by_batch[number] for number in sorted(summaries_by_batch)]
    return summaries, successful_batches, failed_batches, skipped_batches


def _request_visual_batch(
    settings: Settings,
    session_id: UUID,
    profile_id: str,
    batch_number: int,
    total_batches: int,
    start_seconds: float,
    end_seconds: float,
    paths: list[Path],
    labels: list[str],
) -> _BatchCallOutcome:
    failures: list[_BatchAttemptFailure] = []
    for attempt in range(1, settings.analysis_batch_max_attempts + 1):
        response = None
        logger.info(
            "analysis_batch_started session_id=%s batch=%d total_batches=%d start_seconds=%.3f end_seconds=%.3f frame_count=%d attempt=%d max_attempts=%d",
            session_id,
            batch_number,
            total_batches,
            start_seconds,
            end_seconds,
            len(paths),
            attempt,
            settings.analysis_batch_max_attempts,
        )
        try:
            response = analyze_images(
                settings,
                extraction_prompt(profile_id),
                paths,
                AnalysisBatchResult.model_json_schema(),
                image_labels=labels,
                max_output_tokens=(
                    settings.analysis_retry_max_output_tokens if attempt > 1 else None
                ),
                provider_sort=(
                    settings.openrouter_retry_provider_sort if attempt > 1 else None
                ),
            )
            result, structurally_dropped = _validate_batch_result(
                response.content, session_id, batch_number
            )
            return _BatchCallOutcome(
                batch_number=batch_number,
                attempts=attempt,
                response=response,
                result=result,
                structurally_dropped=structurally_dropped,
                failures=tuple(failures),
            )
        except Exception as exc:
            if isinstance(exc, (ApiError, ValidationError, ValueError)):
                logger.warning(
                    "analysis_batch_attempt_failed session_id=%s batch=%d attempt=%d error_type=%s error=%s",
                    session_id,
                    batch_number,
                    attempt,
                    type(exc).__name__,
                    (exc.message if isinstance(exc, ApiError) else str(exc)).replace("\n", " ")[:1000],
                )
            else:
                logger.exception(
                    "analysis_batch_attempt_failed session_id=%s batch=%d attempt=%d error_type=%s",
                    session_id,
                    batch_number,
                    attempt,
                    type(exc).__name__,
                )
            if isinstance(exc, ApiError):
                message = exc.message
                error_code = exc.code
            elif isinstance(exc, (ValidationError, ValueError)):
                message = "The model returned results that failed validation."
                error_code = type(exc).__name__
            else:
                message = "The analysis result could not be processed."
                error_code = type(exc).__name__
            permanent = (
                isinstance(exc, ApiError)
                and exc.code in {
                    "AI_NOT_CONFIGURED",
                    "AI_AUTHENTICATION_FAILED",
                    "AI_REQUEST_INVALID",
                }
            ) or not isinstance(exc, (ApiError, ValidationError, ValueError))
            failures.append(
                _BatchAttemptFailure(
                    usage=response.usage if response else None,
                    message=message,
                    error_code=error_code,
                    permanent=permanent,
                )
            )
            if permanent or attempt == settings.analysis_batch_max_attempts:
                return _BatchCallOutcome(
                    batch_number=batch_number,
                    attempts=attempt,
                    failures=tuple(failures),
                )
            wait_seconds = min(
                settings.analysis_batch_retry_seconds * 2 ** (attempt - 1),
                settings.openrouter_retry_max_wait_seconds,
            )
            logger.info(
                "analysis_batch_retry_scheduled session_id=%s batch=%d next_attempt=%d wait_seconds=%.1f",
                session_id,
                batch_number,
                attempt + 1,
                wait_seconds,
            )
            time.sleep(wait_seconds)

    raise RuntimeError("Batch retry loop finished without an outcome.")


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
            for job in list_batch_jobs(db, session.id):
                if job.status == "running":
                    job.status = "failed"
                    job.error_code = "ANALYSIS_INTERRUPTED"
                    job.error_message = "The backend restarted while this batch was running."
                    job.completed_at = datetime.now(UTC)
                elif job.status == "pending":
                    job.status = "skipped"
                    job.error_code = "ANALYSIS_INTERRUPTED"
                    job.error_message = "This batch did not start before the backend restarted."
                    job.completed_at = datetime.now(UTC)
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

        orphaned_jobs = list(
            db.scalars(
                select(AnalysisBatchJob)
                .join(AnalysisSession, AnalysisSession.id == AnalysisBatchJob.session_id)
                .where(
                    AnalysisSession.status.notin_(("pending", "running")),
                    AnalysisBatchJob.status.in_(("pending", "running")),
                )
            )
        )
        for job in orphaned_jobs:
            was_running = job.status == "running"
            job.status = "failed" if was_running else "skipped"
            job.error_code = "ANALYSIS_INTERRUPTED"
            job.error_message = (
                "The backend restarted while this batch was running."
                if was_running
                else "This batch did not start before the backend restarted."
            )
            job.completed_at = datetime.now(UTC)
        if orphaned_jobs:
            logger.warning("analysis_orphaned_batch_jobs_recovered count=%d", len(orphaned_jobs))
            db.commit()

        orphaned_reports = list(
            db.scalars(
                select(AnalysisReport)
                .join(AnalysisSession, AnalysisSession.id == AnalysisReport.session_id)
                .where(
                    AnalysisSession.status.notin_(("pending", "running")),
                    AnalysisReport.status == "pending",
                )
            )
        )
        for report in orphaned_reports:
            session = db.get(AnalysisSession, report.session_id)
            jobs = list_batch_jobs(db, session.id)
            coverage = _coverage_summary(jobs)
            message = "Deep report generation was interrupted by a backend restart."
            report.status = "failed"
            report.error = message
            report.content = _fallback_report(
                session,
                list_artifacts(db, session.id),
                coverage,
                message,
            )
            report.generated_at = datetime.now(UTC)
        if orphaned_reports:
            logger.warning("analysis_orphaned_reports_recovered count=%d", len(orphaned_reports))
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
        profile_version=PROFILES[previous.profile_id].version,
        model=settings.openrouter_model,
        prompt_version="2.0",
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


def get_structured_results(
    db: Session, owner: User, session_id: UUID, category: str | None = None
) -> StructuredAnalysisResponse:
    session = get_owner_session(db, owner.id, session_id)
    if not session:
        raise ApiError(404, "ANALYSIS_NOT_FOUND", "Analysis was not found.")
    jobs = list_batch_jobs(db, session.id)
    artifacts = list_artifacts(db, session.id, category)
    return StructuredAnalysisResponse(
        batch_jobs=[_batch_job_response(item) for item in jobs],
        artifacts=[_artifact_response(item) for item in artifacts],
        coverage=_coverage_summary(jobs),
    )


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
    report = get_analysis_report(db, session.id)
    limitations: list[str] = []
    if session.status == "partial":
        limitations.append(session.error or "Some analysis batches did not complete.")
    if not report:
        limitations.append("A deep report has not been generated for this legacy analysis.")
    return AnalysisReportResponse(
        session_id=session.id,
        status=session.status,
        profile_id=session.profile_id,
        model=session.model,
        report_status=report.status if report else "unavailable",
        report_version=report.version if report else "legacy",
        content=report.content if report else {},
        limitations=limitations + (report.content.get("limitations", []) if report else []),
    )


def _build_time_batches(
    frames: list[AnalysisFrame], batch_seconds: float
) -> list[list[AnalysisFrame]]:
    if batch_seconds <= 0:
        raise ValueError("Analysis batch duration must be positive.")
    windows: dict[int, list[AnalysisFrame]] = {}
    for frame in frames:
        window = int(float(frame.timestamp_seconds) // batch_seconds)
        windows.setdefault(window, []).append(frame)
    return [windows[window] for window in sorted(windows)]


def _store_batch_result(
    db: Session,
    session: AnalysisSession,
    batch: list[AnalysisFrame],
    result: AnalysisBatchResult,
    batch_job: AnalysisBatchJob,
) -> tuple[int, int, int]:
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
                batch_job.batch_number,
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

    stored_artifacts = 0
    for record_number, proposal in enumerate(result.domain_records, start=1):
        reason = _invalid_domain_record_reason(proposal, frame_by_id, minimum_time, maximum_time, tolerance)
        if reason:
            dropped += 1
            logger.warning(
                "analysis_artifact_dropped session_id=%s batch=%d record=%d reason=%s",
                session.id,
                batch_job.batch_number,
                record_number,
                reason,
            )
            continue
        db.add(
            AnalysisArtifact(
                id=uuid4(),
                session_id=session.id,
                batch_job_id=batch_job.id,
                category=proposal.category,
                subtype=proposal.subtype,
                title=proposal.title,
                start_seconds=proposal.start_seconds,
                end_seconds=proposal.end_seconds,
                observation=proposal.observation,
                interpretation=proposal.interpretation,
                attributes=proposal.attributes.model_dump(mode="json", exclude_none=True),
                confidence=Decimal(str(proposal.confidence)),
                importance=Decimal(str(proposal.importance)),
                evidence_frame_ids=[str(frame_id) for frame_id in proposal.evidence_frame_ids],
                limitations=proposal.limitations,
            )
        )
        stored_artifacts += 1
    return stored, stored_artifacts, dropped


def _validate_batch_result(
    content: dict, session_id: UUID, batch_number: int
) -> tuple[AnalysisBatchResult, int]:
    summary = content.get("summary")
    raw_observations = content.get("observations", [])
    raw_domain_records = content.get("domain_records", [])
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("The model response has no summary.")
    if not isinstance(raw_observations, list):
        raw_observations = []
    if not isinstance(raw_domain_records, list):
        raw_domain_records = []

    observations: list[ObservationProposal] = []
    dropped = 0
    for observation_number, raw_observation in enumerate(raw_observations, start=1):
        try:
            if isinstance(raw_observation, dict):
                raw_observation = _trim_evidence(raw_observation, 8)
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
    if len(observations) > 3:
        dropped += len(observations) - 3
        observations = observations[:3]
    domain_records: list[DomainRecordProposal] = []
    for record_number, raw_record in enumerate(raw_domain_records, start=1):
        try:
            if isinstance(raw_record, dict):
                raw_record = _trim_evidence(raw_record, 12)
            domain_records.append(DomainRecordProposal.model_validate(raw_record))
        except ValidationError as exc:
            dropped += 1
            logger.warning(
                "analysis_artifact_dropped session_id=%s batch=%d record=%d reason=%s",
                session_id,
                batch_number,
                record_number,
                str(exc).replace("\n", " ")[:1000],
            )
    if len(domain_records) > 15:
        dropped += len(domain_records) - 15
        domain_records = domain_records[:15]
    return AnalysisBatchResult(
        summary=summary.strip()[:2000],
        observations=observations,
        domain_records=domain_records,
    ), dropped


def _trim_evidence(record: dict, maximum: int) -> dict:
    evidence = record.get("evidence_frame_ids")
    if not isinstance(evidence, list) or len(evidence) <= maximum:
        return record
    normalized = dict(record)
    normalized["evidence_frame_ids"] = list(dict.fromkeys(evidence))[:maximum]
    return normalized


def _invalid_domain_record_reason(
    proposal: DomainRecordProposal,
    frame_by_id: dict[UUID, AnalysisFrame],
    minimum_time: float,
    maximum_time: float,
    tolerance: float,
) -> str | None:
    if proposal.end_seconds < proposal.start_seconds:
        return "time range is reversed"
    if proposal.start_seconds < max(0, minimum_time - tolerance) or proposal.end_seconds > maximum_time + tolerance:
        return "time is outside the supplied frame batch"
    if any(frame_id not in frame_by_id for frame_id in proposal.evidence_frame_ids):
        return "evidence references a frame outside the supplied batch"
    return None


def _coverage_summary(jobs: list[AnalysisBatchJob]) -> dict:
    if not jobs:
        return {"percent": 0, "covered_ranges": [], "missing_ranges": []}
    covered = [job for job in jobs if job.status == "completed"]
    missing = [job for job in jobs if job.status != "completed"]
    return {
        "percent": round(100 * len(covered) / len(jobs)),
        "successful_batches": len(covered),
        "total_batches": len(jobs),
        "covered_ranges": _merge_job_ranges(covered),
        "missing_ranges": _merge_job_ranges(missing),
    }


def _merge_job_ranges(jobs: list[AnalysisBatchJob]) -> list[dict[str, float]]:
    ranges: list[dict[str, float]] = []
    for job in sorted(jobs, key=lambda item: item.start_seconds):
        start = float(job.start_seconds)
        end = float(job.end_seconds)
        if ranges and start <= ranges[-1]["end_seconds"] + 0.2:
            ranges[-1]["end_seconds"] = max(ranges[-1]["end_seconds"], end)
        else:
            ranges.append({"start_seconds": start, "end_seconds": end})
    return ranges


def _reconcile_artifacts(db: Session, session_id: UUID) -> int:
    """Merge adjacent segment proposals while preserving their combined evidence."""
    segments = list_artifacts(db, session_id, "segment")
    merged = 0
    previous: AnalysisArtifact | None = None
    for segment in segments:
        if (
            previous
            and previous.subtype == segment.subtype
            and float(segment.start_seconds) <= float(previous.end_seconds) + 0.5
        ):
            previous.end_seconds = max(previous.end_seconds, segment.end_seconds)
            if segment.observation not in previous.observation:
                previous.observation = f"{previous.observation} {segment.observation}"[:4000]
            if segment.interpretation and segment.interpretation not in (previous.interpretation or ""):
                previous.interpretation = f"{previous.interpretation or ''} {segment.interpretation}".strip()[:4000]
            previous.attributes = {**segment.attributes, **previous.attributes}
            previous.evidence_frame_ids = list(dict.fromkeys(previous.evidence_frame_ids + segment.evidence_frame_ids))[:24]
            previous.limitations = list(dict.fromkeys(previous.limitations + segment.limitations))[:16]
            previous.confidence = max(previous.confidence, segment.confidence)
            previous.importance = max(previous.importance, segment.importance)
            db.delete(segment)
            merged += 1
        else:
            previous = segment
    db.commit()
    return merged


def _generate_deep_report(
    db: Session,
    session: AnalysisSession,
    jobs: list[AnalysisBatchJob],
    failed_batches: int,
    settings: Settings,
) -> bool:
    artifacts = list_artifacts(db, session.id)
    observations = list_observations(db, session.id)
    coverage = _coverage_summary(jobs)
    evidence = {
        "session": {
            "profile": session.profile_id,
            "sampling_fps": float(session.sampling_fps),
            "coverage": coverage,
        },
        "artifacts": [
            {
                "artifact_id": str(item.id),
                "category": item.category,
                "subtype": item.subtype,
                "title": item.title,
                "start_seconds": float(item.start_seconds),
                "end_seconds": float(item.end_seconds),
                "observation": item.observation,
                "interpretation": item.interpretation,
                "attributes": item.attributes,
                "confidence": float(item.confidence),
                "importance": float(item.importance),
                "limitations": item.limitations,
            }
            for item in artifacts
        ],
        "general_observations": [
            {
                "observation_id": str(item.id),
                "type": item.type,
                "start_seconds": float(item.start_seconds),
                "end_seconds": float(item.end_seconds),
                "observation": item.observation,
                "interpretation": item.interpretation,
                "confidence": float(item.confidence),
                "importance": float(item.importance),
                "limitations": item.limitations,
            }
            for item in observations
        ],
    }
    report = get_analysis_report(db, session.id)
    if not report:
        report = AnalysisReport(id=uuid4(), session_id=session.id, version="2.0", status="pending")
        db.add(report)
        db.commit()
        report = get_analysis_report(db, session.id)

    logger.info(
        "analysis_report_started session_id=%s artifacts=%d observations=%d coverage_percent=%d",
        session.id,
        len(artifacts),
        len(observations),
        coverage["percent"],
    )
    last_message = "Deep report generation failed."
    for attempt in range(1, settings.analysis_batch_max_attempts + 1):
        response = None
        try:
            response = analyze_images(
                settings,
                report_prompt(evidence),
                [],
                DeepReportProposal.model_json_schema(),
            )
            proposal = DeepReportProposal.model_validate(response.content)
            report.content = {**proposal.model_dump(mode="json"), "coverage": coverage}
            report.status = "completed" if failed_batches == 0 else "partial"
            report.error = None
            report.generated_at = datetime.now(UTC)
            _store_usage(db, session, response.usage, "completed", None, "deep_report_generation")
            db.commit()
            logger.info("analysis_report_completed session_id=%s status=%s", session.id, report.status)
            return True
        except Exception as exc:
            db.rollback()
            session = db.get(AnalysisSession, session.id)
            report = get_analysis_report(db, session.id)
            last_message = exc.message if isinstance(exc, ApiError) else "The model returned an invalid deep report."
            _store_usage(db, session, response.usage if response else None, "failed", last_message, "deep_report_generation")
            db.commit()
            logger.warning(
                "analysis_report_attempt_failed session_id=%s attempt=%d error_type=%s error=%s",
                session.id,
                attempt,
                type(exc).__name__,
                last_message.replace("\n", " ")[:1000],
            )

    report = get_analysis_report(db, session.id)
    report.status = "failed"
    report.error = last_message
    report.generated_at = datetime.now(UTC)
    report.content = _fallback_report(session, artifacts, coverage, last_message)
    db.commit()
    return False


def _fallback_report(
    session: AnalysisSession,
    artifacts: list[AnalysisArtifact],
    coverage: dict,
    error: str,
) -> dict:
    important = sorted(artifacts, key=lambda item: item.importance, reverse=True)[:10]
    limitations = [error]
    if coverage["percent"] < 100:
        limitations.append(f"Visual evidence covers {coverage['percent']}% of analysis batches.")
    return {
        "executive_summary": (session.summary or {}).get("overview", "Structured evidence was extracted, but the narrative report could not be generated."),
        "video_features": {},
        "competition_context": {},
        "key_moments": [
            {
                "artifact_id": str(item.id),
                "timestamp_seconds": float(item.start_seconds),
                "title": item.title,
                "description": item.observation,
            }
            for item in important
        ],
        "run_summaries": [],
        "course_analysis": {},
        "technique_analysis": {},
        "synchronization_analysis": {},
        "scoreboard_results": [],
        "comparisons": [],
        "causal_hypotheses": [],
        "strengths": [],
        "weaknesses": [],
        "recommendations": [],
        "limitations": limitations,
        "coverage": coverage,
    }


def _completion_error(failed_batches: int, skipped_batches: int, report_generated: bool) -> str:
    messages = []
    if failed_batches:
        messages.append(f"{failed_batches} visual analysis batch failed; {skipped_batches} remaining batches were skipped.")
    if not report_generated:
        messages.append("Deep report generation failed; a deterministic evidence summary is available.")
    return " ".join(messages)


def _batch_job_response(item: AnalysisBatchJob) -> AnalysisBatchJobResponse:
    return AnalysisBatchJobResponse(
        id=item.id,
        batch_number=item.batch_number,
        start_seconds=float(item.start_seconds),
        end_seconds=float(item.end_seconds),
        source_frame_count=item.source_frame_count,
        status=item.status,
        attempt_count=item.attempt_count,
        error_code=item.error_code,
        error_message=item.error_message,
    )


def _artifact_response(item: AnalysisArtifact) -> AnalysisArtifactResponse:
    return AnalysisArtifactResponse(
        id=item.id,
        batch_job_id=item.batch_job_id,
        category=item.category,
        subtype=item.subtype,
        title=item.title,
        start_seconds=float(item.start_seconds),
        end_seconds=float(item.end_seconds),
        observation=item.observation,
        interpretation=item.interpretation,
        attributes=item.attributes,
        confidence=float(item.confidence),
        importance=float(item.importance),
        evidence_frame_ids=item.evidence_frame_ids,
        limitations=item.limitations,
    )


def _store_usage(
    db: Session,
    session: AnalysisSession,
    usage: ProviderUsage | None,
    outcome: str,
    error: str | None,
    task: str,
) -> None:
    db.add(
        ModelRequest(
            id=uuid4(),
            session_id=session.id,
            owner_id=session.owner_id,
            task=task,
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
