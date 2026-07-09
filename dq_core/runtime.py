from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

from dq_core.models import CanonicalValidationResult, DatasetColumn, DatasetRuleBinding, PipelineLog, RuleRecommendation
from persistence.repository import DqPostgresRepository
from profiling.column_profile import profile_columns
from profiling.dataset_profile import profile_dataset
from profiling.loading import load_dataset
from profiling.metrics import build_profile_metrics
from profiling.models import DatasetConfig, ProfileResult, ProfilingRun
from profiling.sampling import sample_dataset
from profiling.schema_profile import profile_schema
from profiling.semantic_detection import detect_semantics
from rules_engine.catalog import binding_from_recommendation, default_rule_templates, recommend_rules
from rules_engine.evaluators import RuleEvaluator, not_measured_result
from rules_engine.models import RuleConfig, iso
from scoring.v2 import calculate_scores as calculate_scores_v2
from validation.canonical import canonicalize_rule_evaluation
from validation.gx_runtime import GxRuntimeEvaluator
from validation.planner import ruleset_hash


class DqRuntime:
    def __init__(self, repository: DqPostgresRepository | None = None) -> None:
        self.repository = repository or DqPostgresRepository()

    def register_dataset(self, csv_path: str | Path, metadata: dict[str, Any]) -> str:
        content = Path(csv_path).read_bytes()
        bundle = self.repository.register_dataset(content, metadata)
        self._log(bundle.version.dataset_version_id, "register_dataset", "success", f"Registered {bundle.dataset.dataset_id}")
        return bundle.version.dataset_version_id

    def profile_dataset(self, dataset_version_id: str) -> str:
        started_at = perf_counter()
        bundle = self.repository.load_dataset_bundle(dataset_version_id)
        config = dataset_config_from_bundle(bundle)
        dataframe = load_dataset(config)
        profiled_df, sampling = sample_dataset(dataframe, config)
        schema = profile_schema(profiled_df, config)
        columns = profile_columns(profiled_df, config, run_id=f"PRUN-{uuid4().hex[:12].upper()}")
        dataset_profile = profile_dataset(profiled_df, config, run_id=columns[0].run_id if columns else f"PRUN-{uuid4().hex[:12].upper()}", started_at=started_at)
        run = ProfilingRun(
            run_id=dataset_profile.run_id,
            dataset_id=config.dataset_id,
            dataset_version=dataset_version_id,
            run_timestamp=dataset_profile.profiling_timestamp,
            execution_engine="v2_pandas_profile",
            source_path=config.storage_path,
            schema_version=None,
            sampling_method=sampling.sampling_method,
            is_sampled=sampling.is_sampled,
            sample_fraction=sampling.sample_fraction,
            sample_size=sampling.sample_size,
            total_rows=sampling.total_rows,
            status="success",
        )
        result = ProfileResult(run, schema, dataset_profile, columns, [], [])
        semantics = {item.column_name: item for item in detect_semantics(columns)}
        updated_columns = [
            DatasetColumn(
                dataset_version_id=column.dataset_version_id,
                column_name=column.column_name,
                ordinal_position=column.ordinal_position,
                declared_data_type=column.declared_data_type,
                inferred_data_type=next((profile.inferred_data_type for profile in columns if profile.column_name == column.column_name), None),
                nullable=column.nullable,
                semantic_type=semantics.get(column.column_name).semantic_type if column.column_name in semantics else column.semantic_type,
                semantic_confidence=semantics.get(column.column_name).confidence if column.column_name in semantics else column.semantic_confidence,
                is_business_key=column.is_business_key,
                is_cde=column.is_cde,
                is_mandatory=column.is_mandatory,
                is_identifier=column.is_identifier,
                is_timestamp=column.is_timestamp,
            )
            for column in bundle.columns
        ]
        self.repository.save_dataset_bundle(bundle.dataset, bundle.version, updated_columns)
        self.repository.save_profile_result(dataset_version_id, result, build_profile_metrics(dataset_profile, columns))
        self._log(dataset_version_id, "profile_dataset", "success", f"Profiled {config.dataset_id}")
        return dataset_profile.run_id

    def recommend_rules(self, dataset_version_id: str) -> list[dict[str, Any]]:
        bundle = self.repository.load_dataset_bundle(dataset_version_id)
        config = dataset_config_from_bundle(bundle)
        dataframe = load_dataset(config)
        columns = profile_columns(dataframe, config, run_id=f"REC-{uuid4().hex[:12].upper()}")
        semantics = detect_semantics(columns)
        templates = default_rule_templates()
        self.repository.save_rule_templates(templates)
        recommendations = recommend_rules(columns, semantics, config, templates)
        self._log(dataset_version_id, "recommend_rules", "success", f"Generated {len(recommendations)} recommendations")
        return [item.to_record() for item in recommendations]

    def save_recommended_rule_bindings(self, dataset_version_id: str) -> str:
        templates = {item.rule_template_id: item for item in default_rule_templates()}
        recommendations = self.recommend_rules(dataset_version_id)
        bindings = [
            binding_from_recommendation(RuleRecommendation(**item), templates[item["rule_template_id"]], dataset_version_id).to_record()
            for item in recommendations
            if item["confidence"] >= 0.85
        ]
        return self.repository.save_rule_bindings(dataset_version_id, bindings, [])

    def save_rule_bindings(self, dataset_version_id: str, bindings: list[dict[str, Any]], exceptions: list[dict[str, Any]] | None = None) -> str:
        return self.repository.save_rule_bindings(dataset_version_id, bindings, exceptions or [])

    def run_validation(self, dataset_version_id: str) -> str:
        bundle = self.repository.load_dataset_bundle(dataset_version_id)
        config = dataset_config_from_bundle(bundle)
        dataframe = load_dataset(config)
        templates = {item.rule_template_id: item for item in self.repository.load_rule_templates()}
        bindings = self.repository.load_rule_bindings(dataset_version_id)
        hash_value = ruleset_hash(bindings, templates)
        validation_run_id = f"VRUN-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}"
        measurements = []
        summaries = []
        evaluator = RuleEvaluator()
        gx_evaluator = GxRuntimeEvaluator()
        for binding in bindings:
            template = templates[binding.rule_template_id]
            rule = rule_config_from_binding(config.dataset_id, binding, template)
            try:
                if binding.backend in {"gx", "gx_pandas"}:
                    measurement, summary = gx_evaluator.evaluate(
                        dataframe,
                        validation_run_id,
                        binding,
                        template.operator,
                        {**template.parameters, **binding.parameters},
                        null_policy=template.null_policy,
                    )
                else:
                    evaluation = evaluator.evaluate(dataframe, config, rule)
                    measurement, summary = canonicalize_rule_evaluation(validation_run_id, evaluation, binding, null_policy=template.null_policy)
            except Exception as exc:
                evaluation = not_measured_result(validation_run_id, rule, str(exc))
                measurement, summary = canonicalize_rule_evaluation(validation_run_id, evaluation, binding, null_policy=template.null_policy)
            measurements.append(measurement)
            summaries.append(summary)
        result = CanonicalValidationResult(validation_run_id, dataset_version_id, measurements, summaries)
        self.repository.save_validation_result(result, hash_value)
        self._log(dataset_version_id, "run_validation", "success", f"Validated {len(bindings)} bindings")
        return validation_run_id

    def calculate_score(self, validation_run_id: str, scoring_policy_id: str | None = None) -> str:
        validation = self.repository.load_validation_result(validation_run_id)
        bundle = self.repository.load_dataset_bundle(validation.dataset_version_id)
        bindings = {item.binding_id: item for item in self.repository.load_rule_bindings(validation.dataset_version_id, active_only=False)}
        templates = {item.rule_template_id: item for item in self.repository.load_rule_templates(active_only=False)}
        policy = self.repository.load_scoring_policy(scoring_policy_id, bundle.dataset.dataset_type)
        roles = {
            column.column_name: {
                role
                for role, enabled in {
                    "business_key": column.is_business_key,
                    "cde": column.is_cde,
                    "mandatory": column.is_mandatory,
                    "identifier": column.is_identifier,
                }.items()
                if enabled
            }
            for column in bundle.columns
        }
        result = calculate_scores_v2(validation, policy, bindings, templates, roles)
        self.repository.save_score_result(validation.dataset_version_id, result)
        self._log(validation.dataset_version_id, "calculate_score", "success", f"Score run {result.score_run_id}")
        return result.score_run_id

    def get_run_result(self, score_run_id: str | None = None) -> dict[str, Any]:
        rows = self.repository.list_dashboard_rows()
        if score_run_id:
            return {key: [row for row in value if row.get("score_run_id") == score_run_id] for key, value in rows.items()}
        return rows

    def get_pipeline_logs(self) -> list[dict[str, Any]]:
        return self.repository.list_dashboard_rows()["pipeline_log"]

    def _log(self, dataset_version_id: str | None, event_type: str, status: str, message: str) -> None:
        self.repository.save_pipeline_log(PipelineLog(f"LOG-{uuid4().hex[:12].upper()}", dataset_version_id, event_type, status, message))


