from __future__ import annotations

import unittest
from unittest.mock import patch

from dashboard.data import _mask_sensitive_value, aggregate_latest_status_counts, dataset_dashboard_rows, dataset_runs, latest_dataset_scores, load_dashboard_frames, run_details, score_summary_metrics


class FakeRepository:
    def __init__(self, database_url=None):
        pass

    def list_dashboard_rows(self):
        return {
            "dataset": [{"dataset_id": "customer_master", "dataset_name": "Customer", "dataset_type": "customer", "source_type": "csv", "storage_path": "x"}, {"dataset_id": "it_dataset_deadbeef", "dataset_name": "Integration Dataset", "dataset_type": "integration", "source_type": "csv", "storage_path": "memory.csv"}],
            "dataset_version": [{"dataset_version_id": "DV-1", "dataset_id": "customer_master", "version_label": "v1"}, {"dataset_version_id": "DV-deadbeef", "dataset_id": "it_dataset_deadbeef", "version_label": "v1"}],
            "validation_run": [{"validation_run_id": "VRUN-1", "dataset_version_id": "DV-1"}],
            "score_run": [{"score_run_id": "SRUN-1", "validation_run_id": "VRUN-1", "scoring_policy_id": "SP-1", "dataset_version_id": "DV-1", "status": "success", "created_at": "2026-01-01T00:00:00Z"}, {"score_run_id": "SRUN-IT", "validation_run_id": "VRUN-IT", "scoring_policy_id": "SP-IT", "dataset_version_id": "DV-deadbeef", "status": "success", "created_at": "2026-01-02T00:00:00Z"}],
            "dataset_score_history": [{"score_run_id": "SRUN-1", "dataset_dq_score": 91.5, "quality_gate_status": "pass", "measured_dimensions": ["Completeness"], "excluded_dimensions": []}, {"score_run_id": "SRUN-IT", "dataset_dq_score": 90, "quality_gate_status": "fail", "measured_dimensions": ["Completeness"], "excluded_dimensions": []}],
            "dimension_score_history": [{"score_run_id": "SRUN-1", "dimension": "Completeness", "dimension_score": 91.5, "original_dimension_weight": 1.0, "normalized_dimension_weight": 1.0, "measurement_status": "measured"}],
            "rule_score_history": [{"score_run_id": "SRUN-1", "binding_id": "BR-1", "dimension": "Completeness", "rule_score": 91.5, "measurement_status": "measured", "quality_status": "pass"}],
            "dataset_rule_binding": [{"binding_id": "BR-1", "dataset_version_id": "DV-1", "rule_template_id": "RT-1", "target_columns": ["customer_id"], "severity": "high", "backend": "gx", "status": "active", "score_enabled": True}],
            "rule_template": [{"rule_template_id": "RT-1", "rule_code": "NOT_BLANK", "operator": "not_blank", "dimension": "Completeness", "rule_category": "general"}],
            "rule_issue_sample": [{"validation_run_id": "VRUN-1", "binding_id": "BR-1", "record_key": "row-2-secret", "target_column": "customer_id", "actual_value": "", "expected_condition": "NOT_BLANK", "issue_type": "empty", "rule_code": "NOT_BLANK", "sampled_at": "2026-01-01T00:00:00Z"}],
            "profiling_run": [{"profiling_run_id": "PRUN-1", "dataset_version_id": "DV-1", "status": "success", "started_at": "2026-01-01T00:00:00Z", "completed_at": "2026-01-01T00:01:00Z", "scan_mode": "sampled", "sample_method": "mixed_head_tail_random", "coverage_estimate": 0.25, "random_seed": 7}],
            "dataset_profile": [{"profiling_run_id": "PRUN-1", "row_count": 100, "column_count": 1, "duplicate_row_count": 0, "duplicate_row_ratio": 0, "profile_json": {"column_profile": [{"column_name": "customer_id", "inferred_data_type": "integer_like_string", "miscast_count": 1}]}}],
            "column_profile": [
                {"profiling_run_id": "PRUN-1", "column_name": "customer_id", "metric_name": "inferred_type", "metric_value": "integer_like_string", "metric_source": "pandas", "metric_scope": "sampled", "sample_size": 25, "sample_ratio": 0.25, "random_seed": 7, "coverage_estimate": 0.25},
                {"profiling_run_id": "PRUN-1", "column_name": "customer_id", "metric_name": "null_count", "metric_value": 1, "metric_source": "pandas", "metric_scope": "sampled"},
                {"profiling_run_id": "PRUN-1", "column_name": "customer_id", "metric_name": "blank_count", "metric_value": 2, "metric_source": "pandas", "metric_scope": "sampled"},
                {"profiling_run_id": "PRUN-1", "column_name": "customer_id", "metric_name": "distinct_count", "metric_value": 20, "metric_source": "pandas", "metric_scope": "sampled"},
                {"profiling_run_id": "PRUN-1", "column_name": "customer_id", "metric_name": "type_conformance", "metric_value": {"inferred_type": "integer_like_string", "miscast_count": 1}, "metric_source": "gx", "metric_scope": "sampled"},
                {"profiling_run_id": "PRUN-1", "column_name": "customer_id", "metric_name": "profile_evidence", "metric_value": {"metric_scope": "sampled", "inferred_type_confidence": 0.98, "miscast_ratio": 0.04, "patterns": [{"pattern": "999", "ratio": 1.0}], "top_values": [{"value": "001", "count": 3}], "miscast_examples": ["ABC123"]}, "metric_source": "pandas", "metric_scope": "sampled"},
            ],
            "rule_recommendation_run": [{"recommendation_run_id": "RREC-1", "dataset_version_id": "DV-1", "catalog_revision": "cat-1", "status": "success"}],
            "rule_recommendation_result": [{"recommendation_id": "REC-1", "recommendation_run_id": "RREC-1", "column_id": "customer_id", "rule_template_id": "RT-1", "target_columns": ["customer_id"], "candidate_score": 0.91, "score_components_jsonb": {"semantic_match": 0.8}, "reason_jsonb": {"matched": ["mandatory=True"]}, "reason": "Recommend NOT_BLANK", "rank": 1, "score_margin": 0.25, "ambiguity_status": "clear", "decision": "accepted", "suggested_parameters_jsonb": {}, "warnings": [], "source": "framework_auto", "editable": True}],
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
        self.assertEqual(metrics["measurement_coverage"], 1.0)
        self.assertEqual(metrics["rules_total"], 1)
        self.assertEqual(metrics["rules_failed"], 0)
        self.assertEqual(details["rules"].iloc[0]["rule_name"], "NOT_BLANK")
        self.assertEqual(details["column_breakdown"].iloc[0]["target_column"], "customer_id")
        self.assertEqual(details["column_breakdown"].iloc[0]["rules_total"], 1)
        self.assertEqual(details["column_breakdown"].iloc[0]["issue_count"], 1)
        self.assertEqual(details["record_breakdown"].iloc[0]["record_key"], "ro***")
        self.assertEqual(details["record_breakdown"].iloc[0]["issue_count"], 1)
        self.assertEqual(details["record_breakdown"].iloc[0]["affected_columns"], "customer_id")

        view_rows = dataset_dashboard_rows(frames)
        self.assertEqual(len(view_rows), 1)
        self.assertNotIn("it_dataset_deadbeef", latest["dataset_id"].tolist())
        self.assertEqual(view_rows[0].dataset_id, "customer_master")
        self.assertEqual(view_rows[0].dataset_name, "Customer")
        self.assertEqual(view_rows[0].dataset_version_id, "DV-1")
        self.assertEqual(view_rows[0].dq_score, 91.5)
        self.assertEqual(details["issues"].iloc[0]["rule_code"], "NOT_BLANK")
        self.assertEqual(details["issues"].iloc[0]["record_key"], "ro***")
        self.assertEqual(details["issues"].iloc[0]["actual_value"], "<empty>")
        self.assertEqual(details["recommendations"].iloc[0]["rule_code"], "NOT_BLANK")
        self.assertEqual(details["recommendations"].iloc[0]["review_status"], "accepted")
        self.assertEqual(details["recommendations"].iloc[0]["dataset_version_id"], "DV-1")
        self.assertEqual(details["profile_evidence"].iloc[0]["column_name"], "customer_id")
        self.assertEqual(details["profile_evidence"].iloc[0]["inferred_type"], "integer_like_string")
        self.assertEqual(details["profile_evidence"].iloc[0]["metric_scope"], "sampled")
        self.assertEqual(details["profile_evidence"].iloc[0]["miscast_count"], 1)
        self.assertEqual(details["profile_evidence"].iloc[0]["top_values"][0]["value"], "00***")
        self.assertEqual(details["profile_evidence"].iloc[0]["miscast_examples"][0], "AB***")

    def test_mask_sensitive_value_masks_nested_dashboard_exports(self) -> None:
        value = {
            "record_key": "row-12345",
            "actual_value": ["", "A", "AB", "ABCDE", {"nested": "secret"}],
            "count": 3,
        }

        masked = _mask_sensitive_value(value)

        self.assertEqual(masked["record_key"], "ro***")
        self.assertEqual(masked["actual_value"], ["<empty>", "***", "***", "AB***", {"nested": "se***"}])
        self.assertEqual(masked["count"], 3)


if __name__ == "__main__":
    unittest.main()
