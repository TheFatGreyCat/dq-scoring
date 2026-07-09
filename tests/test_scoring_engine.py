from __future__ import annotations

import unittest
from pathlib import Path

from dq_core.models import DatasetColumn, DatasetRecord, DatasetVersion, PipelineLog, ScoringPolicy
from dq_core.runtime import DqRuntime
from persistence.repository import DatasetBundle


class FakeRepository:
    def __init__(self) -> None:
        self.bundle = DatasetBundle(
            DatasetRecord("customer_master", "Customer Master", "customer", "csv", "data/samples/customer_master.csv"),
            DatasetVersion("DV-customer_master-test", "customer_master", "test", None, None),
            [
                DatasetColumn("DV-customer_master-test", "customer_id", 1, "string", is_business_key=True, is_mandatory=True, is_identifier=True),
                DatasetColumn("DV-customer_master-test", "email", 2, "string", is_cde=True, is_mandatory=True),
                DatasetColumn("DV-customer_master-test", "phone_number", 3, "string"),
                DatasetColumn("DV-customer_master-test", "age", 4, "integer"),
            ],
        )
        self.templates = []
        self.bindings = []
        self.validations = {}
        self.scores = {}
        self.logs = []

    def load_dataset_bundle(self, dataset_version_id):
        return self.bundle

    def save_dataset_bundle(self, dataset, version, columns):
        self.bundle = DatasetBundle(dataset, version, columns)

    def save_profile_result(self, dataset_version_id, result, profile_metrics=None):
        self.profile_result = result
        return result.profiling_run.run_id

    def save_rule_templates(self, templates):
        self.templates = list(templates)

    def load_rule_templates(self, active_only=True):
        return self.templates

    def save_rule_bindings(self, dataset_version_id, bindings, exceptions=None):
        from dq_core.models import DatasetRuleBinding

        self.bindings = [DatasetRuleBinding(**binding) for binding in bindings]
        return "BIND-test"

    def load_rule_bindings(self, dataset_version_id, active_only=True):
        return self.bindings

    def save_validation_result(self, validation, ruleset_hash, status="success"):
        self.validations[validation.validation_run_id] = validation
        return validation.validation_run_id

    def load_validation_result(self, validation_run_id):
        return self.validations[validation_run_id]

    def load_scoring_policy(self, scoring_policy_id=None, dataset_type=None):
        return ScoringPolicy(
            "SP-customer",
            "customer",
            {"Completeness": 1.0, "Validity": 1.0, "Uniqueness": 1.0, "Accuracy Proxy": 1.0, "Timeliness": 1.0},
        )

    def save_score_result(self, dataset_version_id, result):
        self.scores[result.score_run_id] = result
        return result.score_run_id

    def save_pipeline_log(self, log: PipelineLog):
        self.logs.append(log.to_record())
        return log.log_id

    def list_dashboard_rows(self):
        return {"pipeline_log": self.logs}


class RuntimeTests(unittest.TestCase):
    def test_runtime_profiles_recommends_validates_and_scores_without_legacy_store(self) -> None:
        runtime = DqRuntime(FakeRepository())
        dataset_version_id = "DV-customer_master-test"

        profile_run_id = runtime.profile_dataset(dataset_version_id)
        self.assertTrue(profile_run_id.startswith("PRUN-"))

        recommendations = runtime.recommend_rules(dataset_version_id)
        self.assertTrue(any(item["rule_template_id"] == "RT-VALI-EMAIL" for item in recommendations))

        bind_run_id = runtime.save_recommended_rule_bindings(dataset_version_id)
        self.assertEqual(bind_run_id, "BIND-test")

        validation_run_id = runtime.run_validation(dataset_version_id)
        validation = runtime.repository.validations[validation_run_id]
        self.assertGreater(len(validation.measurement_results), 0)
        self.assertTrue(all(summary.passed_count >= 0 for summary in validation.record_summaries))

        score_run_id = runtime.calculate_score(validation_run_id)
        score = runtime.repository.scores[score_run_id].dataset_score.dataset_dq_score
        self.assertIsNotNone(score)
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)


if __name__ == "__main__":
    unittest.main()
