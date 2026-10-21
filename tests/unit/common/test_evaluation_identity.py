"""Evaluation identity: what changes the result changes the fingerprint; volatile ids and ordering do not."""
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from dq_scoring.common import evaluation_identity as identity
from dq_scoring.core.entities import DatasetSnapshot, QualityRule, RunSpec
from dq_scoring.core.models import ScoringPolicy


def make_spec(**changes) -> RunSpec:
    tenant, ruleset, policy = uuid4(), uuid4(), uuid4()
    snapshot = DatasetSnapshot(
        snapshot_id=uuid4(), tenant_id=tenant, asset_id=uuid4(), source_kind="OBJECT_FILE",
        source_descriptor={"descriptor_version": 2}, schema_definition={"columns": ["a", "b"]},
        total_rows=3, total_columns=2, captured_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    rules = [QualityRule(rule_id=uuid4(), rule_code=f"R{i}", dimension="completeness", rule_type="non_null",
                         parameters={"column": "a"}) for i in range(2)]
    values = {'run_id': uuid4(), 'tenant_id': tenant, 'snapshot': snapshot, 'rules': rules,
              'policy': ScoringPolicy(dimension_weights={'completeness': 1.0}), 'ruleset_id': ruleset,
              'policy_id': policy, 'created_by': uuid4(), 'profile_id': uuid4(), 'profile_fingerprint': 'a' * 64,
              'outlier_columns': ['a', 'b']}
    values.update(changes)
    return RunSpec(**values)


def test_volatile_ids_timestamps_and_rule_order_do_not_change_fingerprint():
    spec = make_spec()
    same = spec.model_copy(update={
        "run_id": uuid4(), "created_by": uuid4(), "profile_id": uuid4(), "rules": list(reversed(spec.rules)),
        "snapshot": spec.snapshot.model_copy(update={"captured_at": spec.snapshot.captured_at + timedelta(days=1)}),
    })
    assert identity.evaluation_fingerprint(same, profile_fingerprint=same.profile_fingerprint) == identity.evaluation_fingerprint(spec, profile_fingerprint=spec.profile_fingerprint)


@pytest.mark.parametrize("change", ["outlier_order", "profile", "rule", "policy_id", "snapshot_spec", "ruleset"])
def test_result_determining_inputs_change_fingerprint(change):
    spec = make_spec()
    changed = {
        "outlier_order": {"outlier_columns": ["b", "a"]},
        "profile": {"profile_fingerprint": "b" * 64},
        "rule": {"rules": [spec.rules[0].model_copy(update={"parameters": {"column": "b"}}), spec.rules[1]]},
        "policy_id": {"policy_id": uuid4()},
        "snapshot_spec": {"snapshot": spec.snapshot.model_copy(update={"source_descriptor": {"descriptor_version": 2, "x": 1}})},
        "ruleset": {"ruleset_id": uuid4()},
    }[change]
    modified = spec.model_copy(update=changed)
    assert identity.evaluation_fingerprint(modified, profile_fingerprint=modified.profile_fingerprint) != identity.evaluation_fingerprint(spec, profile_fingerprint=spec.profile_fingerprint)


def test_evaluator_version_is_part_of_identity(monkeypatch):
    spec = make_spec()
    before = identity.evaluation_fingerprint(spec, profile_fingerprint=spec.profile_fingerprint)
    monkeypatch.setattr(identity, "EVALUATOR_VERSION", "raw-reader-v2")
    assert identity.evaluation_fingerprint(spec, profile_fingerprint=spec.profile_fingerprint) != before


def test_standard_and_spark_k3s_are_one_execution_profile():
    spec = make_spec(execution_profile="standard")
    assert identity.evaluation_fingerprint(spec, profile_fingerprint=spec.profile_fingerprint) == identity.evaluation_fingerprint(
        spec.model_copy(update={'execution_profile': 'SPARK_K3S'}), profile_fingerprint=spec.profile_fingerprint)


def test_request_identity_ignores_run_and_profile_but_not_payload():
    spec = make_spec()
    saved = {**spec.model_dump(mode="json"), "run_id": str(uuid4()), "profile_id": str(uuid4())}
    assert identity.request_identity_matches(saved, spec)
    assert identity.request_identity_matches({**saved, "execution_profile": "SPARK_K3S"}, spec)
    for key, value in (("outlier_columns", ["b", "a"]), ("policy_id", str(uuid4())), ("ruleset_id", str(uuid4()))):
        assert not identity.request_identity_matches({**saved, key: value}, spec)
    assert not identity.request_identity_matches({k: v for k, v in saved.items() if k != "outlier_columns"}, spec)
    assert not identity.request_identity_matches({k: v for k, v in saved.items() if k != 'execution_profile'}, spec)


def test_legacy_row_without_run_spec_matches_only_readable_scalar_fields():
    spec = make_spec()

    def row(**changes):
        base = {'snapshot_id': spec.snapshot.snapshot_id, 'ruleset_id': spec.ruleset_id, 'policy_id': spec.policy_id,
                'execution_profile': 'SPARK_K3S', 'outlier_config': {'outlier_columns': ['a', 'b']}, 'requested': spec}
        base.update(changes)
        return identity.saved_request_matches(**base)

    assert row()
    assert not row(outlier_config={})  # outlier_columns unreadable: never guessed
    assert not row(outlier_config={"outlier_columns": ["b", "a"]})
    assert not row(snapshot_id=uuid4())
    assert not row(execution_profile=None)
