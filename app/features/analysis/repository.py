from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.features.analysis.models import AnalysisFrame, AnalysisObservation, AnalysisSession, ModelRequest


def get_owner_session(db: Session, owner_id: UUID, session_id: UUID) -> AnalysisSession | None:
    return db.scalar(select(AnalysisSession).where(AnalysisSession.id == session_id, AnalysisSession.owner_id == owner_id))


def list_video_sessions(db: Session, owner_id: UUID, video_id: UUID) -> list[AnalysisSession]:
    return list(db.scalars(select(AnalysisSession).where(AnalysisSession.owner_id == owner_id, AnalysisSession.video_id == video_id).order_by(AnalysisSession.created_at.desc())))


def list_frames(db: Session, session_id: UUID) -> list[AnalysisFrame]:
    return list(db.scalars(select(AnalysisFrame).where(AnalysisFrame.session_id == session_id).order_by(AnalysisFrame.timestamp_seconds)))


def list_observations(db: Session, session_id: UUID) -> list[AnalysisObservation]:
    return list(db.scalars(select(AnalysisObservation).where(AnalysisObservation.session_id == session_id).order_by(AnalysisObservation.start_seconds)))


def list_model_requests(db: Session, session_id: UUID) -> list[ModelRequest]:
    return list(db.scalars(select(ModelRequest).where(ModelRequest.session_id == session_id).order_by(ModelRequest.created_at)))
