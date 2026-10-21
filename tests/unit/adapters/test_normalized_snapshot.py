"""Pinned reads never substitute a newer object version."""
import hashlib
import io
from uuid import uuid4

import pytest
from pydantic import SecretStr, ValidationError

from dq_scoring.adapters.source.tabular_normalization import inspect_schema
from dq_scoring.adapters.storage.normalized_snapshot import (
    PinnedObjectReader,
    resolve_snapshot_source,
)
from dq_scoring.adapters.storage.s3_settings import S3Settings
from dq_scoring.adapters.storage.snapshot_objects import (
    SnapshotObjectError,
    verify_pinned_object,
)
from dq_scoring.adapters.storage.source_settings import (
    SourceStoreSettings,
    source_binding_sha256,
)
from dq_scoring.ports.object_store import ObjectMetadata, ObjectRef


class VersionedStore:
    def __init__(self, data):
        self.data = data
        self.requests = []

    def head(self, ref):
        data = self.data[ref.version_id]
        return ObjectMetadata(ref, len(data), 'etag', ref.version_id)

    def open_stream(self, ref, *, if_match_etag=None):
        return io.BytesIO(self.data[ref.version_id])

    def open_range(self, ref, offset, length):
        self.requests.append((ref.version_id, offset, length))
        return io.BytesIO(self.data[ref.version_id][offset:offset + length])


def settings():
    return S3Settings(_env_file=None, endpoint_url='http://owned:9000', access_key_id=SecretStr('synthetic'),
                      secret_access_key=SecretStr('synthetic-secret'), bucket_snapshots='snapshots')


def descriptor(tenant, data=b'a\n1\n'):
    from dataclasses import asdict
    spec = inspect_schema(io.BytesIO(data), file_format='CSV', column_names_mapping=None)
    return {'descriptor_version': 2, 'storage_mode': 'OWNED_RAW', 'bucket': 'snapshots',
            'key': f'snapshots/{tenant}/upload/source.csv', 'version_id': 'A',
            'content_sha256': hashlib.sha256(data).hexdigest(), 'size_bytes': len(data),
            'format': 'CSV', 'normalization_version': 1, 'normalization': {**asdict(spec), 'columns': list(spec.columns)}}


def test_seek_reader_reads_only_pinned_version_and_bounded_windows():
    data = bytes(range(256)) * 20000
    store = VersionedStore({'A': data, 'B': b'new latest'})
    with PinnedObjectReader(store, ObjectRef('b', 'k', 'A'), len(data)) as reader:
        reader.seek(-32, io.SEEK_END)
        assert reader.read(32) == data[-32:]
        reader.seek(17)
        assert reader.read(3) == data[17:20]
        assert reader.tell() == 20
        target = bytearray(4)
        assert reader.readinto(target) == 4
        assert target == data[20:24]
    assert all(version == 'A' and length <= 1024 * 1024 for version, _, length in store.requests)


def test_exact_verification_does_not_require_latest_equal_pinned():
    tenant = uuid4()
    doc = descriptor(tenant)
    store = VersionedStore({'A': b'a\n1\n', None: b'changed'})
    verify_pinned_object(store, ObjectRef('snapshots', doc['key'], 'A'), doc, full=True)
    doc['content_sha256'] = '0' * 64
    with pytest.raises(SnapshotObjectError) as exc:
        verify_pinned_object(store, ObjectRef('snapshots', doc['key'], 'A'), doc, full=True)
    assert exc.value.code == 'OBJECT_CHANGED'


@pytest.mark.parametrize('mutation', [
    {'endpoint': 'http://untrusted'}, {'canonical': {}}, {'normalization_version': 99},
    {'descriptor_version': 3}, {'content_sha256': 'etag'},
])
def test_descriptor_rejects_unknown_fields_and_inconsistent_codec(mutation):
    tenant = uuid4()
    doc = {**descriptor(tenant), **mutation}
    with pytest.raises(SnapshotObjectError):
        resolve_snapshot_source(tenant, doc, VersionedStore({'A': b'a\n1\n'}), settings())


def test_source_settings_disabled_and_tenant_overlap_rejection():
    assert not SourceStoreSettings().enabled
    a, b = uuid4(), uuid4()
    with pytest.raises(ValidationError):
        SourceStoreSettings(enabled=True, endpoint_url='https://source:9000', bucket='shared',
                            access_key_id='synthetic', secret_access_key='synthetic-secret',
                            tenant_prefixes={a: ['data/'], b: ['data/other/']})


def test_source_binding_normalizes_endpoint_without_credentials():
    a = SourceStoreSettings(endpoint_url='https://SOURCE.example/', bucket='shared')
    b = SourceStoreSettings(endpoint_url='https://source.example:443', bucket='shared')
    assert source_binding_sha256(a) == source_binding_sha256(b)


