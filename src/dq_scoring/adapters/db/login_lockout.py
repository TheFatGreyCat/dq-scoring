"""Consecutive failed-login tracking and temporary account lockout (FR-AUTH-004)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

import psycopg


def record_failed_login(
    conn: psycopg.Connection, user_id: UUID, max_attempts: int, lockout_minutes: int
) -> datetime | None:
    """Count one failure atomically; return the new `locked_until` if this failure locked the account.

    Locking resets the counter, so after the lock expires the user gets a fresh set of attempts.
    """
    row = conn.execute(
        """
        UPDATE users SET
            locked_until = CASE WHEN failed_login_attempts + 1 >= %(max)s
                THEN now() + make_interval(mins => %(mins)s::int) ELSE locked_until END,
            failed_login_attempts = CASE WHEN failed_login_attempts + 1 >= %(max)s
                THEN 0 ELSE failed_login_attempts + 1 END
        WHERE user_id = %(user_id)s
        RETURNING CASE WHEN failed_login_attempts = 0 THEN locked_until END;
        """,
        {"max": max_attempts, "mins": lockout_minutes, "user_id": user_id},
    ).fetchone()
    return row[0] if row else None


def reset_failed_logins(conn: psycopg.Connection, user_id: UUID) -> None:
    conn.execute(
        "UPDATE users SET failed_login_attempts = 0, locked_until = NULL WHERE user_id = %s;",
        (user_id,),
    )
