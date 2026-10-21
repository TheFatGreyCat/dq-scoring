"""Migration 024: descriptor v2 profile eligibility/fingerprint, legacy preservation, guarded down."""
import copy
import hashlib
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

from dq_scoring.adapters.db.migrator import DEFAULT_MIGRATIONS_DIR
from dq_scoring.core.entities import DatasetSnapshot
from dq_scoring.services.snapshot_profile_service import (
    SnapshotProfileError,
    profile_fingerprint,
)

UP = (DEFAULT_MIGRATIONS_DIR / "024_single_source_snapshots.sql").read_text(encoding="utf-8")
DOWN = (DEFAULT_MIGRATIONS_DIR / "024_single_source_snapshots_down.sql").read_text(encoding="utf-8")
SQL_022 = (DEFAULT_MIGRATIONS_DIR / "022_snapshot_profiles.sql").read_text(encoding="utf-8")
FUNCTIONS = ("snapshot_profile_fingerprint", "enforce_snapshot_profile_transition")

# Verbatim 022 fingerprint expression, evaluated independently of the migrated function.
LEGACY_EXPRESSION = """
SELECT encode(public.digest(jsonb_build_object(
    'tenant',%(t)s::uuid,'snapshot',%(s)s::uuid,'schema',%(schema)s::jsonb - 'privacy',
    'canonical',jsonb_build_object('bucket',(%(src)s::jsonb)->'canonical'->'bucket',
        'key',(%(src)s::jsonb)->'canonical'->'key','version',(%(src)s::jsonb)->'canonical'->'version_id',
        'sha256',(%(src)s::jsonb)->'canonical'->'content_sha256'),
    'normalization',(%(src)s::jsonb)->'normalization_version',
    'profiler',%(v)s::text)::text,'sha256'),'hex')
"""

SHA_A, SHA_B = "a" * 64, "b" * 64
COLUMNS = [
    {"index": 0, "original_name": "id", "name": "id", "type": "STRING", "nullable": True},
    {"index": 1, "original_name": "amount", "name": "amount", "type": "STRING", "nullable": True},
]


def legacy_descriptor(sha: str = SHA_A) -> dict:
    return {
        "bucket": "raw", "key": "snapshots/t/u/source.csv", "version_id": "v1", "content_sha256": sha, "size_bytes": 10,
        "format": "CSV", "normalization_version": 1,
        "canonical": {"bucket": "snap", "key": "snapshots/t/u/canonical.parquet", "version_id": "c1",
                      "content_sha256": sha, "size_bytes": 20, "format": "PARQUET"},
    }


def v2_descriptor(mode: str = "OWNED_RAW") -> dict:
    doc = {
        "descriptor_version": 2, "storage_mode": mode, "bucket": "snap", "key": "snapshots/t/u/source.csv",
        "version_id": "v1", "content_sha256": SHA_A, "size_bytes": 10, "format": "CSV", "normalization_version": 1,
        "normalization": {"version": 1, "format": "CSV", "delimiter": ",", "encoding": "utf-8-sig",
                          "columns": copy.deepcopy(COLUMNS)},
    }
    if mode == "EXTERNAL_VERSION":
        doc.update(source_id="shared", source_binding_sha256=SHA_B)
    return doc


