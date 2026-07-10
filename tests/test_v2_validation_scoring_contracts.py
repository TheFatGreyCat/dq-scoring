from __future__ import annotations

import unittest
from pathlib import Path

from dq_core.models import CanonicalValidationResult, DatasetRuleBinding, MeasurementResult, RecordMeasurementSummary, ScoringPolicy
from persistence.seed import build_seed_plan
from profiling.column_profile import profile_columns
from profiling.config import load_config
from profiling.loading import load_dataset
from profiling.metrics import build_profile_metrics
from profiling.semantic_detection import detect_semantics
from rules_engine.catalog import binding_from_recommendation, default_rule_templates, recommend_rules
from rules_engine.config import load_rules
from rules_engine.evaluators import RuleEvaluator
from scoring.v2 import calculate_scores
from validation.canonical import canonicalize_rule_evaluation
from validation.gx_adapter import MapExpectationAdapter
from validation.planner import GX_RESULT_FORMAT, plan_execution, ruleset_hash


class V2ValidationScoringContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_config("data/configs/customer_master.yaml")
        self.dataframe = load_dataset(self.config)
        self.columns = profile_columns(self.dataframe, self.config, run_id="RUN-V2")

    def test_semantic_detection_and_profile_metrics(self) -> None:
        semantics = {item.column_name: item for item in detect_semantics(self.columns)}
        self.assertEqual(semantics["email"].semantic_type, "email")
        self.assertEqual(semantics["phone_number"].semantic_type, "phone")
        self.assertEqual(semantics["customer_id"].semantic_type, "identifier")

        metrics = build_profile_metrics(
            dataset_profile=__import__("profiling.dataset_profile", fromlist=["profile_dataset"]).profile_dataset(
                self.dataframe, self.config, run_id="RUN-V2"
            ),
            column_profiles=self.columns,
        )
        sources = {metric.metric_source for metric in metrics}
        gx_metrics = [metric for metric in metrics if metric.metric_source == "gx"]
        self.assertEqual(sources, {"pandas", "gx"})
        self.assertTrue(any(metric.gx_expectation_type == "expect_column_values_to_be_unique" for metric in gx_metrics))

    def test_rule_catalog_recommendations_and_bindings(self) -> None:
        semantics = detect_semantics(self.columns)
        templates = default_rule_templates()
        recommendations = recommend_rules(self.columns, semantics, self.config, templates)
        keys = {(item.rule_template_id, tuple(item.target_columns)) for item in recommendations}
        self.assertIn(("RT-VALI-EMAIL", ("email",)), keys)
        self.assertIn(("RT-COMP-NOT-BLANK", ("customer_id",)), keys)

        email_template = next(item for item in templates if item.rule_template_id == "RT-VALI-EMAIL")
        email_recommendation = next(item for item in recommendations if item.rule_template_id == "RT-VALI-EMAIL")
        binding = binding_from_recommendation(email_recommendation, email_template, "DV-customer_master-001")
        self.assertEqual(binding.backend, "gx")
        self.assertEqual(binding.scoring_method, "pass_ratio")

    def test_seed_plan_maps_legacy_yaml_to_postgres_contracts(self) -> None:
        plan = build_seed_plan(Path.cwd(), ["customer_master", "retail_sales_dataset"])
        self.assertGreaterEqual(len(plan["dataset"]), 2)
        self.assertGreater(len(plan["rule_template"]), 0)
        self.assertGreater(len(plan["dataset_rule_binding"]), 0)
        required_template_fields = {
            "management_scope",
            "target_scope",
            "evaluation_scope",
            "accuracy_mode",
            "null_policy",
            "score_enabled",
            "gate_enabled",
            "scoring_method",
        }
        self.assertTrue(required_template_fields.issubset(plan["rule_template"][0]))

    def test_ruleset_hash_and_execution_plan_are_stable(self) -> None:
        templates = default_rule_templates()
        template_by_id = {item.rule_template_id: item for item in templates}
        binding = DatasetRuleBinding(
            binding_id="BR-EMAIL",
            dataset_version_id="DV-1",
            rule_template_id="RT-VALI-EMAIL",
            target_columns=["email"],
            acceptance_threshold=0.98,
            backend="gx",
        )
        first_hash = ruleset_hash([binding], template_by_id)
        second_hash = ruleset_hash([binding], template_by_id)
        changed_hash = ruleset_hash([
            DatasetRuleBinding(
                binding_id="BR-EMAIL",
                dataset_version_id="DV-1",
                rule_template_id="RT-VALI-EMAIL",
                target_columns=["email"],
                acceptance_threshold=0.90,
                backend="gx",
            )
        ], template_by_id)
        self.assertEqual(first_hash, second_hash)
        self.assertNotEqual(first_hash, changed_hash)
        self.assertEqual(GX_RESULT_FORMAT["result_format"], "SUMMARY")
        self.assertEqual(plan_execution([binding], template_by_id)[0].backend, "gx")

    def test_canonical_measurement_applies_null_policy(self) -> None:
        rules = {rule.rule_id: rule for rule in load_rules("data/rules/customer_master_rules.yaml")}
        evaluation = RuleEvaluator().evaluate(self.dataframe, self.config, rules["DQ-COMP-PHONE-001"])
        binding = DatasetRuleBinding("BR-PHONE", "DV-1", "RT-COMP-NOT-BLANK", ["phone_number"], backend="python")
        measurement, summary = canonicalize_rule_evaluation("VRUN-1", evaluation, binding, null_policy="fail")
        self.assertEqual(measurement.binding_id, "BR-PHONE")
        self.assertEqual(summary.missing_count, 1)
        self.assertEqual(summary.records_in_scope, 11)

        _, separate_summary = canonicalize_rule_evaluation("VRUN-1", evaluation, binding, null_policy="separate")
        self.assertEqual(separate_summary.records_in_scope, 10)

    def test_scoring_v2_weights_gate_and_explanation(self) -> None:
        templates = {item.rule_template_id: item for item in default_rule_templates()}
        binding = DatasetRuleBinding(
            binding_id="BR-KEY-COMP",
            dataset_version_id="DV-1",
            rule_template_id="RT-COMP-NOT-BLANK",
            target_columns=["customer_id"],
            scoring_pass_threshold=99,
            severity="critical",
            gate_enabled=True,
        )
        validation = CanonicalValidationResult(
            validation_run_id="VRUN-1",
            dataset_version_id="DV-1",
            measurement_results=[
                MeasurementResult(
                    measurement_result_id="MR-1",
                    validation_run_id="VRUN-1",
                    binding_id="BR-KEY-COMP",
                    evaluation_unit="record",
                    expectation_success=False,
                    measurement_status="measured",
                )
            ],
            record_summaries=[RecordMeasurementSummary("MR-1", 90, 10, 0, 0, 100)],
        )
        policy = ScoringPolicy(
            scoring_policy_id="SP-test",
            dataset_type="default",
            dimension_weights={"Completeness": 1.0, "Validity": 1.0},
        )
        result = calculate_scores(
            validation,
            policy,
            {binding.binding_id: binding},
            templates,
            {"customer_id": {"business_key", "mandatory", "identifier"}},
        )
        self.assertEqual(result.rule_scores[0].rule_score, 90.0)
        self.assertEqual(result.rule_scores[0].criticality_weight, 1.5)
        self.assertEqual(result.dataset_score.quality_gate_status, "fail")
        self.assertTrue(result.dataset_score.gate_failures)

    def test_gx_map_adapter_normalizes_summary_result(self) -> None:
        raw = {
            "success": False,
            "result": {"element_count": 10, "unexpected_count": 2, "missing_count": 1},
            "expectation_config": {"kwargs": {"column": "email"}},
        }
        normalized = MapExpectationAdapter().normalize("VRUN-1", "BR-EMAIL", raw)
        self.assertEqual(normalized.summary.passed_count, 7)
        self.assertEqual(normalized.summary.failed_count, 2)
        self.assertEqual(normalized.summary.records_in_scope, 9)


if __name__ == "__main__":
    unittest.main()
