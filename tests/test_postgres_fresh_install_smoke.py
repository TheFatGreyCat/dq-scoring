from __future__ import annotations

import os
import unittest
from uuid import uuid4

from dq_core.runtime import DqRuntime
from persistence.repository import DqPostgresRepository


@unittest.skipUnless(os.environ.get("DQ_DATABASE_URL"), "DQ_DATABASE_URL is required for PostgreSQL smoke test")
class PostgresFreshInstallSmokeTests(unittest.TestCase):
    def test_bootstrap_register_profile_recommend_bind_validate_score(self) -> None:
        repository = DqPostgresRepository(os.environ["DQ_DATABASE_URL"])
        runtime = DqRuntime(repository)
        runtime.bootstrap_catalog()

        dataset_id = f"it_dataset_smoke_{uuid4().hex[:8]}"
        dataset_version_id = runtime.register_dataset_bytes(
            b"id,email,created_at\n1,ada@example.com,2026-01-01\n2,grace@example.com,2026-01-02\n3,,2026-01-03\n",
            {
                "dataset_id": dataset_id,
                "dataset_name": "Integration smoke dataset",
                "dataset_type": "default",
                "primary_key": ["id"],
                "mandatory_fields": ["id", "email"],
                "cde_fields": ["email"],
                "timestamp_column": "created_at",
            },
        )

        profile_run_id = runtime.profile_dataset(dataset_version_id)
        recommendations = runtime.recommend_rules(dataset_version_id)
        binding_run_id = runtime.save_recommended_rule_bindings(dataset_version_id, accept_all_above_threshold=True, threshold=0.70)
        bindings = repository.load_rule_bindings(dataset_version_id)
        validation_run_id = runtime.run_validation(dataset_version_id)
        score_run_id = runtime.calculate_score(validation_run_id)
        result = runtime.get_run_result(score_run_id)

        self.assertTrue(profile_run_id.startswith("PRUN-"))
        self.assertGreater(len(recommendations), 0)
        self.assertTrue(binding_run_id.startswith("BIND-"))
        self.assertGreater(len(bindings), 0)
        self.assertTrue(validation_run_id.startswith("VRUN-"))
        self.assertTrue(score_run_id.startswith("SRUN2-"))
        self.assertTrue(any(row.get("score_run_id") == score_run_id for row in result.get("dataset_score_history", [])))


if __name__ == "__main__":
    unittest.main()