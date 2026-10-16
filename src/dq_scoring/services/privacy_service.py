"""Domain service for sensitive data findings and asset protection policies."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
from fastapi import HTTPException
from psycopg.types.json import Jsonb

from dq_scoring.adapters.db.tenant_context import set_tenant_context
from dq_scoring.adapters.storage.s3_settings import S3Settings
from dq_scoring.adapters.storage.snapshot_objects import (
    SnapshotObjectError,
    spool_canonical,
)
from dq_scoring.common.privacy import REDACTED_SENTINEL
from dq_scoring.ports.object_store import IObjectStorePort
from dq_scoring.presentation.api.pagination import Pagination, fetch_page
from dq_scoring.services.privacy_policy import (
    ACTIVE_FINDINGS_SQL,
    resolve_snapshot_protection,
)

EXPORT_BATCH_ROWS = 65_536

@dataclass(frozen=True)
class MaskedExportArtifact:
    filename: str
    path: Path
    policy_version: int


def begin_tenant_transaction(conn: psycopg.Connection, tenant_id: UUID) -> None:
    """Restore the request role and tenant RLS context; both are transaction-local and vanish on commit."""
    conn.execute("SET LOCAL ROLE dq_app_role;")
    conn.execute("SELECT set_config('app.current_user_id', '', true);")
    set_tenant_context(conn, tenant_id)


ACTIVE_PROTECTION_ROLES = (
    "WORKSPACE_ADMIN",
    "DATA_OWNER",
    "DATA_STEWARD",
    "DATA_ENGINEER",
    "BUSINESS_VIEWER",
    "VIEWER_UNPRIVILEGED",
)


class PrivacyService:
    @classmethod
    def get_sensitive_findings(
        cls,
        conn: psycopg.Connection,
        tenant_id: UUID,
        snapshot_id: UUID,
        paging: Pagination,
    ) -> dict[str, Any]:
        snapshot = conn.execute("SELECT manifest FROM dataset_snapshots WHERE tenant_id=%s AND snapshot_id=%s", (tenant_id,snapshot_id)).fetchone()
        if not snapshot:
            raise HTTPException(404,"RESOURCE_NOT_FOUND")
        protection = resolve_snapshot_protection(conn,tenant_id,snapshot_id)
        job = conn.execute("SELECT scan_id,finished_at,config_version FROM privacy_scan_jobs WHERE tenant_id=%s AND snapshot_id=%s AND purpose='APPLY' ORDER BY created_at DESC,scan_id DESC LIMIT 1", (tenant_id,snapshot_id)).fetchone()
        config = conn.execute("SELECT version FROM privacy_detector_configs WHERE tenant_id=%s", (tenant_id,)).fetchone()
        scan = (snapshot[0] or {}).get("sensitive_scan") or {}

        page_result = fetch_page(
            conn,
            projection=(
                "finding_id, column_name, path, category, detector_code, "
                "detection_method AS method, matched_count, observed_count, status, detector_revision, "
                "detected_by_rule_id AS rule_id, privacy_rule_revision AS rule_revision, scan_id, "
                "(status='CONFIRMED' AND scan_id IS DISTINCT FROM (SELECT scan_id FROM privacy_scan_jobs j "
                "WHERE j.tenant_id=sensitive_data_findings.tenant_id AND j.snapshot_id=sensitive_data_findings.snapshot_id "
                "AND purpose='APPLY' AND state='COMPLETE' ORDER BY created_at DESC,scan_id DESC LIMIT 1)) AS historical"
            ),
            source="sensitive_data_findings",
            predicates=["tenant_id = %s", "snapshot_id = %s", ACTIVE_FINDINGS_SQL],
            params=[tenant_id, snapshot_id],
            order="column_name, path, finding_id",
            paging=paging,
        )

        return {
            "scan_status": protection.scan_status, "scan_stale": protection.scan_stale,
            "scan_id": job[0] if job else None, "scanned_at": job[1] if job else None,
            "config_version": job[2] if job else scan.get("config_version"),
            "active_config_version": config[0] if config else None,
            "detector_revision": scan.get("detector_revision"), "findings": page_result,
        }

    @classmethod
    def update_finding_status(
        cls,
        conn: psycopg.Connection,
        user_id: UUID,
        tenant_id: UUID,
        finding_id: UUID,
        expected_status: str,
        new_status: str,
        reason: str,
    ) -> dict[str, Any]:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT s.asset_id FROM sensitive_data_findings f
                JOIN dataset_snapshots s ON s.tenant_id = f.tenant_id AND s.snapshot_id = f.snapshot_id
                WHERE f.tenant_id = %s AND f.finding_id = %s;
                """,
                (tenant_id, finding_id),
            )
            asset = cur.fetchone()
            if not asset:
                raise HTTPException(status_code=404, detail="RESOURCE_NOT_FOUND")
            # Lock order: asset -> protection revision -> finding.
            cur.execute("SELECT 1 FROM data_assets WHERE tenant_id = %s AND asset_id = %s FOR UPDATE;", (tenant_id, asset[0]))
            cur.execute(
                "INSERT INTO asset_protection_revisions (tenant_id, asset_id, version) VALUES (%s, %s, 0) ON CONFLICT DO NOTHING;",
                (tenant_id, asset[0]),
            )
            cur.execute(
                "SELECT version FROM asset_protection_revisions WHERE tenant_id = %s AND asset_id = %s FOR UPDATE;",
                (tenant_id, asset[0]),
            )
            version = cur.fetchone()[0]
            cur.execute(
                """
                SELECT f.finding_id, f.column_name, f.path, f.category, f.detector_code,
                       f.detection_method AS method, f.matched_count, f.observed_count, f.status,
                       f.detector_revision, f.snapshot_id, s.asset_id,
                       f.detected_by_rule_id, f.privacy_rule_revision, f.scan_id,
                       (%s = 'CONFIRMED' AND f.scan_id IS DISTINCT FROM (
                           SELECT j.scan_id FROM privacy_scan_jobs j
                           WHERE j.tenant_id = f.tenant_id AND j.snapshot_id = f.snapshot_id
                             AND j.purpose = 'APPLY' AND j.state = 'COMPLETE'
                           ORDER BY j.created_at DESC, j.scan_id DESC LIMIT 1
                       )) AS historical
                FROM sensitive_data_findings f
                JOIN dataset_snapshots s ON s.tenant_id = f.tenant_id AND s.snapshot_id = f.snapshot_id
                WHERE f.tenant_id = %s AND f.finding_id = %s
                FOR UPDATE OF f;
                """,
                (new_status, tenant_id, finding_id),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="RESOURCE_NOT_FOUND")

            current_status = row[8]
            if current_status != expected_status:
                raise HTTPException(status_code=409, detail="FINDING_STATUS_CONFLICT")

            cur.execute(
                """
                UPDATE sensitive_data_findings
                SET status = %s, review_reason = %s, reviewed_by = %s, reviewed_at = now()
                WHERE tenant_id = %s AND finding_id = %s;
                """,
                (new_status, reason, user_id, tenant_id, finding_id),
            )
            cur.execute(
                "UPDATE asset_protection_revisions SET version = version + 1 WHERE tenant_id = %s AND asset_id = %s;",
                (tenant_id, row[11]),
            )
            cur.execute(
                """INSERT INTO privacy_change_events
                   (event_id, tenant_id, asset_id, snapshot_id, actor_user_id, action, before_state, after_state, reason)
                   VALUES (%s, %s, %s, %s, %s, 'FINDING_STATUS_CHANGED', %s, %s, %s)""",
                (uuid4(), tenant_id, row[11], row[10], user_id,
                 Jsonb({"finding_id": str(finding_id), "status": current_status, "version": version}),
                 Jsonb({"finding_id": str(finding_id), "status": new_status, "version": version + 1}), reason),
            )

            return {
                "finding_id": row[0],
                "column_name": row[1],
                "path": row[2],
                "category": row[3],
                "detector_code": row[4],
                "method": row[5],
                "matched_count": row[6],
                "observed_count": row[7],
                "status": new_status,
                "detector_revision": row[9],
                "rule_id": row[12],
                "rule_revision": row[13],
                "scan_id": row[14],
                "historical": bool(row[15]),
            }

    @classmethod
    def get_asset_protection_policy(
        cls,
        conn: psycopg.Connection,
        tenant_id: UUID,
        asset_id: UUID,
    ) -> dict[str, Any]:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT asset_id FROM data_assets WHERE tenant_id = %s AND asset_id = %s;",
                (tenant_id, asset_id),
            )
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Data asset not found")
            cur.execute(
                "SELECT version FROM asset_protection_revisions WHERE tenant_id = %s AND asset_id = %s;",
                (tenant_id, asset_id),
            )
            rev_row = cur.fetchone()
            version = rev_row[0] if rev_row else 0

            cur.execute(
                """
                SELECT DISTINCT target_category FROM data_protection_policies
                WHERE tenant_id = %s AND asset_id = %s AND masking_strategy = 'FULL_MASK';
                """,
                (tenant_id, asset_id),
            )
            categories = {r[0] for r in cur.fetchall()}
            cur.execute(
                """
                SELECT COUNT(*) FROM data_protection_policies
                WHERE tenant_id = %s AND asset_id = %s AND masking_strategy != 'FULL_MASK';
                """,
                (tenant_id, asset_id),
            )
            unsupported = cur.fetchone()[0]

        return {
            "asset_id": asset_id,
            "version": version,
            "categories": sorted(categories),
            "unsupported_policies": unsupported,
        }

    @classmethod
    def update_asset_protection_policy(
        cls,
        conn: psycopg.Connection,
        user_id: UUID,
        tenant_id: UUID,
        asset_id: UUID,
        expected_version: int,
        categories: list[str],
    ) -> dict[str, Any]:
        if not conn.execute(
            "SELECT 1 FROM data_assets WHERE tenant_id = %s AND asset_id = %s FOR UPDATE", (tenant_id, asset_id)
        ).fetchone():
            raise HTTPException(status_code=404, detail="RESOURCE_NOT_FOUND")
        conn.execute(
            "INSERT INTO asset_protection_revisions (tenant_id, asset_id, version) VALUES (%s, %s, 0) ON CONFLICT DO NOTHING",
            (tenant_id, asset_id),
        )
        version = conn.execute(
            "SELECT version FROM asset_protection_revisions WHERE tenant_id = %s AND asset_id = %s FOR UPDATE",
            (tenant_id, asset_id),
        ).fetchone()[0]
        if version != expected_version:
            raise HTTPException(status_code=409, detail="POLICY_VERSION_CONFLICT")
        before = cls.get_asset_protection_policy(conn, tenant_id, asset_id)["categories"]
        conn.execute(
            "DELETE FROM data_protection_policies WHERE tenant_id = %s AND asset_id = %s AND masking_strategy = 'FULL_MASK'",
            (tenant_id, asset_id),
        )
        for cat in categories:
            for role in ACTIVE_PROTECTION_ROLES:
                conn.execute(
                    """
                    INSERT INTO data_protection_policies (
                        policy_id, tenant_id, asset_id, target_category, user_role, masking_strategy, masking_parameters
                    ) VALUES (%s, %s, %s, %s, %s, 'FULL_MASK', '{}'::jsonb)
                    ON CONFLICT (tenant_id, COALESCE(asset_id, '00000000-0000-0000-0000-000000000000'::UUID), target_category, user_role)
                    DO UPDATE SET masking_strategy = 'FULL_MASK';
                    """,
                    (uuid4(), tenant_id, asset_id, cat, role),
                )
        conn.execute(
            "UPDATE asset_protection_revisions SET version = version + 1 WHERE tenant_id = %s AND asset_id = %s",
            (tenant_id, asset_id),
        )
        conn.execute(
            """INSERT INTO privacy_change_events
               (event_id, tenant_id, asset_id, actor_user_id, action, before_state, after_state, reason)
               VALUES (%s, %s, %s, %s, 'POLICY_CHANGED', %s, %s, NULL)""",
            (uuid4(), tenant_id, asset_id, user_id,
             Jsonb({"categories": before, "version": version}),
             Jsonb({"categories": sorted(set(categories)), "version": version + 1})),
        )
        return cls.get_asset_protection_policy(conn, tenant_id, asset_id)

    @classmethod
    def export_masked_parquet(
        cls,
        conn: psycopg.Connection,
        store: IObjectStorePort,
        s3_settings: S3Settings,
        tenant_id: UUID,
        asset_id: UUID,
        snapshot_id: UUID | None,
        workdir: Path,
    ) -> MaskedExportArtifact:
        """Stream the pinned canonical Parquet through the shared resolver into `workdir`.

        The caller's transaction is committed before object I/O (no DB transaction spans storage reads) and a
        fresh tenant-scoped transaction rechecks the protection state before the artifact is released.
        """
        asset_row = conn.execute(
            "SELECT slug, current_snapshot_id FROM data_assets WHERE tenant_id = %s AND asset_id = %s",
            (tenant_id, asset_id),
        ).fetchone()
        if not asset_row:
            raise HTTPException(status_code=404, detail="RESOURCE_NOT_FOUND")
        slug, current_snapshot_id = asset_row
        snapshot_id = snapshot_id or current_snapshot_id
        snap_row = snapshot_id and conn.execute(
            "SELECT source_descriptor FROM dataset_snapshots WHERE tenant_id = %s AND asset_id = %s AND snapshot_id = %s",
            (tenant_id, asset_id, snapshot_id),
        ).fetchone()
        if not snap_row:
            raise HTTPException(status_code=404, detail="RESOURCE_NOT_FOUND")
        resolved = resolve_snapshot_protection(conn, tenant_id, snapshot_id)
        protected = resolved.protected_columns
        conn.commit()

        source, out = workdir / "source.parquet", workdir / "masked.parquet"
        try:
            spool_canonical(store, tenant_id, snap_row[0], s3_settings.bucket_snapshots, source)
            parquet = pq.ParquetFile(source)
            schema = pa.schema([
                pa.field(f.name, pa.string()) if f.name in protected else f for f in parquet.schema_arrow
            ])
            with pq.ParquetWriter(out, schema) as writer:
                for batch in parquet.iter_batches(batch_size=EXPORT_BATCH_ROWS):
                    writer.write_batch(pa.RecordBatch.from_arrays(
                        [_mask_array(batch.column(i)) if name in protected else batch.column(i)
                         for i, name in enumerate(batch.schema.names)],
                        schema=schema,
                    ))
        except SnapshotObjectError as exc:
            status = 503 if exc.code == "STORAGE_UNAVAILABLE" else 409
            raise HTTPException(status_code=status, detail=exc.code) from exc
        except (pa.ArrowException, OSError) as exc:
            raise HTTPException(status_code=409, detail="MALFORMED_IMPORT") from exc
        finally:
            source.unlink(missing_ok=True)

        try:
            begin_tenant_transaction(conn, tenant_id)
            current = resolve_snapshot_protection(conn, tenant_id, snapshot_id)
            conn.commit()
        except BaseException:
            out.unlink(missing_ok=True)
            raise
        if current.policy_version != resolved.policy_version or current.protected_columns != protected:
            out.unlink(missing_ok=True)
            raise HTTPException(status_code=409, detail="POLICY_VERSION_CONFLICT")
        return MaskedExportArtifact(f"{slug or 'asset'}_masked.parquet", out, resolved.policy_version)


def _mask_array(values: pa.Array) -> pa.Array:
    """FULL_MASK: null stays null, empty string stays empty, everything else becomes the sentinel."""
    as_text = values.cast(pa.string(), safe=False) if not pa.types.is_nested(values.type) else None
    empty = pc.equal(as_text, "") if as_text is not None else pa.nulls(len(values), pa.bool_())
    masked = pc.if_else(pc.fill_null(empty, False), "", REDACTED_SENTINEL)
    return pc.if_else(pc.is_null(values), pa.nulls(len(values), pa.string()), masked)
