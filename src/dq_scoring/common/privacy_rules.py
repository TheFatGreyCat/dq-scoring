"""Tenant-defined privacy detector rules: validated DTOs, RE2 compilation and pinned snapshots.

Engine-only module: no FastAPI/DB imports. Patterns are untrusted and may contain sensitive literals, so no
error raised here ever carries the pattern text.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Annotated, Literal, Self
from uuid import UUID

import re2
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from dq_scoring.common.hash_utils import compute_deterministic_hash

# Shared with migration 020 seed: rule_id = uuid5(PRIVACY_RULE_NAMESPACE, f"{tenant_id}:{builtin_code}").
PRIVACY_RULE_NAMESPACE = UUID("6f1c2d8e-4b7a-5e93-a0d1-3c5e7f9b2a46")
MAX_PATTERN_LENGTH = 512
MAX_SCOPE_COLUMNS = 1000
MAX_ENABLED_RULES = 100
RE2_MAX_MEM_BYTES = 1 << 20
INVALID_PRIVACY_PATTERN = "INVALID_PRIVACY_PATTERN"

BUILTIN_RULE_CATEGORIES: dict[str, str] = {
    "EMAIL": "BASIC_PERSONAL_DATA",
    "PHONE": "BASIC_PERSONAL_DATA",
    "CARD": "CONFIDENTIAL_BUSINESS_DATA",
    "SSN": "SENSITIVE_PERSONAL_DATA",
    "VN_ID": "SENSITIVE_PERSONAL_DATA",
    "PERSON_NAME": "BASIC_PERSONAL_DATA",
    "ADDRESS": "BASIC_PERSONAL_DATA",
    "BANK_ACCOUNT": "CONFIDENTIAL_BUSINESS_DATA",
    "SECRET": "CONFIDENTIAL_BUSINESS_DATA",
}

RuleKind = Literal["BUILTIN", "COLUMN_NAME", "VALUE_PATTERN"]
CustomRuleKind = Literal["COLUMN_NAME", "VALUE_PATTERN"]
RuleCategory = Literal["BASIC_PERSONAL_DATA", "SENSITIVE_PERSONAL_DATA", "CONFIDENTIAL_BUSINESS_DATA"]
MatchMode = Literal["FULL", "SEARCH"]
RuleCode = Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9_]{0,63}$")]
Pattern = Annotated[str, StringConstraints(min_length=1, max_length=MAX_PATTERN_LENGTH)]
ColumnName = Annotated[str, StringConstraints(min_length=1, max_length=512)]
BuiltinCode = Literal["EMAIL", "PHONE", "CARD", "SSN", "VN_ID", "PERSON_NAME", "ADDRESS", "BANK_ACCOUNT", "SECRET"]


class InvalidPrivacyPattern(ValueError):
    """Pattern rejected by RE2; message is the fixed code, never the pattern or the engine error."""

    def __init__(self) -> None:
        super().__init__(INVALID_PRIVACY_PATTERN)


def _re2_options(case_sensitive: bool) -> re2.Options:
    options = re2.Options()
    options.max_mem = RE2_MAX_MEM_BYTES
    options.log_errors = False
    options.never_capture = True
    options.case_sensitive = case_sensitive
    return options


def compile_pattern(pattern: str, case_sensitive: bool):
    """Compile with RE2 only (linear time, no backreference/lookaround); no Python `re` fallback."""
    try:
        return re2.compile(pattern, _re2_options(case_sensitive))
    except (re2.error, ValueError, TypeError, OverflowError):
        raise InvalidPrivacyPattern from None


def _check_columns(columns: Sequence[str]) -> Sequence[str]:
    if len(set(columns)) != len(columns):
        raise ValueError("DUPLICATE_COLUMNS")
    return columns


class _RuleBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: RuleCategory
    enabled: bool
    match_mode: MatchMode
    case_sensitive: bool
    columns: Annotated[list[ColumnName], Field(max_length=MAX_SCOPE_COLUMNS)]

    @field_validator("columns")
    @classmethod
    def _unique_columns(cls, value: list[str]) -> list[str]:
        _check_columns(value)
        return value


class PrivacyRuleCreate(_RuleBody):
    code: RuleCode
    kind: CustomRuleKind
    pattern: Pattern

    @model_validator(mode="after")
    def _compilable(self) -> Self:
        compile_pattern(self.pattern, self.case_sensitive)
        return self


class PrivacyRuleUpdate(_RuleBody):
    expected_revision: Annotated[int, Field(ge=1)]
    # Required for custom rules, must be null for builtins; the service enforces it against the stored kind.
    pattern: Pattern | None

    @model_validator(mode="after")
    def _compilable(self) -> Self:
        if self.pattern is not None:
            compile_pattern(self.pattern, self.case_sensitive)
        return self


class PrivacyDetectorRule(BaseModel):
    """Immutable definition of one latest rule revision (builtin or custom)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_id: UUID
    revision: Annotated[int, Field(ge=1)]
    code: RuleCode
    kind: RuleKind
    category: RuleCategory
    enabled: bool
    builtin_code: BuiltinCode | None = None
    pattern: Pattern | None = None
    match_mode: MatchMode = "FULL"
    case_sensitive: bool = True
    columns: Annotated[tuple[ColumnName, ...], Field(max_length=MAX_SCOPE_COLUMNS)] = ()

    @model_validator(mode="after")
    def _shape(self) -> Self:
        if self.kind == "BUILTIN":
            if self.builtin_code is None or self.pattern is not None:
                raise ValueError("INVALID_PRIVACY_RULE")
        else:
            if self.builtin_code is not None or self.pattern is None:
                raise ValueError("INVALID_PRIVACY_RULE")
            compile_pattern(self.pattern, self.case_sensitive)
        _check_columns(self.columns)
        return self

    def applies_to(self, column_name: str) -> bool:
        """Empty scope means every column."""
        return not self.columns or column_name in self.columns


