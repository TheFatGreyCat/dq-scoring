"""Pinned snapshot object validation shared by Spark, masked export, and privacy scans."""
from __future__ import annotations

import hashlib
import os
import re
import shutil
from pathlib import Path
from typing import Any
from uuid import UUID

from botocore.exceptions import BotoCoreError, ClientError

from dq_scoring.ports.object_store import IObjectStorePort, ObjectRef

CHUNK_BYTES = 1024 * 1024


class SnapshotObjectError(Exception):
    """Integrity or storage failure with a stable, value-free error code."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code


def canonical_descriptor(source_descriptor: dict[str, Any] | None) -> dict[str, Any]:
    canonical = (source_descriptor or {}).get("canonical")
    if not isinstance(canonical, dict) or canonical.get("format") != "PARQUET":
        raise SnapshotObjectError("SNAPSHOT_REIMPORT_REQUIRED", "Canonical Parquet descriptor is missing.")
    return canonical


def pinned_ref(tenant_id: UUID, descriptor: dict[str, Any], snapshot_bucket: str) -> ObjectRef:
    bucket, key = descriptor.get("bucket"), descriptor.get("key")
    if bucket != snapshot_bucket:
        raise SnapshotObjectError("STORAGE_VIOLATION", "Snapshot bucket is not configured.")
    if not isinstance(key, str) or not key.startswith(f"snapshots/{tenant_id}/"):
        raise SnapshotObjectError("TENANT_ISOLATION_VIOLATION", "Snapshot is outside the tenant scope.")
    if any(part in ("", ".", "..") for part in key.split("/")) or "\\" in key or any(ord(c) < 32 for c in key):
        raise SnapshotObjectError("STORAGE_VIOLATION", "Invalid snapshot object key.")
    version, digest, size = descriptor.get("version_id"), descriptor.get("content_sha256"), descriptor.get("size_bytes")
    if not isinstance(version, str) or not version or version == "null":
        raise SnapshotObjectError("SNAPSHOT_VERSIONING_REQUIRED", "Snapshot has no pinned version.")
    if not isinstance(digest, str) or re.fullmatch(r"[a-f0-9]{64}", digest) is None or not isinstance(size, int) or size <= 0:
        raise SnapshotObjectError("MALFORMED_IMPORT", "Invalid snapshot integrity metadata.")
    return ObjectRef(bucket=bucket, key=key, version_id=version)


def _check_current(store: IObjectStorePort, ref: ObjectRef, size: int) -> None:
    current = store.head(ObjectRef(bucket=ref.bucket, key=ref.key))
    if current.version_id != ref.version_id or current.size_bytes != size:
        raise SnapshotObjectError("OBJECT_CHANGED", "Snapshot object changed after registration.")


def verify_object(store: IObjectStorePort, ref: ObjectRef, descriptor: dict[str, Any], full: bool, spool: Path | None = None) -> None:
    """Verify pinned version/size (and full SHA-256 when `full`); optionally spool verified bytes to `spool`."""
    try:
        _check_current(store, ref, descriptor["size_bytes"])
        if not full:
            return
        digest, size = hashlib.sha256(), 0
        with store.open_stream(ref) as stream, (spool or Path(os.devnull)).open("wb") as out:
            for chunk in iter(lambda: stream.read(CHUNK_BYTES), b""):
                digest.update(chunk)
                size += len(chunk)
                out.write(chunk)
        if digest.hexdigest() != descriptor["content_sha256"] or size != descriptor["size_bytes"]:
            raise SnapshotObjectError("OBJECT_CHANGED", "Snapshot checksum mismatch.")
        _check_current(store, ref, size)
    except FileNotFoundError as exc:
        raise SnapshotObjectError("RESOURCE_NOT_FOUND", "Snapshot object is missing.") from exc
    except (BotoCoreError, ClientError, OSError) as exc:
        raise SnapshotObjectError("STORAGE_UNAVAILABLE", "Snapshot storage cannot be verified.") from exc


def spool_canonical(store: IObjectStorePort, tenant_id: UUID, source_descriptor: dict[str, Any], snapshot_bucket: str, dest: Path) -> None:
    """Spool the pinned canonical Parquet to `dest` after full integrity verification; removes `dest` on failure."""
    descriptor = canonical_descriptor(source_descriptor)
    ref = pinned_ref(tenant_id, descriptor, snapshot_bucket)
    try:
        if shutil.disk_usage(dest.parent).free < descriptor["size_bytes"]:
            raise SnapshotObjectError("STORAGE_UNAVAILABLE", "Scratch storage is insufficient.")
        verify_object(store, ref, descriptor, full=True, spool=dest)
    except BaseException:
        dest.unlink(missing_ok=True)
        raise