def test_external_binding_and_tenant_fail_before_storage_access():
    tenant = uuid4()
    source = SourceStoreSettings(enabled=True, endpoint_url='http://external:9000', bucket='shared',
        access_key_id='synthetic', secret_access_key='synthetic-secret', tenant_prefixes={tenant: ['safe/']})
    doc = {**descriptor(tenant), 'storage_mode': 'EXTERNAL_VERSION', 'bucket': 'shared',
           'key': 'other/source.csv', 'source_id': 'shared', 'source_binding_sha256': source_binding_sha256(source)}
    with pytest.raises(SnapshotObjectError) as exc:
        resolve_snapshot_source(tenant, doc, VersionedStore({}), settings(), source)
    assert exc.value.code == 'TENANT_ISOLATION_VIOLATION'
    doc['key'] = 'safe/source.csv'
    doc['source_binding_sha256'] = '0' * 64
    with pytest.raises(SnapshotObjectError) as exc:
        resolve_snapshot_source(tenant, doc, VersionedStore({}), settings(), source)
    assert exc.value.code == 'STORAGE_VIOLATION'


def test_source_settings_loads_documented_environment(monkeypatch):
    import json
    tenant = uuid4()
    values = {'ENABLED': 'true', 'ENDPOINT_URL': 'http://source:9000', 'ACCESS_KEY_ID': 'synthetic',
              'SECRET_ACCESS_KEY': 'synthetic-secret', 'REGION': 'us-east-1', 'USE_SSL': 'false',
              'BUCKET': 'shared', 'TENANT_PREFIXES': json.dumps({str(tenant): ['tenant/']}),
              'RETENTION_GUARANTEED': 'true', 'EXECUTOR_SECRET': 'source-reader',
              'ACCESS_KEY_ID_KEY': 'reader-key', 'SECRET_ACCESS_KEY_KEY': 'reader-secret',
              'CA_BUNDLE': '/synthetic/source-ca.pem'}
    for key, value in values.items():
        monkeypatch.setenv('DQ_SOURCE_S3_' + key, value)
    source = SourceStoreSettings()
    assert source.enabled and source.retention_guaranteed
    assert source.tenant_prefixes == {tenant: ['tenant/']}
    assert source.executor_secret == 'source-reader'
    assert source.ca_bundle == '/synthetic/source-ca.pem'


def test_normalized_owned_csv_reads_pinned_not_latest():
    from dq_scoring.adapters.storage.normalized_snapshot import open_normalized_snapshot
    tenant = uuid4()
    doc = descriptor(tenant)
    # Descriptor wire format is JSON, including columns as an array.
    import json
    doc = json.loads(json.dumps(doc))
    store = VersionedStore({'A': b'a\n1\n', None: b'a\nwrong latest\n'})
    with open_normalized_snapshot(tenant, doc, store, settings()) as batches:
        assert [row for batch in batches for row in batch.to_pylist()] == [{'a': '1'}]


@pytest.mark.parametrize('column_change', [
    {'index': 0.0}, {'index': True}, {'unknown_codec': 'XML'}, {'logical_types': 'ARRAY'},
    {'logical_types': [1]}, {'type': ''},
])
def test_descriptor_rejects_invalid_column_contract(column_change):
    from dq_scoring.adapters.storage.normalized_snapshot import validate_descriptor
    tenant = uuid4()
    doc = descriptor(tenant)
    doc['normalization']['columns'][0].update(column_change)
    with pytest.raises(SnapshotObjectError):
        validate_descriptor(doc)


def test_protected_source_requires_own_ca_even_when_owned_ca_exists(monkeypatch, tmp_path):
    owned_ca = tmp_path / 'owned.pem'
    owned_ca.write_text('synthetic certificate placeholder')
    monkeypatch.setenv('DQ_PROTECTED_PROCESSING_ENABLED', 'true')
    monkeypatch.setenv('DQ_S3_CA_BUNDLE', str(owned_ca))
    monkeypatch.delenv('DQ_SOURCE_S3_CA_BUNDLE', raising=False)
    with pytest.raises(ValidationError):
        SourceStoreSettings(enabled=True, endpoint_url='https://source:9000', bucket='shared',
            use_ssl=True, access_key_id='synthetic', secret_access_key='synthetic-secret',
            tenant_prefixes={uuid4(): ['tenant/']})


def test_source_disappears_between_head_and_stream_is_not_malformed():
    from dq_scoring.adapters.storage.normalized_snapshot import open_normalized_snapshot
    tenant = uuid4()

    class DisappearingStore(VersionedStore):
        def open_stream(self, ref, *, if_match_etag=None):
            raise FileNotFoundError('synthetic missing version')

    with (
        pytest.raises(SnapshotObjectError) as exc,
        open_normalized_snapshot(tenant, descriptor(tenant), DisappearingStore({'A': b'a\n1\n'}), settings()) as batches,
    ):
        list(batches)
    assert exc.value.code == 'RESOURCE_NOT_FOUND'
