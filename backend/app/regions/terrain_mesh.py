"""Bounded, source-preserving polygon terrain extraction. No synthetic fallback."""
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Literal
from pydantic import Field

import numpy as np
import rasterio
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pyproj import CRS, Transformer
from shapely.geometry import Polygon, box, mapping
from shapely import constrained_delaunay_triangles
from rasterio.windows import Window

from . import local, store
from .geometry import projected_polygon, projection, GEOD
from .tools import Strict

VERSION = 'polygon-dem-mesh-v1'
router = APIRouter(prefix='/api/v1/science', tags=['terrain-laboratory'])


class Extraction(Strict):
    resolution: Literal['preview', 'balanced', 'native'] = 'preview'
    scope: Literal['inside','exclude','global'] = 'inside'
    allow_coarse_overview: bool = False


class RegionName(Strict):
    region_id: str = Field(max_length=150)
    name: str = Field(min_length=1,max_length=80)


@router.get('/terrain-regions')
def saved_regions():
    with store.database() as (db,p):
        rows=db.execute(f'SELECT id,payload FROM region_objects WHERE kind={p} ORDER BY id LIMIT 200',('region',)).fetchall()
        names=db.execute(f'SELECT id,payload FROM region_objects WHERE kind={p}',('region-name',)).fetchall()
    labels={key:json.loads(value)['name'] for key,value in names}
    return {'regions':[{'region':json.loads(value),'name':labels.get(key,'Research region')} for key,value in rows]}


@router.post('/terrain-regions/name')
def name_region(request: RegionName):
    try: store.get('region',request.region_id)
    except KeyError as exc: raise HTTPException(404,'Region not found') from exc
    store.put('region-name',request.region_id,{'name':request.name.strip() or 'Research region'})
    return {'saved':True}


def sources():
    registered = local.catalog()
    root = os.getenv('WISPR_GRID_DIR')
    if root and (Path(root)/'baseline/grid_metadata.json').exists():
        from app.integration.v3 import read_v3
        dataset = read_v3(root)
        meta = dataset.metadata.source['original_metadata']
        registered.append(dict(source_id=dataset.metadata.dataset_id,
            path=str(Path(root)/meta['source']['filename']),sha256=meta['source']['sha256'],
            source_url=meta['source']['url'],coordinate_frame='MOON_ME_DE421',
            vertical_reference=meta['crs']['vertical_reference'],resolution_m=5,
            grid={'crs':meta['crs']['wkt']}))
    return registered


def polygons(value):
    if value.geom_type == 'Polygon':
        yield value
    elif hasattr(value, 'geoms'):
        for part in value.geoms:
            yield from polygons(part)


