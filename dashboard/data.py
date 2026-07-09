from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from persistence.repository import DqPostgresRepository


@dataclass(frozen=True)
class DashboardFrames:
    score_runs: pd.DataFrame
    dataset_scores: pd.DataFrame
    dimension_scores: pd.DataFrame
    rule_scores: pd.DataFrame
    rule_runs: pd.DataFrame
    rule_configs: pd.DataFrame
    issue_samples: pd.DataFrame


def load_dashboard_frames(database_url: str | Path | None = None, _unused: str | Path | None = None) -> DashboardFrames:
    try:
        rows = DqPostgresRepository(str(database_url) if database_url else None).list_dashboard_rows()
    except Exception:
        return _empty_frames()

    datasets = pd.DataFrame(rows.get("dataset", []))
    versions = pd.DataFrame(rows.get("dataset_version", []))
    score_runs_raw = pd.DataFrame(rows.get("score_run", []))
    dataset_scores_raw = pd.DataFrame(rows.get("dataset_score_history", []))
    dimension_scores = pd.DataFrame(rows.get("dimension_score_history", []))
    rule_scores = pd.DataFrame(rows.get("rule_score_history", []))
    bindings = pd.DataFrame(rows.get("dataset_rule_binding", []))
    templates = pd.DataFrame(rows.get("rule_template", []))
    issues = pd.DataFrame(rows.get("rule_issue_sample", []))

    score_runs = _score_runs(score_runs_raw, versions)
    dataset_scores = _dataset_scores(dataset_scores_raw, score_runs, versions)
    dimension_scores = _dimension_scores(dimension_scores, score_runs)
    rule_configs = _rule_configs(bindings, templates, score_runs)
    rule_scores = _rule_scores(rule_scores, rule_configs, score_runs)
    issue_samples = _issues(issues, rule_configs, score_runs)
    return DashboardFrames(
        score_runs=_with_datetime(score_runs, "run_timestamp"),
        dataset_scores=_with_datetime(dataset_scores, "run_timestamp"),
        dimension_scores=dimension_scores,
        rule_scores=rule_scores,
        rule_runs=pd.DataFrame(columns=_rule_run_columns()),
        rule_configs=rule_configs,
        issue_samples=issue_samples,
    )


def latest_dataset_scores(frames: DashboardFrames) -> pd.DataFrame:
    scores = frames.dataset_scores.copy()
    if scores.empty:
        return scores
    scores = scores.sort_values(["dataset_id", "run_timestamp", "run_id"])
    return scores.groupby("dataset_id", as_index=False).tail(1).sort_values("dataset_id").reset_index(drop=True)


def dataset_runs(frames: DashboardFrames, dataset_id: str) -> pd.DataFrame:
    scores = frames.dataset_scores
    if scores.empty:
        return scores.copy()
    return scores[scores["dataset_id"] == dataset_id].sort_values(["run_timestamp", "run_id"], ascending=[False, False]).reset_index(drop=True)


def run_details(frames: DashboardFrames, run_id: str) -> dict[str, Any]:
    dataset_score = frames.dataset_scores[frames.dataset_scores["run_id"] == run_id].copy()
    score_run = frames.score_runs[frames.score_runs["run_id"] == run_id].copy()
    dimensions = frames.dimension_scores[frames.dimension_scores["run_id"] == run_id].copy()
    rules = frames.rule_scores[frames.rule_scores["run_id"] == run_id].copy()
    issues = frames.issue_samples[frames.issue_samples["run_id"] == run_id].copy() if "run_id" in frames.issue_samples.columns else frames.issue_samples.copy()
    return {
        "dataset_score": dataset_score.reset_index(drop=True),
        "score_run": score_run.reset_index(drop=True),
        "rule_run_id": run_id,
        "dimensions": dimensions.sort_values("dimension").reset_index(drop=True) if not dimensions.empty else dimensions,
        "rules": _sort_rules(rules),
        "issues": issues.reset_index(drop=True),
    }


