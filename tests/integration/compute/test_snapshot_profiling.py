"""FULL statistics use actual Spark actions over pinned raw and legacy canonical objects."""
from uuid import uuid4

from dq_scoring.adapters.compute.spark_compute import PySparkComputeAdapter
from tests.support.object_snapshots import create_test_snapshot


def test_full_exact_missing_distinct_and_unknown_parse(tmp_path):
    source = tmp_path / "profile.csv"
    source.write_text('id,amount\nA,12\nA,12\nB,broken\n, \n  ,\n', encoding="utf-8")
    snapshot = create_test_snapshot(source)
    compute = PySparkComputeAdapter()
    try:
        result = compute.profile_snapshot(snapshot, profile_id=uuid4(), fingerprint="a" * 64)
        assert result.mode == "FULL" and result.scanned_rows == result.total_rows == 5
        assert not result.is_sample
        by_name = {c.name: c for c in result.columns}
        assert (by_name["id"].null_count, by_name["id"].non_null_count, by_name["id"].distinct_count) == (2, 3, 2)
        assert (by_name["amount"].null_count, by_name["amount"].distinct_count) == (2, 2)
        assert by_name["amount"].parse_success_count is None
        assert by_name["amount"].parse_reason == "NO_EXPLICIT_TARGET"
    finally:
        compute.release_snapshot(snapshot)


def test_real_worker_publishes_exact_full(client, tenant, pg_dsn, db_conn):
    from dq_scoring.adapters.queue.postgres_profile_queue import PostgresProfileQueue
    from dq_scoring.workers.snapshot_profile_worker import SnapshotProfileWorker
    from tests.support.object_snapshots import register_snapshot_via_api

    snapshot = register_snapshot_via_api(client, tenant.creator, content_or_path=b'id,amount\nA,12\nA,12\nB,broken\n, \n  ,\n')
    compute = PySparkComputeAdapter()
    worker = SnapshotProfileWorker(PostgresProfileQueue(pg_dsn, "spark-profile-smoke"), compute, heartbeat_interval=0.2)
    assert worker.run_once()
    row = db_conn.execute("SELECT state,result,lease_generation,attempt_count FROM snapshot_profile_jobs WHERE snapshot_id=%s", (snapshot['snapshot_id'],)).fetchone()
    assert row[0] == 'COMPLETE'
    assert row[1]['scanned_rows'] == row[1]['total_rows'] == 5
    assert [(c['name'],c['null_count'],c['distinct_count']) for c in row[1]['columns']] == [('id',2,2),('amount',2,2)]
    assert row[2:] == (1,1)
    assert not compute._verified_snapshots


def test_wide_quoted_json_and_explicit_parse(tmp_path):
    import json
    source = tmp_path / "wide.jsonl"
    rows = [{**{f"column_{i}": str(index) for i in range(65)}, "dotted.name": "12" if index == 0 else "broken",
             "back`tick": "2026-10-01" if index == 0 else "invalid", "tiếng Việt": {"nested": index}} for index in range(2)]
    source.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    snapshot = create_test_snapshot(source, file_format="JSONL")
    schema = {**snapshot.schema_definition, "columns": [
        {**column, **({"parse_target": "INTEGER"} if column["name"] == "dotted.name" else
                     {"parse_target": "DATE", "parse_format": "yyyy-MM-dd"} if column["name"] == "back`tick" else {})}
        for column in snapshot.schema_definition["columns"]]}
    snapshot = snapshot.model_copy(update={"schema_definition": schema})
    compute = PySparkComputeAdapter()
    try:
        result = compute.profile_snapshot(snapshot, profile_id=uuid4(), fingerprint="b" * 64)
        columns = {column.name: column for column in result.columns}
        assert len(columns) == 68
        assert columns["dotted.name"].parse_success_count == 1
        assert columns["back`tick"].parse_success_count == 1
        assert columns["tiếng Việt"].distinct_count == 2
        assert columns["tiếng Việt"].parse_success_count is None
    finally:
        compute.release_snapshot(snapshot)


