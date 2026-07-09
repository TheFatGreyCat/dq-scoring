from __future__ import annotations

from hashlib import sha1
from typing import Any

from dq_core.models import DatasetRuleBinding, RuleRecommendation, RuleTemplate
from profiling.models import ColumnProfile, DatasetConfig
from profiling.semantic_detection import SemanticDetectionResult


def default_rule_templates() -> list[RuleTemplate]:
    return [
        RuleTemplate(
            rule_template_id="RT-COMP-NOT-BLANK",
            rule_code="NOT_BLANK_MANDATORY",
            rule_template_version=1,
            rule_category="general",
            dimension="Completeness",
            management_scope="framework",
            target_scope="column",
            evaluation_scope="record",
            operator="not_blank",
            applicability={"mandatory": True},
            null_policy="fail",
            default_acceptance=0.99,
            default_scoring_threshold=99,
            default_severity="high",
            gate_enabled=True,
        ),
        RuleTemplate(
            rule_template_id="RT-VALI-EMAIL",
            rule_code="EMAIL_FORMAT",
            rule_template_version=1,
            rule_category="general",
            dimension="Validity",
            management_scope="framework",
            target_scope="column",
            evaluation_scope="record",
            operator="regex",
            applicability={"semantic_type": "email"},
            parameters={"pattern": r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}$"},
            null_policy="separate",
            default_acceptance=0.98,
            default_scoring_threshold=98,
            default_severity="high",
        ),
        RuleTemplate(
            rule_template_id="RT-VALI-PHONE-10",
            rule_code="PHONE_TEN_DIGITS",
            rule_template_version=1,
            rule_category="general",
            dimension="Validity",
            management_scope="framework",
            target_scope="column",
            evaluation_scope="record",
            operator="regex",
            applicability={"semantic_type": "phone", "inferred_type": "string"},
            parameters={"pattern": r"^\\d{10}$"},
            null_policy="separate",
            default_acceptance=0.98,
            default_scoring_threshold=98,
            default_severity="high",
        ),
        RuleTemplate(
            rule_template_id="RT-UNIQ-IDENTIFIER",
            rule_code="IDENTIFIER_UNIQUE",
            rule_template_version=1,
            rule_category="general",
            dimension="Uniqueness",
            management_scope="framework",
            target_scope="column",
            evaluation_scope="record",
            operator="uniqueness",
            applicability={"semantic_type": "identifier"},
            null_policy="ignore",
            default_acceptance=0.99,
            default_scoring_threshold=99,
            default_severity="critical",
            gate_enabled=True,
        ),
        RuleTemplate(
            rule_template_id="RT-ACCU-AMOUNT-NONNEG",
            rule_code="AMOUNT_NON_NEGATIVE",
            rule_template_version=1,
            rule_category="business",
            dimension="Accuracy Proxy",
            management_scope="dataset",
            target_scope="column",
            evaluation_scope="record",
            operator="range",
            applicability={"semantic_type": "amount"},
            parameters={"min_value": 0, "value_format": "numeric"},
            null_policy="ignore",
            accuracy_mode="plausibility_proxy",
            default_acceptance=0.95,
            default_scoring_threshold=95,
            default_severity="medium",
            locked=False,
        ),
        RuleTemplate(
            rule_template_id="RT-TIME-NOT-FUTURE",
            rule_code="DATETIME_NOT_FUTURE",
            rule_template_version=1,
            rule_category="technical",
            dimension="Timeliness",
            management_scope="dataset",
            target_scope="column",
            evaluation_scope="record",
            operator="not_future",
            applicability={"semantic_type": "datetime"},
            null_policy="separate",
            default_acceptance=0.99,
            default_scoring_threshold=99,
            default_severity="medium",
            locked=False,
        ),
    ]


def recommend_rules(
    column_profiles: list[ColumnProfile],
    semantics: list[SemanticDetectionResult],
    config: DatasetConfig,
    templates: list[RuleTemplate] | None = None,
) -> list[RuleRecommendation]:
    template_list = templates or default_rule_templates()
    semantics_by_column = {item.column_name: item for item in semantics}
    recommendations: list[RuleRecommendation] = []
    for profile in column_profiles:
        semantic = semantics_by_column.get(profile.column_name)
        context = _context(profile, semantic, config)
        for template in template_list:
            applicable, reason, confidence = evaluate_applicability(template, context)
            if applicable:
                recommendations.append(
                    RuleRecommendation(
                        rule_template_id=template.rule_template_id,
                        target_columns=[profile.column_name],
                        reason=reason,
                        confidence=confidence,
                        editable=not template.locked,
                        source="framework_auto" if template.rule_category == "general" else "review_required",
                    )
                )
    return _dedupe(recommendations)


def evaluate_applicability(template: RuleTemplate, context: dict[str, Any]) -> tuple[bool, str, float]:
    checks = template.applicability or {}
    if not checks:
        return True, "template has no applicability restrictions", 0.50
    for key, expected in checks.items():
        actual = bool(context.get(key)) if isinstance(expected, bool) else context.get(key)
        if actual != expected:
            return False, f"{key} does not match {expected}", 0.0
    confidence = float(context.get("semantic_confidence") or 0.75)
    if checks.get("mandatory"):
        confidence = max(confidence, 0.90)
    return True, "; ".join(f"{k}={v}" for k, v in checks.items()), round(min(confidence, 0.99), 6)


def binding_from_recommendation(
    recommendation: RuleRecommendation,
    template: RuleTemplate,
    dataset_version_id: str,
) -> DatasetRuleBinding:
    return DatasetRuleBinding(
        binding_id=f"BR-{_stable_id(dataset_version_id, template.rule_template_id, ','.join(recommendation.target_columns))}",
        dataset_version_id=dataset_version_id,
        rule_template_id=template.rule_template_id,
        target_columns=recommendation.target_columns,
        parameters=template.parameters,
        acceptance_threshold=template.default_acceptance,
        scoring_pass_threshold=template.default_scoring_threshold,
        severity=template.default_severity,
        backend="gx" if template.operator in {"not_blank", "regex", "domain", "range", "length", "type_check", "uniqueness"} else "python",
        source=recommendation.source,
        recommendation_confidence=recommendation.confidence,
        score_enabled=template.score_enabled,
        gate_enabled=template.gate_enabled,
        scoring_method=template.scoring_method,
    )


def _context(profile: ColumnProfile, semantic: SemanticDetectionResult | None, config: DatasetConfig) -> dict[str, Any]:
    return {
        "column_name": profile.column_name,
        "semantic_type": semantic.semantic_type if semantic else "unknown",
        "semantic_confidence": semantic.confidence if semantic else 0.0,
        "inferred_type": profile.inferred_data_type,
        "mandatory": profile.column_name in config.mandatory_fields,
        "business_key": profile.column_name in config.business_key or profile.column_name in config.primary_key,
        "cde": profile.column_name in config.cde_fields,
        "identifier": semantic.semantic_type == "identifier" if semantic else False,
    }


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
