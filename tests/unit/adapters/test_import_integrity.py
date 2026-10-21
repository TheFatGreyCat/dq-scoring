"""Unit tests for dataset import invariants, source freezing, bounds, and worker fencing."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from dq_scoring.adapters.source.tabular_import import TabularImportAdapter
from dq_scoring.adapters.source.tabular_normalization import (
    ImportInspectionException,
    iter_normalized_batches,
)
from dq_scoring.ports.object_store import ObjectMetadata, ObjectRef


class MockObjectStore:
    """Mock object store with copy_object and versioning support for unit testing."""

    def __init__(self) -> None:
        self.files: dict[tuple[str, str], bytes] = {}
        self.etags: dict[tuple[str, str], str] = {}
        self.versions: dict[tuple[str, str], str] = {}
        self.versioning_enabled: bool = True

    def put_bytes(self, bucket: str, key: str, data: bytes, version_id: str = "v-1") -> None:
        self.files[(bucket, key)] = data
        self.etags[(bucket, key)] = f"etag-{len(data)}"
        self.versions[(bucket, key)] = version_id

    def open_stream(self, ref: ObjectRef, *, if_match_etag: str | None = None) -> io.BytesIO:
        data = self.files.get((ref.bucket, ref.key))
        if data is None:
            raise FileNotFoundError(f"Missing {ref.bucket}/{ref.key}")
        return io.BytesIO(data)

    def open_range(self, ref: ObjectRef, offset: int, length: int) -> io.BytesIO:
        with self.open_stream(ref) as stream:
            stream.seek(offset)
            return io.BytesIO(stream.read(length))

    def head(self, ref: ObjectRef) -> ObjectMetadata:
        data = self.files.get((ref.bucket, ref.key))
        if data is None:
            raise FileNotFoundError(f"Missing {ref.bucket}/{ref.key}")
        etag = self.etags.get((ref.bucket, ref.key), "etag-mock")
        ver = self.versions.get((ref.bucket, ref.key), "v-mock")
        return ObjectMetadata(ref=ref, size_bytes=len(data), etag=etag, version_id=ver)

    def copy_object(self, source: ObjectRef, bucket: str, key: str, source_etag: str | None = None) -> ObjectMetadata:
        data = self.files.get((source.bucket, source.key))
        if data is None:
            raise FileNotFoundError(f"Source missing {source.bucket}/{source.key}")
        self.files[(bucket, key)] = data
        self.etags[(bucket, key)] = f"etag-copied-{len(data)}"
        self.versions[(bucket, key)] = "v-copied-1"
        return ObjectMetadata(
            ref=ObjectRef(bucket=bucket, key=key, version_id="v-copied-1"),
            size_bytes=len(data),
            etag=self.etags[(bucket, key)],
            version_id="v-copied-1",
        )

    def create_multipart(self, bucket: str, key: str) -> str:
        return f"mp-{bucket}-{key}"

    def upload_part(self, bucket: str, key: str, multipart_id: str, part_number: int, stream, length: int) -> str:
        chunk = stream.read(length)
        existing = self.files.get((bucket, key), b"")
        self.files[(bucket, key)] = existing + chunk
        etag = f"part-etag-{part_number}"
        self.etags[(bucket, key)] = etag
        return etag

    def complete_multipart(self, bucket: str, key: str, multipart_id: str, parts) -> ObjectMetadata:
        data = self.files.get((bucket, key), b"")
        ver = "v-mp-complete"
        self.versions[(bucket, key)] = ver
        return ObjectMetadata(
            ref=ObjectRef(bucket=bucket, key=key, version_id=ver),
            size_bytes=len(data),
            etag=self.etags.get((bucket, key), "etag-mp"),
            version_id=ver,
        )

    def is_versioning_enabled(self, bucket: str) -> bool:
        return self.versioning_enabled


@pytest.fixture
def mock_store() -> MockObjectStore:
    return MockObjectStore()


@pytest.fixture
def adapter(mock_store: MockObjectStore, tmp_path: Path) -> TabularImportAdapter:
    return TabularImportAdapter(store=mock_store)


# -----------------------------------------------------------------------------
# 1. Source Freeze and Precondition Invariants
# -----------------------------------------------------------------------------

def test_source_freeze_pins_version_and_copies_raw_file(adapter: TabularImportAdapter, mock_store: MockObjectStore):
    csv_bytes = b"id,name,amount\n1,Alice,100\n2,Bob,200\n"
    source = ObjectRef(bucket="staging-bucket", key="tenant/upload/source.csv")
    mock_store.put_bytes("staging-bucket", "tenant/upload/source.csv", csv_bytes, version_id="v-src-1")

    inspection = adapter.inspect_snapshot(source_store=mock_store, storage_mode="OWNED_RAW", 
        source=source,
        destination_bucket="snapshots-bucket",
        destination_prefix="snapshots/tenant/upload/attempt-1",
        file_format="CSV",
    )

    assert inspection.raw_ref.bucket == "snapshots-bucket"
    assert inspection.raw_ref.key == "snapshots/tenant/upload/attempt-1/source.csv"
    assert inspection.raw_ref.version_id == "v-copied-1"
    assert not any(key.endswith("canonical.parquet") for _, key in mock_store.files)
    assert inspection.exact_row_count == 2


def test_object_changed_detected_if_source_modified_concurrently(adapter: TabularImportAdapter, mock_store: MockObjectStore):
    csv_bytes = b"id,val\n1,a\n"
    source = ObjectRef(bucket="staging-bucket", key="source.csv")
    mock_store.put_bytes("staging-bucket", "source.csv", csv_bytes)

    # Patch head to simulate source ETag changing after copy
    original_head = mock_store.head
    head_calls = [0]

    def mutating_head(ref: ObjectRef):
        head_calls[0] += 1
        meta = original_head(ref)
        if head_calls[0] > 1 and ref.key == "source.csv":
            return ObjectMetadata(ref=ref, size_bytes=len(csv_bytes), etag="different-etag")
        return meta

    mock_store.head = mutating_head  # type: ignore

    with pytest.raises(ImportInspectionException) as exc_info:
        adapter.inspect_snapshot(source_store=mock_store, storage_mode="OWNED_RAW", 
            source=source,
            destination_bucket="snapshots-bucket",
            destination_prefix="dest",
            file_format="CSV",
        )
    assert exc_info.value.error_code == "OBJECT_CHANGED"


# -----------------------------------------------------------------------------
# 2. Format Bounds & Structural Checks
# -----------------------------------------------------------------------------

def test_binary_magic_rejection(adapter: TabularImportAdapter, mock_store: MockObjectStore):
    mock_store.put_bytes("b", "test.pdf", b"%PDF-1.4 binary content")
    with pytest.raises(ImportInspectionException) as exc_info:
        adapter.inspect_snapshot(source_store=mock_store, storage_mode="OWNED_RAW", 
            source=ObjectRef("b", "test.pdf"),
            destination_bucket="snap",
            destination_prefix="dest",
            file_format="CSV",
        )
    assert exc_info.value.error_code == "UNSUPPORTED_FORMAT"


def test_parquet_binary_magic_in_csv_rejected(adapter: TabularImportAdapter, mock_store: MockObjectStore):
    mock_store.put_bytes("b", "fake.csv", b"PAR1fake_parquet_bytes")
    with pytest.raises(ImportInspectionException) as exc_info:
        adapter.inspect_snapshot(source_store=mock_store, storage_mode="OWNED_RAW", 
            source=ObjectRef("b", "fake.csv"),
            destination_bucket="snap",
            destination_prefix="dest",
            file_format="CSV",
        )
    assert exc_info.value.error_code == "UNSUPPORTED_FORMAT"


def test_jsonl_duplicate_key_rejection(adapter: TabularImportAdapter, mock_store: MockObjectStore):
    jsonl_bytes = b'{"id": 1, "name": "foo", "id": 2}\n'
    mock_store.put_bytes("b", "test.jsonl", jsonl_bytes)
    with pytest.raises(ImportInspectionException) as exc_info:
        adapter.inspect_snapshot(source_store=mock_store, storage_mode="OWNED_RAW", 
            source=ObjectRef("b", "test.jsonl"),
            destination_bucket="snap",
            destination_prefix="dest",
            file_format="JSONL",
        )
    assert exc_info.value.error_code == "MALFORMED_JSONL"


def test_jsonl_rejects_nan_and_infinity(adapter: TabularImportAdapter, mock_store: MockObjectStore):
    jsonl_bytes = b'{"id": 1, "value": NaN}\n'
    mock_store.put_bytes("b", "test.jsonl", jsonl_bytes)
    with pytest.raises(ImportInspectionException) as exc_info:
        adapter.inspect_snapshot(source_store=mock_store, storage_mode="OWNED_RAW", 
            source=ObjectRef("b", "test.jsonl"),
            destination_bucket="snap",
            destination_prefix="dest",
            file_format="JSONL",
        )
    assert exc_info.value.error_code == "MALFORMED_JSONL"


def test_jsonl_mixed_scalar_types_warning(adapter: TabularImportAdapter, mock_store: MockObjectStore):
    jsonl_bytes = b'{"id": 1, "val": 42}\n{"id": 2, "val": true}\n'
    mock_store.put_bytes("b", "test.jsonl", jsonl_bytes)
    inspection = adapter.inspect_snapshot(source_store=mock_store, storage_mode="OWNED_RAW", 
        source=ObjectRef("b", "test.jsonl"),
        destination_bucket="snap",
        destination_prefix="dest",
        file_format="JSONL",
    )
    assert "MIXED_SCALAR_TYPES" in inspection.warnings


# -----------------------------------------------------------------------------
# 3. Privacy, Masking, and Profiling Stats
# -----------------------------------------------------------------------------

def test_financial_columns_fully_masked_in_preview(adapter: TabularImportAdapter, mock_store: MockObjectStore):
    csv_bytes = b"user_id,bank_account_number,iban,balance\n101,12345678,DE89370400440532013000,500.25\n"
    mock_store.put_bytes("b", "fin.csv", csv_bytes)

    inspection = adapter.inspect_snapshot(source_store=mock_store, storage_mode="OWNED_RAW", 
        source=ObjectRef("b", "fin.csv"),
        destination_bucket="snap",
        destination_prefix="dest",
        file_format="CSV",
    )

    preview_row = inspection.preview_rows[0]
    assert preview_row["bank_account_number"] == "[REDACTED]"
    assert preview_row["iban"] == "[REDACTED]"
    assert preview_row["balance"] == "500.25"


def test_profile_type_hint_leading_zeros_and_timestamp(adapter: TabularImportAdapter, mock_store: MockObjectStore):
    csv_bytes = (
        b"zip_code,event_time\n"
        b"01234,2024/05/01 12:00\n"
        b"09876,2024/05/02 13:00\n"
        b"00123,2024/05/03 14:00\n"
    )
    mock_store.put_bytes("b", "data.csv", csv_bytes)

    inspection = adapter.inspect_snapshot(source_store=mock_store, storage_mode="OWNED_RAW", 
        source=ObjectRef("b", "data.csv"),
        destination_bucket="snap",
        destination_prefix="dest",
        file_format="CSV",
    )

    cols = {c["name"]: c for c in inspection.profile["columns"]}
    # Leading zeros keep STRING hint
    assert cols["zip_code"]["type_hint"] == "STRING"
    # Timestamp format recognized
    assert cols["event_time"]["type_hint"] == "TIMESTAMP"
    assert cols["event_time"]["timestamp_format"] == "yyyy/MM/dd HH:mm"
    assert cols["event_time"]["parse_success_count"] == 3


def test_jsonl_decimal_text_survives_normalization(adapter, mock_store):
    mock_store.put_bytes("staging", "precise.jsonl", b'{"amount":1234567890.1234567890123456789}\n')
    inspection = adapter.inspect_snapshot(source_store=mock_store, storage_mode="OWNED_RAW", source=ObjectRef("staging", "precise.jsonl"), destination_bucket="snapshots", destination_prefix="precise", file_format="JSONL")
    raw = io.BytesIO(mock_store.files[("snapshots", inspection.raw_ref.key)])
    rows = [r for b in iter_normalized_batches(raw, inspection.normalization) for r in b.to_pylist()]
    assert rows == [{"amount": "1234567890.1234567890123456789"}]


def test_csv_unclosed_quote_is_rejected(adapter, mock_store):
    mock_store.put_bytes("staging", "broken.csv", b'id,name\n1,"unclosed\n')
    with pytest.raises(ImportInspectionException) as error:
        adapter.inspect_snapshot(source_store=mock_store, storage_mode="OWNED_RAW", source=ObjectRef("staging", "broken.csv"), destination_bucket="snapshots", destination_prefix="broken", file_format="CSV")
    assert error.value.error_code == "MALFORMED_CSV"


def test_owned_raw_requires_versioned_bucket_even_when_reusing(adapter, mock_store):
    mock_store.put_bytes("snapshots", "snapshots/t/u/source.csv", b"id\n1\n", version_id="v1")
    mock_store.versioning_enabled = False
    with pytest.raises(ImportInspectionException) as error:
        adapter.inspect_snapshot(
            source=ObjectRef("snapshots", "snapshots/t/u/source.csv", "v1"), source_store=mock_store,
            storage_mode="OWNED_RAW", reuse_owned=True, destination_bucket="snapshots",
            destination_prefix="snapshots/t/u", file_format="CSV")
    assert error.value.error_code == "SNAPSHOT_VERSIONING_REQUIRED"