@dataclass(frozen=True, slots=True)
class CompiledPrivacyRule:
    """Immutable compiled custom rule. `matches` is the only matching entry point."""

    rule: PrivacyDetectorRule
    _regex: object
    _full: bool

    def matches(self, text: str) -> bool:
        regex = self._regex
        return (regex.fullmatch(text) if self._full else regex.search(text)) is not None


def compile_rule(rule: PrivacyDetectorRule) -> CompiledPrivacyRule:
    """Compile a custom (COLUMN_NAME/VALUE_PATTERN) rule; builtins keep their existing detector logic."""
    if rule.pattern is None:
        raise ValueError("INVALID_PRIVACY_RULE")
    return CompiledPrivacyRule(rule, compile_pattern(rule.pattern, rule.case_sensitive), rule.match_mode == "FULL")


def compile_rules(rules: Iterable[PrivacyDetectorRule]) -> tuple[CompiledPrivacyRule, ...]:
    return tuple(compile_rule(rule) for rule in rules if rule.pattern is not None)


@dataclass(frozen=True, slots=True)
class PinnedPrivacyRules:
    """Latest-enabled rules consistent with one config version; `digest` is deterministic over definitions."""

    rules: tuple[PrivacyDetectorRule, ...]
    config_version: int
    digest: str

    def to_json(self) -> list[dict]:
        return [rule.model_dump(mode="json") for rule in self.rules]


def rules_digest(rules: Iterable[PrivacyDetectorRule]) -> str:
    ordered = sorted(rules, key=lambda rule: str(rule.rule_id))
    return compute_deterministic_hash({"rules": [rule.model_dump(mode="json") for rule in ordered]})


def pin_rules(rules: Iterable[PrivacyDetectorRule], config_version: int) -> PinnedPrivacyRules:
    ordered = tuple(sorted(rules, key=lambda rule: str(rule.rule_id)))
    return PinnedPrivacyRules(ordered, config_version, rules_digest(ordered))


def pinned_from_json(items: Sequence[dict], config_version: int) -> PinnedPrivacyRules:
    """Rebuild a pin from stored `pinned_rules` JSON (workers/scans)."""
    return pin_rules((PrivacyDetectorRule.model_validate(item) for item in items), config_version)

