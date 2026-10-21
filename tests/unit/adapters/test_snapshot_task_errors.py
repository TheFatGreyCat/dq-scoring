"""Snapshot read failures must fail measurement, including evidence and FULL profiles."""
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from dq_scoring.adapters.compute.spark_compute import PySparkComputeAdapter
from dq_scoring.core.entities import QualityRule
from dq_scoring.core.exceptions import RunAbortedError


def test_full_profile_maps_task_missing_version(monkeypatch):
    adapter = object.__new__(PySparkComputeAdapter)
    monkeypatch.setattr(adapter, '_load_df', lambda snapshot: (_ for _ in ()).throw(
        RuntimeError('DQ_SNAPSHOT_ERROR:RESOURCE_NOT_FOUND')))
    with pytest.raises(RunAbortedError, match='^STORAGE_UNAVAILABLE:'):
        adapter.profile_snapshot(SimpleNamespace(), profile_id=uuid4(), fingerprint='a' * 64)


def test_evidence_read_storage_failure_cannot_become_empty_evidence(monkeypatch):
    import dq_scoring.adapters.compute.spark_compute as module
    rule = QualityRule(rule_id=uuid4(), rule_code='SYN_RANGE', dimension='VALIDITY',
                       rule_type='DOMAIN_RANGE', parameters={'column': 'amount', 'min': 0})
    expr = MagicMock()
    compiled = SimpleNamespace(rule_id=rule.rule_id, referenced_columns=['amount'], target_column='amount',
        is_uniqueness=False, missing_expr=expr, failed_expr=expr, miscast_expr=expr, scope_expr=None)
    monkeypatch.setattr(module, 'compile_rule', lambda _: compiled)
    monkeypatch.setattr(module, 'quoted_col', lambda _: expr)
    monkeypatch.setattr(module, 'F', MagicMock())
    df = MagicMock()
    prefix = f'r_{rule.rule_id.hex}'
    df.select.return_value.collect.return_value = [{f'{prefix}_na': 0, f'{prefix}_passed': 0,
        f'{prefix}_failed': 1, f'{prefix}_missing': 0, f'{prefix}_miscast': 0}]
    df.filter.return_value.select.return_value.limit.return_value.collect.side_effect = RuntimeError('DQ_SNAPSHOT_ERROR:OBJECT_CHANGED')
    df.columns = ['amount']
    adapter = object.__new__(PySparkComputeAdapter)
    monkeypatch.setattr(adapter, '_load_df', lambda _: df)
    snapshot = SimpleNamespace(total_rows=1, schema_definition={'columns': [{'name': 'amount'}]})
    with pytest.raises(RunAbortedError, match='^OBJECT_CHANGED:'):
        adapter.execute_rules(snapshot, [rule])
