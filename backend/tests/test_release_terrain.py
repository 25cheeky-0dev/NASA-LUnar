"""Synthetic ridge checks validate mechanics, not real terrain clearance."""
import hashlib
import json
import numpy as np
import rasterio
from rasterio.transform import from_origin
from app.providers.terrain import horizon


def test_controlling_obstruction_is_traceable(tmp_path, monkeypatch):
    path=tmp_path/'ridge.tif'
    crs='+proj=stere +lat_0=-90 +lat_ts=-90 +lon_0=0 +R=1737400 +units=m +no_defs'
    z=np.zeros((40,40),dtype='float32');z[12,:]=50
    with rasterio.open(path,'w',driver='GTiff',width=40,height=40,count=1,dtype='float32',crs=crs,transform=from_origin(-200,200,10,10)) as raster:
        raster.write(z,1)
    manifest=dict(z_units='metre',source_url='https://pgda.gsfc.nasa.gov/data/LOLA_5mpp/SYNTHETIC_TEST_ONLY',frame='MOON_ME_DE421',vertical_reference='synthetic_test_only',raw_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    path.with_suffix('.tif.json').write_text(json.dumps(manifest))
    monkeypatch.setenv('DEM_R04',str(path))
    result=horizon('R04',1,30,position=(-90,0))
    assert result['far_field_complete'] is False
    for ray in result['azimuth_samples']:
        if ray['terrain_horizon_elevation_deg'] is not None:
            assert 0 < ray['controlling_obstruction_distance_m'] <= ray['supported_radius_m']
            assert ray['controlling_obstruction_elevation_m'] in (0,50)
