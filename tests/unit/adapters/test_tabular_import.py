"""Unit tests for TabularImportAdapter: CSV, Parquet, JSONL inspection and read-time normalization (raw-only snapshots)."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from dq_scoring.adapters.source.tabular_import import TabularImportAdapter
from dq_scoring.adapters.source.tabular_normalization import (
    ImportInspectionException,
    iter_normalized_batches,
)
from dq_scoring.ports.object_store import ObjectRef


class InMemoryObjectStore:
    """In-memory mock of IObjectStorePort for fast deterministic unit tests."""

    def __init__(self) -> None:
        self.files: dict[tuple[str, str], bytes] = {}
        self.stream_calls: list[tuple[ObjectRef, str | None]] = []
        self.copies: list[ObjectRef] = []
        self.aborted: list[str] = []

    def put_bytes(self, bucket: str, key: str, data: bytes) -> None:
        self.files[(bucket, key)] = data

    def open_stream(self, ref: ObjectRef, *, if_match_etag: str | None = None) -> io.BytesIO:
        self.stream_calls.append((ref, if_match_etag))
        data = self.files.get((ref.bucket, ref.key))
        if data is None:
            raise FileNotFoundError(f"Missing {ref.bucket}/{ref.key}")
        return io.BytesIO(data)

    def open_range(self, ref: ObjectRef, offset: int, length: int) -> io.BytesIO:
        with self.open_stream(ref) as stream:
            stream.seek(offset)
            return io.BytesIO(stream.read(length))

    def head(self, ref: ObjectRef):
        data = self.files.get((ref.bucket, ref.key))
        if data is None:
            raise FileNotFoundError(f"Missing {ref.bucket}/{ref.key}")
        from dq_scoring.ports.object_store import ObjectMetadata
        return ObjectMetadata(
            ref=ObjectRef(bucket=ref.bucket, key=ref.key, version_id=ref.version_id or "v1"),
            size_bytes=len(data),
            etag="mock-etag",
            version_id=ref.version_id or "v1",
        )

    def create_multipart(self, bucket: str, key: str) -> str:
        return f"mp-{bucket}-{key}"

    def upload_part(self, bucket: str, key: str, multipart_id: str, part_number: int, stream, length: int) -> str:
        chunk = stream.read(length)
        existing = self.files.get((bucket, key), b"")
        self.files[(bucket, key)] = existing + chunk
        return f"etag-{part_number}"

    def complete_multipart(self, bucket: str, key: str, multipart_id: str, parts) -> Any:
        return self.head(ObjectRef(bucket=bucket, key=key, version_id="v1"))

    def copy_object(
        self,
        source: ObjectRef,
        bucket: str,
        key: str,
        source_etag: str | None = None,
    ) -> Any:
        data = self.files.get((source.bucket, source.key))
        if data is None:
            raise FileNotFoundError(f"Missing {source.bucket}/{source.key}")
        if source_etag is not None and source_etag != "mock-etag":
            from dq_scoring.ports.object_store import ObjectChangedError
            raise ObjectChangedError(f"ETag mismatch: {source_etag}")
        self.files[(bucket, key)] = data
        self.copies.append(source)
        return self.head(ObjectRef(bucket=bucket, key=key, version_id="v1"))

    def abort_multipart(self, bucket: str, key: str, multipart_id: str) -> None:
        self.aborted.append(multipart_id)

    def is_versioning_enabled(self, bucket: str) -> bool:
        return True

    def get_bucket_versioning(self, bucket: str) -> dict[str, Any]:
        return {"Status": "Enabled"}

    def put_file(self, bucket: str, key: str, path: Path) -> Any:
        self.files[(bucket, key)] = path.read_bytes()
        return self.head(ObjectRef(bucket=bucket, key=key, version_id="v1"))

def _read_rows(store: InMemoryObjectStore, inspection) -> list[dict[str, Any]]:
    """Replay read-time normalization from the pinned raw object (no canonical copy exists)."""
    raw = io.BytesIO(store.files[(inspection.raw_ref.bucket, inspection.raw_ref.key)])
    return [row for batch in iter_normalized_batches(raw, inspection.normalization) for row in batch.to_pylist()]


@pytest.fixture
def mem_store() -> InMemoryObjectStore:
    return InMemoryObjectStore()


@pytest.fixture
def import_adapter(mem_store: InMemoryObjectStore, tmp_path: Path) -> TabularImportAdapter:
    return TabularImportAdapter(store=mem_store)


# ---------------------------------------------------------------------------
# CSV Tests
# ---------------------------------------------------------------------------


def test_csv_valid_inspection_and_normalization(mem_store: InMemoryObjectStore, import_adapter: TabularImportAdapter) -> None:
    csv_data = (
        b"trip_id,fare,pickup_time\n"
        b"t1,12.50,2026-10-01 10:00:00\n"
        b"t2,-5.00,2026-10-01 11:30:00\n"
        b"t3,,2026-10-01 12:00:00\n"
    )
    mem_store.put_bytes("staging", "tenant1/trips.csv", csv_data)
    source_ref = ObjectRef("staging", "tenant1/trips.csv")

    inspection = import_adapter.inspect_snapshot(source_store=mem_store, storage_mode="OWNED_RAW", 
        source=source_ref,
        destination_bucket="snapshots",
        destination_prefix="snapshots/tenant1/trips/attempt-1",
        file_format="CSV",
    )

    assert inspection.exact_row_count == 3
    assert len(inspection.columns) == 3
    assert [c["name"] for c in inspection.columns] == ["trip_id", "fare", "pickup_time"]
    assert len(inspection.preview_rows) == 3
    assert inspection.preview_rows[0]["trip_id"] == "t1"
    assert inspection.preview_rows[0]["fare"] == "12.50"
    assert inspection.preview_rows[2]["fare"] is None  # empty parsed as null

    # Verify profiling
    fare_profile = next(c for c in inspection.profile["columns"] if c["name"] == "fare")
    assert fare_profile["null_count"] == 1
    assert fare_profile["non_null_count"] == 2
    assert fare_profile["type_hint"] == "DOUBLE"


def test_csv_empty_file_rejected(mem_store: InMemoryObjectStore, import_adapter: TabularImportAdapter) -> None:
    mem_store.put_bytes("staging", "empty.csv", b"")
    with pytest.raises(ImportInspectionException) as exc:
        import_adapter.inspect_snapshot(source_store=mem_store, storage_mode="OWNED_RAW", 
            source=ObjectRef("staging", "empty.csv"),
            destination_bucket="snapshots",
            destination_prefix="dest",
            file_format="CSV",
        )
    assert exc.value.error_code == "EMPTY_DATASET"


def test_csv_header_only_rejected(mem_store: InMemoryObjectStore, import_adapter: TabularImportAdapter) -> None:
    mem_store.put_bytes("staging", "header_only.csv", b"col1,col2\n")
    with pytest.raises(ImportInspectionException) as exc:
        import_adapter.inspect_snapshot(source_store=mem_store, storage_mode="OWNED_RAW", 
            source=ObjectRef("staging", "header_only.csv"),
            destination_bucket="snapshots",
            destination_prefix="dest",
            file_format="CSV",
        )
    assert exc.value.error_code == "EMPTY_DATASET"


def test_csv_duplicate_header_rejected(mem_store: InMemoryObjectStore, import_adapter: TabularImportAdapter) -> None:
    mem_store.put_bytes("staging", "dup.csv", b"Account,Amount,Account\n1,100,2\n")
    with pytest.raises(ImportInspectionException) as exc:
        import_adapter.inspect_snapshot(source_store=mem_store, storage_mode="OWNED_RAW", 
            source=ObjectRef("staging", "dup.csv"),
            destination_bucket="snapshots",
            destination_prefix="dest",
            file_format="CSV",
        )
    assert exc.value.error_code == "DUPLICATE_COLUMN_NAME"


def test_csv_blank_column_header_rejected(mem_store: InMemoryObjectStore, import_adapter: TabularImportAdapter) -> None:
    mem_store.put_bytes("staging", "blank_col.csv", b"Account,,Amount\n1,x,100\n")
    with pytest.raises(ImportInspectionException) as exc:
        import_adapter.inspect_snapshot(source_store=mem_store, storage_mode="OWNED_RAW", 
            source=ObjectRef("staging", "blank_col.csv"),
            destination_bucket="snapshots",
            destination_prefix="dest",
            file_format="CSV",
        )
    assert exc.value.error_code == "EMPTY_COLUMN_NAME"


def test_csv_mismatched_row_field_count_rejected(mem_store: InMemoryObjectStore, import_adapter: TabularImportAdapter) -> None:
    mem_store.put_bytes("staging", "bad_rows.csv", b"c1,c2\nv1,v2\nv1,v2,extra\n")
    with pytest.raises(ImportInspectionException) as exc:
        import_adapter.inspect_snapshot(source_store=mem_store, storage_mode="OWNED_RAW", 
            source=ObjectRef("staging", "bad_rows.csv"),
            destination_bucket="snapshots",
            destination_prefix="dest",
            file_format="CSV",
        )
    assert exc.value.error_code == "MALFORMED_CSV"


def test_csv_binary_magic_disguised_rejected(mem_store: InMemoryObjectStore, import_adapter: TabularImportAdapter) -> None:
    mem_store.put_bytes("staging", "fake_pdf.csv", b"%PDF-1.4\n1 0 obj\n<<>>\n")
    with pytest.raises(ImportInspectionException) as exc:
        import_adapter.inspect_snapshot(source_store=mem_store, storage_mode="OWNED_RAW", 
            source=ObjectRef("staging", "fake_pdf.csv"),
            destination_bucket="snapshots",
            destination_prefix="dest",
            file_format="CSV",
        )
    assert exc.value.error_code == "UNSUPPORTED_FORMAT"


def test_csv_single_column_warning(mem_store: InMemoryObjectStore, import_adapter: TabularImportAdapter) -> None:
    mem_store.put_bytes("staging", "single.csv", b"single_column\nval1\nval2\n")
    inspection = import_adapter.inspect_snapshot(source_store=mem_store, storage_mode="OWNED_RAW", 
        source=ObjectRef("staging", "single.csv"),
        destination_bucket="snapshots",
        destination_prefix="dest",
        file_format="CSV",
    )
    assert "SINGLE_COLUMN_INPUT" in inspection.warnings


# ---------------------------------------------------------------------------
# JSONL Tests
# ---------------------------------------------------------------------------


def test_jsonl_valid_flat_inspection_and_normalization(mem_store: InMemoryObjectStore, import_adapter: TabularImportAdapter) -> None:
    jsonl_data = (
        b'{"id": "row1", "amount": 100.5, "status": "ACTIVE"}\n'
        b'{"id": "row2", "currency": "USD"}\n'
        b'{"id": "row3", "amount": -10.0, "status": "PENDING", "currency": "EUR"}\n'
    )
    mem_store.put_bytes("staging", "data.jsonl", jsonl_data)

    inspection = import_adapter.inspect_snapshot(source_store=mem_store, storage_mode="OWNED_RAW", 
        source=ObjectRef("staging", "data.jsonl"),
        destination_bucket="snapshots",
        destination_prefix="dest",
        file_format="JSONL",
    )

    assert inspection.exact_row_count == 3
    col_names = [c["name"] for c in inspection.columns]
    assert col_names == ["id", "amount", "status", "currency"]
    assert len(inspection.preview_rows) == 3
    assert inspection.preview_rows[1]["amount"] is None  # missing key is null


def test_jsonl_nested_object_supported(mem_store: InMemoryObjectStore, import_adapter: TabularImportAdapter) -> None:
    jsonl_data = (
        b'{"id": "1", "details": {"score": 90, "active": true}}\n'
        b'{"id": "2", "details": null}\n'
    )
    mem_store.put_bytes("staging", "nested_obj.jsonl", jsonl_data)
    inspection = import_adapter.inspect_snapshot(source_store=mem_store, storage_mode="OWNED_RAW", 
        source=ObjectRef("staging", "nested_obj.jsonl"),
        destination_bucket="snapshots",
        destination_prefix="dest",
        file_format="JSONL",
    )
    assert inspection.normalization_version == 2
    details_col = next(c for c in inspection.columns if c["name"] == "details")
    assert details_col["structural_encoding"] == "JSON"
    assert sorted(details_col["logical_types"]) == ["NULL", "OBJECT"]
    read_rows = _read_rows(mem_store, inspection)
    assert read_rows == [
        {"id": "1", "details": '{"active":true,"score":90}'},
        {"id": "2", "details": None},
    ]


def test_jsonl_nested_array_supported(mem_store: InMemoryObjectStore, import_adapter: TabularImportAdapter) -> None:
    jsonl_data = b'{"id": "1", "tags": ["a", "b"]}\n'
    mem_store.put_bytes("staging", "nested_arr.jsonl", jsonl_data)
    inspection = import_adapter.inspect_snapshot(source_store=mem_store, storage_mode="OWNED_RAW", 
        source=ObjectRef("staging", "nested_arr.jsonl"),
        destination_bucket="snapshots",
        destination_prefix="dest",
        file_format="JSONL",
    )
    assert inspection.normalization_version == 2
    tags_col = next(c for c in inspection.columns if c["name"] == "tags")
    assert tags_col["structural_encoding"] == "JSON"
    assert tags_col["logical_types"] == ["ARRAY"]
    read_rows = _read_rows(mem_store, inspection)
    assert read_rows == [{"id": "1", "tags": '["a","b"]'}]

def test_jsonl_duplicate_key_rejected(mem_store: InMemoryObjectStore, import_adapter: TabularImportAdapter) -> None:
    jsonl_data = (
        b'{"id": "1", "id": "2"}\n'
    )
    mem_store.put_bytes("staging", "dup_key.jsonl", jsonl_data)
    with pytest.raises(ImportInspectionException) as exc:
        import_adapter.inspect_snapshot(source_store=mem_store, storage_mode="OWNED_RAW", 
            source=ObjectRef("staging", "dup_key.jsonl"),
            destination_bucket="snapshots",
            destination_prefix="dest",
            file_format="JSONL",
        )
    assert exc.value.error_code == "MALFORMED_JSONL"


# ---------------------------------------------------------------------------
# Parquet Tests
# ---------------------------------------------------------------------------


def test_parquet_valid_scalar_inspection(mem_store: InMemoryObjectStore, import_adapter: TabularImportAdapter) -> None:
    table = pa.Table.from_arrays(
        [
            pa.array(["p1", "p2", "p3"]),
            pa.array([10, 20, None]),
            pa.array([True, False, True]),
        ],
        names=["id", "score", "is_valid"],
    )
    buf = io.BytesIO()
    pq.write_table(table, buf)
    mem_store.put_bytes("staging", "scalar.parquet", buf.getvalue())

    inspection = import_adapter.inspect_snapshot(source_store=mem_store, storage_mode="OWNED_RAW", 
        source=ObjectRef("staging", "scalar.parquet"),
        destination_bucket="snapshots",
        destination_prefix="dest",
        file_format="PARQUET",
    )

    assert inspection.exact_row_count == 3
    assert [c["name"] for c in inspection.columns] == ["id", "score", "is_valid"]
    assert len(inspection.preview_rows) == 3


def test_parquet_nested_struct_supported(mem_store: InMemoryObjectStore, import_adapter: TabularImportAdapter) -> None:
    struct_array = pa.StructArray.from_arrays(
        [pa.array([1, 2])],
        names=["inner"],
    )
    table = pa.Table.from_arrays([struct_array], names=["nested"])
    buf = io.BytesIO()
    pq.write_table(table, buf)
    mem_store.put_bytes("staging", "nested.parquet", buf.getvalue())

    inspection = import_adapter.inspect_snapshot(source_store=mem_store, storage_mode="OWNED_RAW", 
        source=ObjectRef("staging", "nested.parquet"),
        destination_bucket="snapshots",
        destination_prefix="dest",
        file_format="PARQUET",
    )
    assert inspection.normalization_version == 2
    col = inspection.columns[0]
    assert col["name"] == "nested"
    assert col["structural_encoding"] == "JSON"
    read_rows = _read_rows(mem_store, inspection)
    assert read_rows == [{"nested": '{"inner":1}'}, {"nested": '{"inner":2}'}]


def test_nested_preview_redacts_names_before_truncation():
    preview = TabularImportAdapter._build_preview([
        {"payload": '{"person":{"fullName":"Synthetic Private Person","address":"Synthetic Private Street"}}'}
    ])
    assert "Synthetic Private Person" not in preview[0]["payload"]
    assert "Synthetic Private Street" not in preview[0]["payload"]
    assert "REDACTED" in preview[0]["payload"]


def test_parquet_map_inside_struct_preserves_object_semantics(mem_store, import_adapter):
    arrow_type = pa.struct([pa.field("attributes", pa.map_(pa.string(), pa.int64()))])
    table = pa.table({"payload": pa.array([{"attributes": [("a", 1), ("b", 2)]}], type=arrow_type)})
    buf = io.BytesIO()
    pq.write_table(table, buf)
    mem_store.put_bytes("staging", "map.parquet", buf.getvalue())
    inspection = import_adapter.inspect_snapshot(source_store=mem_store, storage_mode="OWNED_RAW", source=ObjectRef("staging", "map.parquet"), destination_bucket="snapshots", destination_prefix="map", file_format="PARQUET")
    rows = _read_rows(mem_store, inspection)
    assert rows == [{"payload": '{"attributes":{"a":1,"b":2}}'}]


def test_mixed_json_column_quotes_literal_strings_and_keeps_decimal(mem_store, import_adapter):
    mem_store.put_bytes("staging", "mixed.jsonl", b'{"payload":{"amount":1234567890.1234567890123456789}}\n{"payload":"{\\"x\\":1}"}\n{"payload":true}\n{"payload":null}\n')
    inspection = import_adapter.inspect_snapshot(source_store=mem_store, storage_mode="OWNED_RAW", source=ObjectRef("staging", "mixed.jsonl"), destination_bucket="snapshots", destination_prefix="mixed", file_format="JSONL")
    rows = _read_rows(mem_store, inspection)
    assert rows == [{"payload": '{"amount":1234567890.1234567890123456789}'}, {"payload": '"{\\"x\\":1}"'}, {"payload": "true"}, {"payload": None}]
    assert inspection.columns[0]["logical_types"] == ["BOOLEAN", "NULL", "OBJECT", "STRING"]
    assert inspection.profile["columns"][0]["type_hint"] == "JSON"


def test_import_sensitive_match_late_in_file_masks_early_preview_and_profile(
    mem_store: InMemoryObjectStore, import_adapter: TabularImportAdapter
) -> None:
    # 60 rows: rows 1-59 have regular text in 'contact', row 60 has an email
    lines = [b"id,contact\n"]
    for i in range(1, 60):
        lines.append(f"{i},regular_customer_text_{i}\n".encode())
    lines.append(b"60,real_user@example.com\n")
    mem_store.put_bytes("staging", "late_sensitive.csv", b"".join(lines))

    inspection = import_adapter.inspect_snapshot(source_store=mem_store, storage_mode="OWNED_RAW", 
        source=ObjectRef("staging", "late_sensitive.csv"),
        destination_bucket="snapshots",
        destination_prefix="late_sens",
        file_format="CSV",
    )
    assert inspection.sensitive_scan["status"] == "COMPLETE"
    assert "contact" in inspection.sensitive_scan["sensitive_columns"]
    # Row 1 must be masked even though its value was regular text!
    assert inspection.preview_rows[0]["contact"] == "[REDACTED]"
    # Profile for contact must not leak min/max values
    contact_prof = next(c for c in inspection.profile["columns"] if c["name"] == "contact")
    assert contact_prof.get("min") is None
    assert contact_prof.get("max") is None


def test_import_respects_privacy_columns_policy(
    mem_store: InMemoryObjectStore, import_adapter: TabularImportAdapter
) -> None:
    mem_store.put_bytes("staging", "policy.csv", b"id,custom_note\n1,some notes\n2,more notes\n")
    inspection = import_adapter.inspect_snapshot(source_store=mem_store, storage_mode="OWNED_RAW", 
        source=ObjectRef("staging", "policy.csv"),
        destination_bucket="snapshots",
        destination_prefix="policy",
        file_format="CSV",
        privacy_columns=("custom_note",),
    )
    assert "custom_note" in inspection.sensitive_scan["sensitive_columns"]
    assert inspection.preview_rows[0]["custom_note"] == "[REDACTED]"


def test_nested_leaf_sensitive_masks_entire_container_in_preview(
    mem_store: InMemoryObjectStore, import_adapter: TabularImportAdapter
) -> None:
    jsonl_data = (
        b'{"id": "1", "data": {"user": {"email": "secret@test.com"}}}\n'
        b'{"id": "2", "data": {"user": {"email": null}}}\n'
    )
    mem_store.put_bytes("staging", "nested_sens.jsonl", jsonl_data)
    inspection = import_adapter.inspect_snapshot(source_store=mem_store, storage_mode="OWNED_RAW", 
        source=ObjectRef("staging", "nested_sens.jsonl"),
        destination_bucket="snapshots",
        destination_prefix="nested_sens",
        file_format="JSONL",
    )
    assert "data" in inspection.sensitive_scan["sensitive_columns"]
    # Entire container must be masked to avoid leak via parent JSON
    assert inspection.preview_rows[0]["data"] == "[REDACTED]"


@pytest.mark.parametrize(('data', 'mixed'), [
    (b'{"a":1}\n{"b":2}\n', False),
    (b'{"a":1}\n{"a":null,"b":2}\n', True),
])
def test_jsonl_absent_keys_do_not_count_as_observed_null(mem_store, import_adapter, data, mixed):
    mem_store.put_bytes('staging', 'sparse.jsonl', data)
    inspection = import_adapter.inspect_snapshot(source_store=mem_store, storage_mode="OWNED_RAW", source=ObjectRef('staging', 'sparse.jsonl'),
        destination_bucket='snapshots', destination_prefix='sparse', file_format='JSONL')
    assert ('MIXED_SCALAR_TYPES' in inspection.warnings) is mixed


# ---------------------------------------------------------------------------
# Raw-only snapshot contract
# ---------------------------------------------------------------------------


def _kwargs(**extra: Any) -> dict[str, Any]:
    return {"destination_bucket": "snapshots", "destination_prefix": "snapshots/t/u", "file_format": "CSV", **extra}


def test_inspection_has_no_canonical_artifacts(mem_store, import_adapter):
    mem_store.put_bytes("staging", "a.csv", b"id\n1\n")
    inspection = import_adapter.inspect_snapshot(
        source=ObjectRef("staging", "a.csv"), source_store=mem_store, storage_mode="OWNED_RAW", **_kwargs())
    assert inspection.storage_mode == "OWNED_RAW"
    assert inspection.normalization.format == "CSV"
    assert inspection.normalization_version == inspection.normalization.version
    assert inspection.raw_ref.key == "snapshots/t/u/source.csv"
    assert not any(key.endswith("canonical.parquet") for _, key in mem_store.files)


def test_reuse_owned_pins_existing_raw_without_copy(mem_store, import_adapter):
    mem_store.put_bytes("snapshots", "snapshots/t/u/source.csv", b"id\n1\n")
    inspection = import_adapter.inspect_snapshot(
        source=ObjectRef("snapshots", "snapshots/t/u/source.csv", "v9"), source_store=mem_store,
        storage_mode="OWNED_RAW", reuse_owned=True, **_kwargs())
    assert mem_store.copies == []
    assert inspection.raw_ref == ObjectRef("snapshots", "snapshots/t/u/source.csv", "v9")
    assert inspection.exact_row_count == 1


def test_external_version_reads_pinned_source_and_never_writes(mem_store, import_adapter):
    external = InMemoryObjectStore()
    external.put_bytes("shared", "t/a.csv", b"id,v\n1,x\n2,y\n")
    inspection = import_adapter.inspect_snapshot(
        source=ObjectRef("shared", "t/a.csv", "ext-v1"), source_store=external, storage_mode="EXTERNAL_VERSION",
        source_id="shared", **_kwargs())
    assert inspection.raw_ref == ObjectRef("shared", "t/a.csv", "ext-v1")
    assert inspection.exact_row_count == 2
    assert mem_store.files == {} and mem_store.copies == []


def test_external_requires_pinned_version(mem_store, import_adapter):
    external = InMemoryObjectStore()
    external.put_bytes("shared", "a.csv", b"id\n1\n")
    with pytest.raises(ImportInspectionException) as exc:
        import_adapter.inspect_snapshot(
            source=ObjectRef("shared", "a.csv"), source_store=external, storage_mode="EXTERNAL_VERSION",
            source_id="shared", **_kwargs())
    assert exc.value.error_code == "STORAGE_VIOLATION"


def test_shared_source_never_uses_owned_client(mem_store, import_adapter):
    mem_store.put_bytes("shared", "a.csv", b"id\n1\n")
    with pytest.raises(ImportInspectionException) as exc:
        import_adapter.inspect_snapshot(
            source=ObjectRef("shared", "a.csv"), source_store=mem_store, storage_mode="OWNED_RAW",
            source_id="shared", **_kwargs())
    assert exc.value.error_code == "STORAGE_VIOLATION"
    assert mem_store.copies == []


def test_shared_unversioned_fallback_streams_with_if_match_through_owned_multipart(mem_store, import_adapter):
    shared = InMemoryObjectStore()
    shared.put_bytes("shared", "t/a.csv", b"id,v\n1,x\n")
    inspection = import_adapter.inspect_snapshot(
        source=ObjectRef("shared", "t/a.csv"), source_store=shared, storage_mode="OWNED_RAW",
        source_id="shared", **_kwargs())
    assert (ObjectRef("shared", "t/a.csv"), "mock-etag") in shared.stream_calls
    assert shared.copies == [] and mem_store.copies == []
    assert mem_store.files[("snapshots", "snapshots/t/u/source.csv")] == b"id,v\n1,x\n"
    assert inspection.raw_ref.bucket == "snapshots"


def test_multipart_aborted_when_streaming_fails(mem_store, import_adapter):
    shared = InMemoryObjectStore()
    shared.put_bytes("shared", "a.csv", b"id\n1\n")

    def broken(*args, **kwargs):
        raise OSError("upload failed")

    mem_store.upload_part = broken  # type: ignore[method-assign]
    with pytest.raises(OSError, match="upload failed"):
        import_adapter.inspect_snapshot(
            source=ObjectRef("shared", "a.csv"), source_store=shared, storage_mode="OWNED_RAW",
            source_id="shared", **_kwargs())
    assert mem_store.aborted == ["mp-snapshots-snapshots/t/u/source.csv"]


def test_multipart_abort_failure_does_not_mask_original_error(mem_store, import_adapter):
    shared = InMemoryObjectStore()
    shared.put_bytes("shared", "a.csv", b"id\n1\n")

    def broken(*args, **kwargs):
        raise OSError("upload failed")

    def abort_broken(*args, **kwargs):
        raise RuntimeError("abort failed")

    mem_store.upload_part = broken  # type: ignore[method-assign]
    mem_store.abort_multipart = abort_broken  # type: ignore[method-assign]
    with pytest.raises(OSError, match="upload failed"):
        import_adapter.inspect_snapshot(
            source=ObjectRef("shared", "a.csv"), source_store=shared, storage_mode="OWNED_RAW",
            source_id="shared", **_kwargs())


def test_rejection_after_freeze_exposes_frozen_raw_ref(mem_store, import_adapter):
    mem_store.put_bytes("staging", "dup.csv", b"a,a\n1,2\n")
    with pytest.raises(ImportInspectionException) as exc:
        import_adapter.inspect_snapshot(
            source=ObjectRef("staging", "dup.csv"), source_store=mem_store, storage_mode="OWNED_RAW", **_kwargs())
    assert exc.value.error_code == "DUPLICATE_COLUMN_NAME"
    assert exc.value.raw_ref == ObjectRef("snapshots", "snapshots/t/u/source.csv", "v1")


def test_parquet_inspected_through_pinned_reader_and_replays_values(mem_store, import_adapter):
    sink = io.BytesIO()
    pq.write_table(pa.table({"id": [1, 2], "name": ["a", None]}), sink)
    mem_store.put_bytes("staging", "p.parquet", sink.getvalue())
    inspection = import_adapter.inspect_snapshot(
        source=ObjectRef("staging", "p.parquet"), source_store=mem_store, storage_mode="OWNED_RAW",
        **_kwargs(file_format="PARQUET"))
    assert inspection.raw_size_bytes == len(sink.getvalue())
    assert _read_rows(mem_store, inspection) == [{"id": "1", "name": "a"}, {"id": "2", "name": None}]


def test_raw_sha256_covers_full_object(mem_store, import_adapter):
    import hashlib
    data = b"id\n" + b"x\n" * 700_000
    mem_store.put_bytes("staging", "big.csv", data)
    inspection = import_adapter.inspect_snapshot(
        source=ObjectRef("staging", "big.csv"), source_store=mem_store, storage_mode="OWNED_RAW", **_kwargs())
    assert inspection.raw_sha256 == hashlib.sha256(data).hexdigest()
    assert inspection.exact_row_count == 700_000
    assert len(inspection.profile["columns"]) == 1


def test_source_changed_before_complete_aborts_multipart(mem_store, import_adapter):
    shared = InMemoryObjectStore()
    shared.put_bytes("shared", "a.csv", b"id\n1\n")
    heads = [0]
    original = shared.head

    def mutating(ref):
        heads[0] += 1
        meta = original(ref)
        return meta if heads[0] == 1 else type(meta)(ref=ref, size_bytes=meta.size_bytes, etag="changed")

    shared.head = mutating  # type: ignore[method-assign]
    completed: list[str] = []
    mem_store.complete_multipart = lambda *a, **k: completed.append("x")  # type: ignore[method-assign]
    with pytest.raises(ImportInspectionException) as exc:
        import_adapter.inspect_snapshot(
            source=ObjectRef("shared", "a.csv"), source_store=shared, storage_mode="OWNED_RAW",
            source_id="shared", **_kwargs())
    assert exc.value.error_code == "OBJECT_CHANGED"
    assert completed == [] and mem_store.aborted
