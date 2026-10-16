"""Regression tests for CreatePolicyRequest validation."""

import pytest
from pydantic import ValidationError

from dq_scoring.presentation.api.schemas.policy_schemas import CreatePolicyRequest
from dq_scoring.presentation.api.schemas.ruleset_schemas import CreateQualityRuleInput


def test_dimension_weight_keys_are_normalized_to_canonical_dimensions() -> None:
    req = CreatePolicyRequest(name="p", dimension_weights={"Completeness": 2.0, "validity": 1.0})
    assert req.dimension_weights == {"COMPLETENESS": 2.0, "VALIDITY": 1.0}


@pytest.mark.parametrize(
    "weights",
    [{"FRESHNESS": 1.0}, {"COMPLETENESS": -1.0}],
)
def test_invalid_dimension_weights_are_rejected(weights: dict[str, float]) -> None:
    with pytest.raises(ValidationError):
        CreatePolicyRequest(name="p", dimension_weights=weights)


def test_fail_threshold_above_warn_threshold_is_rejected() -> None:
    with pytest.raises(ValidationError):
        CreatePolicyRequest(name="p", gate_fail_threshold=90.0, gate_warn_threshold=80.0)


def test_negative_rule_contribution_weight_is_rejected() -> None:
    with pytest.raises(ValidationError):
        CreateQualityRuleInput(rule_code="R", dimension="COMPLETENESS", rule_type="NON_NULL", contribution_weight=-1)
