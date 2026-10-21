"""Strict snapshot descriptors and bounded historical-object readers."""
from __future__ import annotations

import io
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Literal, Self
from uuid import UUID

import pyarrow.parquet as pq
from botocore.exceptions import BotoCoreError, ClientError
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from dq_scoring.adapters.source.tabular_normalization import (
    NormalizationSpec,
    iter_normalized_batches,
)
from dq_scoring.adapters.storage.s3_object_store import S3ObjectStoreAdapter
from dq_scoring.adapters.storage.s3_settings import S3Settings
from dq_scoring.adapters.storage.snapshot_objects import (
    SnapshotObjectError,
    canonical_descriptor,
    pinned_ref,
    spool_canonical,
    verify_pinned_object,
)
from dq_scoring.adapters.storage.source_settings import (
    SourceStoreSettings,
    source_binding_sha256,
)
from dq_scoring.ports.object_store import (
    IObjectStorePort,
    ObjectChangedError,
    ObjectRef,
)


class NormalizationDocument(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    version: Literal[1, 2]
    format: Literal['CSV', 'JSONL', 'PARQUET']
    delimiter: Literal[',', ';', '\t', '|'] = ','
    encoding: Literal['utf-8-sig'] = 'utf-8-sig'
    columns: list[dict[str, Any]] = Field(min_length=1, max_length=1000)

    @model_validator(mode='after')
    def validate_columns(self) -> Self:
        names = set()
        for i, col in enumerate(self.columns):
            name = col.get('name')
            if col.get('index') != i or not isinstance(col.get('original_name'), str) or not isinstance(name, str) or not name or name in names or not isinstance(col.get('type'), str) or not isinstance(col.get('nullable'), bool):
                raise ValueError('Invalid normalization columns')
            allowed = {'index', 'original_name', 'name', 'type', 'nullable', 'structural_encoding', 'logical_types'}
            if not col['type'] or type(col['index']) is not int or set(col) - allowed:
                raise ValueError('Invalid normalization columns')
            if 'logical_types' in col and (not isinstance(col['logical_types'], list) or any(not isinstance(v, str) for v in col['logical_types'])):
                raise ValueError('Invalid normalization logical types')
            if col.get('structural_encoding') not in (None, 'JSON'):
                raise ValueError('Unsupported structural encoding')
            if col.get('structural_encoding') == 'JSON' and self.version != 2:
                raise ValueError('Container encoding requires normalization v2')
            names.add(name)
        return self

    def spec(self) -> NormalizationSpec:
        return NormalizationSpec(self.version, self.format, tuple(self.columns), self.delimiter, self.encoding)


class SnapshotDescriptorV2(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    descriptor_version: Literal[2]
    storage_mode: Literal['OWNED_RAW', 'EXTERNAL_VERSION']
    bucket: str = Field(min_length=1)
    key: str = Field(min_length=1)
    version_id: str = Field(min_length=1)
    content_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    size_bytes: int = Field(gt=0)
    format: Literal['CSV', 'JSONL', 'PARQUET']
    normalization_version: Literal[1, 2]
    normalization: NormalizationDocument
    source_id: Literal['shared'] | None = None
    source_binding_sha256: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')

    @model_validator(mode='after')
    def validate_identity(self) -> Self:
        if self.version_id == 'null' or self.format != self.normalization.format or self.normalization_version != self.normalization.version:
            raise ValueError('Invalid pinned normalization identity')
        if self.storage_mode == 'EXTERNAL_VERSION':
            if self.source_id != 'shared' or not self.source_binding_sha256:
                raise ValueError('External source binding is required')
        elif self.source_id is not None or self.source_binding_sha256 is not None:
            raise ValueError('Owned source cannot contain an external binding')
        return self


def validate_descriptor(descriptor: dict[str, Any]) -> SnapshotDescriptorV2:
    try:
        return SnapshotDescriptorV2.model_validate(descriptor)
    except (ValidationError, TypeError, ValueError) as exc:
        raise SnapshotObjectError('SNAPSHOT_REIMPORT_REQUIRED', 'Unsupported snapshot descriptor.') from exc


def resolve_snapshot_source(tenant_id: UUID, source_descriptor: dict, owned_store: IObjectStorePort,
                            owned_settings: S3Settings, source_settings: SourceStoreSettings | None = None
                            ) -> tuple[IObjectStorePort, ObjectRef, NormalizationSpec | None]:
    if 'descriptor_version' not in source_descriptor:
        doc = canonical_descriptor(source_descriptor)
        return owned_store, pinned_ref(tenant_id, doc, owned_settings.bucket_snapshots), None
    doc = validate_descriptor(source_descriptor)
    if doc.storage_mode == 'OWNED_RAW':
        return owned_store, pinned_ref(tenant_id, source_descriptor, owned_settings.bucket_snapshots), doc.normalization.spec()
    source = source_settings or SourceStoreSettings()
    if not source.enabled or source.bucket != doc.bucket:
        raise SnapshotObjectError('STORAGE_VIOLATION', 'Source is not configured.')
    try:
        source.validate_owned_separation(owned_settings)
    except ValueError as exc:
        raise SnapshotObjectError('STORAGE_VIOLATION', 'Source ownership overlaps.') from exc
    if source_binding_sha256(source) != doc.source_binding_sha256:
        raise SnapshotObjectError('STORAGE_VIOLATION', 'Source binding changed.')
    if not any(doc.key.startswith(prefix) for prefix in source.tenant_prefixes.get(tenant_id, [])):
        raise SnapshotObjectError('TENANT_ISOLATION_VIOLATION', 'Source is outside tenant scope.')
    if '\\' in doc.key or any(ord(c) < 32 or ord(c) == 127 for c in doc.key) or any(p in ('', '.', '..') for p in doc.key.split('/')):
        raise SnapshotObjectError('STORAGE_VIOLATION', 'Invalid source key.')
    store = S3ObjectStoreAdapter(source.as_s3_settings())
    return store, ObjectRef(doc.bucket, doc.key, doc.version_id), doc.normalization.spec()


class PinnedObjectReader(io.RawIOBase):
    """Seekable exact-version S3 reader with one bounded cache window."""
    WINDOW = 1024 * 1024

    def __init__(self, store: IObjectStorePort, ref: ObjectRef, size_bytes: int):
        super().__init__()
        if not ref.version_id or ref.version_id == 'null' or size_bytes < 0:
            raise ValueError('A pinned version and nonnegative size are required')
        self.store, self.ref, self.size = store, ref, size_bytes
        self.position = 0
        self.cache_start = 0
        self.cache = b''

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        self._checkClosed()
        return self.position

    def seek(self, offset, whence=io.SEEK_SET):
        self._checkClosed()
        if whence not in (io.SEEK_SET, io.SEEK_CUR, io.SEEK_END):
            raise ValueError('Invalid whence')
        pos = offset + (self.position if whence == io.SEEK_CUR else self.size if whence == io.SEEK_END else 0)
        if pos < 0:
            raise ValueError('Negative seek')
        self.position = pos
        return pos

    def read(self, size=-1):
        self._checkClosed()
        remaining = max(0, self.size - self.position)
        size = remaining if size is None or size < 0 else min(size, remaining)
        result = bytearray()
        while size:
            if not self.cache_start <= self.position < self.cache_start + len(self.cache):
                self.cache_start = self.position
                length = min(self.WINDOW, self.size - self.position)
                try:
                    with self.store.open_range(self.ref, self.position, length) as body:
                        self.cache = body.read(length)
                except FileNotFoundError as exc:
                    raise SnapshotObjectError('RESOURCE_NOT_FOUND', 'Pinned object version is missing.') from exc
                except ObjectChangedError as exc:
                    raise SnapshotObjectError('OBJECT_CHANGED', 'Pinned range changed.') from exc
                except (BotoCoreError, ClientError, OSError) as exc:
                    raise SnapshotObjectError('STORAGE_UNAVAILABLE', 'Pinned range is unavailable.') from exc
                if len(self.cache) != length:
                    raise SnapshotObjectError('OBJECT_CHANGED', 'Truncated pinned range.')
            offset = self.position - self.cache_start
            count = min(size, len(self.cache) - offset)
            result.extend(self.cache[offset:offset + count])
            self.position += count
            size -= count
        return bytes(result)

    def readinto(self, buffer):
        data = self.read(len(buffer))
        buffer[:len(data)] = data
        return len(data)

    def close(self):
        self.cache = b''
        super().close()


@contextmanager
def open_normalized_snapshot(tenant_id: UUID, source_descriptor: dict, owned_store: IObjectStorePort,
                             owned_settings: S3Settings, *, source_settings: SourceStoreSettings | None = None):
    store, ref, spec = resolve_snapshot_source(tenant_id, source_descriptor, owned_store, owned_settings, source_settings)
    if spec is None:
        with TemporaryDirectory(prefix='dq-legacy-') as temp:
            path = Path(temp) / 'canonical.parquet'
            spool_canonical(store, tenant_id, source_descriptor, owned_settings.bucket_snapshots, path)
            with pq.ParquetFile(path) as parquet:
                yield parquet.iter_batches(batch_size=8192)
        return
    verify_pinned_object(store, ref, source_descriptor, full=False)
    try:
        raw = PinnedObjectReader(store, ref, source_descriptor['size_bytes']) if spec.format == 'PARQUET' else store.open_stream(ref)
        with raw:
            batches = iter_normalized_batches(raw, spec)
            try:
                yield batches
            finally:
                batches.close()
        verify_pinned_object(store, ref, source_descriptor, full=False)
    except FileNotFoundError as exc:
        raise SnapshotObjectError('RESOURCE_NOT_FOUND', 'Pinned source version is missing.') from exc
    except ObjectChangedError as exc:
        raise SnapshotObjectError('OBJECT_CHANGED', 'Pinned source changed.') from exc
    except (BotoCoreError, ClientError, OSError) as exc:
        raise SnapshotObjectError('STORAGE_UNAVAILABLE', 'Pinned source is unavailable.') from exc


def describe_normalized_snapshot(tenant_id: UUID, source_descriptor: dict, owned_store: IObjectStorePort,
                                 owned_settings: S3Settings, *, source_settings: SourceStoreSettings | None = None) -> NormalizationSpec:
    _, _, spec = resolve_snapshot_source(tenant_id, source_descriptor, owned_store, owned_settings, source_settings)
    if spec is not None:
        return spec
    with TemporaryDirectory(prefix='dq-legacy-schema-') as temp:
        path = Path(temp) / 'canonical.parquet'
        spool_canonical(owned_store, tenant_id, source_descriptor, owned_settings.bucket_snapshots, path)
        with pq.ParquetFile(path) as parquet:
            schema = parquet.schema_arrow
    columns = tuple({'index': i, 'original_name': n, 'name': n, 'type': 'STRING', 'nullable': True} for i, n in enumerate(schema.names))
    return NormalizationSpec(source_descriptor.get('normalization_version', 1), 'PARQUET', columns)


def legacy_equivalence_witness(conn, tenant_id: UUID, asset_id: UUID | None, descriptor: dict,
                               store: IObjectStorePort, settings: S3Settings) -> dict | None:
    """Compare immutable legacy values outside the asset registration lock."""
    import time

    from dq_scoring.common.hash_utils import compute_deterministic_hash
    if asset_id is None:
        return None
    existing = conn.execute(
        "SELECT snapshot_id,source_descriptor FROM dataset_snapshots WHERE tenant_id=%s AND asset_id=%s "
        "AND content_sha256=%s AND source_kind='OBJECT_FILE'",
        (tenant_id, asset_id, descriptor['content_sha256']),
    ).fetchone()
    if existing is None or existing[1].get('descriptor_version') == 2:
        return None
    current_store, current_ref, _ = resolve_snapshot_source(tenant_id, descriptor, store, settings, SourceStoreSettings())
    verify_pinned_object(current_store, current_ref, descriptor, full=True)
    deadline = time.monotonic() + 300

    def rows(batches):
        for batch in batches:
            if time.monotonic() > deadline:
                raise SnapshotObjectError('STORAGE_UNAVAILABLE', 'Legacy comparison deadline exceeded.')
            if any(str(field.type) != 'string' for field in batch.schema):
                raise SnapshotObjectError('SNAPSHOT_REIMPORT_REQUIRED', 'Legacy normalized schema is not string.')
            yield from (tuple(row.items()) for row in batch.to_pylist())

    equal = True
    from itertools import zip_longest
    sentinel = object()
    with (
        open_normalized_snapshot(tenant_id, descriptor, store, settings, source_settings=SourceStoreSettings()) as current,
        open_normalized_snapshot(tenant_id, existing[1], store, settings) as legacy,
    ):
        for left, right in zip_longest(rows(current), rows(legacy), fillvalue=sentinel):
            if left != right:
                equal = False
                break
    return {'snapshot_id': str(existing[0]), 'descriptor_sha256': compute_deterministic_hash(existing[1]),
            'normalization_sha256': compute_deterministic_hash(descriptor['normalization']), 'equal': equal}
