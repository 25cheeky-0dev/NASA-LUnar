import numpy as np
import pytest
from fastapi import HTTPException
from app.digital_terrain import sample,tile

def test_native_samples_dateline_and_nodata():
    elevation=np.tile(np.arange(1440,dtype=float),(720,1));slope=np.full((720,1440),3.);rough=np.full((720,1440),7.)
    result=sample((elevation,slope,rough),np.array([[0.,0.]]),np.array([[0.,360.]]))
    assert result['elevation_m'][0][0]==result['elevation_m'][0][1]
    assert result['slope_deg']==[[3.,3.]]
    slope[:]=np.nan
    assert sample((elevation,slope,rough),np.array([[0.]]),np.array([[0.]]))['slope_deg']==[[None]]

def test_adjacent_tile_edges_share_identical_samples():
    rows,cols=np.indices((720,1440));z=rows*2.+cols
    arrays=(z,z/1000,z/100)
    west,lat=np.meshgrid(np.linspace(0,45,33),np.linspace(-45,-90,33))
    east,_=np.meshgrid(np.linspace(45,90,33),np.linspace(-45,-90,33))
    a=sample(arrays,lat,west);b=sample(arrays,lat,east)
    for field in a:assert np.array_equal(np.array(a[field])[:,-1],np.array(b[field])[:,0])

@pytest.mark.parametrize('args',[(9,0,0),(-1,0,0),(2,8,0),(2,0,4)])
def test_tile_request_bounds(args):
    with pytest.raises(HTTPException) as exc:tile(*args)
    assert exc.value.status_code==422

def test_pole_closure_is_single_physical_vertex():
    z=np.tile(np.arange(1440,dtype=float),(720,1))
    result=sample((z,z,z),np.array([[90.,90.,-90.,-90.]]),np.array([[0.,180.,0.,180.]]))
    assert result['elevation_m'][0]==[719.5]*4
