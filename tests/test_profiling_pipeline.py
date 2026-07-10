from __future__ import annotations

import unittest
from pathlib import Path

from persistence.seed import build_seed_plan


class SeedFixtureTests(unittest.TestCase):
    def test_seed_fixture_builder_reports_v2_contract_counts(self) -> None:
        plan = build_seed_plan(Path.cwd(), ["customer_master"])

        self.assertEqual(len(plan["dataset"]), 1)
        self.assertEqual(plan["dataset"][0]["dataset_id"], "customer_master")
        self.assertEqual(len(plan["dataset_version"]), 1)
        self.assertEqual(plan["dataset_version"][0]["dataset_version_id"], "DV-customer_master-legacy")
        self.assertEqual(plan["dataset_version"][0]["storage_path"], plan["dataset"][0]["storage_path"])
        self.assertGreater(len(plan["dataset_column"]), 0)
        self.assertTrue(all(column["dataset_version_id"] == "DV-customer_master-legacy" for column in plan["dataset_column"]))
        self.assertGreater(len(plan["rule_template"]), 0)
        self.assertGreater(len(plan["dataset_rule_binding"]), 0)
        self.assertTrue(all(binding["dataset_version_id"] == "DV-customer_master-legacy" for binding in plan["dataset_rule_binding"]))
        self.assertTrue({"SP-default", "SP-master_data"}.issubset({policy["scoring_policy_id"] for policy in plan["scoring_policy"]}))

    def test_seed_plan_is_idempotent_by_primary_ids(self) -> None:
        first = build_seed_plan(Path.cwd(), ["customer_master"])
        second = build_seed_plan(Path.cwd(), ["customer_master"])

        self.assertEqual([item["dataset_id"] for item in first["dataset"]], [item["dataset_id"] for item in second["dataset"]])
        self.assertEqual([item["dataset_version_id"] for item in first["dataset_version"]], [item["dataset_version_id"] for item in second["dataset_version"]])
        self.assertEqual([item["rule_template_id"] for item in first["rule_template"]], [item["rule_template_id"] for item in second["rule_template"]])
        self.assertEqual([item["binding_id"] for item in first["dataset_rule_binding"]], [item["binding_id"] for item in second["dataset_rule_binding"]])
        self.assertEqual([item["scoring_policy_id"] for item in first["scoring_policy"]], [item["scoring_policy_id"] for item in second["scoring_policy"]])


if __name__ == "__main__":
    unittest.main()