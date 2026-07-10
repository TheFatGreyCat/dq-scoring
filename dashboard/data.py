from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

import pandas as pd

from persistence.repository import DqPostgresRepository


@dataclass(frozen=True)
class DatasetDashboardRow:
    dataset_id: str
    dataset_name: str | None
    dataset_version_id: str
    dq_score: float | None
    score_status: str
    quality_gate_status: str
    last_run_at: Any


@dataclass(frozen=True)
class DashboardFrames:
    score_runs: pd.DataFrame
    dataset_scores: pd.DataFrame
    dimension_scores: pd.DataFrame
    rule_scores: pd.DataFrame
    rule_runs: pd.DataFrame
    rule_configs: pd.DataFrame
    issue_samples: pd.DataFrame
    profile_evidence: pd.DataFrame
    recommendation_results: pd.DataFrame


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
    profiling_runs = pd.DataFrame(rows.get("profiling_run", []))
    dataset_profiles = pd.DataFrame(rows.get("dataset_profile", []))
    column_profiles = pd.DataFrame(rows.get("column_profile", []))
    recommendation_runs = pd.DataFrame(rows.get("rule_recommendation_run", []))
    recommendation_results_raw = pd.DataFrame(rows.get("rule_recommendation_result", []))

    datasets, versions, score_runs_raw, profiling_runs, recommendation_runs = _exclude_internal_test_data(
        datasets,
        versions,
        score_runs_raw,
        profiling_runs,
        recommendation_runs,
    )

    score_runs = _score_runs(score_runs_raw, versions)
    dataset_scores = _dataset_scores(dataset_scores_raw, score_runs, versions, datasets)
    dimension_scores = _dimension_scores(dimension_scores, score_runs)
    rule_configs = _rule_configs(bindings, templates, score_runs)
    rule_scores = _rule_scores(rule_scores, rule_configs, score_runs)
    issue_samples = _issues(issues, rule_configs, score_runs)
    profile_evidence = _profile_evidence(profiling_runs, dataset_profiles, column_profiles, score_runs)
    recommendation_results = _recommendations(recommendation_runs, recommendation_results_raw, templates)
    return DashboardFrames(
        score_runs=_with_datetime(score_runs, "run_timestamp"),
        dataset_scores=_with_datetime(dataset_scores, "run_timestamp"),
        dimension_scores=dimension_scores,
        rule_scores=rule_scores,
        rule_runs=pd.DataFrame(columns=_rule_run_columns()),
        rule_configs=rule_configs,
        issue_samples=issue_samples,
        profile_evidence=profile_evidence,
        recommendation_results=recommendation_results,
    )


def latest_dataset_scores(frames: DashboardFrames) -> pd.DataFrame:
    scores = frames.dataset_scores.copy()
    if scores.empty:
        return scores
    if "dataset_id" in scores.columns:
        scores = scores[~_is_internal_dataset_id(scores["dataset_id"])].copy()
    scores = scores.sort_values(["dataset_id", "run_timestamp", "run_id"])
    return scores.groupby("dataset_id", as_index=False).tail(1).sort_values("dataset_id").reset_index(drop=True)


def dataset_dashboard_rows(frames: DashboardFrames) -> list[DatasetDashboardRow]:
    latest = latest_dataset_scores(frames)
    rows: list[DatasetDashboardRow] = []
    for item in latest.to_dict(orient="records"):
        rows.append(
            DatasetDashboardRow(
                dataset_id=str(item.get("dataset_id") or ""),
                dataset_name=item.get("dataset_name"),
                dataset_version_id=str(item.get("dataset_version") or ""),
                dq_score=item.get("dq_core_score"),
                score_status=str(item.get("score_status") or item.get("quality_gate_status") or "not_available"),
                quality_gate_status=str(item.get("quality_gate_status") or "not_available"),
                last_run_at=item.get("run_timestamp"),
            )
        )
    return rows


def dataset_runs(frames: DashboardFrames, dataset_id: str) -> pd.DataFrame:
    scores = frames.dataset_scores
    if scores.empty:
        return scores.copy()
    if str(dataset_id).startswith("it_dataset_"):
        return scores.iloc[0:0].copy()
    if "dataset_id" in scores.columns:
        scores = scores[~_is_internal_dataset_id(scores["dataset_id"])].copy()
    return scores[scores["dataset_id"] == dataset_id].sort_values(["run_timestamp", "run_id"], ascending=[False, False]).reset_index(drop=True)


