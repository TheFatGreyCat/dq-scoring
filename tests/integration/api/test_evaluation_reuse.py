"""Evaluation reuse: published results are reused per owner; idempotency keys never leak across users or payloads."""
from uuid import uuid4

import pytest

from dq_scoring.adapters.db.tenant_context import set_tenant_context
from dq_scoring.adapters.queue.postgres_queue import PostgresQueueAdapter
from dq_scoring.common.profiling import ProfileRequiredError
from dq_scoring.core.exceptions import IdempotencyConflictError
from dq_scoring.presentation.api.auth import hash_password
from tests.integration.conftest import PASSWORD, _login
from tests.support.run_seed import seed_run_prerequisites

SHA = "a" * 64
COLUMNS = [
    {"index": 0, "original_name": "fare", "name": "fare", "type": "STRING", "nullable": True},
    {"index": 1, "original_name": "trip_seconds", "name": "trip_seconds", "type": "STRING", "nullable": True},
]


def v2_descriptor() -> dict:
    return {
        "descriptor_version": 2, "storage_mode": "OWNED_RAW", "bucket": "snap", "key": "snapshots/t/u/source.csv",
        "version_id": "v1", "content_sha256": SHA, "size_bytes": 10, "format": "CSV", "normalization_version": 1,
        "normalization": {"version": 1, "format": "CSV", "delimiter": ",", "encoding": "utf-8-sig",
                          "columns": COLUMNS},
    }


def owner_id(db_conn, tenant) -> str:
    return db_conn.execute("SELECT user_id FROM tenant_memberships WHERE tenant_id=%s AND role='DATA_ENGINEER'",
                           (tenant.tenant_id,)).fetchone()[0]


@pytest.fixture
def prepared(pg_dsn, sample_run_spec, tenant, db_conn):
    """Approved config plus a COMPLETE FULL profile over a v2 raw snapshot, owned by the tenant creator."""
    snapshot = sample_run_spec.snapshot.model_copy(update={
        "tenant_id": tenant.tenant_id, "source_descriptor": v2_descriptor(),
        "schema_definition": {"columns": COLUMNS}, "total_rows": 2, "total_columns": 2})
    spec = seed_run_prerequisites(pg_dsn, sample_run_spec.model_copy(update={
        "tenant_id": tenant.tenant_id, "snapshot": snapshot, "created_by": owner_id(db_conn, tenant)}))
    return spec


def body(spec, **extra) -> dict:
    return {"snapshot_id": str(spec.snapshot.snapshot_id), "ruleset_id": str(spec.ruleset_id),
            "policy_id": str(spec.policy_id), **extra}


def finish(db_conn, run_id, publication="PUBLISHED") -> None:
    """Complete a queued run the way a worker would: SUCCEEDED + immutable assessment."""
    row = db_conn.execute("SELECT tenant_id,snapshot_id FROM evaluation_runs WHERE run_id=%s", (run_id,)).fetchone()
    db_conn.execute("UPDATE evaluation_runs SET run_status='SUCCEEDED',completed_at=now() WHERE run_id=%s", (run_id,))
    db_conn.execute(
        "INSERT INTO assessments(assessment_id,tenant_id,run_id,snapshot_id,dq_score,publication_status,visibility_scope,"
        "confidence_status,quality_gate,config_hashes,assessment_hash,published_at) "
        "VALUES(%s,%s,%s,%s,%s,%s,'PRIVATE','CONFIDENT','PASS','{}',repeat('1',64),now())",
        (uuid4(), row[0], run_id, row[1], 90 if publication == "PUBLISHED" else None, publication))
    db_conn.commit()


def run_count(db_conn, spec) -> int:
    return db_conn.execute("SELECT count(*) FROM evaluation_runs WHERE tenant_id=%s", (spec.tenant_id,)).fetchone()[0]


