"""Complete End-to-End lifecycle integration test across all modules (AC-001..AC-025)."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from dq_scoring.adapters.compute.spark_compute import PySparkComputeAdapter
from dq_scoring.adapters.db.postgres_assessment_store import (
    PostgresAssessmentStoreAdapter,
)
from dq_scoring.adapters.queue.postgres_queue import PostgresQueueAdapter
from dq_scoring.presentation.api.app import create_app
from dq_scoring.presentation.api.auth import hash_password
from dq_scoring.services.evaluation_orchestrator import EvaluationOrchestrator
from dq_scoring.workers.evaluation_worker import EvaluationWorker


@pytest.fixture(scope="module")
def client(pg_dsn: str) -> TestClient:
    """FastAPI TestClient fixture."""
    app = create_app()
    return TestClient(app)


@pytest.fixture(scope="module")
def spark_adapter() -> PySparkComputeAdapter:
    """Module-scoped PySparkComputeAdapter."""
    return PySparkComputeAdapter()


@pytest.fixture
def golden_csv_path() -> Path:
    """Path to Golden 5k dataset."""
    project_root = Path(__file__).resolve().parent.parent.parent
    return project_root / "tests/fixtures/chicago_taxi/chicago_taxi_golden_5k.csv"


def test_complete_e2e_lifecycle(
    client: TestClient,
    pg_dsn: str,
    db_conn,
    spark_adapter: PySparkComputeAdapter,
    golden_csv_path: Path,
):
    """Execute complete lifecycle: Auth -> Asset -> Snapshot -> Governance -> Worker -> API Polling & Scorecard."""
    tenant_id = uuid4()
    steward_id = uuid4()
    owner_id = uuid4()
    pwd = "StrongSecurePassword123!"
    pwd_hash = hash_password(pwd)

    # 1. Seed tenant and users
    with db_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO tenants (tenant_id, tenant_code, tenant_name, subscription_tier, status)
            VALUES (%s, %s, %s, 'ENTERPRISE', 'ACTIVE');
            """,
            (tenant_id, f"org_{tenant_id.hex[:8]}", "Full Lifecycle Org"),
        )
        cur.execute(
            """
            INSERT INTO users (user_id, email, password_hash, full_name, is_active)
            VALUES (%s, %s, %s, 'Steward User', TRUE),
                   (%s, %s, %s, 'Owner User', TRUE);
            """,
            (
                steward_id,
                f"steward_{steward_id.hex[:8]}@example.com",
                pwd_hash,
                owner_id,
                f"owner_{owner_id.hex[:8]}@example.com",
                pwd_hash,
            ),
        )
        cur.execute(
            """
            INSERT INTO tenant_memberships (tenant_id, user_id, role, status)
            VALUES (%s, %s, 'DATA_STEWARD', 'ACTIVE'),
                   (%s, %s, 'DATA_OWNER', 'ACTIVE');
            """,
            (tenant_id, steward_id, tenant_id, owner_id),
        )
        db_conn.commit()

    def get_token(email: str) -> dict[str, str]:
        resp = client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": pwd, "tenant_id": str(tenant_id)},
        )
        assert resp.status_code == 200
        return {"Authorization": f"Bearer {resp.json()['access_token']}"}

    steward_hdr = get_token(f"steward_{steward_id.hex[:8]}@example.com")
    owner_hdr = get_token(f"owner_{owner_id.hex[:8]}@example.com")

    # 2. Register Data Asset
    asset_resp = client.post(
        "/api/v1/assets",
        headers=steward_hdr,
        json={"name": "Chicago Taxi E2E Dataset"},
    )
    assert asset_resp.status_code == 201
    asset_id = asset_resp.json()["asset_id"]

    # 3. Register Dataset Snapshot
    from tests.support.object_snapshots import register_snapshot_via_api
    snap = register_snapshot_via_api(client, steward_hdr, pg_dsn, golden_csv_path, asset_id=asset_id)
    snap_id = snap["snapshot_id"]

    # 4. Create & Approve Ruleset (4-Eyes)
    ruleset_resp = client.post(
        "/api/v1/rulesets",
        headers=steward_hdr,
        json={
            "asset_id": asset_id,
            "name": "E2E Quality Ruleset",
            "rules": [
                {
                    "rule_code": "E2E_COMP_01",
                    "dimension": "Completeness",
                    "rule_type": "NON_NULL",
                    "parameters": {"column": "trip_id"},
                    "is_required": True,
                    "is_critical": True,
                    "acceptance_threshold": 95.0,
                },
                {
                    "rule_code": "E2E_VAL_02",
                    "dimension": "Validity",
                    "rule_type": "TYPE_PARSE",
                    "parameters": {"column": "fare", "data_type": "DOUBLE"},
                    "is_required": True,
                },
            ],
        },
    )
    assert ruleset_resp.status_code == 201
    ruleset_id = ruleset_resp.json()["ruleset_id"]

    client.post(f"/api/v1/rulesets/{ruleset_id}/submit", headers=steward_hdr, json={})
    appr_rs = client.post(f"/api/v1/rulesets/{ruleset_id}/approve", headers=owner_hdr, json={})
    assert appr_rs.status_code == 200
    assert appr_rs.json()["status"] == "ACTIVE"

    # 5. Create & Approve Scoring Policy (4-Eyes)
    policy_resp = client.post(
        "/api/v1/policies",
        headers=steward_hdr,
        json={
            "name": "E2E Scoring Policy",
            "gate_fail_threshold": 60.0,
            "gate_warn_threshold": 80.0,
            "min_coverage_threshold": 0.80,
            "critical_acceptance_threshold": 95.0,
        },
    )
    assert policy_resp.status_code == 201
    policy_id = policy_resp.json()["policy_id"]

    client.post(f"/api/v1/policies/{policy_id}/submit", headers=steward_hdr, json={})
    appr_pol = client.post(f"/api/v1/policies/{policy_id}/approve", headers=owner_hdr, json={})
    assert appr_pol.status_code == 200
    assert appr_pol.json()["status"] == "ACTIVE"

    # 6. Trigger Evaluation Run
    run_resp = client.post(
        "/api/v1/runs",
        headers=steward_hdr,
        json={
            "snapshot_id": snap_id,
            "ruleset_id": ruleset_id,
            "policy_id": policy_id,
            "idempotency_key": f"e2e-run-{uuid4()}",
        },
    )
    assert run_resp.status_code == 202
    run_id = run_resp.json()["run_id"]
    assert run_resp.json()["status"] == "QUEUED"

    # 7. Worker processes the queued run
    queue = PostgresQueueAdapter(pg_dsn)
    store = PostgresAssessmentStoreAdapter(pg_dsn)
    orchestrator = EvaluationOrchestrator(
        compute_engine=spark_adapter,
        assessment_store=store,
        queue_port=queue,
    )
    worker = EvaluationWorker(
        queue_port=queue,
        orchestrator=orchestrator,
        worker_id="e2e-worker-01",
        poll_interval=0.01,
        heartbeat_interval=0.5,
    )
    assessment = worker.run_once()
    assert assessment is not None
    assert str(assessment.run_id) == str(run_id)

    # 8. Poll Run Status via API
    status_resp = client.get(f"/api/v1/runs/{run_id}/status", headers=steward_hdr)
    assert status_resp.status_code == 200
    assert status_resp.json()["status"] == "SUCCEEDED"
    assert status_resp.json()["assessment_id"] == str(assessment.assessment_id)

    # 9. Query Published Assessment Scorecard
    assessment_resp = client.get(f"/api/v1/assessments/{assessment.assessment_id}", headers=steward_hdr)
    assert assessment_resp.status_code == 200
    scorecard = assessment_resp.json()
    assert scorecard["publication_status"] == "PUBLISHED"
    assert scorecard["quality_gate"] == "PASS"
    assert scorecard["dq_score"] is not None
    assert scorecard["dq_score"] > 90.0
    assert len(scorecard["dimension_results"]) > 0

