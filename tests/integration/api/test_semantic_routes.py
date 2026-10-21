import json
from uuid import uuid4

import psycopg
import pytest

from dq_scoring.adapters.llm import semantic_adapter
from dq_scoring.adapters.llm.gateway_client import AiError, GatewayReply
from dq_scoring.adapters.llm.gateway_settings import (
    LlmSettings,
    LocalLlmSettings,
    get_llm_settings,
    get_local_llm_settings,
)
from tests.integration.api.test_privacy_routes import (  # noqa: F401
    _seed_asset_and_snapshot,
    org,
)
from tests.integration.conftest import _login

SENTINEL_NAME = "SentinelOriginalName"
COLUMNS = [{"name": "id", "type": "STRING"}, {"name": "email", "type": "STRING"}, {"name": SENTINEL_NAME, "type": "STRING"}]
STAT = {"sample_rows": 10, "type_hint": "STRING", "null_count": 0, "non_null_count": 10, "distinct_count": 10, "parse_success_count": 10}
PROFILE = {"sample_rows": 10, "is_sample": True, "columns": [{"name": c["name"], **STAT} for c in COLUMNS]}


def _settings(cls, enabled=True):
    return cls(_env_file=None, enabled=enabled, endpoint="https://synthetic.test/v1/chat/completions", model="synthetic-pinned", api_key="synthetic")


@pytest.fixture
def providers(client):
    client.app.dependency_overrides[get_llm_settings] = lambda: _settings(LlmSettings)
    client.app.dependency_overrides[get_local_llm_settings] = lambda: _settings(LocalLlmSettings)
    yield
    client.app.dependency_overrides.pop(get_llm_settings, None)
    client.app.dependency_overrides.pop(get_local_llm_settings, None)


@pytest.fixture
def snap(db_conn, org):  # noqa: F811
    _, snapshot, _ = _seed_asset_and_snapshot(db_conn, org["tenant_id"], org["owner"][0], columns=COLUMNS, preview=[], profile=PROFILE)
    db_conn.commit()
    return snapshot


@pytest.fixture
def gateway(monkeypatch):
    """Captures what would cross the wire; settings identify which provider was called."""
    calls = []

    async def fake(settings, system, user):
        calls.append((type(settings).__name__, user))
        tokens = [c["token"] for c in json.loads(user)["columns"]]
        return GatewayReply(json.dumps({"labels": [{"token": t, "label": "IDENTIFIER"} for t in tokens]}), "synthetic-pinned")

    monkeypatch.setattr(semantic_adapter, "complete_json", fake)
    return calls


def url(snapshot, tail=""):
    return f"/api/v1/snapshots/{snapshot}/semantics{tail}"


def put(client, org, snapshot, changes, revision=0, role="owner"):  # noqa: F811
    headers = _login(client, org[role][1], org["tenant_id"])
    return client.put(url(snapshot), headers=headers, json={"expected_revision": revision, "reason": "synthetic business review", "changes": changes})


def infer(client, org, snapshot, provider, role="owner"):  # noqa: F811
    headers = _login(client, org[role][1], org["tenant_id"])
    return client.post(url(snapshot, "/infer"), headers=headers, json={"provider": provider, "profile_mode": "SAMPLE"})


def test_manual_confirm_works_with_providers_off_and_get_never_calls_gateway(client, org, snap, gateway):  # noqa: F811
    client.app.dependency_overrides[get_llm_settings] = lambda: LlmSettings(_env_file=None)
    client.app.dependency_overrides[get_local_llm_settings] = lambda: LocalLlmSettings(_env_file=None)
    headers = _login(client, org["owner"][1], org["tenant_id"])
    before = client.get(url(snap), headers=headers)
    assert before.status_code == 200, before.text
    assert before.json()["revision"] == 0 and all(c["confirmed"] is None for c in before.json()["columns"])
    assert put(client, org, snap, [{"column": "id", "label": "IDENTIFIER"}]).status_code == 200
    after = client.get(url(snap), headers=headers).json()
    assert after["revision"] == 1
    assert {c["column"]: c["confirmed"] and c["confirmed"]["label"] for c in after["columns"]}["id"] == "IDENTIFIER"
    assert infer(client, org, snap, "LOCAL").status_code == 503 and infer(client, org, snap, "API").status_code == 503
    assert gateway == []
    client.app.dependency_overrides.pop(get_llm_settings)
    client.app.dependency_overrides.pop(get_local_llm_settings)


