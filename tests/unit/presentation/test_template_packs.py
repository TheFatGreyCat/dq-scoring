"""Structural validation of template packs (synthetic data only)."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest
from pydantic import ValidationError

from dq_scoring.presentation.api.schemas.template_pack_schemas import (
    TemplatePack,
    bind_rules,
)
from dq_scoring.services.template_pack_service import template_digest

PROVENANCE = {
    "kind": "ENGINEERING_CONVENTION", "source_uri": "repo://packs/synthetic", "source_title": "Synthetic pack",
    "source_version": "1", "source_section": "all", "retrieved_at": "2026-01-01T00:00:00Z",
    "license": "internal", "applicability": "synthetic tests only",
}


def _example(bindings: dict, expected: dict) -> dict:
    return {"input": {"synthetic": True}, "bindings": bindings, "expected": expected}


def _template(code: str, rules: list[dict], schema: dict, bindings: dict, **extra: Any) -> dict:
    codes = [rule["rule_code"] for rule in rules]
    return {
        "template_code": code, "name": code, "domain": "GENERAL", "data_type": "MASTER_DATA", "target_use_case": "TEST",
        "description": "synthetic", "rules_payload": rules, "provenance": PROVENANCE, "placeholder_schema": schema,
        "examples": [
            _example(bindings, {c: "passed" for c in codes}),
            _example(bindings, {c: "failed" for c in codes}),
        ],
        **extra,
    }


def _rule(rule_type: str, parameters: dict, code: str = "R1") -> dict:
    return {"rule_code": code, "dimension": "VALIDITY", "rule_type": rule_type, "parameters": parameters}


COLUMN = {"$col": {"type": "COLUMN"}}
BIND = {"$col": "c"}


def _pack(template: dict) -> dict:
    return {"pack_code": "synthetic", "revision": 1, "templates": [template]}


def _valid(rule_type: str, parameters: dict, schema: dict | None = None, bindings: dict | None = None) -> dict:
    return _pack(_template("T", [_rule(rule_type, parameters)], schema if schema is not None else COLUMN, bindings if bindings is not None else BIND))


VALID_RULES = [
    ("NON_NULL", {"column": "$col"}),
    ("UNIQUENESS", {"column": "$col"}),
    ("TYPE_PARSE", {"column": "$col", "data_type": "TIMESTAMP"}),
    ("DOMAIN_RANGE", {"column": "$col", "min": 0}),
    ("DOMAIN_RANGE", {"column": "$col", "pattern": "^[A-Z]+$"}),
    ("DOMAIN_RANGE", {"column": "$col", "year": 2024}),
    ("CROSS_FIELD", {"column": "$col", "comparison_column": "$other", "operator": "EQ"}),
    ("TEXT_QUALITY", {"column": "$col", "check": "REPLACEMENT_CHARACTER"}),
    ("JSON_FIELD", {"column": "$col", "path": "/a", "check": "NON_NULL"}),
    ("JSON_ARRAY", {"column": "$col", "path": "/a", "unique_items": True}),
]


@pytest.mark.parametrize(("rule_type", "parameters"), VALID_RULES)
def test_every_rule_type_with_pass_and_violation_fixtures_is_accepted(rule_type, parameters):
    schema = {**COLUMN, **({"$other": {"type": "COLUMN"}} if "comparison_column" in parameters else {})}
    bindings = {**BIND, **({"$other": "d"} if "comparison_column" in parameters else {})}
    TemplatePack.model_validate(_valid(rule_type, parameters, schema, bindings))


def test_typed_slots_allowed_values_and_dictionary_revision():
    schema = {**COLUMN, "$vals": {"type": "STRING_ARRAY"}}
    TemplatePack.model_validate(_valid("DOMAIN_RANGE", {"column": "$col", "allowed_values": "$vals"}, schema, {**BIND, "$vals": ["A", "B"]}))
    schema = {**COLUMN, "$rev": {"type": "STRING"}}
    TemplatePack.model_validate(_valid("SPELLING", {"column": "$col", "language": "en", "dictionary_revision": "$rev"}, schema, {**BIND, "$rev": "r1"}))


@pytest.mark.parametrize(
    ("rule_type", "parameters"),
    [
        ("NON_NULL", {"column": "$col", "extra": 1}),
        ("NON_NULL", {"column": ""}),
        ("TYPE_PARSE", {"column": "$col", "data_type": "BLOB"}),
        ("TYPE_PARSE", {"column": "$col", "data_type": "DATE", "type": "DATE"}),
        ("DOMAIN_RANGE", {"column": "$col"}),
        ("DOMAIN_RANGE", {"column": "$col", "min": 5, "max": 1}),
        ("DOMAIN_RANGE", {"column": "$col", "min": "abc"}),
        ("DOMAIN_RANGE", {"column": "$col", "min": 0, "pattern": "x"}),
        ("DOMAIN_RANGE", {"column": "$col", "pattern": "x" * 513}),
        ("DOMAIN_RANGE", {"column": "$col", "allowed_values": []}),
        ("DOMAIN_RANGE", {"column": "$col", "year": True}),
        ("CROSS_FIELD", {"column": "$col"}),
        ("CROSS_FIELD", {"column": "$col", "comparison_column": "$col"}),
        ("CROSS_FIELD", {"column": "$col", "comparison_column": "x", "operator": "DROP"}),
        ("TEXT_QUALITY", {"column": "$col", "check": "NOPE"}),
        ("JSON_FIELD", {"column": "$col", "path": "a", "check": "NON_NULL"}),
        ("JSON_ARRAY", {"column": "$col", "path": ""}),
        ("UNKNOWN_TYPE", {"column": "$col"}),
    ],
)
def test_malformed_rules_are_rejected(rule_type, parameters):
    with pytest.raises(ValidationError):
        TemplatePack.model_validate(_valid(rule_type, parameters, COLUMN, BIND))


def test_placeholder_rules():
    bad_cases = {
        "unknown slot": _valid("NON_NULL", {"column": "x", "format": "$col"}),
        "wrong slot for type": _valid("NON_NULL", {"column": "$col", "comparison_column": "$col"}),
        "wrong declared type": _valid("NON_NULL", {"column": "$col"}, {"$col": {"type": "STRING"}}),
        "undeclared": _valid("NON_NULL", {"column": "$col"}, {}, {}),
        "unused declared": _valid("NON_NULL", {"column": "$col"}, {**COLUMN, "$z": {"type": "COLUMN"}}, {**BIND, "$z": "z"}),
        "malformed name": _valid("NON_NULL", {"column": "$a b"}, {"$a b": {"type": "COLUMN"}}, {"$a b": "c"}),
        "nested": _valid("DOMAIN_RANGE", {"column": "$col", "allowed_values": ["$col"]}, COLUMN, BIND),
        "outside parameters": _pack(_template("T", [{**_rule("NON_NULL", {"column": "$col"}), "dimension": "$col"}], COLUMN, BIND)),
        "binding value is placeholder": _valid("NON_NULL", {"column": "$col"}, COLUMN, {"$col": "$other"}),
    }
    for label, pack in bad_cases.items():
        with pytest.raises(ValidationError):
            TemplatePack.model_validate(pack)
            pytest.fail(label)


def test_binding_type_mismatch_and_missing_fixtures():
    schema = {**COLUMN, "$vals": {"type": "STRING_ARRAY"}}
    rule = {"column": "$col", "allowed_values": "$vals"}
    with pytest.raises(ValidationError):
        TemplatePack.model_validate(_valid("DOMAIN_RANGE", rule, schema, {**BIND, "$vals": "A"}))
    only_passing = _valid("NON_NULL", {"column": "$col"})
    for example in only_passing["templates"][0]["examples"]:
        example["expected"] = {"R1": "passed"}
    with pytest.raises(ValidationError):
        TemplatePack.model_validate(only_passing)
    one_example = _valid("NON_NULL", {"column": "$col"})
    one_example["templates"][0]["examples"].pop()
    with pytest.raises(ValidationError):
        TemplatePack.model_validate(one_example)


def test_provenance_rules():
    public = _valid("NON_NULL", {"column": "$col"})
    public["templates"][0]["provenance"] = {**PROVENANCE, "kind": "PUBLIC_STANDARD"}
    with pytest.raises(ValidationError):
        TemplatePack.model_validate(public)
    public["templates"][0]["provenance"]["source_uri"] = "https://example.org/spec"
    TemplatePack.model_validate(public)
    public["templates"][0]["provenance"]["license"] = " "
    with pytest.raises(ValidationError):
        TemplatePack.model_validate(public)


def test_errors_never_echo_sensitive_input():
    secret = "SYNTHETIC-SECRET-4242"
    pack = _valid("NON_NULL", {"column": "$col", secret: 1})
    with pytest.raises(ValidationError) as exc:
        TemplatePack.model_validate(pack)
    errors = exc.value.errors(include_url=False, include_context=False, include_input=False)
    assert all("input" not in error for error in errors)
    bad_binding = _valid("NON_NULL", {"column": "$col"}, COLUMN, {"$col": secret * 40})
    with pytest.raises(ValidationError) as exc:
        TemplatePack.model_validate(bad_binding)
    assert secret not in str(exc.value.errors(include_url=False, include_context=False, include_input=False))


@pytest.mark.parametrize("revision", [0, -1, True, 2**31, "1"])
def test_revision_bounds(revision):
    pack = _valid("NON_NULL", {"column": "$col"})
    pack["revision"] = revision
    with pytest.raises(ValidationError):
        TemplatePack.model_validate(pack)


def test_bind_rules_exact_replacement_only():
    rules = [_rule("DOMAIN_RANGE", {"column": "$col", "allowed_values": "$vals"})]
    bound = bind_rules(rules, {"$col": "c", "$vals": ["x"]})
    assert bound[0]["parameters"] == {"column": "c", "allowed_values": ["x"]}
    assert rules[0]["parameters"]["column"] == "$col"
    with pytest.raises(ValueError, match="UNRESOLVED_TEMPLATE_PLACEHOLDER"):
        bind_rules(rules, {"$col": "c"})


def test_digest_ignores_nothing_but_content():
    pack = TemplatePack.model_validate(_valid("NON_NULL", {"column": "$col"}))
    template = pack.templates[0]
    assert template_digest(template, 1) == template_digest(template, 1)
    assert template_digest(template, 1) != template_digest(template, 2)
    changed = deepcopy(_valid("NON_NULL", {"column": "$col"}))
    changed["templates"][0]["description"] = "different"
    assert template_digest(TemplatePack.model_validate(changed).templates[0], 1) != template_digest(template, 1)
