"""Bounded tiled global DEM sampling on a local lunar equal-area grid.

The source is a losslessly tiled LOLA product. Reprojected samples and derived
slopes are explicitly distinguished from native laser observations.
"""
import json, math, os
from pathlib import Path
import numpy as np
import rasterio
from rasterio.windows import Window
from rasterio.transform import from_origin
from rasterio.io import MemoryFile
from shapely.geometry import box
from .geometry import projection, projected_polygon

PRODUCT='GLOBAL_LOLA_118M'
METHOD='Bilinear source DEM sampled on a local equal-area grid at nominal source latitude spacing; clipped area weights; projected central gradients and 3x3 standard deviation. These are resampled DEM estimates, not independent laser observations.'


def source():
    path=os.getenv('WISPR_GLOBAL_DEM_MANIFEST')
    if not path:return None
    data=json.loads(Path(path).read_text())
    if data['coordinate_frame']!='MOON_ME_DE421' or data['grid']['width']!=92160 or data['grid']['height']!=46080:
        raise ValueError('Global DEM identity mismatch')
    if Path(data['path']).stat().st_size!=data['byte_size']:
        raise ValueError('Global DEM size differs from verified ingestion manifest')
    return {**data,'product_identifier':PRODUCT,'status':'VERIFIED','spatial_resolution_m':data['resolution_m'],'source_checksum':data['sha256'],
            'integrity':'SHA256 verified during ingestion; immutable release file size checked at runtime'}


