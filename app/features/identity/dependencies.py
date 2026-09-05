from typing import Annotated

from fastapi import Cookie, Depends, Header, Request
from sqlalchemy.orm import Session

from app.features.identity.models import User, UserSession
from app.features.identity.service import load_session, session_cookie_name
from app.platform.config import Settings, get_settings
from app.platform.database import get_db
from app.platform.errors import ApiError
from app.platform.security import verify_csrf


def current_session(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    host_session: Annotated[str | None, Cookie(alias="__Host-session")] = None,
    dev_session: Annotated[str | None, Cookie(alias="dev-session")] = None,
) -> tuple[User, UserSession, str, str]:
    cookie_name = session_cookie_name(settings)
    token = host_session if cookie_name == "__Host-session" else dev_session
    if not token:
        raise ApiError(401, "SESSION_REQUIRED", "Login is required.")

    user, session, csrf = load_session(db, token, settings)
    request.state.session_token = token
    return user, session, csrf, token


def require_approved_user(
    session_data: Annotated[tuple[User, UserSession, str, str], Depends(current_session)],
) -> User:
    return session_data[0]


def require_admin(user: Annotated[User, Depends(require_approved_user)]) -> User:
    if user.role != "admin":
        raise ApiError(403, "ADMIN_REQUIRED", "Administrator access is required.")
    return user


def csrf_protect(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    session_data: Annotated[tuple[User, UserSession, str, str], Depends(current_session)],
    x_csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
    ) -> None:
    origin = request.headers.get("origin")
    if origin and not settings.is_allowed_origin(origin):
        raise ApiError(403, "INVALID_ORIGIN", "Request origin is not allowed.")

    if not x_csrf_token:
        raise ApiError(403, "CSRF_REQUIRED", "CSRF token is required.")

    _, _, _, session_token = session_data
    if not verify_csrf(session_token, x_csrf_token, settings.csrf_secret):
        raise ApiError(403, "CSRF_INVALID", "CSRF token is invalid.")
