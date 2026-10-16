"""Unit tests for authentication and token reuse detection."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException

from dq_scoring.presentation.api.auth import (
    AuthenticatedUser,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_argon2_password_hashing():
    """Verify password hashing and verification with Argon2id."""
    password = "SuperSecretSecurePassword!123"
    pwd_hash = hash_password(password)
    assert pwd_hash.startswith("$argon2id$")
    assert verify_password(pwd_hash, password)
    assert not verify_password(pwd_hash, "WrongPassword")
    assert not verify_password("not-an-argon2-hash", password)


def test_jwt_lifecycle_and_expiration():
    """Verify JWT access token encoding, decoding, and expiration."""
    user = AuthenticatedUser(
        user_id=uuid4(),
        tenant_id=uuid4(),
        email="dev@example.com",
        role="WORKSPACE_ADMIN",
    )
    secret = "test-jwt-secret-key-32-chars-long-minimum"

    token = create_access_token(user, secret, expires_minutes=1)
    decoded = decode_access_token(token, secret)
    assert decoded.user_id == user.user_id
    assert decoded.tenant_id == user.tenant_id
    assert decoded.email == user.email

    # Expired token test
    expired_token = create_access_token(user, secret, expires_minutes=-1)
    with pytest.raises(HTTPException) as exc_info:
        decode_access_token(expired_token, secret)
    assert exc_info.value.status_code == 401
    assert "expired" in exc_info.value.detail.lower()