class Seed:
    def __init__(self, conn):
        self.conn, self.n = conn, 0
        self.tenant, self.user, self.asset = uuid4(), uuid4(), uuid4()
        conn.execute("INSERT INTO tenants(tenant_id,tenant_code,tenant_name) VALUES (%s,%s,'Synthetic')",
                     (self.tenant, f"t_{self.tenant.hex[:8]}"))
        conn.execute("INSERT INTO users(user_id,email,password_hash,full_name) VALUES (%s,%s,'x','Synthetic')",
                     (self.user, f"{self.user.hex[:8]}@example.test"))
        conn.execute("INSERT INTO data_assets(asset_id,tenant_id,asset_name,slug,format,owner_user_id,created_by) "
                     "VALUES (%s,%s,'A',%s,'CSV',%s,%s)", (self.asset, self.tenant, f"a{self.asset.hex[:8]}", self.user, self.user))

    def snapshot(self, descriptor: dict, schema: dict | None = None) -> DatasetSnapshot:
        self.n += 1
        sid, schema = uuid4(), schema or {"columns": COLUMNS, "privacy": {"x": 1}}
        self.conn.execute(
            "INSERT INTO dataset_snapshots(snapshot_id,tenant_id,asset_id,version_number,source_kind,source_descriptor,"
            "content_sha256,storage_location,schema_definition,total_rows,total_columns,created_by,captured_at) "
            "VALUES (%s,%s,%s,%s,'OBJECT_FILE',%s,%s,'s3://x/y',%s,2,2,%s,now())",
            (sid, self.tenant, self.asset, self.n, Jsonb(descriptor), hashlib.sha256(str(sid).encode()).hexdigest(),
             Jsonb(schema), self.user))
        return DatasetSnapshot(snapshot_id=sid, tenant_id=self.tenant, asset_id=self.asset, source_kind="OBJECT_FILE",
                               source_descriptor=descriptor, schema_definition=schema, total_rows=2, total_columns=2,
                               captured_at="2026-01-01T00:00:00+00:00")


def fingerprint(conn, tenant, sid, schema, descriptor, version="full-v1"):
    return conn.execute("SELECT snapshot_profile_fingerprint(%s,%s,%s,%s,%s)",
                        (tenant, sid, Jsonb(schema), Jsonb(descriptor), version)).fetchone()[0]


def definitions(conn):
    return {name: conn.execute("SELECT pg_get_functiondef(p.oid) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
                               "WHERE n.nspname='public' AND p.proname=%s", (name,)).fetchone()[0] for name in FUNCTIONS}


def sql_022_functions() -> str:
    start = SQL_022.index("CREATE FUNCTION snapshot_profile_fingerprint")
    mid = SQL_022.index("CREATE TABLE snapshot_profile_jobs")
    tr = SQL_022.index("CREATE FUNCTION enforce_snapshot_profile_transition")
    end = SQL_022.index("CREATE TRIGGER snapshot_profile_transition")
    return (SQL_022[start:mid] + SQL_022[tr:end]).replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION")


@pytest.fixture
def conn(pg_dsn):
    with psycopg.connect(pg_dsn) as connection:
        yield connection
        connection.rollback()


def insert_job(conn, snap, version="full-v1"):
    fp = fingerprint(conn, snap.tenant_id, snap.snapshot_id, snap.schema_definition, snap.source_descriptor, version)
    return conn.execute("INSERT INTO snapshot_profile_jobs(tenant_id,snapshot_id,fingerprint,profiler_version) "
                        "VALUES (%s,%s,%s,%s) RETURNING profile_id", (snap.tenant_id, snap.snapshot_id, fp, version)).fetchone()[0]


def test_legacy_fingerprint_is_byte_identical_to_022_expression(conn):
    seed = Seed(conn)
    snap = seed.snapshot(legacy_descriptor())
    expected = conn.execute(LEGACY_EXPRESSION, {"t": snap.tenant_id, "s": snap.snapshot_id, "schema": Jsonb(snap.schema_definition),
                                                "src": Jsonb(snap.source_descriptor), "v": "full-v1"}).fetchone()[0]
    assert fingerprint(conn, snap.tenant_id, snap.snapshot_id, snap.schema_definition, snap.source_descriptor) == expected
    assert profile_fingerprint(conn, snap) == expected


