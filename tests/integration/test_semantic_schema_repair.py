"""Fail-closed repair of the pre-release semantic schema; all DDL rolls back."""

import psycopg
import pytest

from dq_scoring.presentation.cli.repair_semantic_schema import (
    RepairAborted,
    repair,
    row_counts,
    schema_state,
)
from tests.integration.test_single_source_migrations import Seed, legacy_descriptor


@pytest.fixture
def conn(pg_dsn):
    with psycopg.connect(pg_dsn) as connection:
        connection.execute("BEGIN")
        yield connection
        connection.rollback()


def legacy(conn):
    conn.execute("DROP TRIGGER semantic_history_guard ON snapshot_column_semantic_history")
    conn.execute("DROP TRIGGER semantic_state_history_required ON snapshot_semantic_state")
    conn.execute("DROP FUNCTION enforce_semantic_history()")


def test_current_schema_repair_is_noop(conn):
    before = conn.execute("SELECT 'snapshot_semantic_state'::regclass::oid").fetchone()[0]
    assert schema_state(conn) == "CURRENT"
    assert repair(conn) == "CURRENT"
    assert conn.execute("SELECT 'snapshot_semantic_state'::regclass::oid").fetchone()[0] == before


def test_empty_legacy_repair_restores_revision_guard(conn):
    seed = Seed(conn)
    snapshot = seed.snapshot(legacy_descriptor())
    versions = conn.execute("SELECT * FROM schema_migrations ORDER BY version").fetchall()
    legacy(conn)
    assert schema_state(conn) == "LEGACY"
    assert repair(conn) == "CURRENT"
    assert schema_state(conn) == "CURRENT"
    assert conn.execute("SELECT * FROM schema_migrations ORDER BY version").fetchall() == versions
    with conn.transaction():
        conn.execute("SET LOCAL row_security=on")
        conn.execute("SET LOCAL ROLE dq_app_role")
        conn.execute("SELECT set_config('app.current_tenant_id', %s, true)", (str(seed.tenant),))
        conn.execute("INSERT INTO snapshot_semantic_state(tenant_id,snapshot_id) VALUES(%s,%s)", (seed.tenant, snapshot.snapshot_id))
        with pytest.raises(psycopg.errors.CheckViolation, match="SEMANTIC_REVISION_INVALID"), conn.transaction():
            conn.execute("UPDATE snapshot_semantic_state SET revision=5 WHERE snapshot_id=%s", (snapshot.snapshot_id,))


def test_legacy_with_evidence_aborts_without_deleting(conn):
    seed = Seed(conn)
    snapshot = seed.snapshot(legacy_descriptor())
    conn.execute("ALTER TABLE snapshot_semantic_state DISABLE TRIGGER USER")
    conn.execute("INSERT INTO snapshot_semantic_state(tenant_id,snapshot_id) VALUES(%s,%s)", (seed.tenant, snapshot.snapshot_id))
    legacy(conn)
    with pytest.raises(RepairAborted) as error:
        repair(conn)
    assert error.value.status == "SEMANTIC_EVIDENCE_NOT_EMPTY"
    assert row_counts(conn)["snapshot_semantic_state"] == 1
    assert conn.execute("SELECT snapshot_id FROM snapshot_semantic_state").fetchall() == [(snapshot.snapshot_id,)]


def test_partial_schema_aborts(conn):
    conn.execute("DROP TABLE snapshot_column_semantic_history CASCADE")
    with pytest.raises(RepairAborted) as error:
        schema_state(conn)
    assert error.value.status == "SEMANTIC_SCHEMA_PARTIAL"
    with pytest.raises(RepairAborted, match="SEMANTIC_SCHEMA_PARTIAL"):
        repair(conn)


def test_absent_schema_is_not_created(conn):
    conn.execute("DROP TABLE snapshot_column_semantic_history, snapshot_column_semantics, snapshot_semantic_state")
    assert schema_state(conn) == "ABSENT"
    assert repair(conn) == "ABSENT"


def test_failed_rebuild_rolls_back_legacy_schema(conn, tmp_path):
    legacy(conn)
    before = conn.execute("SELECT 'snapshot_semantic_state'::regclass::oid").fetchone()[0]
    (tmp_path / "023_column_semantics.sql").write_text("SELECT 1;", encoding="utf-8")
    with pytest.raises(RepairAborted, match="SEMANTIC_REPAIR_VERIFICATION_FAILED"):
        repair(conn, tmp_path)
    assert schema_state(conn) == "LEGACY"
    assert conn.execute("SELECT 'snapshot_semantic_state'::regclass::oid").fetchone()[0] == before
