"""FR-AUTH-004 login lockout: consecutive failures lock the account (synthetic data only)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from dq_scoring.presentation.api.auth import hash_password

PASSWORD = "Synthetic-Password-123!"


@pytest.fixture
def account(db_conn) -> tuple[str, UUID]:
    tenant_id, user_id = uuid4(), uuid4()
    email = f"lockout_{user_id.hex[:8]}@example.com"
    with db_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO tenants (tenant_id, tenant_code, tenant_name, subscription_tier, status) VALUES (%s, %s, 'Lockout Org', 'ENTERPRISE', 'ACTIVE');",
            (tenant_id, f"lock_{tenant_id.hex[:8]}"),
        )
        cur.execute(
            "INSERT INTO users (user_id, email, password_hash, full_name, is_active) VALUES (%s, %s, %s, 'Synthetic User', TRUE);",
            (user_id, email, hash_password(PASSWORD)),
        )
        cur.execute(
            "INSERT INTO tenant_memberships (tenant_id, user_id, role, status) VALUES (%s, %s, 'DATA_ENGINEER', 'ACTIVE');",
            (tenant_id, user_id),
        )
    db_conn.commit()
    return email, user_id


def _login(client: TestClient, email: str, password: str):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


def test_fifth_failure_locks_and_returns_423(client, account, db_conn) -> None:
    email, user_id = account
    assert [_login(client, email, "wrong").status_code for _ in range(4)] == [401] * 4
    locked = _login(client, email, "wrong")
    assert locked.status_code == 423
    body = locked.json()
    assert body["reason"] == "TOO_MANY_FAILED_ATTEMPTS" and body["max_failed_attempts"] == 5
    assert 14 * 60 < body["retry_after_seconds"] <= 15 * 60
    assert locked.headers["Retry-After"] == str(body["retry_after_seconds"])
    assert body["locked_until"].endswith("Z")
    until, attempts = db_conn.execute(
        "SELECT locked_until - now(), failed_login_attempts FROM users WHERE user_id = %s;", (user_id,)
    ).fetchone()
    assert timedelta(minutes=14) < until <= timedelta(minutes=15) and attempts == 0


def test_locked_account_returns_423_regardless_of_password(client, account, db_conn) -> None:
    email, user_id = account
    for _ in range(5):
        _login(client, email, "wrong")
    before = db_conn.execute("SELECT locked_until FROM users WHERE user_id = %s;", (user_id,)).fetchone()[0]
    db_conn.commit()
    right, wrong = _login(client, email, PASSWORD), _login(client, email, "wrong")
    assert right.status_code == wrong.status_code == 423
    assert {k: v for k, v in right.json().items() if k != "retry_after_seconds"} == {
        k: v for k, v in wrong.json().items() if k != "retry_after_seconds"
    }
    assert db_conn.execute("SELECT locked_until FROM users WHERE user_id = %s;", (user_id,)).fetchone()[0] == before


def test_login_succeeds_after_lock_expires_and_resets_state(client, account, db_conn) -> None:
    email, user_id = account
    db_conn.execute(
        "UPDATE users SET locked_until = now() - interval '1 second', failed_login_attempts = 3 WHERE user_id = %s;",
        (user_id,),
    )
    db_conn.commit()
    assert _login(client, email, PASSWORD).status_code == 200
    assert db_conn.execute(
        "SELECT failed_login_attempts, locked_until FROM users WHERE user_id = %s;", (user_id,)
    ).fetchone() == (0, None)


def test_success_resets_the_consecutive_counter(client, account) -> None:
    email, _ = account
    for _ in range(4):
        _login(client, email, "wrong")
    assert _login(client, email, PASSWORD).status_code == 200
    for _ in range(4):
        _login(client, email, "wrong")
    assert _login(client, email, PASSWORD).status_code == 200


def test_unknown_email_failures_stay_plain_401(client) -> None:
    email = f"nobody_{uuid4().hex[:8]}@example.com"
    assert {_login(client, email, "wrong").status_code for _ in range(6)} == {401}


def test_concurrent_failures_still_lock_account(client, account) -> None:
    email, _ = account
    with ThreadPoolExecutor(max_workers=5) as pool:
        list(pool.map(lambda _: _login(client, email, "wrong"), range(5)))
    assert _login(client, email, PASSWORD).status_code == 423


def test_login_email_is_case_insensitive(client, account) -> None:
    email, _ = account
    assert _login(client, email.upper(), PASSWORD).status_code == 200


def test_case_variant_email_cannot_be_inserted(account, db_conn) -> None:
    email, _ = account
    with pytest.raises(psycopg.errors.UniqueViolation):
        db_conn.execute(
            "INSERT INTO users (user_id, email, password_hash, full_name, is_active) VALUES (%s, %s, 'x', 'Synthetic User', TRUE);",
            (uuid4(), email.upper()),
        )
    db_conn.rollback()


def test_lockout_counts_across_email_casing(client, account) -> None:
    email, _ = account
    for _ in range(3):
        _login(client, email, "wrong")
    assert _login(client, email.upper(), "wrong").status_code == 401
    assert _login(client, email.upper(), "wrong").status_code == 423
