"""Test support helpers for creating and registering immutable object storage snapshots."""

from __future__ import annotations

from dataclasses import asdict
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
    """Upload a local file to staging S3 and freeze one immutable raw (v2 descriptor, no canonical Parquet)."""
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

    inspection = tabular_adapter.inspect_snapshot(
        source=ObjectRef(
            bucket=s3_settings.bucket_staging,
            key=staging_key,
            version_id=staged_meta.ref.version_id,
        ),
        source_store=store,
        storage_mode="OWNED_RAW",
        destination_bucket=s3_settings.bucket_snapshots,
        destination_prefix=f"snapshots/{tenant}/{upload_id}",
        file_format=file_format.upper(),
        delimiter=delimiter,
        column_names_mapping=column_names_mapping,
    )

    source_descriptor = {
        "descriptor_version": 2,
        "storage_mode": inspection.storage_mode,
        "bucket": inspection.raw_ref.bucket,
        "key": inspection.raw_ref.key,
        "version_id": inspection.raw_ref.version_id,
        "content_sha256": inspection.raw_sha256,
        "size_bytes": inspection.raw_size_bytes,
        "format": file_format.upper(),
        "normalization_version": inspection.normalization_version,
        "normalization": {**asdict(inspection.normalization), "columns": list(inspection.normalization.columns)},
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
    process_full_profile: bool = False,
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
    registered = reg_resp.json()
    if process_full_profile:
        process_full_profile_for(registered["snapshot_id"], worker_db if isinstance(worker_db, str) else None)
    return registered


_PROFILE_COMPUTE: Any = None


def process_full_profile_for(snapshot_id: str | UUID, dsn: str | None = None) -> None:
    """Run the real Spark profile worker until this snapshot's current FULL job is COMPLETE."""
    import os

    from dq_scoring.adapters.compute.spark_compute import PySparkComputeAdapter
    from dq_scoring.adapters.queue.postgres_profile_queue import PostgresProfileQueue
    from dq_scoring.workers.snapshot_profile_worker import SnapshotProfileWorker

    global _PROFILE_COMPUTE
    dsn = dsn or os.environ["DQ_TEST_POSTGRES_DSN"]
    if _PROFILE_COMPUTE is None:
        _PROFILE_COMPUTE = PySparkComputeAdapter()
    worker = SnapshotProfileWorker(
        PostgresProfileQueue(dsn, f"test-profile-{uuid4().hex[:6]}"), _PROFILE_COMPUTE, heartbeat_interval=0.5
    )
    while True:
        with psycopg.connect(dsn) as conn:
            state = conn.execute(
                "SELECT state FROM snapshot_profile_jobs WHERE snapshot_id=%s", (UUID(str(snapshot_id)),)
            ).fetchone()
        assert state is not None, "registration did not enqueue a FULL profile job"
        if state[0] == "COMPLETE":
            return
        assert state[0] in ("QUEUED", "RUNNING"), f"FULL profile ended in {state[0]}"
        assert worker.run_once(), "FULL profile job was not claimable"
