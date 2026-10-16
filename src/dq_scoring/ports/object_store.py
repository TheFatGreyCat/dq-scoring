"""Object store abstraction port and data structures."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import BinaryIO, Protocol


class ObjectStoreError(Exception):
    """Base exception for object store failures."""


class ObjectChangedError(ObjectStoreError):
    """Raised when an object fails precondition (ETag/version) or was modified concurrently."""


def compute_multipart_etag(part_etags: list[str]) -> str:
    """Compute deterministic S3-style multipart ETag from ordered list of part ETags.

    Returns hex format '<md5_of_concatenated_binary_md5s>-<part_count>'.
    """
    if not part_etags:
        raise ValueError("Cannot compute multipart ETag from empty part list")
    digests = bytearray()
    for etag in part_etags:
        clean = etag.strip('"')
        try:
            digests.extend(bytes.fromhex(clean))
        except ValueError as exc:
            raise ValueError(f"Part ETag '{etag}' is not a valid 32-character hex MD5") from exc
    combined_hash = hashlib.md5(digests).hexdigest()
    return f'"{combined_hash}-{len(part_etags)}"'

@dataclass(frozen=True)
class ObjectRef:
    """Unique locator for an object in storage."""

    bucket: str
    key: str
    version_id: str | None = None

    @property
    def s3a_uri(self) -> str:
        """Return Hadoop S3A URI format for Spark access."""
        return f"s3a://{self.bucket}/{self.key.lstrip('/')}"

    @property
    def s3_uri(self) -> str:
        """Return standard s3:// URI."""
        return f"s3://{self.bucket}/{self.key.lstrip('/')}"


@dataclass(frozen=True)
class ObjectMetadata:
    """Metadata for an existing object in storage."""

    ref: ObjectRef
    size_bytes: int
    etag: str
    version_id: str | None = None
    last_modified: datetime | None = None


@dataclass(frozen=True)
class UploadedPart:
    """Record of an uploaded multipart chunk."""

    part_number: int
    etag: str
    sha256: str = ""
    size_bytes: int = 0


class IObjectStorePort(Protocol):
    """Port for S3 / MinIO object storage operations."""

    def head(self, ref: ObjectRef) -> ObjectMetadata:
        """Retrieve object metadata without reading object body."""
        ...

    def open_stream(self, ref: ObjectRef) -> BinaryIO:
        """Open a readable binary stream for the object. Caller must close."""
        ...

    def list_objects(
        self,
        bucket: str,
        prefix: str = "",
        continuation_token: str | None = None,
        limit: int = 50,
    ) -> tuple[list[ObjectMetadata], str | None]:
        """List objects matching prefix, returning (items, next_continuation_token)."""
        ...

    def create_multipart(self, bucket: str, key: str) -> str:
        """Initialize multipart upload, returning multipart upload ID."""
        ...

    def upload_part(
        self,
        bucket: str,
        key: str,
        multipart_id: str,
        part_number: int,
        stream: BinaryIO,
        length: int,
    ) -> str:
        """Upload a single part and return its ETag."""
        ...

    def list_parts(self, bucket: str, key: str, multipart_id: str) -> list[UploadedPart]:
        """List completed parts for an active multipart upload."""
        ...

    def complete_multipart(
        self,
        bucket: str,
        key: str,
        multipart_id: str,
        parts: list[UploadedPart],
    ) -> ObjectMetadata:
        """Finalize multipart upload and return final object metadata."""
        ...

    def abort_multipart(self, bucket: str, key: str, multipart_id: str) -> None:
        """Abort active multipart upload and clean up parts."""
        ...

    def copy_object(
        self,
        source: ObjectRef,
        bucket: str,
        key: str,
        source_etag: str | None = None,
    ) -> ObjectMetadata:
        """Server-side copy object from source ref to target bucket and key with optional ETag match."""
        ...

    def is_versioning_enabled(self, bucket: str) -> bool:
        """Return True if bucket has object versioning enabled, False if Suspended/Off."""
        ...

    def put_file(self, bucket: str, key: str, path: Path) -> ObjectMetadata:
        """Upload local file to bucket/key and return object metadata."""
        ...
