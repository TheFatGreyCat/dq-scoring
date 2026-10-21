"""Durable FULL profiling boundaries against real PostgreSQL runtime roles."""
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

import psycopg
import pytest

from dq_scoring.adapters.db.tenant_context import set_tenant_context
from tests.support.object_snapshots import register_snapshot_via_api


@pytest.fixture
def profile_role_dsn(pg_dsn):
    import secrets

    from psycopg import sql

    created = []

    def login(group):
        name, password = f"profile_test_{uuid4().hex}", secrets.token_hex(24)
        with psycopg.connect(pg_dsn, autocommit=True) as conn:
            conn.execute(sql.SQL("CREATE ROLE {} LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD {} IN ROLE {}").format(
                sql.Identifier(name), sql.Literal(password), sql.Identifier(group)))
        created.append(name)
        return psycopg.conninfo.make_conninfo(pg_dsn, user=name, password=password)

    yield login
    with psycopg.connect(pg_dsn, autocommit=True) as conn:
        for name in created:
            conn.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(name)))


@pytest.fixture
def profile_worker_dsn(profile_role_dsn):
    return profile_role_dsn("dq_worker_role")


@pytest.fixture
def profile_dispatcher_dsn(profile_role_dsn):
    return profile_role_dsn("dq_dispatcher_role")


def _registered(client, tenant):
    return register_snapshot_via_api(client, tenant.creator, content_or_path=b"id,amount\nA,12\nB,\n")


