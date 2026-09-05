from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.features.identity.models import User, UserSession


def get_user_by_email(db: Session, email_normalized: str) -> User | None:
    return db.scalar(select(User).where(User.email_normalized == email_normalized))


def get_user(db: Session, user_id: UUID) -> User | None:
    return db.get(User, user_id)


def get_session_by_hash(db: Session, token_hash: str) -> UserSession | None:
    return db.scalar(select(UserSession).where(UserSession.token_hash == token_hash))


def list_pending_users(db: Session, limit: int = 50) -> list[User]:
    return list(
        db.scalars(
            select(User)
            .where(User.approval_status == "pending")
            .order_by(User.created_at.asc())
            .limit(limit)
        )
    )