def test_put_conflict_invalid_column_roles_and_atomic_history(client, org, snap, db_conn):  # noqa: F811
    assert put(client, org, snap, [{"column": "id", "label": "IDENTIFIER"}]).status_code == 200
    stale = put(client, org, snap, [{"column": "id", "label": "CATEGORY"}], revision=0)
    assert stale.status_code == 409 and stale.json()["detail"] == "SEMANTIC_REVISION_CONFLICT"
    invalid = put(client, org, snap, [{"column": "id", "label": "MONEY"}, {"column": "missing", "label": "MONEY"}], revision=1)
    assert invalid.status_code == 422 and invalid.json()["detail"] == "SEMANTIC_COLUMN_INVALID"
    assert put(client, org, snap, [{"column": "id", "label": "NOT_A_LABEL"}], revision=1).status_code == 422
    assert put(client, org, snap, [{"column": "id", "label": "MONEY"}], revision=1, role="viewer").status_code == 403
    assert put(client, org, uuid4(), [{"column": "id", "label": "MONEY"}], revision=1).status_code == 404
    assert db_conn.execute("SELECT label,revision FROM snapshot_column_semantics WHERE snapshot_id=%s", (snap,)).fetchall() == [("IDENTIFIER", 1)]
    db_conn.commit()
    assert put(client, org, snap, [{"column": "id", "label": None}], revision=1).json()["revision"] == 2
    rows = db_conn.execute(
        "SELECT revision,action,label,previous_label FROM snapshot_column_semantic_history WHERE snapshot_id=%s ORDER BY revision", (snap,)
    ).fetchall()
    assert rows == [(1, "CONFIRM", "IDENTIFIER", None), (2, "RESET", None, "IDENTIFIER")]
    db_conn.commit()
    with pytest.raises(psycopg.Error):
        db_conn.execute("UPDATE snapshot_column_semantic_history SET label='MONEY' WHERE snapshot_id=%s", (snap,))
    db_conn.rollback()


def test_cross_tenant_read_and_write_are_not_found(client, org, snap, db_conn):  # noqa: F811
    other = uuid4()
    db_conn.execute("INSERT INTO tenants(tenant_id,tenant_code,tenant_name) VALUES(%s,%s,'Other synthetic tenant')", (other, "sem_" + other.hex))
    db_conn.execute("INSERT INTO tenant_memberships(tenant_id,user_id,role,status) VALUES(%s,%s,'DATA_OWNER','ACTIVE')", (other, org["owner"][0]))
    db_conn.commit()
    headers = _login(client, org["owner"][1], other)
    assert client.get(url(snap), headers=headers).status_code == 404
    response = client.put(url(snap), headers=headers, json={"expected_revision": 0, "reason": "x", "changes": [{"column": "id", "label": "MONEY"}]})
    assert response.status_code == 404


def test_app_login_cannot_forge_revision_or_cross_tenant_rows(non_superuser_dsn, org, snap):  # noqa: F811
    with psycopg.connect(non_superuser_dsn) as conn:
        conn.execute("SET LOCAL ROLE dq_app_role")
        conn.execute("SELECT set_config('app.current_tenant_id', %s, true)", (str(uuid4()),))
        assert conn.execute("SELECT count(*) FROM snapshot_semantic_state").fetchone()[0] == 0
        with pytest.raises(psycopg.Error):
            conn.execute("INSERT INTO snapshot_semantic_state(tenant_id,snapshot_id) VALUES(%s,%s)", (org["tenant_id"], snap))
    with psycopg.connect(non_superuser_dsn) as conn:
        conn.execute("SET LOCAL ROLE dq_app_role")
        conn.execute("SELECT set_config('app.current_tenant_id', %s, true)", (str(org["tenant_id"]),))
        conn.execute("INSERT INTO snapshot_semantic_state(tenant_id,snapshot_id) VALUES(%s,%s)", (org["tenant_id"], snap))
        with pytest.raises(psycopg.Error):
            conn.execute("UPDATE snapshot_semantic_state SET revision=5 WHERE snapshot_id=%s", (snap,))


