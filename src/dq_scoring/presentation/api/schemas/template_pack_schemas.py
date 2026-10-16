"""Structural template pack contract; behavioral fixtures are proven by the CLI validator."""
import json
import math
import re
from datetime import datetime
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

from dq_scoring.presentation.api.schemas.ruleset_schemas import (
    RULE_TYPE_ALIASES,
    CreateQualityRuleInput,
)

# Placeholder slot -> (binding type, canonical rule types that may use it).
PLACEHOLDER_SLOTS: dict[str, tuple[str, frozenset[str]]] = {
    "column": ("COLUMN", frozenset(set(RULE_TYPE_ALIASES.values()))),
    "comparison_column": ("COLUMN", frozenset({"CROSS_FIELD"})),
    "allowed_values": ("STRING_ARRAY", frozenset({"DOMAIN_RANGE", "JSON_FIELD"})),
    "dictionary_revision": ("STRING", frozenset({"SPELLING"})),
}
PLACEHOLDER_KEYS = frozenset(PLACEHOLDER_SLOTS)
PLACEHOLDER_NAME = re.compile(r"^\$[A-Za-z][A-Za-z0-9_]{0,63}$")
MAX_REVISION = 2_147_483_647
MAX_BINDING_ITEMS = 1000
TYPE_NAMES = frozenset({"INTEGER", "INT", "BIGINT", "DOUBLE", "FLOAT", "NUMERIC", "DECIMAL", "DATE", "TIMESTAMP", "DATETIME"})
OPERATORS = frozenset({">=", "GTE", "<=", "LTE", ">", "GT", "<", "LT", "==", "=", "EQ", "!=", "<>", "NEQ"})
LEGACY_KEYS: dict[str, frozenset[str]] = {
    "NON_NULL": frozenset({"column"}),
    "UNIQUENESS": frozenset({"column"}),
    "TYPE_PARSE": frozenset({"column", "data_type", "type", "format"}),
    "DOMAIN_RANGE": frozenset({"column", "allowed_values", "values", "pattern", "regex", "year", "format", "min", "max", "min_value", "max_value"}),
    "CROSS_FIELD": frozenset({"column", "comparison_column", "compare_to", "operator", "data_type", "format"}),
}
RULE_FIELDS = frozenset(CreateQualityRuleInput.model_fields)
VIOLATIONS = frozenset({"failed", "missing", "miscast"})

NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Outcome = Literal["passed", "failed", "missing", "miscast", "not_applicable"]


class PackModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Provenance(PackModel):
    kind: Literal["PUBLIC_STANDARD", "ORGANIZATION_SPEC", "ENGINEERING_CONVENTION"]
    source_uri: NonBlank = Field(max_length=2048)
    source_title: NonBlank
    source_version: NonBlank
    source_section: NonBlank
    retrieved_at: datetime
    license: NonBlank
    applicability: NonBlank

    @model_validator(mode="after")
    def validate_source(self):
        """source_uri is stored metadata only and is never fetched."""
        if any(ord(char) < 32 or char.isspace() for char in self.source_uri):
            raise ValueError("source_uri must not contain whitespace or control characters")
        if self.kind == "PUBLIC_STANDARD":
            parts = urlsplit(self.source_uri)
            if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
                raise ValueError("PUBLIC_STANDARD requires an http(s) source_uri without credentials")
        return self


class Placeholder(PackModel):
    type: Literal["COLUMN", "STRING", "STRING_ARRAY"]
    required: Literal[True] = True


def _binding_text(value: str) -> str:
    if not value.strip() or len(value) > 255 or value.startswith("$"):
        raise ValueError("Binding values must be non-blank, at most 255 characters and not start with '$'")
    return value


class Example(PackModel):
    input: dict[str, Any]
    bindings: dict[str, str | list[str]]
    expected: dict[str, Outcome] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_bindings(self):
        for value in self.bindings.values():
            if isinstance(value, list):
                if not 1 <= len(value) <= MAX_BINDING_ITEMS:
                    raise ValueError("Binding lists must contain 1..1000 items")
                for item in value:
                    _binding_text(item)
            else:
                _binding_text(value)
        return self


def _placeholder(value: Any) -> str | None:
    return value if isinstance(value, str) and value.startswith("$") else None


