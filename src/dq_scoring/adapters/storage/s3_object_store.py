"""S3 / MinIO object store adapter implementing IObjectStorePort."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, BinaryIO

import boto3
from boto3.s3.transfer import TransferConfig
from botocore.client import Config
from botocore.exceptions import ClientError

from dq_scoring.adapters.storage.s3_settings import S3Settings, get_s3_settings
from dq_scoring.ports.object_store import (
    IObjectStorePort,
    ObjectChangedError,
    ObjectMetadata,
    ObjectRef,
    UploadedPart,
)


class S3ObjectStoreAdapter(IObjectStorePort):
    """Adapter for S3-compatible object stores (MinIO/AWS S3)."""

    def __init__(self, settings: S3Settings | None = None, s3_client: Any | None = None) -> None:
        self._settings = settings or get_s3_settings()
        if s3_client is not None:
            self._client = s3_client
        else:
            client_kwargs: dict[str, Any] = {
                "service_name": "s3",
                "endpoint_url": self._settings.endpoint_url,
                "aws_access_key_id": self._settings.access_key_id.get_secret_value(),
                "aws_secret_access_key": self._settings.secret_access_key.get_secret_value(),
                "region_name": self._settings.region,
                "use_ssl": self._settings.use_ssl,
                "config": Config(
                    signature_version="s3v4",
                    s3={"addressing_style": "path"},
                ),
            }
            if self._settings.ca_bundle:
                client_kwargs["verify"] = self._settings.ca_bundle
            self._client = boto3.client(**client_kwargs)
        self._transfer_config = TransferConfig(
            multipart_threshold=16 * 1024 * 1024,
            multipart_chunksize=16 * 1024 * 1024,
            max_concurrency=4,
            use_threads=True,
        )

    @staticmethod
    def _clean_etag(etag: str | None) -> str:
        if not etag:
            return ""
        return etag.strip('"')

    def head(self, ref: ObjectRef) -> ObjectMetadata:
        try:
            extra_args: dict[str, Any] = {}
            if ref.version_id:
                extra_args["VersionId"] = ref.version_id
            resp = self._client.head_object(Bucket=ref.bucket, Key=ref.key, **extra_args)
            return ObjectMetadata(
                ref=ref,
                size_bytes=int(resp.get("ContentLength", 0)),
                etag=self._clean_etag(resp.get("ETag")),
                version_id=resp.get("VersionId"),
                last_modified=resp.get("LastModified"),
            )
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in ("404", "NoSuchKey"):
                raise FileNotFoundError(f"Object s3://{ref.bucket}/{ref.key} not found") from exc
            if code in ("403", "AccessDenied"):
                raise PermissionError(f"Access denied to s3://{ref.bucket}/{ref.key}") from exc
            raise

    def open_stream(self, ref: ObjectRef) -> BinaryIO:
        try:
            extra_args: dict[str, Any] = {}
            if ref.version_id:
                extra_args["VersionId"] = ref.version_id
            resp = self._client.get_object(Bucket=ref.bucket, Key=ref.key, **extra_args)
            return resp["Body"]
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in ("404", "NoSuchKey"):
                raise FileNotFoundError(f"Object s3://{ref.bucket}/{ref.key} not found") from exc
            if code in ("403", "AccessDenied"):
                raise PermissionError(f"Access denied to s3://{ref.bucket}/{ref.key}") from exc
            raise

    def list_objects(
        self,
        bucket: str,
        prefix: str = "",
        continuation_token: str | None = None,
        limit: int = 50,
    ) -> tuple[list[ObjectMetadata], str | None]:
        params: dict[str, Any] = {
            "Bucket": bucket,
            "Prefix": prefix,
            "MaxKeys": min(max(1, limit), 1000),
        }
        if continuation_token:
            params["ContinuationToken"] = continuation_token

        try:
            resp = self._client.list_objects_v2(**params)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in ("404", "NoSuchBucket"):
                raise FileNotFoundError(f"Bucket {bucket} not found") from exc
            if code in ("403", "AccessDenied"):
                raise PermissionError(f"Access denied to bucket {bucket}") from exc
            raise

        items: list[ObjectMetadata] = []
        for obj in resp.get("Contents", []):
            key = obj["Key"]
            ref = ObjectRef(bucket=bucket, key=key)
            last_mod: datetime | None = obj.get("LastModified")
            items.append(
                ObjectMetadata(
                    ref=ref,
                    size_bytes=int(obj.get("Size", 0)),
                    etag=self._clean_etag(obj.get("ETag")),
                    last_modified=last_mod,
                )
            )

        next_token = resp.get("NextContinuationToken")
        return items, next_token

    def create_multipart(self, bucket: str, key: str) -> str:
        try:
            resp = self._client.create_multipart_upload(Bucket=bucket, Key=key)
            return str(resp["UploadId"])
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in ("403", "AccessDenied"):
                raise PermissionError(f"Access denied to create multipart on s3://{bucket}/{key}") from exc
            raise

    def upload_part(
        self,
        bucket: str,
        key: str,
        multipart_id: str,
        part_number: int,
        stream: BinaryIO,
        length: int,
    ) -> str:
        try:
            resp = self._client.upload_part(
                Bucket=bucket,
                Key=key,
                UploadId=multipart_id,
                PartNumber=part_number,
                Body=stream,
                ContentLength=length,
            )
            return self._clean_etag(resp.get("ETag"))
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in ("404", "NoSuchUpload"):
                raise FileNotFoundError(f"Multipart upload {multipart_id} not found") from exc
            raise

    def list_parts(self, bucket: str, key: str, multipart_id: str) -> list[UploadedPart]:
        try:
            parts: list[UploadedPart] = []
            part_marker = 0
            while True:
                resp = self._client.list_parts(
                    Bucket=bucket,
                    Key=key,
                    UploadId=multipart_id,
                    PartNumberMarker=part_marker,
                )
                for p in resp.get("Parts", []):
                    parts.append(
                        UploadedPart(
                            part_number=int(p["PartNumber"]),
                            etag=self._clean_etag(p.get("ETag")),
                            size_bytes=int(p.get("Size", 0)),
                        )
                    )
                if resp.get("IsTruncated"):
                    part_marker = resp.get("NextPartNumberMarker", 0)
                else:
                    break
            return sorted(parts, key=lambda x: x.part_number)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in ("404", "NoSuchUpload"):
                raise FileNotFoundError(f"Multipart upload {multipart_id} not found") from exc
            raise

    def complete_multipart(
        self,
        bucket: str,
        key: str,
        multipart_id: str,
        parts: list[UploadedPart],
    ) -> ObjectMetadata:
        try:
            s3_parts = [
                {"PartNumber": p.part_number, "ETag": f'"{self._clean_etag(p.etag)}"'}
                for p in sorted(parts, key=lambda x: x.part_number)
            ]
            self._client.complete_multipart_upload(
                Bucket=bucket,
                Key=key,
                UploadId=multipart_id,
                MultipartUpload={"Parts": s3_parts},
            )
            return self.head(ObjectRef(bucket=bucket, key=key))
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in ("404", "NoSuchUpload"):
                raise FileNotFoundError(f"Multipart upload {multipart_id} not found") from exc
            raise

    def abort_multipart(self, bucket: str, key: str, multipart_id: str) -> None:
        try:
            self._client.abort_multipart_upload(
                Bucket=bucket,
                Key=key,
                UploadId=multipart_id,
            )
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in ("404", "NoSuchUpload"):
                return
            raise

    def copy_object(
        self,
        source: ObjectRef,
        bucket: str,
        key: str,
        source_etag: str | None = None,
    ) -> ObjectMetadata:
        copy_source: dict[str, Any] = {"Bucket": source.bucket, "Key": source.key}
        if source.version_id:
            copy_source["VersionId"] = source.version_id
        extra_args: dict[str, Any] = {}
        if source_etag:
            extra_args["CopySourceIfMatch"] = f'"{self._clean_etag(source_etag)}"'

        try:
            self._client.copy(
                CopySource=copy_source,
                Bucket=bucket,
                Key=key,
                ExtraArgs=extra_args or None,
                Config=self._transfer_config,
            )
            return self.head(ObjectRef(bucket=bucket, key=key))
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in ("412", "PreconditionFailed"):
                raise ObjectChangedError(
                    f"Source object s3://{source.bucket}/{source.key} modified concurrently (ETag mismatch)"
                ) from exc
            if code in ("404", "NoSuchKey", "NoSuchVersion"):
                raise FileNotFoundError(f"Source object s3://{source.bucket}/{source.key} not found") from exc
            if code in ("403", "AccessDenied"):
                raise PermissionError(f"Access denied during copy from s3://{source.bucket}/{source.key}") from exc
            raise

    def is_versioning_enabled(self, bucket: str) -> bool:
        try:
            resp = self._client.get_bucket_versioning(Bucket=bucket)
            return resp.get("Status") == "Enabled"
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in ("404", "NoSuchBucket"):
                raise FileNotFoundError(f"Bucket {bucket} not found") from exc
            if code in ("403", "AccessDenied"):
                raise PermissionError(f"Access denied getting versioning for bucket {bucket}") from exc
            raise

    def put_file(self, bucket: str, key: str, path: Path) -> ObjectMetadata:
        if not path.is_file():
            raise FileNotFoundError(f"Local file {path} not found")
        try:
            self._client.upload_file(
                Filename=str(path),
                Bucket=bucket,
                Key=key,
                Config=self._transfer_config,
            )
            return self.head(ObjectRef(bucket=bucket, key=key))
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in ("403", "AccessDenied"):
                raise PermissionError(f"Access denied writing s3://{bucket}/{key}") from exc
            raise
