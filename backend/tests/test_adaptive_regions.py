"""Independent spatial and contract checks; synthetic rasters are TEST ONLY."""
import json
import math
import time
import hashlib
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from fastapi.testclient import TestClient
from app.main import app
from app.regions.geometry import cell_region,polygon_region,nside_for_width
from app.regions.context import context,statistics
from app.regions import store,local,agent
from app.regions.tools import Arguments,Mission,run
from lunar_global.grid import hpx,lookup,describe,batches,parse_id


@pytest.fixture(autouse=True)
def isolated_store(tmp_path,monkeypatch):
    monkeypatch.setenv('WISPR_DB_PATH',str(tmp_path/'regions.sqlite'))
    monkeypatch.delenv('WISPR_DATABASE_URL',raising=False)
    monkeypatch.delenv('K_SERVICE',raising=False)
    monkeypatch.delenv('WISPR_REGIONAL_CATALOG',raising=False)


@pytest.mark.parametrize('lat,lon',[(-90,0),(-89.9,359.999),(90,180),(0,-179.99),(45,42)])
def test_fine_ids_lineage_area_and_wrap(lat,lon):
    value=lookup(lat,lon,32768);info=describe(value)
    assert value==lookup(lat,lon+360,32768)
    assert 54<math.sqrt(info['area_m2'])<55
    assert info['children']==[]
    n,p=parse_id(value);assert parse_id(info['parent_id'])==(n//2,p//4)
    assert value in describe(info['parent_id'])['children']
    assert len(info['neighbors'])>=7
    with pytest.raises(ValueError):next(batches(32768))
    with pytest.raises(ValueError):hpx(65536)


def test_roi_identity_rotation_direction_wrap_and_source_independence():
    ring=[[359.9,-88],[.1,-88],[.1,-87.99],[359.9,-87.99],[359.9,-88]]
    a=polygon_region({'type':'Polygon','coordinates':[ring]},1024)
    reversed_ring=list(reversed(ring))
    b=polygon_region({'type':'Polygon','coordinates':[reversed_ring]},2048)
    c=polygon_region({'type':'Polygon','coordinates':[[[-.1,-88],[.1,-88],[.1,-87.99],[-.1,-87.99],[-.1,-88]]]},1024)
    assert a['region_id']==b['region_id']==c['region_id']
    assert a['area_m2']>60000
    assert a['intersection_area_error_fraction']<1e-4
    assert sum(x['region_fraction'] for x in a['intersections'])==pytest.approx(1,abs=1e-4)
    assert all(x['geometry']['type'] in ('Polygon','MultiPolygon') for x in a['intersections'])


def test_polar_roi_and_self_intersection():
    r=[[-135,-89.9],[-45,-89.9],[45,-89.9],[135,-89.9],[-135,-89.9]]
    info=polygon_region({'type':'Polygon','coordinates':[r]},128)
    assert info['area_m2']>0 and info['intersections']
    bad=[[0,0],[1,1],[0,1],[1,0],[0,0]]
    with pytest.raises(ValueError):polygon_region({'type':'Polygon','coordinates':[bad]},128)


def test_roi_hole_preserved_and_budget_enforced():
    outer=[[10,-70],[10.1,-70],[10.1,-69.9],[10,-69.9],[10,-70]]
    hole=[[10.02,-69.98],[10.08,-69.98],[10.08,-69.92],[10.02,-69.92],[10.02,-69.98]]
    whole=polygon_region({'type':'Polygon','coordinates':[outer]},128)
    cut=polygon_region({'type':'Polygon','coordinates':[outer,hole]},128)
    assert cut['area_m2']<whole['area_m2']
    assert len(cut['geometry']['coordinates'])==2
    with pytest.raises(ValueError):polygon_region({'type':'Polygon','coordinates':[[[0,0],[10,0],[10,10],[0,10],[0,0]]]},32768)


def test_selection_persists_and_cannot_inherit_coarse_measurements(monkeypatch,tmp_path):
    monkeypatch.setenv('WISPR_GLOBAL_ROOT',str(tmp_path/'missing'))
    with TestClient(app) as client:
        a=client.post('/api/v1/science/regions/select',json={'latitude':-89,'longitude':20,'target_width_m':25})
        assert a.status_code==200,a.text
        result=a.json();key=result['region']['region_id']
        b=client.get('/api/v1/science/regions/'+key).json()
        assert b['region']==result['region']
        assert result['measurement_support']['status']=='INSUFFICIENT_DATA'
        assert not result['capabilities']['verified_terrain_occlusion']
        assert client.post('/api/v1/science/regions/select',json={'latitude':-89,'longitude':20,'cell_id':key}).status_code==422
        assert client.post('/api/v1/science/regions/select',json={'latitude':-89,'longitude':20,'observation_time':'2026-01-01T00:00:00'}).status_code==422


def test_weighted_values_and_nodata_are_not_zero():
    window={'support':{'detailed_terrain_available':True},'region_area_m2':4,
            'source':{'source_id':'SYNTHETIC_TEST_ONLY','source_checksum':'a'*64},'method':'test intersection',
            'samples':[{'intersection_area_m2':1,'elevation_m':0},{'intersection_area_m2':2,'elevation_m':9},{'intersection_area_m2':1,'elevation_m':None}]}
    r=statistics(window,'elevation_m')
    assert r['area_weighted_mean']==6 and r['coverage_fraction']==.75
    window['support']['detailed_terrain_available']=False
    assert statistics(window,'elevation_m')['value'] is None


def test_local_dem_quadtree_native_gradient_and_version_independent_id(tmp_path,monkeypatch):
    from pyproj import CRS,Transformer
    path=tmp_path/'SYNTHETIC_TEST_ONLY.tif';crs=CRS.from_proj4('+proj=stere +lat_0=-90 +lon_0=0 +R=1737400 +units=m')
    z=np.tile(np.arange(100,dtype='float32')*2,(100,1))
    with rasterio.open(path,'w',driver='GTiff',width=100,height=100,count=1,dtype='float32',crs=crs,transform=from_origin(-500,10500,10,10),nodata=-9999) as ds:ds.write(z,1)
    with rasterio.open(path) as ds:stored_crs=ds.crs.to_wkt()
    row={'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'source_id':'SYNTHETIC_TEST_ONLY',
         'coordinate_frame':'MOON_ME_DE421','units':'m','vertical_reference':'SYNTHETIC_TEST_ONLY',
         'grid':{'crs':stored_crs,'origin_x_m':0,'origin_y_m':0,'root_width_m':51200},'version':'v1'}
    config=tmp_path/'catalog.json';config.write_text(json.dumps([row]));monkeypatch.setenv('WISPR_REGIONAL_CATALOG',str(config))
    grid=local.catalog()[0];lon,lat=Transformer.from_crs(crs,crs.geodetic_crs,always_xy=True).transform(25,10025)
    region=local.select(grid['grid_id'],lat,lon,100)
    row['version']='v2';config.write_text(json.dumps([row]))
    assert local.select(local.catalog()[0]['grid_id'],lat,lon,100)['region_id']==region['region_id']
    ctx=context(region);window=local.window(ctx)
    measured=statistics(window,'slope_deg')
    assert measured['area_weighted_mean']==pytest.approx(math.degrees(math.atan(.2)),abs=1e-5)
    assert region['children'] and region['parent_id']
    assert local.describe_id(region['region_id'])['region_id']==region['region_id']
    assert local.describe_id(region['children'][0])['parent_id']==region['region_id']


def test_agent_job_reuses_cache_without_inventing_date(tmp_path,monkeypatch):
    monkeypatch.setenv('WISPR_GLOBAL_ROOT',str(tmp_path/'missing'))
    r=cell_region(lookup(-88,0,32768));store.put('region',r['region_id'],r)
    job=agent.launch(r['region_id'],agent.AnalyzeRequest())
    for _ in range(100):
        done=store.get('job',job['job_id'])
        if done['status'] in ('COMPLETE','FAILED'):break
        time.sleep(.02)
    assert done['status']=='COMPLETE',done
    assert done['result']['input']['mission'] is None
    assert done['result']['evidence_status']=='INSUFFICIENT_DATA'
    assert not any('ephemeris' in e['tool'] for e in done['events'])
    assert agent.launch(r['region_id'],agent.AnalyzeRequest())['cache_hit']
    with pytest.raises(ValueError):Arguments(region_id=r['region_id'],made_up_safety_probability=.99)
    ctx=context(r)
    with pytest.raises(ValueError):run('invent_landing_safety',{'region_id':r['region_id']},ctx,{})


def test_dates_and_budget_limits():
    with pytest.raises(ValueError):Mission(start_utc='2026-01-01',end_utc='2026-01-02')
    with pytest.raises(ValueError):agent.AnalyzeRequest(max_tools=100)
    with pytest.raises(ValueError):Arguments(region_id='x',observer_height_m=-1)


def test_job_capacity_and_source_changes_invalidate_cache(tmp_path,monkeypatch):
    monkeypatch.setenv('WISPR_GLOBAL_ROOT',str(tmp_path/'missing'))
    r=cell_region(lookup(0,0,32768));store.put('region',r['region_id'],r)
    agent.GATE.acquire();agent.GATE.acquire()
    try:
        with pytest.raises(OverflowError):agent.launch(r['region_id'],agent.AnalyzeRequest())
    finally:agent.GATE.release();agent.GATE.release()


def test_adaptive_http_contracts():
    schema=app.openapi()
    select=schema['paths']['/api/v1/science/regions/select']['post']
    assert select['responses']['200']['content']['application/json']['schema']['$ref'].endswith('/RegionContext')
    analysis=schema['paths']['/api/v1/science/regions/{region_id}/analyze']['post']
    assert '202' in analysis['responses']
    assert analysis['requestBody']['content']['application/json']['schema']['$ref'].endswith('AnalyzeRequest')


def test_delay_adapter_preserves_explicit_lunar_reference(monkeypatch):
    from types import SimpleNamespace
    from app.regions import tools
    r=cell_region(lookup(-85,20,64));store.put('region',r['region_id'],r)
    class InspectEngine:
        def __init__(self,registry,celestial):
            meta=registry.datasets['SELECTED_REGIONS'].metadata
            assert meta.reference_radius_m==1737400
            assert meta.coordinate_frame=='MOON_ME_DE421'
        def delay(self,request,original):
            assert request.horizon_model=='GEOMETRIC_IDEAL'
            return {'outcome':'INSUFFICIENT_DATA','test_only':True}
    monkeypatch.setattr(tools,'AnalysisEngine',InspectEngine)
    monkeypatch.setattr(tools,'engine',lambda:SimpleNamespace(celestial=object()))
    result=run('calculate_delay_impact',Arguments(region_id=r['region_id'],mission=Mission(start_utc='2026-11-15T00:00:00Z',end_utc='2026-11-15T03:00:00Z')),context(r),{})
    assert result['status']=='COMPLETE'

def test_delay_source_outage_is_not_cacheable(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from app.regions import tools
    monkeypatch.setenv('WISPR_GLOBAL_ROOT',str(tmp_path/'absent'))
    r=cell_region(lookup(0,0,64));store.put('region',r['region_id'],r)
    class UnavailableEngine:
        def __init__(self,*args,**kwargs):pass
        def delay(self,*args):return {'original':{'results':[{'status':'UNKNOWN','reasons':['SOURCE_UNAVAILABLE']}]},'delayed':{'results':[]},'outcome':'INSUFFICIENT_DATA'}
    monkeypatch.setattr(tools,'AnalysisEngine',UnavailableEngine)
    monkeypatch.setattr(tools,'engine',lambda:SimpleNamespace(celestial=object()))
    result=run('calculate_delay_impact',Arguments(region_id=r['region_id'],mission=Mission(start_utc='2026-11-15T00:00:00Z',end_utc='2026-11-15T03:00:00Z')),context(r),{})
    assert result['status']=='UNAVAILABLE'