def _has_placeholder(value: Any) -> bool:
    if isinstance(value, str):
        return value.startswith("$")
    if isinstance(value, dict):
        return any(_has_placeholder(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_placeholder(item) for item in value)
    return False


def bind_rules(rules: list[dict[str, Any]], bindings: dict[str, str | list[str]]) -> list[dict[str, Any]]:
    """Replace exact placeholder values only; no string interpolation, no nested placeholders."""
    bound = []
    for rule in rules:
        parameters = rule.get("parameters", {})
        if not isinstance(parameters, dict):
            raise TypeError("Rule parameters must be an object")
        resolved = {key: bindings[name] if (name := _placeholder(raw)) in bindings else raw for key, raw in parameters.items()}
        candidate = {**rule, "parameters": resolved}
        if _has_placeholder(candidate):
            raise ValueError("UNRESOLVED_TEMPLATE_PLACEHOLDER")
        bound.append(candidate)
    return bound


def _text(value: Any, limit: int = 255) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= limit


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _alias_pair(params: dict[str, Any], names: tuple[str, str]) -> Any:
    present = [name for name in names if name in params]
    if len(present) > 1:
        raise ValueError(f"Only one of {names[0]}/{names[1]} may be set")
    return params[present[0]] if present else None


def _validate_legacy_params(rule_type: str, params: dict[str, Any]) -> None:
    """Shape rules for the pre-extension rule types, mirroring what sql_rule_compiler consumes."""
    unknown = set(params) - LEGACY_KEYS[rule_type]
    if unknown:
        raise ValueError(f"Unsupported parameters for {rule_type}")
    if not _text(params.get("column")):
        raise ValueError("column must be a non-blank string")
    if "format" in params and not _text(params["format"], 100):
        raise ValueError("format must be a non-blank string")
    if rule_type == "TYPE_PARSE":
        declared = _alias_pair(params, ("data_type", "type"))
        if declared is not None and (not isinstance(declared, str) or declared.upper() not in TYPE_NAMES):
            raise ValueError("Unsupported data_type")
    elif rule_type == "CROSS_FIELD":
        other = _alias_pair(params, ("comparison_column", "compare_to"))
        if not _text(other) or other == params["column"]:
            raise ValueError("comparison_column must be a non-blank column different from column")
        if not isinstance(params.get("operator", ">="), str) or params.get("operator", ">=").upper() not in OPERATORS:
            raise ValueError("Unsupported operator")
        declared = params.get("data_type", "DOUBLE")
        if not isinstance(declared, str) or declared.upper() not in TYPE_NAMES:
            raise ValueError("Unsupported data_type")
    elif rule_type == "DOMAIN_RANGE":
        _validate_domain_range(params)


def _validate_domain_range(params: dict[str, Any]) -> None:
    bounds = {"min", "max", "min_value", "max_value"} & set(params)
    modes = [bool({"allowed_values", "values"} & set(params)), bool({"pattern", "regex"} & set(params)), "year" in params, bool(bounds)]
    if sum(modes) != 1:
        raise ValueError("DOMAIN_RANGE needs exactly one of allowed_values, pattern, year or min/max")
    if "format" in params and "year" not in params:
        raise ValueError("format is only valid with year")
    if modes[0]:
        values = _alias_pair(params, ("allowed_values", "values"))
        if not isinstance(values, list) or not 1 <= len(values) <= MAX_BINDING_ITEMS or not all(_text(item) for item in values):
            raise ValueError("allowed_values must be 1..1000 non-blank strings")
    elif modes[1]:
        pattern = _alias_pair(params, ("pattern", "regex"))
        if not _text(pattern, 512):
            raise ValueError("pattern must be a non-blank string of at most 512 characters")
    elif modes[2]:
        year = params["year"]
        if isinstance(year, bool) or not isinstance(year, int) or not 1 <= year <= 9999:
            raise ValueError("year must be an integer 1..9999")
    else:
        low = _alias_pair(params, ("min", "min_value"))
        high = _alias_pair(params, ("max", "max_value"))
        numbers = [_number(value) for value in (low, high) if value is not None]
        if None in numbers or (low is not None and high is not None and numbers[0] > numbers[1]):
            raise ValueError("Range bounds must be finite numbers with min <= max")


def validate_bound_rule(rule: dict[str, Any]) -> None:
    """Validate a fully bound rule with the same models the ruleset API uses. Never echoes input values."""
    try:
        model = CreateQualityRuleInput.model_validate(rule)
    except ValidationError as exc:
        details = "; ".join(f"{e['loc'][1] if len(e['loc']) > 1 and e['loc'][0] == 'parameters' else e['loc'][0] if e['loc'] else 'rule'}:{e['type']}" for e in exc.errors(include_input=False, include_context=False, include_url=False))
        raise ValueError(f"Rule is invalid ({details})") from None
    if model.rule_type in LEGACY_KEYS:
        _validate_legacy_params(model.rule_type, model.parameters)


class PackTemplate(PackModel):
    template_code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=255)
    domain: Literal["FINANCE", "RETAIL", "HEALTHCARE", "TRANSPORTATION", "GENERAL"]
    data_type: Literal["TRANSACTION_EVENT", "MASTER_DATA", "DIMENSION_TABLE", "TIMESERIES"]
    target_use_case: str = Field(min_length=1)
    description: str = Field(min_length=1)
    rules_payload: list[dict[str, Any]] = Field(min_length=1, max_length=100)
    provenance: Provenance
    examples: list[Example] = Field(min_length=2)
    placeholder_schema: dict[str, Placeholder]

    def _placeholder_usage(self) -> dict[str, str]:
        """Map each placeholder to its binding type, rejecting every non-slot or nested placeholder."""
        used: dict[str, str] = {}
        for index, rule in enumerate(self.rules_payload):
            if set(rule) - RULE_FIELDS:
                raise ValueError(f"rules_payload[{index}] has unsupported fields")
            parameters = rule.get("parameters")
            if not isinstance(parameters, dict) or not isinstance(rule.get("rule_code"), str):
                raise TypeError(f"rules_payload[{index}] needs rule_code and parameters object")
            if _has_placeholder({key: value for key, value in rule.items() if key != "parameters"}):
                raise ValueError(f"rules_payload[{index}] has a placeholder outside parameters")
            rule_type = RULE_TYPE_ALIASES.get(str(rule.get("rule_type", "")).strip().upper())
            for key, value in parameters.items():
                name = _placeholder(value)
                if name is None:
                    if _has_placeholder(value):
                        raise ValueError(f"rules_payload[{index}] has a nested placeholder in '{key}'")
                    continue
                slot = PLACEHOLDER_SLOTS.get(key)
                if slot is None or rule_type not in slot[1]:
                    raise ValueError(f"Placeholder not allowed for parameter '{key}'")
                if not PLACEHOLDER_NAME.match(name):
                    raise ValueError("Malformed placeholder name")
                declared = self.placeholder_schema.get(name)
                if declared is None or declared.type != slot[0]:
                    raise ValueError(f"Placeholder '{name}' must be declared as {slot[0]}")
                used[name] = slot[0]
        return used

    @model_validator(mode="after")
    def validate_contract(self):
        used = self._placeholder_usage()
        if set(used) != set(self.placeholder_schema):
            raise ValueError("placeholder_schema must declare exactly the placeholders used")
        codes = [rule["rule_code"] for rule in self.rules_payload]
        if len(codes) != len(set(codes)):
            raise ValueError("Duplicate rule code")
        outcomes: dict[str, set[str]] = {code: set() for code in codes}
        for position, example in enumerate(self.examples):
            if set(example.bindings) != set(used) or set(example.expected) != set(codes):
                raise ValueError(f"examples[{position}] must bind every placeholder and expect every rule")
            for name, value in example.bindings.items():
                if (used[name] == "STRING_ARRAY") != isinstance(value, list):
                    raise ValueError(f"Binding '{name}' has the wrong type")
            for rule in bind_rules(self.rules_payload, example.bindings):
                validate_bound_rule(rule)
            for code, outcome in example.expected.items():
                outcomes[code].add(outcome)
        if any("passed" not in seen or not seen & VIOLATIONS for seen in outcomes.values()):
            raise ValueError("Each rule needs a passing and a violating (failed/missing/miscast) example")
        return self


class TemplatePack(PackModel):
    pack_code: str = Field(min_length=1, max_length=100)
    revision: int = Field(ge=1, le=MAX_REVISION, strict=True)
    templates: list[PackTemplate] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_pack(self):
        codes = [template.template_code for template in self.templates]
        if len(codes) != len(set(codes)):
            raise ValueError("Duplicate template code")
        try:
            serialized = json.dumps(self.model_dump(mode="json"), allow_nan=False)
        except ValueError:
            raise ValueError("Pack contains non-finite numbers") from None
        if "\\u0000" in serialized:
            raise ValueError("Pack contains NUL characters")
        return self


class RulesetTemplateResponse(BaseModel):
    template_id: UUID
    template_code: str
    name: str
    domain: str
    data_type: str
    target_use_case: str
    description: str | None = None
    rules_payload: list[dict[str, Any]] = Field(default_factory=list)
    is_system_template: bool
    revision: int
    provenance: dict[str, Any]
    examples: list[dict[str, Any]]
    placeholder_schema: dict[str, Any]
    status: str
    validation_status: Literal["STRUCTURAL_ONLY", "LEGACY_UNVERIFIED"]


class TemplateImportResponse(BaseModel):
    items: list[RulesetTemplateResponse]
    created: int
    existing: int
