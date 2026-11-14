"""Source-independent identities on a lunar sphere; local equal-area intersections."""
import hashlib
import math
import json
import numpy as np
from astropy import units as u
from pyproj import CRS, Geod, Transformer
from shapely.geometry import Polygon, mapping
from shapely.ops import transform
from lunar_global.grid import RADIUS_M, FRAME, GRID_VERSION, describe, lookup, hpx, cell_id

ALGORITHM='lunar-geodesic-roi-v1'
GEOD=Geod(a=RADIUS_M,b=RADIUS_M)
MAX_INTERSECTIONS=512


def nside_for_width(width):
    # Select the nearest supported power of two, and disclose actual width.
    raw=math.sqrt(4*math.pi/12)*RADIUS_M/width
    return int(2**min(15,max(0,round(math.log2(raw)))))


def canonical_ring(ring):
    if not 4<=len(ring)<=257:raise ValueError('Ring needs 3–256 vertices and closure')
    points=[]
    for lon,lat in ring:
        if not math.isfinite(lon) or not math.isfinite(lat) or not -90<=lat<=90:
            raise ValueError('Finite lunar longitude/latitude required')
        points.append((round((lon+180)%360-180,9),round(lat,9)))
    if points[0]!=points[-1]:raise ValueError('Polygon ring must be closed')
    points=points[:-1]
    if len(set(points))!=len(points):raise ValueError('Repeated polygon vertex')
    def rotate(p):
        index=min(range(len(p)),key=lambda i:p[i]);return p[index:]+p[:index]
    points=min(rotate(points),rotate(list(reversed(points))))
    return [list(p) for p in points+[points[0]]]


def projection(ring):
    xyz=[]
    for lon,lat in ring[:-1]:
        a,b=math.radians(lon),math.radians(lat)
        xyz.append([math.cos(b)*math.cos(a),math.cos(b)*math.sin(a),math.sin(b)])
    x,y,z=np.mean(xyz,axis=0);norm=math.sqrt(x*x+y*y+z*z)
    if norm<.5:raise ValueError('ROI must fit within one bounded lunar study region')
    lat=math.degrees(math.asin(z/norm));lon=math.degrees(math.atan2(y,x))
    crs=CRS.from_proj4(f'+proj=laea +lat_0={lat} +lon_0={lon} +R={RADIUS_M} +units=m')
    return Transformer.from_crs(crs.geodetic_crs,crs,always_xy=True),Transformer.from_crs(crs,crs.geodetic_crs,always_xy=True),lat,lon


def densify(ring,max_step_m=2000):
    result=[]
    for a,b in zip(ring,ring[1:]):
        result.append(a)
        distance=GEOD.inv(*a,*b)[2]
        count=max(0,math.ceil(distance/max_step_m)-1)
        if count>1000:raise ValueError('Polygon edge exceeds bounded study budget')
        if count:result.extend(GEOD.npts(*a,*b,count))
    return result+[result[0]]


def projected_polygon(geometry,forward):
    rings=[densify(r) for r in geometry['coordinates']]
    poly=transform(forward.transform,Polygon(rings[0],rings[1:]))
    if not poly.is_valid or poly.is_empty or poly.area<=0:
        raise ValueError('Invalid or self-intersecting lunar polygon')
    return poly


def polygon_region(geometry,nside):
    if geometry.get('type')!='Polygon':raise ValueError('Only Polygon selection is supported')
    rings=geometry['coordinates']
    if not 1<=len(rings)<=5:raise ValueError('At most four holes supported')
    canonical={'type':'Polygon','coordinates':[canonical_ring(rings[0])]+sorted(canonical_ring(r) for r in rings[1:])}
    forward,inverse,lat,lon=projection(canonical['coordinates'][0])
    poly=projected_polygon(canonical,forward)
    if poly.area>1e11:raise ValueError('ROI exceeds 100,000 square kilometre study budget')
    center=poly.representative_point();clon,clat=inverse.transform(center.x,center.y)
    radius=max(GEOD.inv(lon,lat,*p)[2] for p in densify(canonical['coordinates'][0]))/RADIUS_M
    if radius>.35:raise ValueError('ROI angular radius exceeds 20 degrees')
    area_per_cell=4*math.pi*RADIUS_M**2/int(hpx(nside).npix)
    if 2*math.pi*RADIUS_M**2*(1-math.cos(radius))/area_per_cell>MAX_INTERSECTIONS:
        raise ValueError('Selection would exceed 512 intersections; choose a coarser grid or smaller polygon')
    pixels=hpx(nside).cone_search_lonlat((lon%360)*u.deg,lat*u.deg,(radius+1e-9)*u.rad)
    if len(pixels)>MAX_INTERSECTIONS*4:raise ValueError('Candidate intersection budget exceeded')
    overlaps=[]
    for pixel in pixels:
        info=describe(cell_id(nside,int(pixel)),step=16)
        candidate=transform(forward.transform,Polygon(info['boundary_lonlat']))
        if not candidate.is_valid:continue
        clipped=poly.intersection(candidate)
        if clipped.area>max(1e-8,poly.area*1e-12):
            if len(overlaps)>=MAX_INTERSECTIONS:raise ValueError('Intersection budget exceeded')
            geographic=transform(inverse.transform,clipped)
            overlaps.append({'cell_id':info['cell_id'],'intersection_area_m2':clipped.area,
                             'region_fraction':clipped.area/poly.area,'geometry':mapping(geographic)})
    overlaps.sort(key=lambda x:x['cell_id'])
    value={'algorithm':ALGORITHM,'coordinate_frame':FRAME,'geometry':canonical}
    key='MOON:ROI:'+hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return dict(region_id=key,kind='POLYGON',geometry=canonical,latitude_deg=clat,longitude_deg=clon%360,
                center_method='interior representative point; never a substitute for polygon support',
                area_m2=poly.area,nominal_width_m=math.sqrt(poly.area),coordinate_frame=FRAME,
                reference_radius_m=RADIUS_M,geometry_version=ALGORITHM,grid_version=GRID_VERSION,
                parent_id=None,children=[],neighbors=[],intersections=overlaps,
                intersection_method='LAEA on lunar sphere; geodesic ROI edges densified at 2 km; sampled HEALPix edges',
                intersection_area_error_fraction=abs(sum(x['intersection_area_m2'] for x in overlaps)-poly.area)/poly.area)


def cell_region(value):
    info=describe(value)
    return dict(region_id=value,kind='HEALPIX',geometry={'type':'Polygon','coordinates':[info['boundary_lonlat']]},
                latitude_deg=info['latitude_deg'],longitude_deg=info['longitude_deg'],
                area_m2=info['area_m2'],nominal_width_m=math.sqrt(info['area_m2']),coordinate_frame=FRAME,
                reference_radius_m=RADIUS_M,geometry_version=GRID_VERSION,grid_version=GRID_VERSION,
                parent_id=info['parent_id'],children=info['children'],neighbors=info['neighbors'],intersections=[],
                boundary_method=info['boundary_method'])