def test_v2_fingerprint_covers_identity_binding_spec_and_ignores_privacy(conn):
    seed = Seed(conn)
    t, s = seed.tenant, uuid4()
    schema = {"columns": COLUMNS, "privacy": {"a": 1}}

    def fp(doc, sch=schema, version="full-v1"):
        return fingerprint(conn, t, s, sch, doc, version)

    for mode in ("OWNED_RAW", "EXTERNAL_VERSION"):
        base = v2_descriptor(mode)
        assert fp(base) == fp(copy.deepcopy(base))
        assert fp(base, {"columns": COLUMNS, "privacy": {"changed": True}}) == fp(base)
        assert fp(base, {"columns": COLUMNS[:1]}) != fp(base)
        assert fp(base, version="full-v2") != fp(base)
        mutations = {
            "bucket": "other", "key": "snapshots/t/u/other.csv", "version_id": "v2", "content_sha256": SHA_B,
            "size_bytes": 11, "format": "JSONL", "normalization_version": 2, "storage_mode": (
                "EXTERNAL_VERSION" if mode == "OWNED_RAW" else "OWNED_RAW"),
        }
        if mode == "EXTERNAL_VERSION":
            mutations["source_binding_sha256"] = "c" * 64
        for field, value in mutations.items():
            changed = copy.deepcopy(base)
            changed[field] = value
            assert fp(changed) != fp(base), field
        for path, value in (("delimiter", ";"), ("columns", COLUMNS[:1]), ("version", 2)):
            changed = copy.deepcopy(base)
            changed["normalization"][path] = value
            assert fp(changed) != fp(base), path
    # v2 never collides with a legacy descriptor of the same raw identity.
    assert fp(v2_descriptor()) != fp(legacy_descriptor())


def test_python_profile_fingerprint_accepts_legacy_and_valid_v2_only(conn):
    seed = Seed(conn)
    for descriptor in (legacy_descriptor(), v2_descriptor(), v2_descriptor("EXTERNAL_VERSION")):
        snap = seed.snapshot(descriptor)
        assert profile_fingerprint(conn, snap) == fingerprint(
            conn, snap.tenant_id, snap.snapshot_id, snap.schema_definition, descriptor)
    for invalid in invalid_v2_descriptors():
        with pytest.raises(SnapshotProfileError) as error:
            profile_fingerprint(conn, seed.snapshot(invalid))
        assert error.value.code == "SNAPSHOT_REIMPORT_REQUIRED"
    local = seed.snapshot(v2_descriptor()).model_copy(update={"source_kind": "LOCAL_FILE"})
    with pytest.raises(SnapshotProfileError):
        profile_fingerprint(conn, local)


def invalid_v2_descriptors():
    def mutate(mode="OWNED_RAW", **changes):
        doc = v2_descriptor(mode)
        for key, value in changes.items():
            if value is None:
                doc.pop(key, None)
            else:
                doc[key] = value
        return doc

    def spec(**changes):
        doc = v2_descriptor()
        doc["normalization"].update(changes)
        return doc

    yield mutate(descriptor_version=3)
    yield mutate(descriptor_version="2")
    yield mutate(storage_mode="REFERENCE")
    yield mutate(storage_mode=None)
    yield mutate(format="XLSX")
    yield mutate(bucket="")
    yield mutate(key=None)
    yield mutate(version_id="null")
    yield mutate(version_id=None)
    yield mutate(content_sha256="A" * 64)
    yield mutate(content_sha256="a" * 63)
    yield mutate(size_bytes=0)
    yield mutate(size_bytes="10")
    yield mutate(normalization_version=3)
    yield mutate(normalization_version=None)
    yield mutate(normalization=None)
    yield mutate(canonical=legacy_descriptor()["canonical"])
    yield mutate(source_id="shared")  # owned raw must not carry external identity
    yield mutate(source_binding_sha256=SHA_B)
    yield mutate("EXTERNAL_VERSION", source_id="other")
    yield mutate("EXTERNAL_VERSION", source_id=None)
    yield mutate("EXTERNAL_VERSION", source_binding_sha256=None)
    yield mutate("EXTERNAL_VERSION", source_binding_sha256="z" * 64)
    yield spec(version=2)  # != top-level normalization_version
    yield spec(format="JSONL")
    yield spec(encoding="latin-1")
    yield spec(columns=[])
    yield spec(columns={})
    yield spec(columns=[COLUMNS[0]] * 1001)
    yield mutate(extra="x")  # unknown top-level key
    yield mutate("EXTERNAL_VERSION", endpoint_url="https://example.invalid")
    yield spec(extra="x")  # unknown spec key
    yield spec(delimiter="\\")
    yield spec(delimiter=",,")
    yield spec(delimiter=1)
    for bad in (
        {"index": 1},  # not consecutive from 0
        {"index": True},
        {"index": "0"},
        {"original_name": None},
        {"original_name": 1},
        {"name": ""},
        {"name": 1},
        {"type": ""},
        {"type": 1},
        {"nullable": "true"},
        {"nullable": None},
        {"structural_encoding": "XML"},
        {"structural_encoding": "JSON"},  # JSON encoding requires normalization v2 (descriptor is v1)
        {"logical_types": "OBJECT"},
        {"logical_types": [1]},
        {"unexpected": 1},
    ):
        yield spec(columns=[{**COLUMNS[0], **bad}, COLUMNS[1]])
    yield spec(columns=[COLUMNS[0], {**COLUMNS[1], "name": "id"}])  # duplicate output name
    yield spec(columns=[COLUMNS[0], "amount"])  # column is not an object
    yield spec(columns=[COLUMNS[0], {k: v for k, v in COLUMNS[1].items() if k != "nullable"}])
    yield spec(columns=[COLUMNS[0], {k: v for k, v in COLUMNS[1].items() if k != "original_name"}])
    doc = v2_descriptor()
    del doc["normalization"]["columns"]
    yield doc


