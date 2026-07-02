from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from dashboard.data import (
    aggregate_latest_status_counts,
    dataset_runs,
    latest_dataset_scores,
    load_dashboard_frames,
    run_details,
    score_summary_metrics,
)
from dashboard.generate_demo_data import generate_demo_data


class DashboardDataTests(unittest.TestCase):
    def test_latest_scores_details_and_issue_join(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rules_store = root / "rules.db"
            score_store = root / "scores.db"
            export_dir = root / "exports"

            generate_demo_data(["customer_master", "retail_sales_dataset"], rules_store, score_store, export_dir)
            generate_demo_data(["customer_master"], rules_store, score_store, export_dir)

            frames = load_dashboard_frames(score_store, rules_store)
            latest = latest_dataset_scores(frames)
            self.assertEqual(set(latest["dataset_id"]), {"customer_master", "retail_sales_dataset"})
            self.assertEqual(len(latest), 2)

            counts = aggregate_latest_status_counts(frames)
            self.assertEqual(sum(counts.values()), 2)

            customer_runs = dataset_runs(frames, "customer_master")
            self.assertEqual(len(customer_runs), 2)
            details = run_details(frames, str(customer_runs.iloc[0]["run_id"]))
            metrics = score_summary_metrics(details["dataset_score"])
            self.assertEqual(metrics["quality_gate_status"], "pass")
            self.assertGreater(metrics["rules_failed"], 0)

            dimensions = details["dimensions"]
            consistency = dimensions[dimensions["dimension"] == "Consistency"].iloc[0]
            self.assertEqual(consistency["measurement_status"], "not_measured")
            self.assertTrue(pd.isna(consistency["dimension_score"]))

            rules = details["rules"]
            self.assertIn("rule_name", rules.columns)
            self.assertIn("severity", rules.columns)
            self.assertGreater(len(details["issues"]), 0)
            self.assertIn("rule_name", details["issues"].columns)

    def test_demo_generator_exports_json_for_all_datasets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            summaries = generate_demo_data(
                ["all"],
                root / "rules.db",
                root / "scores.db",
                root / "exports",
            )

            dataset_ids = {summary["dataset_id"] for summary in summaries}
            self.assertEqual(dataset_ids, {"customer_master", "amazon_products", "retail_sales_dataset"})
            for summary in summaries:
                export_path = Path(str(summary["export_json"]))
                self.assertTrue(export_path.exists())
                self.assertIsNotNone(summary["dq_core_score"])


if __name__ == "__main__":
    unittest.main()
