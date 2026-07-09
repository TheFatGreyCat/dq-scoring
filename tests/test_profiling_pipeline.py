from __future__ import annotations

import unittest
from pathlib import Path

from persistence.import_legacy import import_legacy
from persistence.seed import build_seed_plan


class ImportLegacyTests(unittest.TestCase):
    def test_import_legacy_dry_run_reports_v2_contract_counts(self) -> None:
        report = import_legacy(root=Path.cwd(), datasets=["customer_master"], dry_run=True)
        self.assertTrue(report["dry_run"])
        self.assertEqual(report["datasets_imported"], 1)
        self.assertGreater(report["columns_imported"], 0)
        self.assertGreater(report["templates_created"], 0)
        self.assertGreater(report["bindings_created"], 0)

    def test_seed_plan_is_idempotent_by_primary_ids(self) -> None:
        first = build_seed_plan(Path.cwd(), ["customer_master"])
        second = build_seed_plan(Path.cwd(), ["customer_master"])
        self.assertEqual([item["dataset_id"] for item in first["dataset"]], [item["dataset_id"] for item in second["dataset"]])
        self.assertEqual([item["rule_template_id"] for item in first["rule_template"]], [item["rule_template_id"] for item in second["rule_template"]])
        self.assertEqual([item["binding_id"] for item in first["dataset_rule_binding"]], [item["binding_id"] for item in second["dataset_rule_binding"]])


if __name__ == "__main__":
    unittest.main()