def build_mesh(ds, poly, stride):
    """Intersect every source triangle, retaining holes and barycentric heights.

    The raster samples are pixel centers, not cell corners. Missing native
    samples invalidate coarse cells too: decimation never bridges NoData.
    """
    raw = rasterio.windows.from_bounds(*poly.bounds, ds.transform)
    c0 = max(0, math.floor(raw.col_off) - stride)
    r0 = max(0, math.floor(raw.row_off) - stride)
    c1 = min(ds.width - 1, math.ceil(raw.col_off + raw.width) + stride)
    r1 = min(ds.height - 1, math.ceil(raw.row_off + raw.height) + stride)
    if c1 <= c0 or r1 <= r0:
        raise ValueError('NO_DATA: polygon outside raster sample support')
    if (c1-c0+1)*(r1-r0+1) > 16_000_000:
        raise ValueError('Native read exceeds 16 million samples; select a smaller region')
    rows = list(range(r0, r1+1, stride)); cols = list(range(c0, c1+1, stride))
    if rows[-1] != r1: rows.append(r1)
    if cols[-1] != c1: cols.append(c1)
    if (len(rows)-1)*(len(cols)-1)*2 > 100_000:
        raise ValueError('Mesh exceeds 100,000 source triangles; choose preview or a smaller region')
    data = ds.read(1, window=Window(c0,r0,c1-c0+1,r1-r0+1), masked=True).astype(float).filled(np.nan)
    vertices = []; faces = []; vertex_ids = {}; area = 0.0
    def index(v):
        key = tuple(round(float(x), 8) for x in v)
        if key not in vertex_ids:
            vertex_ids[key] = len(vertices); vertices.append([float(x) for x in v])
        return vertex_ids[key]
    for r, rr in zip(rows, rows[1:]):
        for c, cc in zip(cols, cols[1:]):
            if not np.isfinite(data[r-r0:rr-r0+1,c-c0:cc-c0+1]).all(): continue
            points = np.array([(*(ds.transform*(col+.5,row+.5)), data[row-r0,col-c0])
                               for row,col in [(r,c),(r,cc),(rr,c),(rr,cc)]])
            for ids in [(0,2,1),(1,2,3)]:
                xyz = points[list(ids)]; triangle = Polygon(xyz[:,:2])
                if not triangle.intersects(poly): continue
                clipped = triangle.intersection(poly)
                plane = np.linalg.solve(np.column_stack((xyz[:,:2],np.ones(3))),xyz[:,2])
                for part in polygons(clipped):
                    for tri in constrained_delaunay_triangles(part).geoms:
                        if tri.area <= 1e-10 or not part.covers(tri): continue
                        xy = np.asarray(tri.exterior.coords)[:3]
                        a,b = xy[1]-xy[0],xy[2]-xy[0]
                        if a[0]*b[1]-a[1]*b[0] < 0: xy = xy[::-1]
                        face = [index((x,y,plane[0]*x+plane[1]*y+plane[2])) for x,y in xy]
                        faces.append(face); area += tri.area
    if not faces: raise ValueError('NO_DATA: no complete source triangles intersect polygon')
    return vertices, faces, area


def extract(region, resolution, scope='inside', allow_coarse_overview=False):
    if region['coordinate_frame'] != 'MOON_ME_DE421':
        raise ValueError('Unsupported lunar frame; explicit transformation required')
    choices = []
    for source in sources():
        crs = CRS.from_user_input(source['grid']['crs'])
        forward = Transformer.from_crs(crs.geodetic_crs,crs,always_xy=True)
        poly = projected_polygon(region['geometry'],forward)
        with rasterio.open(source['path']) as ds:
            if poly.intersects(box(*ds.bounds)): choices.append((source,poly))
    if not choices:
        if allow_coarse_overview:
            return overview_mesh(region,resolution,scope)
        raise ValueError('No high-resolution DEM is registered for this selection. Enable coarse LOLA overview to inspect available global terrain (about 7.58 km latitude spacing), or configure a verified regional DEM for detailed extraction.')
    source, poly = min(choices,key=lambda item:item[0]['resolution_m'])
    with rasterio.open(source['path']) as ds:
        if scope not in ('inside','exclude','global'): raise ValueError('Invalid scope')
        domain=box(ds.bounds.left+ds.res[0]/2,ds.bounds.bottom+ds.res[1]/2,
                   ds.bounds.right-ds.res[0]/2,ds.bounds.top-ds.res[1]/2)
        if scope=='global': poly=domain
        elif scope=='exclude': poly=domain.difference(poly)
        if poly.is_empty or poly.area<=0: raise ValueError('NO_DATA: empty analysis scope')
        raw = rasterio.windows.from_bounds(*poly.bounds,ds.transform)
        budget = {'preview':2048,'balanced':12000,'native':50000}[resolution]
        stride = 1 if resolution == 'native' else max(1,math.ceil(math.sqrt(raw.width*raw.height/budget)))
        vertices, faces, covered = build_mesh(ds,poly,stride)
        crs_wkt = ds.crs.to_wkt(); spacing = list(ds.res)
    return mesh_result(region,source,poly,vertices,faces,covered,crs_wkt,spacing,stride,resolution,scope)