def dataset_config_from_bundle(bundle: Any) -> DatasetConfig:
    columns = bundle.columns
    return DatasetConfig(
        dataset_id=bundle.dataset.dataset_id,
        dataset_name=bundle.dataset.dataset_name,
        dataset_type=bundle.dataset.dataset_type,
        source_type=bundle.dataset.source_type,
        storage_path=bundle.dataset.storage_path,
        declared_schema={
            column.column_name: {"data_type": column.declared_data_type or "string", "nullable": True if column.nullable is None else column.nullable}
            for column in columns
        },
        primary_key=[column.column_name for column in columns if column.is_identifier],
        business_key=[column.column_name for column in columns if column.is_business_key],
        mandatory_fields=[column.column_name for column in columns if column.is_mandatory],
        cde_fields=[column.column_name for column in columns if column.is_cde],
        timestamp_column=next((column.column_name for column in columns if column.is_timestamp), None),
    )


def rule_config_from_binding(dataset_id: str, binding: DatasetRuleBinding, template: Any) -> RuleConfig:
    target_column = binding.target_columns[0] if len(binding.target_columns) == 1 else None
    parameters = {**template.parameters, **binding.parameters}
    if len(binding.target_columns) > 1:
        parameters.setdefault("key_columns", binding.target_columns)
    return RuleConfig(
        rule_id=binding.binding_id,
        dataset_id=dataset_id,
        rule_type=template.operator,
        status=binding.status,
        score_enabled=binding.score_enabled,
        rule_name=template.rule_code,
        target_column=target_column,
        dimension=template.dimension,
        parameters=parameters,
        null_policy=template.null_policy,
        threshold=binding.scoring_pass_threshold or template.default_scoring_threshold,
        severity=binding.severity,
        execution_backend=binding.backend,
    )


def to_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=_json_default)


def _json_default(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    try:
        return asdict(value)
    except TypeError:
        return str(value)


