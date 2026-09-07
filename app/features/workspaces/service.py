from uuid import UUID, uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.features.analysis.models import AnalysisSession, SummaryVideo
from app.features.identity.models import User
from app.features.videos.models import MediaAsset, Video
from app.features.videos.service import video_response
from app.features.workspaces.models import Workspace, WorkspaceVideo
from app.features.workspaces.schemas import (
    CreateWorkspaceRequest,
    UpdateWorkspaceRequest,
    WorkspaceDetailResponse,
    WorkspaceResponse,
    WorkspaceVideoResponse,
)
from app.platform.errors import ApiError


def _workspace_response(workspace: Workspace, video_count: int) -> WorkspaceResponse:
    return WorkspaceResponse(
        id=workspace.id,
        name=workspace.name,
        created_at=workspace.created_at,
        updated_at=workspace.updated_at,
        video_count=video_count,
    )


def _get_workspace(db: Session, owner: User, workspace_id: UUID) -> Workspace:
    workspace = db.scalar(select(Workspace).where(Workspace.id == workspace_id, Workspace.owner_id == owner.id))
    if not workspace:
        raise ApiError(404, "WORKSPACE_NOT_FOUND", "Workspace was not found.")
    return workspace


def list_workspaces(db: Session, owner: User) -> list[WorkspaceResponse]:
    workspaces = list(db.scalars(select(Workspace).where(Workspace.owner_id == owner.id).order_by(Workspace.created_at.desc())))
    counts = dict(db.execute(
        select(WorkspaceVideo.workspace_id, func.count(WorkspaceVideo.id))
        .join(Workspace, Workspace.id == WorkspaceVideo.workspace_id)
        .where(Workspace.owner_id == owner.id)
        .group_by(WorkspaceVideo.workspace_id)
    ).all())
    return [_workspace_response(item, counts.get(item.id, 0)) for item in workspaces]


def create_workspace(db: Session, owner: User, request: CreateWorkspaceRequest) -> WorkspaceResponse:
    workspace = Workspace(id=uuid4(), owner_id=owner.id, name=request.name.strip())
    if not workspace.name:
        raise ApiError(422, "WORKSPACE_NAME_REQUIRED", "Workspace name is required.")
    db.add(workspace)
    db.commit()
    db.refresh(workspace)
    return _workspace_response(workspace, 0)


def update_workspace(db: Session, owner: User, workspace_id: UUID, request: UpdateWorkspaceRequest) -> WorkspaceResponse:
    workspace = _get_workspace(db, owner, workspace_id)
    workspace.name = request.name.strip()
    if not workspace.name:
        raise ApiError(422, "WORKSPACE_NAME_REQUIRED", "Workspace name is required.")
    db.commit()
    db.refresh(workspace)
    count = db.scalar(select(func.count(WorkspaceVideo.id)).where(WorkspaceVideo.workspace_id == workspace.id)) or 0
    return _workspace_response(workspace, count)


def delete_workspace(db: Session, owner: User, workspace_id: UUID) -> None:
    workspace = _get_workspace(db, owner, workspace_id)
    db.delete(workspace)
    db.commit()


def attach_video(db: Session, owner: User, workspace_id: UUID, video_id: UUID) -> None:
    workspace = _get_workspace(db, owner, workspace_id)
    video = db.scalar(select(Video).where(Video.id == video_id, Video.owner_id == owner.id))
    if not video:
        raise ApiError(404, "VIDEO_NOT_FOUND", "Video was not found.")
    existing = db.scalar(select(WorkspaceVideo).where(WorkspaceVideo.workspace_id == workspace.id, WorkspaceVideo.video_id == video.id))
    if existing:
        raise ApiError(409, "VIDEO_ALREADY_ATTACHED", "This video is already attached to the workspace.")
    db.add(WorkspaceVideo(id=uuid4(), workspace_id=workspace.id, video_id=video.id))
    db.commit()


def detach_video(db: Session, owner: User, workspace_id: UUID, video_id: UUID) -> None:
    workspace = _get_workspace(db, owner, workspace_id)
    result = db.execute(delete(WorkspaceVideo).where(WorkspaceVideo.workspace_id == workspace.id, WorkspaceVideo.video_id == video_id))
    if result.rowcount == 0:
        raise ApiError(404, "WORKSPACE_VIDEO_NOT_FOUND", "The video is not attached to this workspace.")
    db.commit()


def get_workspace(db: Session, owner: User, workspace_id: UUID) -> WorkspaceDetailResponse:
    workspace = _get_workspace(db, owner, workspace_id)
    rows = db.execute(
        select(Video, AnalysisSession, SummaryVideo, MediaAsset)
        .join(WorkspaceVideo, WorkspaceVideo.video_id == Video.id)
        .outerjoin(
            AnalysisSession,
            (AnalysisSession.video_id == Video.id) & (AnalysisSession.owner_id == owner.id),
        )
        .outerjoin(SummaryVideo, SummaryVideo.session_id == AnalysisSession.id)
        .outerjoin(MediaAsset, (MediaAsset.id == SummaryVideo.asset_id) & (MediaAsset.availability == "available"))
        .where(WorkspaceVideo.workspace_id == workspace.id, Video.owner_id == owner.id)
        .order_by(WorkspaceVideo.created_at, AnalysisSession.created_at.desc())
    ).all()

    videos: list[WorkspaceVideoResponse] = []
    selected: dict[UUID, tuple[Video, AnalysisSession | None, SummaryVideo | None]] = {}
    for video, session, summary_video, media_asset in rows:
        if video.id not in selected:
            selected[video.id] = (video, session, None)
        current_video, current_session, current_summary = selected[video.id]
        if current_summary is None and summary_video and summary_video.status == "completed" and summary_video.asset_id and media_asset:
            selected[video.id] = (current_video, current_session, summary_video)

    for video, session, summary_video in selected.values():
        summary = None
        if summary_video:
            summary = {
                "id": summary_video.id,
                "status": summary_video.status,
                "asset_id": summary_video.asset_id,
                "duration_seconds": float(summary_video.duration_seconds) if summary_video.duration_seconds is not None else None,
                "error": summary_video.error,
            }
        videos.append(WorkspaceVideoResponse(
            **video_response(video).model_dump(),
            analysis={"session_id": session.id, "status": session.status, "summary_video": summary} if session else None,
        ))
    return WorkspaceDetailResponse(
        **_workspace_response(workspace, len(videos)).model_dump(),
        videos=videos,
    )
