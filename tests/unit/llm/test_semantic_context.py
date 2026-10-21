"""Semantic evidence, provider payload allowlists and output validation (no network)."""
from __future__ import annotations

import json

import pytest

from dq_scoring.adapters.llm.gateway_client import AiError, GatewayReply
from dq_scoring.adapters.llm.gateway_settings import LlmSettings, LocalLlmSettings
from dq_scoring.adapters.llm.semantic_adapter import validate_semantics
from dq_scoring.common.llm_context import build_recommendation_context
from dq_scoring.common.semantic_context import (
    build_api_context,
    build_local_context,
    canonical_json,
    local_evidence,
)

STAT = {"type_hint": "STRING", "sample_rows": 4, "null_count": 1, "non_null_count": 3, "distinct_count": 3,
        "parse_success_count": 3, "min": "SECRET-MIN", "max": "SECRET-MAX", "reason": "SECRET-REASON"}
NAMES = ("sentinel_customer", "sentinel_fare", "sentinel_email", "sentinel_free")


def _inputs(names=NAMES):
    schema = {"columns": [{"name": n, "description": "SECRET-DESC"} for n in names]}
    profile = {"sample_rows": 4, "columns": [{"name": n, **STAT} for n in names]}
    return schema, profile


def test_api_context_has_only_confirmed_unprotected_tokens_and_no_original_text():
    schema, profile = _inputs()
    confirmed = {"sentinel_customer": "IDENTIFIER", "sentinel_fare": "MONEY", "sentinel_email": "EMAIL"}
    context, tokens = build_api_context(schema, profile, frozenset({"sentinel_email"}), confirmed, 50)
    payload = canonical_json(context)
    assert tokens == {"c000": "sentinel_customer", "c001": "sentinel_fare"}
    for leaked in ("sentinel", "SECRET", "EMAIL", "SECRET-MIN", "SECRET-MAX", "SECRET-REASON"):
        assert leaked not in payload
    assert [c["semantic"] for c in json.loads(payload)["columns"]] == ["IDENTIFIER", "MONEY"]


def test_api_context_is_none_without_confirmed_eligible_column():
    schema, profile = _inputs()
    assert build_api_context(schema, profile, frozenset(), {}, 50) == (None, {})
    assert build_api_context(schema, profile, frozenset(NAMES), {n: "MONEY" for n in NAMES}, 50) == (None, {})
    assert build_api_context(schema, profile, frozenset(), {"sentinel_fare": "NOT_A_LABEL"}, 50) == (None, {})


def test_local_context_has_names_and_confirmed_label_but_no_values_or_protected_columns():
    schema, profile = _inputs()
    context, tokens = build_local_context(schema, profile, frozenset({"sentinel_email"}), {"sentinel_fare": "MONEY"}, 50)
    payload = canonical_json(context)
    assert "sentinel_customer" in payload and "sentinel_email" not in payload
    for leaked in ("SECRET", "min", "max"):
        assert leaked not in payload
    assert tokens["c001"] == "sentinel_fare"
    by_name = {c["name"]: c["semantic"] for c in json.loads(payload)["columns"]}
    assert by_name == {"sentinel_customer": None, "sentinel_fare": "MONEY", "sentinel_free": None}
    assert build_local_context(schema, profile, frozenset(NAMES), {}, 50) == (None, {})


def test_unknown_counts_stay_null_in_full_profile_contexts():
    stat = {"technical_type": "STRING", "null_count": 1, "non_null_count": 9, "distinct_count": None, "parse_success_count": None}
    schema = {"columns": [{"name": "a"}]}
    profile = {"mode": "FULL", "scanned_rows": 10, "columns": [{"name": "a", **stat}]}
    context, _ = build_api_context(schema, profile, frozenset(), {"a": "CATEGORY"}, 50)
    column = json.loads(canonical_json(context))["columns"][0]
    assert column["distinct_count"] is None and column["parse_success_count"] is None


