"""Synthetic-only global DEM sampling regression tests."""
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from rasterio.io import MemoryFile
from app.regions import global_dem as g
from app.regions.context import statistics


def raster(tmp_path,data):
    path=tmp_path/'synthetic.tif'
    with rasterio.open(path,'w',driver='GTiff',width=data.shape[1],height=data.shape[0],count=1,dtype='float64',nodata=-9999,transform=from_origin(-180,90,1,1),tiled=True,blockxsize=16,blockysize=16) as ds:ds.write(data,1)
    return path


def test_bilinear_centers_wrap_poles_and_missing(tmp_path):
    data=np.arange(180*360,dtype=float).reshape(180,360)
    path=raster(tmp_path,data)
    with rasterio.open(path) as ds:
        actual=g.sample(ds,np.array([-179.5,-179,-180,180,540]),np.array([89.5,89,0,0,0]))
        assert actual[0]==0
        assert actual[1]==pytest.approx((0+1+360+361)/4)
        assert actual[2]==actual[3]==actual[4]
        assert np.isfinite(g.sample(ds,np.array([0.,0.]),np.array([-90.,90.]))).all()
        with pytest.raises(ValueError,match='read budget'):g.sample(ds,np.array([0,90]),np.array([0,40]),max_blocks=1)
    data[0,0]=-9999;path=raster(tmp_path,data)
    with rasterio.open(path) as ds:assert np.isnan(g.sample(ds,np.array([-179.5]),np.array([89.5]))[0])


@pytest.fixture
def configured(tmp_path,monkeypatch):
    path=raster(tmp_path,np.full((180,360),100.))
    info=dict(path=str(path),source_id='SYNTHETIC_ONLY',sha256='synthetic',source_checksum='synthetic',resolution_m=118.4505876,vertical_reference='synthetic',grid=dict(width=360,height=180),limitations=[])
    monkeypatch.setattr(g,'source',lambda:info)
    return info


def region(lon,lat):
    return dict(region_id='SYNTHETIC_ONLY',coordinate_frame='MOON_ME_DE421',geometry=dict(type='Polygon',coordinates=[[[lon-.02,lat-.02],[lon+.02,lat-.02],[lon+.02,lat+.02],[lon-.02,lat+.02],[lon-.02,lat-.02]]]))


@pytest.mark.parametrize('lon,lat',[(0,0),(180,0),(341.5,-83.05),(0,89.95)])
def test_flat_surface_mesh_across_seam_and_poles(configured,lon,lat):
    r=region(lon,lat);m=g.mesh(r,'preview','inside')
    assert m['manifest']['data_quality']=='GLOBAL_DEM_RESAMPLED'
    assert m['manifest']['coverage_fraction']==pytest.approx(1)
    assert all(v[2]==pytest.approx(100) for v in m['vertices'])
    assert m['manifest']['native_spacing_m'] is None
    assert m['manifest']['source_nominal_latitude_spacing_m']==118.4505876
    ctx=dict(region=r,measurement_support=dict(detailed_terrain_available=True))
    w=g.window(ctx)
    assert statistics(w,'elevation_m')['area_weighted_mean']==pytest.approx(100)
    assert statistics(w,'slope_deg')['area_weighted_mean']==pytest.approx(0,abs=1e-10)
    assert 'resampled' in statistics(w,'elevation_m')['definition']
    w['support']['detailed_terrain_available']=False
    assert statistics(w,'elevation_m')['status']=='INSUFFICIENT_DATA'


def test_global_scope_and_large_read_rejected(configured):
    with pytest.raises(ValueError,match='Inside polygon'):g.mesh(region(0,0),'preview','global')
    r=region(0,0);r['geometry']['coordinates']=[[[-2,-2],[2,-2],[2,2],[-2,2],[-2,-2]]]
    with pytest.raises(ValueError,match='25000'):g.grid(r)


def test_stored_elevation_scale_and_offset_are_applied(tmp_path):
    path=raster(tmp_path,np.full((180,360),100.))
    with rasterio.open(path,'r+') as ds:ds.scales=(.5,);ds.offsets=(-10.,)
    with rasterio.open(path) as ds:assert g.sample(ds,np.array([0.]),np.array([0.]))[0]==pytest.approx(40.)


@pytest.mark.parametrize('latitude',[89.95,-89.95])
def test_polygon_enclosing_geographic_pole(configured,latitude):
    r=region(0,0);r['geometry']['coordinates']=[[[-135,latitude],[-45,latitude],[45,latitude],[135,latitude],[-135,latitude]]]
    m=g.mesh(r,'preview','inside')
    assert m['manifest']['coverage_fraction']==pytest.approx(1)
    assert all(v[2]==pytest.approx(100) for v in m['vertices'])
