"""Production queue gate is evaluated after existing idempotency lookup."""
import pytest

from dq_scoring.adapters.queue.postgres_queue import PostgresQueueAdapter
from dq_scoring.common.profiling import ProfileRequiredError
from tests.support.run_seed import seed_run_prerequisites


def test_queue_rejects_missing_full_without_inserting(pg_dsn, sample_run_spec, db_conn):
    spec = seed_run_prerequisites(pg_dsn, sample_run_spec,profile_ready=False)
    with pytest.raises(ProfileRequiredError):
        PostgresQueueAdapter(dsn=pg_dsn).enqueue_run(spec,"missing-profile")
    assert db_conn.execute("SELECT count(*) FROM evaluation_runs WHERE run_id=%s",(spec.run_id,)).fetchone() == (0,)


def test_api_requires_full_then_pins_profile_and_preserves_retry(client,tenant,pg_dsn,db_conn,sample_run_spec,monkeypatch):
    from uuid import uuid4

    from dq_scoring.adapters.compute.spark_compute import PySparkComputeAdapter
    from dq_scoring.adapters.db.tenant_context import set_tenant_context
    from dq_scoring.adapters.queue.postgres_profile_queue import PostgresProfileQueue
    from dq_scoring.services.snapshot_profile_service import load_snapshot
    from dq_scoring.workers.snapshot_profile_worker import SnapshotProfileWorker
    from tests.support.object_snapshots import register_snapshot_via_api

    registered=register_snapshot_via_api(client,tenant.creator,content_or_path=b"fare,trip_seconds\n12,20\n,30\n")
    set_tenant_context(db_conn,tenant.tenant_id)
    snapshot=load_snapshot(db_conn,tenant.tenant_id,registered["snapshot_id"])
    db_conn.commit()
    spec=seed_run_prerequisites(pg_dsn,sample_run_spec.model_copy(update={"tenant_id":tenant.tenant_id,"snapshot":snapshot}),profile_ready=False)
    body={"snapshot_id":str(snapshot.snapshot_id),"ruleset_id":str(spec.ruleset_id),"policy_id":str(spec.policy_id),"idempotency_key":str(uuid4())}
    rejected=client.post('/api/v1/runs',headers=tenant.creator,json=body)
    assert rejected.status_code==409 and rejected.json()['code']=='FULL_PROFILE_REQUIRED'
    assert db_conn.execute('SELECT count(*) FROM evaluation_runs WHERE snapshot_id=%s',(snapshot.snapshot_id,)).fetchone()==(0,)
    db_conn.commit()
    worker=SnapshotProfileWorker(PostgresProfileQueue(pg_dsn,"api-gate-smoke"),PySparkComputeAdapter())
    assert worker.run_once()
    accepted=client.post('/api/v1/runs',headers=tenant.creator,json=body)
    assert accepted.status_code==202
    run_id=accepted.json()['run_id']
    stored=db_conn.execute("SELECT outlier_config->'_run_spec' FROM evaluation_runs WHERE run_id=%s",(run_id,)).fetchone()[0]
    assert stored['profile_id'] and len(stored['profile_fingerprint'])==64
    db_conn.commit()
    from dq_scoring.adapters.db.postgres_assessment_store import (
        PostgresAssessmentStoreAdapter,
    )
    from dq_scoring.services.evaluation_orchestrator import EvaluationOrchestrator
    from dq_scoring.workers.evaluation_worker import EvaluationWorker
    queue=PostgresQueueAdapter(dsn=pg_dsn)
    assessment=EvaluationWorker(queue,EvaluationOrchestrator(worker.compute,PostgresAssessmentStoreAdapter(dsn=pg_dsn),queue)).run_once()
    assert str(assessment.run_id)==run_id
    import dq_scoring.services.snapshot_profile_service as profiles
    monkeypatch.setattr(profiles,'current_full_profile',lambda *args:None)
    retry=client.post('/api/v1/runs',headers=tenant.creator,json=body)
    assert retry.status_code==202 and retry.json()['run_id']==run_id


