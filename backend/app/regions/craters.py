"""Catalogue-centre counts, never image-inferred crater detection."""
import json,math,os,sqlite3
from pathlib import Path
from shapely.geometry import Point
from .geometry import projection,projected_polygon,GEOD


def source():
    value=os.getenv('WISPR_CRATER_CATALOG')
    if not value:return None
    info=json.loads(Path(value).read_text())
    if info['source_records']!=1296796 or info['minimum_diameter_km']!=1 or Path(info['path']).stat().st_size!=info['byte_size']:
        raise ValueError('Crater catalogue differs from verified ingestion manifest')
    return info


def count(region):
    info=source()
    if not info:return {'status':'INSUFFICIENT_DATA','reason':'No verified crater catalogue is configured'}
    forward,_,lat,lon=projection(region['geometry']['coordinates'][0]);poly=projected_polygon(region['geometry'],forward)
    radius=max(GEOD.inv(lon,lat,*p)[2] for p in region['geometry']['coordinates'][0])/1737400
    extent=math.degrees(radius)+1e-6;south=max(-90,lat-extent);north=min(90,lat+extent)
    if south<=-90 or north>=90:ranges=[(0,360)]
    else:
        dx=math.degrees(math.asin(min(1,math.sin(radius)/math.cos(math.radians(lat)))))+1e-6
        left=lon%360-dx;right=lon%360+dx
        ranges=[(max(0,left),min(360,right))]
        if left<0:ranges.append((left+360,360))
        if right>360:ranges.append((0,right-360))
    rows={}
    with sqlite3.connect(Path(info['path']).resolve().as_uri()+'?mode=ro&immutable=1',uri=True) as db:
        db.execute('PRAGMA cache_size=-8192')
        for left,right in ranges:
            query='SELECT c.rid,c.id,c.lon,c.lat,c.diameter_km FROM locations i JOIN craters c ON c.rid=i.rid WHERE i.minx<=? AND i.maxx>=? AND i.miny<=? AND i.maxy>=? AND c.diameter_km>=1 LIMIT 50001'
            rows.update({r[0]:r for r in db.execute(query,(right,left,north,south))})
            if len(rows)>50000:return {'status':'INSUFFICIENT_DATA','reason':'Crater candidate budget exceeded; select a smaller region'}
    matched=[dict(crater_id=r[1],longitude_east_deg=r[2],latitude_deg=r[3],diameter_km=r[4]) for r in rows.values() if poly.covers(Point(*forward.transform(r[2],r[3])))]
    matched.sort(key=lambda r:(-r['diameter_km'],r['crater_id']))
    return dict(status='CATALOGUE_COUNT',count=len(matched),minimum_diameter_km=1,selection_rule='CIRCULAR_FIT_CENTRE_INSIDE_POLYGON',
        largest_diameter_km=matched[0]['diameter_km'] if matched else None,largest_catalogued_craters=matched[:20],
        source={k:v for k,v in info.items() if k!='path'},limitations=info['limitations'],method='Verified Robbins 2018 catalogue; spherical-cap index prefilter and local equal-area point-in-polygon including holes.')
