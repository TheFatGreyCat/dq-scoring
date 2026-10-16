"""Privacy scan worker: claims jobs, scans the pinned canonical Parquet, publishes fenced results.

Connection contract: callers pass an *autocommit* connection (as ImportDaemon does). Every DB step runs in its own
short `conn.transaction()`; object I/O and scanning happen with no open transaction. Heartbeats must use their own
connection. Error codes are fixed strings; exception text is never stored or logged.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pyarrow.parquet as pq
from psycopg.types.json import Jsonb
from pyarrow import ArrowException
from pydantic import ValidationError

from dq_scoring.adapters.db.tenant_context import set_tenant_context
from dq_scoring.adapters.storage.s3_settings import (
    ImportSettings,
    S3Settings,
    get_import_settings,
    get_s3_settings,
)
from dq_scoring.adapters.storage.snapshot_objects import (
    SnapshotObjectError,
    spool_canonical,
)
from dq_scoring.common.privacy import (
    PrivacyScanLimitExceededException,
    PrivacyScanner,
    generate_finding_id,
)
from dq_scoring.common.privacy_rules import InvalidPrivacyPattern, pinned_from_json
from dq_scoring.common.structured_values import (
    StructuredParsingError,
    parse_structured_json,
)
from dq_scoring.ports.object_store import IObjectStorePort

logger = logging.getLogger("dq_scoring.workers.privacy_scan_worker")

MAX_ATTEMPTS = 3
BATCH_ROWS = 1000
MAX_SUMMARY_BYTES = 500 * 1024
_TRANSIENT_CODES = frozenset({"STORAGE_UNAVAILABLE", "PRIVACY_SCAN_FAILED"})
_OBJECT_CODE_MAP = {
    "STORAGE_UNAVAILABLE": "STORAGE_UNAVAILABLE",
    "OBJECT_CHANGED": "OBJECT_CHANGED",
    "RESOURCE_NOT_FOUND": "OBJECT_CHANGED",
}


class _ScanFailure(Exception):
    """Carries only a fixed error code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _json_size(value: Any) -> int:
    return len(json.dumps(value, separators=(",", ":")).encode("utf-8"))


def _bounded(items: list[dict], budget: int) -> tuple[list[dict], bool]:
    """Longest prefix of `items` whose JSON size stays within `budget`."""
    used, kept = 2, []
    for item in items:
        used += _json_size(item) + 1
        if used > budget:
            return kept, True
        kept.append(item)
    return kept, False


def build_summary(result: dict[str, Any], purpose: str) -> dict[str, Any]:
    """Value-free summary <= MAX_SUMMARY_BYTES; PREVIEW additionally lists per-path counts."""
    findings = result["findings"]
    summary: dict[str, Any] = {
        "total_rows": result["total_rows"],
        "finding_count": len(findings),
        "columns_with_findings": len({f["column_name"] for f in findings}),
        "truncated": False,
    }
    half = MAX_SUMMARY_BYTES // 2 - 1024
    scope, scope_cut = _bounded(result["scope_missing_columns"], half)
    summary["scope_missing_columns"] = scope
    if purpose == "PREVIEW":
        keys = ("column_name", "path", "category", "detector_code", "rule_id", "rule_revision",
                "method", "matched_count", "observed_count")
        listed, cut = _bounded([{k: f[k] for k in keys} for f in findings], half)
        summary["findings"] = listed
        summary["truncated"] = cut
    summary["truncated"] = summary["truncated"] or scope_cut
    return summary


