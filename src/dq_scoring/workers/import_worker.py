"""Import worker executing dataset inspection, preview generation, and canonical normalization."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import psycopg
from botocore.exceptions import BotoCoreError, ClientError
from psycopg.types.json import Jsonb
from pyarrow import ArrowException

from dq_scoring.adapters.db.tenant_context import set_tenant_context
from dq_scoring.adapters.source.tabular_import import (
    ImportInspectionException,
    TabularImportAdapter,
)
from dq_scoring.adapters.storage.s3_settings import (
    ImportSettings,
    S3Settings,
    get_import_settings,
    get_s3_settings,
)
from dq_scoring.common.privacy import SENSITIVE_CATEGORIES
from dq_scoring.ports.object_store import IObjectStorePort, ObjectRef
from dq_scoring.services.privacy_rule_service import load_pinned_rules

logger = logging.getLogger("dq_scoring.workers.import_worker")


def _declared_protection(conn: psycopg.Connection, tenant_id: UUID, asset_id: UUID) -> tuple[int, tuple[str, ...]]:
    """Asset protection version plus columns declared sensitive; version fences changes during inspection."""
    version = conn.execute(
        "SELECT version FROM asset_protection_revisions WHERE tenant_id = %s AND asset_id = %s",
        (tenant_id, asset_id),
    ).fetchone()
    columns = conn.execute(
        """SELECT column_name FROM asset_column_classifications
           WHERE tenant_id = %s AND asset_id = %s AND category = ANY(%s) ORDER BY column_name""",
        (tenant_id, asset_id, sorted(SENSITIVE_CATEGORIES)),
    ).fetchall()
    return (version[0] if version else 0), tuple(r[0] for r in columns)


class ImportWorker:
    """Processes STAGED upload sessions with distributed lease fencing."""

    def __init__(
        self,
        store: IObjectStorePort,
        worker_id: str = "import-worker-1",
        s3_settings: S3Settings | None = None,
        import_settings: ImportSettings | None = None,
    ) -> None:
        self.store = store
        self.worker_id = worker_id
        self.s3_settings = s3_settings or get_s3_settings()
        self.import_settings = import_settings or get_import_settings()
        self.adapter = TabularImportAdapter(
            store=self.store,
            temp_root=self.import_settings.temp_root,
        )

    def heartbeat(self, conn: psycopg.Connection, upload_id: UUID, lease_generation: int) -> bool:
        """Extend active worker lease; returns True if lease remains owned, False if stolen/expired."""
        now = datetime.now(UTC)
        new_expires_at = now + timedelta(seconds=self.import_settings.lease_seconds)
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE dataset_upload_sessions
                SET lease_expires_at = %s,
                    updated_at = now()
                WHERE upload_id = %s
                  AND lease_generation = %s
                  AND lease_owner = %s
                  AND lease_expires_at >= now()
                  AND status = 'VERIFYING';
                """,
                (new_expires_at, upload_id, lease_generation, self.worker_id),
            )
            return cur.rowcount > 0

    def claim_next_session(self, conn: psycopg.Connection) -> dict[str, Any] | None:
        """Atomically claim the oldest STAGED or expired VERIFYING upload session."""
        now = datetime.now(UTC)
        lease_expires = now + timedelta(seconds=self.import_settings.lease_seconds)

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT upload_id, tenant_id, lease_generation, attempt_count, status, expires_at
                FROM dataset_upload_sessions
                WHERE status = 'STAGED'
                   OR (status = 'VERIFYING' AND lease_expires_at < now())
                ORDER BY created_at ASC
                LIMIT 1
                FOR UPDATE SKIP LOCKED;
                """
            )
            row = cur.fetchone()
            if not row:
                return None

            upload_id, _tenant_id, current_gen, attempt_count, _old_status, expires_at = row
            if expires_at and expires_at < now:
                cur.execute(
                    """
                    UPDATE dataset_upload_sessions
                    SET status = 'FAILED',
                        error_reason = 'IMPORT_EXPIRED',
                        updated_at = now()
                    WHERE upload_id = %s;
                    """,
                    (upload_id,),
                )
                return None

            next_attempt = attempt_count + 1

            if next_attempt > 3:
                # Retry budget exhausted
                cur.execute(
                    """
                    UPDATE dataset_upload_sessions
                    SET status = 'FAILED',
                        error_reason = 'IMPORT_RETRY_EXHAUSTED',
                        updated_at = now()
                    WHERE upload_id = %s;
                    """,
                    (upload_id,),
                )
                return None

            next_gen = current_gen + 1
            cur.execute(
                """
                UPDATE dataset_upload_sessions
                SET status = 'VERIFYING',
                    lease_owner = %s,
                    lease_generation = %s,
                    attempt_count = %s,
                    lease_expires_at = %s,
                    updated_at = now()
                WHERE upload_id = %s
                RETURNING upload_id, tenant_id, asset_id, asset_name, format, staging_key,
                          destination_location, manifest, lease_generation;
                """,
                (self.worker_id, next_gen, next_attempt, lease_expires, upload_id),
            )
            claimed = cur.fetchone()
            if not claimed:
                return None

            return {
                "upload_id": claimed[0],
                "tenant_id": claimed[1],
                "asset_id": claimed[2],
                "asset_name": claimed[3],
                "format": claimed[4],
                "staging_key": claimed[5],
                "destination_location": claimed[6],
                "manifest": claimed[7] or {},
                "lease_generation": claimed[8],
            }

    def process_session(self, conn: psycopg.Connection, session: dict[str, Any]) -> None:
        """Run inspection, profiling, and canonical Parquet creation under fencing check."""
        upload_id = session["upload_id"]
        tenant_id = session["tenant_id"]
        lease_gen = session["lease_generation"]
        fmt = session["format"]
        manifest = session["manifest"]

        set_tenant_context(conn, tenant_id)
        pinned = load_pinned_rules(conn, tenant_id)

        # Preflight check: bucket versioning required
        if not self.store.is_versioning_enabled(self.s3_settings.bucket_snapshots):
            logger.error("Bucket %s does not have versioning enabled", self.s3_settings.bucket_snapshots)
            patch = {"error_code": "SNAPSHOT_VERSIONING_REQUIRED"}
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE dataset_upload_sessions
                    SET status = 'FAILED',
                        error_reason = 'SNAPSHOT_VERSIONING_REQUIRED',
                        manifest = COALESCE(manifest, '{}'::jsonb) || %s::jsonb,
                        updated_at = now()
                    WHERE upload_id = %s
                      AND lease_generation = %s
                      AND lease_owner = %s
                      AND lease_expires_at >= now()
                      AND status = 'VERIFYING';
                    """,
                    (Jsonb(patch), upload_id, lease_gen, self.worker_id),
                )
            return

        staging_bucket = manifest.get("staging_bucket") or self.s3_settings.bucket_staging
        staging_key = session["staging_key"]
        source_ref = ObjectRef(bucket=staging_bucket, key=staging_key)

        dest_prefix = f"snapshots/{tenant_id}/{upload_id}/attempt-{lease_gen}"
        col_mapping = manifest.get("column_names_mapping")
        csv_opts = manifest.get("csv_options") or {}
        delimiter = csv_opts.get("delimiter", ",")
        asset_id = session.get("asset_id")

        initial_policy_version = 0
        extra_cols: tuple[str, ...] = ()
        if asset_id:
            initial_policy_version, extra_cols = _declared_protection(conn, tenant_id, asset_id)

        try:
            selected = manifest.get("source_ref")
            if selected:
                current = self.store.head(source_ref)
                if current.etag != selected.get("etag") or current.version_id != selected.get("version_id") or current.size_bytes != selected.get("size_bytes"):
                    raise ImportInspectionException("OBJECT_CHANGED", "Selected source changed before validation.")
            inspection = self.adapter.inspect_and_normalize(
                source=source_ref,
                destination_bucket=self.s3_settings.bucket_snapshots,
                destination_prefix=dest_prefix,
                file_format=fmt,
                column_names_mapping=col_mapping,
                delimiter=delimiter,
                privacy_columns=extra_cols,
                privacy_rules=pinned.rules,
            )

            if asset_id and _declared_protection(conn, tenant_id, asset_id)[0] != initial_policy_version:
                raise ImportInspectionException("POLICY_CHANGED", "Asset protection policy changed during inspection.")
            source_descriptor = {
                "bucket": inspection.raw_ref.bucket,
                "key": inspection.raw_ref.key,
                "version_id": inspection.raw_ref.version_id,
                "content_sha256": inspection.raw_sha256,
                "size_bytes": inspection.raw_size_bytes,
                "format": fmt,
                "canonical": {
                    "bucket": inspection.canonical_ref.bucket,
                    "key": inspection.canonical_ref.key,
                    "version_id": inspection.canonical_ref.version_id,
                    "content_sha256": inspection.canonical_sha256,
                    "size_bytes": inspection.canonical_size_bytes,
                    "format": "PARQUET",
                    "s3a_uri": inspection.canonical_ref.s3a_uri,
                },
                "normalization_version": inspection.normalization_version,
            }

            patch = {
                "source_descriptor": source_descriptor,
                "columns": inspection.columns,
                "exact_row_count": inspection.exact_row_count,
                "preview": inspection.preview_rows,
                "profile": inspection.profile,
                "warnings": inspection.warnings,
                "normalization_version": inspection.normalization_version,
                "sensitive_scan": inspection.sensitive_scan,
                "privacy_rules": pinned.to_json(),
                "privacy_config_version": pinned.config_version,
                "privacy_detector_digest": pinned.digest,
                "policy_version": initial_policy_version,
                "error_code": None,
                "invalid_params": None,
            }

            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE dataset_upload_sessions
                    SET status = 'VERIFIED',
                        computed_sha256 = %s,
                        destination_location = %s,
                        manifest = COALESCE(manifest, '{}'::jsonb) || %s::jsonb,
                        error_reason = NULL,
                        updated_at = now()
                    WHERE upload_id = %s
                      AND lease_generation = %s
                      AND lease_owner = %s
                      AND lease_expires_at >= now()
                      AND status = 'VERIFYING';
                    """,
                    (
                        inspection.raw_sha256,
                        inspection.canonical_ref.s3a_uri,
                        Jsonb(patch),
                        upload_id,
                        lease_gen,
                        self.worker_id,
                    ),
                )
                if cur.rowcount == 0:
                    logger.warning("Fencing conflict: lease expired or preempted for session %s", upload_id)

        except ImportInspectionException as exc:
            patch = {
                "error_code": exc.error_code,
                "invalid_params": exc.invalid_params,
            }
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE dataset_upload_sessions
                    SET status = 'REJECTED',
                        error_reason = %s,
                        manifest = COALESCE(manifest, '{}'::jsonb) || %s::jsonb,
                        updated_at = now()
                    WHERE upload_id = %s
                      AND lease_generation = %s
                      AND lease_owner = %s
                      AND lease_expires_at >= now()
                      AND status = 'VERIFYING';
                    """,
                    (exc.error_code, Jsonb(patch), upload_id, lease_gen, self.worker_id),
                )

        except (BotoCoreError, ClientError, OSError, ArrowException, ValueError):
            logger.error("Unexpected import failure for upload %s", upload_id)
            patch = {"error_code": "INTERNAL_WORKER_ERROR"}
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE dataset_upload_sessions
                    SET status = 'FAILED',
                        error_reason = 'INTERNAL_WORKER_ERROR',
                        manifest = COALESCE(manifest, '{}'::jsonb) || %s::jsonb,
                        updated_at = now()
                    WHERE upload_id = %s
                      AND lease_generation = %s
                      AND lease_owner = %s
                      AND lease_expires_at >= now()
                      AND status = 'VERIFYING';
                    """,
                    (Jsonb(patch), upload_id, lease_gen, self.worker_id),
                )
