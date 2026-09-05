from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=1024)


class CurrentUser(BaseModel):
    id: UUID
    email: EmailStr
    role: str
    session_expires_at: datetime | None = None


class AuthResponse(BaseModel):
    user: CurrentUser
    csrf_token: str


class RegistrationResponse(BaseModel):
    status: str


class RegistrationReview(BaseModel):
    id: UUID
    email: EmailStr
    status: str
    created_at: datetime


class PaginatedRegistrations(BaseModel):
    items: list[RegistrationReview]
    next_cursor: str | None = None


class RegistrationDecisionRequest(BaseModel):
    decision: str
