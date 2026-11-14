"""Spherical south-polar stereographic; x east at lon=90, y toward lon=0."""
import math
import re
from app.catalog import SITES
from app.metadata import metadata

RADIUS = 1737400.0
PROJECTION = dict(name='MOON_SOUTH_POLAR_STEREOGRAPHIC',
    wkt_or_proj='+proj=stere +lat_0=-90 +lat_ts=-90 +lon_0=0 +R=1737400 +units=m +no_defs',
    axis_units='metre', reference_radius_m=RADIUS,
    frame='Canonical spherical lunar ME grid; terrain frame transformations require separate verification')


def project(lat, lon):
    if not -90 <= lat < 90:
        raise ValueError('South-polar projection excludes the north pole')
    rho = 2 * RADIUS * math.tan(math.pi / 4 + math.radians(lat) / 2)
    return rho * math.sin(math.radians(lon)), rho * math.cos(math.radians(lon))


def unproject(x, y):
    return math.degrees(2 * math.atan(math.hypot(x, y) / (2 * RADIUS)) - math.pi / 2), math.degrees(math.atan2(x, y)) % 360


def cell_at(lat, lon):
    x, y = project(lat, lon)
    return cell(math.floor(x / 1000), math.floor(y / 1000))


def cell(ix, iy):
    x, y = (ix + .5) * 1000, (iy + .5) * 1000
    lat, lon = unproject(x, y)
    corners = [unproject(a * 1000, b * 1000) for a, b in [(ix, iy), (ix+1, iy), (ix+1, iy+1), (ix, iy+1), (ix, iy)]]
    return dict(cell_id=f'SP1KM:{ix}:{iy}', grid_version='south_polar_v1', cell_size_m=1000,
        center_lat_deg=lat, center_lon_east_deg=lon, center_x_m=x, center_y_m=y,
        boundary_lonlat_east=[[lo, la] for la, lo in corners], raster_coverage='UNVERIFIED',
        ephemeris_status='UNEVALUATED', observations_represent_center_only=True)


def lookup(cell_id):
    match = re.fullmatch(r'SP1KM:(-?\d{1,4}):(-?\d{1,4})', cell_id)
    if not match:
        raise ValueError('Invalid canonical cell ID')
    ix, iy = map(int, match.groups())
    if abs(ix) > 4000 or abs(iy) > 4000:
        raise ValueError('Cell outside supported south-polar scope')
    return cell(ix, iy)


def neighborhood(site_id, radius=1):
    site = SITES[site_id]
    x, y = project(site['lat_deg'], site['lon_east_deg'])
    ix, iy = math.floor(x/1000), math.floor(y/1000)
    return dict(site_id=site_id, grid_version='south_polar_v1', projection=PROJECTION,
        center_cell_id=f'SP1KM:{ix}:{iy}', cells=[cell(ix+a, iy+b) for a in range(-radius, radius+1) for b in range(-radius, radius+1)],
        **metadata(limitations=['Grid construction performs no astronomy requests. Reference-point results do not evaluate a containing cell center.']))
