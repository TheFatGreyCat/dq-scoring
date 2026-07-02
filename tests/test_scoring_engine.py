from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from rules_engine.run import run_rules
from scoring.config import load_scoring_config, parse_scoring_config
from scoring.engine import score_rules_engine_result
from scoring.run import run_scoring
from scoring.store import ScoreStore


class ScoringEngineTests(unittest.TestCase):
    def test_rule_dimension_and_dq_core_scores(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            rules_result = run_rules(
                "data/configs/customer_master.yaml",
                "data/rules/customer_master_rules.yaml",
                str(Path(tmp) / "rules.db"),
            )
            scoring_config = load_scoring_config("data/scoring/customer_master_scoring.yaml")
            result = score_rules_engine_result(rules_result, scoring_config, "data/scoring/customer_master_scoring.yaml")

        rule_scores = {score.rule_id: score for score in result.rule_score_history}
        self.assertAlmostEqual(rule_scores["DQ-VALI-EMAIL-001"].rule_score or 0, 90.909091, places=5)
        self.assertEqual(rule_scores["DQ-VALI-EMAIL-001"].quality_status, "fail")
        self.assertAlmostEqual(rule_scores["DQ-COMP-PHONE-001"].rule_score or 0, 90.909091, places=5)
        self.assertEqual(rule_scores["DQ-UNIQ-CUSTOMER-001"].failed, 2)
        self.assertEqual(rule_scores["DQ-UNIQ-DUPROW-001"].failed, 2)
        self.assertNotIn("DQ-TIME-FRESHNESS-001", rule_scores)

        dimensions = {score.dimension: score for score in result.dimension_score_history}
        self.assertTrue(dimensions["Completeness"].is_measured)
        self.assertFalse(dimensions["Consistency"].is_measured)
        self.assertEqual(dimensions["Consistency"].dimension_score, None)
        self.assertEqual(dimensions["Consistency"].dimension_weight, 0.0)
        self.assertAlmostEqual(
            sum(score.dimension_weight for score in dimensions.values() if score.is_measured),
            1.0,
            places=5,
        )
        self.assertIsNotNone(result.dataset_score_history.dq_core_score)
        self.assertEqual(result.dataset_score_history.quality_gate_status, "pass")

    def test_not_measured_rules_are_not_scored_as_zero(self) -> None:
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
            rules_result = run_rules("data/configs/customer_master.yaml", str(rule_file), str(Path(tmp) / "rules.db"))
            scoring_config = parse_scoring_config({"dimension_weights": {"Validity": 1.0}})
            scoring_result = score_rules_engine_result(rules_result, scoring_config)

            self.assertEqual(scoring_result.rule_score_history[0].measurement_status, "not_measured")
            self.assertIsNone(scoring_result.rule_score_history[0].rule_score)
            self.assertIsNone(scoring_result.dataset_score_history.dq_core_score)
            self.assertEqual(scoring_result.dataset_score_history.quality_gate_status, "not_scored")

    def test_end_to_end_writes_score_tables_and_json_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            rules_store = Path(tmp) / "rules.db"
            score_store = Path(tmp) / "scores.db"
            export = Path(tmp) / "score.json"

            result = run_scoring(
                "data/configs/customer_master.yaml",
                "data/rules/customer_master_rules.yaml",
                "data/scoring/customer_master_scoring.yaml",
                str(rules_store),
                str(score_store),
            )
            ScoreStore(score_store).store_scoring_result(result)
            export.write_text(json.dumps(result.to_artifact(), ensure_ascii=False, indent=2), encoding="utf-8")

            artifact = json.loads(export.read_text(encoding="utf-8"))
            self.assertIn("rule_score_history", artifact)
            self.assertIn("dimension_score_history", artifact)
            self.assertIn("dataset_score_history", artifact)

            with closing(sqlite3.connect(rules_store)) as conn:
                for table in ("rule_run", "rule_config", "rule_evaluation_result", "rule_issue_sample"):
                    count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    self.assertGreater(count, 0)

            with closing(sqlite3.connect(score_store)) as conn:
                for table in ("score_run", "rule_score_history", "dimension_score_history", "dataset_score_history"):
                    count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    self.assertGreater(count, 0)


if __name__ == "__main__":
    unittest.main()