def test_profile_rejects_object_and_row_count_mismatch(tmp_path):
    import pytest

    from dq_scoring.core.exceptions import RunAbortedError
    source = tmp_path / "mismatch.csv"
    source.write_text("id,value\nA,1\n", encoding="utf-8")
    snapshot = create_test_snapshot(source)
    compute = PySparkComputeAdapter()
    try:
        with pytest.raises(RunAbortedError, match="PROFILE_ROW_COUNT_MISMATCH"):
            compute.profile_snapshot(snapshot.model_copy(update={"total_rows": 2}), profile_id=uuid4(), fingerprint="a" * 64)
        compute.release_snapshot(snapshot)
        descriptor = {**snapshot.source_descriptor, 'content_sha256': 'f' * 64}
        with pytest.raises(RunAbortedError, match="OBJECT_CHANGED"):
            compute.profile_snapshot(snapshot.model_copy(update={"source_descriptor": descriptor}), profile_id=uuid4(), fingerprint="a" * 64)
    finally:
        compute.release_snapshot(snapshot)


def test_empty_legacy_canonical_has_zero_counts(tmp_path):
    import hashlib

    import pyarrow as pa
    import pyarrow.parquet as pq

    from dq_scoring.adapters.storage.s3_object_store import S3ObjectStoreAdapter
    from dq_scoring.adapters.storage.s3_settings import get_s3_settings

    source = tmp_path / "seed.csv"
    source.write_text("id,value\nA,1\n", encoding="utf-8")
    snapshot = create_test_snapshot(source)
    empty = tmp_path / "empty.parquet"
    pq.write_table(pa.table({"id": pa.array([], type=pa.string()), "value": pa.array([], type=pa.string())}), empty)
    settings = get_s3_settings()
    meta = S3ObjectStoreAdapter(settings=settings).put_file(settings.bucket_snapshots, f"snapshots/{snapshot.tenant_id}/{uuid4()}/empty.parquet", empty)
    canonical = {"bucket": meta.ref.bucket, "key": meta.ref.key, "version_id": meta.version_id,
        "size_bytes": empty.stat().st_size, "content_sha256": hashlib.sha256(empty.read_bytes()).hexdigest(), "format": "PARQUET"}
    legacy = {key: snapshot.source_descriptor[key] for key in (
        'bucket', 'key', 'version_id', 'size_bytes', 'content_sha256', 'format', 'normalization_version')}
    snapshot = snapshot.model_copy(update={"total_rows": 0, "source_descriptor": {**legacy, "canonical": canonical}})
    compute = PySparkComputeAdapter()
    try:
        profile = compute.profile_snapshot(snapshot, profile_id=uuid4(), fingerprint="c" * 64)
        assert profile.scanned_rows == profile.total_rows == 0
        assert [(c.null_count, c.non_null_count, c.distinct_count) for c in profile.columns] == [(0,0,0),(0,0,0)]
    finally:
        compute.release_snapshot(snapshot)


def test_late_spark_result_cannot_replace_new_generation(client, tenant, pg_dsn, db_conn):
    from dq_scoring.adapters.db.tenant_context import set_tenant_context
    from dq_scoring.adapters.queue.postgres_profile_queue import PostgresProfileQueue
    from dq_scoring.services.snapshot_profile_service import load_snapshot
    from tests.support.object_snapshots import register_snapshot_via_api

    registered = register_snapshot_via_api(client, tenant.creator, content_or_path=b"id,value\nA,1\nB,2\n")
    first, replacement = PostgresProfileQueue(pg_dsn,"late"), PostgresProfileQueue(pg_dsn,"new")
    job = first.claim_next_job()
    set_tenant_context(db_conn,tenant.tenant_id)
    snapshot = load_snapshot(db_conn,tenant.tenant_id,registered["snapshot_id"])
    db_conn.commit()
    compute = PySparkComputeAdapter()
    try:
        result = compute.profile_snapshot(snapshot,profile_id=job["profile_id"],fingerprint=job["fingerprint"])
        db_conn.execute("UPDATE snapshot_profile_jobs SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE profile_id=%s",(job["profile_id"],))
        db_conn.commit()
        newer = replacement.claim_next_job()
        assert newer["lease_generation"] == 2
        assert not first.complete(job,result)
        assert replacement.complete(newer,result)
        assert db_conn.execute("SELECT state,lease_generation FROM snapshot_profile_jobs WHERE profile_id=%s",(job["profile_id"],)).fetchone() == ("COMPLETE",2)
    finally:
        compute.release_snapshot(snapshot)


