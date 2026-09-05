from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.features.identity.dependencies import csrf_protect, require_admin
from app.features.identity.models import User
from app.features.identity.repository import list_pending_users
from app.features.identity.schemas import (
    PaginatedRegistrations,
    RegistrationDecisionRequest,
    RegistrationReview,
)
from app.features.identity.service import decide_registration, registration_review
from app.platform.database import get_db

router = APIRouter(prefix="/admin/registrations", tags=["admin"])


@router.get("", response_model=PaginatedRegistrations)
def list_registrations_route(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_admin)],
    status: str = "pending",
) -> PaginatedRegistrations:
    if status != "pending":
        return PaginatedRegistrations(items=[], next_cursor=None)

    return PaginatedRegistrations(
        items=[registration_review(user) for user in list_pending_users(db)],
        next_cursor=None,
    )


@router.post("/{user_id}/decision", response_model=RegistrationReview, dependencies=[Depends(csrf_protect)])
def decide_registration_route(
    user_id: UUID,
    body: RegistrationDecisionRequest,
    db: Annotated[Session, Depends(get_db)],
    administrator: Annotated[User, Depends(require_admin)],
) -> RegistrationReview:
    return decide_registration(db, user_id, body.decision, administrator)
