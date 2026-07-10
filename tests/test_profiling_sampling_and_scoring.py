from __future__ import annotations

import unittest

import pandas as pd

from dq_core.models import CanonicalValidationResult, DatasetRuleBinding, MeasurementResult, RecordMeasurementSummary, RuleTemplate, ScoringPolicy
from profiling.column_profile import profile_columns
from profiling.models import DatasetConfig, ProfilingConfig
from profiling.sampling import sample_dataset
from scoring.v2 import calculate_scores


class ProfilingSamplingScoringTests(unittest.TestCase):
    def test_profile_separates_null_blank_leading_zero_and_miscast(self) -> None:
        frame = pd.DataFrame({"code": ["001", "002", "", None, "ABC"]})
        config = DatasetConfig(
            dataset_id="ds",
            dataset_name=None,
            dataset_type="default",
            source_type="csv",
            storage_path="memory.csv",
            declared_schema={"code": {"data_type": "integer"}},
        )
        profile = profile_columns(frame, config)[0]

        self.assertEqual(profile.null_count, 1)
        self.assertEqual(profile.blank_count, 1)
        self.assertEqual(profile.non_null_count, 4)
        self.assertEqual(profile.inferred_data_type, "mixed")
        self.assertGreaterEqual(profile.inferred_type_evidence["leading_zero_ratio"], 0.4)
        self.assertEqual(profile.miscast_count, 1)
        self.assertIn("***", profile.miscast_examples[0])
        self.assertTrue(profile.top_values_detail)
        self.assertIn("metric_scope", profile.to_record())

    def test_sampling_records_scope_seed_and_coverage(self) -> None:
        frame = pd.DataFrame({"id": range(300)})
        config = DatasetConfig(
            dataset_id="ds",
            dataset_name=None,
            dataset_type="default",
            source_type="csv",
            storage_path="memory.csv",
            profiling_config=ProfilingConfig(sampling_method="random", sample_fraction=0.2, min_sample_size=10, random_seed=7),
        )
        sample, info = sample_dataset(frame, config)

        self.assertTrue(info.is_sampled)
        self.assertEqual(info.scan_mode, "sampled")
        self.assertTrue(str(info.sample_method).startswith("mixed_head_tail_random"))
        self.assertEqual(info.random_seed, 7)
        self.assertAlmostEqual(info.coverage_estimate or 0, len(sample) / len(frame))

    def test_wide_dataset_uses_sampled_scope_for_three_hundred_columns(self) -> None:
        frame = pd.DataFrame({f"col_{index:03d}": range(100) for index in range(300)})
        config = DatasetConfig(
            dataset_id="wide_ds",
            dataset_name=None,
            dataset_type="default",
            source_type="csv",
            storage_path="memory.csv",
            profiling_config=ProfilingConfig(sampling_method="auto", sample_fraction=0.2, min_sample_size=10, random_seed=11),
        )

        sample, info = sample_dataset(frame, config)
        profiles = profile_columns(sample, config, run_id="PRUN-WIDE", metric_scope=info.scan_mode)

        self.assertTrue(info.is_sampled)
        self.assertEqual(info.scan_mode, "sampled")
        self.assertTrue(str(info.sample_method).startswith("mixed_head_tail_random"))
        self.assertEqual(len(profiles), 300)
        self.assertTrue(all(profile.metric_scope == "sampled" for profile in profiles))
    def test_scoring_coverage_and_conflict_resolution(self) -> None:
        template_a = RuleTemplate("RT-A", "NOT_NULL", 1, "general", "Completeness", "framework", "column", "record", "not_blank", conflict_group="mandatory")
        template_b = RuleTemplate("RT-B", "NOT_BLANK", 1, "general", "Completeness", "framework", "column", "record", "not_blank", conflict_group="mandatory")
        binding_a = DatasetRuleBinding("BR-A", "DV-1", "RT-A", ["id"], scoring_pass_threshold=99, severity="high", conflict_group="mandatory")
        binding_b = DatasetRuleBinding("BR-B", "DV-1", "RT-B", ["id"], scoring_pass_threshold=99, severity="high", conflict_group="mandatory", primary_scoring_rule=False)
        validation = CanonicalValidationResult(
            "VRUN-1",
            "DV-1",
            [
                MeasurementResult("MR-A", "VRUN-1", "BR-A", "record", False, "measured"),
                MeasurementResult("MR-B", "VRUN-1", "BR-B", "record", False, "measured"),
            ],
            [RecordMeasurementSummary("MR-A", 90, 10, 0, 0, 100), RecordMeasurementSummary("MR-B", 50, 50, 0, 0, 100)],
        )
        policy = ScoringPolicy("SP", "default", {"Completeness": 1.0, "Validity": 1.0, "Uniqueness": 1.0})

        result = calculate_scores(validation, policy, {"BR-A": binding_a, "BR-B": binding_b}, {"RT-A": template_a, "RT-B": template_b})

        self.assertEqual(result.rule_scores[0].rule_score, 90.0)
        self.assertFalse(next(score for score in result.rule_scores if score.binding_id == "BR-B").primary_scoring_rule)
        self.assertEqual(result.dataset_score.measured_dimension_count, 1)
        self.assertEqual(result.dataset_score.total_dimension_count, 3)
        self.assertEqual(result.dataset_score.score_status, "provisional")
        self.assertIn("dimension_weights", result.policy_snapshot)

    def test_not_measured_is_not_zero(self) -> None:
        template = RuleTemplate("RT-A", "RANGE", 1, "general", "Validity", "framework", "column", "record", "range")
        binding = DatasetRuleBinding("BR-A", "DV-1", "RT-A", ["amount"])
        validation = CanonicalValidationResult(
            "VRUN-1",
            "DV-1",
            [MeasurementResult("MR-A", "VRUN-1", "BR-A", "record", None, "not_measured", measurement_status_reason="no_applicable_records")],
            [RecordMeasurementSummary("MR-A", 0, 0, 0, 0, 0)],
        )
        policy = ScoringPolicy("SP", "default", {"Validity": 1.0})

        result = calculate_scores(validation, policy, {"BR-A": binding}, {"RT-A": template})

        self.assertIsNone(result.rule_scores[0].rule_score)
        self.assertEqual(result.rule_scores[0].quality_status, "not_measured")
        self.assertIsNone(result.dataset_score.dataset_dq_score)


if __name__ == "__main__":
    unittest.main()