class PrivacyScanWorker:
    def __init__(
        self,
        store: IObjectStorePort,
        worker_id: str = "privacy-scan-worker-1",
        s3_settings: S3Settings | None = None,
        import_settings: ImportSettings | None = None,
    ) -> None:
        self.store = store
        self.worker_id = worker_id
        self.s3_settings = s3_settings or get_s3_settings()
        self.settings = import_settings or get_import_settings()

    # ---- queue ---------------------------------------------------------------------------------

    def claim_next_job(self, conn: psycopg.Connection) -> dict[str, Any] | None:
        """Claim the oldest QUEUED or lease-expired RUNNING job (cross-tenant via dispatcher RLS)."""
        with conn.transaction(), conn.cursor() as cur:
            cur.execute(
                """SELECT scan_id FROM privacy_scan_jobs
                   WHERE state = 'QUEUED' OR (state = 'RUNNING' AND lease_expires_at < now())
                   ORDER BY created_at ASC, scan_id ASC
                   LIMIT 1 FOR UPDATE SKIP LOCKED"""
            )
            row = cur.fetchone()
            if not row:
                return None
            scan_id = row[0]
            cur.execute(
                """UPDATE privacy_scan_jobs
                   SET state = 'RUNNING', lease_owner = %s, lease_generation = lease_generation + 1,
                       attempt_count = attempt_count + 1,
                       lease_expires_at = now() + make_interval(secs => %s),
                       started_at = COALESCE(started_at, now())
                   WHERE scan_id = %s
                   RETURNING scan_id, tenant_id, snapshot_id, requested_by, purpose, pinned_rules,
                             config_version, lease_generation, attempt_count""",
                (self.worker_id, self.settings.lease_seconds, scan_id),
            )
            c = cur.fetchone()
            return {
                "scan_id": c[0], "tenant_id": c[1], "snapshot_id": c[2], "requested_by": c[3],
                "purpose": c[4], "pinned_rules": c[5], "config_version": c[6],
                "lease_generation": c[7], "attempt_count": c[8],
            }

    def heartbeat(self, conn: psycopg.Connection, scan_id: UUID, lease_generation: int, *, tenant_id: UUID) -> bool:
        """Extend the lease; False when the lease was lost (stolen, expired, or job finished)."""
        with conn.transaction(), conn.cursor() as cur:
            set_tenant_context(conn, tenant_id)
            cur.execute(
                """UPDATE privacy_scan_jobs
                   SET lease_expires_at = now() + make_interval(secs => %s)
                   WHERE tenant_id = %s AND scan_id = %s AND state = 'RUNNING'
                     AND lease_owner = %s AND lease_generation = %s AND lease_expires_at >= now()""",
                (self.settings.lease_seconds, tenant_id, scan_id, self.worker_id, lease_generation),
            )
            return cur.rowcount > 0

    # ---- processing ----------------------------------------------------------------------------

    def process_job(self, conn: psycopg.Connection, job: dict[str, Any]) -> bool:
        """Scan and publish. Returns True when a result (COMPLETE/FAILED/requeue) was recorded by this lease."""
        if job["attempt_count"] > MAX_ATTEMPTS:
            logger.error("Privacy scan %s exhausted max attempts (%s)", job["scan_id"], job["attempt_count"])
            return self._fail(conn, job, "PRIVACY_SCAN_FAILED")

        tenant_id = job["tenant_id"]
        with conn.transaction(), conn.cursor() as cur:
            set_tenant_context(conn, tenant_id)
            cur.execute(
                "SELECT source_descriptor, schema_definition FROM dataset_snapshots WHERE tenant_id = %s AND snapshot_id = %s",
                (tenant_id, job["snapshot_id"]),
            )
            snapshot = cur.fetchone()

        try:
            if not snapshot:
                raise _ScanFailure("SNAPSHOT_REIMPORT_REQUIRED")
            result = self._scan(job, snapshot[0], snapshot[1])
        except _ScanFailure as failure:
            return self._fail(conn, job, failure.code)
        except Exception as error:  # noqa: BLE001 - recorded as fixed PRIVACY_SCAN_FAILED, never success
            logger.error("Privacy scan %s failed: %s", job["scan_id"], type(error).__name__)
            return self._fail(conn, job, "PRIVACY_SCAN_FAILED")

        try:
            return self._publish(conn, job, result)
        except (psycopg.errors.IntegrityError, psycopg.errors.DataError):
            logger.error("Privacy scan %s publication rejected", job["scan_id"])
            return self._fail(conn, job, "PRIVACY_SCAN_FAILED")

    def _scan(self, job: dict[str, Any], source_descriptor: Any, schema: Any) -> dict[str, Any]:
        columns = [c for c in (schema or {}).get("columns", []) if isinstance(c, dict) and c.get("name")]
        if not columns:
            raise _ScanFailure("SNAPSHOT_REIMPORT_REQUIRED")
        names = [c["name"] for c in columns]
        structured = {c["name"] for c in columns if c.get("structural_encoding") == "JSON"}
        try:
            pinned = pinned_from_json(job["pinned_rules"], job["config_version"])
            scanner = PrivacyScanner(columns=columns, rules=pinned.rules)
        except (ValidationError, InvalidPrivacyPattern, ValueError, TypeError, KeyError):
            raise _ScanFailure("PRIVACY_RULE_INVALID") from None

        root = Path(self.settings.temp_root)
        os.makedirs(root, exist_ok=True)
        try:
            with tempfile.TemporaryDirectory(dir=root, prefix="privacy-scan-") as workdir:
                spool = Path(workdir) / "canonical.parquet"
                spool_canonical(self.store, job["tenant_id"], source_descriptor, self.s3_settings.bucket_snapshots, spool)
                parquet = pq.ParquetFile(spool)
                if not set(names) <= set(parquet.schema_arrow.names):
                    raise _ScanFailure("SNAPSHOT_REIMPORT_REQUIRED")
                for batch in parquet.iter_batches(batch_size=BATCH_ROWS, columns=names):
                    for row in batch.to_pylist():
                        for name in structured:
                            if isinstance(row.get(name), str):
                                row[name] = parse_structured_json(row[name])
                        scanner.feed_row(row)
        except SnapshotObjectError as error:
            raise _ScanFailure(_OBJECT_CODE_MAP.get(error.code, "SNAPSHOT_REIMPORT_REQUIRED")) from None
        except PrivacyScanLimitExceededException:
            raise _ScanFailure("PRIVACY_SCAN_LIMIT_EXCEEDED") from None
        except (ArrowException, StructuredParsingError):
            raise _ScanFailure("SNAPSHOT_REIMPORT_REQUIRED") from None

        result = scanner.finish()
        if result["total_rows"] == 0:
            raise _ScanFailure("SNAPSHOT_REIMPORT_REQUIRED")
        return result

    # ---- fenced writes -------------------------------------------------------------------------

    def _lock_fenced(self, cur: psycopg.Cursor, job: dict[str, Any]) -> UUID | None:
        """Lock asset -> protection revision -> job, then verify owner, generation and expiry.

        Returns the asset id, or None when the lease is gone (caller must write nothing).
        """
        tenant_id = job["tenant_id"]
        cur.execute(
            "SELECT asset_id FROM dataset_snapshots WHERE tenant_id = %s AND snapshot_id = %s",
            (tenant_id, job["snapshot_id"]),
        )
        asset = cur.fetchone()
        if not asset:
            return None
        asset_id = asset[0]
        cur.execute("SELECT 1 FROM data_assets WHERE tenant_id = %s AND asset_id = %s FOR UPDATE", (tenant_id, asset_id))
        cur.execute(
            "INSERT INTO asset_protection_revisions (tenant_id, asset_id, version) VALUES (%s, %s, 0) ON CONFLICT DO NOTHING",
            (tenant_id, asset_id),
        )
        cur.execute(
            "SELECT version FROM asset_protection_revisions WHERE tenant_id = %s AND asset_id = %s FOR UPDATE",
            (tenant_id, asset_id),
        )
        cur.execute(
            """SELECT 1 FROM privacy_scan_jobs
               WHERE tenant_id = %s AND scan_id = %s AND state = 'RUNNING' AND lease_owner = %s
                 AND lease_generation = %s AND lease_expires_at >= now()
               FOR UPDATE""",
            (tenant_id, job["scan_id"], self.worker_id, job["lease_generation"]),
        )
        return asset_id if cur.fetchone() else None

    def _publish(self, conn: psycopg.Connection, job: dict[str, Any], result: dict[str, Any]) -> bool:
        tenant_id, scan_id, apply = job["tenant_id"], job["scan_id"], job["purpose"] == "APPLY"
        summary = build_summary(result, job["purpose"])
        with conn.transaction(), conn.cursor() as cur:
            set_tenant_context(conn, tenant_id)
            asset_id = self._lock_fenced(cur, job)
            if asset_id is None:
                logger.warning("Privacy scan %s lease lost; publication skipped", scan_id)
                return False
            if apply:
                self._write_findings(cur, job, asset_id, result["findings"])
            cur.execute(
                """UPDATE privacy_scan_jobs
                   SET state = 'COMPLETE', finished_at = now(), result_summary = %s,
                       lease_owner = NULL, lease_expires_at = NULL, error_code = NULL
                   WHERE tenant_id = %s AND scan_id = %s""",
                (Jsonb(summary), tenant_id, scan_id),
            )
        return True

    def _write_findings(self, cur: psycopg.Cursor, job: dict[str, Any], asset_id: UUID, findings: list[dict]) -> None:
        tenant_id, scan_id, snapshot_id = job["tenant_id"], job["scan_id"], job["snapshot_id"]
        cur.execute(
            """SELECT scan_id FROM privacy_scan_jobs
               WHERE tenant_id = %s AND snapshot_id = %s AND purpose = 'APPLY' AND state = 'COMPLETE' AND scan_id <> %s
               ORDER BY created_at DESC, scan_id DESC LIMIT 1""",
            (tenant_id, snapshot_id, scan_id),
        )
        previous = cur.fetchone()
        decisions: dict[tuple, tuple] = {}
        if previous:
            cur.execute(
                """SELECT detected_by_rule_id, privacy_rule_revision, column_name, path,
                          status, review_reason, reviewed_by, reviewed_at
                   FROM sensitive_data_findings
                   WHERE tenant_id = %s AND scan_id = %s AND status IN ('CONFIRMED', 'DISMISSED')
                     AND detected_by_rule_id IS NOT NULL""",
                (tenant_id, previous[0]),
            )
            decisions = {(str(r[0]), r[1], r[2], r[3]): r[4:] for r in cur.fetchall()}

        rows = []
        for f in findings:
            decision = decisions.get((f["rule_id"], f["rule_revision"], f["column_name"], f["path"])) \
                if f["rule_id"] else None
            status, reason, reviewer, reviewed_at = decision or ("DETECTED", None, None, None)
            rows.append((
                generate_finding_id(scan_id, f["column_name"], f["path"], f["detector_code"], f["detector_revision"]),
                tenant_id, snapshot_id, f["column_name"], f["path"], f["category"], f["confidence_score"],
                status, f["detector_code"], f["detector_revision"], f["matched_count"], f["observed_count"],
                f["method"], f["rule_id"], f["rule_revision"], scan_id, reason, reviewer, reviewed_at,
            ))
        if rows:
            cur.executemany(
                """INSERT INTO sensitive_data_findings (
                       finding_id, tenant_id, snapshot_id, column_name, path, category, confidence_score,
                       status, detected_at, detector_code, detector_revision, matched_count, observed_count,
                       detection_method, detected_by_rule_id, privacy_rule_revision, scan_id,
                       review_reason, reviewed_by, reviewed_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now(), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                rows,
            )
        cur.execute(
            "UPDATE asset_protection_revisions SET version = version + 1 WHERE tenant_id = %s AND asset_id = %s RETURNING version",
            (tenant_id, asset_id),
        )
        version = cur.fetchone()[0]
        cur.execute(
            """INSERT INTO privacy_change_events
               (event_id, tenant_id, asset_id, snapshot_id, actor_user_id, action, before_state, after_state, reason)
               VALUES (%s, %s, %s, %s, %s, 'PRIVACY_SCAN_APPLIED', %s, %s, NULL)""",
            (uuid4(), tenant_id, asset_id, snapshot_id, job["requested_by"],
             Jsonb({"version": version - 1}),
             Jsonb({"scan_id": str(scan_id), "config_version": job["config_version"],
                    "finding_count": len(rows), "version": version})),
        )

    def _fail(self, conn: psycopg.Connection, job: dict[str, Any], code: str) -> bool:
        """Record a fixed failure code; transient codes requeue while attempts remain. Fenced by lease."""
        requeue = code in _TRANSIENT_CODES and job["attempt_count"] < MAX_ATTEMPTS
        with conn.transaction(), conn.cursor() as cur:
            set_tenant_context(conn, job["tenant_id"])
            if requeue:
                cur.execute(
                    """UPDATE privacy_scan_jobs SET state = 'QUEUED', lease_owner = NULL, lease_expires_at = NULL
                       WHERE tenant_id = %s AND scan_id = %s AND state = 'RUNNING' AND lease_owner = %s
                         AND lease_generation = %s AND lease_expires_at >= now()""",
                    (job["tenant_id"], job["scan_id"], self.worker_id, job["lease_generation"]),
                )
            else:
                cur.execute(
                    """UPDATE privacy_scan_jobs
                       SET state = 'FAILED', error_code = %s, finished_at = now(), result_summary = NULL,
                           lease_owner = NULL, lease_expires_at = NULL
                       WHERE tenant_id = %s AND scan_id = %s AND state = 'RUNNING' AND lease_owner = %s
                         AND lease_generation = %s AND lease_expires_at >= now()""",
                    (code, job["tenant_id"], job["scan_id"], self.worker_id, job["lease_generation"]),
                )
            changed = cur.rowcount > 0
            if changed and not requeue:
                cur.execute(
                    """INSERT INTO privacy_change_events
                       (event_id,tenant_id,snapshot_id,actor_user_id,action,after_state)
                       VALUES(%s,%s,%s,%s,'PRIVACY_SCAN_FAILED',%s)""",
                    (uuid4(), job["tenant_id"], job["snapshot_id"], job["requested_by"],
                     Jsonb({"scan_id": str(job["scan_id"]), "error_code": code})),
                )
            return changed