def aggregate_latest_status_counts(frames: DashboardFrames) -> dict[str, int]:
    latest = latest_dataset_scores(frames)
    if latest.empty:
        return {}
    return {str(key): int(value) for key, value in latest["quality_gate_status"].value_counts().to_dict().items()}


def score_summary_metrics(dataset_score: pd.DataFrame) -> dict[str, Any]:
    if dataset_score.empty:
        return {"dq_core_score": None, "quality_gate_status": "not_available", "total_records": 0, "rules_total": 0, "rules_failed": 0}
    row = dataset_score.iloc[0]
    return {
        "dq_core_score": row.get("dq_core_score"),
        "quality_gate_status": row.get("quality_gate_status"),
        "total_records": int(row.get("total_records") or 0),
        "rules_total": int(row.get("rules_total") or 0),
        "rules_failed": int(row.get("rules_failed") or 0),
    }


def _score_runs(score_runs: pd.DataFrame, versions: pd.DataFrame) -> pd.DataFrame:
    if score_runs.empty:
        return pd.DataFrame(columns=_score_run_columns())
    frame = score_runs.rename(columns={"score_run_id": "run_id", "created_at": "run_timestamp"}).copy()
    if not versions.empty:
        frame = frame.merge(versions[["dataset_version_id", "dataset_id"]], on="dataset_version_id", how="left")
    frame["rule_run_id"] = frame["validation_run_id"]
    return _ensure_columns(frame, _score_run_columns())


def _dataset_scores(dataset_scores: pd.DataFrame, score_runs: pd.DataFrame, versions: pd.DataFrame) -> pd.DataFrame:
    if dataset_scores.empty or score_runs.empty:
        return pd.DataFrame(columns=_dataset_score_columns())
    frame = dataset_scores.rename(columns={"score_run_id": "run_id", "dataset_dq_score": "dq_core_score"}).copy()
    frame = frame.merge(score_runs[["run_id", "dataset_id", "dataset_version_id", "run_timestamp"]], on="run_id", how="left")
    frame["dataset_version"] = frame["dataset_version_id"]
    frame["total_records"] = 0
    frame["rules_total"] = 0
    frame["rules_failed"] = 0
    frame["score_level"] = "dataset"
    return _ensure_columns(frame, _dataset_score_columns())


def _dimension_scores(dimensions: pd.DataFrame, score_runs: pd.DataFrame) -> pd.DataFrame:
    if dimensions.empty:
        return pd.DataFrame(columns=_dimension_score_columns())
    frame = dimensions.rename(columns={"score_run_id": "run_id", "normalized_dimension_weight": "dimension_weight"}).copy()
    frame["is_measured"] = frame["measurement_status"].eq("measured")
    frame["rules_total"] = 0
    frame["rules_failed"] = 0
    frame["rules_warning"] = 0
    frame["rules_passed"] = 0
    return _ensure_columns(frame, _dimension_score_columns())


def _rule_configs(bindings: pd.DataFrame, templates: pd.DataFrame, score_runs: pd.DataFrame) -> pd.DataFrame:
    if bindings.empty:
        return pd.DataFrame(columns=_rule_config_columns())
    frame = bindings.copy()
    if not templates.empty:
        frame = frame.merge(templates[["rule_template_id", "rule_code", "operator", "dimension", "rule_category"]], on="rule_template_id", how="left")
    frame["rule_id"] = frame["binding_id"]
    frame["rule_name"] = frame.get("rule_code")
    frame["rule_type"] = frame.get("operator")
    frame["target_column"] = frame.get("target_columns").map(lambda value: value[0] if isinstance(value, list) and value else None)
    frame["score_enabled"] = frame.get("score_enabled", True)
    return _ensure_columns(frame, _rule_config_columns())


