from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.features.analysis.profiles import PROFILES
from app.features.analysis.schemas import (
    AnalysisFrameResponse,
    AnalysisObservationResponse,
    AnalysisProfileResponse,
    AnalysisReportResponse,
    AnalysisResultsResponse,
    AnalysisSessionResponse,
    ModelUsageResponse,
    StartAnalysisRequest,
    StructuredAnalysisResponse,
    SummaryVideoResponse,
)
from app.features.analysis.service import delete_analysis, get_report, get_results, get_session, get_structured_results, get_usage, get_video_sessions, retry_analysis, run_analysis, start_analysis
from app.features.analysis.summary import get_summary_video, run_summary_video, start_summary_video
from app.features.identity.dependencies import csrf_protect, require_approved_user
from app.features.identity.models import User
from app.platform.config import Settings, get_settings
from app.platform.database import get_db

router = APIRouter(tags=["analysis"])


@router.get("/analysis-profiles", response_model=list[AnalysisProfileResponse])
def list_profiles() -> list[AnalysisProfileResponse]:
    return list(PROFILES.values())


@router.post("/videos/{video_id}/analyses", response_model=AnalysisSessionResponse, status_code=202, dependencies=[Depends(csrf_protect)])
def create_analysis(
    video_id: UUID,
    request: StartAnalysisRequest,
    background_tasks: BackgroundTasks,
    owner: Annotated[User, Depends(require_approved_user)],
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AnalysisSessionResponse:
    result = start_analysis(db, owner, video_id, request, settings)
    if result.status == "pending":
        background_tasks.add_task(run_analysis, result.id, settings)
    return result


@router.get("/videos/{video_id}/analyses", response_model=list[AnalysisSessionResponse])
def list_analyses(video_id: UUID, owner: Annotated[User, Depends(require_approved_user)], db: Annotated[Session, Depends(get_db)]) -> list[AnalysisSessionResponse]:
    return get_video_sessions(db, owner, video_id)


@router.get("/analyses/{session_id}", response_model=AnalysisSessionResponse)
def analysis_detail(session_id: UUID, owner: Annotated[User, Depends(require_approved_user)], db: Annotated[Session, Depends(get_db)]) -> AnalysisSessionResponse:
    return get_session(db, owner, session_id)


@router.get("/analyses/{session_id}/status", response_model=AnalysisSessionResponse)
def analysis_status(session_id: UUID, owner: Annotated[User, Depends(require_approved_user)], db: Annotated[Session, Depends(get_db)]) -> AnalysisSessionResponse:
    return get_session(db, owner, session_id)


@router.delete("/analyses/{session_id}", status_code=204, dependencies=[Depends(csrf_protect)])
def delete_analysis_route(
    session_id: UUID,
    owner: Annotated[User, Depends(require_approved_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    delete_analysis(db, owner, session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/analyses/{session_id}/results", response_model=AnalysisResultsResponse)
def analysis_results(session_id: UUID, owner: Annotated[User, Depends(require_approved_user)], db: Annotated[Session, Depends(get_db)]) -> AnalysisResultsResponse:
    return get_results(db, owner, session_id)


@router.get("/analyses/{session_id}/frames", response_model=list[AnalysisFrameResponse])
def analysis_frames(session_id: UUID, owner: Annotated[User, Depends(require_approved_user)], db: Annotated[Session, Depends(get_db)]) -> list[AnalysisFrameResponse]:
    return get_results(db, owner, session_id).frames


@router.get("/analyses/{session_id}/observations", response_model=list[AnalysisObservationResponse])
def analysis_observations(session_id: UUID, owner: Annotated[User, Depends(require_approved_user)], db: Annotated[Session, Depends(get_db)]) -> list[AnalysisObservationResponse]:
    return get_results(db, owner, session_id).observations


@router.get("/analyses/{session_id}/key-moments", response_model=list[AnalysisObservationResponse])
def analysis_key_moments(session_id: UUID, owner: Annotated[User, Depends(require_approved_user)], db: Annotated[Session, Depends(get_db)]) -> list[AnalysisObservationResponse]:
    results = get_results(db, owner, session_id)
    return [item for item in results.observations if item.importance > 0]


@router.get("/analyses/{session_id}/usage", response_model=ModelUsageResponse)
def analysis_usage(session_id: UUID, owner: Annotated[User, Depends(require_approved_user)], db: Annotated[Session, Depends(get_db)]) -> ModelUsageResponse:
    return get_usage(db, owner, session_id)


@router.get("/analyses/{session_id}/report", response_model=AnalysisReportResponse)
def analysis_report(session_id: UUID, owner: Annotated[User, Depends(require_approved_user)], db: Annotated[Session, Depends(get_db)]) -> AnalysisReportResponse:
    return get_report(db, owner, session_id)


@router.post(
    "/analyses/{session_id}/summary-video",
    response_model=SummaryVideoResponse,
    status_code=202,
    dependencies=[Depends(csrf_protect)],
)
def create_summary_video(
    session_id: UUID,
    background_tasks: BackgroundTasks,
    owner: Annotated[User, Depends(require_approved_user)],
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SummaryVideoResponse:
    result = start_summary_video(db, owner, session_id, settings)
    if result.status == "pending":
        background_tasks.add_task(run_summary_video, result.id, settings)
    return result


@router.get("/analyses/{session_id}/summary-video", response_model=SummaryVideoResponse)
def summary_video_detail(
    session_id: UUID,
    owner: Annotated[User, Depends(require_approved_user)],
    db: Annotated[Session, Depends(get_db)],
) -> SummaryVideoResponse:
    return get_summary_video(db, owner, session_id)


@router.get("/analyses/{session_id}/structured", response_model=StructuredAnalysisResponse)
def analysis_structured_results(
    session_id: UUID,
    owner: Annotated[User, Depends(require_approved_user)],
    db: Annotated[Session, Depends(get_db)],
    category: Annotated[str | None, Query(max_length=40)] = None,
) -> StructuredAnalysisResponse:
    return get_structured_results(db, owner, session_id, category)


@router.post("/analyses/{session_id}/retry", response_model=AnalysisSessionResponse, status_code=202, dependencies=[Depends(csrf_protect)])
def retry_analysis_route(
    session_id: UUID,
    background_tasks: BackgroundTasks,
    owner: Annotated[User, Depends(require_approved_user)],
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AnalysisSessionResponse:
    result = retry_analysis(db, owner, session_id, settings)
    if result.status == "pending":
        background_tasks.add_task(run_analysis, result.id, settings)
    return result
