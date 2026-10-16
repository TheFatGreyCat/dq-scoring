"""Global pytest configuration and environment hooks."""

import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest


def pytest_configure() -> None:
    """Auto-configure JAVA_HOME for local Spark execution and default JWT algorithm for tests."""
    project_root = Path(__file__).resolve().parent.parent
    local_jdk = project_root / ".tools" / "jdk-21"
    java_exe = "java.exe" if os.name == "nt" else "java"
    if (local_jdk / "bin" / java_exe).is_file():
        os.environ["JAVA_HOME"] = str(local_jdk)
        path_env = os.environ.get("PATH", "")
        bin_dir = str(local_jdk / "bin")
        if bin_dir not in path_env:
            os.environ["PATH"] = f"{bin_dir}{os.pathsep}{path_env}"
    os.environ["DQ_AUTH_ALGORITHM"] = "HS256"
    os.environ["DQ_JWT_ALGORITHM"] = "HS256"
    private_env = project_root / ".tmp" / "e2e.env"
    if private_env.exists():
        from scripts.setup_test_environment import _read_env
        for key, value in _read_env(private_env).items():
            os.environ.setdefault(key, value)
    os.environ.setdefault("DQ_AUTH_SECRET_KEY", "synthetic-test-only-jwt-secret-key-0123456789")
    os.environ.setdefault("DQ_JWT_SECRET", os.environ["DQ_AUTH_SECRET_KEY"])
    os.environ.setdefault("DQ_POSTGRES_DSN", "postgresql://unused@localhost:15432/dq_scoring_unused")


@pytest.fixture(scope="session", autouse=True)
def isolated_storage():
    """Own random buckets only; never use credentials or buckets from developer .env."""
    from uuid import uuid4

    from dq_scoring.adapters.storage.s3_object_store import S3ObjectStoreAdapter
    from dq_scoring.adapters.storage.s3_settings import get_s3_settings
    endpoint = os.getenv("DQ_S3_ENDPOINT_URL")
    if endpoint is None or urlsplit(endpoint).hostname not in ("127.0.0.1", "localhost", "minio"):
        raise RuntimeError("Synthetic isolated MinIO test environment is required.")
    names = {name: f"dq-e2e-{uuid4().hex}-{name.lower()}" for name in ("STAGING", "SNAPSHOTS", "ARTIFACTS")}
    previous = {f"DQ_S3_BUCKET_{name}": os.environ.get(f"DQ_S3_BUCKET_{name}") for name in names}
    for name, bucket in names.items():
        os.environ[f"DQ_S3_BUCKET_{name}"] = bucket
    get_s3_settings.cache_clear()
    store = S3ObjectStoreAdapter()
    for bucket in names.values():
        store._client.create_bucket(Bucket=bucket)
    store._client.put_bucket_versioning(Bucket=names["SNAPSHOTS"], VersioningConfiguration={"Status": "Enabled"})
    yield
    for bucket in names.values():
        for page in store._client.get_paginator("list_object_versions").paginate(Bucket=bucket):
            objects = [{"Key": obj["Key"], "VersionId": obj["VersionId"]} for obj in [*page.get("Versions", []), *page.get("DeleteMarkers", [])]]
            if objects:
                store._client.delete_objects(Bucket=bucket, Delete={"Objects": objects})
        for page in store._client.get_paginator("list_multipart_uploads").paginate(Bucket=bucket):
            for upload in page.get("Uploads", []):
                store._client.abort_multipart_upload(Bucket=bucket, Key=upload["Key"], UploadId=upload["UploadId"])
        store._client.delete_bucket(Bucket=bucket)
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    get_s3_settings.cache_clear()


