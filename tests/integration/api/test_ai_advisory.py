from uuid import uuid4

import pytest

from dq_scoring.adapters.llm.gateway_client import AiError, GatewayReply
from dq_scoring.adapters.llm.gateway_settings import LlmSettings, get_llm_settings
from tests.integration.api.test_privacy_routes import (  # noqa: F401
    _seed_asset_and_snapshot,
    org,
)
from tests.integration.conftest import _login


@pytest.fixture
def enabled(client):
    settings = LlmSettings(_env_file=None, enabled=True, endpoint='https://synthetic.test/v1/chat/completions', model='synthetic-pinned', api_key='synthetic')
    client.app.dependency_overrides[get_llm_settings] = lambda: settings
    yield settings
    client.app.dependency_overrides.pop(get_llm_settings, None)


@pytest.fixture
def snapshot(db_conn, org):  # noqa: F811
    profile = {'sample_rows': 10, 'is_sample': True, 'columns': [{'name': 'id', 'sample_rows': 10, 'type_hint': 'STRING', 'null_count': 0, 'non_null_count': 10, 'distinct_count': 10, 'parse_success_count': 10}]}
    asset, snap, _ = _seed_asset_and_snapshot(db_conn, org['tenant_id'], org['owner'][0], preview=[{'id':'synthetic','email':'[REDACTED]'}], profile=profile)
    db_conn.commit()
    return asset, snap


def request(client, org, snap, role='owner', engine='LLM'):  # noqa: F811
    headers = _login(client, org[role][1], org['tenant_id'])
    return client.post(f'/api/v1/snapshots/{snap}/recommendations/ai', headers=headers, json={'engine':engine,'domain':'GENERAL','priorities':['COMPLETENESS','UNIQUENESS']})


def test_advisory_disabled_does_not_break_heuristic(client, org, snapshot):  # noqa: F811
    client.app.dependency_overrides[get_llm_settings] = lambda: LlmSettings(_env_file=None)
    _, snap = snapshot
    headers = _login(client, org['owner'][1], org['tenant_id'])
    assert client.get('/api/v1/ai/status', headers=headers).json()['enabled'] is False
    assert client.get(f'/api/v1/snapshots/{snap}/recommendations', headers=headers).status_code == 200
    assert request(client, org, snap).status_code == 503
    client.app.dependency_overrides.pop(get_llm_settings)


def test_advisory_validates_local_mapping_and_hybrid_fallback(client, org, snapshot, enabled, monkeypatch):  # noqa: F811
    from dq_scoring.services import ai_recommendation_service as service
    async def reply(settings, context):
        assert context.columns[0].token == 'c000'
        return GatewayReply('{"candidates":[{"token":"c000","rule_type":"NON_NULL","null_policy":"fail"}]}', 'synthetic-pinned'), ''
    monkeypatch.setattr(service, 'request_candidates', reply)
    response = request(client, org, snapshot[1])
    assert response.status_code == 200, response.text
    rule = response.json()['rules'][0]['rule']
    assert rule['parameters'] == {'column':'id'}
    assert rule['is_required'] is False and rule['is_critical'] is False
    async def unavailable(*args):
        raise AiError('AI_TIMEOUT')
    monkeypatch.setattr(service, 'request_candidates', unavailable)
    fallback = request(client, org, snapshot[1], engine='HYBRID')
    assert fallback.status_code == 200, fallback.text
    assert fallback.json()['provenance']['source'] == 'HEURISTIC_FALLBACK'
    assert request(client, org, snapshot[1]).status_code == 504


def test_advisory_denies_viewer_missing_resource_and_stale_scan_before_gateway(client, org, snapshot, enabled, monkeypatch, db_conn):  # noqa: F811
    from dq_scoring.services import ai_recommendation_service as service
    async def forbidden(*args):
        pytest.fail('unauthorized or stale request reached gateway')
    monkeypatch.setattr(service, 'request_candidates', forbidden)
    assert request(client, org, snapshot[1], role='viewer').status_code == 403
    assert request(client, org, uuid4()).status_code == 404
    other_tenant = uuid4()
    db_conn.execute("INSERT INTO tenants(tenant_id,tenant_code,tenant_name) VALUES(%s,%s,'Other synthetic tenant')", (other_tenant, 'ai_' + other_tenant.hex))
    db_conn.execute("INSERT INTO tenant_memberships(tenant_id,user_id,role,status) VALUES(%s,%s,'DATA_OWNER','ACTIVE')", (other_tenant, org['owner'][0]))
    db_conn.commit()
    other_headers = _login(client, org['owner'][1], other_tenant)
    other_response = client.post(f'/api/v1/snapshots/{snapshot[1]}/recommendations/ai', headers=other_headers, json={'engine': 'LLM', 'domain': 'GENERAL', 'priorities': ['COMPLETENESS']})
    assert other_response.status_code == 404
    _, pending, _ = _seed_asset_and_snapshot(db_conn, org['tenant_id'], org['owner'][0], with_findings=False, preview=[], profile={})
    db_conn.commit()
    assert request(client, org, pending).status_code == 409