def run_details(frames: DashboardFrames, run_id: str) -> dict[str, Any]:
    dataset_score = frames.dataset_scores[frames.dataset_scores["run_id"] == run_id].copy()
    score_run = frames.score_runs[frames.score_runs["run_id"] == run_id].copy()
    dimensions = frames.dimension_scores[frames.dimension_scores["run_id"] == run_id].copy()
    rules = _sort_rules(frames.rule_scores[frames.rule_scores["run_id"] == run_id].copy())
    issues = frames.issue_samples[frames.issue_samples["run_id"] == run_id].copy() if "run_id" in frames.issue_samples.columns else frames.issue_samples.copy()
    profile_evidence = frames.profile_evidence[frames.profile_evidence["run_id"] == run_id].copy() if "run_id" in frames.profile_evidence.columns else frames.profile_evidence.copy()
    dataset_score = _enrich_dataset_score_summary(dataset_score, dimensions, rules)
    column_breakdown = _column_breakdown(rules, issues)
    record_breakdown = _record_breakdown(issues)
    dataset_version = dataset_score.iloc[0]["dataset_version"] if not dataset_score.empty and "dataset_version" in dataset_score.columns else None
    recommendations = frames.recommendation_results[frames.recommendation_results["dataset_version_id"] == dataset_version].copy() if dataset_version and "dataset_version_id" in frames.recommendation_results.columns else pd.DataFrame(columns=_recommendation_columns())
    return {
        "dataset_score": dataset_score.reset_index(drop=True),
        "score_run": score_run.reset_index(drop=True),
        "rule_run_id": run_id,
        "dimensions": dimensions.sort_values("dimension").reset_index(drop=True) if not dimensions.empty else dimensions,
        "rules": rules,
        "issues": issues.reset_index(drop=True),
        "profile_evidence": profile_evidence.reset_index(drop=True),
        "recommendations": recommendations.reset_index(drop=True),
        "column_breakdown": column_breakdown.reset_index(drop=True),
        "record_breakdown": record_breakdown.reset_index(drop=True),
    }


def _enrich_dataset_score_summary(dataset_score: pd.DataFrame, dimensions: pd.DataFrame, rules: pd.DataFrame) -> pd.DataFrame:
    if dataset_score.empty:
        return dataset_score
    enriched = dataset_score.copy()
    rules_total = len(rules) if not rules.empty else 0
    rules_failed = int(rules["quality_status"].eq("fail").sum()) if not rules.empty and "quality_status" in rules.columns else 0
    enriched.loc[:, "rules_total"] = rules_total
    enriched.loc[:, "rules_failed"] = rules_failed
    if not dimensions.empty:
        total_dimensions = len(dimensions)
        if "is_measured" in dimensions.columns:
            measured_dimensions = int(dimensions["is_measured"].fillna(False).sum())
        elif "measurement_status" in dimensions.columns:
            measured_dimensions = int(dimensions["measurement_status"].eq("measured").sum())
        else:
            measured_dimensions = 0
        coverage = measured_dimensions / total_dimensions if total_dimensions else None
        for column, value in (
            ("measurement_coverage", coverage),
            ("measured_dimension_count", measured_dimensions),
            ("total_dimension_count", total_dimensions),
        ):
            current = enriched.iloc[0].get(column) if column in enriched.columns else None
            if current is None or pd.isna(current):
                enriched.loc[:, column] = value
    return enriched


def aggregate_latest_status_counts(frames: DashboardFrames) -> dict[str, int]:
    latest = latest_dataset_scores(frames)
    if latest.empty:
        return {}
    return {str(key): int(value) for key, value in latest["quality_gate_status"].value_counts().to_dict().items()}


