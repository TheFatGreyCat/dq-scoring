from tests.integration.api.test_operations_routes import headers


def test_empty_viewer_overview_has_real_zero_and_no_import_fields(client):
    _, viewer = headers('VIEWER')
    response = client.get('/api/v1/overview', headers=viewer)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['counts']['assets'] == 0
    assert data['counts']['snapshots'] == 0
    assert data['counts']['runs'] == {status:0 for status in ('QUEUED','LEASED','RUNNING','SUCCEEDED','FAILED','CANCELLED')}
    assert data['recent_runs'] == []
    assert data['import_counts'] is None and data['recent_imports'] is None
