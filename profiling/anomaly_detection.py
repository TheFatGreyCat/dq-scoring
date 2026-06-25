from __future__ import annotations

from profiling.models import AnomalyFlag, ColumnProfile, DatasetConfig, DatasetProfile


def detect_anomalies(
    dataset_profile: DatasetProfile,
    column_profiles: list[ColumnProfile],
    baseline: dict | None,
    config: DatasetConfig,
) -> list[AnomalyFlag]:
    if not config.profiling_config.enable_basic_anomaly_detection:
        return []
    thresholds = {
        "null_spike_delta": 0.10,
        "volume_deviation": 0.30,
        "pattern_shift_delta": 0.20,
        "miscast_ratio": 0.01,
        **config.profiling_config.thresholds,
    }
    anomalies: list[AnomalyFlag] = []
    if dataset_profile.volume_deviation_rate is not None and dataset_profile.volume_deviation_rate >= thresholds["volume_deviation"]:
        anomalies.append(
            AnomalyFlag(
                anomaly_id=f"ANOM-VOLUME-{dataset_profile.run_id}",
                run_id=dataset_profile.run_id,
                dataset_id=config.dataset_id,
                column_name=None,
                anomaly_type="volume_anomaly",
                severity=_severity(dataset_profile.volume_deviation_rate, 0.30, 0.50),
                description="Row count deviates from expected row count",
                current_value=str(dataset_profile.row_count),
                baseline_value=str(dataset_profile.expected_row_count),
            )
        )

    baseline_columns = {item["column_name"]: item for item in (baseline or {}).get("columns", [])}
    for column in column_profiles:
        anomalies.extend(_column_anomalies(column, baseline_columns.get(column.column_name), thresholds, config))
    return anomalies


def _column_anomalies(
    column: ColumnProfile,
    baseline: dict | None,
    thresholds: dict[str, float],
    config: DatasetConfig,
) -> list[AnomalyFlag]:
    anomalies: list[AnomalyFlag] = []
    if baseline:
        baseline_null_ratio = float(baseline.get("null_ratio") or 0.0)
        if column.null_ratio - baseline_null_ratio >= thresholds["null_spike_delta"]:
            anomalies.append(
                AnomalyFlag(
                    anomaly_id=f"ANOM-NULL-{column.run_id}-{column.column_name}",
                    run_id=column.run_id,
                    dataset_id=config.dataset_id,
                    column_name=column.column_name,
                    anomaly_type="null_spike",
                    severity=_severity(column.null_ratio - baseline_null_ratio, 0.10, 0.25),
                    description="Null ratio increased compared with baseline",
                    current_value=str(column.null_ratio),
                    baseline_value=str(baseline_null_ratio),
                )
            )

        pattern, ratio = _dominant(column.pattern_frequency)
        baseline_pattern, baseline_ratio = _dominant(baseline.get("pattern_frequency") or {})
        if pattern != baseline_pattern or abs(ratio - baseline_ratio) >= thresholds["pattern_shift_delta"]:
            if pattern and baseline_pattern:
                anomalies.append(
                    AnomalyFlag(
                        anomaly_id=f"ANOM-PATTERN-{column.run_id}-{column.column_name}",
                        run_id=column.run_id,
                        dataset_id=config.dataset_id,
                        column_name=column.column_name,
                        anomaly_type="pattern_shift",
                        severity=_severity(abs(ratio - baseline_ratio), 0.20, 0.40),
                        description="Dominant pattern shifted compared with baseline",
                        current_value=f"{pattern}:{ratio}",
                        baseline_value=f"{baseline_pattern}:{baseline_ratio}",
                    )
                )

    non_empty_count = max(1, int(round(column.distinct_count / column.uniqueness_ratio))) if column.uniqueness_ratio else 1
    miscast_ratio = column.miscast_count / non_empty_count
    if miscast_ratio >= thresholds["miscast_ratio"]:
        anomalies.append(
            AnomalyFlag(
                anomaly_id=f"ANOM-TYPE-{column.run_id}-{column.column_name}",
                run_id=column.run_id,
                dataset_id=config.dataset_id,
                column_name=column.column_name,
                anomaly_type="type_anomaly",
                severity=_severity(miscast_ratio, 0.01, 0.05),
                description="Miscast ratio is above configured threshold",
                current_value=str(round(miscast_ratio, 6)),
                baseline_value=str(thresholds["miscast_ratio"]),
            )
        )
    if column.inferred_data_type == "numeric" and None not in (column.min_value, column.max_value, column.p25, column.p75):
        q1 = float(column.p25 or 0.0)
        q3 = float(column.p75 or 0.0)
        iqr = q3 - q1
        if iqr > 0:
            lower = q1 - 1.5 * iqr
            upper = q3 + 1.5 * iqr
            min_value = float(column.min_value or 0.0)
            max_value = float(column.max_value or 0.0)
            if min_value < lower or max_value > upper:
                anomalies.append(
                    AnomalyFlag(
                        anomaly_id=f"ANOM-OUTLIER-{column.run_id}-{column.column_name}",
                        run_id=column.run_id,
                        dataset_id=config.dataset_id,
                        column_name=column.column_name,
                        anomaly_type="numeric_outlier",
                        severity="medium",
                        description="Numeric min/max is outside the IQR expected range",
                        current_value=f"{min_value}..{max_value}",
                        baseline_value=f"{round(lower, 6)}..{round(upper, 6)}",
                    )
                )
    return anomalies


def _dominant(values: dict[str, float]) -> tuple[str | None, float]:
    if not values:
        return None, 0.0
    key = max(values, key=values.get)
    return key, float(values[key])


def _severity(value: float, medium_at: float, high_at: float) -> str:
    if value >= high_at:
        return "high"
    if value >= medium_at:
        return "medium"
    return "low"
