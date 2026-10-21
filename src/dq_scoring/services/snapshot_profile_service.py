"""Tenant-scoped profile lookup/submission; no object access or heavy compute."""
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from dq_scoring.common.profiling import PROFILER_VERSION, ProfileRequiredError
from dq_scoring.core.entities import DatasetSnapshot


class SnapshotProfileError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


PROFILE_COLUMNS = "profile_id,tenant_id,snapshot_id,fingerprint,profiler_version,state,created_at,started_at,finished_at,error_code,result"


def load_snapshot(conn: psycopg.Connection, tenant_id: UUID, snapshot_id: UUID) -> DatasetSnapshot:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT snapshot_id,tenant_id,asset_id,source_kind,source_descriptor,schema_definition,total_rows,total_columns,captured_at "
            "FROM dataset_snapshots WHERE tenant_id=%s AND snapshot_id=%s",
            (tenant_id, snapshot_id),
        )
        row = cur.fetchone()
    if row is None:
        raise SnapshotProfileError("RESOURCE_NOT_FOUND")
    return DatasetSnapshot.model_validate(row)


def profile_fingerprint(conn: psycopg.Connection, snapshot: DatasetSnapshot, version: str = PROFILER_VERSION) -> str:
    from psycopg.types.json import Jsonb
    # Eligibility (legacy canonical Parquet or valid v2 descriptor) is defined once, in SQL, next to the fingerprint.
    if snapshot.source_kind != "OBJECT_FILE" or not conn.execute(
        "SELECT snapshot_source_is_profileable(%s)", (Jsonb(snapshot.source_descriptor),)
    ).fetchone()[0]:
        raise SnapshotProfileError("SNAPSHOT_REIMPORT_REQUIRED")
    return conn.execute(
        "SELECT snapshot_profile_fingerprint(%s,%s,%s,%s,%s)",
        (snapshot.tenant_id, snapshot.snapshot_id, Jsonb(snapshot.schema_definition), Jsonb(snapshot.source_descriptor), version),
    ).fetchone()[0]


def current_full_profile(conn: psycopg.Connection, tenant_id: UUID, snapshot_id: UUID) -> dict | None:
    snapshot = load_snapshot(conn, tenant_id, snapshot_id)
    fingerprint = profile_fingerprint(conn, snapshot)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(f"SELECT {PROFILE_COLUMNS} FROM snapshot_profile_jobs WHERE tenant_id=%s AND snapshot_id=%s AND fingerprint=%s",
                    (tenant_id, snapshot_id, fingerprint))
        return cur.fetchone()


def ensure_full_profile(
    conn: psycopg.Connection, tenant_id: UUID, snapshot_id: UUID,
    requested_by: UUID | None = None, *, requeue_failed: bool = False,
) -> dict:
    """Use caller's transaction; concurrent submission shares one immutable identity."""
    snapshot = load_snapshot(conn, tenant_id, snapshot_id)
    fingerprint = profile_fingerprint(conn, snapshot)
    conn.execute(
        "INSERT INTO snapshot_profile_jobs(tenant_id,snapshot_id,fingerprint,profiler_version,requested_by) "
        "VALUES(%s,%s,%s,%s,%s) ON CONFLICT(tenant_id,snapshot_id,fingerprint) DO NOTHING",
        (tenant_id, snapshot_id, fingerprint, PROFILER_VERSION, requested_by),
    )
    if requeue_failed:
        conn.execute("UPDATE snapshot_profile_jobs SET state='QUEUED' WHERE tenant_id=%s AND snapshot_id=%s AND fingerprint=%s AND state='FAILED'",
                     (tenant_id, snapshot_id, fingerprint))
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(f"SELECT {PROFILE_COLUMNS} FROM snapshot_profile_jobs WHERE tenant_id=%s AND snapshot_id=%s AND fingerprint=%s",
                    (tenant_id, snapshot_id, fingerprint))
        return cur.fetchone()


def require_full_profile(conn: psycopg.Connection, tenant_id: UUID, snapshot_id: UUID) -> dict:
    try:
        job = current_full_profile(conn, tenant_id, snapshot_id)
    except SnapshotProfileError as error:
        raise ProfileRequiredError({"state": "UNSUPPORTED", "error_code": error.code}) from None
    if job is None or job["state"] != "COMPLETE":
        raise ProfileRequiredError(None if job is None else {"profile_id":str(job["profile_id"]),"state":job["state"]})
    return job
