"""Exercise real canonical scans and lease fencing using synthetic storage."""
import os
from uuid import UUID

import psycopg

from dq_scoring.adapters.storage.s3_object_store import S3ObjectStoreAdapter
from dq_scoring.workers.privacy_scan_worker import PrivacyScanWorker
from tests.integration.api.test_privacy_routes import client, org  # noqa: F401
from tests.integration.conftest import _login
from tests.support.object_snapshots import register_snapshot_via_api


def test_apply_worker_publishes_and_reclaims_expired_lease(client, org, db_conn):  # noqa: F811
    headers = _login(client, org["owner"][1], org["tenant_id"])
    snapshot = register_snapshot_via_api(client, headers, content_or_path=b'id,email,notes\nA,qa@example.com,SYN-01\n')
    sid = snapshot["snapshot_id"]
    before = client.get(f"/api/v1/snapshots/{sid}/column-classifications", headers=headers).json()
    queued = client.post(f"/api/v1/snapshots/{sid}/privacy-scans", headers=headers, json={"purpose": "APPLY"})
    assert queued.status_code == 202
    worker = PrivacyScanWorker(S3ObjectStoreAdapter(), worker_id="synthetic-worker-a")
    successor = PrivacyScanWorker(S3ObjectStoreAdapter(), worker_id="synthetic-worker-b")
    with psycopg.connect(os.environ["DQ_TEST_POSTGRES_DSN"], autocommit=True) as conn:
        conn.execute("SET ROLE dq_worker_role")
        job = worker.claim_next_job(conn)
        assert str(job["scan_id"]) == queued.json()["scan_id"]
        assert successor.claim_next_job(conn) is None
        assert worker.heartbeat(conn, job["scan_id"], job["lease_generation"], tenant_id=job["tenant_id"])
        db_conn.execute("UPDATE privacy_scan_jobs SET lease_expires_at=now()-interval '1 second' WHERE scan_id=%s", (job["scan_id"],))
        db_conn.commit()
        replacement = successor.claim_next_job(conn)
        assert replacement["lease_generation"] == job["lease_generation"] + 1
        assert not worker.heartbeat(conn, job["scan_id"], job["lease_generation"], tenant_id=job["tenant_id"])
        assert worker.process_job(conn, job) is False
        assert successor.process_job(conn, replacement) is True
    state = client.get(f"/api/v1/privacy-scans/{queued.json()['scan_id']}", headers=headers).json()
    assert state["state"] == "COMPLETE", state
    findings = client.get(f"/api/v1/snapshots/{sid}/sensitive-findings", headers=headers).json()
    email = next(f for f in findings["findings"]["items"] if f["detector_code"] == "EMAIL")
    assert email["scan_id"] == queued.json()["scan_id"]
    assert UUID(email["rule_id"])
    after = client.get(f"/api/v1/snapshots/{sid}/column-classifications", headers=headers).json()
    assert after["version"] == before["version"] + 2  # queue invalidation and publication
    assert next(c for c in after["columns"] if c["column_name"] == "email")["protected"]
    assert not next(c for c in after["columns"] if c["column_name"] == "id")["protected"]


def test_preview_isolation_and_apply_inherits_same_revision_decisions(client, org, db_conn):  # noqa: F811
    headers = _login(client, org["owner"][1], org["tenant_id"])
    snapshot = register_snapshot_via_api(client, headers, content_or_path=b'id,email\nA,qa@example.com\n')
    sid = snapshot["snapshot_id"]
    findings_url = f"/api/v1/snapshots/{sid}/sensitive-findings"
    initial = client.get(findings_url, headers=headers).json()
    email = next(f for f in initial["findings"]["items"] if f["detector_code"] == "EMAIL")
    assert client.patch(f"/api/v1/sensitive-findings/{email['finding_id']}", headers=headers, json={
        "expected_status": "DETECTED", "status": "DISMISSED", "reason": "Synthetic false positive",
    }).status_code == 200
    worker = PrivacyScanWorker(S3ObjectStoreAdapter(), worker_id="synthetic-worker")
    classification_url = f"/api/v1/snapshots/{sid}/column-classifications"
    before = client.get(classification_url, headers=headers).json()
    with psycopg.connect(os.environ["DQ_TEST_POSTGRES_DSN"], autocommit=True) as conn:
        conn.execute("SET ROLE dq_worker_role")
        for purpose in ("PREVIEW", "APPLY"):
            payload = {"purpose": purpose}
            if purpose == "PREVIEW":
                payload.update(rule_id=email["rule_id"], revision=email["rule_revision"])
            queued = client.post(f"/api/v1/snapshots/{sid}/privacy-scans", headers=headers, json=payload)
            assert queued.status_code == 202
            job = worker.claim_next_job(conn)
            assert worker.process_job(conn, job)
            state = client.get(f"/api/v1/privacy-scans/{queued.json()['scan_id']}", headers=headers).json()
            assert state["state"] == "COMPLETE", state
            if purpose == "PREVIEW":
                assert state["result_summary"]["findings"][0]["matched_count"] == 1
                assert "qa@example.com" not in str(state)
                assert client.get(classification_url, headers=headers).json() == before
            else:
                current = client.get(findings_url, headers=headers).json()
                inherited = next(f for f in current["findings"]["items"] if f["detector_code"] == "EMAIL")
                assert inherited["status"] == "DISMISSED"
                assert inherited["finding_id"] != email["finding_id"]
                assert inherited["scan_id"] == queued.json()["scan_id"]
                assert not next(c for c in client.get(classification_url, headers=headers).json()["columns"] if c["column_name"] == "email")["protected"]


