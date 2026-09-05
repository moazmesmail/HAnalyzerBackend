from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.features.identity.dependencies import csrf_protect, current_session
from app.features.identity.schemas import AuthResponse, Credentials, RegistrationResponse
from app.features.identity.service import check_auth_rate_limit, login, logout, register, user_response
from app.platform.config import Settings, get_settings
from app.platform.database import get_db

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=RegistrationResponse, status_code=201)
def register_route(
    request: Request,
    credentials: Credentials,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> RegistrationResponse:
    check_auth_rate_limit(
        db,
        "register",
        credentials.identity,
        request.client.host if request.client else "unknown",
        settings,
    )
    register(db, credentials.identity, credentials.password)
    return RegistrationResponse(status="pending")


@router.post("/login", response_model=AuthResponse)
def login_route(
    request: Request,
    credentials: Credentials,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthResponse:
    check_auth_rate_limit(
        db,
        "login",
        credentials.identity,
        request.client.host if request.client else "unknown",
        settings,
    )
    return login(db, credentials.identity, credentials.password, response, settings)


@router.get("/me", response_model=AuthResponse)
def me_route(
    session_data: Annotated[tuple, Depends(current_session)],
) -> AuthResponse:
    user, session, csrf, _ = session_data
    return AuthResponse(user=user_response(user, session.expires_at), csrf_token=csrf)


@router.post("/logout", status_code=204, dependencies=[Depends(csrf_protect)])
def logout_route(
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    session_data: Annotated[tuple, Depends(current_session)],
) -> None:
    _, session, _, _ = session_data
    logout(db, session, response, settings)
