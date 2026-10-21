from uuid import uuid4

from dq_scoring.presentation.api.auth import hash_password
from tests.integration.conftest import PASSWORD, _login
from tests.support.object_snapshots import register_snapshot_via_api


def test_modes_are_read_only_and_full_is_queued(client, tenant, db_conn):
    snap=register_snapshot_via_api(client,tenant.creator,content_or_path=b'id,value\nA,1\nB,2\n')
    base=f"/api/v1/snapshots/{snap['snapshot_id']}"
    sample=client.get(base+'/profile?mode=SAMPLE',headers=tenant.creator)
    assert sample.status_code==200
    assert sample.json()['result']['mode']=='SAMPLE'
    assert sample.json()['result']['sampling_method']=='PREFIX'
    full=client.get(base+'/profile?mode=FULL',headers=tenant.creator)
    assert full.status_code==200 and full.json()['state']=='QUEUED'
    first=full.json()['profile_id']
    ensure=client.post(base+'/profiles/full',headers=tenant.creator)
    assert ensure.status_code==202 and ensure.json()['profile_id']==first
    assert db_conn.execute('SELECT count(*) FROM snapshot_profile_jobs WHERE snapshot_id=%s',(snap['snapshot_id'],)).fetchone()==(1,)


def test_get_never_enqueues_and_viewer_cannot_submit(client,tenant,db_conn):
    snap=register_snapshot_via_api(client,tenant.creator,content_or_path=b"id,value\nA,1\n")
    base=f"/api/v1/snapshots/{snap['snapshot_id']}"
    db_conn.execute("DELETE FROM snapshot_profile_jobs WHERE snapshot_id=%s",(snap['snapshot_id'],))
    db_conn.commit()
    result=client.get(base+'/profile?mode=FULL',headers=tenant.creator)
    assert result.status_code==200 and result.json()['state'] is None
    assert db_conn.execute("SELECT count(*) FROM snapshot_profile_jobs WHERE snapshot_id=%s",(snap['snapshot_id'],)).fetchone()==(0,)
    db_conn.execute("UPDATE tenant_memberships SET role='BUSINESS_VIEWER' WHERE tenant_id=%s AND role='DATA_ENGINEER'",(tenant.tenant_id,))
    db_conn.commit()
    assert client.post(base+'/profiles/full',headers=tenant.creator).status_code==403
    assert client.get(base+'/profile?mode=SAMPLE',headers=tenant.creator).status_code==200


def test_cross_tenant_and_missing_profiles_are_not_found(client,tenant):
    from uuid import uuid4
    assert client.get(f'/api/v1/snapshots/{uuid4()}/profile?mode=FULL',headers=tenant.creator).status_code==404
    assert client.post(f'/api/v1/snapshots/{uuid4()}/profiles/full',headers=tenant.creator).status_code==404

def test_foreign_tenant_cannot_read_or_submit_profile(client, tenant, db_conn):
    snap = register_snapshot_via_api(client, tenant.creator, content_or_path=b"id,value\nA,1\nB,2\n")
    snap_id = snap["snapshot_id"]

    tenant_b_id, user_b_id = uuid4(), uuid4()
    email_b = f"eng_{user_b_id.hex[:8]}@example.com"
    with db_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO tenants (tenant_id, tenant_code, tenant_name, status) VALUES (%s, %s, 'Tenant B', 'ACTIVE');",
            (tenant_b_id, f"tb_{tenant_b_id.hex[:8]}"),
        )
        cur.execute(
            "INSERT INTO users (user_id, email, password_hash, full_name, is_active) VALUES (%s, %s, %s, 'Eng B', TRUE);",
            (user_b_id, email_b, hash_password(PASSWORD)),
        )
        cur.execute(
            "INSERT INTO tenant_memberships (tenant_id, user_id, role, status) VALUES (%s, %s, 'DATA_ENGINEER', 'ACTIVE');",
            (tenant_b_id, user_b_id),
        )
        db_conn.commit()
    headers_b = _login(client, email_b, tenant_b_id)

    assert client.get(f"/api/v1/snapshots/{snap_id}/profile?mode=FULL", headers=headers_b).status_code == 404
    assert client.get(f"/api/v1/snapshots/{snap_id}/profile?mode=SAMPLE", headers=headers_b).status_code == 404
    assert client.post(f"/api/v1/snapshots/{snap_id}/profiles/full", headers=headers_b).status_code == 404

    with db_conn.cursor() as cur:
        cur.execute("SELECT tenant_id FROM snapshot_profile_jobs WHERE snapshot_id=%s;", (snap_id,))
        jobs = cur.fetchall()
        assert len(jobs) == 1
        assert jobs[0][0] == tenant.tenant_id


