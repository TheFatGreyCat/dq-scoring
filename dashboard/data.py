from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


DEFAULT_SCORE_STORE_PATH = Path("data/score_store/dq_scores.db")
DEFAULT_RULE_STORE_PATH = Path("data/rules_store/dq_rules.db")


@dataclass(frozen=True)
class DashboardFrames:
    score_runs: pd.DataFrame
    dataset_scores: pd.DataFrame
    dimension_scores: pd.DataFrame
    rule_scores: pd.DataFrame
    rule_runs: pd.DataFrame
    rule_configs: pd.DataFrame
    issue_samples: pd.DataFrame


def load_dashboard_frames(
    score_store_path: str | Path = DEFAULT_SCORE_STORE_PATH,
    rule_store_path: str | Path = DEFAULT_RULE_STORE_PATH,
) -> DashboardFrames:
    score_store = Path(score_store_path)
    rule_store = Path(rule_store_path)
    score_runs = _read_table(score_store, "score_run", _score_run_columns())
    dataset_scores = _read_table(score_store, "dataset_score_history", _dataset_score_columns())
    dimension_scores = _read_table(score_store, "dimension_score_history", _dimension_score_columns())
    rule_scores = _read_table(score_store, "rule_score_history", _rule_score_columns())
    rule_runs = _read_table(rule_store, "rule_run", _rule_run_columns())
    rule_configs = _read_table(rule_store, "rule_config", _rule_config_columns())
    issue_samples = _read_table(rule_store, "rule_issue_sample", _issue_sample_columns())

    dataset_scores = _decode_json_columns(dataset_scores, ["measured_dimensions", "excluded_dimensions"])
    return DashboardFrames(
        score_runs=score_runs,
        dataset_scores=_with_datetime(dataset_scores, "run_timestamp"),
        dimension_scores=dimension_scores,
        rule_scores=rule_scores,
        rule_runs=_with_datetime(rule_runs, "run_timestamp"),
        rule_configs=rule_configs,
        issue_samples=issue_samples,
    )


def latest_dataset_scores(frames: DashboardFrames) -> pd.DataFrame:
    scores = frames.dataset_scores.copy()
    if scores.empty:
        return scores
    scores = scores.sort_values(["dataset_id", "run_timestamp", "run_id"])
    latest = scores.groupby("dataset_id", as_index=False).tail(1)
    return latest.sort_values("dataset_id").reset_index(drop=True)


def dataset_runs(frames: DashboardFrames, dataset_id: str) -> pd.DataFrame:
    scores = frames.dataset_scores
    if scores.empty:
        return scores.copy()
    rows = scores[scores["dataset_id"] == dataset_id].copy()
    return rows.sort_values(["run_timestamp", "run_id"], ascending=[False, False]).reset_index(drop=True)


