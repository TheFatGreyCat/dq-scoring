"""Import worker inspecting one immutable raw snapshot under lease fencing."""

from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import psycopg
from botocore.exceptions import BotoCoreError, ClientError
from psycopg.types.json import Jsonb
from pyarrow import ArrowException

from dq_scoring.adapters.db.postgres_import_store import PostgresImportStore
from dq_scoring.adapters.db.tenant_context import set_tenant_context
from dq_scoring.adapters.source.tabular_import import TabularImportAdapter
from dq_scoring.adapters.source.tabular_normalization import ImportInspectionException
from dq_scoring.adapters.storage.normalized_snapshot import (
    legacy_equivalence_witness,
    resolve_snapshot_source,
    validate_descriptor,
)
from dq_scoring.adapters.storage.s3_object_store import S3ObjectStoreAdapter
from dq_scoring.adapters.storage.s3_settings import (
    ImportSettings,
    S3Settings,
    get_import_settings,
    get_s3_settings,
)
from dq_scoring.adapters.storage.snapshot_objects import SnapshotObjectError
from dq_scoring.adapters.storage.source_settings import (
    get_source_settings,
    source_binding_sha256,
)
from dq_scoring.common.privacy import SENSITIVE_CATEGORIES
from dq_scoring.ports.object_store import (
    IObjectStorePort,
    ObjectChangedError,
    ObjectRef,
)
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
        self.adapter = TabularImportAdapter(store=self.store)

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
            # Pick the candidate tenant without row locks, take the shared storage lock, then lock the row:
            # same order as API mutators and the pruner (tenant lock -> row lock), so no lock inversion.
            cur.execute(
                """
                SELECT upload_id, tenant_id FROM dataset_upload_sessions
                WHERE status = 'STAGED'
                   OR (status = 'VERIFYING' AND lease_expires_at < now())
                ORDER BY created_at ASC
                LIMIT 1;
                """
            )
            candidate = cur.fetchone()
            if not candidate:
                return None
            PostgresImportStore.lock_tenant_storage(conn, candidate[1])
            cur.execute(
                """
                SELECT upload_id, tenant_id, lease_generation, attempt_count, status, expires_at
                FROM dataset_upload_sessions
                WHERE upload_id = %s
                  AND (status = 'STAGED'
                       OR (status = 'VERIFYING' AND lease_expires_at < now()))
                FOR UPDATE SKIP LOCKED;
                """,
                (candidate[0],),
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
        """Inspect raw bytes and publish only the winning lease's descriptor."""
        upload_id = session["upload_id"]
        tenant_id = session["tenant_id"]
        lease_gen = session["lease_generation"]
        fmt = session["format"]
        manifest = session["manifest"]

        set_tenant_context(conn, tenant_id)
        PostgresImportStore.lock_tenant_storage(conn, tenant_id)
        pinned = load_pinned_rules(conn, tenant_id)

        col_mapping = manifest.get("column_names_mapping")
        csv_opts = manifest.get("csv_options") or {}
        delimiter = csv_opts.get("delimiter", ",")
        asset_id = session.get("asset_id")

        initial_policy_version = 0
        extra_cols: tuple[str, ...] = ()
        if asset_id:
            initial_policy_version, extra_cols = _declared_protection(conn, tenant_id, asset_id)

        inspection = None
        try:
            source_store = self.store
            storage_mode = manifest.get('storage_mode', 'OWNED_RAW')
            selected = manifest.get('source_ref') or {}
            source_ref = ObjectRef(manifest.get('staging_bucket') or self.s3_settings.bucket_staging,
                                   session['staging_key'], selected.get('version_id'))
            reuse_owned = False
            previous = manifest.get('source_descriptor')
            frozen = manifest.get('owned_raw_ref')
            if previous and previous.get('descriptor_version') == 2 and previous.get('storage_mode') == 'OWNED_RAW':
                source_store, source_ref, _ = resolve_snapshot_source(tenant_id, previous, self.store, self.s3_settings)
                reuse_owned = True
            elif frozen:
                source_ref = ObjectRef(**frozen)
                if source_ref.bucket != self.s3_settings.bucket_snapshots or not source_ref.key.startswith(f'snapshots/{tenant_id}/{upload_id}/') or not source_ref.version_id or source_ref.version_id == 'null' or any(p in ('', '.', '..') for p in source_ref.key.split('/')) or '\\' in source_ref.key:
                    raise ImportInspectionException('STORAGE_VIOLATION', 'Invalid retained raw object.')
                reuse_owned = True
            elif selected.get('source_id') == 'shared':
                config = get_source_settings()
                config.validate_owned_separation(self.s3_settings)
                if not config.enabled or config.bucket != source_ref.bucket or not any(source_ref.key.startswith(p) for p in config.tenant_prefixes.get(tenant_id, [])):
                    raise ImportInspectionException('TENANT_ISOLATION_VIOLATION', 'Source is not authorized.')
                if manifest.get('source_binding_sha256') != source_binding_sha256(config):
                    raise ImportInspectionException('STORAGE_VIOLATION', 'Source binding changed.')
                source_store = S3ObjectStoreAdapter(config.as_s3_settings())
            elif manifest.get('upload_layout_version') == 2:
                expected_key = f'snapshots/{tenant_id}/{upload_id}/source.{fmt.lower()}'
                if source_ref.bucket != self.s3_settings.bucket_snapshots or source_ref.key != expected_key:
                    raise ImportInspectionException('STORAGE_VIOLATION', 'Invalid upload object.')
                reuse_owned = True
            elif source_ref.bucket != self.s3_settings.bucket_staging:
                raise ImportInspectionException('STORAGE_VIOLATION', 'Invalid staging bucket.')
            if selected and not reuse_owned:
                current = source_store.head(source_ref)
                current_version = current.version_id if current.version_id not in (None, '', 'null') else None
                if current.etag != selected.get('etag') or current_version != selected.get('version_id') or current.size_bytes != selected.get('size_bytes'):
                    raise ImportInspectionException('OBJECT_CHANGED', 'Selected source metadata changed.')
            inspection = self.adapter.inspect_snapshot(
                source=source_ref,
                source_store=source_store,
                storage_mode=storage_mode,
                source_id=None if reuse_owned else selected.get('source_id'),
                reuse_owned=reuse_owned,
                destination_bucket=self.s3_settings.bucket_snapshots,
                destination_prefix=f'snapshots/{tenant_id}/{upload_id}',
                file_format=fmt,
                column_names_mapping=col_mapping,
                delimiter=delimiter,
                privacy_columns=extra_cols,
                privacy_rules=pinned.rules,
            )

            if asset_id and _declared_protection(conn, tenant_id, asset_id)[0] != initial_policy_version:
                raise ImportInspectionException("POLICY_CHANGED", "Asset protection policy changed during inspection.")
            source_descriptor = {
                'descriptor_version': 2,
                'storage_mode': inspection.storage_mode,
                "bucket": inspection.raw_ref.bucket,
                "key": inspection.raw_ref.key,
                "version_id": inspection.raw_ref.version_id,
                "content_sha256": inspection.raw_sha256,
                "size_bytes": inspection.raw_size_bytes,
                "format": fmt,
                "normalization_version": inspection.normalization_version,
                'normalization': {**asdict(inspection.normalization), 'columns': list(inspection.normalization.columns)},
            }
            if storage_mode == 'EXTERNAL_VERSION':
                source_descriptor.update(source_id='shared', source_binding_sha256=manifest['source_binding_sha256'])
            validate_descriptor(source_descriptor)
            witness = legacy_equivalence_witness(conn, tenant_id, asset_id, source_descriptor, self.store, self.s3_settings)

            patch = {
                "source_descriptor": source_descriptor,
                'legacy_equivalence': witness,
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
                        inspection.raw_ref.s3a_uri,
                        Jsonb(patch),
                        upload_id,
                        lease_gen,
                        self.worker_id,
                    ),
                )
                if cur.rowcount == 0:
                    logger.warning("Fencing conflict: lease expired or preempted for session %s", upload_id)

        except ImportInspectionException as exc:
            frozen_ref = getattr(exc, 'raw_ref', None) or (inspection.raw_ref if inspection else None)
            self._inspection_failure(conn, upload_id, lease_gen, exc.error_code, exc.invalid_params,
                                     raw_ref=frozen_ref if storage_mode == 'OWNED_RAW' else None)

        except SnapshotObjectError as exc:
            self._inspection_failure(conn, upload_id, lease_gen, exc.code,
                raw_ref=inspection.raw_ref if inspection and inspection.storage_mode == 'OWNED_RAW' else None)
        except ObjectChangedError:
            self._inspection_failure(conn, upload_id, lease_gen, 'OBJECT_CHANGED')
        except FileNotFoundError:
            self._inspection_failure(conn, upload_id, lease_gen, 'RESOURCE_NOT_FOUND')
        except (BotoCoreError, ClientError, OSError, ArrowException, ValueError):
            self._inspection_failure(conn, upload_id, lease_gen, 'STORAGE_UNAVAILABLE',
                raw_ref=inspection.raw_ref if inspection and inspection.storage_mode == 'OWNED_RAW' else None)

    def _inspection_failure(self, conn, upload_id: UUID, lease_gen: int, code: str, invalid_params=None, *, raw_ref=None) -> None:
        patch = {'error_code': code, 'invalid_params': invalid_params}
        if raw_ref is not None:
            patch['owned_raw_ref'] = asdict(raw_ref)
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE dataset_upload_sessions SET status='REJECTED',error_reason=%s,"
                "manifest=COALESCE(manifest,'{}'::jsonb)||%s::jsonb,updated_at=now() "
                "WHERE upload_id=%s AND lease_generation=%s AND lease_owner=%s "
                "AND lease_expires_at>=now() AND status='VERIFYING'",
                (code, Jsonb(patch), upload_id, lease_gen, self.worker_id),
            )

