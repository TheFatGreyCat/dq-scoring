from __future__ import annotations

import unittest
from unittest.mock import patch

from dashboard.data import aggregate_latest_status_counts, dataset_runs, latest_dataset_scores, load_dashboard_frames, run_details, score_summary_metrics


class FakeRepository:
    def __init__(self, database_url=None):
        pass

    def list_dashboard_rows(self):
        return {
            "dataset": [{"dataset_id": "customer_master", "dataset_name": "Customer", "dataset_type": "customer", "source_type": "csv", "storage_path": "x"}],
            "dataset_version": [{"dataset_version_id": "DV-1", "dataset_id": "customer_master", "version_label": "v1"}],
            "validation_run": [{"validation_run_id": "VRUN-1", "dataset_version_id": "DV-1"}],
            "score_run": [{"score_run_id": "SRUN-1", "validation_run_id": "VRUN-1", "scoring_policy_id": "SP-1", "dataset_version_id": "DV-1", "status": "success", "created_at": "2026-01-01T00:00:00Z"}],
            "dataset_score_history": [{"score_run_id": "SRUN-1", "dataset_dq_score": 91.5, "quality_gate_status": "pass", "measured_dimensions": ["Completeness"], "excluded_dimensions": []}],
            "dimension_score_history": [{"score_run_id": "SRUN-1", "dimension": "Completeness", "dimension_score": 91.5, "original_dimension_weight": 1.0, "normalized_dimension_weight": 1.0, "measurement_status": "measured"}],
            "rule_score_history": [{"score_run_id": "SRUN-1", "binding_id": "BR-1", "dimension": "Completeness", "rule_score": 91.5, "measurement_status": "measured", "quality_status": "pass"}],
            "dataset_rule_binding": [{"binding_id": "BR-1", "dataset_version_id": "DV-1", "rule_template_id": "RT-1", "target_columns": ["customer_id"], "severity": "high", "backend": "gx", "status": "active", "score_enabled": True}],
            "rule_template": [{"rule_template_id": "RT-1", "rule_code": "NOT_BLANK", "operator": "not_blank", "dimension": "Completeness", "rule_category": "general"}],
            "rule_issue_sample": [],
            "pipeline_log": [],
        }


class DashboardDataTests(unittest.TestCase):
    def test_load_dashboard_frames_from_postgres_rows(self) -> None:
        with patch("dashboard.data.DqPostgresRepository", FakeRepository):
            frames = load_dashboard_frames("postgresql://test")

        latest = latest_dataset_scores(frames)
        self.assertEqual(latest.iloc[0]["dataset_id"], "customer_master")
        self.assertEqual(aggregate_latest_status_counts(frames), {"pass": 1})

        runs = dataset_runs(frames, "customer_master")
        self.assertEqual(len(runs), 1)
        details = run_details(frames, "SRUN-1")
        metrics = score_summary_metrics(details["dataset_score"])
        self.assertEqual(metrics["dq_core_score"], 91.5)
        self.assertEqual(metrics["quality_gate_status"], "pass")
        self.assertEqual(details["rules"].iloc[0]["rule_name"], "NOT_BLANK")


if __name__ == "__main__":
    unittest.main()
