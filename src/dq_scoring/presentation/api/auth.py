"""Authentication service managing Argon2id hashing, JWT, and Token Reuse Detection (AC-023)."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import HTTPException, status
from pydantic import BaseModel, ConfigDict

ph = PasswordHasher()

# Verified against when the email is unknown, so both paths cost one Argon2 verification
# and response timing does not reveal which accounts exist.
_TIMING_EQUALIZATION_HASH = ph.hash(secrets.token_urlsafe(16))


def hash_password(password: str) -> str:
    """Hash plaintext password using Argon2id."""
    return ph.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    """Verify password against an Argon2id hash; None (unknown user) never verifies."""
    try:
        return ph.verify(password_hash or _TIMING_EQUALIZATION_HASH, password) and password_hash is not None
    except (VerificationError, InvalidHashError):
        return False


class AuthenticatedUser(BaseModel):
    """Authenticated user context extracted from JWT access token."""

    model_config = ConfigDict(frozen=True)

    user_id: UUID
    tenant_id: UUID
    email: str
    role: str = "DATA_ENGINEER"


def create_access_token(
    user: AuthenticatedUser,
    secret_key: str,
    algorithm: str = "HS256",
    expires_minutes: int = 30,
) -> str:
    """Encode user claims into signed JWT access token."""
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user.user_id),
        "tenant_id": str(user.tenant_id),
        "email": user.email,
        "role": user.role,
        "iat": now,
        "exp": now + timedelta(minutes=expires_minutes),
    }
    return jwt.encode(payload, secret_key, algorithm=algorithm)


def decode_access_token(
    token: str, secret_key: str, algorithms: list[str] | None = None
) -> AuthenticatedUser:
    """Decode and validate JWT access token, returning AuthenticatedUser context."""
    if algorithms is None:
        algorithms = ["HS256"]
    try:
        payload = jwt.decode(token, secret_key, algorithms=algorithms)
        return AuthenticatedUser(
            user_id=UUID(payload["sub"]),
            tenant_id=UUID(payload["tenant_id"]),
            email=payload["email"],
            role=payload.get("role", "DATA_ENGINEER"),
        )
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Access token has expired.",
        ) from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid access token.",
        ) from exc

