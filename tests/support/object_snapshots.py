"""Test support helpers for creating and registering immutable object storage snapshots."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
from fastapi.testclient import TestClient

from dq_scoring.adapters.source.tabular_import import TabularImportAdapter
from dq_scoring.adapters.storage.s3_object_store import S3ObjectStoreAdapter
from dq_scoring.adapters.storage.s3_settings import get_s3_settings
from dq_scoring.core.entities import DatasetSnapshot
from dq_scoring.ports.object_store import ObjectRef
from dq_scoring.workers.import_worker import ImportWorker


def create_test_snapshot(
    file_path: Path | str,
    *,
    tenant_id: UUID | None = None,
    asset_id: UUID | None = None,
    snapshot_id: UUID | None = None,
    file_format: str = "CSV",
    delimiter: str = ",",
    column_names_mapping: list[str] | None = None,
) -> DatasetSnapshot:
    """Upload a local file directly to staging S3 and normalize to canonical Parquet snapshot."""
    path = Path(file_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Fixture file not found: {path}")

    s3_settings = get_s3_settings()
    store = S3ObjectStoreAdapter(settings=s3_settings)
    tabular_adapter = TabularImportAdapter(store=store)

    tenant = tenant_id or uuid4()
    asset = asset_id or uuid4()
    snap_id = snapshot_id or uuid4()
    upload_id = uuid4()
    ext = file_format.lower()
    staging_key = f"staging/{tenant}/{upload_id}/source.{ext}"

    staged_meta = store.put_file(s3_settings.bucket_staging, staging_key, path)

    inspection = tabular_adapter.inspect_and_normalize(
        source=ObjectRef(
            bucket=s3_settings.bucket_staging,
            key=staging_key,
            version_id=staged_meta.ref.version_id,
        ),
        destination_bucket=s3_settings.bucket_snapshots,
        destination_prefix=f"snapshots/{tenant}/{upload_id}/attempt-1",
        file_format=file_format.upper(),
        delimiter=delimiter,
        column_names_mapping=column_names_mapping,
    )

    source_descriptor = {
        "bucket": inspection.raw_ref.bucket,
        "key": inspection.raw_ref.key,
        "version_id": inspection.raw_ref.version_id,
        "size_bytes": inspection.raw_size_bytes,
        "content_sha256": inspection.raw_sha256,
        "format": file_format.upper(),
        "canonical": {
            "bucket": inspection.canonical_ref.bucket,
            "key": inspection.canonical_ref.key,
            "version_id": inspection.canonical_ref.version_id,
            "size_bytes": inspection.canonical_size_bytes,
            "content_sha256": inspection.canonical_sha256,
            "format": "PARQUET",
            "s3a_uri": inspection.canonical_ref.s3a_uri,
        },
        "normalization_version": inspection.normalization_version,
    }

    return DatasetSnapshot(
        snapshot_id=snap_id,
        tenant_id=tenant,
        asset_id=asset,
        source_kind="OBJECT_FILE",
        source_descriptor=source_descriptor,
        schema_definition={"columns": inspection.columns},
        total_rows=inspection.exact_row_count,
        total_columns=len(inspection.columns),
        captured_at=datetime.now(UTC),
    )


def register_snapshot_via_api(
    client: TestClient,
    headers: dict[str, str],
    worker_db: str | psycopg.Connection | None = None,
    content_or_path: bytes | str | Path | None = None,
    *,
    asset_id: str | UUID | None = None,
    asset_name: str | None = None,
    file_format: str = "CSV",
    filename: str = "data.csv",
    delimiter: str = ",",
) -> dict[str, Any]:
    """Execute real upload session -> chunk upload -> complete -> worker claim & process -> register snapshot."""
    import os
    if worker_db is None:
        worker_db = os.environ["DQ_TEST_POSTGRES_DSN"]
    if content_or_path is None:
        content_or_path = b"col1,col2\nval1,val2\n"
    if isinstance(content_or_path, (str, Path)):
        p = Path(content_or_path)
        if p.is_file():
            payload_bytes = p.read_bytes()
            if filename == "data.csv":
                filename = p.name
        else:
            payload_bytes = str(content_or_path).encode("utf-8")
    else:
        payload_bytes = content_or_path

    body: dict[str, Any] = {
        "client_request_id": str(uuid4()),
        "format": file_format.upper(),
        "original_filename": filename,
        "size_bytes": len(payload_bytes),
        "csv_options": {"delimiter": delimiter, "encoding": "utf-8"},
    }
    if asset_id is not None:
        body["asset_id"] = str(asset_id)
    else:
        body["asset_name"] = asset_name or f"Asset {uuid4().hex[:8]}"

    # 1. Initiate session
    init_resp = client.post("/api/v1/imports", headers=headers, json=body)
    assert init_resp.status_code == 201, f"Failed to initiate import: {init_resp.text}"
    session_data = init_resp.json()
    upload_id = session_data["upload_id"]

    # 2. Upload part 1
    part_resp = client.post(
        f"/api/v1/imports/{upload_id}/parts/1",
        headers={**headers, "Content-Length": str(len(payload_bytes))},
        content=payload_bytes,
    )
    assert part_resp.status_code == 200, f"Failed to upload part: {part_resp.text}"
    etag = part_resp.json()["etag"]

    # 3. Complete upload
    complete_resp = client.post(
        f"/api/v1/imports/{upload_id}/complete",
        headers=headers,
        json={"parts": [{"part_number": 1, "etag": etag}]},
    )
    assert complete_resp.status_code == 202, f"Failed to complete import: {complete_resp.text}"

    # 4. Worker process session
    s3_settings = get_s3_settings()
    store = S3ObjectStoreAdapter(settings=s3_settings)
    worker = ImportWorker(store=store, worker_id=f"test-worker-{uuid4().hex[:6]}")

    def _process_with_conn(conn: psycopg.Connection) -> None:
        claimed = worker.claim_next_session(conn)
        assert claimed is not None, "Worker failed to claim staged import session"
        worker.process_session(conn, claimed)
        conn.commit()

    if isinstance(worker_db, str):
        with psycopg.connect(worker_db, autocommit=False) as conn:
            _process_with_conn(conn)
    else:
        _process_with_conn(worker_db)

    # 5. Register snapshot
    reg_resp = client.post(
        f"/api/v1/imports/{upload_id}/register",
        headers=headers,
        json={"acknowledged_warnings": ["SINGLE_COLUMN_INPUT"]},
    )
    assert reg_resp.status_code == 200, f"Failed to register snapshot: {reg_resp.text}"
    return reg_resp.json()
