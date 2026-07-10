from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from profiling.adaptive import profile_csv_in_chunks
from profiling.column_profile import profile_columns
from profiling.models import DatasetConfig, ProfilingConfig
from profiling.semantic_detection import detect_semantics
from rules_engine.benchmark import calculate_metrics
from rules_engine.catalog import backend_coverage_matrix, catalog_inventory, default_rule_templates, recommend_rules, validate_catalog


class RuleCatalogChunkedProfilingTests(unittest.TestCase):
    def test_rule_catalog_has_lifecycle_metadata_and_backend_coverage(self) -> None:
        templates = default_rule_templates()
        active = [item for item in templates if item.lifecycle_status == "active"]
        families = {item.family for item in active}

        self.assertGreaterEqual(len(active), 15)
        self.assertGreaterEqual(len(families), 6)
        self.assertFalse(validate_catalog(templates))
        self.assertTrue(all(item.backend_support for item in active))
        self.assertTrue(any(row["python"] for row in backend_coverage_matrix(templates)))
        self.assertTrue(any(row["gx"] for row in backend_coverage_matrix(templates)))
        inventory = catalog_inventory(templates)
        self.assertIn("lifecycle_status", inventory[0])

    def test_deterministic_recommendation_has_score_components_and_ambiguity(self) -> None:
        frame = pd.DataFrame({"customer_id": ["C001", "C002", "C003"], "email": ["a@example.com", "b@example.com", "c@example.com"]})
        config = DatasetConfig(
            dataset_id="customer",
            dataset_name=None,
            dataset_type="customer",
            source_type="csv",
            storage_path="memory.csv",
            primary_key=["customer_id"],
            mandatory_fields=["customer_id", "email"],
            cde_fields=["email"],
        )
        profiles = profile_columns(frame, config, run_id="REC-TEST")
        semantics = detect_semantics(profiles)
        recommendations = recommend_rules(profiles, semantics, config, default_rule_templates(), recommendation_run_id="RREC-1")
        email = next(item for item in recommendations if item.rule_template_id == "RT-VALI-EMAIL")

        self.assertIsNotNone(email.recommendation_id)
        self.assertGreater(email.candidate_score or 0, 0.8)
        self.assertIn("semantic_match", email.score_components)
        self.assertEqual(email.review_status, "suggested")
        self.assertEqual(email.ambiguity_status, "clear")
        self.assertEqual(email.rank, 1)

    def test_benchmark_metrics(self) -> None:
        results = [
            {"target_columns": ["email"], "rule_code": "EMAIL_FORMAT", "rank": 1, "ambiguity_status": "clear"},
            {"target_columns": ["email"], "rule_code": "NOT_BLANK_MANDATORY", "rank": 2, "ambiguity_status": "clear"},
            {"target_columns": ["amount"], "rule_code": "AMOUNT_NON_NEGATIVE", "rank": 1, "ambiguity_status": "ambiguous"},
        ]
        truth = {
            "email": {"expected_rules": ["EMAIL_FORMAT"], "forbidden_rules": [], "requires_review": False},
            "amount": {"expected_rules": ["AMOUNT_NON_NEGATIVE"], "forbidden_rules": [], "requires_review": True},
        }

        metrics = calculate_metrics(results, truth)

        self.assertEqual(metrics["recall_at_3"], 1.0)
        self.assertGreater(metrics["mrr"], 0.9)
        self.assertEqual(metrics["ambiguous_column_detection_recall"], 1.0)

    def test_chunked_csv_profile_records_incremental_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "large.csv"
            frame = pd.DataFrame({"id": range(120), "amount": [str(i) if i % 10 else "bad" for i in range(120)], "note": ["" if i % 7 == 0 else "ok" for i in range(120)]})
            frame.to_csv(path, index=False)
            config = DatasetConfig(
                dataset_id="sales",
                dataset_name=None,
                dataset_type="sales",
                source_type="csv",
                storage_path=str(path),
                profiling_config=ProfilingConfig(chunk_size=25, memory_budget_mb=1, random_seed=3),
            )

            summary = profile_csv_in_chunks(path, config)

        self.assertEqual(summary.row_count, 120)
        self.assertEqual(summary.column_count, 3)
        self.assertGreater(summary.null_counts["note"], 0)
        self.assertLess(summary.parse_ratio["amount"], 1.0)
        self.assertEqual(summary.metadata["profile_strategy"], "chunked_budget")
        self.assertGreater(len(summary.sample), 0)


if __name__ == "__main__":
    unittest.main()