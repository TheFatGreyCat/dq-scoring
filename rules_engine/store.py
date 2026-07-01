from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from rules_engine.models import RulesEngineResult

DEFAULT_RULE_STORE_PATH = Path("data/rules_store/dq_rules.db")


class RuleStore:
    def __init__(self, path: str | Path = DEFAULT_RULE_STORE_PATH) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def store_rules_engine_result(self, result: RulesEngineResult) -> str:
        with closing(sqlite3.connect(self.path)) as conn:
            with conn:
                self._insert(conn, "rule_run", result.rule_run.to_record())
                for rule in result.rule_configs:
                    record = rule.to_record()
                    record["rule_run_id"] = result.rule_run.rule_run_id
                    self._insert(conn, "rule_config", record)
                for evaluation in result.rule_evaluation_results:
                    self._insert(conn, "rule_evaluation_result", evaluation.to_record())
                for sample in result.rule_issue_samples:
                    self._insert(conn, "rule_issue_sample", sample.to_record())
        return result.rule_run.rule_run_id

    def _init_schema(self) -> None:
        with closing(sqlite3.connect(self.path)) as conn:
            with conn:
                conn.executescript(
                    """
                CREATE TABLE IF NOT EXISTS rule_run (
                    rule_run_id TEXT PRIMARY KEY,
                    dataset_id TEXT NOT NULL,
                    dataset_version TEXT,
                    run_timestamp TEXT NOT NULL,
                    execution_engine TEXT NOT NULL,
                    source_path TEXT NOT NULL,
                    rule_config_path TEXT NOT NULL,
                    status TEXT NOT NULL,
                    total_rules INTEGER NOT NULL,
                    measured_rules INTEGER NOT NULL,
                    not_measured_rules INTEGER NOT NULL,
                    skipped_rules INTEGER NOT NULL,
                    error_message TEXT
                );

                CREATE TABLE IF NOT EXISTS rule_config (
                    rule_run_id TEXT NOT NULL,
                    rule_id TEXT NOT NULL,
                    dataset_id TEXT NOT NULL,
                    rule_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    score_enabled INTEGER NOT NULL,
                    rule_name TEXT,
                    description TEXT,
                    target_table TEXT,
                    target_column TEXT,
                    dimension TEXT,
                    scope_filter TEXT,
                    parameters TEXT,
                    null_policy TEXT,
                    threshold REAL,
                    severity TEXT,
                    execution_backend TEXT,
                    created_by TEXT,
                    created_at TEXT,
                    updated_at TEXT,
                    mask_actual_value INTEGER,
                    PRIMARY KEY (rule_run_id, rule_id)
                );

                CREATE TABLE IF NOT EXISTS rule_evaluation_result (
                    rule_run_id TEXT NOT NULL,
                    rule_id TEXT NOT NULL,
                    dataset_id TEXT NOT NULL,
                    target_table TEXT,
                    target_column TEXT,
                    dimension TEXT,
                    evaluation_unit TEXT NOT NULL,
                    passed INTEGER NOT NULL,
                    failed INTEGER NOT NULL,
                    miscast INTEGER NOT NULL,
                    empty INTEGER NOT NULL,
                    not_applicable INTEGER NOT NULL,
                    total_records_in_scope INTEGER NOT NULL,
                    threshold REAL,
                    measurement_status TEXT NOT NULL,
                    error_message TEXT,
                    evaluated_at TEXT NOT NULL,
                    PRIMARY KEY (rule_run_id, rule_id)
                );

                CREATE TABLE IF NOT EXISTS rule_issue_sample (
                    rule_run_id TEXT NOT NULL,
                    rule_id TEXT NOT NULL,
                    dataset_id TEXT NOT NULL,
                    record_key TEXT,
                    target_column TEXT,
                    actual_value TEXT,
                    expected_condition TEXT,
                    issue_type TEXT,
                    sampled_at TEXT
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


def store_rules_engine_result(result: RulesEngineResult, path: str | Path = DEFAULT_RULE_STORE_PATH) -> str:
    return RuleStore(path).store_rules_engine_result(result)


def _encode_value(value: Any) -> Any:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value
