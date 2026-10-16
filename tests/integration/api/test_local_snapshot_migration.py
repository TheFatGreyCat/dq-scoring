"""Sandbox migration preserves history and requires drained legacy runs."""
import hashlib
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from dq_scoring.presentation.cli.migrate_local_snapshots import migrate


def test_dry_run_and_apply_preserve_historical_snapshot(db_conn, tmp_path):
    tenant, user, asset, old = uuid4(), uuid4(), uuid4(), uuid4()
    raw = b'id,amount\n1,12\n2,-1\n'
    path = tmp_path / 'legacy.csv'
    path.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    with db_conn.cursor() as cur:
        cur.execute("INSERT INTO tenants(tenant_id,tenant_code,tenant_name) VALUES (%s,%s,'Synthetic')", (tenant, tenant.hex))
        cur.execute("INSERT INTO users(user_id,email,password_hash,full_name) VALUES (%s,%s,'synthetic','Synthetic')", (user, f'{user}@example.test'))
        cur.execute("INSERT INTO data_assets(asset_id,tenant_id,asset_name,slug,format,owner_user_id,created_by) VALUES (%s,%s,'Legacy',%s,'CSV',%s,%s)", (asset, tenant, asset.hex, user, user))
        cur.execute("INSERT INTO dataset_snapshots(snapshot_id,tenant_id,asset_id,version_number,source_kind,source_descriptor,content_sha256,storage_location,schema_definition,total_rows,total_columns,created_by,captured_at) VALUES (%s,%s,%s,1,'LOCAL_FILE',%s,%s,'legacy.csv','{}',2,2,%s,now())", (old, tenant, asset, Jsonb({'path': 'legacy.csv', 'format': 'CSV'}), digest, user))
    db_conn.commit()
    report = migrate(db_conn, tenant, [asset], tmp_path, False)
    assert report == [{'old_snapshot_id': str(old), 'status': 'VALIDATED'}]
    assert db_conn.execute('SELECT count(*) FROM dataset_snapshots WHERE asset_id=%s', (asset,)).fetchone()[0] == 1
    db_conn.commit()
    report = migrate(db_conn, tenant, [asset], tmp_path, True)
    db_conn.commit()
    successor = report[0]['new_snapshot_id']
    historical = db_conn.execute('SELECT source_kind,content_sha256,source_descriptor FROM dataset_snapshots WHERE snapshot_id=%s', (old,)).fetchone()
    assert historical == ('LOCAL_FILE', digest, {'path': 'legacy.csv', 'format': 'CSV'})
    created = db_conn.execute('SELECT source_kind,content_sha256,parent_snapshot_id FROM dataset_snapshots WHERE snapshot_id=%s', (successor,)).fetchone()
    assert created == ('OBJECT_FILE', digest, old)
    assert db_conn.execute('SELECT current_snapshot_id FROM data_assets WHERE asset_id=%s', (asset,)).fetchone()[0] == UUID(successor)