@pytest.mark.parametrize('state',['QUEUED','RUNNING','FAILED'])
def test_noncomplete_current_profile_never_inserts_run(pg_dsn,sample_run_spec,db_conn,state):
    from dq_scoring.adapters.db.tenant_context import set_tenant_context
    from dq_scoring.adapters.queue.postgres_profile_queue import PostgresProfileQueue
    from dq_scoring.services.snapshot_profile_service import ensure_full_profile
    spec=seed_run_prerequisites(pg_dsn,sample_run_spec,profile_ready=False)
    set_tenant_context(db_conn,spec.tenant_id)
    ensure_full_profile(db_conn,spec.tenant_id,spec.snapshot.snapshot_id)
    db_conn.commit()
    if state != 'QUEUED':
        queue=PostgresProfileQueue(pg_dsn,'gate-state')
        claimed=queue.claim_next_job()
        if state=='FAILED':
            assert queue.fail(claimed,'PROFILE_FAILED')
    with pytest.raises(ProfileRequiredError) as rejected:
        PostgresQueueAdapter(dsn=pg_dsn).enqueue_run(spec,'state-test')
    assert rejected.value.job['state']==state
    assert db_conn.execute('SELECT count(*) FROM evaluation_runs WHERE run_id=%s',(spec.run_id,)).fetchone()==(0,)

def test_queue_rejects_complete_profile_from_different_snapshot(pg_dsn, sample_run_spec, db_conn):
    from uuid import uuid4
    seed_run_prerequisites(pg_dsn, sample_run_spec, profile_ready=True)
    snapshot_b = sample_run_spec.snapshot.model_copy(update={"snapshot_id": uuid4(), "asset_id": uuid4()})
    spec_b = seed_run_prerequisites(
        pg_dsn,
        sample_run_spec.model_copy(update={"run_id": uuid4(), "snapshot": snapshot_b}),
        profile_ready=False,
    )
    with pytest.raises(ProfileRequiredError):
        PostgresQueueAdapter(dsn=pg_dsn).enqueue_run(spec_b, "key-diff-snap")
    assert db_conn.execute("SELECT count(*) FROM evaluation_runs WHERE snapshot_id=%s", (snapshot_b.snapshot_id,)).fetchone() == (0,)


def test_queue_rejects_altered_schema_or_canonical_descriptor_against_complete_profile(pg_dsn, sample_run_spec, db_conn):
    from uuid import uuid4
    spec = seed_run_prerequisites(pg_dsn, sample_run_spec, profile_ready=True)

    alt_schema = spec.model_copy(
        update={
            "run_id": uuid4(),
            "snapshot": spec.snapshot.model_copy(update={"schema_definition": {"columns": ["unprofiled_col"]}}),
        }
    )
    with pytest.raises(ProfileRequiredError):
        PostgresQueueAdapter(dsn=pg_dsn).enqueue_run(alt_schema, f"alt-schema-{uuid4()}")
    assert db_conn.execute("SELECT count(*) FROM evaluation_runs WHERE run_id=%s", (alt_schema.run_id,)).fetchone() == (0,)

    alt_canonical = spec.model_copy(
        update={
            "run_id": uuid4(),
            "snapshot": spec.snapshot.model_copy(
                update={
                    "source_descriptor": {
                        **spec.snapshot.source_descriptor,
                        "canonical": {**spec.snapshot.source_descriptor["canonical"], "version_id": "v-altered"},
                    }
                }
            ),
        }
    )
    with pytest.raises(ProfileRequiredError):
        PostgresQueueAdapter(dsn=pg_dsn).enqueue_run(alt_canonical, f"alt-canonical-{uuid4()}")
    assert db_conn.execute("SELECT count(*) FROM evaluation_runs WHERE run_id=%s", (alt_canonical.run_id,)).fetchone() == (0,)


def test_direct_queue_idempotency_retry_succeeds_even_if_readiness_unavailable(pg_dsn, sample_run_spec, db_conn):
    from uuid import uuid4
    queue = PostgresQueueAdapter(dsn=pg_dsn)
    spec = seed_run_prerequisites(pg_dsn, sample_run_spec, profile_ready=True)
    key = f"direct-retry-{uuid4()}"
    run_id = queue.enqueue_run(spec, key)
    assert run_id == spec.run_id

    db_conn.execute(
        "DELETE FROM snapshot_profile_jobs WHERE snapshot_id=%s;",
        (spec.snapshot.snapshot_id,),
    )
    db_conn.commit()

    retried_id = queue.enqueue_run(spec, key)
    assert retried_id == run_id
    assert db_conn.execute('SELECT count(*) FROM evaluation_runs WHERE run_id=%s',(spec.run_id,)).fetchone()==(1,)
