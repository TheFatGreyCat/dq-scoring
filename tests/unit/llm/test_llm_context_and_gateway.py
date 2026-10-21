"""Egress allowlist, candidate validation and gateway transport guarantees (no network)."""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from pydantic import ValidationError

from dq_scoring.adapters.llm import gateway_client
from dq_scoring.adapters.llm.gateway_client import AiError, GatewayReply, complete_json
from dq_scoring.adapters.llm.gateway_settings import LlmSettings
from dq_scoring.adapters.llm.recommendation_adapter import validate_candidates
from dq_scoring.common.llm_context import (
    ColumnContext,
    build_recommendation_context,
    canonical_json,
)

STAT = {"type_hint": "STRING", "sample_rows": 4, "null_count": 1, "non_null_count": 3, "distinct_count": 3,
        "parse_success_count": 3, "min": "SECRET-MIN", "max": "SECRET-MAX"}


def _settings(**kw) -> LlmSettings:
    base = {"enabled": True, "endpoint": "https://gw.example/v1/chat/completions", "model": "m", "api_key": "synthetic-key"}
    return LlmSettings(_env_file=None, **{**base, **kw})


def _build(columns, protected=frozenset(), total=4, sample=4):
    schema = {"columns": [{"name": n} for n in columns]}
    profile = {"sample_rows": sample, "columns": [{"name": n, **s} for n, s in columns.items()]}
    return build_recommendation_context(schema, profile, protected, total, 50, {n: "CATEGORY" for n in columns}), profile


def test_payload_contains_only_tokens_and_aggregates():
    (context, tokens), _ = _build({"customer_email": STAT, "fare": STAT}, protected=frozenset({"customer_email"}))
    payload = canonical_json(context)
    assert tokens == {"c001": "fare"}
    for leaked in ("customer_email", "fare", "SECRET-MIN", "SECRET-MAX"):
        assert leaked not in payload
    assert set(json.loads(payload)["columns"][0]) == {
        "token", "type", "sample_rows", "null_count", "non_null_count", "distinct_count", "parse_success_count",
        "semantic"}


@pytest.mark.parametrize("patch", [
    {"null_count": "1"}, {"null_count": -1}, {"non_null_count": 10**13}, {"distinct_count": 9},
    {"parse_success_count": 9}, {"null_count": 2}, {"distinct_count": None},
])
def test_invalid_or_inconsistent_counts_exclude_column_instead_of_fabricating_zero(patch):
    (context, tokens), _ = _build({"a": {**STAT, **patch}, "b": STAT})
    assert tokens == {"c001": "b"} and [c.token for c in context.columns] == ["c001"]


def test_all_columns_invalid_or_unprofiled_yields_no_context():
    (context, tokens), _ = _build({"a": {**STAT, "null_count": None}})
    assert context is None and tokens == {}
    assert build_recommendation_context({"columns": [{"name": "a"}]}, {"sample_rows": 4, "columns": []}, frozenset(), 4, 50) == (None, {})


def test_missing_total_rows_is_not_zero():
    (context, _), _ = _build({"a": STAT}, total=None)
    assert context is None


def test_context_models_reject_unknown_fields():
    with pytest.raises(ValidationError):
        ColumnContext(token="c000", type="STRING", sample_rows=1, null_count=0, non_null_count=1, distinct_count=1,
                      parse_success_count=1, name="leak")


def _reply(candidates) -> GatewayReply:
    return GatewayReply(content=json.dumps({"candidates": candidates}), model="m")


def test_candidates_map_to_local_names_and_drop_unknown_tokens_and_duplicates():
    (context, tokens), profile = _build({"fare": STAT, "id": STAT})
    rules, rejected = validate_candidates(
        _reply([
            {"token": "c000", "rule_type": "NON_NULL", "null_policy": "fail"},
            {"token": "c000", "rule_type": "NON_NULL", "null_policy": "fail"},
            {"token": "c009", "rule_type": "NON_NULL", "null_policy": "fail"},
            {"token": "c001", "rule_type": "TYPE_PARSE", "null_policy": "fail"},
        ]),
        tokens, profile, context, ("COMPLETENESS", "VALIDITY", "UNIQUENESS"),
    )
    assert [r["rule"]["parameters"] for r in rules] == [{"column": "fare"}]
    assert rejected == 2  # unknown token + TYPE_PARSE on a STRING column
    assert rules[0]["rule"]["is_required"] is False and rules[0]["rule"]["is_critical"] is False


def test_candidate_outside_requested_priorities_is_rejected():
    (context, tokens), profile = _build({"fare": STAT})
    rules, rejected = validate_candidates(
        _reply([{"token": "c000", "rule_type": "UNIQUENESS", "null_policy": "fail"}]), tokens, profile, context, ("COMPLETENESS",))
    assert rules == [] and rejected == 1


