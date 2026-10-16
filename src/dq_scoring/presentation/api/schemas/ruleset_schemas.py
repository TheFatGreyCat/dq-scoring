"""Ruleset and Quality Rule request and response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from dq_scoring.common.rule_parameters import (
    JsonArrayParameters,
    JsonFieldParameters,
    SpellingParameters,
    TextQualityParameters,
)
from dq_scoring.core.models import StandardDimension

# Canonical rule types accepted by quality_rules.rule_type; aliases understood by the
# rule compiler are mapped onto them so the database never sees an alias.
RULE_TYPE_ALIASES: dict[str, str] = {
    "NON_NULL": "NON_NULL", "NOT_NULL": "NON_NULL", "COMPLETENESS": "NON_NULL",
    "TYPE_PARSE": "TYPE_PARSE", "TYPE": "TYPE_PARSE", "PARSER": "TYPE_PARSE",
    "DOMAIN_RANGE": "DOMAIN_RANGE", "RANGE": "DOMAIN_RANGE", "DOMAIN": "DOMAIN_RANGE",
    "ALLOWED_VALUES": "DOMAIN_RANGE", "REGEX": "DOMAIN_RANGE",
    "CROSS_FIELD": "CROSS_FIELD", "CONSISTENCY": "CROSS_FIELD", "COLUMN_COMPARISON": "CROSS_FIELD",
    "UNIQUENESS": "UNIQUENESS", "UNIQUE": "UNIQUENESS", "DISTINCT": "UNIQUENESS",
    "TEXT_QUALITY": "TEXT_QUALITY", "SPELLING": "SPELLING",
    "JSON_FIELD": "JSON_FIELD", "JSON_ARRAY": "JSON_ARRAY",
}
NULL_POLICIES = frozenset({"fail", "ignore", "separate", "not_applicable"})


class CreateQualityRuleInput(BaseModel):
    """Payload to configure a single quality rule."""

    rule_code: str = Field(..., min_length=1, max_length=100)
    dimension: str
    rule_type: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    null_policy: str = "fail"
    is_required: bool = False
    is_critical: bool = False
    gate_enabled: bool = True
    score_enabled: bool = True
    contribution_weight: float = Field(1.0, ge=0, allow_inf_nan=False)
    acceptance_threshold: float | None = Field(default=None, ge=0.0, le=100.0)
    is_advisory: bool = False

    @field_validator("dimension")
    @classmethod
    def _canonical_dimension(cls, value: str) -> str:
        name = value.strip().upper()
        if name not in {d.value for d in StandardDimension}:
            raise ValueError(f"Unknown dimension '{value}'")
        return name

    @field_validator("rule_type")
    @classmethod
    def _canonical_rule_type(cls, value: str) -> str:
        canonical = RULE_TYPE_ALIASES.get(value.strip().upper())
        if canonical is None:
            raise ValueError(f"Unsupported rule type '{value}'. Allowed: {sorted(set(RULE_TYPE_ALIASES.values()))}")
        return canonical

    @field_validator("null_policy")
    @classmethod
    def _known_null_policy(cls, value: str) -> str:
        policy = value.strip().lower()
        if policy not in NULL_POLICIES:
            raise ValueError(f"Unsupported null policy '{value}'. Allowed: {sorted(NULL_POLICIES)}")
        return policy

    @model_validator(mode="after")
    def _extended_parameters(self):
        placeholder_keys = ("column", "comparison_column", "allowed_values", "dictionary_revision")
        if any(isinstance(self.parameters.get(key), str) and self.parameters[key].startswith("$") for key in placeholder_keys):
            raise ValueError("UNRESOLVED_TEMPLATE_PLACEHOLDER")
        models = {"TEXT_QUALITY": TextQualityParameters, "SPELLING": SpellingParameters,
                  "JSON_FIELD": JsonFieldParameters, "JSON_ARRAY": JsonArrayParameters}
        model = models.get(self.rule_type)
        if model is not None:
            self.parameters = model.model_validate(self.parameters).model_dump(exclude_none=True)
        if self.rule_type == "SPELLING" or (self.rule_type == "TEXT_QUALITY" and self.parameters.get("check") == "MOJIBAKE"):
            self.is_advisory = True
            self.is_required = False
            self.is_critical = False
            self.score_enabled = False
            self.gate_enabled = False
            self.contribution_weight = 0
        return self


class CreateRulesetRequest(BaseModel):
    """Payload to create a new ruleset."""

    asset_id: UUID
    name: str = Field(..., min_length=1, max_length=255)
    rules: list[CreateQualityRuleInput] = Field(default_factory=list)


class QualityRuleResponse(BaseModel):
    """Quality Rule response schema."""

    model_config = ConfigDict(from_attributes=True)

    rule_id: UUID
    rule_code: str
    dimension: str
    rule_type: str
    parameters: dict[str, Any]
    null_policy: str
    is_required: bool
    is_critical: bool
    gate_enabled: bool
    score_enabled: bool
    contribution_weight: float
    acceptance_threshold: float | None = None
    is_advisory: bool


class RulesetResponse(BaseModel):
    """Ruleset response schema."""

    model_config = ConfigDict(from_attributes=True)

    ruleset_id: UUID
    tenant_id: UUID
    asset_id: UUID
    name: str
    status: str
    current_version: int
    created_by: UUID
    created_at: datetime
    rules: list[QualityRuleResponse] = Field(default_factory=list)


class SubmitRulesetRequest(BaseModel):
    """Payload to submit ruleset revision for approval."""

    notes: str | None = None


class ApproveRulesetRequest(BaseModel):
    """Payload to approve ruleset revision."""

    approval_notes: str | None = None
