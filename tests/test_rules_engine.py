from __future__ import annotations

import unittest

import pandas as pd

from dq_core.models import DatasetRuleBinding
from validation.gx_runtime import GxRuntimeEvaluator


class GxRuntimeTests(unittest.TestCase):

    def test_gx_regex_runtime_returns_canonical_counts(self) -> None:
        frame = pd.DataFrame({"email": ["a@example.com", "bad", "", None]})
        binding = DatasetRuleBinding("BR-email", "DV-1", "RT-email", ["email"], backend="gx")
        evaluator = GxRuntimeEvaluator()
        measurement, summary = evaluator.evaluate(
            frame,
            "VRUN-1",
            binding,
            "regex",
            {"pattern": r"^[^@]+@[^@]+\.[^@]+$"},
            null_policy="separate",
            rule_code="EMAIL_FORMAT",
        )
        self.assertEqual(measurement.backend, "gx")
        self.assertEqual(summary.passed_count, 1)
        self.assertEqual(summary.failed_count, 1)
        self.assertEqual(summary.missing_count, 2)
        self.assertEqual(summary.records_in_scope, 2)
        self.assertEqual(len(evaluator.last_issue_samples), 3)
        self.assertEqual(evaluator.last_issue_samples[0].rule_code, "EMAIL_FORMAT")


    def test_gx_null_policy_fail_includes_missing_in_denominator(self) -> None:
        frame = pd.DataFrame({"email": ["a@example.com", "bad", "", None]})
        binding = DatasetRuleBinding("BR-email", "DV-1", "RT-email", ["email"], backend="gx")
        measurement, summary = GxRuntimeEvaluator().evaluate(
            frame,
            "VRUN-1",
            binding,
            "regex",
            {"pattern": r"^[^@]+@[^@]+\.[^@]+$"},
            null_policy="fail",
            rule_code="EMAIL_FORMAT",
        )

        self.assertFalse(measurement.expectation_success)
        self.assertEqual(summary.passed_count, 1)
        self.assertEqual(summary.failed_count, 1)
        self.assertEqual(summary.missing_count, 2)
        self.assertEqual(summary.records_in_scope, 4)

    def test_gx_null_policy_ignore_excludes_missing_from_denominator(self) -> None:
        frame = pd.DataFrame({"email": ["a@example.com", "bad", "", None]})
        binding = DatasetRuleBinding("BR-email", "DV-1", "RT-email", ["email"], backend="gx")
        _, summary = GxRuntimeEvaluator().evaluate(
            frame,
            "VRUN-1",
            binding,
            "regex",
            {"pattern": r"^[^@]+@[^@]+\.[^@]+$"},
            null_policy="ignore",
            rule_code="EMAIL_FORMAT",
        )

        self.assertEqual(summary.missing_count, 0)
        self.assertEqual(summary.not_applicable_count, 2)
        self.assertEqual(summary.records_in_scope, 2)

    def test_gx_uniqueness_runtime_flags_duplicates(self) -> None:
        frame = pd.DataFrame({"id": ["1", "2", "2", ""]})
        binding = DatasetRuleBinding("BR-id", "DV-1", "RT-id", ["id"], backend="gx")
        _, summary = GxRuntimeEvaluator().evaluate(frame, "VRUN-1", binding, "uniqueness", {}, null_policy="ignore")
        self.assertEqual(summary.passed_count, 1)
        self.assertEqual(summary.failed_count, 2)
        self.assertEqual(summary.not_applicable_count, 1)


if __name__ == "__main__":
    unittest.main()