def test_registration_enqueues_one_current_full_job(client, tenant, db_conn):
    snap = _registered(client, tenant)
    rows = db_conn.execute(
        "SELECT state, profiler_version, fingerprint, result FROM snapshot_profile_jobs WHERE snapshot_id=%s",
        (snap["snapshot_id"],),
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "QUEUED" and rows[0][3] is None
    assert len(rows[0][2]) == 64


def test_runtime_app_cannot_forge_profile_publication(client, tenant, non_superuser_dsn):
    snap = _registered(client, tenant)
    for statement in (
        "UPDATE snapshot_profile_jobs SET state='COMPLETE',result='{}' WHERE snapshot_id=%s",
        "UPDATE snapshot_profile_jobs SET lease_owner='forged',lease_generation=9 WHERE snapshot_id=%s",
        "DELETE FROM snapshot_profile_jobs WHERE snapshot_id=%s",
    ):
        with psycopg.connect(non_superuser_dsn) as conn:
            set_tenant_context(conn, tenant.tenant_id)
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(statement, (snap["snapshot_id"],))


def test_tenant_read_isolation(client, tenant, non_superuser_dsn):
    snap = _registered(client, tenant)
    with psycopg.connect(non_superuser_dsn) as conn:
        set_tenant_context(conn, uuid4())
        assert conn.execute("SELECT profile_id FROM snapshot_profile_jobs WHERE snapshot_id=%s", (snap["snapshot_id"],)).fetchall() == []


def test_concurrent_ensure_is_idempotent(client, tenant, non_superuser_dsn, db_conn):
    from dq_scoring.services.snapshot_profile_service import ensure_full_profile
    snap = _registered(client, tenant)
    db_conn.execute("DELETE FROM snapshot_profile_jobs WHERE snapshot_id=%s", (snap["snapshot_id"],))
    db_conn.commit()

    def submit(_):
        with psycopg.connect(non_superuser_dsn) as conn:
            set_tenant_context(conn, tenant.tenant_id)
            return ensure_full_profile(conn, tenant.tenant_id, UUID(snap["snapshot_id"]))["profile_id"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(submit, range(2)))
    assert ids[0] == ids[1]


def test_expired_lease_cannot_heartbeat_or_publish(client, tenant, db_conn, profile_worker_dsn):
    from dq_scoring.adapters.queue.postgres_profile_queue import PostgresProfileQueue
    snap = _registered(client, tenant)
    first = PostgresProfileQueue(profile_worker_dsn, "first")
    job = first.claim_next_job()
    assert str(job["snapshot_id"]) == snap["snapshot_id"]
    assert first.heartbeat(job)
    db_conn.execute("UPDATE snapshot_profile_jobs SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE profile_id=%s", (job["profile_id"],))
    db_conn.commit()
    assert not first.heartbeat(job)
    assert not first.fail(job, "PROFILE_FAILED")
    replacement = PostgresProfileQueue(profile_worker_dsn, "replacement")
    newer = replacement.claim_next_job()
    assert newer["lease_generation"] == job["lease_generation"] + 1
    assert not first.fail(job, "PROFILE_FAILED")
    assert replacement.fail(newer, "PROFILE_FAILED")
    assert replacement.claim_next_job() is None


def test_registration_replay_and_duplicate_share_job(client, tenant, db_conn):
    snap = _registered(client, tenant)
    upload_id = db_conn.execute("SELECT upload_id FROM dataset_upload_sessions WHERE registered_snapshot_id=%s", (snap["snapshot_id"],)).fetchone()[0]
    replay = client.post(f"/api/v1/imports/{upload_id}/register", headers=tenant.creator, json={"acknowledged_warnings": []})
    assert replay.status_code == 200 and replay.json()["snapshot_id"] == snap["snapshot_id"]
    duplicate = register_snapshot_via_api(client, tenant.creator, content_or_path=b"id,amount\nA,12\nB,\n", asset_id=snap["asset_id"])
    assert duplicate["snapshot_id"] == snap["snapshot_id"]
    assert db_conn.execute("SELECT count(*) FROM snapshot_profile_jobs WHERE snapshot_id=%s", (snap["snapshot_id"],)).fetchone()[0] == 1


def test_failed_requires_explicit_requeue_and_complete_is_immutable(client, tenant, db_conn, profile_worker_dsn, non_superuser_dsn):
    from datetime import UTC, datetime

    from dq_scoring.adapters.queue.postgres_profile_queue import PostgresProfileQueue
    from dq_scoring.common.profiling import ColumnProfile, SnapshotProfile
    from dq_scoring.services.snapshot_profile_service import ensure_full_profile

    snap = _registered(client, tenant)
    queue = PostgresProfileQueue(profile_worker_dsn, "worker")
    job = queue.claim_next_job()
    assert queue.fail(job, "PROFILE_FAILED")
    with psycopg.connect(non_superuser_dsn) as conn:
        set_tenant_context(conn, tenant.tenant_id)
        assert ensure_full_profile(conn, tenant.tenant_id, UUID(snap["snapshot_id"]))["state"] == "FAILED"
        assert ensure_full_profile(conn, tenant.tenant_id, UUID(snap["snapshot_id"]), requeue_failed=True)["state"] == "QUEUED"
    newer = queue.claim_next_job()
    result = SnapshotProfile(mode="FULL", profiler_version=newer["profiler_version"], profile_id=newer["profile_id"],
        fingerprint=newer["fingerprint"], generated_at=datetime.now(UTC), total_rows=2, scanned_rows=2,
        is_sample=False, sampling_method="EXACT", columns=(
            ColumnProfile(name="id", technical_type="STRING", null_count=0, non_null_count=2, distinct_count=2, parse_reason="NO_EXPLICIT_TARGET"),
            ColumnProfile(name="amount", technical_type="STRING", null_count=1, non_null_count=1, distinct_count=1, parse_reason="NO_EXPLICIT_TARGET"),
        ))
    wrong_type = result.model_copy(update={"columns": (result.columns[0].model_copy(update={"technical_type": "INTEGER"}), result.columns[1])})
    with pytest.raises(ValueError, match="PROFILE_SCHEMA_MISMATCH"):
        queue.complete(newer, wrong_type)
    guessed_parse = result.model_copy(update={"columns": (result.columns[0].model_copy(update={"parse_target": "INTEGER", "parse_reason": None, "parse_success_count": 2}), result.columns[1])})
    with pytest.raises(ValueError, match="PROFILE_SCHEMA_MISMATCH"):
        queue.complete(newer, guessed_parse)
    assert queue.complete(newer, result)
    assert not queue.complete(newer, result)
    assert not queue.fail(newer, "PROFILE_FAILED")
    db_conn.rollback()
    with pytest.raises(psycopg.errors.CheckViolation):
        db_conn.execute("UPDATE snapshot_profile_jobs SET state='QUEUED' WHERE profile_id=%s", (newer["profile_id"],))
    db_conn.rollback()


def test_submission_rollback_removes_job(client, tenant, db_conn, non_superuser_dsn):
    from dq_scoring.services.snapshot_profile_service import ensure_full_profile

    snap = _registered(client, tenant)
    # Remove only test-owned queued evidence, then prove the caller's rollback owns submission.
    db_conn.execute("DELETE FROM snapshot_profile_jobs WHERE snapshot_id=%s", (snap["snapshot_id"],))
    db_conn.commit()
    with psycopg.connect(non_superuser_dsn) as conn:
        set_tenant_context(conn, tenant.tenant_id)
        ensure_full_profile(conn, tenant.tenant_id, UUID(snap["snapshot_id"]))
        conn.rollback()
    assert db_conn.execute("SELECT count(*) FROM snapshot_profile_jobs WHERE snapshot_id=%s", (snap["snapshot_id"],)).fetchone()[0] == 0


def test_dispatcher_claims_without_snapshot_access(client, tenant, profile_dispatcher_dsn):
    from dq_scoring.adapters.queue.postgres_profile_queue import PostgresProfileQueue
    snap = _registered(client, tenant)
    queue = PostgresProfileQueue(profile_dispatcher_dsn, "dispatcher")
    job = queue.claim_next_job()
    assert str(job["snapshot_id"]) == snap["snapshot_id"]
    with psycopg.connect(profile_dispatcher_dsn) as conn:
        assert conn.execute("SELECT snapshot_id FROM dataset_snapshots WHERE snapshot_id=%s", (snap["snapshot_id"],)).fetchall() == []
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        queue.fail(job, "PROFILE_FAILED")
