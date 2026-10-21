"""Unit tests for S3ObjectStoreAdapter."""

from __future__ import annotations

import io
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError
from pydantic import SecretStr

from dq_scoring.adapters.storage.s3_object_store import S3ObjectStoreAdapter
from dq_scoring.adapters.storage.s3_settings import S3Settings
from dq_scoring.ports.object_store import ObjectChangedError, ObjectRef, UploadedPart


@pytest.fixture
def mock_s3_client() -> MagicMock:
    return MagicMock()


@pytest.fixture
def adapter(mock_s3_client: MagicMock) -> S3ObjectStoreAdapter:
    settings = S3Settings(
        endpoint_url="http://localhost:9000",
        access_key_id=SecretStr("test_key"),
        secret_access_key=SecretStr("test_secret"),
    )
    return S3ObjectStoreAdapter(settings=settings, s3_client=mock_s3_client)


def test_head_returns_object_metadata(adapter: S3ObjectStoreAdapter, mock_s3_client: MagicMock) -> None:
    mock_s3_client.head_object.return_value = {
        "ContentLength": 1024,
        "ETag": '"test-etag"',
        "VersionId": "v1",
    }
    ref = ObjectRef(bucket="test-bucket", key="test/file.csv")
    meta = adapter.head(ref)
    assert meta.ref == ref
    assert meta.size_bytes == 1024
    assert meta.etag == "test-etag"
    assert meta.version_id == "v1"