def sample(ds,lon,lat,max_blocks=512):
    """Bilinear interpolation with periodic longitude and strict NoData support."""
    # Source grid is the documented full-Moon simple cylindrical raster.
    cols=((np.asarray(lon)+180)%360)/360*ds.width-.5
    rows=(90-np.asarray(lat))/180*ds.height-.5
    rows=np.clip(rows,0,ds.height-1)
    c0=np.floor(cols).astype('int64');r0=np.floor(rows).astype('int64')
    tx=cols-c0;ty=rows-r0
    result=np.zeros(cols.shape);valid=np.ones(cols.shape,dtype=bool)
    wanted=[];blocks=set();bh,bw=ds.block_shapes[0]
    for dr,dc,weight in [(0,0,(1-tx)*(1-ty)),(0,1,tx*(1-ty)),(1,0,(1-tx)*ty),(1,1,tx*ty)]:
        rr=np.clip(r0+dr,0,ds.height-1);cc=(c0+dc)%ds.width
        ids=(rr//bh)*math.ceil(ds.width/bw)+cc//bw
        wanted.append((rr,cc,weight,ids));blocks.update(int(v) for v in np.unique(ids))
    if len(blocks)>max_blocks:raise ValueError('Global DEM read budget exceeded; select a smaller region')
    ncols=math.ceil(ds.width/bw)
    # Stream blocks; never retain the entire polar ring in memory.
    for key in blocks:
        r,c=divmod(key,ncols);w=Window(c*bw,r*bh,min(bw,ds.width-c*bw),min(bh,ds.height-r*bh))
        tile=ds.read(1,window=w,masked=True).astype('float64').filled(np.nan)
        tile=tile*ds.scales[0]+ds.offsets[0]
        for rr,cc,weight,ids in wanted:
            mask=(ids==key)&(weight>1e-12)
            if not mask.any():continue
            values=tile[rr[mask]%bh,cc[mask]%bw]
            valid[mask] &= np.isfinite(values)
            result[mask] += np.nan_to_num(values)*weight[mask]
    return np.where(valid,result,np.nan)


def grid(region,budget=25000,lod=False):
    info=source()
    if not info:raise ValueError('Verified global DEM is not configured')
    forward,inverse,_,_=projection(region['geometry']['coordinates'][0])
    poly=projected_polygon(region['geometry'],forward);left,bottom,right,top=poly.bounds
    step=info['resolution_m']
    pixels=(right-left)*(top-bottom)/step**2
    if lod:step*=max(1,math.ceil(math.sqrt(pixels/budget)))
    elif pixels>budget:raise ValueError('Global terrain statistics exceed 25000 grid samples; select a smaller region')
    left=math.floor(left/step)*step-2*step;top=math.ceil(top/step)*step+2*step
    width=math.ceil((right-left)/step)+2;height=math.ceil((top-bottom)/step)+2
    if width*height>max(budget*2,2000):raise ValueError('Global terrain grid budget exceeded; select a smaller region')
    affine=from_origin(left,top,step,step)
    rr,cc=np.indices((height,width));lon,lat=inverse.transform(left+(cc+.5)*step,top-(rr+.5)*step)
    with rasterio.Env(GDAL_CACHEMAX=32*1024*1024),rasterio.open(info['path']) as ds:
        if ds.width!=info['grid']['width'] or ds.height!=info['grid']['height'] or not ds.is_tiled:
            raise ValueError('Global DEM layout mismatch')
        if info['source_id']=='USGS_LOLA_GLOBAL_118M_2014' and (ds.scales!=(0.5,) or ds.offsets!=(0.0,)):
            raise ValueError('Global DEM elevation scale/offset differs from source')
        data=sample(ds,lon,lat)
    return info,poly,forward.target_crs,affine,data,step


def window(ctx):
    info,poly,crs,affine,z,step=grid(ctx['region'],lod=True)
    east=(z[1:-1,2:]-z[1:-1,:-2])/(2*step);north=(z[:-2,1:-1]-z[2:,1:-1])/(2*step)
    slope=np.degrees(np.arctan(np.hypot(east,north)))
    rough=np.std(np.stack([z[a:a+z.shape[0]-2,b:b+z.shape[1]-2] for a in range(3) for b in range(3)]),axis=0)
    samples=[]
    for r in range(1,z.shape[0]-1):
        for c in range(1,z.shape[1]-1):
            x,y=affine*(c,r);area=poly.intersection(box(x,y-step,x+step,y)).area
            if area<=0:continue
            values={'elevation_m':z[r,c],'slope_deg':slope[r-1,c-1],'roughness_m':rough[r-1,c-1]}
            samples.append(dict(row=r,col=c,intersection_area_m2=area,**{k:float(v) if np.isfinite(v) else None for k,v in values.items()}))
    return dict(status='RESAMPLED_SOURCE_WINDOW',samples=samples,source=info,region_area_m2=poly.area,
                covered_area_m2=sum(s['intersection_area_m2'] for s in samples if s['elevation_m'] is not None),method=METHOD+f' Analysis grid spacing: {step:.3f} m.',sample_grid_spacing_m=step,
                support=ctx['measurement_support'],tool_version='global-projected-window-v1',resampled=True)


def mesh(region,resolution,scope):
    if scope!='inside':raise ValueError('Global DEM extraction supports Inside polygon only; whole-Moon meshes exceed the bounded extraction budget')
    from .terrain_mesh import build_mesh,mesh_result
    info,poly,crs,affine,z,step=grid(region,{'preview':2048,'balanced':12000,'native':25000}[resolution],lod=resolution!='native')
    with MemoryFile() as mem:
        with mem.open(driver='GTiff',height=z.shape[0],width=z.shape[1],count=1,dtype='float64',crs=crs,transform=affine,nodata=np.nan) as ds:
            ds.write(z,1);vertices,faces,covered=build_mesh(ds,poly,1)
    result=mesh_result(region,info,poly,vertices,faces,covered,crs.to_wkt(),[info['resolution_m']]*2,step/info['resolution_m'],resolution,scope)
    result['manifest'].update(data_quality='GLOBAL_DEM_RESAMPLED',native_spacing_m=None,source_nominal_latitude_spacing_m=info['resolution_m'],interpolation=METHOD,scope_domain='Selected polygon on local equal-area grid',
        source_sampling='256 pixels per degree; 118.45 m latitude spacing; east-west ground spacing varies with latitude',
        uncertainty='No local uncertainty raster; pixel spacing is not height accuracy.',limitations=info['limitations']+['Reprojected bilinear DEM surface; derivatives are scale dependent.','Pole rows use nearest available latitude sample; longitude wraps at the antimeridian.'])
    return result
