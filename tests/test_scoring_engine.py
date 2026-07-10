from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dq_core.models import DatasetColumn, DatasetRecord, DatasetRuleBinding, DatasetVersion, PipelineLog, RuleRecommendation, RuleTemplate, ScoringPolicy
from dq_core.runtime import DqRuntime, _should_profile_in_chunks
from persistence.repository import DatasetBundle, DqPostgresRepository
from profiling.models import DatasetConfig, ProfilingConfig


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
        self.validation_statuses = {}
        self.scores = {}
        self.logs = []
        self.policies = []

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

    def save_scoring_policies(self, policies):
        self.policies = list(policies)

    def save_rule_bindings(self, dataset_version_id, bindings, exceptions=None):
        from dq_core.models import DatasetRuleBinding

        self.bindings = [DatasetRuleBinding(**binding) for binding in bindings]
        return "BIND-test"

    def load_rule_bindings(self, dataset_version_id, active_only=True):
        return self.bindings

    def save_validation_result(self, validation, ruleset_hash, status="success"):
        self.validations[validation.validation_run_id] = validation
        self.validation_statuses[validation.validation_run_id] = status
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

    def test_repository_persists_storage_path_per_dataset_version(self) -> None:
        class CaptureRepository(DqPostgresRepository):
            def __init__(self, upload_dir: Path) -> None:
                super().__init__(upload_dir=upload_dir)
                self.saved_bundles = []

            def save_dataset_bundle(self, dataset, version, columns):
                self.saved_bundles.append(DatasetBundle(dataset, version, columns))

        with tempfile.TemporaryDirectory() as tempdir:
            repo = CaptureRepository(Path(tempdir))
            first = repo.register_dataset(b"id\n1\n", {"dataset_id": "orders", "dataset_version_id": "DV-orders-v1"})
            second = repo.register_dataset(b"id\n2\n", {"dataset_id": "orders", "dataset_version_id": "DV-orders-v2"})

        self.assertNotEqual(first.version.storage_path, second.version.storage_path)
        self.assertTrue(first.version.storage_path.endswith("DV-orders-v1.csv"))
        self.assertTrue(second.version.storage_path.endswith("DV-orders-v2.csv"))

    def test_bootstrap_catalog_seeds_default_scoring_policy(self) -> None:
        runtime = DqRuntime(FakeRepository())

        result = runtime.bootstrap_catalog()

        self.assertGreater(result["rule_template"], 0)
        self.assertGreater(result["scoring_policy"], 0)
        self.assertTrue(any(policy.scoring_policy_id == "SP-default" for policy in runtime.repository.policies))


    def test_chunked_profile_budget_trigger_uses_file_size_and_config(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "small.csv"
            path.write_text("id\n1\n", encoding="utf-8")
            disabled = DatasetConfig("sample", None, "default", "csv", str(path), profiling_config=ProfilingConfig(memory_budget_mb=512))
            forced = DatasetConfig("sample", None, "default", "csv", str(path), profiling_config=ProfilingConfig(memory_budget_mb=0))

            self.assertFalse(_should_profile_in_chunks(disabled))
            self.assertTrue(_should_profile_in_chunks(forced))
    def test_runtime_uses_chunked_profile_when_budget_requires_it(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "chunked.csv"
            path.write_text("id,amount\n1,10\n2,\n3,bad\n", encoding="utf-8")
            repo = FakeRepository()
            repo.bundle = DatasetBundle(
                DatasetRecord("sales", "Sales", "sales", "csv", "legacy.csv"),
                DatasetVersion("DV-sales-v1", "sales", "v1", None, None, storage_path=str(path)),
                [DatasetColumn("DV-sales-v1", "id", 1, "string"), DatasetColumn("DV-sales-v1", "amount", 2, "string")],
            )
            runtime = DqRuntime(repo)

            with patch("dq_core.runtime._should_profile_in_chunks", return_value=True):
                profile_run_id = runtime.profile_dataset("DV-sales-v1")

        self.assertTrue(profile_run_id.startswith("PRUN-"))
        self.assertEqual(runtime.repository.profile_result.profiling_run.profile_strategy, "chunked_budget")
        self.assertEqual(runtime.repository.profile_result.dataset_profile.row_count, 3)
        amount_profile = next(profile for profile in runtime.repository.profile_result.column_profiles if profile.column_name == "amount")
        self.assertEqual(amount_profile.metric_scope, "sampled")

    def test_runtime_profiles_recommends_validates_and_scores_without_legacy_store(self) -> None:
        runtime = DqRuntime(FakeRepository())
        dataset_version_id = "DV-customer_master-test"

        profile_run_id = runtime.profile_dataset(dataset_version_id)
        self.assertTrue(profile_run_id.startswith("PRUN-"))
        self.assertEqual(runtime.repository.profile_result.profiling_run.scan_mode, "full")
        self.assertEqual(runtime.repository.profile_result.profiling_run.coverage_estimate, 1.0)
        self.assertTrue(all(profile.metric_scope == "full" for profile in runtime.repository.profile_result.column_profiles))

        recommendations = runtime.recommend_rules(dataset_version_id)
        self.assertTrue(any(item["rule_template_id"] == "RT-VALI-EMAIL" for item in recommendations))

        bind_run_id = runtime.save_recommended_rule_bindings(dataset_version_id, accept_all_above_threshold=True)
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


    def test_save_recommended_bindings_uses_reviewed_accepted_and_edited(self) -> None:
        runtime = DqRuntime(FakeRepository())
        dataset_version_id = "DV-customer_master-test"
        accepted = RuleRecommendation("RT-VALI-EMAIL", ["email"], "accepted", 0.95, True, review_status="accepted")
        edited = RuleRecommendation("RT-COMP-NOT-NULL", ["customer_id"], "edited", 0.96, True, review_status="edited")

        def load_latest(_dataset_version_id, decision=None):
            return {"accepted": [accepted], "edited": [edited]}.get(decision, [])

        runtime.repository.load_latest_recommendations = load_latest
        runtime.save_recommended_rule_bindings(dataset_version_id)

        bound_template_ids = {binding.rule_template_id for binding in runtime.repository.bindings}
        self.assertEqual(bound_template_ids, {"RT-VALI-EMAIL", "RT-COMP-NOT-NULL"})

    def test_auto_bind_skips_review_required_recommendations(self) -> None:
        runtime = DqRuntime(FakeRepository())
        dataset_version_id = "DV-customer_master-test"
        runtime.recommend_rules = lambda _dataset_version_id: [
            {
                "rule_template_id": "RT-VALI-EMAIL",
                "target_columns": ["email"],
                "reason": "email semantic",
                "confidence": 0.95,
                "editable": True,
                "source": "framework_auto",
            },
            {
                "rule_template_id": "RT-COMP-CONDITIONAL",
                "target_columns": ["email"],
                "reason": "conditional business rule",
                "confidence": 0.99,
                "editable": True,
                "source": "review_required",
            },
        ]

        runtime.save_recommended_rule_bindings(dataset_version_id, accept_all_above_threshold=True, threshold=0.8)

        bound_template_ids = {binding.rule_template_id for binding in runtime.repository.bindings}
        self.assertIn("RT-VALI-EMAIL", bound_template_ids)
        self.assertNotIn("RT-COMP-CONDITIONAL", bound_template_ids)

    def test_validation_status_becomes_partial_success_when_not_measured_exists(self) -> None:
        runtime = DqRuntime(FakeRepository())
        dataset_version_id = "DV-customer_master-test"
        runtime.repository.templates = [
            RuleTemplate(
                rule_template_id="RT-CROSS",
                rule_code="START_BEFORE_END",
                rule_template_version=1,
                rule_category="business",
                dimension="Consistency",
                management_scope="dataset",
                target_scope="multiple_columns",
                evaluation_scope="cross_field",
                operator="comparison",
                parameters={"operator": "lte"},
                null_policy="not_applicable",
            )
        ]
        runtime.repository.bindings = [
            DatasetRuleBinding(
                binding_id="BR-CROSS",
                dataset_version_id=dataset_version_id,
                rule_template_id="RT-CROSS",
                target_columns=["customer_id", "email"],
                backend="gx",
            )
        ]

        validation_run_id = runtime.run_validation(dataset_version_id)

        self.assertEqual(runtime.repository.validation_statuses[validation_run_id], "partial_success")


if __name__ == "__main__":
    unittest.main()
