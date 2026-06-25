from __future__ import annotations

from profiling.models import CandidateRule, ColumnProfile, DatasetConfig, DatasetProfile


def generate_candidate_rules(
    dataset_profile: DatasetProfile,
    column_profiles: list[ColumnProfile],
    config: DatasetConfig,
) -> list[CandidateRule]:
    if not config.profiling_config.enable_candidate_rule_generation:
        return []
    thresholds = {
        "not_null_max_null_ratio": 0.01,
        "unique_min_ratio": 0.98,
        "pattern_min_ratio": 0.90,
        "domain_max_distinct": 20,
        "domain_max_uniqueness_ratio": 0.50,
        **config.profiling_config.thresholds,
    }

    candidates: list[CandidateRule] = []
    for column in column_profiles:
        candidates.extend(_column_candidates(column, config, thresholds))

    if config.timestamp_column and dataset_profile.freshness_lag is not None:
        candidates.append(
            CandidateRule(
                candidate_rule_id=f"CAND-TIME-{config.dataset_id}-{config.timestamp_column}",
                run_id=dataset_profile.run_id,
                dataset_id=config.dataset_id,
                column_name=config.timestamp_column,
                dimension="Timeliness",
                rule_type="freshness",
                expectation_type=None,
                proposed_threshold=float(config.sla_config.get("max_freshness_lag_hours", 24)),
                confidence=0.80,
                evidence={"freshness_lag": dataset_profile.freshness_lag},
            )
        )
    return _dedupe(candidates)


def _column_candidates(
    column: ColumnProfile, config: DatasetConfig, thresholds: dict[str, float]
) -> list[CandidateRule]:
    rules: list[CandidateRule] = []
    if column.null_ratio <= thresholds["not_null_max_null_ratio"]:
        confidence = 0.95 if column.column_name in config.mandatory_fields else 0.75
        rules.append(
            CandidateRule(
                candidate_rule_id=f"CAND-COMP-{config.dataset_id}-{column.column_name}",
                run_id=column.run_id,
                dataset_id=config.dataset_id,
                column_name=column.column_name,
                dimension="Completeness",
                rule_type="not_null",
                expectation_type="expect_column_values_to_not_be_null",
                proposed_threshold=1.0 - thresholds["not_null_max_null_ratio"],
                confidence=confidence,
                evidence={"null_ratio": column.null_ratio, "blank_count": column.blank_count},
            )
        )

    if column.uniqueness_ratio >= thresholds["unique_min_ratio"]:
        rules.append(
            CandidateRule(
                candidate_rule_id=f"CAND-UNIQ-{config.dataset_id}-{column.column_name}",
                run_id=column.run_id,
                dataset_id=config.dataset_id,
                column_name=column.column_name,
                dimension="Uniqueness",
                rule_type="uniqueness",
                expectation_type="expect_column_values_to_be_unique",
                proposed_threshold=thresholds["unique_min_ratio"],
                confidence=min(0.99, column.uniqueness_ratio),
                evidence={"uniqueness_ratio": column.uniqueness_ratio, "distinct_count": column.distinct_count},
            )
        )

    if column.inferred_data_type == "numeric" and column.min_value is not None and column.max_value is not None:
        rules.append(
            CandidateRule(
                candidate_rule_id=f"CAND-RANGE-{config.dataset_id}-{column.column_name}",
                run_id=column.run_id,
                dataset_id=config.dataset_id,
                column_name=column.column_name,
                dimension="Accuracy Proxy",
                rule_type="range",
                expectation_type="expect_column_values_to_be_between",
                proposed_threshold=0.90,
                confidence=0.70,
                evidence={"min_value": column.min_value, "max_value": column.max_value, "p25": column.p25, "p75": column.p75},
            )
        )

    dominant_pattern, pattern_ratio = _dominant(column.pattern_frequency)
    if dominant_pattern and pattern_ratio >= thresholds["pattern_min_ratio"]:
        rules.append(
            CandidateRule(
                candidate_rule_id=f"CAND-VALI-PATTERN-{config.dataset_id}-{column.column_name}",
                run_id=column.run_id,
                dataset_id=config.dataset_id,
                column_name=column.column_name,
                dimension="Validity",
                rule_type="regex",
                expectation_type="expect_column_values_to_match_regex",
                proposed_threshold=thresholds["pattern_min_ratio"],
                confidence=min(0.95, pattern_ratio),
                evidence={"dominant_pattern": dominant_pattern, "dominant_pattern_ratio": pattern_ratio},
            )
        )

    if (
        column.distinct_count > 0
        and column.distinct_count <= thresholds["domain_max_distinct"]
        and column.uniqueness_ratio <= thresholds["domain_max_uniqueness_ratio"]
    ):
        rules.append(
            CandidateRule(
                candidate_rule_id=f"CAND-DOMAIN-{config.dataset_id}-{column.column_name}",
                run_id=column.run_id,
                dataset_id=config.dataset_id,
                column_name=column.column_name,
                dimension="Validity",
                rule_type="domain",
                expectation_type="expect_column_values_to_be_in_set",
                proposed_threshold=0.98,
                confidence=0.75,
                evidence={"distinct_count": column.distinct_count, "top_values": column.top_values},
            )
        )
    return rules


def _dominant(values: dict[str, float]) -> tuple[str | None, float]:
    if not values:
        return None, 0.0
    key = max(values, key=values.get)
    return key, values[key]


def _dedupe(candidates: list[CandidateRule]) -> list[CandidateRule]:
    seen: set[str] = set()
    result: list[CandidateRule] = []
    for candidate in candidates:
        if candidate.candidate_rule_id not in seen:
            result.append(candidate)
            seen.add(candidate.candidate_rule_id)
    return result
