from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.features.identity.models import ApprovalDecision, AuthRateLimit, User, UserSession
from app.features.identity.repository import get_session_by_hash, get_user, get_user_by_email
from app.features.identity.schemas import AuthResponse, CurrentUser, RegistrationReview
from app.platform.config import Settings
from app.platform.errors import ApiError
from app.platform.security import csrf_token, hash_password, random_token, sha256_text, verify_password


def normalize_email(email: str) -> str:
    return email.strip().lower()


def session_cookie_name(settings: Settings) -> str:
    return settings.session_cookie_name if settings.secure_cookies else settings.dev_session_cookie_name


def user_response(user: User, expires_at: datetime | None = None) -> CurrentUser:
    return CurrentUser(
        id=user.id,
        email=user.email_normalized,
        role=user.role,
        session_expires_at=expires_at,
    )


def check_auth_rate_limit(
    db: Session,
    action: str,
    email: str,
    client_host: str,
    settings: Settings,
) -> None:
    now = datetime.now(UTC)
    subject = sha256_text(f"{action}:{client_host}:{normalize_email(email)}")
    window = timedelta(seconds=settings.auth_rate_limit_window_seconds)
    limit = db.scalar(
        select(AuthRateLimit).where(
            AuthRateLimit.subject_key == subject,
            AuthRateLimit.action == action,
        )
    )

    if not limit or limit.expires_at <= now:
        if not limit:
            limit = AuthRateLimit(subject_key=subject, action=action)
            db.add(limit)
        limit.window_start = now
        limit.expires_at = now + window
        limit.attempts = 1
        db.commit()
        return

    limit.attempts += 1
    db.commit()

    if limit.attempts > settings.auth_rate_limit_attempts:
        raise ApiError(429, "RATE_LIMITED", "Too many attempts. Try again later.")


def register(db: Session, email: str, password: str) -> None:
    user = User(
        email_normalized=normalize_email(email),
        password_hash=hash_password(password),
        role="user",
        approval_status="pending",
    )
    db.add(user)

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ApiError(409, "REGISTRATION_EXISTS", "This email already has a registration.") from exc


def create_session_response(db: Session, user: User, response: Response, settings: Settings) -> AuthResponse:
    token = random_token()
    now = datetime.now(UTC)
    expires_at = now + timedelta(minutes=settings.session_absolute_minutes)
    csrf = csrf_token(token, settings.csrf_secret)
    session = UserSession(
        user_id=user.id,
        token_hash=sha256_text(token),
        csrf_hash=sha256_text(csrf),
        expires_at=expires_at,
        last_seen_at=now,
    )
    db.add(session)
    db.commit()

    response.set_cookie(
        session_cookie_name(settings),
        token,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        max_age=settings.session_absolute_minutes * 60,
        path="/",
    )
    return AuthResponse(user=user_response(user, expires_at), csrf_token=csrf)


def login(db: Session, email: str, password: str, response: Response, settings: Settings) -> AuthResponse:
    user = get_user_by_email(db, normalize_email(email))
    if not user or not verify_password(password, user.password_hash):
        raise ApiError(401, "INVALID_CREDENTIALS", "Invalid email or password.")

    if user.approval_status == "pending":
        raise ApiError(403, "ACCOUNT_PENDING", "This account is waiting for owner approval.")

    if user.approval_status == "rejected":
        raise ApiError(403, "ACCOUNT_REJECTED", "This account was rejected.")

    return create_session_response(db, user, response, settings)


def load_session(db: Session, token: str, settings: Settings) -> tuple[User, UserSession, str]:
    session = get_session_by_hash(db, sha256_text(token))
    now = datetime.now(UTC)

    if not session or session.revoked_at or session.expires_at <= now:
        raise ApiError(401, "SESSION_REQUIRED", "Login is required.")

    user = get_user(db, session.user_id)
    if not user or user.approval_status != "approved":
        raise ApiError(401, "SESSION_REQUIRED", "Login is required.")

    csrf = csrf_token(token, settings.csrf_secret)
    session.last_seen_at = now
    db.commit()
    return user, session, csrf


def logout(db: Session, session: UserSession, response: Response, settings: Settings) -> None:
    session.revoked_at = datetime.now(UTC)
    db.commit()
    response.delete_cookie(session_cookie_name(settings), path="/")


def decide_registration(
    db: Session,
    target_user_id: UUID,
    decision: str,
    administrator: User,
) -> RegistrationReview:
    if decision not in {"approved", "rejected"}:
        raise ApiError(422, "INVALID_DECISION", "Decision must be approved or rejected.")

    target = db.get(User, target_user_id)
    if not target:
        raise ApiError(404, "REGISTRATION_NOT_FOUND", "Registration was not found.")

    if target.approval_status != "pending":
        if target.approval_status == decision:
            return registration_review(target)
        raise ApiError(409, "REGISTRATION_ALREADY_DECIDED", "Registration was already decided.")

    target.approval_status = decision
    if decision == "approved":
        target.approved_at = datetime.now(UTC)

    db.add(
        ApprovalDecision(
            user_id=target.id,
            administrator_id=administrator.id,
            decision=decision,
        )
    )
    db.commit()
    db.refresh(target)
    return registration_review(target)


def registration_review(user: User) -> RegistrationReview:
    return RegistrationReview(
        id=user.id,
        email=user.email_normalized,
        status=user.approval_status,
        created_at=user.created_at,
    )