def test_api_payload_has_only_confirmed_unprotected_tokens(client, org, snap, providers, gateway):  # noqa: F811
    none = infer(client, org, snap, "API")
    assert none.status_code == 422 and none.json()["detail"] == "AI_NO_ELIGIBLE_COLUMNS"
    assert gateway == []
    assert put(client, org, snap, [{"column": "email", "label": "EMAIL"}, {"column": SENTINEL_NAME, "label": "CATEGORY"}]).status_code == 200
    response = infer(client, org, snap, "API")
    assert response.status_code == 200, response.text
    (provider, payload), = gateway
    assert provider == "LlmSettings"
    columns = json.loads(payload)["columns"]
    assert [c["semantic"] for c in columns] == ["CATEGORY"]
    for forbidden in (SENTINEL_NAME, "email", "reason", "synthetic business review"):
        assert forbidden not in payload
    body = response.json()
    assert body["candidates"] == [{"column": SENTINEL_NAME, "label": "IDENTIFIER", "reason_codes": ["MODEL_SUGGESTION"], "source": "API"}]
    prov = body["provenance"]
    assert prov["provider"] == "API" and prov["columns_sent"] == 1
    assert isinstance(prov["semantic_revision"], int) and prov["semantic_revision"] >= 1
    assert isinstance(prov["privacy_policy_version"], int) and prov["vocabulary_version"] == "dq-semantic-v1"
    assert "profiler_version" in prov["profile"]


def test_local_payload_has_names_but_no_values_and_failure_never_uses_api(client, org, snap, providers, gateway, monkeypatch):  # noqa: F811
    response = infer(client, org, snap, "LOCAL")
    assert response.status_code == 200, response.text
    provider, payload = gateway[0]
    assert provider == "LocalLlmSettings" and "id" in payload and "email" not in payload and "min" not in payload
    gateway.clear()

    async def failing(settings, system, user):
        gateway.append((type(settings).__name__, user))
        raise AiError("AI_UNAVAILABLE")

    monkeypatch.setattr(semantic_adapter, "complete_json", failing)
    failed = infer(client, org, snap, "LOCAL")
    assert failed.status_code == 503 and failed.json()["detail"] == "AI_UNAVAILABLE"
    assert [name for name, _ in gateway] == ["LocalLlmSettings"]


def test_inference_never_persists_candidates(client, org, snap, providers, gateway, db_conn):  # noqa: F811
    assert infer(client, org, snap, "LOCAL").status_code == 200
    assert db_conn.execute("SELECT count(*) FROM snapshot_column_semantics").fetchone()[0] == 0
    db_conn.commit()


def test_unauthorized_and_missing_snapshot_never_reach_gateway(client, org, snap, providers, gateway):  # noqa: F811
    assert infer(client, org, snap, "LOCAL", role="viewer").status_code == 403
    assert infer(client, org, uuid4(), "LOCAL").status_code == 404
    assert gateway == []


@pytest.mark.parametrize("change", ["semantic", "privacy", "membership"])
def test_context_change_during_inference_is_stale(client, org, snap, providers, monkeypatch, db_conn, change):  # noqa: F811
    async def changed(settings, system, user):
        if change == "semantic":
            db_conn.execute("INSERT INTO snapshot_semantic_state(tenant_id,snapshot_id,revision) VALUES(%s,%s,0)", (org["tenant_id"], snap))
            db_conn.execute("UPDATE snapshot_semantic_state SET revision=1 WHERE snapshot_id=%s", (snap,))
            db_conn.execute(
                "INSERT INTO snapshot_column_semantic_history(tenant_id,snapshot_id,revision,column_name,action,label,actor_user_id,reason) "
                "VALUES(%s,%s,1,'id','CONFIRM','MONEY',%s,'synthetic')", (org["tenant_id"], snap, org["owner"][0]))
            db_conn.execute(
                "INSERT INTO snapshot_column_semantics(tenant_id,snapshot_id,column_name,label,revision,updated_by,reason) "
                "VALUES(%s,%s,'id','MONEY',1,%s,'synthetic')", (org["tenant_id"], snap, org["owner"][0]))
        elif change == "privacy":
            asset = db_conn.execute("SELECT asset_id FROM dataset_snapshots WHERE snapshot_id=%s", (snap,)).fetchone()[0]
            db_conn.execute("INSERT INTO asset_protection_revisions(tenant_id,asset_id,version) VALUES(%s,%s,1)", (org["tenant_id"], asset))
        else:
            db_conn.execute("UPDATE tenant_memberships SET status='SUSPENDED' WHERE user_id=%s", (org["owner"][0],))
        db_conn.commit()
        return GatewayReply('{"labels":[]}', "synthetic-pinned")

    monkeypatch.setattr(semantic_adapter, "complete_json", changed)
    response = infer(client, org, snap, "LOCAL")
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "AI_CONTEXT_STALE"


