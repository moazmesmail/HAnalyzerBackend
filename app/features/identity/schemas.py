from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class Credentials(BaseModel):
    identity: str = Field(min_length=4, max_length=64)
    password: str = Field(min_length=1, max_length=1024)

    @field_validator("identity")
    @classmethod
    def validate_identity(cls, value: str) -> str:
        normalized = value.strip().lower()
        if len(normalized) < 4:
            raise ValueError("Identity must contain more than 3 characters.")
        return normalized


class RegistrationCredentials(Credentials):
    password: str = Field(min_length=8, max_length=1024)


class CurrentUser(BaseModel):
    id: UUID
    identity: str
    role: Literal["user", "coach", "admin"]
    session_expires_at: datetime | None = None


class AuthResponse(BaseModel):
    user: CurrentUser
    csrf_token: str


class RegistrationResponse(BaseModel):
    status: str


class RegistrationReview(BaseModel):
    id: UUID
    identity: str
    status: str
    created_at: datetime


class PaginatedRegistrations(BaseModel):
    items: list[RegistrationReview]
    next_cursor: str | None = None


class RegistrationDecisionRequest(BaseModel):
    decision: str