def test_trigger_admits_legacy_and_valid_v2_and_rejects_invalid_v2(conn):
    seed = Seed(conn)
    for descriptor in (legacy_descriptor(), v2_descriptor(), v2_descriptor("EXTERNAL_VERSION")):
        assert insert_job(conn, seed.snapshot(descriptor))
    for invalid in invalid_v2_descriptors():
        snap = seed.snapshot(invalid)
        with pytest.raises(psycopg.errors.CheckViolation, match="PROFILE_SUBMISSION_INVALID"), conn.transaction():
            conn.execute("INSERT INTO snapshot_profile_jobs(tenant_id,snapshot_id,fingerprint,profiler_version) VALUES (%s,%s,%s,'full-v1')",
                         (snap.tenant_id, snap.snapshot_id, SHA_A))
    # Legacy non-Parquet canonical stays ineligible, and a forged fingerprint is rejected for v2.
    bad_legacy = legacy_descriptor()
    bad_legacy["canonical"]["format"] = "CSV"
    for snap, forged in ((seed.snapshot(bad_legacy), SHA_A), (seed.snapshot(v2_descriptor()), SHA_A)):
        with pytest.raises(psycopg.errors.CheckViolation, match="PROFILE_SUBMISSION_INVALID"), conn.transaction():
            conn.execute("INSERT INTO snapshot_profile_jobs(tenant_id,snapshot_id,fingerprint,profiler_version) VALUES (%s,%s,%s,'full-v1')",
                         (snap.tenant_id, snap.snapshot_id, forged))


def test_v2_job_keeps_lease_and_publication_checks(conn):
    seed = Seed(conn)
    snap = seed.snapshot(v2_descriptor())
    profile_id = insert_job(conn, snap)
    fp = profile_fingerprint(conn, snap)
    conn.execute("UPDATE snapshot_profile_jobs SET state='RUNNING',lease_owner='w',lease_generation=1,attempt_count=1,"
                 "lease_expires_at=clock_timestamp()+interval '1 hour' WHERE profile_id=%s", (profile_id,))
    with pytest.raises(psycopg.errors.CheckViolation, match="PROFILE_RESULT_INVALID"), conn.transaction():
        conn.execute("UPDATE snapshot_profile_jobs SET state='COMPLETE',finished_at=now(),result=%s WHERE profile_id=%s",
                     (Jsonb({"mode": "SAMPLE"}), profile_id))
    result = {"mode": "FULL", "profile_id": str(profile_id), "fingerprint": fp, "profiler_version": "full-v1",
              "scanned_rows": 2, "total_rows": 2}
    conn.execute("UPDATE snapshot_profile_jobs SET state='COMPLETE',finished_at=now(),result=%s WHERE profile_id=%s",
                 (Jsonb(result), profile_id))
    with pytest.raises(psycopg.errors.CheckViolation, match="PROFILE_IMMUTABLE"), conn.transaction():
        conn.execute("UPDATE snapshot_profile_jobs SET state='QUEUED' WHERE profile_id=%s", (profile_id,))