def test_recommendation_context_carries_only_confirmed_columns():
    schema, profile = _inputs(("a", "b"))
    context, _ = build_recommendation_context(schema, profile, frozenset(), 4, 50, {"a": "IDENTIFIER", "b": "bogus"})
    assert [c.semantic for c in context.columns] == ["IDENTIFIER"]
    assert build_recommendation_context(schema, profile, frozenset(), 4, 50) == (None, {})
    assert build_recommendation_context(schema, profile, frozenset({"a"}), 4, 50, {"a": "IDENTIFIER"}) == (None, {})


def test_evidence_does_not_claim_identifier_from_distinct_ratio_alone():
    schema = {"columns": [{"name": "alpha"}, {"name": "customer_id"}, {"name": "birth_date"}, {"name": "x"}]}
    unique = {"type_hint": "STRING", "sample_rows": 3, "null_count": 0, "non_null_count": 3, "distinct_count": 3,
              "parse_success_count": 3}
    profile = {"sample_rows": 3, "columns": [
        {"name": "alpha", **unique}, {"name": "customer_id", **unique},
        {"name": "birth_date", **unique, "type_hint": "DATE"}, {"name": "x", **unique, "distinct_count": None},
    ]}
    privacy = [{"column_name": "x", "effective_categories": ["BASIC_PERSONAL_DATA"]}]
    evidence = {e["column"]: e for e in local_evidence(schema, profile, privacy)}
    assert evidence["alpha"]["suggested_label"] == "UNKNOWN" and evidence["alpha"]["reason_codes"] == ["NO_SEMANTIC_EVIDENCE"]
    assert evidence["customer_id"]["suggested_label"] == "IDENTIFIER"
    assert "DISTINCT_EQUALS_NON_NULL" in evidence["customer_id"]["reason_codes"]
    assert evidence["birth_date"]["suggested_label"] == "DATE_TIME"
    assert evidence["x"]["suggested_label"] == "UNKNOWN"
    assert all(e["source"] == "LOCAL_EVIDENCE" and 0 <= e["confidence"] <= 1 for e in evidence.values())


def _reply(labels) -> GatewayReply:
    return GatewayReply(content=json.dumps({"labels": labels}), model="m")


def _ctx():
    schema, profile = _inputs(("a", "b"))
    return build_api_context(schema, profile, frozenset(), {"a": "MONEY", "b": "MONEY"}, 50)


def test_validator_maps_tokens_and_rejects_unknown_token_or_label():
    context, tokens = _ctx()
    labels = [{"token": "c000", "label": "MONEY"}, {"token": "c009", "label": "MONEY"}, {"token": "c001", "label": "SECRETS"}]
    results, rejected = validate_semantics(_reply(labels), tokens, context)
    assert results == [{"column": "a", "label": "MONEY", "reason_codes": ["MODEL_SUGGESTION"]}]
    assert rejected == 2


@pytest.mark.parametrize("content", [
    "not json", "[]", json.dumps({"labels": [{"token": "c000", "label": "MONEY", "why": "x"}]}),
    json.dumps({"labels": [], "extra": 1}),
    json.dumps({"labels": [{"token": "c000", "label": "MONEY"}, {"token": "c000", "label": "UNKNOWN"}]}),
    json.dumps({"labels": [{"token": "c000", "label": "MONEY"}] * 201}),
    json.dumps({"labels": [{"token": "name", "label": "MONEY"}]}),
])
def test_validator_malformed_extra_duplicate_or_oversized_output_is_fixed_code(content):
    context, tokens = _ctx()
    with pytest.raises(AiError) as exc:
        validate_semantics(GatewayReply(content=content, model="m"), tokens, context)
    assert exc.value.code == "AI_INVALID_OUTPUT"


def test_local_settings_read_local_prefix_only(monkeypatch):
    monkeypatch.setenv("DQ_LLM_ENABLED", "true")
    monkeypatch.setenv("DQ_LLM_MODEL", "api-model")
    monkeypatch.setenv("DQ_LLM_LOCAL_MODEL", "local-model")
    assert LocalLlmSettings(_env_file=None).enabled is False
    assert LocalLlmSettings(_env_file=None).model == "local-model"
    assert LlmSettings(_env_file=None).model == "api-model"
    monkeypatch.setenv("DQ_LLM_LOCAL_ENDPOINT", "http://insecure.example/v1")
    assert LocalLlmSettings(_env_file=None).configured is False
