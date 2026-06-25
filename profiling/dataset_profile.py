from __future__ import annotations

from datetime import datetime, timezone
from time import perf_counter
from typing import Any

import pandas as pd

from profiling.models import DatasetConfig, DatasetProfile


def profile_dataset(
    df: pd.DataFrame,
    config: DatasetConfig,
    run_id: str | None = None,
    started_at: float | None = None,
    baseline: dict[str, Any] | None = None,
) -> DatasetProfile:
    run_id = run_id or "RUN_PREVIEW"
    started_at = started_at if started_at is not None else perf_counter()
    profiling_timestamp = datetime.now(timezone.utc)
    row_count = len(df)
    duplicate_row_count = int(df.duplicated().sum()) if row_count else 0
    expected_row_count = _expected_row_count(config, baseline)
    volume_deviation_rate = _volume_deviation(row_count, expected_row_count)
    last_updated_timestamp, freshness_lag = _freshness(df, config, profiling_timestamp)

    return DatasetProfile(
        run_id=run_id,
        dataset_id=config.dataset_id,
        row_count=row_count,
        column_count=len(df.columns),
        duplicate_row_count=duplicate_row_count,
        duplicate_row_ratio=round(duplicate_row_count / row_count, 6) if row_count else 0.0,
        last_updated_timestamp=last_updated_timestamp,
        profiling_timestamp=profiling_timestamp.isoformat(),
        freshness_time_basis=config.freshness_time_basis,
        freshness_lag=freshness_lag,
        expected_row_count=expected_row_count,
        volume_deviation_rate=volume_deviation_rate,
        profile_duration_seconds=round(perf_counter() - started_at, 6),
    )


def _freshness(
    df: pd.DataFrame, config: DatasetConfig, profiling_timestamp: datetime
) -> tuple[str | None, float | None]:
    column = config.timestamp_column
    if not column or column not in df.columns or df.empty:
        return None, None
    timestamps = pd.to_datetime(df[column], errors="coerce").dropna()
    if timestamps.empty:
        return None, None
    latest = timestamps.max()
    latest_dt = latest.to_pydatetime()
    if latest_dt.tzinfo is None:
        latest_dt = latest_dt.replace(tzinfo=timezone.utc)
    lag_hours = (profiling_timestamp - latest_dt).total_seconds() / 3600
    return latest_dt.isoformat(), round(lag_hours, 6)


def _expected_row_count(config: DatasetConfig, baseline: dict[str, Any] | None) -> int | None:
    if config.sla_config.get("expected_row_count") is not None:
        return int(config.sla_config["expected_row_count"])
    if baseline and baseline.get("row_count") is not None:
        return int(baseline["row_count"])
    return None


def _volume_deviation(row_count: int, expected_row_count: int | None) -> float | None:
    if not expected_row_count:
        return None
    return round(abs(row_count - expected_row_count) / expected_row_count, 6)
