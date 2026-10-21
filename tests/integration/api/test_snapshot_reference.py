"""Import session contract for single immutable snapshots (real Postgres + isolated MinIO)."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from dq_scoring.adapters.storage.s3_object_store import S3ObjectStoreAdapter
from dq_scoring.adapters.storage.s3_settings import get_s3_settings
from dq_scoring.adapters.storage.source_settings import (
    SourceStoreSettings,
    get_source_settings,
    source_binding_sha256,
)
from dq_scoring.presentation.api.auth import AuthenticatedUser, create_access_token
from dq_scoring.presentation.api.config import get_api_settings

CSV = b"a,b\n1,2\n3,4\n"


@pytest.fixture
def user_id() -> UUID:
    return uuid4()


@pytest.fixture
def headers(test_tenant_id, user_id, db_conn):
    with db_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO tenants (tenant_id, tenant_code, tenant_name, subscription_tier, status) "
            "VALUES (%s, %s, 'Ref Tenant', 'ENTERPRISE', 'ACTIVE') ON CONFLICT DO NOTHING;",
            (test_tenant_id, f"t_{test_tenant_id.hex[:8]}"),
        )
        cur.execute(
            "INSERT INTO users (user_id, email, password_hash, full_name, is_active) "
            "VALUES (%s, %s, 'x', 'Ref Engineer', TRUE) ON CONFLICT DO NOTHING;",
            (user_id, f"ref_{user_id.hex[:8]}@example.com"),
        )
        cur.execute("SELECT set_config('app.current_tenant_id', %s, false);", (str(test_tenant_id),))
        cur.execute(
            "INSERT INTO tenant_memberships (tenant_id, user_id, role, status) "
            "VALUES (%s, %s, 'DATA_ENGINEER', 'ACTIVE') ON CONFLICT DO NOTHING;",
            (test_tenant_id, user_id),
        )
        db_conn.commit()
    user = AuthenticatedUser(user_id=user_id, tenant_id=test_tenant_id, email="e@example.com", role="DATA_ENGINEER")
    return {"Authorization": f"Bearer {create_access_token(user, secret_key=get_api_settings().jwt_secret)}"}


@pytest.fixture
def owned():
    settings = get_s3_settings()
    return settings, S3ObjectStoreAdapter(settings)


@pytest.fixture
def shared_bucket(owned):
    """A distinct bucket reached through the read-only source client configuration."""
    _, store = owned
    bucket = f"dq-src-{uuid4().hex}"
    store._client.create_bucket(Bucket=bucket)
    store._client.put_bucket_versioning(Bucket=bucket, VersioningConfiguration={"Status": "Enabled"})
    yield bucket
    for page in store._client.get_paginator("list_object_versions").paginate(Bucket=bucket):
        objs = [{"Key": o["Key"], "VersionId": o["VersionId"]} for o in [*page.get("Versions", []), *page.get("DeleteMarkers", [])]]
        if objs:
            store._client.delete_objects(Bucket=bucket, Delete={"Objects": objs})
    store._client.delete_bucket(Bucket=bucket)


def _source_config(owned_settings, bucket: str, tenant_id: UUID, *, retention: bool) -> SourceStoreSettings:
    return SourceStoreSettings(
        enabled=True,
        endpoint_url=owned_settings.endpoint_url,
        access_key_id=owned_settings.access_key_id,
        secret_access_key=owned_settings.secret_access_key,
        region=owned_settings.region,
        use_ssl=owned_settings.use_ssl,
        ca_bundle=owned_settings.ca_bundle,
        bucket=bucket,
        tenant_prefixes={tenant_id: [f"tenants/{tenant_id}/"]},
        retention_guaranteed=retention,
    )


@pytest.fixture
def configure_source(client: TestClient, owned, shared_bucket, test_tenant_id):
    def _apply(retention: bool) -> SourceStoreSettings:
        config = _source_config(owned[0], shared_bucket, test_tenant_id, retention=retention)
        client.app.dependency_overrides[get_source_settings] = lambda: config
        return config

    yield _apply
    client.app.dependency_overrides.pop(get_source_settings, None)


def _create(client, headers, source=None, size=None, **extra):
    payload = {
        "client_request_id": str(uuid4()),
        "asset_name": f"asset-{uuid4().hex[:8]}",
        "format": "CSV",
        "original_filename": "data.csv",
        "size_bytes": size or len(CSV),
        **({"source": source} if source else {}),
        **extra,
    }
    return client.post("/api/v1/imports", headers=headers, json=payload)


def _manifest(db_conn, upload_id):
    with db_conn.cursor() as cur:
        cur.execute("SELECT manifest, staging_key, status FROM dataset_upload_sessions WHERE upload_id=%s", (upload_id,))
        return cur.fetchone()


def _put(store, bucket, key, body=CSV):
    return store._client.put_object(Bucket=bucket, Key=key, Body=body)


def test_direct_upload_uses_snapshot_bucket_layout_v2_and_pins_source_ref(client, headers, db_conn, owned, test_tenant_id):
    settings, store = owned
    resp = _create(client, headers)
    assert resp.status_code == 201
    upload_id = resp.json()["upload_id"]
    manifest, key, _ = _manifest(db_conn, upload_id)
    assert manifest["upload_layout_version"] == 2
    assert manifest["storage_mode"] == "OWNED_RAW"
    assert manifest["staging_bucket"] == settings.bucket_snapshots
    assert key == f"snapshots/{test_tenant_id}/{upload_id}/source.csv"

    part = client.post(f"/api/v1/imports/{upload_id}/parts/1", headers={**headers, "Content-Length": str(len(CSV))}, content=CSV)
    assert part.status_code == 200
    etag = part.json()["etag"]
    done = client.post(f"/api/v1/imports/{upload_id}/complete", headers=headers, json={"parts": [{"part_number": 1, "etag": etag}]})
    assert done.status_code == 202
    manifest, _, status = _manifest(db_conn, upload_id)
    assert status == "STAGED"
    head = store._client.head_object(Bucket=settings.bucket_snapshots, Key=key)
    assert manifest["source_ref"] == {
        "bucket": settings.bucket_snapshots,
        "key": key,
        "etag": head["ETag"].strip('"'),
        "version_id": head["VersionId"],
        "size_bytes": len(CSV),
    }
    # Nothing was written to the legacy staging bucket.
    listing = store._client.list_objects_v2(Bucket=settings.bucket_staging, Prefix=f"imports/{test_tenant_id}/{upload_id}/")
    assert listing.get("KeyCount", 0) == 0


def test_direct_upload_abort_targets_manifest_bucket(client, headers, db_conn, owned):
    settings, store = owned
    upload_id = _create(client, headers).json()["upload_id"]
    assert client.post(f"/api/v1/imports/{upload_id}/abort", headers=headers).status_code == 200
    uploads = store._client.list_multipart_uploads(Bucket=settings.bucket_snapshots, Prefix="snapshots/").get("Uploads", [])
    assert all(upload_id not in u["Key"] for u in uploads)


def test_inflight_legacy_staging_upload_still_completes(client, headers, db_conn, owned, test_tenant_id):
    settings, store = owned
    resp = _create(client, headers)
    upload_id = resp.json()["upload_id"]
    # Rewrite the session into the pre-layout-2 shape: multipart opened in staging.
    legacy_key = f"imports/{test_tenant_id}/{upload_id}/source.csv"
    mp_id = store.create_multipart(settings.bucket_staging, legacy_key)
    store.abort_multipart(settings.bucket_snapshots, f"snapshots/{test_tenant_id}/{upload_id}/source.csv", _manifest_mp(db_conn, upload_id))
    with db_conn.cursor() as cur:
        cur.execute(
            "UPDATE dataset_upload_sessions SET staging_key=%s, multipart_id=%s, "
            "manifest = (manifest - 'upload_layout_version' - 'storage_mode') || jsonb_build_object('staging_bucket', %s::text) "
            "WHERE upload_id=%s",
            (legacy_key, mp_id, settings.bucket_staging, upload_id),
        )
        db_conn.commit()
    part = client.post(f"/api/v1/imports/{upload_id}/parts/1", headers={**headers, "Content-Length": str(len(CSV))}, content=CSV)
    assert part.status_code == 200
    done = client.post(f"/api/v1/imports/{upload_id}/complete", headers=headers, json={"parts": [{"part_number": 1, "etag": part.json()["etag"]}]})
    assert done.status_code == 202
    manifest, _, _ = _manifest(db_conn, upload_id)
    assert manifest["source_ref"]["bucket"] == settings.bucket_staging
    assert manifest["source_ref"]["key"] == legacy_key


def _manifest_mp(db_conn, upload_id) -> str:
    with db_conn.cursor() as cur:
        cur.execute("SELECT multipart_id FROM dataset_upload_sessions WHERE upload_id=%s", (upload_id,))
        return cur.fetchone()[0]


def test_part_upload_rejects_tampered_manifest_location(client, headers, db_conn, owned):
    upload_id = _create(client, headers).json()["upload_id"]
    with db_conn.cursor() as cur:
        cur.execute("UPDATE dataset_upload_sessions SET staging_key='snapshots/other/x/source.csv' WHERE upload_id=%s", (upload_id,))
        db_conn.commit()
    part = client.post(f"/api/v1/imports/{upload_id}/parts/1", headers={**headers, "Content-Length": str(len(CSV))}, content=CSV)
    assert part.status_code == 409


def test_staging_selection_pins_owned_raw_with_exact_metadata(client, headers, db_conn, owned, test_tenant_id):
    settings, store = owned
    key = f"imports/{test_tenant_id}/{uuid4()}/source.csv"
    put = _put(store, settings.bucket_staging, key)
    resp = _create(client, headers, source={"bucket": settings.bucket_staging, "key": key})
    assert resp.status_code == 201
    manifest, staged_key, status = _manifest(db_conn, resp.json()["upload_id"])
    assert status == "STAGED" and staged_key == key
    assert manifest["storage_mode"] == "OWNED_RAW"
    assert manifest["staging_bucket"] == settings.bucket_staging and manifest["staging_key"] == key
    assert "upload_layout_version" not in manifest
    assert manifest["source_ref"]["etag"] == put["ETag"].strip('"')
    assert manifest["source_ref"]["size_bytes"] == len(CSV)


def test_shared_source_with_retention_pins_external_version(client, headers, db_conn, owned, shared_bucket, configure_source, test_tenant_id):
    _, store = owned
    config = configure_source(retention=True)
    key = f"tenants/{test_tenant_id}/in.csv"
    put = _put(store, shared_bucket, key)
    resp = _create(client, headers, source={"source_id": "shared", "bucket": shared_bucket, "key": key})
    assert resp.status_code == 201
    manifest, _, status = _manifest(db_conn, resp.json()["upload_id"])
    assert status == "STAGED"
    assert manifest["storage_mode"] == "EXTERNAL_VERSION"
    assert manifest["source_binding_sha256"] == source_binding_sha256(config)
    assert manifest["source_ref"] == {
        "bucket": shared_bucket, "key": key, "etag": put["ETag"].strip('"'),
        "version_id": put["VersionId"], "size_bytes": len(CSV), "source_id": "shared",
    }


def test_shared_source_without_retention_falls_back_to_owned_raw(client, headers, db_conn, owned, shared_bucket, configure_source, test_tenant_id):
    _, store = owned
    configure_source(retention=False)
    key = f"tenants/{test_tenant_id}/in.csv"
    _put(store, shared_bucket, key)
    resp = _create(client, headers, source={"source_id": "shared", "bucket": shared_bucket, "key": key})
    assert resp.status_code == 201
    manifest, _, _ = _manifest(db_conn, resp.json()["upload_id"])
    assert manifest["storage_mode"] == "OWNED_RAW"
    assert manifest["source_ref"]["source_id"] == "shared"


def test_suspended_source_null_version_freezes_one_owned_raw(client, headers, db_conn, owned, shared_bucket, configure_source, test_tenant_id, monkeypatch):
    from dataclasses import replace

    from dq_scoring.workers.import_worker import ImportWorker
    settings, store = owned
    config = configure_source(retention=True)
    monkeypatch.setattr('dq_scoring.workers.import_worker.get_source_settings', lambda: config)
    store._client.put_bucket_versioning(Bucket=shared_bucket, VersioningConfiguration={'Status': 'Suspended'})
    key = f'tenants/{test_tenant_id}/null.csv'
    _put(store, shared_bucket, key)
    original_head = S3ObjectStoreAdapter.head
    def source_head(self, ref):
        meta = original_head(self, ref)
        return replace(meta, version_id='null') if ref.bucket == shared_bucket else meta
    monkeypatch.setattr(S3ObjectStoreAdapter, 'head', source_head)
    created = _create(client, headers, source={'source_id': 'shared', 'bucket': shared_bucket, 'key': key})
    assert created.status_code == 201, created.text
    upload = created.json()['upload_id']
    worker = ImportWorker(store)
    claimed = worker.claim_next_session(db_conn)
    worker.process_session(db_conn, claimed)
    db_conn.commit()
    manifest, _, state = _manifest(db_conn, upload)
    assert state == 'VERIFIED', manifest
    assert manifest['source_descriptor']['storage_mode'] == 'OWNED_RAW'
    versions = store._client.list_object_versions(Bucket=settings.bucket_snapshots, Prefix=f'snapshots/{test_tenant_id}/{upload}/').get('Versions', [])
    assert len(versions) == 1


def test_shared_source_pins_historical_version_not_latest(client, headers, db_conn, owned, shared_bucket, configure_source, test_tenant_id):
    _, store = owned
    configure_source(retention=True)
    key = f"tenants/{test_tenant_id}/in.csv"
    first = _put(store, shared_bucket, key)
    _put(store, shared_bucket, key, CSV + b"5,6\n")
    resp = _create(client, headers, source={"source_id": "shared", "bucket": shared_bucket, "key": key, "version_id": first["VersionId"]})
    assert resp.status_code == 201
    manifest, _, _ = _manifest(db_conn, resp.json()["upload_id"])
    assert manifest["source_ref"]["version_id"] == first["VersionId"]
    assert manifest["source_ref"]["etag"] == first["ETag"].strip('"')
    # Declared size describes the latest object, not the pinned one.
    assert _create(client, headers, size=len(CSV) + 4, source={"source_id": "shared", "bucket": shared_bucket, "key": key, "version_id": first["VersionId"]}).status_code == 409


@pytest.mark.parametrize("variant", ["other_tenant_prefix", "other_bucket", "missing", "unknown_version", "disabled"])
def test_shared_source_unauthorized_or_missing_is_generic_404(client, headers, owned, shared_bucket, configure_source, test_tenant_id, variant):
    settings, store = owned
    config = configure_source(retention=True)
    key = f"tenants/{test_tenant_id}/in.csv"
    _put(store, shared_bucket, key)
    other_key = f"tenants/{uuid4()}/in.csv"
    _put(store, shared_bucket, other_key)
    source = {"source_id": "shared", "bucket": shared_bucket, "key": key}
    if variant == "other_tenant_prefix":
        source["key"] = other_key
    elif variant == "other_bucket":
        source["bucket"] = settings.bucket_snapshots
    elif variant == "missing":
        source["key"] = f"tenants/{test_tenant_id}/absent.csv"
    elif variant == "unknown_version":
        source["version_id"] = "does-not-exist"
    else:
        client.app.dependency_overrides[get_source_settings] = lambda: SourceStoreSettings()
    resp = _create(client, headers, source=source)
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "RESOURCE_NOT_FOUND"
    assert shared_bucket not in resp.text and config.bucket not in resp.text.replace("RESOURCE_NOT_FOUND", "")


def test_workspace_admin_gets_no_shared_prefix_bypass(client, db_conn, owned, shared_bucket, configure_source, test_tenant_id, user_id):
    _, store = owned
    configure_source(retention=True)
    other_key = f"tenants/{uuid4()}/in.csv"
    _put(store, shared_bucket, other_key)
    with db_conn.cursor() as cur:
        cur.execute("INSERT INTO tenants (tenant_id, tenant_code, tenant_name, subscription_tier, status) VALUES (%s, %s, 'Adm', 'ENTERPRISE', 'ACTIVE') ON CONFLICT DO NOTHING;", (test_tenant_id, f"t_{test_tenant_id.hex[:8]}"))
        cur.execute("INSERT INTO users (user_id, email, password_hash, full_name, is_active) VALUES (%s, %s, 'x', 'Adm', TRUE) ON CONFLICT DO NOTHING;", (user_id, f"adm_{user_id.hex[:8]}@example.com"))
        db_conn.commit()
    admin = AuthenticatedUser(user_id=user_id, tenant_id=test_tenant_id, email="a@example.com", role="WORKSPACE_ADMIN")
    admin_headers = {"Authorization": f"Bearer {create_access_token(admin, secret_key=get_api_settings().jwt_secret)}"}
    resp = _create(client, admin_headers, source={"source_id": "shared", "bucket": shared_bucket, "key": other_key})
    assert resp.status_code == 404


@pytest.mark.parametrize(
    "extra",
    [{"endpoint_url": "http://evil"}, {"access_key_id": "x"}, {"secret_access_key": "x"}, {"source_id": "other"}, {"version_id": ""}, {"version_id": "null"}],
)
def test_source_schema_forbids_endpoints_secrets_and_empty_versions(client, headers, extra):
    resp = _create(client, headers, source={"bucket": "b", "key": "k.csv", **extra})
    assert resp.status_code == 422


def test_configure_clears_legacy_equivalence_and_keeps_descriptor(client, headers, db_conn, owned, test_tenant_id):
    settings, store = owned
    key = f"imports/{test_tenant_id}/{uuid4()}/source.csv"
    _put(store, settings.bucket_staging, key)
    upload_id = _create(client, headers, source={"bucket": settings.bucket_staging, "key": key}).json()["upload_id"]
    descriptor = {"descriptor_version": 2, "marker": "keep"}
    with db_conn.cursor() as cur:
        cur.execute(
            "UPDATE dataset_upload_sessions SET status='VERIFIED', manifest = manifest || "
            "jsonb_build_object('legacy_equivalence', jsonb_build_object('equal', true), 'source_descriptor', %s::jsonb, "
            "'owned_raw_ref', jsonb_build_object('bucket', 'b')) WHERE upload_id=%s",
            ('{"descriptor_version": 2, "marker": "keep"}', upload_id),
        )
        db_conn.commit()
    resp = client.post(f"/api/v1/imports/{upload_id}/configure", headers=headers, json={"column_names": ["x", "y"]})
    assert resp.status_code == 200
    manifest, _, status = _manifest(db_conn, upload_id)
    assert status == "STAGED"
    assert manifest["legacy_equivalence"] is None
    assert manifest["source_descriptor"] == descriptor
    assert manifest["owned_raw_ref"] == {"bucket": "b"}
    assert manifest["column_names_mapping"] == ["x", "y"]


def test_automatic_expired_lease_retries_remain_bounded(client, headers, db_conn, owned, test_tenant_id):
    from dq_scoring.workers.import_worker import ImportWorker
    settings, store = owned
    key = f'imports/{test_tenant_id}/{uuid4()}/source.csv'
    _put(store, settings.bucket_staging, key)
    created = _create(client, headers, source={'bucket': settings.bucket_staging, 'key': key})
    assert created.status_code == 201, created.text
    upload = created.json()['upload_id']
    worker = ImportWorker(store)
    for generation in range(1, 4):
        claimed = worker.claim_next_session(db_conn)
        assert claimed is not None and claimed['lease_generation'] == generation
        db_conn.execute("UPDATE dataset_upload_sessions SET lease_expires_at=now()-interval '1 second' WHERE upload_id=%s", (upload,))
        db_conn.commit()
    assert worker.claim_next_session(db_conn) is None
    state, reason = db_conn.execute('SELECT status,error_reason FROM dataset_upload_sessions WHERE upload_id=%s', (upload,)).fetchone()
    assert state == 'FAILED' and reason == 'IMPORT_RETRY_EXHAUSTED'