def test_scheduler_processes_both_real_job_classes(client, tenant, pg_dsn, db_conn, sample_run_spec):
    from dq_scoring.adapters.db.postgres_assessment_store import (
        PostgresAssessmentStoreAdapter,
    )
    from dq_scoring.adapters.db.tenant_context import set_tenant_context
    from dq_scoring.adapters.queue.postgres_profile_queue import PostgresProfileQueue
    from dq_scoring.adapters.queue.postgres_queue import PostgresQueueAdapter
    from dq_scoring.services.evaluation_orchestrator import EvaluationOrchestrator
    from dq_scoring.services.snapshot_profile_service import load_snapshot
    from dq_scoring.workers.evaluation_worker import EvaluationWorker
    from dq_scoring.workers.snapshot_profile_worker import (
        FairProfileScheduler,
        SnapshotProfileWorker,
    )
    from tests.support.object_snapshots import register_snapshot_via_api
    from tests.support.run_seed import seed_run_prerequisites

    registered = register_snapshot_via_api(client, tenant.creator, content_or_path=b"fare,trip_seconds\n12,20\n,30\n")
    set_tenant_context(db_conn,tenant.tenant_id)
    snapshot = load_snapshot(db_conn,tenant.tenant_id,registered["snapshot_id"])
    db_conn.commit()
    spec = seed_run_prerequisites(
        pg_dsn, sample_run_spec.model_copy(update={"tenant_id": tenant.tenant_id, "snapshot": snapshot}), profile_ready=False
    )
    queue = PostgresQueueAdapter(dsn=pg_dsn)
    compute = PySparkComputeAdapter()
    profiles = SnapshotProfileWorker(PostgresProfileQueue(pg_dsn, "fair-profile"), compute)
    assert profiles.run_once()
    assert db_conn.execute("SELECT state FROM snapshot_profile_jobs WHERE snapshot_id=%s", (snapshot.snapshot_id,)).fetchone() == ("COMPLETE",)
    db_conn.commit()
    queue.enqueue_run(spec, str(uuid4()))
    # A second FULL job keeps both queue classes populated so the scheduler must serve each in turn.
    other = register_snapshot_via_api(client, tenant.creator, content_or_path=b"id,value\nA,1\n")
    evaluation = EvaluationWorker(queue, EvaluationOrchestrator(compute, PostgresAssessmentStoreAdapter(dsn=pg_dsn), queue))
    scheduler = FairProfileScheduler(evaluation, SnapshotProfileWorker(PostgresProfileQueue(pg_dsn, "fair-profile-2"), compute))
    assert scheduler.run_once()
    assert scheduler.run_once()
    assert db_conn.execute("SELECT state FROM snapshot_profile_jobs WHERE snapshot_id=%s", (other["snapshot_id"],)).fetchone() == ("COMPLETE",)
    db_conn.commit()
    assert db_conn.execute("SELECT count(*) FROM assessments WHERE run_id=%s", (spec.run_id,)).fetchone() == (1,)


def test_stop_before_action_cancels_future_profile_jobs(client, tenant, pg_dsn, db_conn):
    from dq_scoring.adapters.queue.postgres_profile_queue import PostgresProfileQueue
    from dq_scoring.workers.snapshot_profile_worker import SnapshotProfileWorker
    from tests.support.object_snapshots import register_snapshot_via_api

    registered = register_snapshot_via_api(client, tenant.creator, content_or_path=b"id,value\nA,1\n")

    class StopDuringVerification(PySparkComputeAdapter):
        def verify_snapshot(self, snapshot):
            super().verify_snapshot(snapshot)
            worker.stop()

    compute = StopDuringVerification()
    queue = PostgresProfileQueue(pg_dsn,"cancel-before-action")
    worker = SnapshotProfileWorker(queue,compute)
    assert worker.run_once()
    state = db_conn.execute("SELECT state,result FROM snapshot_profile_jobs WHERE snapshot_id=%s",(registered["snapshot_id"],)).fetchone()
    assert state == ("RUNNING",None)
    assert not compute._verified_snapshots
    # Cancellation is group-scoped: another group's real action still runs.
    compute.spark.sparkContext.setJobGroup(str(uuid4()),"next-work")
    assert compute.spark.range(3).count() == 3
    compute.spark.sparkContext.setLocalProperty("spark.jobGroup.id",None)
