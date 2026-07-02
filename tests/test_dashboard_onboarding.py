from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from dashboard.onboarding import (
    default_cde_fields,
    default_mandatory_fields,
    generate_rules,
    infer_schema,
    load_csv_bytes,
    persist_onboarding_artifacts,
    sanitize_dataset_id,
)


class DashboardOnboardingTests(unittest.TestCase):
    def test_sanitize_dataset_id(self) -> None:
        self.assertEqual(sanitize_dataset_id("Sales Orders 2026.csv"), "sales_orders_2026_csv")
        with self.assertRaises(ValueError):
            sanitize_dataset_id("123 bad")

    def test_infer_schema_and_generate_default_rules(self) -> None:
        dataframe = load_csv_bytes(
            b"order_id,order_date,amount,age,status\n"
            b"A001,2026-01-01,100.50,31,ACTIVE\n"
            b"A002,2026-01-02,0,29,INACTIVE\n"
        )

        schema = infer_schema(dataframe)
        self.assertEqual(schema["order_id"]["data_type"], "string")
        self.assertEqual(schema["order_date"]["data_type"], "datetime")
        self.assertIn(schema["amount"]["data_type"], {"integer", "numeric"})

        mandatory = default_mandatory_fields(dataframe)
        cde = default_cde_fields(dataframe, mandatory)
        self.assertIn("order_id", mandatory)
        self.assertIn("order_id", cde)

        rules = generate_rules(
            dataset_id="sales_orders",
            declared_schema=schema,
            mandatory_fields=mandatory,
            primary_key=["order_id"],
            business_key=[],
            timestamp_column="order_date",
        )["rules"]
        rule_types = {rule["rule_type"] for rule in rules}
        self.assertIn("not_blank", rule_types)
        self.assertIn("uniqueness", rule_types)
        self.assertIn("not_future", rule_types)
        self.assertIn("date_parseable", rule_types)

    def test_persist_onboarding_artifacts_writes_configs(self) -> None:
        csv_content = (
            b"order_id,order_date,amount\n"
            b"A001,2026-01-01,100.50\n"
            b"A002,2026-01-02,0\n"
        )
        dataframe = load_csv_bytes(csv_content)
        schema = infer_schema(dataframe)

        with tempfile.TemporaryDirectory() as tmp:
            artifacts = persist_onboarding_artifacts(
                root=tmp,
                dataset_id="sales_orders",
                dataset_name="Sales Orders",
                dataset_type="transaction",
                csv_content=csv_content,
                declared_schema=schema,
                primary_key=["order_id"],
                business_key=[],
                mandatory_fields=["order_id", "order_date", "amount"],
                cde_fields=["order_id", "amount"],
                timestamp_column="order_date",
                max_freshness_lag_hours=24,
            )

            for path in (
                artifacts.sample_path,
                artifacts.dataset_config_path,
                artifacts.rules_config_path,
                artifacts.scoring_config_path,
            ):
                self.assertTrue(path.exists(), path)

            dataset_config = yaml.safe_load(artifacts.dataset_config_path.read_text(encoding="utf-8"))
            rules_config = yaml.safe_load(artifacts.rules_config_path.read_text(encoding="utf-8"))
            scoring_config = yaml.safe_load(artifacts.scoring_config_path.read_text(encoding="utf-8"))

            self.assertEqual(dataset_config["dataset_id"], "sales_orders")
            self.assertEqual(dataset_config["storage_path"], "data/samples/sales_orders.csv")
            self.assertEqual(dataset_config["timestamp_column"], "order_date")
            self.assertGreaterEqual(len(rules_config["rules"]), 1)
            self.assertIn("dimension_weights", scoring_config)


if __name__ == "__main__":
    unittest.main()