def test_policy_change_during_inference_discards_result(client, org, snapshot, enabled, monkeypatch, db_conn):  # noqa: F811
    from dq_scoring.services import ai_recommendation_service as service
    async def changed(*args):
        db_conn.execute("INSERT INTO asset_protection_revisions(tenant_id,asset_id,version) VALUES(%s,%s,1)", (org['tenant_id'],snapshot[0]))
        db_conn.commit()
        return GatewayReply('{"candidates":[]}', 'synthetic-pinned'), ''
    monkeypatch.setattr(service, 'request_candidates', changed)
    response = request(client, org, snapshot[1])
    assert response.status_code == 409, response.text

def test_narrative_persists_separately_without_mutating_assessment(client, org, snapshot, enabled, monkeypatch, db_conn):  # noqa: F811
    from dq_scoring.services import assessment_report_service as service
    tenant, user = org['tenant_id'], org['owner'][0]
    asset, snap = snapshot
    ruleset, policy, run, assessment = (uuid4() for _ in range(4))
    db_conn.execute("INSERT INTO rulesets(ruleset_id,tenant_id,asset_id,version,config_hash,status,created_by) VALUES(%s,%s,%s,'v1','r','DRAFT',%s)", (ruleset,tenant,asset,user))
    db_conn.execute("INSERT INTO scoring_policies(policy_id,tenant_id,version,config_hash,status,created_by,dimension_weights,publication_threshold,gate_rules) VALUES(%s,%s,'v1','p','DRAFT',%s,'{}',0.8,'{}')", (policy,tenant,user))
    db_conn.execute("INSERT INTO evaluation_runs(run_id,tenant_id,snapshot_id,ruleset_id,policy_id,idempotency_key,outlier_config,outlier_config_hash,run_status,created_by) VALUES(%s,%s,%s,%s,%s,%s,'{}','o','SUCCEEDED',%s)", (run,tenant,snap,ruleset,policy,str(run),user))
    db_conn.execute("INSERT INTO assessments(assessment_id,tenant_id,run_id,snapshot_id,dq_score,publication_status,visibility_scope,coverage_ratio,confidence_status,quality_gate,config_hashes,assessment_hash,published_at) VALUES(%s,%s,%s,%s,50,'PUBLISHED','PRIVATE',1,'VERIFIED','FAIL','{}','synthetic-immutable',now())", (assessment,tenant,run,snap))
    db_conn.commit()
    async def reply(*args):
        return GatewayReply('{"narrative":"Review measured quality rules.","cited_rules":[]}', 'synthetic-pinned')
    monkeypatch.setattr(service, 'complete_json', reply)
    headers = _login(client, org['owner'][1], tenant)
    url = f'/api/v1/assessments/{assessment}/narrative'
    assert client.get(url, headers=headers).status_code == 404
    created = client.post(url, headers=headers)
    assert created.status_code == 201, created.text
    report = client.get(url, headers=headers)
    assert report.status_code == 200, report.text
    assert report.json()['report_id'] == created.json()['report_id']
    assert report.json()['narrative'] == 'Review measured quality rules.'
    assert db_conn.execute('SELECT dq_score,coverage_ratio,quality_gate,assessment_hash FROM assessments WHERE assessment_id=%s', (assessment,)).fetchone() == (50,1,'FAIL','synthetic-immutable')
    db_conn.commit()
    repeated = client.post(url, headers=headers)
    assert repeated.status_code == 201, repeated.text
    assert repeated.json()['report_id'] != created.json()['report_id']
    viewer = _login(client, org['viewer'][1], tenant)
    assert client.post(url, headers=viewer).status_code == 403
    async def unavailable(*args):
        raise AiError('AI_UNAVAILABLE')
    monkeypatch.setattr(service, 'complete_json', unavailable)
    assert client.post(url, headers=headers).status_code == 503
    assert client.get(url, headers=headers).json()['report_id'] == repeated.json()['report_id']
    async def changed(*args):
        db_conn.execute('INSERT INTO asset_protection_revisions(tenant_id,asset_id,version) VALUES(%s,%s,1)', (tenant, asset))
        db_conn.commit()
        return GatewayReply('{"narrative":"Outdated advisory.","cited_rules":[]}', 'synthetic-pinned')
    monkeypatch.setattr(service, 'complete_json', changed)
    assert client.post(url, headers=headers).status_code == 409
    assert db_conn.execute('SELECT count(*) FROM assessment_narratives WHERE assessment_id=%s', (assessment,)).fetchone()[0] == 2
    db_conn.commit()
