from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from scoring.models import ScoringResult

DEFAULT_SCORE_STORE_PATH = Path("data/score_store/dq_scores.db")


class ScoreStore:
    def __init__(self, path: str | Path = DEFAULT_SCORE_STORE_PATH) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def store_scoring_result(self, result: ScoringResult) -> str:
        with closing(sqlite3.connect(self.path)) as conn:
            with conn:
                self._insert(conn, "score_run", result.score_run.to_record())
                for score in result.rule_score_history:
                    self._insert(conn, "rule_score_history", score.to_record())
                for score in result.dimension_score_history:
                    self._insert(conn, "dimension_score_history", score.to_record())
                self._insert(conn, "dataset_score_history", result.dataset_score_history.to_record())
        return result.score_run.run_id

    def _init_schema(self) -> None:
        with closing(sqlite3.connect(self.path)) as conn:
            with conn:
                conn.executescript(
                    """
                CREATE TABLE IF NOT EXISTS score_run (
                    run_id TEXT PRIMARY KEY,
                    rule_run_id TEXT NOT NULL,
                    dataset_id TEXT NOT NULL,
                    run_timestamp TEXT NOT NULL,
                    scoring_config_path TEXT,
                    status TEXT NOT NULL,
                    rules_total INTEGER NOT NULL,
                    rules_scored INTEGER NOT NULL,
                    dimensions_measured INTEGER NOT NULL,
                    error_message TEXT
                );

                CREATE TABLE IF NOT EXISTS rule_score_history (
                    run_id TEXT NOT NULL,
                    dataset_id TEXT NOT NULL,
                    rule_id TEXT NOT NULL,
                    dimension TEXT,
                    target_column TEXT,
                    passed INTEGER NOT NULL,
                    failed INTEGER NOT NULL,
                    miscast INTEGER NOT NULL,
                    empty INTEGER NOT NULL,
                    not_applicable INTEGER NOT NULL,
                    total_records_in_scope INTEGER NOT NULL,
                    rule_score REAL,
                    threshold REAL,
                    measurement_status TEXT NOT NULL,
                    quality_status TEXT NOT NULL,
                    PRIMARY KEY (run_id, rule_id)
                );

                CREATE TABLE IF NOT EXISTS dimension_score_history (
                    run_id TEXT NOT NULL,
                    dataset_id TEXT NOT NULL,
                    dimension TEXT NOT NULL,
                    dimension_score REAL,
                    original_dimension_weight REAL NOT NULL,
                    dimension_weight REAL NOT NULL,
                    is_measured INTEGER NOT NULL,
                    measurement_status TEXT NOT NULL,
                    rules_total INTEGER NOT NULL,
                    rules_failed INTEGER NOT NULL,
                    rules_warning INTEGER NOT NULL,
                    rules_passed INTEGER NOT NULL,
                    PRIMARY KEY (run_id, dimension)
                );

                CREATE TABLE IF NOT EXISTS dataset_score_history (
                    run_id TEXT PRIMARY KEY,
                    dataset_id TEXT NOT NULL,
                    dataset_version TEXT,
                    run_timestamp TEXT NOT NULL,
                    dq_core_score REAL,
                    quality_gate_status TEXT NOT NULL,
                    total_records INTEGER NOT NULL,
                    rules_total INTEGER NOT NULL,
                    rules_failed INTEGER NOT NULL,
                    measured_dimensions TEXT,
                    excluded_dimensions TEXT,
                    score_level TEXT NOT NULL
                );
                """
                )

    @staticmethod
    def _insert(conn: sqlite3.Connection, table: str, record: dict[str, Any]) -> None:
        encoded = {key: _encode_value(value) for key, value in record.items()}
        columns = ", ".join(encoded)
        placeholders = ", ".join("?" for _ in encoded)
        conn.execute(
            f"INSERT OR REPLACE INTO {table} ({columns}) VALUES ({placeholders})",
            tuple(encoded.values()),
        )


def store_scoring_result(result: ScoringResult, path: str | Path = DEFAULT_SCORE_STORE_PATH) -> str:
    return ScoreStore(path).store_scoring_result(result)


def _encode_value(value: Any) -> Any:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value