def test_down_restores_exact_022_definitions_and_up_is_reapplicable(conn):
    current = definitions(conn)
    conn.execute(DOWN)
    restored = definitions(conn)
    assert restored != current
    conn.execute(sql_022_functions())
    assert definitions(conn) == restored  # down body is exactly the 022 text, attributes included
    assert conn.execute("SELECT to_regprocedure('snapshot_source_is_profileable(jsonb)')").fetchone()[0] is None
    assert conn.execute("SELECT to_regprocedure('snapshot_v2_columns_valid(jsonb,jsonb)')").fetchone()[0] is None
    attributes = conn.execute(
        "SELECT proname,provolatile,proisstrict,proconfig FROM pg_proc WHERE proname = ANY(%s) ORDER BY proname",
        (list(FUNCTIONS),)).fetchall()
    assert attributes == [("enforce_snapshot_profile_transition", "v", False, ["search_path=pg_catalog, public"]),
                          ("snapshot_profile_fingerprint", "i", True, ["search_path=pg_catalog, public"])]
    conn.execute(UP)
    assert definitions(conn) == current
    conn.rollback()
    assert definitions(conn) == current


def test_down_and_reup_preserve_legacy_data_fingerprints_and_complete_profiles(conn):
    seed = Seed(conn)
    snap = seed.snapshot(legacy_descriptor())
    profile_id = insert_job(conn, snap)
    fp = profile_fingerprint(conn, snap)
    conn.execute("UPDATE snapshot_profile_jobs SET state='RUNNING',lease_owner='w',lease_generation=1,attempt_count=1,"
                 "lease_expires_at=clock_timestamp()+interval '1 hour' WHERE profile_id=%s", (profile_id,))
    result = {"mode": "FULL", "profile_id": str(profile_id), "fingerprint": fp, "profiler_version": "full-v1",
              "scanned_rows": 2, "total_rows": 2}
    conn.execute("UPDATE snapshot_profile_jobs SET state='COMPLETE',finished_at=now(),result=%s WHERE profile_id=%s",
                 (Jsonb(result), profile_id))
    query = ("SELECT j.profile_id,j.fingerprint,j.state,j.result,s.source_descriptor::text,s.schema_definition::text,s.content_sha256 "
             "FROM snapshot_profile_jobs j JOIN dataset_snapshots s USING (tenant_id,snapshot_id) WHERE j.profile_id=%s")
    before = conn.execute(query, (profile_id,)).fetchone()
    conn.execute(DOWN)
    assert conn.execute(query, (profile_id,)).fetchone() == before
    assert fingerprint(conn, snap.tenant_id, snap.snapshot_id, snap.schema_definition, snap.source_descriptor) == fp
    conn.execute(UP)
    assert conn.execute(query, (profile_id,)).fetchone() == before
    assert profile_fingerprint(conn, snap) == fp == before[1]


@pytest.mark.parametrize("mode", ["OWNED_RAW", "EXTERNAL_VERSION"])
def test_down_refuses_when_any_v2_snapshot_exists_and_changes_nothing(pg_dsn, mode):
    with psycopg.connect(pg_dsn) as setup:
        seed = Seed(setup)
        snap = seed.snapshot(v2_descriptor(mode))
        profile_id = insert_job(setup, snap)
        setup.commit()
    try:
        with psycopg.connect(pg_dsn) as conn:
            current = definitions(conn)
            with pytest.raises(psycopg.errors.RaiseException, match="SINGLE_SOURCE_SNAPSHOTS_IN_USE"):
                conn.execute(DOWN)
            conn.rollback()
            assert definitions(conn) == current
            assert conn.execute("SELECT to_regprocedure('snapshot_source_is_profileable(jsonb)')").fetchone()[0] is not None
            assert conn.execute("SELECT count(*) FROM snapshot_profile_jobs WHERE profile_id=%s", (profile_id,)).fetchone()[0] == 1
            assert conn.execute("SELECT source_descriptor FROM dataset_snapshots WHERE snapshot_id=%s",
                                (snap.snapshot_id,)).fetchone()[0] == snap.source_descriptor
    finally:
        with psycopg.connect(pg_dsn) as cleanup:
            cleanup.execute("TRUNCATE tenants, users CASCADE")
            cleanup.commit()


