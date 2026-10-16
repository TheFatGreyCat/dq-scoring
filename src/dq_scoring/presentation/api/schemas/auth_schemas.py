"""Authentication request and response schemas."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    """User login request payload."""

    email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=1)
    tenant_id: UUID | None = None



class TokenResponse(BaseModel):
    """Token response payload upon successful authentication or refresh."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int = 1800
    refresh_token: str


class RefreshTokenRequest(BaseModel):
    """Refresh token request payload."""

    refresh_token: str


class UserResponse(BaseModel):
    """Public user profile response."""

    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    tenant_id: UUID
    email: str
    full_name: str
    role: str
