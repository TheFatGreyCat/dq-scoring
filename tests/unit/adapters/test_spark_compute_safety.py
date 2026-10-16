"""Regression tests: no SQL text built from user input, rule-level fault containment, minimal evidence."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from dq_scoring.adapters.compute.spark_compute import PySparkComputeAdapter
from dq_scoring.core.entities import DatasetSnapshot, QualityRule
from dq_scoring.core.exceptions import RunAbortedError
from dq_scoring.core.models import MeasurementStatus

CSV = (
    "id,ts,start_ts,amount,email,odd`name\n"
    "1,2023-01-01T10:00:00,2023-01-01T09:00:00,10,a@example.com,x\n"
    "2,2023-01-02T10:00:00,2023-01-02T11:00:00,abc,b@example.com,\n"
    "3,2023-01-03T10:00:00,2023-01-03T09:00:00,30,c@example.com,y\n"
)


@pytest.fixture(scope="module")
def spark_adapter() -> PySparkComputeAdapter:
    return PySparkComputeAdapter()


@pytest.fixture
def snapshot(tmp_path: Path) -> DatasetSnapshot:
    from tests.support.object_snapshots import create_test_snapshot
    path = tmp_path / "safety.csv"
    path.write_text(CSV, encoding="utf-8")
    return create_test_snapshot(path)

def _rule(rule_type: str, **params: object) -> QualityRule:
    return QualityRule(rule_id=uuid4(), rule_code=f"R_{rule_type}", dimension="VALIDITY", rule_type=rule_type, parameters=params)


def _run(adapter: PySparkComputeAdapter, snapshot: DatasetSnapshot, *rules: QualityRule):
    outputs = adapter.execute_rules(snapshot, list(rules))
    return {o.rule_id: o for o in outputs}


def test_timestamp_format_with_quoted_literal_is_not_spliced_into_sql(spark_adapter, snapshot) -> None:
    """A legal Spark pattern containing quotes must parse, not break (or alter) a SQL string."""
    rule = _rule("TYPE_PARSE", column="ts", data_type="TIMESTAMP", format="yyyy-MM-dd'T'HH:mm:ss")
    out = _run(spark_adapter, snapshot, rule)[rule.rule_id]
    assert out.status == MeasurementStatus.MEASURED
    assert out.counts.passed == 3


def test_injection_payload_in_format_cannot_pass_rows(spark_adapter, snapshot) -> None:
    rule = _rule("TYPE_PARSE", column="amount", data_type="TIMESTAMP", format="yyyy') IS NULL OR TRUE OR ('")
    out = _run(spark_adapter, snapshot, rule)[rule.rule_id]
    assert out.counts.passed == 0


def test_column_name_with_backtick_is_quoted_safely(spark_adapter, snapshot) -> None:
    rule = _rule("NON_NULL", column="odd`name")
    out = _run(spark_adapter, snapshot, rule)[rule.rule_id]
    assert out.status == MeasurementStatus.MEASURED
    assert (out.counts.passed, out.counts.missing) == (2, 1)


def test_unknown_cross_field_operator_fails_only_that_rule(spark_adapter, snapshot) -> None:
    bad = _rule("CROSS_FIELD", column="ts", comparison_column="start_ts", operator="=~", data_type="TIMESTAMP", format="yyyy-MM-dd'T'HH:mm:ss")
    good = _rule("NON_NULL", column="id")
    outs = _run(spark_adapter, snapshot, bad, good)
    assert outs[bad.rule_id].status == MeasurementStatus.FAILED_TO_MEASURE
    assert outs[good.rule_id].status == MeasurementStatus.MEASURED


def test_missing_comparison_column_fails_only_that_rule(spark_adapter, snapshot) -> None:
    bad = _rule("CROSS_FIELD", column="ts", comparison_column="no_such_column", operator=">=")
    good = _rule("NON_NULL", column="id")
    outs = _run(spark_adapter, snapshot, bad, good)
    assert outs[bad.rule_id].status == MeasurementStatus.FAILED_TO_MEASURE
    assert outs[good.rule_id].status == MeasurementStatus.MEASURED


def test_cross_field_timestamp_comparison(spark_adapter, snapshot) -> None:
    rule = _rule("CROSS_FIELD", column="ts", comparison_column="start_ts", operator=">=", data_type="TIMESTAMP", format="yyyy-MM-dd'T'HH:mm:ss")
    out = _run(spark_adapter, snapshot, rule)[rule.rule_id]
    assert (out.counts.passed, out.counts.failed) == (2, 1)


def test_evidence_samples_contain_only_referenced_columns(spark_adapter, snapshot) -> None:
    """Data minimisation: unrelated columns (e.g. email) never enter evidence."""
    rule = _rule("TYPE_PARSE", column="amount", data_type="DOUBLE")
    out = _run(spark_adapter, snapshot, rule)[rule.rule_id]
    assert out.counts.miscast == 1
    assert out.evidence_samples == [{"amount": "[REDACTED]"}]


def test_outlier_detection_quotes_column_name(spark_adapter, snapshot) -> None:
    out = spark_adapter.detect_outliers(snapshot, "odd`name")
    assert out.total_evaluated == 0


# Handled by test_reject_tampered_content_hash
def test_reject_legacy_local_file_snapshot(spark_adapter) -> None:
    legacy_snap = DatasetSnapshot(
        snapshot_id=uuid4(),
        tenant_id=uuid4(),
        asset_id=uuid4(),
        source_kind="LOCAL_FILE",
        source_descriptor={"path": "/data/test.csv"},
        schema_definition={},
        total_rows=10,
        total_columns=2,
        captured_at=datetime.now(UTC),
    )
    with pytest.raises(RunAbortedError, match="LEGACY_SOURCE_UNSUPPORTED"):
        spark_adapter.verify_snapshot(legacy_snap)


def test_reject_cross_tenant_snapshot_key(spark_adapter, snapshot) -> None:
    other_tenant_id = uuid4()
    tampered_snap = DatasetSnapshot(
        snapshot_id=snapshot.snapshot_id,
        tenant_id=other_tenant_id,
        asset_id=snapshot.asset_id,
        source_kind=snapshot.source_kind,
        source_descriptor=snapshot.source_descriptor,
        schema_definition=snapshot.schema_definition,
        total_rows=snapshot.total_rows,
        total_columns=snapshot.total_columns,
        captured_at=snapshot.captured_at,
    )
    with pytest.raises(RunAbortedError, match="TENANT_ISOLATION_VIOLATION"):
        spark_adapter.verify_snapshot(tampered_snap)


def test_reject_tampered_content_hash(spark_adapter, snapshot) -> None:
    desc = dict(snapshot.source_descriptor)
    canonical = dict(desc["canonical"])
    canonical["content_sha256"] = "1" * 64
    desc["canonical"] = canonical
    tampered_snap = DatasetSnapshot(
        snapshot_id=uuid4(),
        tenant_id=snapshot.tenant_id,
        asset_id=snapshot.asset_id,
        source_kind=snapshot.source_kind,
        source_descriptor=desc,
        schema_definition=snapshot.schema_definition,
        total_rows=snapshot.total_rows,
        total_columns=snapshot.total_columns,
        captured_at=snapshot.captured_at,
    )
    with pytest.raises(RunAbortedError, match="OBJECT_CHANGED"):
        spark_adapter.verify_snapshot(tampered_snap)
