"""Raw-only snapshots feed privacy scans and masked export without a canonical copy."""
import hashlib
import io
import json
from dataclasses import asdict
from uuid import uuid4

import pyarrow.parquet as pq
import pytest
from fastapi import HTTPException

from dq_scoring.adapters.source.tabular_normalization import inspect_schema
from dq_scoring.adapters.storage.s3_object_store import S3ObjectStoreAdapter
from dq_scoring.adapters.storage.s3_settings import get_s3_settings
from dq_scoring.common.privacy_rules import PrivacyDetectorRule, pin_rules
from dq_scoring.services.privacy_service import PrivacyService
from dq_scoring.workers.privacy_scan_worker import PrivacyScanWorker
from tests.integration.api.test_privacy_routes import (  # noqa: F401
    _seed_asset_and_snapshot,
    org,
)


def raw_snapshot(tenant):
    data = b'{"id":"1","payload":{"email":"synthetic@example.test"}}\n{"id":"2","payload":null}\n'
    settings = get_s3_settings()
    store = S3ObjectStoreAdapter(settings)
    key = f'snapshots/{tenant}/{uuid4()}/source.jsonl'
    version = store._client.put_object(Bucket=settings.bucket_snapshots, Key=key, Body=data)['VersionId']
    spec = inspect_schema(io.BytesIO(data), file_format='JSONL', column_names_mapping=None)
    doc = {'descriptor_version': 2, 'storage_mode': 'OWNED_RAW', 'bucket': settings.bucket_snapshots,
           'key': key, 'version_id': version, 'content_sha256': hashlib.sha256(data).hexdigest(), 'size_bytes': len(data),
           'format': 'JSONL', 'normalization_version': spec.version, 'normalization': json.loads(json.dumps(asdict(spec)))}
    return store, settings, doc, list(spec.columns)


def test_raw_jsonl_privacy_scan_decodes_nested_fields(org):  # noqa: F811
    store, settings, doc, columns = raw_snapshot(org['tenant_id'])
    rule = PrivacyDetectorRule(rule_id=uuid4(), revision=1, code='EMAIL', kind='BUILTIN',
        category='BASIC_PERSONAL_DATA', enabled=True, builtin_code='EMAIL')
    worker = PrivacyScanWorker(store, s3_settings=settings)
    job = {'tenant_id': org['tenant_id'], 'pinned_rules': pin_rules([rule], 0).to_json(), 'config_version': 0}
    result = worker._scan(job, doc, {'columns': columns})
    assert result['total_rows'] == 2
    assert [(f['column_name'], f['path'], f['matched_count']) for f in result['findings']] == [('payload', '/email', 1)]


def test_raw_jsonl_masked_export_has_only_requested_artifact(org, db_conn, tmp_path):  # noqa: F811
    store, settings, doc, columns = raw_snapshot(org['tenant_id'])
    asset, snapshot, _ = _seed_asset_and_snapshot(db_conn, org['tenant_id'], org['owner'][0],
        source_descriptor=doc, columns=columns, with_findings=False)
    db_conn.commit()
    artifact = PrivacyService.export_masked_parquet(db_conn, store, settings, org['tenant_id'], asset, snapshot, tmp_path)
    assert pq.read_table(artifact.path).to_pylist() == [
        {'id': '[REDACTED]', 'payload': '[REDACTED]'}, {'id': '[REDACTED]', 'payload': None}]
    assert [p.name for p in tmp_path.iterdir()] == ['masked.parquet']


def test_policy_change_during_raw_export_removes_output(org, db_conn, tmp_path):  # noqa: F811
    store, settings, doc, columns = raw_snapshot(org['tenant_id'])
    asset, snapshot, _ = _seed_asset_and_snapshot(db_conn, org['tenant_id'], org['owner'][0],
        source_descriptor=doc, columns=columns, with_findings=False)
    db_conn.execute('INSERT INTO asset_protection_revisions(tenant_id,asset_id,version) VALUES(%s,%s,0)',
                    (org['tenant_id'], asset))
    db_conn.commit()

    class PolicyChangingStore:
        def head(self, ref):
            return store.head(ref)

        def open_stream(self, ref, *, if_match_etag=None):
            db_conn.execute('UPDATE asset_protection_revisions SET version=version+1 WHERE tenant_id=%s AND asset_id=%s',
                            (org['tenant_id'], asset))
            db_conn.commit()
            return store.open_stream(ref, if_match_etag=if_match_etag)

    with pytest.raises(HTTPException) as exc:
        PrivacyService.export_masked_parquet(db_conn, PolicyChangingStore(), settings, org['tenant_id'], asset, snapshot, tmp_path)
    assert exc.value.status_code == 409 and exc.value.detail == 'POLICY_VERSION_CONFLICT'
    assert list(tmp_path.iterdir()) == []


