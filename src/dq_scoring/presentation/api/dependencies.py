"""FastAPI dependency injection providers."""

from __future__ import annotations

import os
from collections.abc import Generator
from functools import lru_cache
from uuid import UUID

import psycopg
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from dq_scoring.adapters.db.postgres_assessment_store import (
    PostgresAssessmentStoreAdapter,
)
from dq_scoring.adapters.db.tenant_context import (
    clear_tenant_context,
    set_tenant_context,
)
from dq_scoring.adapters.queue.postgres_queue import PostgresQueueAdapter
from dq_scoring.common.protected_transport import (
    protected_connect,
    require_protected_dsn,
    validate_protected_runtime,
)
from dq_scoring.ports.assessment_store import IAssessmentStorePort
from dq_scoring.ports.queue_port import IQueuePort
from dq_scoring.presentation.api.auth import AuthenticatedUser, decode_access_token
from dq_scoring.presentation.api.config import ApiSettings, get_api_settings

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")
oauth2_scheme_optional = OAuth2PasswordBearer(
    tokenUrl="/api/v1/auth/login", auto_error=False
)


class PrivilegedSessionError(psycopg.errors.InsufficientPrivilege, PermissionError):
    """Raised when an API database connection attempts to use a privileged session_user."""


@lru_cache(maxsize=1)
def _validate_api_protected_runtime() -> None:
    validate_protected_runtime("api")


def get_pg_dsn(settings: ApiSettings = Depends(get_api_settings)) -> str:
    """Return active PostgreSQL DSN from environment override or settings."""
    _validate_api_protected_runtime()
    dsn = os.getenv("DQ_RUNTIME_POSTGRES_DSN") or settings.postgres_dsn
    return require_protected_dsn(dsn)


def get_optional_user(
    token: str | None = Depends(oauth2_scheme_optional),
    settings: ApiSettings = Depends(get_api_settings),
) -> AuthenticatedUser | None:
    """Extract AuthenticatedUser if valid bearer token is present, else None."""
    if not token:
        return None
    try:
        return decode_access_token(
            token=token,
            secret_key=settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
    except HTTPException:
        return None


def validate_api_session(conn: psycopg.Connection) -> None:
    row = conn.execute(
        "SELECT session_user,current_user,r.rolsuper,r.rolbypassrls,current_setting('is_superuser') "
        "FROM pg_roles r WHERE r.rolname=session_user"
    ).fetchone()
    if (
        not row
        or row[0] == "dq_app_role"
        or row[1] == "dq_app_role"
        or row[2]
        or row[3]
        or row[4] == "on"
    ):
        raise PrivilegedSessionError(
            "Privileged session_user is not permitted for API database connections."
        )


def get_db_connection(
    dsn: str = Depends(get_pg_dsn),
    user: AuthenticatedUser | None = Depends(get_optional_user),
) -> Generator[psycopg.Connection]:
    """Yield active database connection with RLS role and transaction-scoped tenant isolation."""
    with protected_connect(dsn, autocommit=False) as conn, conn.transaction():
        validate_api_session(conn)

        conn.execute("SET LOCAL ROLE dq_app_role;")
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.current_user_id', '', true);")
        if user is not None:
            set_tenant_context(conn, user.tenant_id)
        else:
            clear_tenant_context(conn)
        yield conn


def get_assessment_store(
    dsn: str = Depends(get_pg_dsn),
) -> IAssessmentStorePort:
    """Provide assessment store adapter."""
    return PostgresAssessmentStoreAdapter(dsn)


def get_queue_port(
    conn: psycopg.Connection = Depends(get_db_connection),
) -> IQueuePort:
    """Provide queue adapter bound to the tenant-scoped request transaction."""
    return PostgresQueueAdapter(connection=conn)


def get_current_user(
    token: str = Depends(oauth2_scheme),
    settings: ApiSettings = Depends(get_api_settings),
) -> AuthenticatedUser:
    """Validate bearer token and extract AuthenticatedUser context."""
    return decode_access_token(
        token=token,
        secret_key=settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
    )


def get_current_tenant_id(
    user: AuthenticatedUser = Depends(get_current_user),
) -> UUID:
    """Extract authenticated tenant ID."""
    return user.tenant_id


def check_tenant_access(
    resource_tenant_id: UUID,
    current_tenant_id: UUID,
) -> None:
    """AC-020: Enforce strict internal Tenant isolation (Anti-BOLA)."""
    if resource_tenant_id != current_tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Requested resource was not found.",
        )
