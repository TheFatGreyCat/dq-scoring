"""Guarded orphan pruning against real Postgres with a deterministic version-aware in-memory store."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb
from pydantic import SecretStr

from dq_scoring.adapters.db.postgres_import_store import PostgresImportStore
from dq_scoring.adapters.storage.s3_settings import S3Settings
from dq_scoring.adapters.storage.source_settings import SourceStoreSettings
from dq_scoring.ports.object_store import ObjectMetadata, ObjectRef
from dq_scoring.presentation.cli import prune_snapshot_orphans as cli
from dq_scoring.presentation.cli.prune_snapshot_orphans import (
    PruneAborted,
    prune_orphans,
)

NOW = datetime.now(UTC)
OLD = NOW - timedelta(days=3)
S3 = S3Settings(
    endpoint_url="http://localhost:9000", access_key_id=SecretStr("k"), secret_access_key=SecretStr("s"),
    bucket_staging="stg", bucket_snapshots="snap", bucket_artifacts="art",
)
SOURCE = SourceStoreSettings(_env_file=None)


class FakeStore:
    def __init__(self) -> None:
        self.versions: dict[tuple[str, str, str | None], datetime] = {}
        self.deleted: list[ObjectRef] = []
        self.deny = False
        self.on_head = None

    def add(self, bucket: str, key: str, version: str | None = "v1", modified: datetime = OLD) -> ObjectRef:
        self.versions[(bucket, key, version)] = modified
        return ObjectRef(bucket, key, version)

    def list_versions(self, bucket, prefix):
        for (b, k, v), modified in sorted(self.versions.items(), key=str):
            if b == bucket and k.startswith(prefix):
                yield ObjectMetadata(ObjectRef(b, k, v), 7, "e", v, modified)

    def head(self, ref):
        if self.on_head:
            self.on_head()
        if (ref.bucket, ref.key, ref.version_id) not in self.versions:
            raise FileNotFoundError
        return ObjectMetadata(ref, 7, "e", ref.version_id, self.versions[(ref.bucket, ref.key, ref.version_id)])

    def delete_version(self, ref):
        assert ref.version_id and ref.version_id != "null"
        if self.deny:
            raise PermissionError
        if self.versions.pop((ref.bucket, ref.key, ref.version_id), None) is None:
            raise FileNotFoundError
        self.deleted.append(ref)


@pytest.fixture
def tenant(db_conn: psycopg.Connection):
    tenant_id, user_id, asset_id = uuid4(), uuid4(), uuid4()
    db_conn.execute("INSERT INTO tenants (tenant_id, tenant_code, tenant_name) VALUES (%s,%s,'T')", (tenant_id, f"t{tenant_id.hex[:8]}"))
    db_conn.execute("INSERT INTO users (user_id,email,password_hash,full_name) VALUES (%s,%s,'x','U')", (user_id, f"{user_id}@x.test"))
    db_conn.execute(
        "INSERT INTO data_assets (asset_id,tenant_id,asset_name,slug,format,owner_user_id,created_by) VALUES (%s,%s,'a','a','CSV',%s,%s)",
        (asset_id, tenant_id, user_id, user_id),
    )
    db_conn.commit()
    return tenant_id, user_id, asset_id


def session(db_conn, tenant, *, status="FAILED", expired=True, manifest=None, key=None, upload_id=None) -> UUID:
    tenant_id, user_id, asset_id = tenant
    upload_id = upload_id or uuid4()
    when = OLD if expired else NOW
    db_conn.execute(
        "INSERT INTO dataset_upload_sessions (upload_id,tenant_id,asset_id,client_request_id,format,original_filename,size_bytes,"
        "staging_key,status,manifest,created_by,created_at,expires_at,updated_at) VALUES (%s,%s,%s,%s,'CSV','f.csv',1,%s,%s,%s,%s,%s,%s,%s)",
        (upload_id, tenant_id, asset_id, uuid4(), key or f"snapshots/{tenant_id}/{upload_id}/source.csv", status,
         Jsonb(manifest or {}), user_id, when, when if expired else NOW + timedelta(hours=24), when),
    )
    db_conn.commit()
    return upload_id


def run(db_conn, store, tenant, apply=False, **kw):
    with db_conn.transaction():
        return prune_orphans(db_conn, store, S3, SOURCE, tenant_id=tenant[0], apply=apply, now=NOW, **kw)


def statuses(report):
    return {(c["key"], c["version_id"]): c["status"] for c in report["candidates"]}


def test_dry_run_deletes_nothing_and_apply_deletes_exact_version(db_conn, tenant):
    upload = session(db_conn, tenant)
    store = FakeStore()
    key = f"snapshots/{tenant[0]}/{upload}/source.csv"
    store.add("snap", key, "v1")
    store.add("snap", key, "v2")
    code, report = run(db_conn, store, tenant)
    assert code == 0 and set(statuses(report).values()) == {"WOULD_DELETE"} and not store.deleted
    json.dumps(report)
    code, report = run(db_conn, store, tenant, apply=True)
    assert code == 0 and report["counts"] == {"DELETED": 2} and len(store.deleted) == 2 and not store.versions


def test_live_roots_are_protected(db_conn, tenant):
    tenant_id, user_id, asset_id = tenant
    store = FakeStore()
    registered, session_root, unbound, keep, run_root = (session(db_conn, tenant) for _ in range(5))
    keys = {u: f"snapshots/{tenant_id}/{u}/source.csv" for u in (registered, session_root, unbound, keep, run_root)}
    for k in keys.values():
        store.add("snap", k, "v1")
        store.add("snap", k, "v2")
    snap_id = uuid4()
    db_conn.execute(
        "INSERT INTO dataset_snapshots (snapshot_id,tenant_id,asset_id,version_number,version_status,source_kind,source_descriptor,"
        "content_sha256,storage_location,schema_definition,total_rows,total_columns,created_by,captured_at,manifest) "
        "VALUES (%s,%s,%s,1,'ARCHIVED','OBJECT_FILE',%s,%s,'x',%s,1,1,%s,now(),%s)",
        (snap_id, tenant_id, asset_id,
         Jsonb({"descriptor_version": 2, "bucket": "snap", "key": keys[registered], "version_id": "v1"}),
         "a" * 64, Jsonb({"columns": ["a"]}), user_id,
         Jsonb({"canonical": {"bucket": "snap", "key": keys[unbound]}})),
    )
    ruleset, policy, run_id = uuid4(), uuid4(), uuid4()
    db_conn.execute("INSERT INTO rulesets(ruleset_id,tenant_id,asset_id,version,config_hash,status,created_by) "
                    "VALUES(%s,%s,%s,'prune-root','r','DRAFT',%s)", (ruleset, tenant_id, asset_id, user_id))
    db_conn.execute("INSERT INTO scoring_policies(policy_id,tenant_id,version,config_hash,status,created_by,dimension_weights,"
                    "publication_threshold,gate_rules) VALUES(%s,%s,'prune-root','p','DRAFT',%s,'{}',0.8,'{}')",
                    (policy, tenant_id, user_id))
    db_conn.execute("INSERT INTO evaluation_runs(run_id,tenant_id,snapshot_id,ruleset_id,policy_id,idempotency_key,outlier_config,"
                    "outlier_config_hash,run_status,created_by) VALUES(%s,%s,%s,%s,%s,%s,%s,'root-hash','QUEUED',%s)",
                    (run_id, tenant_id, snap_id, ruleset, policy, str(run_id),
                     Jsonb({'_run_spec': {'snapshot': {'source_descriptor': {
                         'bucket': 'snap', 'key': keys[run_root], 'version_id': 'v1'}}}}), user_id))
    db_conn.commit()
    active = session(db_conn, tenant, status="VERIFIED", expired=True,
                     manifest={"owned_raw_ref": {"bucket": "snap", "key": keys[session_root], "version_id": "v2"}})
    _, report = run(db_conn, store, tenant)
    result = statuses(report)
    assert result[(keys[registered], "v1")] == "SKIPPED_LIVE_ROOT"
    assert result[(keys[registered], "v2")] == "WOULD_DELETE"
    assert result[(keys[unbound], "v1")] == result[(keys[unbound], "v2")] == "SKIPPED_LIVE_ROOT"
    assert result[(keys[session_root], "v2")] == "SKIPPED_LIVE_ROOT"
    assert result[(keys[keep], "v1")] == "WOULD_DELETE"
    assert result[(keys[run_root], 'v1')] == 'SKIPPED_LIVE_ROOT'
    assert result[(keys[run_root], 'v2')] == 'WOULD_DELETE'
    assert str(active) not in {c['upload_id'] for c in report['candidates']}


@pytest.mark.parametrize('state', ['FAILED', 'REJECTED'])
def test_nonexpired_and_active_sessions_never_candidates(db_conn, tenant, state):
    store = FakeStore()
    fresh = session(db_conn, tenant, status=state, expired=False,
                    manifest={'error_code': 'DUPLICATE_COLUMN_NAME'})
    staged = session(db_conn, tenant, status="STAGED")
    for u in (fresh, staged):
        store.add("snap", f"snapshots/{tenant[0]}/{u}/source.csv")
    _, report = run(db_conn, store, tenant, apply=True)
    assert report["sessions"] == 0 and not store.deleted


def test_recent_versions_kept_and_unversioned_skipped(db_conn, tenant):
    upload = session(db_conn, tenant)
    store = FakeStore()
    key = f"snapshots/{tenant[0]}/{upload}/source.csv"
    store.add("snap", key, "new", modified=NOW)
    store.add("snap", key + ".u", None)
    code, report = run(db_conn, store, tenant, apply=True)
    assert code == 0 and not store.deleted
    assert statuses(report) == {(key, "new"): "SKIPPED_RECENT", (key + ".u", None): "UNVERSIONED_SKIPPED"}
    assert report["unversioned_bytes_not_reclaimed"] == 7


def test_external_selected_source_never_deleted(db_conn, tenant):
    store = FakeStore()
    key = f"imports/{tenant[0]}/other.csv"
    store.add("stg", key, "v1")
    session(db_conn, tenant, key=key, manifest={"staging_bucket": "stg", "source_ref": {"bucket": "stg", "key": key, "version_id": "v1"}})
    _, report = run(db_conn, store, tenant, apply=True)
    assert not store.deleted and report["candidates"] == []


@pytest.mark.parametrize('prefix', ['staging', 'imports'])
def test_exact_staging_key_owned_by_session_is_candidate(db_conn, tenant, prefix):
    upload = uuid4()
    key = f"{prefix}/{tenant[0]}/{upload}/source.csv"
    store = FakeStore()
    store.add("stg", key)
    store.add("stg", key + "2")  # sibling key must not match the exact staging target
    session(db_conn, tenant, key=key, upload_id=upload, manifest={"staging_bucket": "stg"})
    run(db_conn, store, tenant, apply=True)
    assert [d.key for d in store.deleted] == [key]


def test_denied_blocks_nonzero_and_not_found_is_idempotent(db_conn, tenant):
    upload = session(db_conn, tenant)
    key = f"snapshots/{tenant[0]}/{upload}/source.csv"
    store = FakeStore()
    store.add("snap", key)
    store.deny = True
    code, report = run(db_conn, store, tenant, apply=True)
    assert code == 1 and report["status"] == "BLOCKED" and statuses(report)[(key, "v1")] == "BLOCKED"
    store.deny = False
    store.on_head = lambda: store.versions.clear()
    code, report = run(db_conn, store, tenant, apply=True)
    assert code == 0 and statuses(report)[(key, "v1")] == "ALREADY_ABSENT"


def test_root_appearing_before_delete_is_rechecked(db_conn, tenant):
    upload = session(db_conn, tenant)
    active = session(db_conn, tenant, status="VERIFIED")
    key = f"snapshots/{tenant[0]}/{upload}/source.csv"
    store = FakeStore()
    store.add("snap", key)

    def pin():
        db_conn.execute(
            "UPDATE dataset_upload_sessions SET manifest=%s WHERE upload_id=%s",
            (Jsonb({"owned_raw_ref": {"bucket": "snap", "key": key, "version_id": "v1"}}), active),
        )
        store.on_head = None

    # the recheck loads roots first, so mutate between scan and delete via list_versions side effect
    original = store.list_versions

    def listing(bucket, prefix):
        yield from list(original(bucket, prefix))
        pin()

    store.list_versions = listing
    _, report = run(db_conn, store, tenant, apply=True)
    assert not store.deleted and statuses(report)[(key, "v1")] == "SKIPPED_LIVE_ROOT"


def test_min_age_and_source_separation_enforced(db_conn, tenant):
    with pytest.raises(PruneAborted):
        run(db_conn, FakeStore(), tenant, older_than_hours=23)
    overlap = SourceStoreSettings(_env_file=None, enabled=True, endpoint_url="http://localhost:9000", bucket="snap",
                                  access_key_id=SecretStr("k"), secret_access_key=SecretStr("s"),
                                  tenant_prefixes={tenant[0]: ["p/"]})
    with pytest.raises(PruneAborted), db_conn.transaction():
        prune_orphans(db_conn, FakeStore(), S3, overlap, tenant_id=tenant[0], apply=True)


def test_apply_blocks_when_mutator_holds_shared_lock(db_conn, tenant, pg_dsn, monkeypatch, capsys):
    monkeypatch.setenv("DQ_MIGRATION_POSTGRES_DSN", pg_dsn)
    monkeypatch.setattr(cli, "get_s3_settings", lambda: S3)
    monkeypatch.setattr(cli, "S3ObjectStoreAdapter", lambda settings: FakeStore())
    monkeypatch.setattr(cli, "SourceStoreSettings", lambda: SOURCE)
    monkeypatch.setattr(cli, "LOCK_TIMEOUT", "200ms")
    with psycopg.connect(pg_dsn) as holder, holder.transaction():
        PostgresImportStore.lock_tenant_storage(holder, tenant[0])
        assert cli.main(["--tenant-id", str(tenant[0]), "--apply"]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "STORAGE_BUSY"
    assert cli.main(["--tenant-id", str(tenant[0]), "--dry-run"]) == 0
    assert cli.main(["--tenant-id", str(tenant[0]), "--apply"]) == 0


def test_cli_rejects_missing_dsn_and_short_age(monkeypatch, capsys):
    monkeypatch.delenv("DQ_MIGRATION_POSTGRES_DSN", raising=False)
    assert cli.main(["--tenant-id", str(uuid4()), "--dry-run"]) == 2
    with pytest.raises(SystemExit):
        cli.main(["--tenant-id", str(uuid4()), "--dry-run", "--older-than-hours", "1"])
    with pytest.raises(SystemExit):
        cli.main(["--tenant-id", str(uuid4())])


def test_apply_never_enumerates_other_tenant_prefix(db_conn, tenant):
    upload = session(db_conn, tenant)
    store = FakeStore()
    own = store.add('snap', f'snapshots/{tenant[0]}/{upload}/source.csv')
    foreign = store.add('snap', f'snapshots/{uuid4()}/{upload}/source.csv')
    code, report = run(db_conn, store, tenant, apply=True)
    assert code == 0 and report['counts'] == {'DELETED': 1}
    assert store.deleted == [own]
    assert (foreign.bucket, foreign.key, foreign.version_id) in store.versions
