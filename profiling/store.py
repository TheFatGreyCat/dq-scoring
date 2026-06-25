from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from profiling.models import ProfileResult

DEFAULT_STORE_PATH = Path("data/profile_store/dq_profile.db")


class ProfileStore:
    def __init__(self, path: str | Path = DEFAULT_STORE_PATH) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def store_profile_result(self, result: ProfileResult) -> str:
        with closing(sqlite3.connect(self.path)) as conn:
            with conn:
                self._insert(conn, "profiling_run", result.profiling_run.to_record())
                dataset_record = result.dataset_profile.to_record()
                dataset_record["schema_profile"] = result.schema_profile.to_record()
                self._insert(conn, "dataset_profile", dataset_record)
                for profile in result.column_profiles:
                    self._insert(conn, "column_profile", profile.to_record())
                for candidate in result.candidate_rules:
                    self._insert(conn, "candidate_rule", candidate.to_record())
                for anomaly in result.anomaly_flags:
                    self._insert(conn, "anomaly_flag", anomaly.to_record())
        return result.profiling_run.run_id

    def latest_baseline(self, dataset_id: str) -> dict[str, Any] | None:
        with closing(sqlite3.connect(self.path)) as conn:
            conn.row_factory = sqlite3.Row
            with conn:
                dataset_row = conn.execute(
                    """
                    SELECT * FROM dataset_profile
                    WHERE dataset_id = ?
                    ORDER BY profiling_timestamp DESC
                    LIMIT 1
                    """,
                    (dataset_id,),
                ).fetchone()
                if dataset_row is None:
                    return None
                run_id = dataset_row["run_id"]
                columns = conn.execute(
                    "SELECT * FROM column_profile WHERE run_id = ? ORDER BY column_name",
                    (run_id,),
                ).fetchall()
        return {
            **dict(dataset_row),
            "columns": [_decode_record(dict(row)) for row in columns],
        }

    def _init_schema(self) -> None:
        with closing(sqlite3.connect(self.path)) as conn:
            with conn:
                conn.executescript(
                    """
                CREATE TABLE IF NOT EXISTS profiling_run (
                    run_id TEXT PRIMARY KEY,
                    dataset_id TEXT NOT NULL,
                    dataset_version TEXT,
                    run_timestamp TEXT NOT NULL,
                    execution_engine TEXT NOT NULL,
                    source_path TEXT NOT NULL,
                    schema_version TEXT,
                    sampling_method TEXT NOT NULL,
                    is_sampled INTEGER NOT NULL,
                    sample_fraction REAL,
                    sample_size INTEGER NOT NULL,
                    total_rows INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    error_message TEXT
                );

                CREATE TABLE IF NOT EXISTS dataset_profile (
                    run_id TEXT PRIMARY KEY,
                    dataset_id TEXT NOT NULL,
                    row_count INTEGER NOT NULL,
                    column_count INTEGER NOT NULL,
                    duplicate_row_count INTEGER NOT NULL,
                    duplicate_row_ratio REAL NOT NULL,
                    last_updated_timestamp TEXT,
                    profiling_timestamp TEXT NOT NULL,
                    freshness_time_basis TEXT,
                    freshness_lag REAL,
                    expected_row_count INTEGER,
                    volume_deviation_rate REAL,
                    profile_duration_seconds REAL,
                    schema_profile TEXT
                );

                CREATE TABLE IF NOT EXISTS column_profile (
                    run_id TEXT NOT NULL,
                    dataset_id TEXT NOT NULL,
                    column_name TEXT NOT NULL,
                    declared_data_type TEXT,
                    inferred_data_type TEXT NOT NULL,
                    null_count INTEGER NOT NULL,
                    null_ratio REAL NOT NULL,
                    blank_count INTEGER NOT NULL,
                    distinct_count INTEGER NOT NULL,
                    uniqueness_ratio REAL NOT NULL,
                    min_value TEXT,
                    max_value TEXT,
                    mean_value REAL,
                    std_value REAL,
                    p25 REAL,
                    p50 REAL,
                    p75 REAL,
                    p99 REAL,
                    top_values TEXT,
                    pattern_frequency TEXT,
                    length_distribution TEXT,
                    miscast_count INTEGER NOT NULL,
                    PRIMARY KEY (run_id, column_name)
                );

                CREATE TABLE IF NOT EXISTS candidate_rule (
                    candidate_rule_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    dataset_id TEXT NOT NULL,
                    column_name TEXT,
                    dimension TEXT NOT NULL,
                    rule_type TEXT NOT NULL,
                    expectation_type TEXT,
                    proposed_threshold REAL NOT NULL,
                    confidence REAL NOT NULL,
                    evidence TEXT,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (candidate_rule_id, run_id)
                );

                CREATE TABLE IF NOT EXISTS anomaly_flag (
                    anomaly_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    dataset_id TEXT NOT NULL,
                    column_name TEXT,
                    anomaly_type TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    description TEXT NOT NULL,
                    current_value TEXT,
                    baseline_value TEXT,
                    detected_at TEXT NOT NULL,
                    PRIMARY KEY (anomaly_id, run_id)
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


def store_profile_result(result: ProfileResult, path: str | Path = DEFAULT_STORE_PATH) -> str:
    return ProfileStore(path).store_profile_result(result)


def _encode_value(value: Any) -> Any:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value


def _decode_record(record: dict[str, Any]) -> dict[str, Any]:
    for key in ("top_values", "pattern_frequency", "length_distribution", "schema_profile"):
        if key in record and isinstance(record[key], str) and record[key]:
            record[key] = json.loads(record[key])
    return record
