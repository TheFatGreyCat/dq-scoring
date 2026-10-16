"""Integration tests for S3 / MinIO storage operations against local MinIO."""

from __future__ import annotations

import io
from uuid import uuid4

import pytest

from dq_scoring.adapters.storage.s3_object_store import S3ObjectStoreAdapter
from dq_scoring.adapters.storage.s3_settings import get_s3_settings
from dq_scoring.ports.object_store import ObjectRef, UploadedPart


@pytest.fixture
def storage_adapter() -> S3ObjectStoreAdapter:
    settings = get_s3_settings()
    return S3ObjectStoreAdapter(settings=settings)


def test_minio_storage_lifecycle(storage_adapter: S3ObjectStoreAdapter) -> None:
    settings = get_s3_settings()
    test_id = uuid4().hex[:8]
    staging_key = f"tests/integration/{test_id}/test_upload.csv"

    # 1. Create multipart
    mp_id = storage_adapter.create_multipart(settings.bucket_staging, staging_key)
    assert mp_id

    # 2. Upload part 1 (5 MiB minimal valid S3 part for multipart)
    part_bytes = b"id,val\n" + (b"1,test\n" * (1024 * 1024))  # > 5 MiB
    stream = io.BytesIO(part_bytes)
    etag1 = storage_adapter.upload_part(
        bucket=settings.bucket_staging,
        key=staging_key,
        multipart_id=mp_id,
        part_number=1,
        stream=stream,
        length=len(part_bytes),
    )
    assert etag1

    # 3. List parts
    parts = storage_adapter.list_parts(settings.bucket_staging, staging_key, mp_id)
    assert len(parts) == 1
    assert parts[0].part_number == 1
    assert parts[0].etag == etag1

    # 4. Complete multipart
    meta = storage_adapter.complete_multipart(
        bucket=settings.bucket_staging,
        key=staging_key,
        multipart_id=mp_id,
        parts=[UploadedPart(part_number=1, etag=etag1, size_bytes=len(part_bytes))],
    )
    assert meta.size_bytes == len(part_bytes)
    assert meta.ref.key == staging_key

    # 5. Head object
    head_meta = storage_adapter.head(ObjectRef(bucket=settings.bucket_staging, key=staging_key))
    assert head_meta.size_bytes == len(part_bytes)

    # 6. Open stream and verify contents
    body = storage_adapter.open_stream(ObjectRef(bucket=settings.bucket_staging, key=staging_key))
    chunk = body.read(7)
    assert chunk == b"id,val\n"
    body.close()

    # 7. List objects
    items, _ = storage_adapter.list_objects(
        bucket=settings.bucket_staging,
        prefix=f"tests/integration/{test_id}/",
    )
    assert any(i.ref.key == staging_key for i in items)


def test_minio_abort_multipart(storage_adapter: S3ObjectStoreAdapter) -> None:
    settings = get_s3_settings()
    test_id = uuid4().hex[:8]
    staging_key = f"tests/integration/{test_id}/abort_upload.csv"

    mp_id = storage_adapter.create_multipart(settings.bucket_staging, staging_key)
    assert mp_id

    # Abort upload
    storage_adapter.abort_multipart(settings.bucket_staging, staging_key, mp_id)

    # Verify head raises FileNotFoundError
    with pytest.raises(FileNotFoundError):
        storage_adapter.head(ObjectRef(bucket=settings.bucket_staging, key=staging_key))
