import pytest
from pydantic import ValidationError

from dq_scoring.presentation.api.schemas.ruleset_schemas import CreateQualityRuleInput


@pytest.mark.parametrize("kind,parameters", [
    ("SPELLING", {"column": "text", "language": "en", "dictionary_revision": "synthetic-v1"}),
    ("TEXT_QUALITY", {"column": "text", "check": "MOJIBAKE"}),
])
def test_uncertain_text_checks_cannot_be_scoring_or_gate_rules(kind, parameters):
    rule = CreateQualityRuleInput(rule_code="SYNTHETIC", dimension="VALIDITY", rule_type=kind, parameters=parameters, is_required=True, is_critical=True)
    assert rule.is_advisory
    assert not rule.is_required and not rule.is_critical
    assert not rule.score_enabled and not rule.gate_enabled
    assert rule.contribution_weight == 0


def test_json_parameters_reject_unknown_fields():
    with pytest.raises(ValidationError):
        CreateQualityRuleInput(rule_code="SYNTHETIC", dimension="VALIDITY", rule_type="JSON_ARRAY", parameters={"column":"payload", "path":"", "min_items":1, "eval":"arbitrary"})
