from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

import pandas as pd

from profiling.candidate_rules import generate_candidate_rules
from profiling.column_profile import profile_columns
from profiling.config import load_config, parse_config
from profiling.dataset_profile import profile_dataset
from profiling.loading import load_dataset
from profiling.run import run_pipeline
from profiling.sampling import sample_dataset
from profiling.schema_profile import profile_schema


class ProfilingPipelineTests(unittest.TestCase):
    def test_config_parser_requires_core_fields(self) -> None:
        with self.assertRaises(ValueError):
            parse_config({"dataset_id": "x", "source_type": "csv"})

    def test_loading_sampling_and_profiles(self) -> None:
        config = load_config("data/configs/customer_master.yaml")
        df = load_dataset(config)
        sampled, sampling = sample_dataset(df, config)
        self.assertFalse(sampling.is_sampled)
        self.assertEqual(len(sampled), 11)

        schema = profile_schema(sampled, config)
        self.assertEqual(schema.missing_columns, [])
        self.assertEqual(schema.extra_columns, [])

        columns = profile_columns(sampled, config, run_id="RUN-TEST")
        email = next(item for item in columns if item.column_name == "email")
        age = next(item for item in columns if item.column_name == "age")
        phone = next(item for item in columns if item.column_name == "phone_number")
        self.assertEqual(email.null_count, 0)
        self.assertGreaterEqual(email.pattern_frequency["valid_email_format"], 0.8)
        self.assertEqual(age.miscast_count, 1)
        self.assertEqual(phone.blank_count, 1)

        dataset_profile = profile_dataset(sampled, config, run_id="RUN-TEST")
        self.assertEqual(dataset_profile.row_count, 11)
        self.assertEqual(dataset_profile.duplicate_row_count, 1)
        self.assertIsNotNone(dataset_profile.freshness_lag)

    def test_random_sampling_is_reproducible(self) -> None:
        config = parse_config(
            {
                "dataset_id": "sampled",
                "source_type": "csv",
                "storage_path": "unused.csv",
                "profiling_config": {
                    "sampling_method": "random",
                    "sample_fraction": 0.3,
                    "random_seed": 7,
                },
            }
        )
        df = pd.DataFrame({"id": list(range(20))})
        first, _ = sample_dataset(df, config)
        second, _ = sample_dataset(df, config)
        self.assertEqual(first["id"].tolist(), second["id"].tolist())

    def test_candidate_rules_are_pending_review(self) -> None:
        config = load_config("data/configs/customer_master.yaml")
        df = load_dataset(config)
        columns = profile_columns(df, config, run_id="RUN-CAND")
        dataset_profile = profile_dataset(df, config, run_id="RUN-CAND")
        candidates = generate_candidate_rules(dataset_profile, columns, config)
        self.assertTrue(candidates)
        self.assertTrue(all(item.status == "pending_review" for item in candidates))

    def test_end_to_end_writes_five_tables_and_no_scores(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "profile.db"
            result = run_pipeline("data/configs/customer_master.yaml", str(store))
            run_pipeline("data/configs/customer_master.yaml", str(store))
            summary = result.to_summary(str(store))
            artifact = result.to_artifact()
            self.assertNotIn("RuleScore", str(summary))
            self.assertNotIn("DimensionScore", str(summary))
            self.assertNotIn("DQ_Core", str(summary))
            self.assertNotIn("FinalScore", str(summary))
            self.assertIn("profiling_run", artifact)
            self.assertIn("dataset_profile", artifact)
            self.assertIn("column_profile", artifact)
            self.assertIn("candidate_rules", artifact)
            self.assertIn("anomaly_flags", artifact)
            self.assertNotIn("RuleScore", str(artifact))
            self.assertNotIn("DimensionScore", str(artifact))
            self.assertNotIn("DQ_Core", str(artifact))
            self.assertNotIn("FinalScore", str(artifact))

            with closing(sqlite3.connect(store)) as conn:
                with conn:
                    for table in ("profiling_run", "dataset_profile", "column_profile", "candidate_rule", "anomaly_flag"):
                        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                        if table == "anomaly_flag":
                            self.assertGreaterEqual(count, 0)
                        else:
                            self.assertGreater(count, 0)
                    dataset_rows = conn.execute("SELECT COUNT(*) FROM dataset_profile").fetchone()[0]
                    self.assertEqual(dataset_rows, 2)


if __name__ == "__main__":
    unittest.main()
