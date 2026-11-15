"""Analytic test rasters only; no fixture is served as lunar observations."""
import json
import hashlib
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from pyproj import CRS, Transformer
from shapely.geometry import Polygon, box
from fastapi.testclient import TestClient
from app.regions import terrain_mesh as tm, store
from app.main import app


@pytest.fixture
def source(tmp_path, monkeypatch):
    crs=CRS.from_proj4('+proj=stere +lat_0=-90 +lat_ts=-90 +lon_0=0 +R=1737400 +units=m')
    path=tmp_path/'test-only.tif'; affine=from_origin(0,100,5,5)
    rows,cols=np.indices((20,20)); x=(cols+.5)*5; y=100-(rows+.5)*5
    z=(2*x+3*y+100).astype('float64')
    with rasterio.open(path,'w',driver='GTiff',width=20,height=20,count=1,dtype='float64',crs=crs,transform=affine,nodata=-9999) as ds:ds.write(z,1)
    item=dict(source_id='TEST_ONLY',path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),coordinate_frame='MOON_ME_DE421',units='m',vertical_reference='test analytic plane',grid=dict(crs=crs.to_wkt(),origin_x_m=0,origin_y_m=100,root_width_m=100))
    catalog=tmp_path/'catalog.json';catalog.write_text(json.dumps([item]));monkeypatch.setenv('WISPR_REGIONAL_CATALOG',str(catalog));monkeypatch.delenv('WISPR_GRID_DIR',raising=False);monkeypatch.setenv('WISPR_DB_PATH',str(tmp_path/'store.sqlite'));monkeypatch.delenv('WISPR_DATABASE_URL',raising=False);monkeypatch.delenv('K_SERVICE',raising=False)
    return path,crs


def test_partial_triangles_holes_and_native_elevation(source):
    path,_=source
    poly=Polygon([(11,11),(89,17),(75,88),(14,79)],holes=[[(35,35),(55,35),(55,55),(35,55)]])
    with rasterio.open(path) as ds:vertices,faces,area=tm.build_mesh(ds,poly,1)
    assert area==pytest.approx(poly.area,rel=1e-10)
    v=np.array(vertices)
    assert np.allclose(v[:,2],2*v[:,0]+3*v[:,1]+100)
    for face in faces: assert poly.buffer(1e-8).covers(Polygon(v[face,:2]))
    assert any(abs(x/5-.5-round(x/5-.5))>1e-4 for x,y,z in vertices)


def test_lod_retains_plane_and_nodata_is_not_bridged(source):
    path,_=source
    with rasterio.open(path,'r+') as ds:
        z=ds.read(1);z[9,9]=-9999;ds.write(z,1)
    poly=box(10,10,90,90)
    with rasterio.open(path) as ds:
        v,f,area=tm.build_mesh(ds,poly,4)
    assert 0<area<poly.area
    assert all(abs(z-(2*x+3*y+100))<1e-7 for x,y,z in v)
    assert not any(Polygon(np.array(v)[face,:2]).contains(box(47,52,48,53).centroid) for face in f)


def test_no_coverage_and_invalid_source(source):
    path,_=source
    with rasterio.open(path) as ds:
        with pytest.raises(ValueError,match='NO_DATA'):tm.build_mesh(ds,box(200,200,220,220),1)
    path.write_bytes(b'broken')
    with pytest.raises(ValueError,match='integrity'):tm.sources()


def test_http_extraction_export_and_restore(source):
    _,crs=source
    inv=Transformer.from_crs(crs,crs.geodetic_crs,always_xy=True)
    ring=[list(inv.transform(x,y)) for x,y in [(12,12),(88,12),(88,88),(12,88),(12,12)]]
    region={'region_id':'TEST:POLYGON','coordinate_frame':'MOON_ME_DE421','geometry':{'type':'Polygon','coordinates':[ring]}}
    store.put('region',region['region_id'],region)
    client=TestClient(app)
    response=client.post('/api/v1/science/regions/TEST:POLYGON/terrain',json={'resolution':'native'})
    assert response.status_code==200,response.text
    result=response.json();key=result['mesh_id'];manifest=result['manifest']
    assert manifest['native_spacing_m']==[5,5]
    assert manifest['coverage_fraction']==pytest.approx(1,abs=1e-7)
    assert client.get(f'/api/v1/science/terrain/{key}').json()==result
    geo=client.get(f'/api/v1/science/terrain/{key}/export/geojson').json()
    assert geo['geometry']==region['geometry']
    assert geo['properties']['lunar_reference']['coordinate_frame']=='MOON_ME_DE421'
    obj=client.get(f'/api/v1/science/terrain/{key}/export/obj')
    assert obj.status_code==200 and '\nv ' in obj.text and '\nf ' in obj.text
    assert client.get(f'/api/v1/science/terrain/{key}/export/json').json()==result
    assert client.post('/api/v1/science/regions/TEST:POLYGON/terrain',json={'resolution':'native','exaggeration':7}).status_code==422
    assert client.post('/api/v1/science/regions/missing/terrain',json={}).status_code==404


def test_scope_partition_and_saved_names(source):
    _,crs=source
    inv=Transformer.from_crs(crs,crs.geodetic_crs,always_xy=True)
    ring=[list(inv.transform(x,y)) for x,y in [(20,20),(70,20),(70,70),(20,70),(20,20)]]
    region={'region_id':'TEST:SCOPE','coordinate_frame':'MOON_ME_DE421','geometry':{'type':'Polygon','coordinates':[ring]},'latitude_deg':-89.9,'longitude_deg':0}
    inside=tm.extract(region,'native','inside');outside=tm.extract(region,'native','exclude');full=tm.extract(region,'native','global')
    assert inside['manifest']['covered_area_m2']+outside['manifest']['covered_area_m2']==pytest.approx(full['manifest']['covered_area_m2'],rel=1e-8)
    assert len({r['mesh_id'] for r in (inside,outside,full)})==3
    store.put('region',region['region_id'],region)
    tm.name_region(tm.RegionName(region_id=region['region_id'],name='Crater rim'))
    assert tm.saved_regions()['regions'][0]['name']=='Crater rim'


def test_terrain_routes_have_unique_operations():
    schema=app.openapi()
    path='/api/v1/science/regions/{region_id}/terrain'
    assert 'post' in schema['paths'][path]
    ids=[op['operationId'] for methods in schema['paths'].values() for op in methods.values() if isinstance(op,dict) and 'operationId' in op]
    assert len(ids)==len(set(ids))


def test_regular_polygon_uses_regional_native_statistics(source, monkeypatch):
    from app.regions import context as context_module
    from app.regions import local
    path,crs=source
    inverse=Transformer.from_crs(crs,crs.geodetic_crs,always_xy=True)
    ring=[list(inverse.transform(x,y)) for x,y in [(20,20),(80,20),(80,80),(20,80),(20,20)]]
    region={'region_id':'analytic','kind':'POLYGON','geometry':{'type':'Polygon','coordinates':[ring]},'nominal_width_m':60,'coordinate_frame':'MOON_ME_DE421'}
    monkeypatch.setattr(context_module,'source_registry',lambda:[])
    ctx=context_module.context(region)
    assert ctx['measurement_support']['source_resolution_m']==5
    assert ctx['measurement_support']['detailed_terrain_available']
    window=local.window(ctx)
    result=context_module.statistics(window,'elevation_m')
    assert result['area_weighted_mean']==pytest.approx(350,abs=.01)
    assert result['coverage_fraction']==pytest.approx(1,abs=.001)