def test_terminal_scan_failure_is_audited_without_raw_error(client, org, db_conn):  # noqa: F811
    from tests.integration.api.test_privacy_routes import _seed_asset_and_snapshot

    headers = _login(client, org["owner"][1], org["tenant_id"])
    _, sid, _ = _seed_asset_and_snapshot(db_conn, org["tenant_id"], org["owner"][0])
    db_conn.commit()
    queued = client.post(f"/api/v1/snapshots/{sid}/privacy-scans", headers=headers, json={"purpose": "APPLY"}).json()
    worker = PrivacyScanWorker(S3ObjectStoreAdapter(), worker_id="synthetic-failure-worker")
    with psycopg.connect(os.environ["DQ_TEST_POSTGRES_DSN"], autocommit=True) as conn:
        conn.execute("SET ROLE dq_worker_role")
        job = worker.claim_next_job(conn)
        assert worker.process_job(conn, job)
    state = client.get(f"/api/v1/privacy-scans/{queued['scan_id']}", headers=headers).json()
    assert state["state"] == "FAILED"
    assert state["error_code"] == "SNAPSHOT_REIMPORT_REQUIRED"
    event = db_conn.execute("SELECT actor_user_id,after_state FROM privacy_change_events WHERE snapshot_id=%s AND action='PRIVACY_SCAN_FAILED'", (sid,)).fetchone()
    assert event is not None
    assert event[0] == org["owner"][0]
    assert event[1]["error_code"] == "SNAPSHOT_REIMPORT_REQUIRED"


def test_crash_reclaim_exhaustion_emits_terminal_failed_audit_exactly_once(client, org, db_conn):  # noqa: F811
    headers = _login(client, org["owner"][1], org["tenant_id"])
    snapshot = register_snapshot_via_api(client, headers, content_or_path=b"id,email\nA,qa@example.com\n")
    sid = snapshot["snapshot_id"]
    queued = client.post(f"/api/v1/snapshots/{sid}/privacy-scans", headers=headers, json={"purpose": "APPLY"})
    assert queued.status_code == 202
    scan_id = queued.json()["scan_id"]

    class _RejectingStore:
        def __getattr__(self, name: str):
            raise AssertionError(f"Object I/O performed unexpectedly: {name}")

    worker = PrivacyScanWorker(_RejectingStore(), worker_id="synthetic-exhaustion-worker")

    with psycopg.connect(os.environ["DQ_TEST_POSTGRES_DSN"], autocommit=True) as conn:
        conn.execute("SET ROLE dq_worker_role")
        last_job = None
        for attempt in range(1, 4):
            last_job = worker.claim_next_job(conn)
            assert last_job is not None
            assert last_job["attempt_count"] == attempt
            db_conn.execute(
                "UPDATE privacy_scan_jobs SET lease_expires_at = now() - interval '1 second' WHERE scan_id = %s",
                (last_job["scan_id"],),
            )
            db_conn.commit()

        # Reclaim after exhaustion (attempt 4 > MAX_ATTEMPTS)
        exhausted_job = worker.claim_next_job(conn)
        assert exhausted_job is not None
        assert exhausted_job["attempt_count"] == 4
        # Process routes through _fail under fenced lease without touching store or asset locks
        assert worker.process_job(conn, exhausted_job) is True

        # Further claims find nothing active
        assert worker.claim_next_job(conn) is None

        # Stale attempt from crashed worker is fenced out
        assert worker.process_job(conn, last_job) is False

    state = client.get(f"/api/v1/privacy-scans/{scan_id}", headers=headers).json()
    assert state["state"] == "FAILED"
    assert state["error_code"] == "PRIVACY_SCAN_FAILED"

    events = db_conn.execute(
        "SELECT actor_user_id, after_state FROM privacy_change_events WHERE snapshot_id = %s AND action = 'PRIVACY_SCAN_FAILED'",
        (sid,),
    ).fetchall()
    assert len(events) == 1
    assert events[0][0] == org["owner"][0]
    assert events[0][1]["scan_id"] == scan_id
    assert events[0][1]["error_code"] == "PRIVACY_SCAN_FAILED"