def score_summary_metrics(dataset_score: pd.DataFrame) -> dict[str, Any]:
    if dataset_score.empty:
        return {"dq_core_score": None, "quality_gate_status": "not_available", "measurement_coverage": None, "score_status": "not_available", "total_records": 0, "rules_total": 0, "rules_failed": 0}
    row = dataset_score.iloc[0]
    return {
        "dq_core_score": row.get("dq_core_score"),
        "quality_gate_status": row.get("quality_gate_status"),
        "measurement_coverage": row.get("measurement_coverage"),
        "score_status": row.get("score_status"),
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


def _dataset_scores(dataset_scores: pd.DataFrame, score_runs: pd.DataFrame, versions: pd.DataFrame, datasets: pd.DataFrame) -> pd.DataFrame:
    if dataset_scores.empty or score_runs.empty:
        return pd.DataFrame(columns=_dataset_score_columns())
    frame = dataset_scores.rename(columns={"score_run_id": "run_id", "dataset_dq_score": "dq_core_score"}).copy()
    frame = frame.merge(score_runs[["run_id", "dataset_id", "dataset_version_id", "run_timestamp"]], on="run_id", how="left")
    frame = frame[frame["dataset_id"].notna()].copy()
    if not datasets.empty:
        frame = frame.merge(datasets[["dataset_id", "dataset_name"]], on="dataset_id", how="left")
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
    frame = issues.rename(columns={"binding_id": "rule_id"}).copy()
    if "validation_run_id" in frame.columns and {"run_id", "validation_run_id"}.issubset(score_runs.columns):
        frame = frame.merge(score_runs[["run_id", "validation_run_id"]], on="validation_run_id", how="left")
    elif "validation_run_id" in frame.columns:
        frame["run_id"] = frame["validation_run_id"]
    if not configs.empty:
        frame = frame.merge(configs[["rule_id", "rule_name", "severity"]], on="rule_id", how="left")
    for column in ("actual_value", "record_key"):
        if column in frame.columns:
            frame[column] = frame[column].map(_mask_sensitive_value)
    return _ensure_columns(frame, _issue_sample_columns() + ["rule_name", "severity", "run_id"])



def _recommendations(runs: pd.DataFrame, results: pd.DataFrame, templates: pd.DataFrame) -> pd.DataFrame:
    if runs.empty or results.empty:
        return pd.DataFrame(columns=_recommendation_columns())
    frame = results.copy()
    frame = frame.merge(runs[["recommendation_run_id", "dataset_version_id", "catalog_revision", "status"]], on="recommendation_run_id", how="left")
    if not templates.empty and "rule_template_id" in templates.columns:
        columns = [column for column in ["rule_template_id", "rule_code", "family", "dimension"] if column in templates.columns]
        frame = frame.merge(templates[columns], on="rule_template_id", how="left")
    frame = frame.rename(columns={"decision": "review_status"})
    return _ensure_columns(frame, _recommendation_columns())

def _profile_evidence(profiling_runs: pd.DataFrame, dataset_profiles: pd.DataFrame, column_profiles: pd.DataFrame, score_runs: pd.DataFrame) -> pd.DataFrame:
    if profiling_runs.empty or column_profiles.empty or score_runs.empty:
        return pd.DataFrame(columns=_profile_evidence_columns())
    required = {"profiling_run_id", "dataset_version_id"}
    if not required.issubset(profiling_runs.columns) or "profiling_run_id" not in column_profiles.columns:
        return pd.DataFrame(columns=_profile_evidence_columns())

    runs = profiling_runs.copy()
    if "completed_at" in runs.columns:
        runs["_sort_time"] = pd.to_datetime(runs["completed_at"], errors="coerce", utc=True)
    elif "started_at" in runs.columns:
        runs["_sort_time"] = pd.to_datetime(runs["started_at"], errors="coerce", utc=True)
    else:
        runs["_sort_time"] = pd.NaT
    latest_runs = runs.sort_values(["dataset_version_id", "_sort_time", "profiling_run_id"]).groupby("dataset_version_id", as_index=False).tail(1)
    latest_run_ids = set(latest_runs["profiling_run_id"].astype(str))
    run_by_id = {str(row["profiling_run_id"]): row for row in latest_runs.to_dict(orient="records")}
    score_runs_by_version = score_runs[["run_id", "dataset_version_id"]].dropna().to_dict(orient="records") if {"run_id", "dataset_version_id"}.issubset(score_runs.columns) else []

    profile_json_by_run: dict[str, dict[str, Any]] = {}
    if not dataset_profiles.empty and {"profiling_run_id", "profile_json"}.issubset(dataset_profiles.columns):
        for item in dataset_profiles.to_dict(orient="records"):
            value = _metric_value(item.get("profile_json"))
            profile_json_by_run[str(item.get("profiling_run_id"))] = value if isinstance(value, dict) else {}

    rows: list[dict[str, Any]] = []
    metrics = column_profiles.copy()
    metrics = metrics[metrics["profiling_run_id"].astype(str).isin(latest_run_ids)]
    if "column_name" in metrics.columns:
        metrics = metrics[metrics["column_name"].notna() & metrics["column_name"].ne("__dataset__")]
    for (profiling_run_id, column_name), group in metrics.groupby(["profiling_run_id", "column_name"]):
        profiling_run_id = str(profiling_run_id)
        run_meta = run_by_id.get(profiling_run_id, {})
        dataset_version_id = run_meta.get("dataset_version_id")
        matching_score_runs = [item for item in score_runs_by_version if item.get("dataset_version_id") == dataset_version_id]
        if not matching_score_runs:
            continue
        values = {str(row.get("metric_name")): _metric_value(row.get("metric_value")) for row in group.to_dict(orient="records")}
        evidence = values.get("profile_evidence") if isinstance(values.get("profile_evidence"), dict) else {}
        type_conformance = values.get("type_conformance") if isinstance(values.get("type_conformance"), dict) else {}
        artifact_column = _artifact_column(profile_json_by_run.get(profiling_run_id, {}), str(column_name))
        for score_run in matching_score_runs:
            rows.append(
                {
                    "run_id": score_run.get("run_id"),
                    "profiling_run_id": profiling_run_id,
                    "dataset_version_id": dataset_version_id,
                    "column_name": column_name,
                    "inferred_type": values.get("inferred_type") or artifact_column.get("inferred_data_type"),
                    "inferred_type_confidence": evidence.get("inferred_type_confidence") or artifact_column.get("inferred_type_confidence"),
                    "metric_scope": evidence.get("metric_scope") or _first_non_null(group, "metric_scope") or artifact_column.get("metric_scope"),
                    "scan_mode": run_meta.get("scan_mode"),
                    "sample_method": run_meta.get("sample_method"),
                    "sample_size": _first_non_null(group, "sample_size"),
                    "sample_ratio": _first_non_null(group, "sample_ratio"),
                    "coverage_estimate": _first_non_null(group, "coverage_estimate") or run_meta.get("coverage_estimate"),
                    "random_seed": _first_non_null(group, "random_seed") or run_meta.get("random_seed"),
                    "null_count": values.get("null_count") if values.get("null_count") is not None else artifact_column.get("null_count"),
                    "blank_count": values.get("blank_count") if values.get("blank_count") is not None else artifact_column.get("blank_count"),
                    "distinct_count": values.get("distinct_count") if values.get("distinct_count") is not None else artifact_column.get("distinct_count"),
                    "miscast_count": type_conformance.get("miscast_count") if type_conformance else artifact_column.get("miscast_count"),
                    "miscast_ratio": evidence.get("miscast_ratio") or artifact_column.get("miscast_ratio"),
                    "top_values": evidence.get("top_values") or artifact_column.get("top_values_detail"),
                    "patterns": evidence.get("patterns") or artifact_column.get("patterns_detail"),
                    "length_summary": evidence.get("length_summary") or artifact_column.get("length_summary"),
                    "numeric_summary": evidence.get("numeric_summary") or artifact_column.get("numeric_summary"),
                    "miscast_examples": evidence.get("miscast_examples") or artifact_column.get("miscast_examples"),
                }
            )
    frame = pd.DataFrame(rows)
    for column in ("top_values", "miscast_examples"):
        if column in frame.columns:
            frame[column] = frame[column].map(_mask_sensitive_value)
    return _ensure_columns(frame, _profile_evidence_columns())

def _column_breakdown(rules: pd.DataFrame, issues: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "target_column",
        "quality_status",
        "rules_total",
        "failed_rules",
        "avg_rule_score",
        "min_rule_score",
        "dimensions",
        "failed_rule_ids",
        "issue_count",
    ]
    if rules.empty and issues.empty:
        return pd.DataFrame(columns=columns)

    frames: list[pd.DataFrame] = []
    if not rules.empty and "target_column" in rules.columns:
        rule_frame = rules.copy()
        rule_frame["target_column"] = rule_frame["target_column"].fillna("__dataset__").astype(str)
        rule_frame["_rule_score"] = pd.to_numeric(rule_frame["rule_score"] if "rule_score" in rule_frame.columns else pd.Series(index=rule_frame.index, dtype=float), errors="coerce")
        rule_frame["_is_failed"] = rule_frame.get("quality_status", pd.Series(index=rule_frame.index, dtype=object)).eq("fail")
        grouped = rule_frame.groupby("target_column", dropna=False)
        summary = grouped.agg(
            rules_total=("rule_id", "count"),
            failed_rules=("_is_failed", "sum"),
            avg_rule_score=("_rule_score", "mean"),
            min_rule_score=("_rule_score", "min"),
        ).reset_index()
        summary["dimensions"] = grouped["dimension"].apply(_join_unique_values).values if "dimension" in rule_frame.columns else ""
        summary["failed_rule_ids"] = grouped.apply(_failed_rule_ids).values
        frames.append(summary)

    if not issues.empty and "target_column" in issues.columns:
        issue_frame = issues.copy()
        issue_frame["target_column"] = issue_frame["target_column"].fillna("__dataset__").astype(str)
        issue_counts = issue_frame.groupby("target_column").size().rename("issue_count").reset_index()
        frames.append(issue_counts)

    if not frames:
        return pd.DataFrame(columns=columns)
    result = frames[0]
    for frame in frames[1:]:
        result = result.merge(frame, on="target_column", how="outer")
    for column in ("rules_total", "failed_rules", "issue_count"):
        if column not in result.columns:
            result[column] = 0
        result[column] = result[column].fillna(0).astype(int)
    for column in ("avg_rule_score", "min_rule_score"):
        if column not in result.columns:
            result[column] = None
    for column in ("dimensions", "failed_rule_ids"):
        if column not in result.columns:
            result[column] = ""
        result[column] = result[column].fillna("")
    result["quality_status"] = result.apply(_column_quality_status, axis=1)
    return _ensure_columns(result.sort_values(["failed_rules", "issue_count", "target_column"], ascending=[False, False, True]), columns)


def _record_breakdown(issues: pd.DataFrame) -> pd.DataFrame:
    columns = ["record_key", "issue_count", "affected_columns", "rule_codes", "issue_types"]
    if issues.empty or "record_key" not in issues.columns:
        return pd.DataFrame(columns=columns)
    frame = issues.copy()
    frame["record_key"] = frame["record_key"].fillna("<unknown>").astype(str)
    grouped = frame.groupby("record_key", dropna=False)
    result = grouped.size().rename("issue_count").reset_index()
    result["affected_columns"] = grouped["target_column"].apply(_join_unique_values).values if "target_column" in frame.columns else ""
    result["rule_codes"] = grouped["rule_code"].apply(_join_unique_values).values if "rule_code" in frame.columns else ""
    result["issue_types"] = grouped["issue_type"].apply(_join_unique_values).values if "issue_type" in frame.columns else ""
    return _ensure_columns(result.sort_values(["issue_count", "record_key"], ascending=[False, True]), columns)


def _column_quality_status(row: pd.Series) -> str:
    if int(row.get("failed_rules") or 0) > 0 or int(row.get("issue_count") or 0) > 0:
        return "fail"
    if int(row.get("rules_total") or 0) > 0:
        return "pass"
    return "not_available"


def _join_unique_values(values: pd.Series) -> str:
    unique = sorted({str(value) for value in values.dropna() if str(value)})
    return ", ".join(unique)


def _failed_rule_ids(group: pd.DataFrame) -> str:
    if "quality_status" not in group.columns or "rule_id" not in group.columns:
        return ""
    failed = group[group["quality_status"].eq("fail")]
    return _join_unique_values(failed["rule_id"])

def _mask_sensitive_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return value
    if isinstance(value, list):
        return [_mask_sensitive_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_mask_sensitive_value(item) for item in value)
    if isinstance(value, dict):
        return {key: _mask_sensitive_value(item) if isinstance(item, (str, list, tuple, dict)) else item for key, item in value.items()}
    if isinstance(value, str):
        if value == "":
            return "<empty>"
        if len(value) <= 2:
            return "***"
        return f"{value[:2]}***"
    return value


def _exclude_internal_test_data(
    datasets: pd.DataFrame,
    versions: pd.DataFrame,
    score_runs: pd.DataFrame,
    profiling_runs: pd.DataFrame,
    recommendation_runs: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if datasets.empty or "dataset_id" not in datasets.columns:
        return datasets, versions, score_runs, profiling_runs, recommendation_runs
    visible_datasets = datasets[~_is_internal_dataset_id(datasets["dataset_id"])].copy()
    if versions.empty or "dataset_id" not in versions.columns:
        return visible_datasets, versions, score_runs, profiling_runs, recommendation_runs
    visible_dataset_ids = set(visible_datasets["dataset_id"].astype(str))
    visible_versions = versions[versions["dataset_id"].astype(str).isin(visible_dataset_ids)].copy()
    visible_version_ids = set(visible_versions["dataset_version_id"].astype(str)) if "dataset_version_id" in visible_versions.columns else set()
    if not score_runs.empty and "dataset_version_id" in score_runs.columns:
        score_runs = score_runs[score_runs["dataset_version_id"].astype(str).isin(visible_version_ids)].copy()
    if not profiling_runs.empty and "dataset_version_id" in profiling_runs.columns:
        profiling_runs = profiling_runs[profiling_runs["dataset_version_id"].astype(str).isin(visible_version_ids)].copy()
    if not recommendation_runs.empty and "dataset_version_id" in recommendation_runs.columns:
        recommendation_runs = recommendation_runs[recommendation_runs["dataset_version_id"].astype(str).isin(visible_version_ids)].copy()
    return visible_datasets, visible_versions, score_runs, profiling_runs, recommendation_runs
def _is_internal_dataset_id(values: pd.Series) -> pd.Series:
    return values.astype(str).str.startswith("it_dataset_", na=False)

def _artifact_column(profile_json: dict[str, Any], column_name: str) -> dict[str, Any]:
    columns = profile_json.get("column_profile") if isinstance(profile_json, dict) else None
    if not isinstance(columns, list):
        return {}
    for item in columns:
        if isinstance(item, dict) and item.get("column_name") == column_name:
            return item
    return {}


def _metric_value(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _first_non_null(frame: pd.DataFrame, column: str) -> Any:
    if column not in frame.columns:
        return None
    values = frame[column].dropna()
    return None if values.empty else values.iloc[0]


def _empty_frames() -> DashboardFrames:
    return DashboardFrames(
        score_runs=pd.DataFrame(columns=_score_run_columns()),
        dataset_scores=pd.DataFrame(columns=_dataset_score_columns()),
        dimension_scores=pd.DataFrame(columns=_dimension_score_columns()),
        rule_scores=pd.DataFrame(columns=_rule_score_columns()),
        rule_runs=pd.DataFrame(columns=_rule_run_columns()),
        rule_configs=pd.DataFrame(columns=_rule_config_columns()),
        issue_samples=pd.DataFrame(columns=_issue_sample_columns()),
        profile_evidence=pd.DataFrame(columns=_profile_evidence_columns()),
        recommendation_results=pd.DataFrame(columns=_recommendation_columns()),
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
    return ["run_id", "dataset_id", "dataset_name", "dataset_version", "run_timestamp", "dq_core_score", "quality_gate_status", "measurement_coverage", "score_status", "validation_scope", "measured_dimension_count", "total_dimension_count", "total_records", "rules_total", "rules_failed", "measured_dimensions", "excluded_dimensions", "score_level"]


def _dimension_score_columns() -> list[str]:
    return ["run_id", "dimension", "dimension_score", "original_dimension_weight", "dimension_weight", "is_measured", "measurement_status", "rules_total", "rules_failed", "rules_warning", "rules_passed"]


def _rule_score_columns() -> list[str]:
    return ["run_id", "rule_id", "dimension", "target_column", "rule_score", "threshold", "quality_status", "passed", "failed", "miscast", "empty", "not_applicable", "total_records_in_scope", "measurement_status", "evaluated_count", "conflict_group", "primary_scoring_rule", "score_enabled", "measurement_status_reason", "contribution"]


def _rule_run_columns() -> list[str]:
    return ["rule_run_id", "dataset_id", "dataset_version", "run_timestamp", "execution_engine", "source_path", "rule_config_path", "status", "total_rules", "measured_rules", "not_measured_rules", "skipped_rules", "error_message"]


def _rule_config_columns() -> list[str]:
    return ["rule_id", "binding_id", "dataset_version_id", "rule_template_id", "rule_name", "rule_type", "dimension", "target_column", "severity", "score_enabled", "backend", "status"]


def _issue_sample_columns() -> list[str]:
    return ["rule_id", "record_key", "target_column", "actual_value", "expected_condition", "issue_type", "rule_code", "sampled_at"]


def _profile_evidence_columns() -> list[str]:
    return ["run_id", "profiling_run_id", "dataset_version_id", "column_name", "inferred_type", "inferred_type_confidence", "metric_scope", "scan_mode", "sample_method", "sample_size", "sample_ratio", "coverage_estimate", "random_seed", "null_count", "blank_count", "distinct_count", "miscast_count", "miscast_ratio", "top_values", "patterns", "length_summary", "numeric_summary", "miscast_examples"]



def _recommendation_columns() -> list[str]:
    return ["recommendation_id", "recommendation_run_id", "dataset_version_id", "column_id", "rule_template_id", "rule_code", "family", "dimension", "target_columns", "candidate_score", "score_components_jsonb", "reason", "rank", "score_margin", "ambiguity_status", "review_status", "suggested_parameters_jsonb", "warnings", "source", "editable", "catalog_revision", "status"]









