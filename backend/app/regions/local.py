"""Opt-in DEM-aligned quadtree with grid identity independent of product versions."""
import hashlib
import json
import math
import os
from pathlib import Path
import numpy as np
import rasterio
from pyproj import CRS, Transformer
from shapely.geometry import Polygon, box
from shapely.ops import transform
from lunar_global.grid import RADIUS_M,FRAME
from lunar_global.storage import sha256


def catalog():
    path=os.getenv('WISPR_REGIONAL_CATALOG')
    if not path:return []
    rows=json.loads(Path(path).read_text())
    if not isinstance(rows,list) or len(rows)>16:raise ValueError('Regional catalog budget exceeded')
    result=[]
    for row in rows:
        crs=CRS.from_user_input(row['grid']['crs'])
        if not crs.is_projected or abs(crs.ellipsoid.semi_major_metre-RADIUS_M)>1e-5 or crs.ellipsoid.inverse_flattening!=0:
            raise ValueError('Regional grid requires lunar spherical projected CRS')
        if any(a.unit_name!='metre' for a in crs.axis_info):raise ValueError('Projected metre units required')
        definition={'crs_wkt':crs.to_wkt(),'origin_x_m':row['grid']['origin_x_m'],'origin_y_m':row['grid']['origin_y_m'],
                    'root_width_m':row['grid']['root_width_m'],'algorithm':'lunar-dem-quadtree-v1','coordinate_frame':FRAME}
        key=hashlib.sha256(json.dumps(definition,sort_keys=True).encode()).hexdigest()[:24]
        if row.get('coordinate_frame')!=FRAME or row.get('units')!='m' or not row.get('vertical_reference'):
            raise ValueError('Explicit lunar frame, metre units and vertical reference required')
        if sha256(row['path'])!=row['sha256']:raise ValueError('Regional DEM integrity failed')
        with rasterio.open(row['path']) as ds:
            if CRS.from_user_input(ds.crs)!=crs or ds.transform.b!=0 or ds.transform.d!=0:raise ValueError('DEM CRS/orientation differs from grid')
            res=max(ds.res)
            for origin,offset,step in [(definition['origin_x_m'],ds.transform.c,ds.res[0]),(definition['origin_y_m'],ds.transform.f,ds.res[1])]:
                if abs((origin-offset)/step-round((origin-offset)/step))>1e-6:raise ValueError('Grid origin not aligned to DEM pixels')
        result.append(dict(row,grid_id=key,grid_definition=definition,resolution_m=res))
    return result