def test_revoked_membership_is_forbidden_on_profile_routes(client, tenant, db_conn):
    snap = register_snapshot_via_api(client, tenant.creator, content_or_path=b"id,value\nA,1\n")
    snap_id = snap["snapshot_id"]
    with db_conn.cursor() as cur:
        cur.execute("UPDATE tenant_memberships SET status='SUSPENDED' WHERE tenant_id=%s AND role='DATA_ENGINEER';", (tenant.tenant_id,))
        db_conn.commit()
    assert client.get(f"/api/v1/snapshots/{snap_id}/profile?mode=SAMPLE", headers=tenant.creator).status_code == 403
    assert client.get(f"/api/v1/snapshots/{snap_id}/profile?mode=FULL", headers=tenant.creator).status_code == 403
    assert client.post(f"/api/v1/snapshots/{snap_id}/profiles/full", headers=tenant.creator).status_code == 403


def test_stale_full_profile_is_labeled_stale(client, tenant, pg_dsn, monkeypatch):
    snap = register_snapshot_via_api(client, tenant.creator, content_or_path=b"id,value\nA,1\nB,2\n")
    snap_id = snap["snapshot_id"]
    from dq_scoring.adapters.compute.spark_compute import PySparkComputeAdapter
    from dq_scoring.adapters.queue.postgres_profile_queue import PostgresProfileQueue
    from dq_scoring.workers.snapshot_profile_worker import SnapshotProfileWorker
    worker = SnapshotProfileWorker(PostgresProfileQueue(pg_dsn, "stale-test"), PySparkComputeAdapter())
    assert worker.run_once()

    monkeypatch.setattr("dq_scoring.presentation.api.routes.asset_routes.current_full_profile", lambda *args: None)

    resp = client.get(f"/api/v1/snapshots/{snap_id}/profile?mode=FULL", headers=tenant.creator)
    assert resp.status_code == 200
    data = resp.json()
    assert data["current"] is False
    assert data["stale"] is True
    assert data["state"] == "COMPLETE"


def test_profile_extrema_are_masked_for_protected_columns(client, tenant, db_conn):
    snap = register_snapshot_via_api(client, tenant.creator, content_or_path=b"age,secret_score\n25,10\n40,90\n")
    snap_id = snap["snapshot_id"]
    user_id = db_conn.execute("SELECT user_id FROM tenant_memberships WHERE tenant_id=%s LIMIT 1;", (tenant.tenant_id,)).fetchone()[0]
    with db_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO asset_column_classifications (tenant_id, asset_id, column_name, category, reason, updated_by)
            VALUES (%s, %s, 'secret_score', 'SENSITIVE_PERSONAL_DATA', 'Contains sensitive score', %s)
            ON CONFLICT (tenant_id, asset_id, column_name) DO UPDATE SET category='SENSITIVE_PERSONAL_DATA', updated_by=EXCLUDED.updated_by;
            """,
            (tenant.tenant_id, snap["asset_id"], user_id),
        )
        db_conn.commit()

    resp = client.get(f"/api/v1/snapshots/{snap_id}/profile?mode=SAMPLE", headers=tenant.creator)
    assert resp.status_code == 200
    cols = {c["name"]: c for c in resp.json()["result"]["columns"]}
    assert "min" in cols["age"] and "max" in cols["age"]
    assert "min" not in cols["secret_score"] and "max" not in cols["secret_score"]
    assert cols["secret_score"]["null_count"] == 0
