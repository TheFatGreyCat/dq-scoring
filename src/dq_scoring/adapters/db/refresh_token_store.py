"""Persistent refresh-token families with rotation and reuse detection (AC-023).

Raw tokens are random opaque strings returned to the client once; only their SHA-256
is stored. Rotation re-reads the user's current account and membership so a refresh
never resurrects a deactivated user or a stale role.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import psycopg

REFRESH_TOKEN_BYTES = 32
"""Entropy of each opaque refresh token (256 bits)."""


class RefreshTokenRejected(Exception):
    """The presented refresh token cannot be rotated; the client must sign in again."""


@dataclass(frozen=True)
class RefreshedIdentity:
    user_id: UUID
    tenant_id: UUID
    email: str
    role: str


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_refresh_token(
    conn: psycopg.Connection,
    user_id: UUID,
    tenant_id: UUID,
    expires_in_days: int,
    family_id: UUID | None = None,
) -> str:
    """Create a token (new family unless one is given) and return the raw value."""
    token = secrets.token_urlsafe(REFRESH_TOKEN_BYTES)
    now = datetime.now(UTC)
    conn.execute(
        """
        INSERT INTO refresh_tokens (token_hash, family_id, user_id, tenant_id, issued_at, expires_at)
        VALUES (%s, %s, %s, %s, %s, %s);
        """,
        (_hash(token), family_id or uuid4(), user_id, tenant_id, now, now + timedelta(days=expires_in_days)),
    )
    return token


def _revoke_family(conn: psycopg.Connection, family_id: UUID) -> None:
    conn.execute(
        "UPDATE refresh_tokens SET revoked_at = now() WHERE family_id = %s AND revoked_at IS NULL;",
        (family_id,),
    )


def rotate_refresh_token(
    conn: psycopg.Connection, token: str, expires_in_days: int
) -> tuple[str, RefreshedIdentity]:
    """Consume a token and issue its successor, or raise RefreshTokenRejected.

    Replaying an already-used token revokes the whole family. The caller must commit
    that revocation even though the request is rejected.
    """
    row = conn.execute(
        """
        SELECT family_id, user_id, tenant_id, expires_at, used_at, revoked_at
        FROM refresh_tokens WHERE token_hash = %s FOR UPDATE;
        """,
        (_hash(token),),
    ).fetchone()
    if row is None:
        raise RefreshTokenRejected("Invalid refresh token.")
    family_id, user_id, tenant_id, expires_at, used_at, revoked_at = row
    if revoked_at is not None:
        raise RefreshTokenRejected("Refresh token has been revoked.")
    if used_at is not None:
        _revoke_family(conn, family_id)
        raise RefreshTokenRejected("Suspicious refresh token reuse detected. Session invalidated.")
    if expires_at < datetime.now(UTC):
        raise RefreshTokenRejected("Refresh token has expired.")

    conn.execute("UPDATE refresh_tokens SET used_at = now() WHERE token_hash = %s;", (_hash(token),))

    # Membership rows are readable only for the current user under RLS.
    conn.execute("SELECT set_config('app.current_user_id', %s, true);", (str(user_id),))
    identity = conn.execute(
        """
        SELECT u.email, m.role
        FROM users u
        JOIN tenant_memberships m ON m.user_id = u.user_id
        WHERE u.user_id = %s AND u.is_active AND m.tenant_id = %s AND m.status = 'ACTIVE';
        """,
        (user_id, tenant_id),
    ).fetchone()
    if identity is None:
        _revoke_family(conn, family_id)
        raise RefreshTokenRejected("Account or workspace membership is no longer active.")

    new_token = issue_refresh_token(conn, user_id, tenant_id, expires_in_days, family_id=family_id)
    return new_token, RefreshedIdentity(user_id=user_id, tenant_id=tenant_id, email=identity[0], role=identity[1])


def revoke_refresh_token(conn: psycopg.Connection, token: str) -> None:
    """Revoke the presented token's whole family (sign-out ends the session everywhere it was rotated)."""
    row = conn.execute("SELECT family_id FROM refresh_tokens WHERE token_hash = %s;", (_hash(token),)).fetchone()
    if row is not None:
        _revoke_family(conn, row[0])