def _rule_scores(scores: pd.DataFrame, configs: pd.DataFrame, score_runs: pd.DataFrame) -> pd.DataFrame:
    if scores.empty:
        return pd.DataFrame(columns=_rule_score_columns())
    frame = scores.rename(columns={"score_run_id": "run_id", "binding_id": "rule_id"}).copy()
    if not configs.empty:
        frame = frame.merge(configs[["rule_id", "rule_name", "severity", "target_column"]], on="rule_id", how="left")
    frame["passed"] = 0
    frame["failed"] = frame["quality_status"].eq("fail").astype(int)
    frame["miscast"] = 0
    frame["empty"] = 0
    frame["not_applicable"] = 0
    frame["total_records_in_scope"] = 0
    frame["threshold"] = None
    return _ensure_columns(frame, _rule_score_columns() + ["rule_name", "severity"])


def _issues(issues: pd.DataFrame, configs: pd.DataFrame, score_runs: pd.DataFrame) -> pd.DataFrame:
    if issues.empty:
        return pd.DataFrame(columns=_issue_sample_columns())
    frame = issues.rename(columns={"validation_run_id": "run_id", "binding_id": "rule_id"}).copy()
    if not configs.empty:
        frame = frame.merge(configs[["rule_id", "rule_name", "severity"]], on="rule_id", how="left")
    return _ensure_columns(frame, _issue_sample_columns() + ["rule_name", "severity", "run_id"])


def _empty_frames() -> DashboardFrames:
    return DashboardFrames(
        score_runs=pd.DataFrame(columns=_score_run_columns()),
        dataset_scores=pd.DataFrame(columns=_dataset_score_columns()),
        dimension_scores=pd.DataFrame(columns=_dimension_score_columns()),
        rule_scores=pd.DataFrame(columns=_rule_score_columns()),
        rule_runs=pd.DataFrame(columns=_rule_run_columns()),
        rule_configs=pd.DataFrame(columns=_rule_config_columns()),
        issue_samples=pd.DataFrame(columns=_issue_sample_columns()),
    )


def _ensure_columns(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    result = frame.copy()
    for column in columns:
        if column not in result.columns:
            result[column] = None
    return result[columns]


def _with_datetime(frame: pd.DataFrame, column: str) -> pd.DataFrame:
    converted = frame.copy()
    if column in converted.columns and not converted.empty:
        converted[column] = pd.to_datetime(converted[column], errors="coerce", utc=True)
    return converted


def _sort_rules(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.reset_index(drop=True)
    columns = [column for column in ["quality_status", "dimension", "rule_id"] if column in frame.columns]
    return frame.sort_values(columns).reset_index(drop=True) if columns else frame.reset_index(drop=True)


def _score_run_columns() -> list[str]:
    return ["run_id", "rule_run_id", "dataset_id", "dataset_version_id", "validation_run_id", "run_timestamp", "status", "scoring_policy_id"]


def _dataset_score_columns() -> list[str]:
    return ["run_id", "dataset_id", "dataset_version", "run_timestamp", "dq_core_score", "quality_gate_status", "total_records", "rules_total", "rules_failed", "measured_dimensions", "excluded_dimensions", "score_level"]


def _dimension_score_columns() -> list[str]:
    return ["run_id", "dimension", "dimension_score", "original_dimension_weight", "dimension_weight", "is_measured", "measurement_status", "rules_total", "rules_failed", "rules_warning", "rules_passed"]


def _rule_score_columns() -> list[str]:
    return ["run_id", "rule_id", "dimension", "target_column", "rule_score", "threshold", "quality_status", "passed", "failed", "miscast", "empty", "not_applicable", "total_records_in_scope", "measurement_status"]


def _rule_run_columns() -> list[str]:
    return ["rule_run_id", "dataset_id", "dataset_version", "run_timestamp", "execution_engine", "source_path", "rule_config_path", "status", "total_rules", "measured_rules", "not_measured_rules", "skipped_rules", "error_message"]


def _rule_config_columns() -> list[str]:
    return ["rule_id", "binding_id", "dataset_version_id", "rule_template_id", "rule_name", "rule_type", "dimension", "target_column", "severity", "score_enabled", "backend", "status"]


def _issue_sample_columns() -> list[str]:
    return ["rule_id", "record_key", "target_column", "actual_value", "expected_condition", "issue_type", "sampled_at"]

