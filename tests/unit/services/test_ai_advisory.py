import json

import pytest

from dq_scoring.adapters.llm.gateway_client import AiError, GatewayReply
from dq_scoring.adapters.llm.recommendation_adapter import validate_candidates
from dq_scoring.common.llm_context import build_recommendation_context, canonical_json
from dq_scoring.services.assessment_report_service import _validate


def context():
    profile = {'sample_rows': 3, 'columns': [{'name': 'private@example.test', 'type_hint': 'STRING', 'sample_rows': 3, 'null_count': 1, 'non_null_count': 2, 'distinct_count': 2, 'parse_success_count': 2, 'min': 'secret'}]}
    ctx, tokens = build_recommendation_context({'columns': ['private@example.test']}, profile, frozenset(), 3, 50)
    return ctx, tokens, profile


def test_external_context_excludes_dataset_strings_and_extrema():
    ctx, _, _ = context()
    payload = canonical_json(ctx)
    assert 'private@example.test' not in payload
    assert 'secret' not in payload
    assert json.loads(payload)['columns'][0]['non_null_count'] == 2


def test_protected_columns_never_enter_external_context():
    _, _, profile = context()
    ctx, tokens = build_recommendation_context({'columns': ['private@example.test']}, profile, frozenset({'private@example.test'}), 3, 50)
    assert ctx is None and tokens == {}


def test_invalid_candidate_cannot_reference_unknown_column_or_invent_parameters():
    ctx, tokens, profile = context()
    reply = GatewayReply(json.dumps({'candidates': [{'token': 'c999', 'rule_type': 'NON_NULL', 'null_policy': 'fail'}]}), 'synthetic')
    rules, rejected = validate_candidates(reply, tokens, profile, ctx, ('COMPLETENESS',))
    assert rules == [] and rejected == 1
    malicious = GatewayReply(json.dumps({'candidates': [{'token': 'c000', 'rule_type': 'NON_NULL', 'parameters': {'sql': 'DROP TABLE x'}}]}), 'synthetic')
    with pytest.raises(AiError, match='AI_INVALID_OUTPUT'):
        validate_candidates(malicious, tokens, profile, ctx, ('COMPLETENESS',))


def test_valid_candidate_maps_locally_and_cannot_set_required_or_critical():
    ctx, tokens, profile = context()
    reply = GatewayReply('{"candidates":[{"token":"c000","rule_type":"NON_NULL","null_policy":"fail"}]}', 'synthetic')
    rules, rejected = validate_candidates(reply, tokens, profile, ctx, ('COMPLETENESS',))
    assert rejected == 0
    assert rules[0]['rule']['parameters']['column'] == 'private@example.test'
    assert rules[0]['rule']['is_required'] is False
    assert rules[0]['rule']['is_critical'] is False


@pytest.mark.parametrize('text', ['<script>alert(1)</script>', '[x](javascript:alert(1))', 'https://unsafe.test'])
def test_narrative_rejects_active_markup_and_links(text):
    with pytest.raises(AiError, match='AI_INVALID_OUTPUT'):
        _validate(json.dumps({'narrative': text, 'cited_rules': []}), {})


def test_narrative_rejects_fabricated_rule_citation():
    with pytest.raises(AiError, match='AI_INVALID_OUTPUT'):
        _validate('{"narrative":"Review measured rule","cited_rules":["r999"]}', {'r000': 'local-id'})
