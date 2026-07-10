from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from profiling.models import ColumnProfile, DatasetProfile, iso, utc_now


@dataclass(frozen=True)
class ProfileMetric:
    run_id: str
    dataset_id: str
    column_name: str | None
    metric_name: str
    metric_value: Any
    metric_source: str
    gx_expectation_type: str | None = None
    metric_scope: str = "full"
    is_approximate: bool = False
    sample_size: int | None = None
    sample_ratio: float | None = None
    random_seed: int | None = None
    coverage_estimate: float | None = None
    collected_at: str = field(default_factory=lambda: iso(utc_now()) or "")

    def to_record(self) -> dict[str, Any]:
        return self.__dict__.copy()


def build_profile_metrics(dataset_profile: DatasetProfile, column_profiles: list[ColumnProfile]) -> list[ProfileMetric]:
    metrics: list[ProfileMetric] = [
        ProfileMetric(dataset_profile.run_id, dataset_profile.dataset_id, None, "row_count", dataset_profile.row_count, "pandas"),
        ProfileMetric(dataset_profile.run_id, dataset_profile.dataset_id, None, "column_count", dataset_profile.column_count, "pandas"),
        ProfileMetric(dataset_profile.run_id, dataset_profile.dataset_id, None, "duplicate_row_count", dataset_profile.duplicate_row_count, "pandas"),
        ProfileMetric(dataset_profile.run_id, dataset_profile.dataset_id, None, "duplicate_row_ratio", dataset_profile.duplicate_row_ratio, "pandas"),
    ]
    for profile in column_profiles:
        metrics.extend(_column_metrics(profile))
    return metrics


def _column_metrics(profile: ColumnProfile) -> list[ProfileMetric]:
    total_count = profile.non_null_count + profile.null_count
    missing_count = profile.null_count + profile.blank_count
    missing_percent = round(missing_count / total_count, 6) if total_count else 0.0
    base = [
        ("inferred_type", profile.inferred_data_type, "pandas", None),
        ("null_count", profile.null_count, "pandas", None),
        ("null_ratio", profile.null_ratio, "pandas", None),
        ("blank_count", profile.blank_count, "pandas", None),
        ("distinct_count", profile.distinct_count, "pandas", None),
        ("distinct_ratio", profile.uniqueness_ratio, "pandas", None),
        ("min", profile.min_value, "pandas", None),
        ("max", profile.max_value, "pandas", None),
        ("mean", profile.mean_value, "pandas", None),
        ("top_values", profile.top_values, "pandas", None),
        ("pattern_sample", profile.pattern_frequency, "pandas", None),
        ("string_length", profile.length_distribution, "pandas", None),
        ("element_count", total_count, "gx", "expect_column_values_to_not_be_null"),
        ("missing_count", missing_count, "gx", "expect_column_values_to_not_be_null"),
        ("missing_percent", missing_percent, "gx", "expect_column_values_to_not_be_null"),
        ("observed_min", profile.min_value, "gx", "expect_column_min_to_be_between"),
        ("observed_max", profile.max_value, "gx", "expect_column_max_to_be_between"),
        ("uniqueness_evidence", {"distinct_count": profile.distinct_count, "uniqueness_ratio": profile.uniqueness_ratio}, "gx", "expect_column_values_to_be_unique"),
        ("type_conformance", {"inferred_type": profile.inferred_data_type, "miscast_count": profile.miscast_count}, "gx", "expect_column_values_to_be_of_type"),
        ("profile_evidence", {
            "metric_scope": profile.metric_scope,
            "non_null_count": profile.non_null_count,
            "distinct_count_including_null": profile.distinct_count_including_null,
            "trimmed_blank_count": profile.trimmed_blank_count,
            "miscast_ratio": profile.miscast_ratio,
            "inferred_type_confidence": profile.inferred_type_confidence,
            "inferred_type_evidence": profile.inferred_type_evidence,
            "top_values": profile.top_values_detail,
            "patterns": profile.patterns_detail,
            "length_summary": profile.length_summary,
            "numeric_summary": profile.numeric_summary,
            "miscast_examples": profile.miscast_examples,
        }, "pandas", None),
    ]
    return [
        ProfileMetric(
            profile.run_id,
            profile.dataset_id,
            profile.column_name,
            name,
            value,
            source,
            expectation,
            metric_scope=profile.metric_scope,
            is_approximate=profile.metric_scope != "full",
            sample_size=total_count if profile.metric_scope != "full" else None,
        )
        for name, value, source, expectation in base
    ]