def test_raw_export_checksum_failure_removes_partial_output(org, db_conn, tmp_path):  # noqa: F811
    store, settings, doc, columns = raw_snapshot(org['tenant_id'])
    doc['content_sha256'] = '0' * 64
    asset, snapshot, _ = _seed_asset_and_snapshot(db_conn, org['tenant_id'], org['owner'][0],
        source_descriptor=doc, columns=columns, with_findings=False)
    db_conn.commit()
    with pytest.raises(HTTPException) as exc:
        PrivacyService.export_masked_parquet(db_conn, store, settings, org['tenant_id'], asset, snapshot, tmp_path)
    assert exc.value.detail == 'OBJECT_CHANGED'
    assert list(tmp_path.iterdir()) == []


def test_external_reference_scan_and_export_preserve_nested_masking(org, db_conn, tmp_path, monkeypatch):  # noqa: F811
    from dq_scoring.adapters.storage.source_settings import source_binding_sha256
    from dq_scoring.ports.object_store import ObjectRef
    from tests.integration.api.test_snapshot_reference import _source_config
    tenant = org['tenant_id']
    store, settings, doc, columns = raw_snapshot(tenant)
    bucket = f'dq-privacy-source-{uuid4().hex}'
    store._client.create_bucket(Bucket=bucket)
    store._client.put_bucket_versioning(Bucket=bucket, VersioningConfiguration={'Status': 'Enabled'})
    with store.open_stream(ObjectRef(doc['bucket'], doc['key'], doc['version_id'])) as raw:
        data = raw.read()
    key = f'tenants/{tenant}/nested.jsonl'
    version = store._client.put_object(Bucket=bucket, Key=key, Body=data)['VersionId']
    config = _source_config(settings, bucket, tenant, retention=True)
    monkeypatch.setattr('dq_scoring.workers.privacy_scan_worker.get_source_settings', lambda: config)
    monkeypatch.setattr('dq_scoring.services.privacy_service.get_source_settings', lambda: config)
    external = {**doc, 'storage_mode': 'EXTERNAL_VERSION', 'source_id': 'shared',
                'source_binding_sha256': source_binding_sha256(config), 'bucket': bucket, 'key': key, 'version_id': version}
    try:
        rule = PrivacyDetectorRule(rule_id=uuid4(), revision=1, code='EMAIL', kind='BUILTIN',
            category='BASIC_PERSONAL_DATA', enabled=True, builtin_code='EMAIL')
        job = {'tenant_id': tenant, 'pinned_rules': pin_rules([rule], 0).to_json(), 'config_version': 0}
        result = PrivacyScanWorker(store, s3_settings=settings)._scan(job, external, {'columns': columns})
        assert [(finding['column_name'], finding['path'], finding['matched_count']) for finding in result['findings']] == [('payload', '/email', 1)]
        asset, snapshot, _ = _seed_asset_and_snapshot(db_conn, tenant, org['owner'][0],
            source_descriptor=external, columns=columns, with_findings=False)
        db_conn.commit()
        artifact = PrivacyService.export_masked_parquet(db_conn, store, settings, tenant, asset, snapshot, tmp_path)
        assert pq.read_table(artifact.path).to_pylist() == [
            {'id': '[REDACTED]', 'payload': '[REDACTED]'}, {'id': '[REDACTED]', 'payload': None}]
        assert store._client.get_object(Bucket=bucket, Key=key, VersionId=version)['Body'].read() == data
    finally:
        store._client.delete_object(Bucket=bucket, Key=key, VersionId=version)
        store._client.delete_bucket(Bucket=bucket)
