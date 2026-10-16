"""Create object-storage successors without rewriting historical snapshots."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from uuid import UUID, uuid4

import psycopg

from dq_scoring.adapters.db.postgres_import_store import PostgresImportStore
from dq_scoring.adapters.db.tenant_context import set_tenant_context
from dq_scoring.adapters.source.tabular_import import (
    ImportInspectionException,
    TabularImportAdapter,
)
from dq_scoring.adapters.storage.s3_object_store import S3ObjectStoreAdapter
from dq_scoring.adapters.storage.s3_settings import get_s3_settings
from dq_scoring.core.exceptions import RunAbortedError
from dq_scoring.ports.object_store import ObjectRef
from dq_scoring.services.dataset_import_service import DatasetImportService


def _source(root: Path, descriptor: dict) -> tuple[Path, str]:
    raw = descriptor.get("path")
    if not isinstance(raw, str) or not raw or "://" in raw:
        raise ValueError("LEGACY_SOURCE_INVALID")
    path = (root / raw).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("LEGACY_SOURCE_OUTSIDE_ROOT")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return path, digest.hexdigest()


def migrate(conn: psycopg.Connection, tenant_id: UUID, asset_ids: list[UUID], root: Path, apply: bool) -> list[dict]:
    root = root.expanduser().resolve(strict=True)
    with conn.transaction():
        set_tenant_context(conn, tenant_id)
        with conn.cursor() as cur:
            cur.execute(
                """SELECT r.run_id FROM evaluation_runs r JOIN dataset_snapshots s
                ON s.tenant_id=r.tenant_id AND s.snapshot_id=r.snapshot_id
                WHERE r.tenant_id=%s AND s.asset_id=ANY(%s)
                  AND s.source_kind <> 'OBJECT_FILE' AND r.run_status IN ('QUEUED','LEASED','RUNNING');""",
                (tenant_id, asset_ids),
            )
            pending = [str(row[0]) for row in cur.fetchall()]
            if pending:
                print(json.dumps({"status": "DRAIN_LEGACY_RUNS", "run_ids": pending}))
                if apply:
                    raise ValueError("DRAIN_LEGACY_RUNS")
            cur.execute(
                """SELECT snapshot_id,asset_id,source_descriptor,content_sha256,created_by
                FROM dataset_snapshots WHERE tenant_id=%s AND asset_id=ANY(%s)
                AND source_kind <> 'OBJECT_FILE' ORDER BY captured_at,snapshot_id;""",
                (tenant_id, asset_ids),
            )
            legacy = cur.fetchall()
    checked = []
    for old_id, asset_id, descriptor, registered_hash, user_id in legacy:
        path, digest = _source(root, descriptor)
        if digest != registered_hash:
            raise ValueError("OBJECT_CHANGED")
        fmt = str(descriptor.get("format", path.suffix[1:])).upper()
        if fmt not in ("CSV", "PARQUET", "JSONL"):
            raise ValueError("UNSUPPORTED_FORMAT")
        checked.append((old_id, asset_id, path, fmt, digest, user_id))
    report = [{"old_snapshot_id": str(row[0]), "status": "VALIDATED"} for row in checked]
    if not apply:
        return report
    settings = get_s3_settings()
    store = S3ObjectStoreAdapter(settings=settings)
    if not store.is_versioning_enabled(settings.bucket_snapshots):
        raise ValueError("SNAPSHOT_VERSIONING_REQUIRED")
    adapter = TabularImportAdapter(store)
    for index, (old_id, asset_id, path, fmt, digest, user_id) in enumerate(checked):
        upload_id = uuid4()
        key = f"imports/{tenant_id}/{upload_id}/source.{fmt.lower()}"
        staged = store.put_file(settings.bucket_staging, key, path)
        inspection = adapter.inspect_and_normalize(
            source=ObjectRef(settings.bucket_staging, key, staged.version_id),
            destination_bucket=settings.bucket_snapshots,
            destination_prefix=f"snapshots/{tenant_id}/{upload_id}/attempt-1",
            file_format=fmt,
            delimiter=str(legacy[index][2].get("delimiter", ",")),
        )
        if inspection.raw_sha256 != digest:
            raise ValueError("OBJECT_CHANGED")
        source = {
            "bucket": inspection.raw_ref.bucket, "key": inspection.raw_ref.key,
            "version_id": inspection.raw_ref.version_id, "size_bytes": inspection.raw_size_bytes,
            "content_sha256": inspection.raw_sha256, "format": fmt,
            "canonical": {
                "bucket": inspection.canonical_ref.bucket, "key": inspection.canonical_ref.key,
                "version_id": inspection.canonical_ref.version_id,
                "size_bytes": inspection.canonical_size_bytes,
                "content_sha256": inspection.canonical_sha256, "format": "PARQUET",
            }, "normalization_version": inspection.normalization_version,
        }
        with conn.transaction():
            set_tenant_context(conn, tenant_id)
            PostgresImportStore.create_session(
                conn, upload_id=upload_id, tenant_id=tenant_id, user_id=user_id,
                asset_id=asset_id, asset_name=None, client_request_id=uuid4(), format=fmt,
                original_filename=path.name, size_bytes=inspection.raw_size_bytes,
                staging_key=key, destination_location=inspection.canonical_ref.s3a_uri,
                multipart_id=None, status="VERIFIED", manifest={
                    "source_descriptor": source, "columns": inspection.columns,
                    "exact_row_count": inspection.exact_row_count, "preview": inspection.preview_rows,
                    "profile": inspection.profile, "warnings": inspection.warnings,
                    "normalization_version": inspection.normalization_version,
                    "sensitive_scan": inspection.sensitive_scan,
                    "parent_snapshot_id": str(old_id),
                },
            )
            successor = DatasetImportService.register_snapshot(
                conn, upload_id=upload_id, tenant_id=tenant_id, user_id=user_id,
                acknowledged_warnings=inspection.warnings,
            )
        report[index] = {"old_snapshot_id": str(old_id), "new_snapshot_id": str(successor.snapshot_id), "status": "REGISTERED"}
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", type=UUID, required=True)
    parser.add_argument("--asset-id", type=UUID, action="append", required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    environment = os.getenv("DQ_ENVIRONMENT", os.getenv("DQ_APP_ENV", "development")).lower()
    if environment not in ("development", "test", "sandbox"):
        print(json.dumps({"status": "SANDBOX_ONLY"}))
        return 2
    dsn = os.getenv("DQ_MIGRATION_POSTGRES_DSN")
    if not dsn:
        print(json.dumps({"status": "MIGRATION_DSN_REQUIRED"}))
        return 2
    try:
        with psycopg.connect(dsn, autocommit=True) as conn:
            result = migrate(conn, args.tenant_id, args.asset_id, args.data_root, args.apply)
        print(json.dumps({"snapshots": result, "count": len(result)}))
        return 0
    except (ValueError, ImportInspectionException, RunAbortedError, psycopg.Error, OSError):
        print(json.dumps({"status": "MIGRATION_FAILED", "action": "Check source containment, checksum, pending runs and sandbox configuration."}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
