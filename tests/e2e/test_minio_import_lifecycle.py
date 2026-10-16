"""Real import, independent governance, Spark replay, and immutable object versions."""
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from dq_scoring.adapters.compute.spark_compute import PySparkComputeAdapter
from dq_scoring.adapters.db.postgres_assessment_store import (
    PostgresAssessmentStoreAdapter,
)
from dq_scoring.adapters.queue.postgres_queue import PostgresQueueAdapter
from dq_scoring.adapters.storage.s3_object_store import S3ObjectStoreAdapter
from dq_scoring.core.exceptions import RunAbortedError
from dq_scoring.presentation.api.app import create_app
from dq_scoring.presentation.api.auth import hash_password
from dq_scoring.services.evaluation_orchestrator import EvaluationOrchestrator
from dq_scoring.workers.evaluation_worker import EvaluationWorker
from tests.support.object_snapshots import register_snapshot_via_api


@pytest.mark.parametrize("changed_object", ["raw", "canonical"])
def test_import_governance_replay_and_overwrite(pg_dsn, db_conn, changed_object):
    tenant, creator, approver = uuid4(), uuid4(), uuid4()
    password = uuid4().hex
    with db_conn.cursor() as cur:
        cur.execute("INSERT INTO tenants(tenant_id,tenant_code,tenant_name) VALUES (%s,%s,'Synthetic finance')", (tenant, tenant.hex))
        for user, role in [(creator, "DATA_ENGINEER"), (approver, "DATA_STEWARD")]:
            cur.execute("INSERT INTO users(user_id,email,password_hash,full_name) VALUES (%s,%s,%s,'Synthetic user')", (user, f"{user}@example.test", hash_password(password)))
            cur.execute("INSERT INTO tenant_memberships(tenant_id,user_id,role) VALUES (%s,%s,%s)", (tenant, user, role))
    db_conn.commit()
    with TestClient(create_app()) as client:
        def login(user):
            result = client.post("/api/v1/auth/login", json={"email": f"{user}@example.test", "password": password, "tenant_id": str(tenant)})
            assert result.status_code == 200
            return {"Authorization": f"Bearer {result.json()['access_token']}"}
        headers, independent = login(creator), login(approver)
        raw = b"transaction_id,amount,currency\nt1,10.00,USD\nt2,-1.00,USD\nt3,,USD\n"
        snap = register_snapshot_via_api(client, headers, pg_dsn, raw, asset_name="Finance E2E")
        assert snap["total_rows"] == 3
        rules = client.post("/api/v1/rulesets", headers=headers, json={"asset_id": snap["asset_id"], "name": "Finance rules", "rules": [
            {"rule_code": "nonnull", "dimension": "COMPLETENESS", "rule_type": "NON_NULL", "parameters": {"column": "amount"}},
            {"rule_code": "range", "dimension": "VALIDITY", "rule_type": "DOMAIN_RANGE", "parameters": {"column": "amount", "min_value": 0}},
        ]})
        assert rules.status_code == 201
        ruleset = rules.json()["ruleset_id"]
        policy = client.post("/api/v1/policies", headers=headers, json={"name": "Finance policy", "gate_fail_threshold": 60, "gate_warn_threshold": 80, "min_coverage_threshold": 0.8, "dimension_weights": {"COMPLETENESS": 1, "VALIDITY": 1}})
        assert policy.status_code == 201
        policy_id = policy.json()["policy_id"]
        for path, identifier in [("rulesets", ruleset), ("policies", policy_id)]:
            assert client.post(f"/api/v1/{path}/{identifier}/submit", headers=headers, json={}).status_code == 200
            assert client.post(f"/api/v1/{path}/{identifier}/approve", headers=headers, json={}).status_code == 403
            assert client.post(f"/api/v1/{path}/{identifier}/approve", headers=independent, json={}).status_code == 200
        queue = PostgresQueueAdapter(pg_dsn)
        compute = PySparkComputeAdapter()
        worker = EvaluationWorker(queue, EvaluationOrchestrator(compute, PostgresAssessmentStoreAdapter(pg_dsn), queue), worker_id="finance-synthetic")
        def run():
            result = client.post("/api/v1/runs", headers=headers, json={"snapshot_id": snap["snapshot_id"], "ruleset_id": ruleset, "policy_id": policy_id, "idempotency_key": uuid4().hex})
            assert result.status_code == 202
            assessment = worker.run_by_id(UUID(result.json()["run_id"]))
            return result.json()["run_id"], assessment
        _, first = run()
        _, replay = run()
        assert first.dq_score == pytest.approx(50)
        assert first.coverage_ratio == 1
        assert first.quality_gate.value == "FAIL"
        assert replay.assessment_hash == first.assessment_hash
        detail = client.get(f"/api/v1/assessments/{first.assessment_id}", headers=headers).json()
        counts = {r["rule_code"]: r for r in detail["rule_results"]}
        assert counts["nonnull"]["passed_count"] == 2
        assert counts["nonnull"]["missing_count"] == 1
        assert counts["range"]["passed_count"] == 1
        assert counts["range"]["failed_count"] == 1
        assert counts["range"]["missing_count"] == 1
        source = snap["source_descriptor"]
        descriptor = source if changed_object == "raw" else source["canonical"]
        store = S3ObjectStoreAdapter()
        store._client.put_object(Bucket=descriptor["bucket"], Key=descriptor["key"], Body=b"changed")
        result = client.post("/api/v1/runs", headers=headers, json={"snapshot_id": snap["snapshot_id"], "ruleset_id": ruleset, "policy_id": policy_id, "idempotency_key": uuid4().hex})
        assert result.status_code == 202
        failed_run = result.json()["run_id"]
        with pytest.raises(RunAbortedError, match="OBJECT_CHANGED"):
            worker.run_by_id(UUID(failed_run))
        state = client.get(f"/api/v1/runs/{failed_run}/status", headers=headers).json()
        assert state["status"] == "FAILED"
        assert state["assessment_id"] is None
    with psycopg.connect(pg_dsn) as conn:
        assert conn.execute("SELECT count(*) FROM assessments WHERE tenant_id=%s", (tenant,)).fetchone()[0] == 2
