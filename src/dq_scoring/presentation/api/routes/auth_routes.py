"""Authentication routes handling login, token refresh, and logout."""

from __future__ import annotations

import math
from datetime import UTC, datetime

import psycopg
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse

from dq_scoring.adapters.db.login_lockout import (
    record_failed_login,
    reset_failed_logins,
)
from dq_scoring.adapters.db.refresh_token_store import (
    RefreshTokenRejected,
    issue_refresh_token,
    revoke_refresh_token,
    rotate_refresh_token,
)
from dq_scoring.presentation.api.auth import (
    AuthenticatedUser,
    create_access_token,
    verify_password,
)
from dq_scoring.presentation.api.config import ApiSettings, get_api_settings
from dq_scoring.presentation.api.dependencies import get_current_user, get_db_connection
from dq_scoring.presentation.api.errors import create_problem_response
from dq_scoring.presentation.api.schemas.auth_schemas import (
    LoginRequest,
    RefreshTokenRequest,
    TokenResponse,
)

INVALID_CREDENTIALS = "Invalid email or password."
LOGIN_PATH = "/api/v1/auth/login"

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])


@router.get("/me", response_model=AuthenticatedUser)
def current_identity(user: AuthenticatedUser = Depends(get_current_user)) -> AuthenticatedUser:
    return user


def _invalid_credentials() -> JSONResponse:
    return create_problem_response(
        status_code=status.HTTP_401_UNAUTHORIZED,
        title="Unauthorized",
        detail=INVALID_CREDENTIALS,
        type_uri="urn:dq-scoring:error:401",
        instance=LOGIN_PATH,
    )


def _locked_response(locked_until: datetime, max_attempts: int) -> JSONResponse:
    retry_after = max(1, math.ceil((locked_until - datetime.now(UTC)).total_seconds()))
    return create_problem_response(
        status_code=status.HTTP_423_LOCKED,
        title="Account locked",
        detail="Too many failed sign-in attempts. Try again later.",
        type_uri="urn:dq-scoring:error:423",
        instance=LOGIN_PATH,
        extensions={
            "reason": "TOO_MANY_FAILED_ATTEMPTS",
            "max_failed_attempts": max_attempts,
            "locked_until": locked_until.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "retry_after_seconds": retry_after,
        },
        headers={"Retry-After": str(retry_after)},
    )


@router.post("/login", response_model=TokenResponse)
def login(
    req: LoginRequest,
    conn: psycopg.Connection = Depends(get_db_connection),
    settings: ApiSettings = Depends(get_api_settings),
) -> TokenResponse | JSONResponse:
    """Authenticate user with email and password, issuing access & refresh tokens.

    Failure responses are returned, not raised, so the failed-attempt counter commits.
    """
    with conn.cursor() as cur:
        # FOR UPDATE serializes concurrent attempts on one account so no failure is lost.
        cur.execute(
            """
            SELECT user_id, password_hash, is_active, locked_until
            FROM users
            WHERE lower(email) = lower(%s)
            LIMIT 1
            FOR UPDATE;
            """,
            (req.email,),
        )
        row = cur.fetchone()
        # Always verify (against a dummy hash for unknown emails) and check the password
        # before revealing account state, so responses do not enumerate accounts.
        password_ok = verify_password(row[1] if row else None, req.password)
        if not row:
            return _invalid_credentials()
        u_id, _pwd_hash, is_active, locked_until = row
        if locked_until is not None and locked_until > datetime.now(UTC):
            return _locked_response(locked_until, settings.login_max_failed_attempts)
        if not password_ok:
            new_lock = record_failed_login(
                conn, u_id, settings.login_max_failed_attempts, settings.login_lockout_minutes
            )
            if new_lock is not None:
                return _locked_response(new_lock, settings.login_max_failed_attempts)
            return _invalid_credentials()
        reset_failed_logins(conn, u_id)
        if not is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is deactivated.",
            )
        # Set app.current_user_id locally in the transaction so RLS permits
        # the verified user to read their own active tenant memberships.
        cur.execute("SELECT set_config('app.current_user_id', %s, true);", (str(u_id),))

        if req.tenant_id:
            cur.execute(
                """
                SELECT tenant_id, role
                FROM tenant_memberships
                WHERE user_id = %s AND tenant_id = %s AND status = 'ACTIVE'
                LIMIT 1;
                """,
                (u_id, req.tenant_id),
            )
            t_row = cur.fetchone()
            if not t_row:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="User does not have active membership in requested tenant.",
                )
            t_id, role = t_row
        else:
            cur.execute(
                """
                SELECT tenant_id, role
                FROM tenant_memberships
                WHERE user_id = %s AND status = 'ACTIVE'
                ORDER BY joined_at ASC
                LIMIT 1;
                """,
                (u_id,),
            )
            t_row = cur.fetchone()
            if not t_row:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="User does not have active membership in any tenant.",
                )
            t_id, role = t_row
    user = AuthenticatedUser(
        user_id=u_id,
        tenant_id=t_id,
        email=req.email,
        role=role,
    )
    access_token = create_access_token(
        user=user,
        secret_key=settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
        expires_minutes=settings.access_token_expire_minutes,
    )
    refresh_token = issue_refresh_token(
        conn,
        user_id=u_id,
        tenant_id=t_id,
        expires_in_days=settings.refresh_token_expire_days,
    )

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=settings.access_token_expire_minutes * 60,
        refresh_token=refresh_token,
    )


@router.post("/refresh", response_model=TokenResponse)
def refresh_token(
    req: RefreshTokenRequest,
    conn: psycopg.Connection = Depends(get_db_connection),
    settings: ApiSettings = Depends(get_api_settings),
) -> TokenResponse | JSONResponse:
    """AC-023: Rotate refresh token with persistent family reuse detection."""
    try:
        new_token, identity = rotate_refresh_token(
            conn, req.refresh_token, expires_in_days=settings.refresh_token_expire_days
        )
    except RefreshTokenRejected as exc:
        # Returned, not raised: a reuse-triggered family revocation must be committed.
        return create_problem_response(
            status_code=status.HTTP_401_UNAUTHORIZED,
            title="Unauthorized",
            detail=str(exc),
            type_uri="urn:dq-scoring:error:401",
            instance="/api/v1/auth/refresh",
        )
    user = AuthenticatedUser(
        user_id=identity.user_id,
        tenant_id=identity.tenant_id,
        email=identity.email,
        role=identity.role,
    )
    access_token = create_access_token(
        user=user,
        secret_key=settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
        expires_minutes=settings.access_token_expire_minutes,
    )
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=settings.access_token_expire_minutes * 60,
        refresh_token=new_token,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    req: RefreshTokenRequest,
    conn: psycopg.Connection = Depends(get_db_connection),
) -> None:
    """Revoke the refresh-token family; unknown tokens are ignored (idempotent sign-out)."""
    revoke_refresh_token(conn, req.refresh_token)
