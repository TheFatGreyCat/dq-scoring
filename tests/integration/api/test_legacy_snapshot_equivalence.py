"""Reimport dedup preserves historical descriptors and requires a fenced equivalence witness."""
import hashlib
import io
from uuid import UUID, uuid4

import psycopg
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from psycopg.types.json import Jsonb

from dq_scoring.adapters.storage.s3_object_store import S3ObjectStoreAdapter
from dq_scoring.adapters.storage.s3_settings import get_s3_settings
from dq_scoring.workers.import_worker import ImportWorker
from tests.integration.api.test_import_integrity import (  # noqa: F401
    auth_headers,
    seeded_tenant_and_users,
    test_user_id,
)


@pytest.mark.parametrize('external', [False, True])
def test_missing_legacy_witness_reconfigure_recovers_without_upload(client, db_conn, auth_headers,  # noqa: F811
        seeded_tenant_and_users, test_tenant_id, test_user_id, external, monkeypatch):  # noqa: F811
    tenant = test_tenant_id
    store, settings = S3ObjectStoreAdapter(), get_s3_settings()
    asset, snap, legacy_upload = uuid4(), uuid4(), uuid4()
    raw = b'id,amount\n1,10\n2,\n'
    key = f'snapshots/{tenant}/{legacy_upload}/source.csv'
    meta = store._client.put_object(Bucket=settings.bucket_snapshots, Key=key, Body=raw)
    canonical_key = f'snapshots/{tenant}/{legacy_upload}/canonical.parquet'
    buffer = io.BytesIO()
    pq.write_table(pa.table({'id': ['1', '2'], 'amount': ['10', None]}), buffer, row_group_size=1)
    canonical = buffer.getvalue()
    canonical_version = store._client.put_object(Bucket=settings.bucket_snapshots, Key=canonical_key, Body=canonical)['VersionId']
    descriptor = {'bucket': settings.bucket_snapshots, 'key': key, 'version_id': meta['VersionId'],
        'size_bytes': len(raw), 'content_sha256': hashlib.sha256(raw).hexdigest(), 'format': 'CSV',
        'normalization_version': 1, 'canonical': {'bucket': settings.bucket_snapshots, 'key': canonical_key,
        'version_id': canonical_version, 'content_sha256': hashlib.sha256(canonical).hexdigest(),
        'size_bytes': len(canonical), 'format': 'PARQUET'}}
    cols = [{'index': i, 'original_name': n, 'name': n, 'type': 'STRING', 'nullable': True}
            for i, n in enumerate(['id', 'amount'])]
    db_conn.execute("INSERT INTO data_assets(asset_id,tenant_id,asset_name,slug,format,owner_user_id,created_by) VALUES(%s,%s,'Legacy synthetic',%s,'CSV',%s,%s)",
        (asset, tenant, 'legacy-' + asset.hex, test_user_id, test_user_id))
    db_conn.execute("INSERT INTO dataset_snapshots(snapshot_id,tenant_id,asset_id,version_number,source_kind,source_descriptor,content_sha256,storage_location,schema_definition,total_rows,total_columns,created_by,captured_at) VALUES(%s,%s,%s,1,'OBJECT_FILE',%s,%s,%s,%s,2,2,%s,now())",
        (snap, tenant, asset, Jsonb(descriptor), hashlib.sha256(raw).hexdigest(), f's3://{settings.bucket_snapshots}/{canonical_key}', Jsonb({'columns': cols}), test_user_id))
    db_conn.commit()
    source = {}
    if external:
        from dq_scoring.adapters.storage.source_settings import get_source_settings
        from tests.integration.api.test_snapshot_reference import _source_config
        bucket = f'dq-legacy-source-{uuid4().hex}'
        store._client.create_bucket(Bucket=bucket)
        store._client.put_bucket_versioning(Bucket=bucket, VersioningConfiguration={'Status': 'Enabled'})
        source_key = f'tenants/{tenant}/source.csv'
        store._client.put_object(Bucket=bucket, Key=source_key, Body=raw)
        config = _source_config(settings, bucket, tenant, retention=True)
        client.app.dependency_overrides[get_source_settings] = lambda: config
        monkeypatch.setattr('dq_scoring.workers.import_worker.get_source_settings', lambda: config)
        import json
        for name, value in {
            'ENABLED': 'true', 'ENDPOINT_URL': config.endpoint_url, 'BUCKET': bucket,
            'ACCESS_KEY_ID': config.access_key_id.get_secret_value(),
            'SECRET_ACCESS_KEY': config.secret_access_key.get_secret_value(),
            'TENANT_PREFIXES': json.dumps({str(tenant): [f'tenants/{tenant}/']}),
            'RETENTION_GUARANTEED': 'true',
        }.items():
            monkeypatch.setenv('DQ_SOURCE_S3_' + name, value)
        source = {'source': {'source_id': 'shared', 'bucket': bucket, 'key': source_key}}
    created = client.post('/api/v1/imports', headers=auth_headers, json={'client_request_id': str(uuid4()),
        'asset_id': str(asset), 'format': 'CSV', 'original_filename': 'synthetic.csv', 'size_bytes': len(raw), **source})
    assert created.status_code == 201, created.text
    upload = created.json()['upload_id']
    if not external:
        part = client.post(f'/api/v1/imports/{upload}/parts/1', headers={**auth_headers, 'Content-Length': str(len(raw))}, content=raw)
        assert part.status_code == 200, part.text
        assert client.post(f'/api/v1/imports/{upload}/complete', headers=auth_headers,
            json={'parts': [{'part_number': 1, 'etag': part.json()['etag']}]}).status_code == 202
    worker = ImportWorker(store)
    def process():
        with psycopg.connect(__import__('os').environ['DQ_TEST_POSTGRES_DSN']) as conn:
            session = worker.claim_next_session(conn)
            assert session is not None
            worker.process_session(conn, session)
    process()
    state = client.get(f'/api/v1/imports/{upload}', headers=auth_headers).json()
    assert state['status'] == 'VERIFIED', state
    for _ in range(4):
        configured = client.post(f'/api/v1/imports/{upload}/configure', headers=auth_headers, json={'column_names': ['id', 'amount']})
        assert configured.status_code == 200, configured.text
        process()
        state = client.get(f'/api/v1/imports/{upload}', headers=auth_headers).json()
        assert state['status'] == 'VERIFIED', state
    # Simulate a worker comparison that preceded a concurrently registered legacy snapshot.
    db_conn.execute("UPDATE dataset_upload_sessions SET manifest=manifest-'legacy_equivalence' WHERE upload_id=%s", (UUID(upload),))
    db_conn.commit()
    missing = client.post(f'/api/v1/imports/{upload}/register', headers=auth_headers, json={'acknowledged_warnings': []})
    assert missing.status_code == 409 and missing.json()['error_code'] == 'IMPORT_REVERIFY_REQUIRED'
    assert client.post(f'/api/v1/imports/{upload}/configure', headers=auth_headers, json={'column_names': ['id', 'amount']}).status_code == 200
    process()
    registered = client.post(f'/api/v1/imports/{upload}/register', headers=auth_headers, json={'acknowledged_warnings': []})
    assert registered.status_code == 200, registered.text
    assert registered.json()['snapshot_id'] == str(snap)
    assert db_conn.execute('SELECT source_descriptor FROM dataset_snapshots WHERE snapshot_id=%s', (snap,)).fetchone()[0] == descriptor
    versions = store._client.list_object_versions(Bucket=settings.bucket_snapshots, Prefix=f'snapshots/{tenant}/{upload}/').get('Versions', [])
    assert len(versions) == (0 if external else 1)
    if external:
        client.app.dependency_overrides.pop(get_source_settings, None)
        for page in store._client.get_paginator('list_object_versions').paginate(Bucket=bucket):
            for version in page.get('Versions', []):
                store._client.delete_object(Bucket=bucket, Key=version['Key'], VersionId=version['VersionId'])
        store._client.delete_bucket(Bucket=bucket)