def test_published_run_is_reused_with_200_and_no_new_run(client, tenant, prepared, db_conn):
    first = client.post("/api/v1/runs", headers=tenant.creator, json=body(prepared))
    assert first.status_code == 202
    finish(db_conn, first.json()["run_id"])
    hit = client.post("/api/v1/runs", headers=tenant.creator, json=body(prepared, execution_profile="SPARK_K3S"))
    assert hit.status_code == 200
    payload = hit.json()
    assert payload["run_id"] == first.json()["run_id"] and payload["status"] == "SUCCEEDED"
    assert payload["assessment_id"] and payload["completed_at"]
    assert run_count(db_conn, prepared) == 1


def test_pending_withheld_disabled_and_keyed_requests_miss(client, tenant, prepared, db_conn):
    first = client.post("/api/v1/runs", headers=tenant.creator, json=body(prepared))
    assert client.post("/api/v1/runs", headers=tenant.creator, json=body(prepared)).status_code == 202  # still QUEUED
    withheld = client.post("/api/v1/runs", headers=tenant.creator, json=body(prepared, outlier_columns=["fare"]))
    finish(db_conn, withheld.json()["run_id"], "WITHHELD")
    assert client.post("/api/v1/runs", headers=tenant.creator, json=body(prepared, outlier_columns=["fare"])).status_code == 202
    finish(db_conn, first.json()["run_id"])
    assert client.post("/api/v1/runs", headers=tenant.creator, json=body(prepared, reuse_completed=False)).status_code == 202
    keyed = client.post("/api/v1/runs", headers=tenant.creator, json=body(prepared, idempotency_key=str(uuid4())))
    assert keyed.status_code == 202 and keyed.json()["run_id"] != first.json()["run_id"]


def test_outlier_order_changes_identity(client, tenant, prepared, db_conn):
    ordered = body(prepared, outlier_columns=["fare", "trip_seconds"])
    first = client.post("/api/v1/runs", headers=tenant.creator, json=ordered)
    finish(db_conn, first.json()["run_id"])
    assert client.post("/api/v1/runs", headers=tenant.creator, json=ordered).status_code == 200
    swapped = body(prepared, outlier_columns=["trip_seconds", "fare"])
    assert client.post("/api/v1/runs", headers=tenant.creator, json=swapped).status_code == 202


def test_reuse_is_owner_only(client, tenant, prepared, db_conn):
    first = client.post("/api/v1/runs", headers=tenant.creator, json=body(prepared))
    finish(db_conn, first.json()["run_id"])
    other, email = uuid4(), f"other_{uuid4().hex[:8]}@example.com"
    db_conn.execute("INSERT INTO users(user_id,email,password_hash,full_name,is_active) VALUES(%s,%s,%s,'Synthetic',TRUE)",
                    (other, email, hash_password(PASSWORD)))
    db_conn.execute("INSERT INTO tenant_memberships(tenant_id,user_id,role,status) VALUES(%s,%s,'DATA_ENGINEER','ACTIVE')",
                    (tenant.tenant_id, other))
    db_conn.commit()
    headers = _login(client, email, tenant.tenant_id)
    mine = client.post("/api/v1/runs", headers=headers, json=body(prepared))
    assert mine.status_code == 202 and mine.json()["run_id"] != first.json()["run_id"]


def test_validation_precedes_reuse(client, tenant, prepared, db_conn):
    first = client.post("/api/v1/runs", headers=tenant.creator, json=body(prepared))
    finish(db_conn, first.json()["run_id"])
    db_conn.execute("UPDATE rulesets SET status='DEPRECATED' WHERE ruleset_id=%s", (prepared.ruleset_id,))
    db_conn.commit()
    assert client.post("/api/v1/runs", headers=tenant.creator, json=body(prepared)).status_code == 422


