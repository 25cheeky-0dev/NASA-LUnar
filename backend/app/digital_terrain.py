"""Bounded visual terrain sampling; native evidence is not rewritten."""
import os
from functools import lru_cache
from pathlib import Path
import numpy as np
from fastapi import APIRouter,HTTPException,Query
from app.explorer import terrain_source
router=APIRouter(prefix='/api/v1/explorer',tags=['digital-moon'])

def source():
    root=os.getenv('WISPR_GLOBAL_ROOT','data/lunar-v1')
    try:
        stat=(Path(root)/'source_products/lola/ldem_4.img').stat()
        return terrain_source(root,stat.st_size,stat.st_mtime_ns)
    except (OSError,ValueError) as exc:raise HTTPException(503,'Checksum-verified LOLA DEM unavailable') from exc

def sample(arrays,lat,lon):
    # Elevation interpolation is display only. Native derivatives are never upsampled as evidence.
    rr=np.clip((90-lat)*4-.5,0,719);cc=(lon%360)*4-.5
    r0=np.floor(rr).astype(int);r1=np.minimum(r0+1,719);c0=np.floor(cc).astype(int)%1440;c1=(c0+1)%1440
    fr=rr-r0;fc=cc-np.floor(cc);z=arrays[0]
    elevation=(1-fr)*((1-fc)*z[r0,c0]+fc*z[r0,c1])+fr*((1-fc)*z[r1,c0]+fc*z[r1,c1])
    elevation=np.where(np.isclose(lat,90,rtol=0,atol=1e-10),np.nanmean(z[0]),elevation)
    elevation=np.where(np.isclose(lat,-90,rtol=0,atol=1e-10),np.nanmean(z[-1]),elevation)
    rows=np.clip(np.floor((90-lat)*4).astype(int),0,719);cols=np.floor((lon%360)*4).astype(int)%1440
    values=[elevation,arrays[1][rows,cols],arrays[2][rows,cols]]
    return {k:np.where(np.isfinite(v),v,None).tolist() for k,v in zip(('elevation_m','slope_deg','roughness_m'),values)}

@router.get('/terrain-tile/{level}/{x}/{y}')
def tile(level:int,x:int,y:int):
    if not 0<=level<=8 or not 0<=x<2**(level+1) or not 0<=y<2**level:raise HTTPException(422,'Tile outside lunar hierarchy')
    src,arrays=source();return cached_tile(level,x,y,src.source_checksum,src.source_id,src.spatial_resolution_m,os.getenv('WISPR_GLOBAL_ROOT','data/lunar-v1'))

@lru_cache(maxsize=48)
def cached_tile(level,x,y,checksum,source_id,resolution,root):
    stat=(Path(root)/'source_products/lola/ldem_4.img').stat();_,arrays=terrain_source(root,stat.st_size,stat.st_mtime_ns)
    width=180/2**level;west=x*width;south=90-(y+1)*width
    lon,lat=np.meshgrid(np.linspace(west,west+width,33),np.linspace(south+width,south,33))
    return {'level':level,'x':x,'y':y,'west':west,'north':south+width,'span_degrees':width,'size':33,
            **sample(arrays,lat,lon),'source_id':source_id,'source_sha256':checksum,'source_resolution_m':resolution,
            'reference_radius_m':1737400,'coordinate_frame':'MOON_ME_DE421','purpose':'DISPLAY_INTERPOLATION_ONLY; exact pole closure uses native terminal-row mean','terrain_occlusion':'UNKNOWN'}

@router.get('/terrain-globe')
def globe():
    src,arrays=source();lon,lat=np.meshgrid(np.linspace(0,360,257),np.linspace(90,-90,129))
    return {'size_x':257,'size_y':129,**sample(arrays,lat,lon),'source':src.model_dump(),'reference_radius_m':1737400,
            'coordinate_frame':'MOON_ME_DE421','purpose':'DISPLAY_INTERPOLATION_ONLY; exact pole closure uses native terminal-row mean','terrain_occlusion':'UNKNOWN'}
