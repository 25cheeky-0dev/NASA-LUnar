"""Intersect actual source pixels, never color values or copied parent measures."""
import hashlib
import json
import math
import os
from pathlib import Path
import numpy as np
from shapely.geometry import Polygon
from shapely.ops import transform
from lunar_global.sources import SourceProduct
from lunar_global.storage import sha256
from lunar_global.features import native_terrain
from .geometry import projection,projected_polygon,GEOD

TOOL_VERSION='region-native-overlap-v3'


def source_registry():
    root=Path(os.getenv('WISPR_GLOBAL_ROOT','data/lunar-v1'))
    records=[]
    for name,filename in [('lola','ldem_4.img'),('lroc','WAC_GLOBAL_E000N1800_004P.IMG'),('diviner','global_cumul_avg_cyl_90s80s_002.tab')]:
        folder=root/'source_products'/name
        try:
            source=SourceProduct.model_validate_json((folder/'source.json').read_text())
            source.validate_alignment()
            if sha256(folder/filename)!=source.source_checksum:raise ValueError('Source hash mismatch')
            records.append(source.model_dump())
        except (OSError,ValueError):
            records.append({'source_id':name,'status':'UNAVAILABLE','reason':'Product unavailable or failed integrity validation'})
    return records


def context(region):
    sources=source_registry()
    if region['kind']=='LOCAL_QUADTREE':
        from .local import catalog
        regional=next((s for s in catalog() if s['grid_id']==region['local_grid_id']),None)
        if regional:
            sources.append({k:v for k,v in regional.items() if k!='path'})
            sources[-1].update(product_identifier='REGISTERED_REGIONAL_DEM',status='VERIFIED',
                               spatial_resolution_m=regional['resolution_m'],source_checksum=regional['sha256'])
    dem=next((s for s in sources if s.get('product_identifier')=='LDEM_4' and s.get('status')=='VERIFIED'),None)
    if region['kind']=='LOCAL_QUADTREE':dem=next((s for s in sources if s.get('product_identifier')=='REGISTERED_REGIONAL_DEM'),None)
    resolution=dem['spatial_resolution_m'] if dem else None
    support_width=region['nominal_width_m']
    if region['kind']=='POLYGON':
        forward,_,_,_=projection(region['geometry']['coordinates'][0])
        hull=projected_polygon(region['geometry'],forward).minimum_rotated_rectangle
        corners=list(hull.exterior.coords)
        support_width=min(math.dist(corners[i],corners[i+1]) for i in range(4))
    supported=bool(resolution and support_width>=2*resolution)
    missing=[]
    if not dem:missing.append('NO_VERIFIED_DEM')
    elif not supported:missing.append('SELECTION_FINER_THAN_SCIENTIFIC_SUPPORT')
    missing+=['TERRAIN_DATUM_UNVERIFIED','TERRAIN_UNCERTAINTY_UNKNOWN','MISSION_DATE_NOT_SUPPLIED']
    fingerprint=hashlib.sha256(json.dumps(sources,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return dict(region=region,available_datasets=sources,measurement_support={
        'selection_width_m':region['nominal_width_m'],'minimum_support_width_m':support_width,'source_resolution_m':resolution,
        'detailed_terrain_available':supported,'status':'SOURCE_BACKED_OVERVIEW' if supported else 'INSUFFICIENT_DATA',
        'minimum_independent_samples_across_region':2,
        'rule':'A target width is geography, not measurement resolution; no coarse-parent value inheritance.'},
        missing_measurements=missing,quality='UNCERTAINTY_UNKNOWN',source_fingerprint=fingerprint,
        capabilities={'static_terrain':supported,'native_dem_window':bool(dem),'geometric_ephemeris_at_representative_point':True,
                      'polygon_wide_visibility':False,'verified_terrain_occlusion':False,'delay_comparison':True},
        coordinate_frame=region['coordinate_frame'],tool_version=TOOL_VERSION)


def dem_window(ctx):
    region=ctx['region'];sources=ctx['available_datasets']
    dem=next((s for s in sources if s.get('product_identifier')=='LDEM_4' and s.get('status')=='VERIFIED'),None)
    if not dem:return {'status':'INSUFFICIENT_DATA','reason':'NO_VERIFIED_DEM','samples':[]}
    root=Path(os.getenv('WISPR_GLOBAL_ROOT','data/lunar-v1'))
    arrays=native_terrain(root/'source_products/lola/ldem_4.img',SourceProduct.model_validate(dem))
    forward,inverse,_,_=projection(region['geometry']['coordinates'][0])
    poly=projected_polygon(region['geometry'],forward)
    # Geographic candidates are a bounded raster window; actual aggregation uses
    # each pixel's clipped intersection, including holes and longitude wrap.
    latitudes=[p[1] for p in region['geometry']['coordinates'][0]]
    # A polar enclosing polygon can extend farther poleward than its vertices.
    minx,miny,maxx,maxy=poly.bounds
    probes=[inverse.transform(x,y) for x in np.linspace(minx,maxx,9) for y in np.linspace(miny,maxy,9)]
    latitudes.extend(p[1] for p in probes)
    r0=max(0,int(math.floor((90-max(latitudes))*4))-2);r1=min(719,int(math.floor((90-min(latitudes))*4))+2)
    cols=set()
    for lon,lat in probes+region['geometry']['coordinates'][0]:
        center=int(math.floor((lon%360)*4))%1440
        cols.update((center+d)%1440 for d in range(-3,4))
    # Use continuous wrapped longitude span unless near a pole: all longitudes
    # can then participate. Never treat an antimeridian footprint as empty.
    ref=region['longitude_deg'];unwrapped=[ref+((p[0]-ref+180)%360-180) for p in probes+region['geometry']['coordinates'][0]]
    if r0==0 or r1==719 or max(unwrapped)-min(unwrapped)>180:cols=set(range(1440))
    else:cols=set(c%1440 for c in range(math.floor(min(unwrapped)*4)-2,math.ceil(max(unwrapped)*4)+3))
    if (r1-r0+1)*len(cols)>25000:return {'status':'INSUFFICIENT_DATA','reason':'SOURCE_PIXEL_BUDGET_EXCEEDED: select a smaller area (maximum 25000 native pixels)','samples':[]}
    samples=[]
    for r in range(r0,r1+1):
        north=90-r/4;south=north-.25
        for c in sorted(cols):
            west=c/4;east=west+.25
            # Densify latitude/longitude pixel edges (not geodesic ROI edges).
            ring=[[west+(east-west)*f,north] for f in np.linspace(0,1,5)]+[[east,north+(south-north)*f] for f in np.linspace(0,1,5)]+[[east+(west-east)*f,south] for f in np.linspace(0,1,5)]+[[west,south+(north-south)*f] for f in np.linspace(0,1,5)]
            pixel=transform(forward.transform,Polygon(ring))
            if not pixel.is_valid:continue
            area=poly.intersection(pixel).area
            if area<=poly.area*1e-12:continue
            values={name:float(a[r,c]) if np.isfinite(a[r,c]) else None for name,a in zip(('elevation_m','slope_deg','roughness_m'),arrays)}
            samples.append(dict(row=r,col=c,intersection_area_m2=area,**values))
    return {'status':'SOURCE_PIXEL_WINDOW','samples':samples,'source':dem,
            'region_area_m2':poly.area,'covered_area_m2':sum(v['intersection_area_m2'] for v in samples),
            'method':'Native source-pixel intersection weights in lunar LAEA; no resampling of physical derivatives',
            'support':ctx['measurement_support'],'tool_version':TOOL_VERSION}


def statistics(window,field):
    if window.get('status')=='INSUFFICIENT_DATA':return {'status':'INSUFFICIENT_DATA','value':None,'reason':window.get('reason'),'unit':'degree' if field=='slope_deg' else 'm'}
    if not window.get('support',{}).get('detailed_terrain_available'):
        return {'status':'INSUFFICIENT_DATA','value':None,'unit':'degree' if field=='slope_deg' else 'm',
                'reason':'Fine geometry does not resolve coarse DEM measurements','source_resolution_m':window.get('support',{}).get('source_resolution_m')}
    valid=[s for s in window['samples'] if s[field] is not None]
    area=sum(s['intersection_area_m2'] for s in valid)
    coverage=min(1,area/window['region_area_m2'])
    if not area:return {'status':'INSUFFICIENT_DATA','value':None,'coverage_fraction':0,'reason':'DEM_NODATA'}
    mean=sum(s[field]*s['intersection_area_m2'] for s in valid)/area
    return {'status':'SOURCE_BACKED_OVERVIEW','area_weighted_mean':mean,'minimum':min(s[field] for s in valid),
            'maximum':max(s[field] for s in valid),'coverage_fraction':coverage,'native_pixel_count':len(valid),
            'unit':'degree' if field=='slope_deg' else 'm','uncertainty':None,
            'source_id':window['source']['source_id'],'source_sha256':window['source']['source_checksum'],
            'method':window['method'],'definition':'native 3x3 elevation standard deviation' if field=='roughness_m' else 'native source elevation/central-gradient slope'}
