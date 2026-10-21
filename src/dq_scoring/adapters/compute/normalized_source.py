"""Spark Python DataSource that normalizes one pinned raw snapshot object at read time.

Options and partitions carry only non-secret metadata (tenant id, descriptor, row group).
Executors rebuild storage clients from their own environment.
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID

import pyarrow.parquet as pq
from botocore.exceptions import BotoCoreError, ClientError
from pyspark.sql.datasource import DataSource, DataSourceReader, InputPartition
from pyspark.sql.types import StringType, StructField, StructType

from dq_scoring.adapters.source.tabular_normalization import (
    ImportInspectionException,
    iter_normalized_batches,
)
from dq_scoring.adapters.storage.normalized_snapshot import (
    PinnedObjectReader,
    describe_normalized_snapshot,
    resolve_snapshot_source,
    validate_descriptor,
)
from dq_scoring.adapters.storage.s3_object_store import S3ObjectStoreAdapter
from dq_scoring.adapters.storage.s3_settings import get_s3_settings
from dq_scoring.adapters.storage.snapshot_objects import (
    SnapshotObjectError,
    verify_pinned_object,
)
from dq_scoring.adapters.storage.source_settings import get_source_settings
from dq_scoring.core.exceptions import RunAbortedError

SOURCE_NAME = "dq_snapshot"
OPTION_NAME = "snapshot"
ERROR_PREFIX = "DQ_SNAPSHOT_ERROR:"
ALLOWED_CODES = frozenset({
    "RESOURCE_NOT_FOUND", "OBJECT_CHANGED", "STORAGE_UNAVAILABLE", "STORAGE_VIOLATION",
    "TENANT_ISOLATION_VIOLATION", "SNAPSHOT_REIMPORT_REQUIRED", "SNAPSHOT_VERSIONING_REQUIRED",
    "MALFORMED_IMPORT",
})
_ERROR_PATTERN = re.compile(re.escape(ERROR_PREFIX) + r"([A-Z_]{1,64})")


def snapshot_options(tenant_id: UUID, descriptor: dict[str, Any]) -> str:
    """Metadata-only JSON option from a strictly validated descriptor; never clients or credentials."""
    validated = validate_descriptor(descriptor).model_dump(mode="json", exclude_none=True)
    return json.dumps({"tenant_id": str(tenant_id), "descriptor": validated}, sort_keys=True, separators=(",", ":"))


def _code(exc: Exception) -> str:
    if isinstance(exc, SnapshotObjectError):
        return exc.code if exc.code in ALLOWED_CODES else "INTERNAL"
    if isinstance(exc, ImportInspectionException):
        return "MALFORMED_IMPORT"
    if isinstance(exc, FileNotFoundError):
        return "RESOURCE_NOT_FOUND"
    if isinstance(exc, PermissionError):
        return "STORAGE_VIOLATION"
    if isinstance(exc, (BotoCoreError, ClientError, OSError)):
        return "STORAGE_UNAVAILABLE"
    return "INTERNAL"


@contextmanager
def _fixed_errors():
    try:
        yield
    except Exception as exc:  # noqa: BLE001 - preserve task failure with only a fixed, value-free code
        raise RuntimeError(f"{ERROR_PREFIX}{_code(exc)}") from None


def snapshot_run_error(exc: BaseException) -> RunAbortedError | None:
    """Map a wrapped Spark/Python task failure to a fixed-code RunAbortedError; None if unrelated."""
    seen = 0
    current: BaseException | None = exc
    while current is not None and seen < 8:
        match = _ERROR_PATTERN.search(str(current))
        if match:
            code = match.group(1)
            if code not in ALLOWED_CODES:
                return None
            return RunAbortedError(f"{code}: Snapshot source cannot be read.")
        current = current.__cause__ or current.__context__
        seen += 1
    return None


def _environment() -> tuple[Any, Any, Any]:
    settings = get_s3_settings()
    return S3ObjectStoreAdapter(settings=settings), settings, get_source_settings()


def _parse(blob: str) -> tuple[UUID, dict[str, Any]]:
    payload = json.loads(blob)
    return UUID(payload["tenant_id"]), payload["descriptor"]


class SnapshotPartition(InputPartition):
    """One Parquet row group, or the whole object when row_group is None."""

    def __init__(self, row_group: int | None) -> None:
        super().__init__(row_group)
        self.row_group = row_group


class NormalizedSnapshotSource(DataSource):
    @classmethod
    def name(cls) -> str:
        return SOURCE_NAME

    def schema(self) -> StructType:
        with _fixed_errors():
            tenant_id, descriptor = _parse(self.options[OPTION_NAME])
            if "descriptor_version" not in descriptor:
                raise SnapshotObjectError("SNAPSHOT_REIMPORT_REQUIRED", "Legacy snapshots do not use this source.")
            store, settings, source = _environment()
            spec = describe_normalized_snapshot(tenant_id, descriptor, store, settings, source_settings=source)
            return StructType([StructField(col["name"], StringType(), True) for col in spec.columns])

    def reader(self, schema: StructType) -> NormalizedSnapshotReader:
        return NormalizedSnapshotReader(self.options[OPTION_NAME])


class NormalizedSnapshotReader(DataSourceReader):
    def __init__(self, blob: str) -> None:
        self.blob = blob

    def _resolve(self):
        tenant_id, descriptor = _parse(self.blob)
        store, settings, source = _environment()
        resolved_store, ref, spec = resolve_snapshot_source(tenant_id, descriptor, store, settings, source)
        if spec is None:
            raise SnapshotObjectError("SNAPSHOT_REIMPORT_REQUIRED", "Legacy snapshots do not use this source.")
        return resolved_store, ref, spec, descriptor

    def partitions(self) -> list[SnapshotPartition]:
        with _fixed_errors():
            store, ref, spec, descriptor = self._resolve()
            if spec.format != "PARQUET":
                return [SnapshotPartition(None)]
            verify_pinned_object(store, ref, descriptor, full=False)
            with PinnedObjectReader(store, ref, descriptor["size_bytes"]) as raw:
                meta = pq.ParquetFile(raw).metadata
                groups = [i for i in range(meta.num_row_groups) if meta.row_group(i).num_rows > 0]
            verify_pinned_object(store, ref, descriptor, full=False)
            return [SnapshotPartition(i) for i in groups] or [SnapshotPartition(None)]

    def read(self, partition: SnapshotPartition) -> Iterator[Any]:
        with _fixed_errors():
            store, ref, spec, descriptor = self._resolve()
            verify_pinned_object(store, ref, descriptor, full=False)
            groups = None if partition.row_group is None else (partition.row_group,)
            raw = PinnedObjectReader(store, ref, descriptor["size_bytes"]) if spec.format == "PARQUET" else store.open_stream(ref)
            with raw:
                batches = iter_normalized_batches(raw, spec, row_groups=groups)
                try:
                    yield from batches
                finally:
                    batches.close()
            verify_pinned_object(store, ref, descriptor, full=False)
