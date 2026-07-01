from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

import pandas as pd

from profiling.config import load_config
from profiling.loading import load_dataset
from rules_engine.config import load_rules, parse_rule_config, validate_rule_config
from rules_engine.evaluators import RuleEvaluator
from rules_engine.run import run_rules


class RulesEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dataset_config = load_config("data/configs/customer_master.yaml")
        self.dataframe = load_dataset(self.dataset_config)

    def test_rule_parser_requires_core_fields(self) -> None:
        with self.assertRaises(ValueError):
            parse_rule_config({"rule_id": "DQ-TEST"})

    def test_validator_rejects_unsupported_rule_type_and_missing_threshold(self) -> None:
        rule = parse_rule_config(
            {
                "rule_id": "DQ-BAD-001",
                "dataset_id": "customer_master",
                "dimension": "Validity",
                "rule_type": "unknown_rule",
                "target_column": "email",
                "parameters": {},
                "null_policy": "ignore",
                "severity": "high",
                "execution_backend": "pandas",
                "status": "active",
                "score_enabled": True,
            }
        )
        errors = validate_rule_config(rule, self.dataset_config, set(self.dataframe.columns))
        self.assertTrue(any("Unsupported rule_type" in error for error in errors))
        self.assertTrue(any("threshold" in error for error in errors))

    def test_validator_rejects_missing_column_and_missing_regex_parameter(self) -> None:
        rule = parse_rule_config(
            {
                "rule_id": "DQ-BAD-002",
                "dataset_id": "customer_master",
                "dimension": "Validity",
                "rule_type": "regex",
                "target_column": "missing_email",
                "parameters": {},
                "null_policy": "ignore",
                "threshold": 98,
                "severity": "high",
                "execution_backend": "pandas",
                "status": "active",
                "score_enabled": True,
            }
        )
        errors = validate_rule_config(rule, self.dataset_config, set(self.dataframe.columns))
        self.assertTrue(any("target_column" in error for error in errors))
        self.assertTrue(any("parameters.pattern" in error for error in errors))

    def test_evaluators_cover_customer_master_rules(self) -> None:
        rules = {rule.rule_id: rule for rule in load_rules("data/rules/customer_master_rules.yaml")}
        evaluator = RuleEvaluator()

        email = evaluator.evaluate(self.dataframe, self.dataset_config, rules["DQ-VALI-EMAIL-001"])
        self.assertEqual(email.failed, 1)
        self.assertEqual(email.total_records_in_scope, 10)

        age_type = evaluator.evaluate(self.dataframe, self.dataset_config, rules["DQ-VALI-AGE-TYPE-001"])
        self.assertEqual(age_type.miscast, 1)
        self.assertEqual(age_type.passed, 9)

        age_range = evaluator.evaluate(self.dataframe, self.dataset_config, rules["DQ-ACCU-AGE-001"])
        self.assertEqual(age_range.miscast, 1)
        self.assertEqual(age_range.failed, 0)

        phone = evaluator.evaluate(self.dataframe, self.dataset_config, rules["DQ-COMP-PHONE-001"])
        self.assertEqual(phone.empty, 1)
        self.assertEqual(phone.total_records_in_scope, 10)

        unique = evaluator.evaluate(self.dataframe, self.dataset_config, rules["DQ-UNIQ-CUSTOMER-001"])
        self.assertEqual(unique.passed, 10)
        self.assertEqual(unique.total_records_in_scope, 10)

        status = evaluator.evaluate(self.dataframe, self.dataset_config, rules["DQ-VALI-STATUS-001"])
        self.assertEqual(status.passed, 10)

        parseable = evaluator.evaluate(self.dataframe, self.dataset_config, rules["DQ-TIME-UPDATED-001"])
        self.assertEqual(parseable.passed, 10)

        not_future = evaluator.evaluate(self.dataframe, self.dataset_config, rules["DQ-TIME-NOT-FUTURE-001"])
        self.assertEqual(not_future.passed, 10)

    def test_null_policy_ignore_marks_empty_values_not_applicable(self) -> None:
        rule = parse_rule_config(
            {
                "rule_id": "DQ-VALI-PHONE-LEN-TEST",
                "dataset_id": "customer_master",
                "dimension": "Validity",
                "rule_type": "length",
                "target_column": "phone_number",
                "parameters": {"exact_length": 10},
                "null_policy": "ignore",
                "threshold": 98,
                "severity": "medium",
                "execution_backend": "pandas",
                "status": "active",
                "score_enabled": True,
            }
        )
        result = RuleEvaluator().evaluate(self.dataframe, self.dataset_config, rule)
        self.assertEqual(result.not_applicable, 1)
        self.assertEqual(result.total_records_in_scope, 9)

    def test_run_rules_writes_four_tables_and_no_score_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "rules.db"
            export = Path(tmp) / "rules.json"
            result = run_rules(
                "data/configs/customer_master.yaml",
                "data/rules/customer_master_rules.yaml",
                str(store),
            )
            export.write_text(str(result.to_artifact()), encoding="utf-8")

            artifact_text = str(result.to_artifact())
            self.assertNotIn("RuleScore", artifact_text)
            self.assertNotIn("DimensionScore", artifact_text)
            self.assertNotIn("DQ_Core", artifact_text)
            self.assertNotIn("FinalScore", artifact_text)
            self.assertNotIn("quality_status", artifact_text)
            self.assertIn("rule_run", result.to_artifact())
            self.assertIn("rule_config", result.to_artifact())
            self.assertIn("rule_evaluation_result", result.to_artifact())
            self.assertIn("rule_issue_sample", result.to_artifact())
            self.assertGreaterEqual(result.rule_run.measured_rules, 10)
            self.assertGreaterEqual(len(result.rule_issue_samples), 3)

            with closing(sqlite3.connect(store)) as conn:
                with conn:
                    for table in ("rule_run", "rule_config", "rule_evaluation_result", "rule_issue_sample"):
                        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                        self.assertGreater(count, 0)
                    score_columns = conn.execute("PRAGMA table_info(rule_evaluation_result)").fetchall()
                    names = {row[1] for row in score_columns}
                    self.assertNotIn("quality_status", names)
                    self.assertNotIn("rule_score", names)

    def test_invalid_active_rule_becomes_not_measured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            rule_file = Path(tmp) / "bad_rules.yaml"
            rule_file.write_text(
                """
rules:
  - rule_id: DQ-BAD-MISSING-COLUMN
    dataset_id: customer_master
    dimension: Validity
    rule_type: regex
    target_column: no_such_column
    parameters:
      pattern: ".*"
    null_policy: ignore
    threshold: 98
    severity: high
    execution_backend: pandas
    status: active
    score_enabled: true
""",
                encoding="utf-8",
            )
            result = run_rules("data/configs/customer_master.yaml", str(rule_file), str(Path(tmp) / "rules.db"))
            self.assertEqual(result.rule_run.not_measured_rules, 1)
            self.assertEqual(result.rule_evaluation_results[0].measurement_status, "not_measured")
            self.assertEqual(result.rule_evaluation_results[0].total_records_in_scope, 0)


if __name__ == "__main__":
    unittest.main()