def run_details(frames: DashboardFrames, run_id: str) -> dict[str, Any]:
    dataset_score = frames.dataset_scores[frames.dataset_scores["run_id"] == run_id].copy()
    score_run = frames.score_runs[frames.score_runs["run_id"] == run_id].copy()
    rule_run_id = _first_value(score_run, "rule_run_id")

    dimensions = frames.dimension_scores[frames.dimension_scores["run_id"] == run_id].copy()
    rules = frames.rule_scores[frames.rule_scores["run_id"] == run_id].copy()
    if rule_run_id and not frames.rule_configs.empty:
        configs = frames.rule_configs[frames.rule_configs["rule_run_id"] == rule_run_id]
        config_cols = ["rule_id", "rule_name", "rule_type", "severity", "score_enabled"]
        rules = rules.merge(configs[config_cols], on="rule_id", how="left")

    issues = pd.DataFrame(columns=_issue_sample_columns())
    if rule_run_id and not frames.issue_samples.empty:
        issues = frames.issue_samples[frames.issue_samples["rule_run_id"] == rule_run_id].copy()
        if not frames.rule_configs.empty:
            configs = frames.rule_configs[frames.rule_configs["rule_run_id"] == rule_run_id]
            issues = issues.merge(configs[["rule_id", "rule_name", "severity"]], on="rule_id", how="left")

    return {
        "dataset_score": dataset_score.reset_index(drop=True),
        "score_run": score_run.reset_index(drop=True),
        "rule_run_id": rule_run_id,
        "dimensions": dimensions.sort_values("dimension").reset_index(drop=True),
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
        return {
            "dq_core_score": None,
            "quality_gate_status": "not_available",
            "total_records": 0,
            "rules_total": 0,
            "rules_failed": 0,
        }
    row = dataset_score.iloc[0]
    return {
        "dq_core_score": row.get("dq_core_score"),
        "quality_gate_status": row.get("quality_gate_status"),
        "total_records": int(row.get("total_records") or 0),
        "rules_total": int(row.get("rules_total") or 0),
        "rules_failed": int(row.get("rules_failed") or 0),
    }


def _read_table(path: Path, table: str, columns: list[str]) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=columns)
    with closing(sqlite3.connect(path)) as conn:
        if not _table_exists(conn, table):
            return pd.DataFrame(columns=columns)
        return pd.read_sql_query(f"SELECT * FROM {table}", conn)


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _decode_json_columns(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    decoded = frame.copy()
    for column in columns:
        if column in decoded.columns:
            decoded[column] = decoded[column].map(_decode_json_value)
    return decoded


def _decode_json_value(value: Any) -> Any:
    if value is None or isinstance(value, list):
        return value
    if pd.isna(value):
        return []
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else value
        except json.JSONDecodeError:
            return value
    return value


def _with_datetime(frame: pd.DataFrame, column: str) -> pd.DataFrame:
    converted = frame.copy()
    if column in converted.columns and not converted.empty:
        converted[column] = pd.to_datetime(converted[column], errors="coerce", utc=True)
    return converted


def _first_value(frame: pd.DataFrame, column: str) -> Any:
    if frame.empty or column not in frame.columns:
        return None
    return frame.iloc[0][column]


def _sort_rules(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.reset_index(drop=True)
    columns = [column for column in ["quality_status", "dimension", "rule_id"] if column in frame.columns]
    return frame.sort_values(columns).reset_index(drop=True) if columns else frame.reset_index(drop=True)


def _score_run_columns() -> list[str]:
    return [
        "run_id",
        "rule_run_id",
        "dataset_id",
        "run_timestamp",
        "scoring_config_path",
        "status",
        "rules_total",
        "rules_scored",
        "dimensions_measured",
        "error_message",
    ]


def _dataset_score_columns() -> list[str]:
    return [
        "run_id",
        "dataset_id",
        "dataset_version",
        "run_timestamp",
        "dq_core_score",
        "quality_gate_status",
        "total_records",
        "rules_total",
        "rules_failed",
        "measured_dimensions",
        "excluded_dimensions",
        "score_level",
    ]


def _dimension_score_columns() -> list[str]:
    return [
        "run_id",
        "dataset_id",
        "dimension",
        "dimension_score",
        "original_dimension_weight",
        "dimension_weight",
        "is_measured",
        "measurement_status",
        "rules_total",
        "rules_failed",
        "rules_warning",
        "rules_passed",
    ]


def _rule_score_columns() -> list[str]:
    return [
        "run_id",
        "dataset_id",
        "rule_id",
        "dimension",
        "target_column",
        "passed",
        "failed",
        "miscast",
        "empty",
        "not_applicable",
        "total_records_in_scope",
        "rule_score",
        "threshold",
        "measurement_status",
        "quality_status",
    ]


def _rule_run_columns() -> list[str]:
    return [
        "rule_run_id",
        "dataset_id",
        "dataset_version",
        "run_timestamp",
        "execution_engine",
        "source_path",
        "rule_config_path",
        "status",
        "total_rules",
        "measured_rules",
        "not_measured_rules",
        "skipped_rules",
        "error_message",
    ]


def _rule_config_columns() -> list[str]:
    return [
        "rule_run_id",
        "rule_id",
        "dataset_id",
        "rule_type",
        "status",
        "score_enabled",
        "rule_name",
        "description",
        "target_table",
        "target_column",
        "dimension",
        "scope_filter",
        "parameters",
        "null_policy",
        "threshold",
        "severity",
        "execution_backend",
        "created_by",
        "created_at",
        "updated_at",
        "mask_actual_value",
    ]


def _issue_sample_columns() -> list[str]:
    return [
        "rule_run_id",
        "rule_id",
        "dataset_id",
        "record_key",
        "target_column",
        "actual_value",
        "expected_condition",
        "issue_type",
        "sampled_at",
    ]
