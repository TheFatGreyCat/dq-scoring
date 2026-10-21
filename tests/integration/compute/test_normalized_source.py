"""Spark reads pinned v2 raw objects through the dq_snapshot DataSource (synthetic MinIO data only)."""
import hashlib
import io
import json
from dataclasses import asdict
from datetime import UTC, datetime
from uuid import uuid4

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from dq_scoring.adapters.compute.normalized_source import (
    ERROR_PREFIX,
    snapshot_options,
    snapshot_run_error,
)
from dq_scoring.adapters.compute.spark_compute import PySparkComputeAdapter
from dq_scoring.adapters.source.tabular_normalization import inspect_schema
from dq_scoring.adapters.storage.s3_object_store import S3ObjectStoreAdapter
from dq_scoring.adapters.storage.s3_settings import get_s3_settings
from dq_scoring.core.entities import DatasetSnapshot, QualityRule
from dq_scoring.core.exceptions import RunAbortedError

CSV_A = b'id,amount,note\n1,5,"line one\nline two"\n2,50,x\n3,,y\n'
CSV_B = b"id,amount,note\n9,1,changed\n"
JSONL_A = (b'{"id":"1","amount":5,"note":"a"}\n{"id":"2","amount":50,"note":"b"}\n'
           b'{"id":"3","amount":null,"note":"c"}\n')
JSONL_B = b'{"id":"9","amount":1,"note":"changed"}\n'


def parquet_bytes(amounts):
    sink = io.BytesIO()
    table = pa.table({"id": ["1", "2", "3"], "amount": amounts, "note": ["a", "b", "c"]})
    pq.write_table(table, sink, row_group_size=1)
    return sink.getvalue()


def publish(data, fmt, replacement):
    """Upload `data`, overwrite the same key with `replacement`; return a snapshot pinned to `data`."""
    settings = get_s3_settings()
    store = S3ObjectStoreAdapter(settings)
    tenant = uuid4()
    key = f"snapshots/{tenant}/{uuid4()}/source.{fmt.lower()}"
    client = store._client
    version = client.put_object(Bucket=settings.bucket_snapshots, Key=key, Body=data)["VersionId"]
    client.put_object(Bucket=settings.bucket_snapshots, Key=key, Body=replacement)
    spec = inspect_schema(io.BytesIO(data), file_format=fmt, column_names_mapping=None)
    descriptor = {
        "descriptor_version": 2, "storage_mode": "OWNED_RAW", "bucket": settings.bucket_snapshots, "key": key,
        "version_id": version, "content_sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data),
        "format": fmt, "normalization_version": spec.version,
        "normalization": {**asdict(spec), "columns": list(spec.columns)},
    }
    return DatasetSnapshot(
        snapshot_id=uuid4(), tenant_id=tenant, asset_id=uuid4(), source_kind="OBJECT_FILE",
        source_descriptor=descriptor, schema_definition={"columns": list(spec.columns)},
        total_rows=3, total_columns=3, captured_at=datetime.now(UTC),
    )


def rule(kind, **parameters):
    return QualityRule(rule_id=uuid4(), rule_code=f"SYNTHETIC_{kind}", dimension="VALIDITY",
                       rule_type=kind, parameters=parameters)


CASES = [
    pytest.param(CSV_A, "CSV", CSV_B, id="csv-multiline"),
    pytest.param(JSONL_A, "JSONL", JSONL_B, id="jsonl"),
    pytest.param(parquet_bytes([5, 50, None]), "PARQUET", parquet_bytes([1, 1, 1]), id="parquet-rowgroups"),
]


@pytest.mark.parametrize(("data", "fmt", "replacement"), CASES)
def test_historical_version_counts_ignore_overwrite(data, fmt, replacement):
    snapshot = publish(data, fmt, replacement)
    compute = PySparkComputeAdapter()
    try:
        non_null, ranged = compute.execute_rules(snapshot, [
            rule("NON_NULL", column="amount"), rule("DOMAIN_RANGE", column="amount", min="0", max="10"),
        ])
        assert (non_null.counts.passed, non_null.counts.missing) == (2, 1)
        assert (ranged.counts.passed, ranged.counts.failed, ranged.counts.missing) == (1, 1, 1)
        df = compute._load_df(snapshot)
        assert df.columns == ["id", "amount", "note"]
        assert {f.dataType.simpleString() for f in df.schema.fields} == {"string"}
        if fmt == "PARQUET":
            assert df.rdd.getNumPartitions() == 3
        if fmt == "CSV":
            assert "line one\nline two" in {row["note"] for row in df.collect()}
    finally:
        compute.release_snapshot(snapshot)


def test_v2_verify_hashes_every_call_and_detects_pinned_mismatch():
    snapshot = publish(CSV_A, "CSV", CSV_B)
    compute = PySparkComputeAdapter()
    compute.verify_snapshot(snapshot)
    assert not compute._verified_snapshots
    bad = {**snapshot.source_descriptor, "content_sha256": "f" * 64}
    with pytest.raises(RunAbortedError, match="OBJECT_CHANGED"):
        compute.verify_snapshot(snapshot.model_copy(update={"source_descriptor": bad}))


def test_options_are_metadata_only_and_strict():
    snapshot = publish(CSV_A, "CSV", CSV_B)
    text = snapshot_options(snapshot.tenant_id, snapshot.source_descriptor)
    assert set(json.loads(text)) == {"tenant_id", "descriptor"}
    secret = get_s3_settings().secret_access_key.get_secret_value()
    assert secret not in text
    polluted = {**snapshot.source_descriptor, "secret_access_key": "synthetic"}
    with pytest.raises(Exception, match="SNAPSHOT_REIMPORT_REQUIRED"):
        snapshot_options(snapshot.tenant_id, polluted)


def test_task_failure_maps_only_allowlisted_fixed_code():
    wrapped = RuntimeError(f"PythonException: {ERROR_PREFIX}OBJECT_CHANGED /tenant/path secret")
    mapped = snapshot_run_error(wrapped)
    assert str(mapped) == "OBJECT_CHANGED: Snapshot source cannot be read."
    assert snapshot_run_error(RuntimeError(f"{ERROR_PREFIX}ANYTHING_ELSE")) is None
    assert snapshot_run_error(RuntimeError("unrelated")) is None