def test_missing_full_profile_is_409_even_with_reusable_history(client, tenant, pg_dsn, sample_run_spec, prepared, db_conn):
    first = client.post("/api/v1/runs", headers=tenant.creator, json=body(prepared))
    finish(db_conn, first.json()["run_id"])
    fresh_snapshot = prepared.snapshot.model_copy(update={'snapshot_id': uuid4(), 'asset_id': uuid4()})
    fresh = seed_run_prerequisites(pg_dsn, prepared.model_copy(update={'snapshot': fresh_snapshot, 'ruleset_id': uuid4(),
        'rules': [rule.model_copy(update={'rule_id': uuid4()}) for rule in prepared.rules]}), profile_ready=False)
    response = client.post("/api/v1/runs", headers=tenant.creator, json=body(fresh))
    assert response.status_code == 409 and response.json()["code"] == "FULL_PROFILE_REQUIRED"


def test_explicit_key_retry_returns_existing_even_after_config_deprecated(client, tenant, prepared, db_conn):
    key = str(uuid4())
    first = client.post("/api/v1/runs", headers=tenant.creator, json=body(prepared, idempotency_key=key))
    db_conn.execute("UPDATE rulesets SET status='DEPRECATED' WHERE ruleset_id=%s", (prepared.ruleset_id,))
    db_conn.commit()
    retry = client.post("/api/v1/runs", headers=tenant.creator, json=body(prepared, idempotency_key=key))
    assert retry.status_code == 202 and retry.json()["run_id"] == first.json()["run_id"]


def test_explicit_key_conflicts_for_other_payload_or_other_owner(client, tenant, prepared, db_conn):
    key = str(uuid4())
    first = client.post("/api/v1/runs", headers=tenant.creator, json=body(prepared, idempotency_key=key))
    changed = client.post("/api/v1/runs", headers=tenant.creator,
                          json=body(prepared, idempotency_key=key, outlier_columns=["fare"]))
    assert changed.status_code == 409 and changed.json()["code"] == "IDEMPOTENCY_CONFLICT"
    other, email = uuid4(), f"other_{uuid4().hex[:8]}@example.com"
    db_conn.execute("INSERT INTO users(user_id,email,password_hash,full_name,is_active) VALUES(%s,%s,%s,'Synthetic',TRUE)",
                    (other, email, hash_password(PASSWORD)))
    db_conn.execute("INSERT INTO tenant_memberships(tenant_id,user_id,role,status) VALUES(%s,%s,'DATA_ENGINEER','ACTIVE')",
                    (tenant.tenant_id, other))
    db_conn.commit()
    foreign = client.post("/api/v1/runs", headers=_login(client, email, tenant.tenant_id),
                          json=body(prepared, idempotency_key=key))
    assert foreign.status_code == 409 and first.json()["run_id"] not in foreign.text


def test_legacy_run_without_run_spec_matches_scalars_only(client, tenant, prepared, db_conn):
    key = str(uuid4())
    run = uuid4()

    def insert(outlier_config: dict, idem: str) -> None:
        db_conn.execute(
            "INSERT INTO evaluation_runs(run_id,tenant_id,snapshot_id,ruleset_id,policy_id,idempotency_key,outlier_config,"
            "outlier_config_hash,run_status,created_by) VALUES(%s,%s,%s,%s,%s,%s,%s::jsonb,'legacy','QUEUED',%s)",
            (run if idem == key else uuid4(), tenant.tenant_id, prepared.snapshot.snapshot_id, prepared.ruleset_id,
             prepared.policy_id, idem, __import__("json").dumps(outlier_config), prepared.created_by))
        db_conn.commit()

    insert({"outlier_columns": []}, key)
    assert client.post("/api/v1/runs", headers=tenant.creator, json=body(prepared, idempotency_key=key)).json()["run_id"] == str(run)
    missing = str(uuid4())
    insert({}, missing)  # outlier_columns unreadable: conflict, not a guess
    response = client.post("/api/v1/runs", headers=tenant.creator, json=body(prepared, idempotency_key=missing))
    assert response.status_code == 409 and response.json()["code"] == "IDEMPOTENCY_CONFLICT"