def mesh_result(region,source,poly,vertices,faces,covered,crs_wkt,spacing,stride,resolution,scope):
    z = [v[2] for v in vertices]
    origin = [float(poly.centroid.x),float(poly.centroid.y),min(z)]
    manifest = dict(algorithm=VERSION,region_id=region['region_id'],coordinate_frame=region['coordinate_frame'],
        crs_wkt=crs_wkt,units='metre',vertical_reference=source['vertical_reference'],
        source_id=source['source_id'],source_sha256=source['sha256'],source_url=source.get('source_url',source.get('canonical_url')),
        native_spacing_m=spacing,effective_spacing_m=[s*stride for s in spacing],stride=stride,
        resolution=resolution,scope=scope,scope_domain='Selected source DEM sample-center footprint',triangle_count=len(faces),vertex_count=len(vertices),display_origin_m=origin,
        projected_region_area_m2=poly.area,covered_area_m2=covered,coverage_fraction=min(1,covered/poly.area),
        elevation_min_m=min(z),elevation_max_m=max(z),relief_m=max(z)-min(z),
        perimeter_m=sum(GEOD.line_length(*zip(*ring)) for ring in region['geometry']['coordinates']),
        interpolation='piecewise planar between DEM pixel centers; exact planar triangle clipping',
        uncertainty=source.get('uncertainty_source','Not supplied; spacing is not accuracy'),
        limitations=['One finest intersecting DEM; no multi-tile mosaic yet.',
          'LOD decimation changes geometric detail; native NoData cells remain excluded.',
          'Coverage ends at source sample centers. Sidewalls are display geometry only.',
          'Sun/Earth visibility is not calculated by terrain extraction.'])
    if source.get('overview'):
        manifest.update(data_quality='COARSE_OVERVIEW_ONLY',native_angular_spacing_deg=0.25,
            source_nominal_latitude_spacing_m=source['resolution_m'],native_spacing_m=None,
            source_sampling='0.25 degrees longitude/latitude; east-west ground spacing varies with latitude',
            interpolation='Bilinear global LOLA samples on a local equal-area display grid, then planar triangle clipping',
            scope_domain='Selected polygon only',limitations=source['limitations']+manifest['limitations'])
    key = hashlib.sha256(json.dumps({'manifest':manifest,'geometry':region['geometry']},sort_keys=True).encode()).hexdigest()
    return dict(mesh_id=key,manifest=manifest,geometry=region['geometry'],vertices=vertices,triangles=faces)


