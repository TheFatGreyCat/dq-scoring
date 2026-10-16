"""Regression tests mapping persisted scoring_policies rows to the domain ScoringPolicy."""

from uuid import uuid4

from dq_scoring.adapters.db.policy_mapping import scoring_policy_from_row


def test_maps_thresholds_and_weights_written_by_the_policy_api() -> None:
    policy_id = uuid4()
    policy = scoring_policy_from_row(
        policy_id=policy_id,
        dimension_weights={"COMPLETENESS": 2.0, "VALIDITY": 1.0},
        publication_threshold=0.5,
        gate_rules={
            "gate_fail_threshold": 10.0,
            "gate_warn_threshold": 20.0,
            "critical_acceptance_threshold": 95.0,
        },
    )
    assert policy.gate_fail_threshold == 10.0
    assert policy.gate_warn_threshold == 20.0
    assert policy.publication_threshold == 0.5
    assert policy.critical_acceptance_threshold == 95.0
    assert policy.dimension_weights == {"COMPLETENESS": 2.0, "VALIDITY": 1.0}
    assert policy.policy_id == policy_id


def test_maps_legacy_warn_min_pass_min_keys() -> None:
    policy = scoring_policy_from_row(
        policy_id=uuid4(),
        dimension_weights=None,
        publication_threshold=0.8,
        gate_rules={"warn_min": 55.0, "pass_min": 75.0},
    )
    assert (policy.gate_fail_threshold, policy.gate_warn_threshold) == (55.0, 75.0)
    assert policy.dimension_weights == {}
