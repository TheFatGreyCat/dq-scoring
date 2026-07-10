from __future__ import annotations

import sys
import unittest
from unittest.mock import patch

from dashboard.app import V2_SETUP_COMMANDS
from dashboard.generate_demo_data import _resolve_datasets
from persistence import db


class RuntimeCleanupTests(unittest.TestCase):
    def test_dashboard_setup_commands_are_v2_runtime_workflow(self) -> None:
        command_text = "\n".join(V2_SETUP_COMMANDS)

        self.assertEqual(V2_SETUP_COMMANDS[0], "python -m persistence.db migrate")
        self.assertIn("python -m dq_core.cli register_dataset", command_text)
        self.assertIn("python -m dq_core.cli save_recommended_bindings", command_text)
        self.assertIn("python -m dq_core.cli calculate_score", command_text)
        self.assertNotIn("persistence.import_legacy", command_text)
        self.assertNotIn("python -m persistence.db seed", command_text)

    def test_demo_dataset_resolution_rejects_unknown_dataset(self) -> None:
        self.assertIn("customer_master", _resolve_datasets(["all"]))
        self.assertEqual(_resolve_datasets(["customer_master,amazon_products"]), ["customer_master", "amazon_products"])

        with self.assertRaisesRegex(ValueError, "Unknown dataset"):
            _resolve_datasets(["missing_dataset"])

    def test_db_reset_requires_explicit_confirmation(self) -> None:
        with patch.object(sys, "argv", ["persistence.db", "reset"]):
            with self.assertRaisesRegex(SystemExit, "--yes"):
                db.main()

    def test_db_reset_calls_repository_only_when_confirmed(self) -> None:
        with patch.object(sys, "argv", ["persistence.db", "reset", "--yes"]), patch("persistence.db.DqPostgresRepository") as repository_cls, patch("builtins.print"):
            db.main()

        repository_cls.return_value.reset_v2_data.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()