def test_head_raises_file_not_found(adapter: S3ObjectStoreAdapter, mock_s3_client: MagicMock) -> None:
    mock_s3_client.head_object.side_effect = ClientError(
        {"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject"
    )
    with pytest.raises(FileNotFoundError):
        adapter.head(ObjectRef(bucket="test-bucket", key="missing.csv"))


def test_list_objects(adapter: S3ObjectStoreAdapter, mock_s3_client: MagicMock) -> None:
    mock_s3_client.list_objects_v2.return_value = {
        "Contents": [
            {"Key": "test/a.csv", "Size": 100, "ETag": '"etag-a"'},
            {"Key": "test/b.csv", "Size": 200, "ETag": '"etag-b"'},
        ],
        "NextContinuationToken": "next-token-123",
    }
    items, next_token = adapter.list_objects("test-bucket", prefix="test/", limit=10)
    assert len(items) == 2
    assert items[0].ref.key == "test/a.csv"
    assert items[1].ref.key == "test/b.csv"
    assert next_token == "next-token-123"


def test_multipart_lifecycle(adapter: S3ObjectStoreAdapter, mock_s3_client: MagicMock) -> None:
    mock_s3_client.create_multipart_upload.return_value = {"UploadId": "mp-123"}
    mock_s3_client.upload_part.return_value = {"ETag": '"part-etag-1"'}
    mock_s3_client.list_parts.return_value = {
        "Parts": [{"PartNumber": 1, "ETag": '"part-etag-1"', "Size": 1024}]
    }
    mock_s3_client.complete_multipart_upload.return_value = {
        "ETag": '"final-etag"',
        "VersionId": "v-final",
    }
    mock_s3_client.head_object.return_value = {
        "ContentLength": 1024,
        "ETag": '"final-etag"',
        "VersionId": "v-final",
    }

    mp_id = adapter.create_multipart("test-bucket", "test/out.csv")
    assert mp_id == "mp-123"

    part_stream = io.BytesIO(b"x" * 1024)
    etag = adapter.upload_part("test-bucket", "test/out.csv", mp_id, 1, part_stream, 1024)
    assert etag == "part-etag-1"

    parts = adapter.list_parts("test-bucket", "test/out.csv", mp_id)
    assert len(parts) == 1
    assert parts[0].part_number == 1

    completed_meta = adapter.complete_multipart(
        "test-bucket", "test/out.csv", mp_id, [UploadedPart(part_number=1, etag="part-etag-1")]
    )
    assert completed_meta.size_bytes == 1024
    assert completed_meta.etag == "final-etag"


def test_copy_object(adapter: S3ObjectStoreAdapter, mock_s3_client: MagicMock) -> None:
    mock_s3_client.copy_object.return_value = {
        "CopyObjectResult": {"ETag": '"copied-etag"'},
        "VersionId": "v-copy",
    }
    mock_s3_client.head_object.return_value = {
        "ContentLength": 500,
        "ETag": '"copied-etag"',
        "VersionId": "v-copy",
    }
    source = ObjectRef(bucket="staging", key="file.csv")
    meta = adapter.copy_object(source, "snapshots", "dest/file.csv")
    assert meta.ref.bucket == "snapshots"
    assert meta.ref.key == "dest/file.csv"
    assert meta.size_bytes == 500


def test_range_rejects_wrong_version_and_closes_body(adapter, mock_s3_client):
    from dq_scoring.ports.object_store import ObjectChangedError
    body = io.BytesIO(b'abc')
    mock_s3_client.get_object.return_value = {
        'Body': body, 'VersionId': 'B', 'ContentLength': 3, 'ContentRange': 'bytes 2-4/10',
    }
    with pytest.raises(ObjectChangedError):
        adapter.open_range(ObjectRef('bucket', 'key', 'A'), 2, 3)
    assert body.closed


def test_range_reads_selected_historical_version(adapter, mock_s3_client):
    mock_s3_client.get_object.return_value = {
        'Body': io.BytesIO(b'abc'), 'VersionId': 'A', 'ContentLength': 3, 'ContentRange': 'bytes 2-4/10',
    }
    with adapter.open_range(ObjectRef('bucket', 'key', 'A'), 2, 3) as body:
        assert body.read() == b'abc'
    mock_s3_client.get_object.assert_called_once_with(Bucket='bucket', Key='key', VersionId='A', Range='bytes=2-4')


def test_missing_historical_version_never_falls_back(adapter, mock_s3_client):
    mock_s3_client.get_object.side_effect = ClientError({'Error': {'Code': 'NoSuchVersion'}}, 'GetObject')
    with pytest.raises(FileNotFoundError):
        adapter.open_range(ObjectRef('bucket', 'key', 'A'), 0, 1)


def test_open_stream_sends_if_match_and_version(adapter: S3ObjectStoreAdapter, mock_s3_client: MagicMock) -> None:
    mock_s3_client.get_object.return_value = {"Body": io.BytesIO(b"x")}
    adapter.open_stream(ObjectRef("bucket", "key", "A"), if_match_etag='"etag-1"')
    mock_s3_client.get_object.assert_called_once_with(Bucket="bucket", Key="key", VersionId="A", IfMatch='"etag-1"')


def test_open_stream_without_if_match_sends_no_precondition(adapter: S3ObjectStoreAdapter, mock_s3_client: MagicMock) -> None:
    mock_s3_client.get_object.return_value = {"Body": io.BytesIO(b"x")}
    adapter.open_stream(ObjectRef("bucket", "key"))
    mock_s3_client.get_object.assert_called_once_with(Bucket="bucket", Key="key")


@pytest.mark.parametrize("code", ["412", "PreconditionFailed"])
def test_open_stream_precondition_failure_is_object_changed(adapter: S3ObjectStoreAdapter, mock_s3_client: MagicMock, code: str) -> None:
    mock_s3_client.get_object.side_effect = ClientError({"Error": {"Code": code}}, "GetObject")
    with pytest.raises(ObjectChangedError):
        adapter.open_stream(ObjectRef("bucket", "key"), if_match_etag="etag-1")


def test_list_versions_yields_real_versions_only(adapter: S3ObjectStoreAdapter, mock_s3_client: MagicMock) -> None:
    mock_s3_client.get_paginator.return_value.paginate.return_value = [
        {"Versions": [{"Key": "k", "VersionId": "v1", "Size": 3, "ETag": '"e"'}, {"Key": "u", "VersionId": "null", "Size": 1}],
         "DeleteMarkers": [{"Key": "k", "VersionId": "dm"}]},
    ]
    items = list(adapter.list_versions("bucket", "k"))
    assert [(i.ref.key, i.ref.version_id) for i in items] == [("k", "v1"), ("u", None)]
    mock_s3_client.get_paginator.assert_called_once_with("list_object_versions")


@pytest.mark.parametrize("version", [None, "", "null"])
def test_delete_version_requires_exact_version(adapter: S3ObjectStoreAdapter, mock_s3_client: MagicMock, version) -> None:
    with pytest.raises(ValueError):
        adapter.delete_version(ObjectRef("bucket", "key", version))
    mock_s3_client.delete_object.assert_not_called()


def test_delete_version_sends_version_and_maps_errors(adapter: S3ObjectStoreAdapter, mock_s3_client: MagicMock) -> None:
    adapter.delete_version(ObjectRef("bucket", "key", "A"))
    mock_s3_client.delete_object.assert_called_once_with(Bucket="bucket", Key="key", VersionId="A")
    mock_s3_client.delete_object.side_effect = ClientError({"Error": {"Code": "NoSuchVersion"}}, "DeleteObject")
    with pytest.raises(FileNotFoundError):
        adapter.delete_version(ObjectRef("bucket", "key", "A"))
    mock_s3_client.delete_object.side_effect = ClientError({"Error": {"Code": "AccessDenied"}}, "DeleteObject")
    with pytest.raises(PermissionError):
        adapter.delete_version(ObjectRef("bucket", "key", "A"))


def test_delete_version_maps_minio_worm_retention(adapter, mock_s3_client):
    mock_s3_client.delete_object.side_effect = ClientError(
        {'Error': {'Code': 'InvalidRequest', 'Message': 'Object is WORM protected and cannot be overwritten'}},
        'DeleteObject')
    with pytest.raises(PermissionError):
        adapter.delete_version(ObjectRef('bucket', 'key', 'retained'))
