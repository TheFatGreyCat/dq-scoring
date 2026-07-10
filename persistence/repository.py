from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from dq_core.models import (
    CanonicalValidationResult,
    DatasetColumn,
    DatasetRecord,
    DatasetRuleBinding,
    DatasetVersion,
    MeasurementResult,
    PipelineLog,
    RecordMeasurementSummary,
    RuleRecommendation,
    RuleRecommendationRun,
    RuleTemplate,
    ScoringPolicy,
)
from persistence.postgres import connect
from scoring.v2 import ScoringV2Result


DEFAULT_UPLOAD_DIR = Path("data/uploads")


@dataclass(frozen=True)
class DatasetBundle:
    dataset: DatasetRecord
    version: DatasetVersion
    columns: list[DatasetColumn]


class DqPostgresRepository:
    def __init__(self, database_url: str | None = None, upload_dir: str | Path = DEFAULT_UPLOAD_DIR) -> None:
        self.database_url = database_url
        self.upload_dir = Path(upload_dir)

    def register_dataset(self, csv_content: bytes, metadata: dict[str, Any]) -> DatasetBundle:
        dataset_id = str(metadata["dataset_id"])
        dataset_name = metadata.get("dataset_name")
        dataset_type = str(metadata.get("dataset_type") or "default")
        source_type = str(metadata.get("source_type") or "csv")
        fingerprint = hashlib.sha256(csv_content).hexdigest()
        version_label = str(metadata.get("version_label") or fingerprint[:12])
        dataset_version_id = str(metadata.get("dataset_version_id") or f"DV-{dataset_id}-{fingerprint[:12]}")
        storage_path = str(metadata.get("storage_path") or self._persist_csv(dataset_id, dataset_version_id, csv_content))

        rows, headers = _read_csv_shape(csv_content)
        declared_schema = metadata.get("declared_schema") or {column: {} for column in headers}
        dataset = DatasetRecord(dataset_id, dataset_name, dataset_type, source_type, storage_path)
        version = DatasetVersion(dataset_version_id, dataset_id, version_label, fingerprint, rows, storage_path=storage_path)
        columns = [
            DatasetColumn(
                dataset_version_id=dataset_version_id,
                column_name=column,
                ordinal_position=index,
                declared_data_type=(declared_schema.get(column) or {}).get("data_type"),
                nullable=(declared_schema.get(column) or {}).get("nullable"),
                is_business_key=column in set(metadata.get("business_key") or []),
                is_cde=column in set(metadata.get("cde_fields") or []),
                is_mandatory=column in set(metadata.get("mandatory_fields") or []),
                is_identifier=column in set(metadata.get("primary_key") or []) or column in set(metadata.get("business_key") or []),
                is_timestamp=column == metadata.get("timestamp_column"),
            )
            for index, column in enumerate(headers, start=1)
        ]
        self.save_dataset_bundle(dataset, version, columns)
        return DatasetBundle(dataset, version, columns)

    def save_dataset_bundle(self, dataset: DatasetRecord, version: DatasetVersion, columns: list[DatasetColumn]) -> None:
        with connect(self.database_url) as conn:
            with conn.cursor() as cur:
                _upsert(cur, "dataset", dataset.to_record(), ["dataset_id"])
                _upsert(cur, "dataset_version", version.to_record(), ["dataset_version_id"])
                for column in columns:
                    _upsert(cur, "dataset_column", column.to_record(), ["dataset_version_id", "column_name"])
            conn.commit()

    def save_seed_plan(self, plan: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
        counts: dict[str, int] = {}
        order = ["dataset", "dataset_version", "dataset_column", "rule_template", "dataset_rule_binding", "scoring_policy"]
        keys = {
            "dataset": ["dataset_id"],
            "dataset_version": ["dataset_version_id"],
            "dataset_column": ["dataset_version_id", "column_name"],
            "rule_template": ["rule_template_id"],
            "dataset_rule_binding": ["binding_id"],
            "scoring_policy": ["scoring_policy_id"],
        }
        with connect(self.database_url) as conn:
            with conn.cursor() as cur:
                for table in order:
                    rows = plan.get(table, [])
                    for row in rows:
                        _upsert(cur, table, row, keys[table])
                    counts[table] = len(rows)
            conn.commit()
        return counts

    def reset_v2_data(self) -> None:
        tables = [
            "pipeline_log",
            "dataset_score_history",
            "dimension_score_history",
            "rule_score_history",
            "score_run",
            "rule_issue_sample",
            "record_measurement_summary",
            "measurement_result",
            "validation_run",
            "column_profile",
            "dataset_profile",
            "profiling_run",
            "dataset_rule_binding",
            "rule_template",
            "scoring_policy",
            "dataset_column",
            "dataset_version",
            "dataset",
        ]
        with connect(self.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute("TRUNCATE TABLE " + ", ".join(tables) + " RESTART IDENTITY CASCADE")
            conn.commit()

    def load_dataset_bundle(self, dataset_version_id: str) -> DatasetBundle:
        with connect(self.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT d.dataset_id, d.dataset_name, d.dataset_type, d.source_type, d.storage_path, d.created_at,
                           v.dataset_version_id, v.version_label, v.source_fingerprint, v.row_count, v.created_at, v.storage_path
                    FROM dataset_version v
                    JOIN dataset d ON d.dataset_id = v.dataset_id
                    WHERE v.dataset_version_id = %s
                    """,
                    (dataset_version_id,),
                )
                row = cur.fetchone()
                if row is None:
                    raise KeyError(f"Unknown dataset_version_id '{dataset_version_id}'")
                dataset = DatasetRecord(row[0], row[1], row[2], row[3], row[4], str(row[5]))
                version = DatasetVersion(row[6], row[0], row[7], row[8], row[9], str(row[10]), row[11])
                cur.execute(
                    """
                    SELECT dataset_version_id, column_name, ordinal_position, declared_data_type, inferred_data_type,
                           nullable, semantic_type, semantic_confidence, is_business_key, is_cde,
                           is_mandatory, is_identifier, is_timestamp
                    FROM dataset_column
                    WHERE dataset_version_id = %s
                    ORDER BY ordinal_position
                    """,
                    (dataset_version_id,),
                )
                columns = [DatasetColumn(*item) for item in cur.fetchall()]
        return DatasetBundle(dataset, version, columns)

    def save_profile_result(self, dataset_version_id: str, result: Any, profile_metrics: list[Any] | None = None) -> str:
        profile_metrics = profile_metrics or []
        with connect(self.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO profiling_run (profiling_run_id, dataset_version_id, status, completed_at)
                    VALUES (%s, %s, %s, now())
                    ON CONFLICT (profiling_run_id) DO UPDATE
                    SET status = EXCLUDED.status, completed_at = EXCLUDED.completed_at
                    """,
                    (result.profiling_run.run_id, dataset_version_id, result.profiling_run.status),
                )
                cur.execute(
                    """
                    UPDATE profiling_run
                    SET scan_mode = %s,
                        sample_method = %s,
                        sample_ratio = %s,
                        random_seed = %s,
                        coverage_estimate = %s,
                        profile_confidence = %s,
                        chunk_size = %s,
                        memory_budget_mb = %s,
                        time_budget_sec = %s,
                        budget_used = %s,
                        skipped_metrics = %s,
                        termination_reason = %s,
                        deep_profiled_columns = %s,
                        profile_strategy = %s
                    WHERE profiling_run_id = %s
                    """,
                    (
                        result.profiling_run.scan_mode,
                        result.profiling_run.sample_method,
                        result.profiling_run.sample_ratio,
                        result.profiling_run.random_seed,
                        result.profiling_run.coverage_estimate,
                        result.profiling_run.profile_confidence,
                        result.profiling_run.chunk_size,
                        result.profiling_run.memory_budget_mb,
                        result.profiling_run.time_budget_sec,
                        _encode("budget_used", result.profiling_run.budget_used),
                        result.profiling_run.skipped_metrics,
                        result.profiling_run.termination_reason,
                        result.profiling_run.deep_profiled_columns,
                        result.profiling_run.profile_strategy,
                        result.profiling_run.run_id,
                    ),
                )
                _upsert(
                    cur,
                    "dataset_profile",
                    {
                        "profiling_run_id": result.profiling_run.run_id,
                        "row_count": result.dataset_profile.row_count,
                        "column_count": result.dataset_profile.column_count,
                        "duplicate_row_count": result.dataset_profile.duplicate_row_count,
                        "duplicate_row_ratio": result.dataset_profile.duplicate_row_ratio,
                        "profile_json": result.to_artifact(),
                    },
                    ["profiling_run_id"],
                )
                for metric in profile_metrics:
                    _upsert(
                        cur,
                        "column_profile",
                        {
                            "profiling_run_id": metric.run_id,
                            "column_name": metric.column_name or "__dataset__",
                            "metric_name": metric.metric_name,
                            "metric_value": metric.metric_value,
                            "metric_source": metric.metric_source,
                            "gx_expectation_type": metric.gx_expectation_type,
                            "metric_scope": metric.metric_scope,
                            "is_approximate": metric.is_approximate,
                            "sample_size": metric.sample_size,
                            "sample_ratio": metric.sample_ratio,
                            "random_seed": metric.random_seed,
                            "coverage_estimate": metric.coverage_estimate,
                            "collected_at": metric.collected_at,
                        },
                        ["profiling_run_id", "column_name", "metric_name", "metric_source"],
                    )
            conn.commit()
        return result.profiling_run.run_id

    def save_rule_templates(self, templates: Iterable[RuleTemplate]) -> None:
        with connect(self.database_url) as conn:
            with conn.cursor() as cur:
                for template in templates:
                    _upsert(cur, "rule_template", template.to_record(), ["rule_template_id"])
            conn.commit()

    def load_rule_templates(self, active_only: bool = True) -> list[RuleTemplate]:
        sql = "SELECT * FROM rule_template"
        if active_only:
            sql += " WHERE active = true"
        sql += " ORDER BY rule_code, rule_template_version"
        with connect(self.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                columns = [desc.name for desc in cur.description]
                return [RuleTemplate(**_rowdict(columns, row)) for row in cur.fetchall()]

    def save_rule_bindings(self, dataset_version_id: str, bindings: list[dict[str, Any]], exceptions: list[dict[str, Any]] | None = None) -> str:
        run_id = f"BIND-{uuid4().hex[:12].upper()}"
        with connect(self.database_url) as conn:
            with conn.cursor() as cur:
                for binding in bindings:
                    binding = {**binding, "dataset_version_id": dataset_version_id}
                    _upsert(cur, "dataset_rule_binding", binding, ["binding_id"])
                for exception in exceptions or []:
                    self._insert_log(cur, dataset_version_id, "rule_binding_exception", "warning", exception.get("reason"), exception)
            conn.commit()
        return run_id

    def load_rule_bindings(self, dataset_version_id: str, active_only: bool = True) -> list[DatasetRuleBinding]:
        sql = "SELECT * FROM dataset_rule_binding WHERE dataset_version_id = %s"
        params: list[Any] = [dataset_version_id]
        if active_only:
            sql += " AND status = %s"
            params.append("active")
        sql += " ORDER BY binding_id"
        with connect(self.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                columns = [desc.name for desc in cur.description]
                return [DatasetRuleBinding(**_rowdict(columns, row)) for row in cur.fetchall()]

    def save_validation_result(self, validation: CanonicalValidationResult, ruleset_hash: str, status: str = "success") -> str:
        with connect(self.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO validation_run (validation_run_id, dataset_version_id, ruleset_hash, status, completed_at)
                    VALUES (%s, %s, %s, %s, now())
                    ON CONFLICT (validation_run_id) DO UPDATE
                    SET status = EXCLUDED.status, completed_at = EXCLUDED.completed_at
                    """,
                    (validation.validation_run_id, validation.dataset_version_id, ruleset_hash, status),
                )
                for measurement in validation.measurement_results:
                    record = measurement.to_record()
                    record["observed_value_jsonb"] = record.pop("observed_value")
                    record["expected_spec_jsonb"] = record.pop("expected_spec")
                    record["failure_breakdown_jsonb"] = record.pop("failure_breakdown")
                    _upsert(cur, "measurement_result", record, ["measurement_result_id"])
                for summary in validation.record_summaries:
                    _upsert(cur, "record_measurement_summary", summary.to_record(), ["measurement_result_id"])
                for sample in validation.issue_samples:
                    record = sample.to_record()
                    cur.execute(
                        """
                        INSERT INTO rule_issue_sample (
                            validation_run_id, binding_id, record_key, target_column,
                            actual_value, expected_condition, issue_type, rule_code, sampled_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            record["validation_run_id"],
                            record["binding_id"],
                            record.get("record_key"),
                            record.get("target_column"),
                            record.get("actual_value"),
                            record.get("expected_condition"),
                            record.get("issue_type"),
                            record.get("rule_code"),
                            record.get("sampled_at"),
                        ),
                    )
            conn.commit()
        return validation.validation_run_id

    def load_validation_result(self, validation_run_id: str) -> CanonicalValidationResult:
        with connect(self.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT dataset_version_id FROM validation_run WHERE validation_run_id = %s", (validation_run_id,))
                row = cur.fetchone()
                if row is None:
                    raise KeyError(f"Unknown validation_run_id '{validation_run_id}'")
                dataset_version_id = row[0]
                cur.execute("SELECT * FROM measurement_result WHERE validation_run_id = %s ORDER BY binding_id", (validation_run_id,))
                columns = [desc.name for desc in cur.description]
                measurements = []
                for item in cur.fetchall():
                    record = _rowdict(columns, item)
                    record["observed_value"] = record.pop("observed_value_jsonb")
                    record["expected_spec"] = record.pop("expected_spec_jsonb")
                    record["failure_breakdown"] = record.pop("failure_breakdown_jsonb")
                    measurements.append(MeasurementResult(**record))
                cur.execute(
                    """
                    SELECT s.*
                    FROM record_measurement_summary s
                    JOIN measurement_result m ON m.measurement_result_id = s.measurement_result_id
                    WHERE m.validation_run_id = %s
                    ORDER BY m.binding_id
                    """,
                    (validation_run_id,),
                )
                columns = [desc.name for desc in cur.description]
                summaries = [RecordMeasurementSummary(**_rowdict(columns, item)) for item in cur.fetchall()]
                cur.execute("SELECT * FROM rule_issue_sample WHERE validation_run_id = %s", (validation_run_id,))
                columns = [desc.name for desc in cur.description]
                from dq_core.models import ValidationIssueSample
                issue_samples = [ValidationIssueSample(**_rowdict(columns, item)) for item in cur.fetchall()]
        return CanonicalValidationResult(validation_run_id, dataset_version_id, measurements, summaries, issue_samples)


    def bootstrap_catalog(self, templates: Iterable[RuleTemplate], policies: Iterable[ScoringPolicy] | None = None) -> dict[str, int]:
        template_list = list(templates)
        policy_list = list(policies or [])
        self.save_rule_templates(template_list)
        if policy_list:
            self.save_scoring_policies(policy_list)
        return {"rule_template": len(template_list), "scoring_policy": len(policy_list)}

    def save_scoring_policies(self, policies: Iterable[ScoringPolicy]) -> None:
        with connect(self.database_url) as conn:
            with conn.cursor() as cur:
                for policy in policies:
                    _upsert(cur, "scoring_policy", policy.to_record(), ["scoring_policy_id"])
            conn.commit()

    def save_recommendation_run(self, run: RuleRecommendationRun, recommendations: list[RuleRecommendation]) -> str:
        with connect(self.database_url) as conn:
            with conn.cursor() as cur:
                _upsert(cur, "rule_recommendation_run", run.to_record(), ["recommendation_run_id"])
                for item in recommendations:
                    record = {
                        "recommendation_id": item.recommendation_id,
                        "recommendation_run_id": item.recommendation_run_id or run.recommendation_run_id,
                        "column_id": item.target_columns[0] if item.target_columns else None,
                        "rule_template_id": item.rule_template_id,
                        "target_columns": item.target_columns,
                        "candidate_score": item.candidate_score if item.candidate_score is not None else item.confidence,
                        "score_components_jsonb": item.score_components,
                        "reason_jsonb": item.reason_json,
                        "reason": item.reason,
                        "rank": item.rank or 0,
                        "score_margin": item.score_margin,
                        "ambiguity_status": item.ambiguity_status,
                        "decision": item.review_status,
                        "suggested_parameters_jsonb": item.suggested_parameters,
                        "warnings": item.warnings,
                        "source": item.source,
                        "editable": item.editable,
                    }
                    _upsert(cur, "rule_recommendation_result", record, ["recommendation_id"])
            conn.commit()
        return run.recommendation_run_id

    def load_latest_recommendations(self, dataset_version_id: str, decision: str | None = None) -> list[RuleRecommendation]:
        with connect(self.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT recommendation_run_id
                    FROM rule_recommendation_run
                    WHERE dataset_version_id = %s
                    ORDER BY COALESCE(completed_at, started_at) DESC, recommendation_run_id DESC
                    LIMIT 1
                    """,
                    (dataset_version_id,),
                )
                row = cur.fetchone()
                if row is None:
                    return []
                run_id = row[0]
                sql = "SELECT * FROM rule_recommendation_result WHERE recommendation_run_id = %s"
                params: list[Any] = [run_id]
                if decision is not None:
                    sql += " AND decision = %s"
                    params.append(decision)
                sql += " ORDER BY column_id, rank, candidate_score DESC"
                cur.execute(sql, params)
                columns = [desc.name for desc in cur.description]
                rows = [_rowdict(columns, item) for item in cur.fetchall()]
        return [_recommendation_from_row(row) for row in rows]

    def review_recommendation(self, recommendation_id: str, decision: str, suggested_parameters: dict[str, Any] | None = None) -> str:
        if decision not in {"accepted", "rejected", "edited", "suggested"}:
            raise ValueError(f"Unsupported recommendation decision '{decision}'")
        with connect(self.database_url) as conn:
            with conn.cursor() as cur:
                if suggested_parameters is None:
                    cur.execute(
                        """
                        UPDATE rule_recommendation_result
                        SET decision = %s, reviewed_at = now()
                        WHERE recommendation_id = %s
                        """,
                        (decision, recommendation_id),
                    )
                else:
                    cur.execute(
                        """
                        UPDATE rule_recommendation_result
                        SET decision = %s, suggested_parameters_jsonb = %s, reviewed_at = now()
                        WHERE recommendation_id = %s
                        """,
                        (decision, _encode("suggested_parameters_jsonb", suggested_parameters), recommendation_id),
                    )
            conn.commit()
        return recommendation_id
    def load_scoring_policy(self, scoring_policy_id: str | None = None, dataset_type: str | None = None) -> ScoringPolicy:
        if scoring_policy_id is None and dataset_type is None:
            raise ValueError("scoring_policy_id or dataset_type is required")
        with connect(self.database_url) as conn:
            with conn.cursor() as cur:
                if scoring_policy_id is not None:
                    cur.execute("SELECT * FROM scoring_policy WHERE scoring_policy_id = %s", (scoring_policy_id,))
                else:
                    cur.execute(
                        """
                        SELECT *
                        FROM scoring_policy
                        WHERE dataset_type IN (%s, 'default')
                        ORDER BY CASE WHEN dataset_type = %s THEN 0 ELSE 1 END, scoring_policy_id
                        LIMIT 1
                        """,
                        (dataset_type, dataset_type),
                    )
                row = cur.fetchone()
                if row is None:
                    raise KeyError("No scoring policy found")
                columns = [desc.name for desc in cur.description]
                return ScoringPolicy(**_rowdict(columns, row))

    def save_score_result(self, dataset_version_id: str, result: ScoringV2Result) -> str:
        with connect(self.database_url) as conn:
            with conn.cursor() as cur:
                _upsert(
                    cur,
                    "score_run",
                    {
                        "score_run_id": result.score_run_id,
                        "validation_run_id": result.validation_run_id,
                        "scoring_policy_id": result.scoring_policy_id,
                        "dataset_version_id": dataset_version_id,
                        "status": "success",
                        "policy_snapshot_jsonb": result.policy_snapshot,
                        "formula_revision": result.formula_revision,
                        "validation_scope": result.validation_scope,
                    },
                    ["score_run_id"],
                )
                for score in result.rule_scores:
                    _upsert(
                        cur,
                        "rule_score_history",
                        {
                            "score_run_id": result.score_run_id,
                            "binding_id": score.binding_id,
                            "dimension": score.dimension,
                            "rule_score": score.rule_score,
                            "measurement_status": score.measurement_status,
                            "quality_status": score.quality_status,
                            "base_rule_weight": score.base_rule_weight,
                            "severity_weight": score.severity_weight,
                            "criticality_weight": score.criticality_weight,
                            "effective_weight": score.effective_weight,
                            "evaluated_count": score.evaluated_count,
                            "conflict_group": score.conflict_group,
                            "primary_scoring_rule": score.primary_scoring_rule,
                            "score_enabled": score.score_enabled,
                            "measurement_status_reason": score.measurement_status_reason,
                            "contribution": score.contribution,
                            "explanation_jsonb": score.explanation,
                        },
                        ["score_run_id", "binding_id"],
                    )
                for score in result.dimension_scores:
                    _upsert(
                        cur,
                        "dimension_score_history",
                        {
                            "score_run_id": result.score_run_id,
                            "dimension": score.dimension,
                            "dimension_score": score.dimension_score,
                            "original_dimension_weight": score.original_dimension_weight,
                            "normalized_dimension_weight": score.normalized_dimension_weight,
                            "measurement_status": score.measurement_status,
                        },
                        ["score_run_id", "dimension"],
                    )
                _upsert(
                    cur,
                    "dataset_score_history",
                    {
                        "score_run_id": result.score_run_id,
                        "dataset_dq_score": result.dataset_score.dataset_dq_score,
                        "quality_gate_status": result.dataset_score.quality_gate_status,
                        "measured_dimensions": result.dataset_score.measured_dimensions,
                        "excluded_dimensions": result.dataset_score.excluded_dimensions,
                        "gate_failures": result.dataset_score.gate_failures,
                        "measurement_coverage": result.dataset_score.measurement_coverage,
                        "measured_dimension_count": result.dataset_score.measured_dimension_count,
                        "total_dimension_count": result.dataset_score.total_dimension_count,
                        "score_status": result.dataset_score.score_status,
                        "validation_scope": result.dataset_score.validation_scope,
                        "policy_snapshot_jsonb": result.dataset_score.policy_snapshot,
                        "formula_revision": result.dataset_score.formula_revision,
                    },
                    ["score_run_id"],
                )
            conn.commit()
        return result.score_run_id
    def list_dashboard_rows(self) -> dict[str, list[dict[str, Any]]]:
        tables = [
            "dataset",
            "dataset_version",
            "validation_run",
            "score_run",
            "dataset_score_history",
            "dimension_score_history",
            "rule_score_history",
            "dataset_rule_binding",
            "rule_template",
            "rule_issue_sample",
            "profiling_run",
            "dataset_profile",
            "column_profile",
            "rule_recommendation_run",
            "rule_recommendation_result",
            "pipeline_log",
        ]
        result: dict[str, list[dict[str, Any]]] = {}
        with connect(self.database_url) as conn:
            with conn.cursor() as cur:
                for table in tables:
                    cur.execute(f"SELECT * FROM {table}")
                    columns = [desc.name for desc in cur.description]
                    result[table] = [_rowdict(columns, row) for row in cur.fetchall()]
        return result

    def save_pipeline_log(self, log: PipelineLog) -> str:
        with connect(self.database_url) as conn:
            with conn.cursor() as cur:
                self._insert_log(cur, log.dataset_version_id, log.event_type, log.status, log.message, log.context, log.log_id)
            conn.commit()
        return log.log_id

    def _persist_csv(self, dataset_id: str, dataset_version_id: str, csv_content: bytes) -> Path:
        path = self.upload_dir / dataset_id / f"{dataset_version_id}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(csv_content)
        return path

    @staticmethod
    def _insert_log(
        cur: Any,
        dataset_version_id: str | None,
        event_type: str,
        status: str,
        message: str | None,
        context: dict[str, Any],
        log_id: str | None = None,
    ) -> None:
        _upsert(
            cur,
            "pipeline_log",
            {
                "log_id": log_id or f"LOG-{uuid4().hex[:12].upper()}",
                "dataset_version_id": dataset_version_id,
                "event_type": event_type,
                "status": status,
                "message": message,
                "context": context,
            },
            ["log_id"],
        )


def _read_csv_shape(csv_content: bytes) -> tuple[int, list[str]]:
    decoded = csv_content.decode("utf-8-sig")
    reader = csv.reader(decoded.splitlines())
    headers = next(reader)
    return sum(1 for _ in reader), [str(column) for column in headers]


def _upsert(cur: Any, table: str, record: dict[str, Any], key_columns: list[str]) -> None:
    encoded = {key: _encode(key, value) for key, value in record.items()}
    columns = list(encoded)
    placeholders = ", ".join(["%s"] * len(columns))
    assignments = ", ".join(f"{column} = EXCLUDED.{column}" for column in columns if column not in key_columns)
    conflict = ", ".join(key_columns)
    sql = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders}) ON CONFLICT ({conflict}) "
    sql += f"DO UPDATE SET {assignments}" if assignments else "DO NOTHING"
    cur.execute(sql, tuple(encoded[column] for column in columns))


def _encode(column: str, value: Any) -> Any:
    if column in {"target_columns", "required_columns", "backend_support", "warnings", "skipped_metrics", "deep_profiled_columns", "measured_dimensions", "excluded_dimensions"}:
        return value
    if column.endswith("jsonb") or column in {
        "applicability",
        "parameters",
        "normalization",
        "dimension_weights",
        "severity_weights",
        "criticality_weights",
        "profile_json",
        "metric_value",
        "context",
        "gate_failures",
        "exclusions",
        "parameters_schema",
        "recommendation_metadata",
        "score_components_jsonb",
        "reason_jsonb",
        "suggested_parameters_jsonb",
        "expected_jsonb",
        "budget_used",
    }:
        try:
            from psycopg.types.json import Jsonb
        except Exception:
            return json.dumps(value, ensure_ascii=False, sort_keys=True)
        return Jsonb(value)
    return value


def _rowdict(columns: list[str], row: tuple[Any, ...]) -> dict[str, Any]:
    return {column: value for column, value in zip(columns, row)}











def _recommendation_from_row(row: dict[str, Any]) -> RuleRecommendation:
    return RuleRecommendation(
        rule_template_id=row["rule_template_id"],
        target_columns=list(row.get("target_columns") or []),
        reason=row.get("reason") or "",
        confidence=float(row.get("candidate_score") or 0.0),
        editable=bool(row.get("editable", True)),
        source=row.get("source") or "framework_auto",
        recommendation_id=row.get("recommendation_id"),
        recommendation_run_id=row.get("recommendation_run_id"),
        candidate_score=row.get("candidate_score"),
        score_components=row.get("score_components_jsonb") or {},
        reason_json=row.get("reason_jsonb") or {},
        rank=row.get("rank"),
        score_margin=row.get("score_margin"),
        ambiguity_status=row.get("ambiguity_status") or "clear",
        review_status=row.get("decision") or "suggested",
        suggested_parameters=row.get("suggested_parameters_jsonb") or {},
        warnings=list(row.get("warnings") or []),
    )
