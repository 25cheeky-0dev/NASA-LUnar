from fastapi.testclient import TestClient
from app.main import app
from datetime import datetime


def test_real_offline_demo_http():
    with TestClient(app) as client:
        cells = client.get('/api/v1/navigation/demo/cells').json()
        response = client.post('/api/v1/navigation/demo/delay')
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['delivery_mode'] == 'PRESERVED_REAL_DATA_OFFLINE'
    assert data['outcome'] == 'KEEP'
    for a, b in zip(data['original']['results'], data['delayed']['results']):
        assert a['cell_id'] == b['cell_id']
        x, y = a['dynamic_vector'], b['dynamic_vector']
        assert (datetime.fromisoformat(y['start_utc'])-datetime.fromisoformat(x['start_utc'])).total_seconds() == 604800
        assert x['features']['unknown_data_fraction'] == 0
        assert all(q['delivery'] == 'VERIFIED_CACHE' for q in x['provenance']['queries'].values())
        assert a['cell'] == next(c for c in cells['cells'] if c['cell_id'] == a['cell_id'])


def test_navigation_is_not_cell_identity():
    with TestClient(app) as client:
        places = client.get('/api/v1/navigation/locations').json()['locations']
        for p in places:
            assert p['source'].startswith('https://')
            cell = client.get('/api/v1/science/global/cells/lookup', params={'latitude':p['latitude_deg'],'longitude':p['longitude_deg']}).json()
            assert cell['cell_id'].startswith('MOON:HPX:NESTED:128:')
