"""Short profile queue transactions; worker owns a live generation, never a snapshot-wide privilege."""
from typing import get_args

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from dq_scoring.adapters.db.tenant_context import set_tenant_context
from dq_scoring.common.profiling import ProfileErrorCode, SnapshotProfile
from dq_scoring.common.protected_transport import protected_connect
from dq_scoring.services.snapshot_profile_service import (
    load_snapshot,
    profile_fingerprint,
)


class PostgresProfileQueue:
    def __init__(self, dsn: str, worker_id: str, lease_seconds: int = 300) -> None:
        if not worker_id or len(worker_id) > 200 or lease_seconds <= 0:
            raise ValueError("PROFILE_WORKER_CONFIGURATION_INVALID")
        self.dsn, self.worker_id, self.lease_seconds = dsn, worker_id, lease_seconds

    def claim_next_job(self) -> dict | None:
        with protected_connect(self.dsn) as conn, conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT profile_id FROM snapshot_profile_jobs WHERE state='QUEUED' "
                "OR (state='RUNNING' AND lease_expires_at<clock_timestamp()) "
                "ORDER BY created_at,profile_id LIMIT 1 FOR UPDATE SKIP LOCKED"
            )
            row = cur.fetchone()
            if row is None:
                return None
            cur.execute(
                "UPDATE snapshot_profile_jobs SET state='RUNNING',lease_owner=%s,lease_generation=lease_generation+1,"
                "attempt_count=attempt_count+1,lease_expires_at=clock_timestamp()+make_interval(secs=>%s),"
                "heartbeat_at=clock_timestamp(),started_at=COALESCE(started_at,clock_timestamp()) "
                "WHERE profile_id=%s RETURNING *",
                (self.worker_id, self.lease_seconds, row["profile_id"]),
            )
            return cur.fetchone()

    def _update(self, job: dict, assignments: str, values: tuple) -> bool:
        with protected_connect(self.dsn) as conn, conn.transaction():
            set_tenant_context(conn, job["tenant_id"])
            cur = conn.execute(
                f"UPDATE snapshot_profile_jobs SET {assignments} WHERE tenant_id=%s AND profile_id=%s "
                "AND state='RUNNING' AND lease_owner=%s AND lease_generation=%s AND lease_expires_at>=clock_timestamp()",
                (*values, job["tenant_id"], job["profile_id"], self.worker_id, job["lease_generation"]),
            )
            return cur.rowcount == 1

    def heartbeat(self, job: dict) -> bool:
        return self._update(job, "heartbeat_at=clock_timestamp(),lease_expires_at=clock_timestamp()+make_interval(secs=>%s)", (self.lease_seconds,))

    def fail(self, job: dict, code: ProfileErrorCode) -> bool:
        if code not in get_args(ProfileErrorCode):
            raise ValueError("PROFILE_ERROR_CODE_INVALID")
        return self._update(job, "state='FAILED',error_code=%s,finished_at=clock_timestamp()", (code,))

    def complete(self, job: dict, result: SnapshotProfile) -> bool:
        result = SnapshotProfile.model_validate(result.model_dump())
        with protected_connect(self.dsn) as conn, conn.transaction():
            set_tenant_context(conn, job["tenant_id"])
            snapshot = load_snapshot(conn, job["tenant_id"], job["snapshot_id"])
            names = [c if isinstance(c, str) else c["name"] for c in snapshot.schema_definition.get("columns", [])]
            if (result.mode != "FULL" or result.profile_id != job["profile_id"]
                or result.fingerprint != job["fingerprint"] or result.profiler_version != job["profiler_version"]
                or result.fingerprint != profile_fingerprint(conn, snapshot, job["profiler_version"])
                or result.total_rows != snapshot.total_rows or [c.name for c in result.columns] != names):
                raise ValueError("PROFILE_RESULT_INVALID")
            schema_columns = snapshot.schema_definition.get("columns", [])
            for column, definition in zip(result.columns, schema_columns, strict=True):
                definition = {"name": definition, "type": "STRING"} if isinstance(definition, str) else definition
                target = definition.get("parse_target")
                if (column.technical_type != definition.get("type", "STRING").upper()
                    or column.parse_target != target or column.parse_format != definition.get("parse_format")
                    or (target is None and (column.parse_success_count is not None or column.parse_reason != "NO_EXPLICIT_TARGET"))):
                    raise ValueError("PROFILE_SCHEMA_MISMATCH")
            cur = conn.execute(
                "UPDATE snapshot_profile_jobs SET state='COMPLETE',result=%s,finished_at=clock_timestamp() "
                "WHERE tenant_id=%s AND profile_id=%s AND state='RUNNING' AND lease_owner=%s "
                "AND lease_generation=%s AND lease_expires_at>=clock_timestamp()",
                (Jsonb(result.model_dump(mode="json")), job["tenant_id"], job["profile_id"], self.worker_id, job["lease_generation"]),
            )
            return cur.rowcount == 1
