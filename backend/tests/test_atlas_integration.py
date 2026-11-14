from fastapi.testclient import TestClient
from app.main import app

def test_atlas_reuses_canonical_identity(tmp_path,monkeypatch):
    monkeypatch.setenv('WISPR_DB_PATH',str(tmp_path/'atlas.sqlite'))
    monkeypatch.setenv('WISPR_GLOBAL_ROOT',str(tmp_path/'absent'))
    c=TestClient(app)
    a=c.post('/api/v1/science/adaptive/regions/select',json={'latitude_deg':-88,'longitude_deg':0,'target_width_m':50})
    b=c.post('/api/v1/science/regions/select',json={'latitude':-88,'longitude':0,'target_width_m':50})
    assert a.status_code==200
    assert a.json()['region_id']==b.json()['region']['region_id']
    assert a.json()['context']['measurement_support']['status']=='INSUFFICIENT_DATA'
    assert c.post('/api/v1/science/adaptive/regions/select',json={'latitude_deg':100,'longitude_deg':0}).status_code==422
    assert c.get('/api/v1/science/adaptive/atlas/layers').json()['status']=='NOT_BUILT'
    assert c.get('/api/v1/science/adaptive/atlas/elevation').status_code==503

def test_atlas_polygon_keeps_actual_boundary(tmp_path,monkeypatch):
    monkeypatch.setenv('WISPR_DB_PATH',str(tmp_path/'atlas.sqlite'))
    monkeypatch.setenv('WISPR_GLOBAL_ROOT',str(tmp_path/'absent'))
    c=TestClient(app);ring=[[359.99,-88],[.01,-88],[.01,-87.99],[359.99,-87.99]]
    a=c.post('/api/v1/science/adaptive/regions/select',json={'kind':'POLYGON','coordinates_lonlat':ring,'target_width_m':1000})
    assert a.status_code==200,a.text
    assert a.json()['kind']=='POLYGON'
    assert a.json()['intersections']
    assert len(a.json()['boundary_lonlat'])==5
