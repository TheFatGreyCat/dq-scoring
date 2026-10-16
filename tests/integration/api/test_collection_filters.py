"""Collection counts, literal search and stable paging stay tenant-scoped."""
from uuid import uuid4

import pytest

from dq_scoring.presentation.api.auth import AuthenticatedUser, create_access_token
from dq_scoring.presentation.api.config import get_api_settings


def test_asset_paging_literal_search_and_tenant_count(client, db_conn):
    tenant, foreign, user = uuid4(), uuid4(), uuid4()
    with db_conn.cursor() as cur:
        for identifier in (tenant, foreign):
            cur.execute("INSERT INTO tenants(tenant_id,tenant_code,tenant_name) VALUES (%s,%s,'Synthetic')", (identifier, identifier.hex))
        cur.execute("INSERT INTO users(user_id,email,password_hash,full_name) VALUES (%s,%s,'synthetic','Synthetic')", (user, f'{user}@example.test'))
        for identifier in (tenant, foreign):
            for i in range(6):
                cur.execute("INSERT INTO data_assets(asset_id,tenant_id,asset_name,slug,format,owner_user_id,created_by) VALUES (%s,%s,%s,%s,'CSV',%s,%s)", (uuid4(), identifier, f'literal_% item {i}', uuid4().hex, user, user))
    db_conn.commit()
    identity = AuthenticatedUser(user_id=user, tenant_id=tenant, email=f'{user}@example.test', role='DATA_ENGINEER')
    headers = {'Authorization': f'Bearer {create_access_token(identity, secret_key=get_api_settings().jwt_secret)}'}
    first = client.get('/api/v1/assets', params={'q': '_%', 'page_size': 2}, headers=headers)
    second = client.get('/api/v1/assets', params={'q': '_%', 'page_size': 2, 'page': 2}, headers=headers)
    assert first.status_code == second.status_code == 200
    a, b = first.json(), second.json()
    assert a['total'] == b['total'] == 6
    assert len(a['items']) == len(b['items']) == 2
    assert {row['asset_id'] for row in a['items']}.isdisjoint(row['asset_id'] for row in b['items'])
    assert all(row['tenant_id'] == str(tenant) for row in a['items'] + b['items'])
    assert client.get('/api/v1/assets', params={'q': 'missing%'}, headers=headers).json()['total'] == 0
    assert client.get('/api/v1/assets', params={'page_size': 101}, headers=headers).status_code == 422
    assert client.get('/api/v1/runs', params={'status': 'INVALID'}, headers=headers).status_code == 422
    assert client.get('/api/v1/assessments', params={'created_from': '2026-10-14T00:00:00Z', 'created_to': '2026-10-13T00:00:00Z'}, headers=headers).status_code == 422


@pytest.mark.parametrize('endpoint', ['rulesets', 'policies', 'runs', 'assessments', 'snapshots'])
def test_empty_collections_have_consistent_paging(client, endpoint):
    identity = AuthenticatedUser(user_id=uuid4(), tenant_id=uuid4(), email='synthetic@example.test', role='DATA_ENGINEER')
    headers = {'Authorization': f'Bearer {create_access_token(identity, secret_key=get_api_settings().jwt_secret)}'}
    result = client.get(f'/api/v1/{endpoint}', headers=headers)
    assert result.status_code == 200
    assert result.json() == {'items': [], 'total': 0, 'page': 1, 'page_size': 25}
