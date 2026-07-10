from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from hashlib import sha1
from typing import Any, Iterable

from dq_core.models import DatasetRuleBinding, RuleRecommendation, RuleTemplate
from profiling.models import ColumnProfile, DatasetConfig
from profiling.semantic_detection import SemanticDetectionResult
from validation.planner import GX_SUPPORTED_OPERATORS

SCORE_WEIGHTS = {
    "name_match": 0.20,
    "type_match": 0.20,
    "semantic_match": 0.25,
    "profile_match": 0.20,
    "role_match": 0.10,
    "catalog_priority": 0.05,
}
REVIEW_STATUSES = {"suggested", "accepted", "rejected", "edited"}


@dataclass(frozen=True)
class ApplicabilityResult:
    applicable: bool
    matched_conditions: list[str]
    failed_conditions: list[str]
    warnings: list[str]
    exclusion_reason: str | None = None

    @property
    def reason(self) -> str:
        if self.exclusion_reason:
            return self.exclusion_reason
        if self.failed_conditions:
            return "; ".join(self.failed_conditions)
        return "; ".join(self.matched_conditions) if self.matched_conditions else "catalog candidate"


def default_rule_templates() -> list[RuleTemplate]:
    return [
        _template("RT-COMP-NOT-NULL", "NOT_NULL", "Not null", "completeness", "Completeness", "general", "not_null", {"mandatory": True}, null_policy="fail", severity="high", threshold=99, gate=True, conflict="mandatory_presence", priority=96),
        _template("RT-COMP-NOT-BLANK", "NOT_BLANK_MANDATORY", "Mandatory not blank", "completeness", "Completeness", "general", "not_blank", {"mandatory": True}, null_policy="fail", severity="high", threshold=99, gate=True, conflict="mandatory_presence", priority=100),
        _template("RT-COMP-MIN-RATIO", "MIN_COMPLETENESS_RATIO", "Minimum completeness ratio", "completeness", "Completeness", "general", "not_blank", {"cde": True}, null_policy="fail", severity="medium", threshold=95, priority=78, validation_only=True),
        _template("RT-COMP-CONDITIONAL", "CONDITIONAL_REQUIRED", "Conditionally required", "completeness", "Completeness", "business", "conditional_required", {"required_review": True}, target_scope="column", backend=("python",), null_policy="not_applicable", severity="high", threshold=95, priority=68, review=True, lifecycle="tested"),
        _template("RT-VALI-TYPE", "TYPE_VALIDITY", "Type validity", "validity", "Validity", "technical", "type_check", {"has_declared_type": True}, null_policy="separate", severity="medium", threshold=98, priority=75),
        _template("RT-VALI-EMAIL", "EMAIL_FORMAT", "Email format", "validity", "Validity", "general", "regex", {"semantic_type": "email"}, parameters={"pattern": r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}$"}, null_policy="separate", severity="high", threshold=98, priority=95),
        _template("RT-VALI-PHONE-10", "PHONE_TEN_DIGITS", "Phone has ten digits", "validity", "Validity", "general", "regex", {"semantic_type": "phone"}, parameters={"pattern": r"^\\d{10}$"}, null_policy="separate", severity="high", threshold=98, priority=88),
        _template("RT-VALI-DOMAIN", "ALLOWED_DOMAIN", "Allowed domain", "validity", "Validity", "business", "domain", {"semantic_type": "category"}, parameters={"values": []}, null_policy="separate", severity="medium", threshold=98, priority=72, review=True),
        _template("RT-VALI-NUMERIC-RANGE", "NUMERIC_RANGE", "Numeric range", "validity", "Validity", "general", "range", {"numeric": True}, parameters={"min_value": 0, "value_format": "number"}, null_policy="separate", severity="medium", threshold=95, priority=74, exclusions={"semantic_types": ["phone", "identifier", "datetime"]}),
        _template("RT-VALI-STRING-LENGTH", "STRING_LENGTH", "String length", "validity", "Validity", "general", "length", {"string_like": True}, parameters={"min_length": 1}, null_policy="separate", severity="low", threshold=95, priority=58),
        _template("RT-VALI-DATE-FORMAT", "DATE_FORMAT", "Date parseable", "validity", "Validity", "general", "type_check", {"semantic_type": "datetime"}, parameters={"expected_type": "datetime"}, null_policy="separate", severity="medium", threshold=98, priority=82),
        _template("RT-TIME-NOT-FUTURE", "DATETIME_NOT_FUTURE", "Datetime not future", "timeliness", "Timeliness", "technical", "not_future", {"semantic_type": "datetime"}, null_policy="separate", severity="medium", threshold=99, priority=80, locked=False),
        _template("RT-VALI-BOOLEAN", "BOOLEAN_DOMAIN", "Boolean domain", "validity", "Validity", "general", "domain", {"inferred_type": "boolean"}, parameters={"values": ["true", "false", "0", "1", "yes", "no"]}, null_policy="separate", severity="low", threshold=99, priority=55),
        _template("RT-UNIQ-IDENTIFIER", "IDENTIFIER_UNIQUE", "Identifier unique", "uniqueness", "Uniqueness", "general", "uniqueness", {"semantic_type": "identifier"}, null_policy="ignore", severity="critical", threshold=99, gate=True, priority=96, exclusions={"column_name_patterns": ["*type_id", "*category_id"], "semantic_types": ["category"]}),
        _template("RT-UNIQ-COMPOSITE", "COMPOSITE_UNIQUE", "Composite key unique", "uniqueness", "Uniqueness", "business", "composite_uniqueness", {"business_key": True}, target_scope="multiple_columns", backend=("python",), null_policy="ignore", severity="critical", threshold=99, gate=True, priority=76, review=True),
        _template("RT-UNIQ-FULL-ROW", "FULL_ROW_DUPLICATE", "Full row duplicate", "uniqueness", "Uniqueness", "technical", "full_row_duplicate", {"dataset_level": True}, target_scope="dataset", backend=("python",), null_policy="ignore", severity="medium", threshold=99, priority=50, review=True),
        _template("RT-UNIQ-DUP-RATIO", "DUPLICATE_RATIO_LIMIT", "Duplicate ratio limit", "uniqueness", "Uniqueness", "technical", "full_row_duplicate", {"dataset_level": True}, target_scope="dataset", backend=("python",), null_policy="ignore", severity="medium", threshold=99, priority=48, validation_only=True, review=True),
        _template("RT-CONS-START-END", "START_BEFORE_END", "Start before end", "consistency", "Consistency", "business", "comparison", {"relation_type": "start_end"}, target_scope="multiple_columns", backend=("python",), parameters={"operator": "lte"}, null_policy="not_applicable", severity="high", threshold=99, priority=70, review=True),
        _template("RT-CONS-CREATED-UPDATED", "CREATED_BEFORE_UPDATED", "Created before updated", "consistency", "Consistency", "technical", "comparison", {"relation_type": "created_updated"}, target_scope="multiple_columns", backend=("python",), parameters={"operator": "lte"}, null_policy="not_applicable", severity="medium", threshold=99, priority=62, review=True),
        _template("RT-CONS-TOTAL-AMOUNT", "TOTAL_AMOUNT_CONSISTENCY", "Total amount consistency", "consistency", "Consistency", "business", "comparison", {"relation_type": "quantity_price_total"}, target_scope="multiple_columns", backend=("python",), parameters={"operator": "eq", "tolerance": 0.01}, null_policy="not_applicable", severity="high", threshold=99, priority=85, review=True),
        _template("RT-ACCU-AMOUNT-NONNEG", "AMOUNT_NON_NEGATIVE", "Amount non-negative", "plausibility", "Accuracy Proxy", "business", "range", {"semantic_type": "amount"}, parameters={"min_value": 0, "value_format": "numeric"}, null_policy="ignore", severity="medium", threshold=95, priority=86, locked=False),
        _template("RT-ACCU-POS-QUANTITY", "POSITIVE_QUANTITY", "Positive quantity", "plausibility", "Accuracy Proxy", "business", "range", {"semantic_type": "quantity"}, parameters={"min_value": 1, "value_format": "number"}, null_policy="ignore", severity="medium", threshold=95, priority=78, review=True),
        _template("RT-ACCU-PERCENT", "PERCENTAGE_RANGE", "Percentage range", "plausibility", "Accuracy Proxy", "business", "range", {"name_pattern": "*percent*"}, parameters={"min_value": 0, "max_value": 100, "value_format": "percentage"}, null_policy="ignore", severity="medium", threshold=95, priority=70, review=True),
        _template("RT-SCHEMA-REQUIRED", "REQUIRED_COLUMNS", "Required columns", "schema", "Consistency", "technical", "schema_required_columns", {"dataset_level": True}, target_scope="dataset", backend=("python",), null_policy="not_applicable", severity="high", threshold=100, priority=60, lifecycle="draft", review=True),
    ]


def recommend_rules(
    column_profiles: list[ColumnProfile],
    semantics: list[SemanticDetectionResult],
    config: DatasetConfig,
    templates: list[RuleTemplate] | None = None,
    *,
    recommendation_run_id: str | None = None,
) -> list[RuleRecommendation]:
    template_list = [item for item in (templates or default_rule_templates()) if item.active and item.lifecycle_status in {"tested", "active"}]
    semantics_by_column = {item.column_name: item for item in semantics}
    candidates: list[RuleRecommendation] = []
    for profile in column_profiles:
        semantic = semantics_by_column.get(profile.column_name)
        context = _context(profile, semantic, config)
        for template in template_list:
            if template.target_scope != "column":
                continue
            details = evaluate_applicability_details(template, context)
            if not details.applicable:
                continue
            components = _score_components(template, context, details)
            score = _weighted_score(components)
            recommendation_id = f"REC-{_stable_id(recommendation_run_id or 'preview', template.rule_template_id, profile.column_name)}"
            candidates.append(
                RuleRecommendation(
                    rule_template_id=template.rule_template_id,
                    target_columns=[profile.column_name],
                    reason=_reason_text(template, details, components),
                    confidence=score,
                    editable=not template.locked or bool(template.recommendation_metadata.get("requires_user_review")),
                    source="review_required" if _requires_review(template, details) else "framework_auto",
                    recommendation_id=recommendation_id,
                    recommendation_run_id=recommendation_run_id,
                    candidate_score=score,
                    score_components=components,
                    reason_json={"matched": details.matched_conditions, "warnings": details.warnings, "components": components},
                    suggested_parameters=template.parameters,
                    warnings=details.warnings,
                    review_status="suggested",
                )
            )
    candidates.extend(_multi_column_candidates(template_list, column_profiles, semantics_by_column, config, recommendation_run_id))
    return _rank_and_margin(_dedupe(candidates))


def evaluate_applicability(template: RuleTemplate, context: dict[str, Any]) -> tuple[bool, str, float]:
    details = evaluate_applicability_details(template, context)
    if not details.applicable:
        return False, details.reason, 0.0
    return True, details.reason, _weighted_score(_score_components(template, context, details))


def evaluate_applicability_details(template: RuleTemplate, context: dict[str, Any]) -> ApplicabilityResult:
    exclusion = _exclusion_reason(template, context)
    if exclusion:
        return ApplicabilityResult(False, [], [], [], exclusion)
    matched: list[str] = []
    failed: list[str] = []
    warnings: list[str] = []
    if template.backend_support and not any(_backend_ready(backend, template.operator) for backend in template.backend_support):
        failed.append("no supported backend")
    checks = template.applicability or {}
    for key, expected in checks.items():
        if key == "required_review":
            warnings.append("requires review")
            continue
        if key in {"dataset_level", "relation_type"}:
            matched.append(f"{key}={expected}")
            continue
        actual = context.get(key)
        if isinstance(expected, bool):
            actual = bool(actual)
        if _matches(actual, expected):
            matched.append(f"{key}={expected}")
        else:
            failed.append(f"{key} expected {expected}, got {actual}")
    if context.get("metric_scope") == "sampled":
        warnings.append("profile metric is sampled")
    if template.target_scope == "column" and not matched:
        failed.append("no column applicability evidence")
    return ApplicabilityResult(not failed, matched, failed, warnings)


def binding_from_recommendation(
    recommendation: RuleRecommendation,
    template: RuleTemplate,
    dataset_version_id: str,
) -> DatasetRuleBinding:
    backend = _preferred_backend(template)
    return DatasetRuleBinding(
        binding_id=f"BR-{_stable_id(dataset_version_id, template.rule_template_id, ','.join(recommendation.target_columns))}",
        dataset_version_id=dataset_version_id,
        rule_template_id=template.rule_template_id,
        target_columns=recommendation.target_columns,
        parameters=recommendation.suggested_parameters or template.parameters,
        acceptance_threshold=template.default_acceptance,
        scoring_pass_threshold=template.default_scoring_threshold,
        severity=template.default_severity,
        backend=backend,
        source=recommendation.source,
        recommendation_confidence=recommendation.candidate_score if recommendation.candidate_score is not None else recommendation.confidence,
        score_enabled=template.score_enabled and not template.validation_only,
        gate_enabled=template.gate_enabled,
        scoring_method=template.scoring_method,
        conflict_group=template.conflict_group,
        primary_scoring_rule=template.primary_scoring_rule,
        validation_only=template.validation_only,
    )


def can_auto_bind_recommendation(recommendation: RuleRecommendation, template: RuleTemplate) -> bool:
    if recommendation.source == "review_required":
        return False
    if recommendation.ambiguity_status == "ambiguous":
        return False
    if any("review" in warning.lower() for warning in recommendation.warnings):
        return False
    metadata = template.recommendation_metadata or {}
    if bool(metadata.get("requires_user_review")):
        return False
    if "auto_bind_allowed" in metadata and not bool(metadata.get("auto_bind_allowed")):
        return False
    return True


def catalog_revision(templates: Iterable[RuleTemplate] | None = None) -> str:
    template_list = templates or default_rule_templates()
    payload = "|".join(f"{item.rule_code}:{item.revision}:{item.lifecycle_status}" for item in sorted(template_list, key=lambda value: value.rule_code))
    return sha1(payload.encode("utf-8")).hexdigest()[:12]


def catalog_inventory(templates: Iterable[RuleTemplate] | None = None) -> list[dict[str, Any]]:
    return [
        {
            "rule_code": item.rule_code,
            "revision": item.revision,
            "family": item.family,
            "dimension": item.dimension,
            "operator": item.operator,
            "lifecycle_status": item.lifecycle_status,
            "backend_support": item.backend_support,
            "active": item.active,
        }
        for item in (templates or default_rule_templates())
    ]


def backend_coverage_matrix(templates: Iterable[RuleTemplate] | None = None) -> list[dict[str, Any]]:
    rows = []
    for item in templates or default_rule_templates():
        gx = "gx" in item.backend_support or "gx_pandas" in item.backend_support
        python = "python" in item.backend_support
        rows.append({"rule_code": item.rule_code, "gx": gx and item.operator in GX_SUPPORTED_OPERATORS, "python": python, "status": "ready" if item.lifecycle_status in {"tested", "active"} and item.backend_support else "draft"})
    return rows


def validate_catalog(templates: Iterable[RuleTemplate] | None = None) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    seen: set[tuple[str, int]] = set()
    for item in templates or default_rule_templates():
        key = (item.rule_code, item.revision)
        if key in seen:
            issues.append({"rule_code": item.rule_code, "issue": "duplicate revision"})
        seen.add(key)
        for field in ("rule_name", "family", "backend_support", "parameters_schema", "recommendation_metadata", "description_for_recommendation"):
            value = getattr(item, field)
            if value is None or value == "" or value == []:
                issues.append({"rule_code": item.rule_code, "issue": f"missing {field}"})
        if item.lifecycle_status == "active" and not item.backend_support:
            issues.append({"rule_code": item.rule_code, "issue": "active rule has no backend"})
    return issues


def _template(
    template_id: str,
    code: str,
    name: str,
    family: str,
    dimension: str,
    category: str,
    operator: str,
    applicability: dict[str, Any],
    *,
    target_scope: str = "column",
    backend: tuple[str, ...] | None = None,
    parameters: dict[str, Any] | None = None,
    null_policy: str = "separate",
    severity: str = "medium",
    threshold: float | None = None,
    gate: bool = False,
    conflict: str | None = None,
    priority: int = 50,
    review: bool = False,
    lifecycle: str = "active",
    locked: bool = True,
    validation_only: bool = False,
    exclusions: dict[str, Any] | None = None,
) -> RuleTemplate:
    backend_support = list(backend or (("gx",) if operator in GX_SUPPORTED_OPERATORS else ("python",)))
    return RuleTemplate(
        rule_template_id=template_id,
        rule_code=code,
        rule_template_version=1,
        rule_category=category,
        dimension=dimension,
        management_scope="framework" if category in {"general", "technical"} else "dataset",
        target_scope=target_scope,
        evaluation_scope="dataset_aggregate" if target_scope == "dataset" else ("cross_field" if target_scope == "multiple_columns" else "record"),
        operator=operator,
        applicability=applicability,
        parameters=parameters or {},
        null_policy=null_policy,
        default_acceptance=threshold,
        default_scoring_threshold=threshold,
        default_severity=severity,
        gate_enabled=gate,
        locked=locked,
        conflict_group=conflict,
        validation_only=validation_only,
        rule_name=name,
        family=family,
        required_columns=[],
        backend_support=backend_support,
        exclusions=exclusions or {},
        parameters_schema=_parameter_schema(parameters or {}),
        recommendation_metadata={"priority": priority, "requires_user_review": review, "auto_bind_allowed": not review},
        lifecycle_status=lifecycle,
        revision=1,
        description_for_recommendation=name,
    )


def _context(profile: ColumnProfile, semantic: SemanticDetectionResult | None, config: DatasetConfig) -> dict[str, Any]:
    inferred = profile.inferred_data_type
    return {
        "column_name": profile.column_name,
        "dataset_type": config.dataset_type,
        "semantic_type": semantic.semantic_type if semantic else "unknown",
        "semantic_confidence": semantic.confidence if semantic else 0.0,
        "inferred_type": inferred,
        "mandatory": profile.column_name in config.mandatory_fields,
        "business_key": profile.column_name in config.business_key or profile.column_name in config.primary_key,
        "cde": profile.column_name in config.cde_fields,
        "identifier": semantic.semantic_type == "identifier" if semantic else False,
        "numeric": inferred in {"integer", "float", "numeric_string", "integer_like_string"},
        "string_like": inferred in {"string", "mixed", "integer_like_string"},
        "has_declared_type": bool(profile.declared_data_type),
        "metric_scope": profile.metric_scope,
        "profile": profile,
    }


def _multi_column_candidates(templates: list[RuleTemplate], profiles: list[ColumnProfile], semantics: dict[str, SemanticDetectionResult], config: DatasetConfig, run_id: str | None) -> list[RuleRecommendation]:
    columns = [profile.column_name for profile in profiles]
    lowered = {column: column.lower() for column in columns}
    candidates: list[RuleRecommendation] = []
    relations = [
        ("quantity_price_total", ["quantity", "price", "total"]),
        ("start_end", ["start", "end"]),
        ("created_updated", ["created", "updated"]),
    ]
    for template in templates:
        if template.target_scope != "multiple_columns":
            continue
        relation = template.applicability.get("relation_type")
        terms = next((items for name, items in relations if name == relation), [])
        matched = []
        for term in terms:
            match = next((column for column, lower in lowered.items() if term in lower), None)
            if match:
                matched.append(match)
        if len(set(matched)) < len(terms):
            continue
        score = 0.70 + float(template.recommendation_metadata.get("priority", 50)) / 1000
        rec_id = f"REC-{_stable_id(run_id or 'preview', template.rule_template_id, ','.join(matched))}"
        candidates.append(RuleRecommendation(template.rule_template_id, list(dict.fromkeys(matched)), f"matched relation {relation}", round(min(score, 0.99), 6), True, "review_required", rec_id, run_id, round(min(score, 0.99), 6), {"name_match": 1.0, "type_match": 0.5, "semantic_match": 0.5, "profile_match": 0.5, "role_match": 0.5, "catalog_priority": float(template.recommendation_metadata.get("priority", 50)) / 100}, {"matched": [f"relation_type={relation}"], "warnings": ["business rule requires review"]}, None, None, "ambiguous", "suggested", template.parameters, ["business rule requires review"]))
    return candidates


def _score_components(template: RuleTemplate, context: dict[str, Any], details: ApplicabilityResult) -> dict[str, float]:
    name = str(context.get("column_name", "")).lower()
    semantic = context.get("semantic_type")
    inferred = context.get("inferred_type")
    priority = float(template.recommendation_metadata.get("priority", 50)) / 100
    return {
        "name_match": _name_score(template, name),
        "type_match": _type_score(template, inferred),
        "semantic_match": 1.0 if template.applicability.get("semantic_type") == semantic else (0.6 if semantic and semantic != "unknown" else 0.2),
        "profile_match": 0.6 if context.get("metric_scope") == "sampled" else 1.0,
        "role_match": 1.0 if any(context.get(role) for role in ("mandatory", "business_key", "cde", "identifier")) else 0.4,
        "catalog_priority": max(0.0, min(priority, 1.0)),
    }


def _weighted_score(components: dict[str, float]) -> float:
    return round(sum(components[key] * SCORE_WEIGHTS[key] for key in SCORE_WEIGHTS), 6)


def _rank_and_margin(items: list[RuleRecommendation]) -> list[RuleRecommendation]:
    grouped: dict[tuple[str, ...], list[RuleRecommendation]] = {}
    for item in items:
        grouped.setdefault(tuple(item.target_columns), []).append(item)
    result: list[RuleRecommendation] = []
    for group in grouped.values():
        ordered = sorted(group, key=lambda item: (item.candidate_score if item.candidate_score is not None else item.confidence), reverse=True)
        for index, item in enumerate(ordered, start=1):
            score = item.candidate_score if item.candidate_score is not None else item.confidence
            second = ordered[1].candidate_score if len(ordered) > 1 and ordered[1].candidate_score is not None else (ordered[1].confidence if len(ordered) > 1 else 0.0)
            margin = round(score - second, 6) if index == 1 else None
            ambiguity = _ambiguity(margin, item.warnings, item.source)
            result.append(_replace_recommendation(item, rank=index, score_margin=margin, ambiguity_status=ambiguity))
    return sorted(result, key=lambda item: (item.target_columns, item.rank or 999, item.rule_template_id))


def _replace_recommendation(item: RuleRecommendation, **updates: Any) -> RuleRecommendation:
    data = item.to_record()
    data.update(updates)
    return RuleRecommendation(**data)


def _ambiguity(margin: float | None, warnings: list[str], source: str) -> str:
    if source == "review_required" or warnings:
        return "ambiguous"
    if margin is None or margin >= 0.20:
        return "clear"
    if margin >= 0.10:
        return "moderate"
    return "ambiguous"


def _reason_text(template: RuleTemplate, details: ApplicabilityResult, components: dict[str, float]) -> str:
    return f"Recommend {template.rule_code}: {details.reason}; score={_weighted_score(components):.2f}"


def _requires_review(template: RuleTemplate, details: ApplicabilityResult) -> bool:
    return template.rule_category == "business" or template.target_scope != "column" or bool(template.recommendation_metadata.get("requires_user_review")) or bool(details.warnings)


def _name_score(template: RuleTemplate, column_name: str) -> float:
    tokens = set(re.split(r"[_\W]+", column_name))
    code_tokens = set(template.rule_code.lower().split("_"))
    if tokens & code_tokens:
        return 1.0
    if any(token in column_name for token in code_tokens):
        return 0.8
    return 0.3


def _type_score(template: RuleTemplate, inferred: Any) -> float:
    expected = template.applicability.get("inferred_type")
    if expected is None:
        return 0.7
    return 1.0 if _matches(inferred, expected) else 0.0


def _matches(actual: Any, expected: Any) -> bool:
    if isinstance(expected, (list, tuple, set)):
        return actual in expected
    if isinstance(expected, str) and "*" in expected:
        return fnmatch.fnmatch(str(actual), expected)
    return actual == expected


def _exclusion_reason(template: RuleTemplate, context: dict[str, Any]) -> str | None:
    exclusions = template.exclusions or {}
    column_name = str(context.get("column_name") or "")
    for pattern in exclusions.get("column_name_patterns", []):
        if fnmatch.fnmatch(column_name.lower(), str(pattern).lower()):
            return f"excluded by column pattern {pattern}"
    if context.get("semantic_type") in set(exclusions.get("semantic_types", [])):
        return f"excluded by semantic type {context.get('semantic_type')}"
    if context.get("dataset_type") in set(exclusions.get("dataset_types", [])):
        return f"excluded by dataset type {context.get('dataset_type')}"
    return None


def _backend_ready(backend: str, operator: str) -> bool:
    if backend in {"gx", "gx_pandas"}:
        return operator in GX_SUPPORTED_OPERATORS
    return backend == "python"


def _preferred_backend(template: RuleTemplate) -> str:
    if any(backend in {"gx", "gx_pandas"} for backend in template.backend_support) and template.operator in GX_SUPPORTED_OPERATORS:
        return "gx"
    return "python"


def _parameter_schema(parameters: dict[str, Any]) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    for key, value in parameters.items():
        if isinstance(value, bool):
            kind = "boolean"
        elif isinstance(value, (int, float)):
            kind = "number"
        elif isinstance(value, list):
            kind = "array"
        elif isinstance(value, dict):
            kind = "object"
        else:
            kind = "string"
        properties[key] = {"type": kind}
    return {"type": "object", "properties": properties, "required": []}


def _dedupe(recommendations: list[RuleRecommendation]) -> list[RuleRecommendation]:
    seen: set[tuple[str, tuple[str, ...]]] = set()
    result: list[RuleRecommendation] = []
    for item in recommendations:
        key = (item.rule_template_id, tuple(item.target_columns))
        if key not in seen:
            result.append(item)
            seen.add(key)
    return result


def _stable_id(*parts: str) -> str:
    return sha1("|".join(parts).encode("utf-8")).hexdigest()[:12].upper()