@pytest.mark.parametrize("content", [
    "not json", json.dumps({"candidates": [], "extra": 1}),
    json.dumps({"candidates": [{"token": "c000", "rule_type": "DROP_TABLE", "null_policy": "fail"}]}),
    json.dumps({"candidates": [{"token": "c000", "rule_type": "NON_NULL", "parameters": {"column": "x"}}]}),
])
def test_malformed_model_output_is_fixed_code_error(content):
    (context, tokens), profile = _build({"fare": STAT})
    with pytest.raises(AiError) as exc:
        validate_candidates(GatewayReply(content=content, model="m"), tokens, profile, context, ("COMPLETENESS",))
    assert exc.value.code == "AI_INVALID_OUTPUT"


def _use_transport(monkeypatch, handler):
    real = httpx.AsyncClient
    seen: dict = {}

    def factory(**kwargs):
        seen.update(kwargs)
        return real(transport=httpx.MockTransport(handler), **{k: v for k, v in kwargs.items() if k in ("timeout", "follow_redirects", "trust_env")})

    monkeypatch.setattr(gateway_client.httpx, "AsyncClient", factory)
    return seen


def _ok(content="{}"):
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


def test_gateway_sends_bearer_only_to_configured_endpoint_without_redirects_or_env_trust(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        return _ok('{"candidates":[]}')

    seen = _use_transport(monkeypatch, handler)
    reply = asyncio.run(complete_json(_settings(), "sys", "usr"))
    assert reply.content == '{"candidates":[]}' and reply.model == "m"
    assert str(requests[0].url) == "https://gw.example/v1/chat/completions"
    assert requests[0].headers["authorization"] == "Bearer synthetic-key"
    body = json.loads(requests[0].content)
    assert body["stream"] is False and "tools" not in body and body["messages"][1]["content"] == "usr"
    assert seen["follow_redirects"] is False and seen["trust_env"] is False


def test_redirect_is_not_followed_and_error_is_fixed_code(monkeypatch):
    _use_transport(monkeypatch, lambda r: httpx.Response(302, headers={"location": "https://evil.example/"}))
    with pytest.raises(AiError) as exc:
        asyncio.run(complete_json(_settings(), "s", "u"))
    assert exc.value.code == "AI_UNAVAILABLE" and "evil" not in str(exc.value)


def test_oversized_response_is_rejected(monkeypatch):
    _use_transport(monkeypatch, lambda r: httpx.Response(200, content=b"x" * (gateway_client.MAX_RESPONSE_BYTES + 1)))
    with pytest.raises(AiError) as exc:
        asyncio.run(complete_json(_settings(), "s", "u"))
    assert exc.value.code == "AI_INVALID_OUTPUT"


def test_transport_failure_and_timeout_map_to_safe_codes(monkeypatch):
    def boom(request):
        raise httpx.ConnectError("synthetic-key leaked?")

    _use_transport(monkeypatch, boom)
    with pytest.raises(AiError) as exc:
        asyncio.run(complete_json(_settings(), "s", "u"))
    assert exc.value.code == "AI_UNAVAILABLE" and "synthetic" not in str(exc.value)
    monkeypatch.undo()

    def slow(request):
        raise httpx.ReadTimeout("t")

    _use_transport(monkeypatch, slow)
    with pytest.raises(AiError) as exc:
        asyncio.run(complete_json(_settings(), "s", "u"))
    assert exc.value.code == "AI_TIMEOUT"


@pytest.mark.parametrize("kw", [{"endpoint": "http://gw.example/v1"}, {"endpoint": "https://user:pw@gw.example/v1"},
                                {"model": None}, {"api_key": None}])
def test_unsafe_or_incomplete_configuration_is_not_configured(kw):
    settings = _settings(**kw)
    assert not settings.configured
    with pytest.raises(AiError) as exc:
        gateway_client.require_enabled(settings)
    assert exc.value.code == "AI_NOT_CONFIGURED"


def test_disabled_by_default():
    with pytest.raises(AiError) as exc:
        gateway_client.require_enabled(LlmSettings(_env_file=None))
    assert exc.value.code == "AI_DISABLED"


def test_concurrency_bound_fails_fast():
    async def run():
        settings = _settings(max_concurrency=1)
        async with gateway_client.gateway_slot(settings):
            with pytest.raises(AiError) as exc:
                async with gateway_client.gateway_slot(settings):
                    pass
            assert exc.value.code == "AI_BUSY"

    gateway_client._SEMAPHORES.clear()
    asyncio.run(run())


def test_full_profile_context_keeps_unknown_metrics_null_and_uses_scanned_rows():
    stat = {"technical_type": "STRING", "null_count": 1, "non_null_count": 9, "distinct_count": None,
            "parse_success_count": None, "parse_target": None}
    schema = {"columns": [{"name": "a"}]}
    profile = {"mode": "FULL", "is_sample": False, "scanned_rows": 10, "columns": [{"name": "a", **stat}]}
    context, tokens = build_recommendation_context(schema, profile, frozenset(), 10, 50, {"a": "CATEGORY"})
    column = json.loads(canonical_json(context))["columns"][0]
    assert column["sample_rows"] == 10 and column["distinct_count"] is None and column["parse_success_count"] is None
    assert tokens == {"c000": "a"}