def test_down_takes_table_lock_before_checking_for_v2(pg_dsn):
    with psycopg.connect(pg_dsn) as holder, psycopg.connect(pg_dsn) as downer:
        holder.execute("LOCK TABLE snapshot_profile_jobs IN ROW EXCLUSIVE MODE")
        downer.execute("SET lock_timeout='300ms'")
        with pytest.raises(psycopg.errors.LockNotAvailable):
            downer.execute(DOWN)
        downer.rollback()
        holder.rollback()


UP_025 = (DEFAULT_MIGRATIONS_DIR / "025_evaluation_reuse.sql").read_text(encoding="utf-8")
DOWN_025 = (DEFAULT_MIGRATIONS_DIR / "025_evaluation_reuse_down.sql").read_text(encoding="utf-8")


def _insert_legacy_run(conn, seed, snap):
    ruleset, policy, run = uuid4(), uuid4(), uuid4()
    conn.execute("INSERT INTO rulesets(ruleset_id,tenant_id,asset_id,version,config_hash,status,created_by) "
                 "VALUES(%s,%s,%s,'v1','r','DRAFT',%s)", (ruleset, seed.tenant, seed.asset, seed.user))
    conn.execute("INSERT INTO scoring_policies(policy_id,tenant_id,version,config_hash,status,created_by,dimension_weights,"
                 "publication_threshold,gate_rules) VALUES(%s,%s,'v1','p','DRAFT',%s,'{}',0.8,'{}')",
                 (policy, seed.tenant, seed.user))
    conn.execute("INSERT INTO evaluation_runs(run_id,tenant_id,snapshot_id,ruleset_id,policy_id,idempotency_key,outlier_config,"
                 "outlier_config_hash,run_status,created_by) VALUES(%s,%s,%s,%s,%s,%s,'{}','legacy-hash','SUCCEEDED',%s)",
                 (run, seed.tenant, snap.snapshot_id, ruleset, policy, str(run), seed.user))
    return run


def test_025_down_and_reup_keep_legacy_runs_and_hashes(conn):
    seed = Seed(conn)
    snap = seed.snapshot(legacy_descriptor())
    run = _insert_legacy_run(conn, seed, snap)
    fp = profile_fingerprint(conn, snap)
    query = "SELECT outlier_config::text,outlier_config_hash,run_status FROM evaluation_runs WHERE run_id=%s"
    before = conn.execute(query, (run,)).fetchone()
    assert conn.execute("SELECT evaluation_fingerprint FROM evaluation_runs WHERE run_id=%s", (run,)).fetchone() == (None,)
    conn.execute(DOWN_025)
    assert conn.execute("SELECT to_regclass('idx_runs_completed_evaluation_fingerprint')").fetchone()[0] is None
    assert not conn.execute("SELECT 1 FROM information_schema.columns WHERE table_name='evaluation_runs' "
                            "AND column_name='evaluation_fingerprint'").fetchone()
    assert conn.execute(query, (run,)).fetchone() == before
    assert profile_fingerprint(conn, snap) == fp
    conn.execute(DOWN)  # legacy-only data: 024 down still allowed after 025 down
    conn.execute(UP)
    conn.execute(UP_025)
    assert conn.execute(query, (run,)).fetchone() == before
    assert profile_fingerprint(conn, snap) == fp


def test_025_rejects_non_sha256_fingerprint(conn):
    seed = Seed(conn)
    run = _insert_legacy_run(conn, seed, seed.snapshot(legacy_descriptor()))
    with pytest.raises(psycopg.errors.CheckViolation), conn.transaction():
        conn.execute("UPDATE evaluation_runs SET evaluation_fingerprint='nope' WHERE run_id=%s", (run,))


def test_down_024_still_blocked_by_v2_after_025(pg_dsn):
    with psycopg.connect(pg_dsn) as setup:
        Seed(setup).snapshot(v2_descriptor())
        setup.commit()
    try:
        with psycopg.connect(pg_dsn) as conn:
            conn.execute(DOWN_025)
            with pytest.raises(psycopg.errors.RaiseException, match="SINGLE_SOURCE_SNAPSHOTS_IN_USE"):
                conn.execute(DOWN)
            conn.rollback()
    finally:
        with psycopg.connect(pg_dsn) as cleanup:
            cleanup.execute("TRUNCATE tenants, users CASCADE")
            cleanup.commit()