def overview_mesh(region,resolution,scope):
    """Explicit opt-in overview. Never promote display sampling to source detail."""
    from rasterio.io import MemoryFile
    from rasterio.transform import from_origin
    from lunar_global.sources import SourceProduct
    from lunar_global.features import native_terrain
    if resolution=='native':
        raise ValueError('Native regional detail is unavailable here. Choose Preview or Balanced for the coarse global overview.')
    if scope!='inside':
        raise ValueError('Coarse overview supports Inside polygon only. Global/exclude scopes require a registered regional DEM.')
    directory=Path(os.getenv('WISPR_GLOBAL_ROOT','data/lunar-v1'))/'source_products/lola'
    try:
        product=SourceProduct.model_validate_json((directory/'source.json').read_text())
        if product.product_identifier!='LDEM_4' or product.coordinate_frame!=region['coordinate_frame'] or product.status!='VERIFIED':
            raise ValueError('Global DEM identity, status or coordinate frame mismatch')
        z,_,_=native_terrain(directory/'ldem_4.img',product)
    except (OSError,ValueError) as exc:
        raise ValueError('Verified global LOLA overview is unavailable or failed integrity checks') from exc
    forward,inverse,_,_=projection(region['geometry']['coordinates'][0])
    poly=projected_polygon(region['geometry'],forward)
    step=float(product.spatial_resolution_m)
    left,bottom,right,top=poly.bounds
    left=math.floor(left/step)*step-step;top=math.ceil(top/step)*step+step
    width=max(3,math.ceil((right-left)/step)+2);height=max(3,math.ceil((top-bottom)/step)+2)
    if width*height>50000: raise ValueError('Overview exceeds 50,000 display samples; select a smaller region')
    affine=from_origin(left,top,step,step)
    yy,xx=np.indices((height,width));x=left+(xx+.5)*step;y=top-(yy+.5)*step
    lon,lat=inverse.transform(x,y)
    valid=np.isfinite(lon)&np.isfinite(lat)&(lat>=-89.875)&(lat<=89.875)
    rr=np.clip((90-np.where(valid,lat,0))*4-.5,0,719)
    cc=(np.where(valid,lon,0)%360)*4-.5
    r0=np.floor(rr).astype(int);r1=np.minimum(r0+1,719)
    c0=np.floor(cc).astype(int)%1440;c1=(c0+1)%1440
    fr=rr-r0;fc=cc-np.floor(cc)
    values=(1-fr)*((1-fc)*z[r0,c0]+fc*z[r0,c1])+fr*((1-fc)*z[r1,c0]+fc*z[r1,c1])
    values[~valid]=np.nan
    crs=forward.target_crs
    with MemoryFile() as mem:
        with mem.open(driver='GTiff',width=width,height=height,count=1,dtype='float64',crs=crs,transform=affine,nodata=np.nan) as ds:
            ds.write(values,1)
            vertices,faces,covered=build_mesh(ds,poly,1)
    source=dict(source_id=product.source_id,sha256=product.source_checksum,source_url=product.canonical_url,
        vertical_reference=product.vertical_reference,resolution_m=step,overview=True,
        uncertainty_source='Unknown; coarse interpolated overview, not local terrain measurements.',
        limitations=['COARSE OVERVIEW ONLY: 0.25-degree source; approximately 7.58 km latitude spacing.',
          'Small polygons may contain no independent source samples. Relief and slope are display interpolation, not measured local detail.',
          'No extrapolation beyond native polar sample centers; no shadow or Earth-visibility inference.'])
    return mesh_result(region,source,poly,vertices,faces,covered,crs.to_wkt(),[step,step],1,resolution,scope)


@router.post('/regions/{region_id}/terrain')
def extract_route(region_id: str, request: Extraction):
    try:
        result = extract(store.get('region',region_id),request.resolution,request.scope,request.allow_coarse_overview)
        store.put('terrain',result['mesh_id'],result)
        return result
    except KeyError as exc: raise HTTPException(404,'Region not found') from exc
    except (ValueError, OSError) as exc: raise HTTPException(422,str(exc)) from exc


@router.get('/terrain/{mesh_id}')
def retrieve(mesh_id: str):
    try: return store.get('terrain',mesh_id)
    except KeyError as exc: raise HTTPException(404,'Terrain not found') from exc


@router.get('/terrain/{mesh_id}/export/{kind}')
def export(mesh_id: str, kind: Literal['obj','json','geojson']):
    result = retrieve(mesh_id)
    if kind == 'obj':
        text = '# WISPR projected metres, source Z-up. Download JSON manifest for georeferencing.\n'
        text += '\n'.join('v '+' '.join(format(x,'.12g') for x in p) for p in result['vertices'])+'\n'
        text += '\n'.join('f '+' '.join(str(i+1) for i in f) for f in result['triangles'])
        media = 'text/plain'
    else:
        value = result if kind == 'json' else {'type':'Feature','geometry':result['geometry'],
            'properties':{'lunar_reference':result['manifest'],'warning':'Lunar coordinates, not Earth WGS84'}}
        text = json.dumps(value,allow_nan=False); media = 'application/json'
    return Response(text,media_type=media,headers={'Content-Disposition':f'attachment; filename="wispr-{mesh_id[:16]}.{kind}"'})