def test_queue_stores_fingerprint_and_pins_full_profile(pg_dsn, prepared, db_conn):
    queue = PostgresQueueAdapter(dsn=pg_dsn)
    run = queue.enqueue_run(prepared, str(uuid4()))
    fingerprint, stored = db_conn.execute(
        "SELECT evaluation_fingerprint, outlier_config->'_run_spec' FROM evaluation_runs WHERE run_id=%s", (run,)).fetchone()
    assert len(fingerprint) == 64 and stored["profile_id"] and len(stored["profile_fingerprint"]) == 64


def test_queue_rejects_without_full_profile(pg_dsn, prepared, db_conn):
    fresh = seed_run_prerequisites(pg_dsn, prepared.model_copy(
        update={'snapshot': prepared.snapshot.model_copy(update={'snapshot_id': uuid4(), 'asset_id': uuid4()})}), profile_ready=False)
    with pytest.raises(ProfileRequiredError):
        PostgresQueueAdapter(dsn=pg_dsn).enqueue_run(fresh, str(uuid4()))


@pytest.mark.parametrize('conflict', ['owner', 'payload'])
def test_queue_race_loser_is_authorized_against_winner(pg_dsn, prepared, db_conn, monkeypatch, conflict):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier, local
    key = str(uuid4())
    competitor = prepared.model_copy(update={'run_id': uuid4()})
    if conflict == 'owner':
        competitor = seed_run_prerequisites(pg_dsn, competitor.model_copy(update={'created_by': uuid4()}))
    else:
        competitor = competitor.model_copy(update={'outlier_columns': ['fare']})
    barrier, thread_state = Barrier(2), local()
    real = PostgresQueueAdapter._authorized_existing
    def synchronized_lookup(cur, spec, idempotency_key):
        existing = real(cur, spec, idempotency_key)
        if not getattr(thread_state, 'looked_up', False):
            thread_state.looked_up = True
            barrier.wait(timeout=10)
        return existing
    monkeypatch.setattr(PostgresQueueAdapter, '_authorized_existing', staticmethod(synchronized_lookup))
    def enqueue(spec):
        try:
            return PostgresQueueAdapter(dsn=pg_dsn).enqueue_run(spec, key)
        except IdempotencyConflictError:
            return 'IDEMPOTENCY_CONFLICT'
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(enqueue, [prepared, competitor]))
    assert outcomes.count('IDEMPOTENCY_CONFLICT') == 1
    winner = next(result for result in outcomes if result != 'IDEMPOTENCY_CONFLICT')
    set_tenant_context(db_conn, prepared.tenant_id)
    assert db_conn.execute('SELECT run_id FROM evaluation_runs WHERE tenant_id=%s AND idempotency_key=%s', (prepared.tenant_id, key)).fetchall() == [(winner,)]


def test_key_race_loser_returns_winner_state_and_time(client, tenant, prepared, db_conn):
    from dq_scoring.presentation.api.dependencies import get_queue_port
    key = str(uuid4())
    def competing_queue():
        class CompetingQueue:
            def enqueue_run(self, spec, idempotency_key):
                winner = spec.model_copy(update={'run_id': uuid4()})
                winner_id = PostgresQueueAdapter(connection=db_conn).enqueue_run(winner, idempotency_key)
                finish(db_conn, winner_id)
                return winner_id
        return CompetingQueue()
    client.app.dependency_overrides[get_queue_port] = competing_queue
    try:
        response = client.post('/api/v1/runs', headers=tenant.creator, json=body(prepared, idempotency_key=key))
        assert response.status_code == 202, response.text
        payload = response.json()
        state, created_at = db_conn.execute('SELECT run_status,created_at FROM evaluation_runs WHERE run_id=%s', (payload['run_id'],)).fetchone()
        assert payload['status'] == state == 'SUCCEEDED'
        from datetime import datetime
        assert datetime.fromisoformat(payload['created_at']) == created_at
    finally:
        client.app.dependency_overrides.pop(get_queue_port, None)
