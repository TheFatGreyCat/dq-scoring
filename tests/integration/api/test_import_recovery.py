from tests.integration.api.test_operations_routes import headers

pytest_plugins = ["tests.integration.api.test_import_routes"]


def test_import_listing_preserves_metadata_and_excludes_other_tenants(client, seeded_tenant_and_users, auth_headers):
    response = client.post('/api/v1/imports',headers=auth_headers,json={
        'client_request_id':__import__('uuid').uuid4().hex,'asset_name':'Synthetic recovery',
        'format':'CSV','original_filename':'synthetic.csv','size_bytes':20,
        'csv_options':{'delimiter':';','encoding':'utf-8'}})
    assert response.status_code==201,response.text
    session=response.json()
    listing=client.get('/api/v1/imports',headers=auth_headers)
    assert listing.status_code==200,listing.text
    row=next(row for row in listing.json()['items'] if row['upload_id']==session['upload_id'])
    assert row['updated_at']==session['updated_at'] and row['expires_at']==session['expires_at']
    assert 'manifest' not in row and 'source_descriptor' not in row
    detail=client.get('/api/v1/imports/'+session['upload_id'],headers=auth_headers)
    assert detail.json()['csv_options']['delimiter']==';'
    _, viewer=headers('VIEWER')
    assert client.get('/api/v1/imports',headers=viewer).status_code==403
    _, other=headers('DATA_ENGINEER')
    assert client.get('/api/v1/imports',headers=other).json()['items']==[]
    assert client.get('/api/v1/imports/'+session['upload_id'],headers=other).status_code==404
