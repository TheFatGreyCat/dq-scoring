from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from dq_core.models import DatasetColumn, DatasetRecord, DatasetRuleBinding, DatasetVersion, RuleTemplate, ScoringPolicy
from profiling.config import load_config
from rules_engine.config import load_rules
from scoring.config import load_scoring_config


def build_seed_plan(root: str | Path, dataset_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    base = Path(root)
    datasets: list[DatasetRecord] = []
    versions: list[DatasetVersion] = []
    columns: list[DatasetColumn] = []
    templates_by_key: dict[tuple[str, str, str, str], RuleTemplate] = {}
    bindings: list[DatasetRuleBinding] = []
    policies: list[ScoringPolicy] = []

    for dataset_id in dataset_ids:
        artifact_name = _artifact_name(dataset_id)
        config = load_config(base / "data" / "configs" / f"{artifact_name}.yaml")
        rules = load_rules(base / "data" / "rules" / f"{artifact_name}_rules.yaml")
        scoring = load_scoring_config(base / "data" / "scoring" / f"{artifact_name}_scoring.yaml")
        dataset_version_id = f"DV-{config.dataset_id}-legacy"
        datasets.append(DatasetRecord(config.dataset_id, config.dataset_name, config.dataset_type, config.source_type, config.storage_path))
        versions.append(DatasetVersion(dataset_version_id, config.dataset_id, "legacy", _fingerprint(base / config.storage_path)))
        for index, (column_name, spec) in enumerate(config.declared_schema.items(), start=1):
            columns.append(
                DatasetColumn(
                    dataset_version_id=dataset_version_id,
                    column_name=column_name,
                    ordinal_position=index,
                    declared_data_type=spec.get("data_type"),
                    nullable=bool(spec.get("nullable", True)),
                    is_business_key=column_name in config.business_key,
                    is_cde=column_name in config.cde_fields,
                    is_mandatory=column_name in config.mandatory_fields,
                    is_identifier=column_name in config.primary_key or column_name in config.business_key,
                    is_timestamp=column_name == config.timestamp_column,
                )
            )

        for rule in rules:
            key = (dataset_id, rule.rule_type, rule.dimension or "", rule.target_column or "")
            template = templates_by_key.get(key)
            if template is None:
                template = _template_from_legacy_rule(dataset_id, rule)
                templates_by_key[key] = template
            bindings.append(
                DatasetRuleBinding(
                    binding_id=f"BR-{rule.rule_id}",
                    dataset_version_id=dataset_version_id,
                    rule_template_id=template.rule_template_id,
                    target_columns=[rule.target_column] if rule.target_column else list(rule.parameters.get("key_columns", [])),
                    parameters=rule.parameters,
                    acceptance_threshold=(rule.threshold / 100 if rule.threshold and rule.threshold > 1 else rule.threshold),
                    scoring_pass_threshold=rule.threshold,
                    severity=rule.severity,
                    backend="python" if rule.execution_backend == "pandas" else rule.execution_backend,
                    source="legacy_import",
                    score_enabled=rule.score_enabled,
                    gate_enabled=rule.severity == "critical",
                    scoring_method="gate_only" if not rule.score_enabled else "pass_ratio",
                )
            )

        policies.append(
            ScoringPolicy(
                scoring_policy_id=f"SP-{config.dataset_type}",
                dataset_type=config.dataset_type,
                dimension_weights=scoring.dimension_weights,
                quality_gate_pass_threshold=scoring.quality_gate_pass_threshold,
                quality_gate_warning_threshold=scoring.quality_gate_warning_threshold,
            )
        )

    return {
        "dataset": [item.to_record() for item in datasets],
        "dataset_version": [item.to_record() for item in versions],
        "dataset_column": [item.to_record() for item in columns],
        "rule_template": [item.to_record() for item in templates_by_key.values()],
        "dataset_rule_binding": [item.to_record() for item in bindings],
        "scoring_policy": [item.to_record() for item in _dedupe_policies(policies)],
    }


def _template_from_legacy_rule(dataset_id: str, rule: Any) -> RuleTemplate:
    dimension = "Accuracy Proxy" if rule.dimension == "Accuracy Proxy" else (rule.dimension or "Validity")
    category = "technical" if rule.rule_type in {"freshness", "full_row_duplicate"} else "general"
    dataset_slug = _slug(dataset_id)
    target_slug = _slug(rule.target_column or "dataset")
    dimension_slug = _slug(dimension)
    return RuleTemplate(
        rule_template_id=f"RT-{_stable_id(dataset_id, rule.rule_type, dimension, rule.target_column or 'dataset')}",
        rule_code=f"{rule.rule_type.upper()}_{dimension_slug}_{dataset_slug}_{target_slug}",
        rule_template_version=1,
        rule_category=category,
        dimension=dimension,
        management_scope="framework" if category == "general" else "dataset",
        target_scope="dataset" if not rule.target_column else "column",
        evaluation_scope="dataset_aggregate" if rule.rule_type == "freshness" else "record",
        operator=rule.rule_type,
        parameters=rule.parameters,
        null_policy="separate" if dimension == "Validity" else rule.null_policy,
        default_acceptance=(rule.threshold / 100 if rule.threshold and rule.threshold > 1 else rule.threshold),
        default_scoring_threshold=rule.threshold,
        default_severity=rule.severity,
        score_enabled=rule.score_enabled,
        gate_enabled=rule.severity == "critical",
        scoring_method="gate_only" if not rule.score_enabled else "pass_ratio",
        locked=category == "general",
    )


def _fingerprint(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_id(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:12].upper()


def _slug(value: str) -> str:
    result = []
    for char in value.upper():
        result.append(char if char.isalnum() else "_")
    slug = "".join(result)
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug.strip("_") or "ITEM"


def _artifact_name(dataset_id: str) -> str:
    if dataset_id == "amazon_products":
        return "amazon"
    return dataset_id


def _dedupe_policies(policies: list[ScoringPolicy]) -> list[ScoringPolicy]:
    result: dict[str, ScoringPolicy] = {}
    for policy in policies:
        result[policy.scoring_policy_id] = policy
    return list(result.values())
