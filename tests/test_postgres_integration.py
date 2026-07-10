from __future__ import annotations

import unittest
from uuid import uuid4

from dq_core.models import (
    CanonicalValidationResult,
    DatasetColumn,
    DatasetRecord,
    DatasetRuleBinding,
    DatasetVersion,
    MeasurementResult,
    RecordMeasurementSummary,
    RuleTemplate,
    ScoringPolicy,
    ValidationIssueSample,
)
from persistence.postgres import apply_migrations, connect, database_url_from_env
from persistence.repository import DqPostgresRepository
from scoring.v2 import calculate_scores


class PostgresIntegrationTests(unittest.TestCase):
    def test_migration_validation_samples_and_score_metadata_round_trip(self) -> None:
        try:
            database_url = database_url_from_env()
        except RuntimeError as exc:
            self.skipTest(str(exc))
        try:
            apply_migrations(database_url)
        except RuntimeError as exc:
            if "psycopg" in str(exc):
                self.skipTest(str(exc))
            raise

        suffix = uuid4().hex[:10]
        dataset_id = f"it_dataset_{suffix}"
        dataset_version_id = f"DV-{suffix}"
        template_id = f"RT-{suffix}"
        binding_id = f"BR-{suffix}"
        validation_run_id = f"VRUN-{suffix}"
        measurement_id = f"MR-{suffix}"
        policy_id = f"SP-{suffix}"

        repo = DqPostgresRepository(database_url)
        dataset = DatasetRecord(dataset_id, "Integration Dataset", "integration", "csv", "memory.csv")
        version = DatasetVersion(dataset_version_id, dataset_id, "v1", suffix, 100)
        columns = [DatasetColumn(dataset_version_id, "email", 1, "string", is_mandatory=True, is_cde=True)]
        rule_code = f"EMAIL_REQUIRED_{suffix}"
        template = RuleTemplate(template_id, rule_code, 1, "general", "Completeness", "framework", "column", "record", "not_blank")
        binding = DatasetRuleBinding(binding_id, dataset_version_id, template_id, ["email"], scoring_pass_threshold=95, severity="high")
        policy = ScoringPolicy(policy_id, "integration", {"Completeness": 1.0, "Validity": 1.0})
        validation = CanonicalValidationResult(
            validation_run_id,
            dataset_version_id,
            [MeasurementResult(measurement_id, validation_run_id, binding_id, "record", False, "measured")],
            [RecordMeasurementSummary(measurement_id, 90, 10, 0, 0, 100)],
            [ValidationIssueSample(validation_run_id, binding_id, "row-10", "email", "", "not_blank", "empty", rule_code)],
        )

        try:
            repo.save_dataset_bundle(dataset, version, columns)
            repo.save_rule_templates([template])
            repo.save_rule_bindings(dataset_version_id, [binding.to_record()], [])
            repo.save_seed_plan({"scoring_policy": [policy.to_record()]})
            repo.save_validation_result(validation, ruleset_hash="integration-test")

            loaded = repo.load_validation_result(validation_run_id)
            self.assertEqual(len(loaded.issue_samples), 1)
            self.assertEqual(loaded.issue_samples[0].rule_code, rule_code)
            self.assertEqual(loaded.issue_samples[0].record_key, "row-10")

            result = calculate_scores(loaded, policy, {binding_id: binding}, {template_id: template}, {"email": {"mandatory", "cde"}})
            repo.save_score_result(dataset_version_id, result)
            rows = repo.list_dashboard_rows()

            saved_score = next(row for row in rows["dataset_score_history"] if row["score_run_id"] == result.score_run_id)
            self.assertEqual(saved_score["score_status"], result.dataset_score.score_status)
            self.assertEqual(saved_score["formula_revision"], result.formula_revision)
            self.assertIsNotNone(saved_score["policy_snapshot_jsonb"])
            saved_sample = next(row for row in rows["rule_issue_sample"] if row["validation_run_id"] == validation_run_id)
            self.assertEqual(saved_sample["rule_code"], rule_code)
        finally:
            _cleanup_integration_rows(
                database_url,
                dataset_id=dataset_id,
                dataset_version_id=dataset_version_id,
                template_id=template_id,
                binding_id=binding_id,
                validation_run_id=validation_run_id,
                measurement_id=measurement_id,
                policy_id=policy_id,
            )


def _cleanup_integration_rows(
    database_url: str,
    *,
    dataset_id: str,
    dataset_version_id: str,
    template_id: str,
    binding_id: str,
    validation_run_id: str,
    measurement_id: str,
    policy_id: str,
) -> None:
    with connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM dataset_score_history WHERE score_run_id IN (SELECT score_run_id FROM score_run WHERE dataset_version_id = %s)", (dataset_version_id,))
            cur.execute("DELETE FROM dimension_score_history WHERE score_run_id IN (SELECT score_run_id FROM score_run WHERE dataset_version_id = %s)", (dataset_version_id,))
            cur.execute("DELETE FROM rule_score_history WHERE score_run_id IN (SELECT score_run_id FROM score_run WHERE dataset_version_id = %s)", (dataset_version_id,))
            cur.execute("DELETE FROM score_run WHERE dataset_version_id = %s", (dataset_version_id,))
            cur.execute("DELETE FROM rule_issue_sample WHERE validation_run_id = %s", (validation_run_id,))
            cur.execute("DELETE FROM record_measurement_summary WHERE measurement_result_id = %s", (measurement_id,))
            cur.execute("DELETE FROM measurement_result WHERE validation_run_id = %s", (validation_run_id,))
            cur.execute("DELETE FROM validation_run WHERE validation_run_id = %s", (validation_run_id,))
            cur.execute("DELETE FROM dataset_rule_binding WHERE binding_id = %s", (binding_id,))
            cur.execute("DELETE FROM rule_template WHERE rule_template_id = %s", (template_id,))
            cur.execute("DELETE FROM scoring_policy WHERE scoring_policy_id = %s", (policy_id,))
            cur.execute("DELETE FROM dataset_column WHERE dataset_version_id = %s", (dataset_version_id,))
            cur.execute("DELETE FROM dataset_version WHERE dataset_version_id = %s", (dataset_version_id,))
            cur.execute("DELETE FROM dataset WHERE dataset_id = %s", (dataset_id,))
        conn.commit()


if __name__ == "__main__":
    unittest.main()