@pytest.mark.parametrize("field", ["profile_id", "fingerprint"])
def test_full_profile_identity_change_during_inference_is_stale(client, org, snap, providers, gateway, monkeypatch, field):  # noqa: F811
    from dq_scoring.presentation.api.routes import asset_routes

    original = asset_routes._semantic_data
    loads = 0
    identity = {"profile_id": str(uuid4()), "fingerprint": "a" * 64}
    replacement = str(uuid4()) if field == "profile_id" else "f" * 64

    def changed(*args):
        nonlocal loads
        data = original(*args)
        loads += 1
        profile = {**data["profile"], "mode": "FULL", "is_sample": False, **identity}
        if loads > 1:
            profile[field] = replacement
        return {**data, "profile": profile}

    monkeypatch.setattr(asset_routes, "_semantic_data", changed)
    response = infer(client, org, snap, "LOCAL")
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "AI_CONTEXT_STALE"
    assert len(gateway) == 1


def test_no_database_transaction_is_held_during_gateway_await(client, org, snap, providers, monkeypatch, db_conn):  # noqa: F811
    counts = []

    async def reply(*args):
        counts.append(db_conn.execute(
            "SELECT count(*) FROM pg_stat_activity WHERE pg_has_role(usename, 'dq_app_role', 'member') "
            "AND datname=current_database() AND state IN ('idle in transaction','idle in transaction (aborted)')"
        ).fetchone()[0])
        db_conn.rollback()
        return GatewayReply('{"labels":[]}', "synthetic-pinned")

    monkeypatch.setattr(semantic_adapter, "complete_json", reply)
    response = infer(client, org, snap, "LOCAL")
    assert response.status_code == 200, response.text
    assert counts == [0]


def _app(dsn, tenant):
    conn = psycopg.connect(dsn)
    conn.execute("SET LOCAL ROLE dq_app_role")
    conn.execute("SELECT set_config('app.current_tenant_id', %s, true)", (str(tenant),))
    return conn


def _history(conn, tenant, snap, revision, actor, column="id", action="CONFIRM", label="MONEY"):
    conn.execute(
        "INSERT INTO snapshot_column_semantic_history(tenant_id,snapshot_id,revision,column_name,action,label,actor_user_id,reason) "
        "VALUES(%s,%s,%s,%s,%s,%s,%s,'synthetic')", (tenant, snap, revision, column, action, label, actor))


def _project(conn, tenant, snap, revision, actor, label="MONEY"):
    conn.execute(
        "INSERT INTO snapshot_column_semantics(tenant_id,snapshot_id,column_name,label,revision,updated_by,reason) "
        "VALUES(%s,%s,'id',%s,%s,%s,'synthetic')", (tenant, snap, label, revision, actor))


def test_direct_sql_cannot_forge_semantic_state(non_superuser_dsn, client, org, snap):  # noqa: F811
    tenant, owner, viewer = org["tenant_id"], org["owner"][0], org["viewer"][0]
    bump = "UPDATE snapshot_semantic_state SET revision=revision+1 WHERE snapshot_id=%s"
    insert_state = "INSERT INTO snapshot_semantic_state(tenant_id,snapshot_id) VALUES(%s,%s)"

    conn = _app(non_superuser_dsn, tenant)
    conn.execute(insert_state, (tenant, snap))
    conn.execute(bump, (snap,))
    with pytest.raises(psycopg.Error):
        conn.commit()
    conn.close()

    conn = _app(non_superuser_dsn, tenant)
    conn.execute(insert_state, (tenant, snap))
    conn.execute(bump, (snap,))
    _project(conn, tenant, snap, 1, owner)
    with pytest.raises(psycopg.Error):
        conn.commit()
    conn.close()

    for revision, actor in ((1, viewer), (1, uuid4()), (2, owner)):
        conn = _app(non_superuser_dsn, tenant)
        conn.execute(insert_state, (tenant, snap))
        conn.execute(bump, (snap,))
        with pytest.raises(psycopg.Error):
            _history(conn, tenant, snap, revision, actor)
        conn.close()

    assert put(client, org, snap, [{"column": "id", "label": "IDENTIFIER"}]).status_code == 200
    conn = _app(non_superuser_dsn, tenant)
    conn.execute("DELETE FROM snapshot_column_semantics WHERE snapshot_id=%s", (snap,))
    with pytest.raises(psycopg.Error):
        conn.commit()
    conn.close()
    assert put(client, org, snap, [{"column": "id", "label": None}], revision=1).status_code == 200