def select(grid_id,latitude,longitude,target_width):
    source=next((s for s in catalog() if s['grid_id']==grid_id),None)
    if not source:raise ValueError('Unregistered local grid')
    g=source['grid_definition'];crs=CRS.from_wkt(g['crs_wkt'])
    level=max(0,min(20,round(math.log2(g['root_width_m']/target_width))))
    width=g['root_width_m']/2**level
    if width<2*source['resolution_m']:raise ValueError('Local cell width requires at least two native source pixels')
    ratio=width/source['resolution_m']
    if abs(ratio-round(ratio))>1e-6:raise ValueError('Requested quadtree level is not DEM-pixel aligned')
    x,y=Transformer.from_crs(crs.geodetic_crs,crs,always_xy=True).transform(longitude,latitude)
    ix=math.floor((x-g['origin_x_m'])/width);iy=math.floor((y-g['origin_y_m'])/width)
    x0=g['origin_x_m']+ix*width;y0=g['origin_y_m']+iy*width
    inverse=Transformer.from_crs(crs,crs.geodetic_crs,always_xy=True)
    ring=[list(inverse.transform(a,b)) for a,b in [(x0,y0),(x0+width,y0),(x0+width,y0+width),(x0,y0+width),(x0,y0)]]
    lon,lat=inverse.transform(x0+width/2,y0+width/2)
    key=lambda l,i,j:f'MOON:LOCAL:{grid_id}:{l}:{i}:{j}'
    return dict(region_id=key(level,ix,iy),kind='LOCAL_QUADTREE',geometry={'type':'Polygon','coordinates':[ring]},
                latitude_deg=lat,longitude_deg=lon%360,area_m2=width*width,nominal_width_m=width,
                coordinate_frame=FRAME,reference_radius_m=RADIUS_M,geometry_version='lunar-dem-quadtree-v1',
                grid_version='lunar-dem-quadtree-v1',grid_definition=g,local_grid_id=grid_id,
                parent_id=key(level-1,ix//2,iy//2) if level else None,
                children=[key(level+1,ix*2+a,iy*2+b) for a in (0,1) for b in (0,1)] if width/2>=2*source['resolution_m'] else [],
                neighbors=[key(level,ix+a,iy+b) for a,b in [(1,0),(-1,0),(0,1),(0,-1)]],intersections=[])


def window(ctx):
    region=ctx['region'];source=next(s for s in catalog() if s['grid_id']==region['local_grid_id'])
    with rasterio.open(source['path']) as ds:
        crs=CRS.from_user_input(ds.crs);forward=Transformer.from_crs(crs.geodetic_crs,crs,always_xy=True)
        poly=transform(forward.transform,Polygon(region['geometry']['coordinates'][0]))
        win=rasterio.windows.from_bounds(*poly.bounds,ds.transform).round_offsets().round_lengths()
        if win.width*win.height>25000:raise ValueError('DEM window exceeds pixel budget')
        # Include a one-pixel halo; boundary/NoData derivatives remain missing.
        halo=rasterio.windows.Window(win.col_off-1,win.row_off-1,win.width+2,win.height+2)
        raw=ds.read(1,window=halo,boundless=True,masked=True).astype(float).filled(np.nan)
        east=(raw[1:-1,2:]-raw[1:-1,:-2])/(2*ds.res[0]);north=(raw[:-2,1:-1]-raw[2:,1:-1])/(2*ds.res[1])
        slope=np.degrees(np.arctan(np.hypot(east,north)))
        stack=np.stack([raw[a:a+int(win.height),b:b+int(win.width)] for a in range(3) for b in range(3)])
        rough=np.std(stack,axis=0);z=raw[1:-1,1:-1];samples=[]
        for r in range(z.shape[0]):
            for c in range(z.shape[1]):
                x,y=ds.transform*(win.col_off+c,win.row_off+r)
                area=poly.intersection(box(x,y-ds.res[1],x+ds.res[0],y)).area
                if area<=0:continue
                values={name:float(a[r,c]) if np.isfinite(a[r,c]) else None for name,a in [('elevation_m',z),('slope_deg',slope),('roughness_m',rough)]}
                samples.append(dict(row=int(win.row_off+r),col=int(win.col_off+c),intersection_area_m2=area,**values))
    return dict(status='SOURCE_PIXEL_WINDOW',samples=samples,source=dict(source,source_id=source['source_id'],source_checksum=source['sha256']),
                region_area_m2=poly.area,covered_area_m2=sum(s['intersection_area_m2'] for s in samples if s['elevation_m'] is not None),
                method='Native raster window plus 1-pixel halo; projected intersection weights; central gradients; 3x3 std; no imputation',
                support=ctx['measurement_support'],tool_version='regional-native-window-v1')


def describe_id(region_id):
    parts=region_id.split(':')
    if len(parts)!=6 or parts[:2]!=['MOON','LOCAL']:raise ValueError('Invalid local grid ID')
    grid_id=parts[2];level,ix,iy=map(int,parts[3:])
    if not 0<=level<=20 or abs(ix)>2**40 or abs(iy)>2**40:raise ValueError('Local cell outside index bounds')
    source=next((s for s in catalog() if s['grid_id']==grid_id),None)
    if not source:raise ValueError('Unregistered local grid')
    g=source['grid_definition'];width=g['root_width_m']/2**level;crs=CRS.from_wkt(g['crs_wkt'])
    lon,lat=Transformer.from_crs(crs,crs.geodetic_crs,always_xy=True).transform(g['origin_x_m']+(ix+.5)*width,g['origin_y_m']+(iy+.5)*width)
    result=select(grid_id,lat,lon,width)
    if result['region_id']!=region_id:raise ValueError('Local cell outside valid projection domain')
    return result
