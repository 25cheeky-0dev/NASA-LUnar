"""Read only explicitly configured, source-documented local NASA rasters."""
import hashlib
import json
import math
import os
from pathlib import Path
from app.catalog import SITES
from app.metadata import metadata
from app.science.grid import RADIUS

NASA = 'https://pgda.gsfc.nasa.gov/data/LOLA_5mpp/'


class TerrainUnavailable(Exception):
    pass


def load(site_id, position=None):
    path = os.getenv('DEM_'+site_id)
    if not path:
        raise TerrainUnavailable('No source-documented local DEM configured')
    try:
        import rasterio
        from pyproj import CRS, Transformer
        raster = rasterio.open(path)
        manifest = json.loads(Path(path+'.json').read_text())
        if manifest['z_units'] != 'metre' or not manifest['source_url'].startswith(NASA) or manifest['frame'] != 'MOON_ME_DE421':
            raise ValueError('Unverified source, units or lunar frame')
        if not manifest.get('vertical_reference'):
            raise ValueError('Missing vertical reference')
        with open(path, 'rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if digest != manifest['raw_sha256']:
            raise ValueError('Raster hash mismatch')
        crs = CRS.from_user_input(raster.crs)
        if not crs.is_projected or any(axis.unit_name.lower() not in ('metre', 'meter') for axis in crs.axis_info):
            raise ValueError('Require metre-based projected lunar raster')
        if abs(crs.ellipsoid.semi_major_metre-RADIUS) > 1:
            raise ValueError('Unexpected lunar radius / Earth CRS')
        if abs(raster.transform.b) > 1e-9 or abs(raster.transform.d) > 1e-9:
            raise ValueError('Rotated raster needs explicit resampling')
        transformer = Transformer.from_crs(crs.geodetic_crs, crs, always_xy=True)
        lat, lon = position if position is not None else (SITES[site_id]['lat_deg'], SITES[site_id]['lon_east_deg'])
        x, y = transformer.transform(lon, lat)
        if not (raster.bounds.left <= x < raster.bounds.right and raster.bounds.bottom < y <= raster.bounds.top):
            raise ValueError('OUTSIDE_DEM_FOOTPRINT')
        return raster, manifest, x, y, digest
    except (ImportError, OSError, ValueError, KeyError) as exc:
        if 'raster' in locals():
            raster.close()
        raise TerrainUnavailable(str(exc)) from exc


def terrain_metadata(site_id):
    try:
        raster, manifest, x, y, digest = load(site_id)
        with raster:
            return dict(site_id=site_id, coverage='PARTIAL', verified_import_state='HASH_AND_FOOTPRINT_CHECKED',
                crs_wkt=raster.crs.to_wkt(), xy_units='metre', z_units='metre', vertical_reference=manifest['vertical_reference'],
                nodata=raster.nodata, width=raster.width, height=raster.height, resolution_m=list(raster.res),
                bounding_box=list(raster.bounds), observing_point_xy_m=[x,y], far_field_complete=False,
                uncertainty_source=manifest.get('uncertainty_source', 'Not supplied; pixel size is not measurement accuracy'),
                **metadata('NASA_LOLA_DEM', 'TERRAIN_PARTIAL', 'PARTIAL',
                    dict(dataset_ids=[SITES[site_id]['dem_site_id']], source_urls=[manifest['source_url']], raw_sha256=[digest],
                         coordinate_frame=manifest['frame'], request_params={}, sample_step_minutes=None)))
    except TerrainUnavailable as exc:
        return dict(site_id=site_id, coverage='UNAVAILABLE', verified_import_state='UNVERIFIED', far_field_complete=False,
            reason=str(exc), **metadata(mode='TERRAIN_UNAVAILABLE', limitations=[str(exc)]))


def heightmap(site_id, size_m, max_points):
    import numpy as np
    from rasterio.enums import Resampling
    from rasterio.windows import from_bounds
    raster, manifest, x, y, digest = load(site_id)
    with raster:
        size = min(max_points, max(2, int(size_m/min(raster.res))))
        win = from_bounds(x-size_m/2, y-size_m/2, x+size_m/2, y+size_m/2, raster.transform)
        data = raster.read(1, window=win, out_shape=(size,size), masked=True, boundless=True, resampling=Resampling.nearest)
        mask = np.ma.getmaskarray(data) | ~np.isfinite(data.filled(np.nan))
        z = [[None if mask[j,i] else float(data[j,i]) for i in range(size)] for j in range(size)]
        return dict(origin_x_m=x-size_m/2+size_m/(2*size), origin_y_m=y+size_m/2-size_m/(2*size),
            dx_m=size_m/size, dy_m=-size_m/size, z_m=z, nodata_mask=mask.tolist(),
            origin_convention='Center of first pixel; rows follow negative projected y',
            projection={'wkt_or_proj': raster.crs.to_wkt()}, coverage='PARTIAL',
            source={'url': manifest['source_url'], 'raw_sha256': digest}, **metadata('NASA_LOLA_DEM', 'TERRAIN_PARTIAL', 'PARTIAL'))


def curvature_angle(distance_m, delta_height_m):
    theta = distance_m/RADIUS
    return math.degrees(math.atan2((RADIUS+delta_height_m)*math.cos(theta)-RADIUS, (RADIUS+delta_height_m)*math.sin(theta)))


def horizon(site_id, observer_height_m, az_step_deg, *, position=None):
    import numpy as np
    from pyproj import Geod, CRS, Transformer
    raster, manifest, x, y, digest = load(site_id, position=position)
    with raster:
        origin = next(raster.sample([(x,y)], masked=True))[0]
        if np.ma.is_masked(origin) or not np.isfinite(origin):
            raise TerrainUnavailable('Observer falls on DEM NoData')
        crs = CRS.from_user_input(raster.crs)
        transformer = Transformer.from_crs(crs.geodetic_crs, crs, always_xy=True)
        geod = Geod(a=RADIUS,b=RADIUS)
        latitude, longitude = position if position is not None else (SITES[site_id]['lat_deg'], SITES[site_id]['lon_east_deg'])
        spacing = max(10., max(raster.res))
        max_radius = min(20000., math.hypot(raster.bounds.right-raster.bounds.left, raster.bounds.top-raster.bounds.bottom))
        distances = np.arange(spacing,max_radius,spacing)
        samples = []
        radii = []
        for az in range(0,360,az_step_deg):
            lon, lat, _ = geod.fwd(np.full(len(distances),longitude), np.full(len(distances),latitude), np.full(len(distances),az), distances)
            xs, ys = transformer.transform(lon,lat)
            vals = list(raster.sample(zip(xs,ys), masked=True))
            angles, obstructions, supported = [], [], 0.
            for d, xx, yy, value in zip(distances,xs,ys,vals):
                if not (raster.bounds.left <= xx < raster.bounds.right and raster.bounds.bottom < yy <= raster.bounds.top) or np.ma.is_masked(value[0]) or not np.isfinite(value[0]):
                    break
                angles.append(curvature_angle(float(d), float(value[0])-float(origin)-observer_height_m))
                obstructions.append((float(d), float(value[0])))
                supported = float(d)
            radii.append(supported)
            samples.append(dict(azimuth_deg=az, terrain_horizon_elevation_deg=max(angles) if angles else None,
                coverage='PARTIAL' if angles else 'UNKNOWN', uncertainty_deg=None, supported_radius_m=supported,
                controlling_obstruction_distance_m=obstructions[int(np.argmax(angles))][0] if angles else None,
                controlling_obstruction_elevation_m=obstructions[int(np.argmax(angles))][1] if angles else None))
        return dict(observation_position=dict(latitude_deg=latitude, longitude_east_deg=longitude), source_manifest=manifest, raster_sha256=digest, azimuth_samples=samples, max_supported_radius_m=max(radii,default=0), far_field_complete=False,
            observer_ground_height_m=float(origin), observer_height_m=observer_height_m,
            **metadata('NASA_LOLA_DEM','TERRAIN_PARTIAL','PARTIAL',limitations=[
                'Finite local DEM cannot certify clear far-field sectors. No terrain-mode eligibility is inferred.',
                'Curvature uses a spherical Moon; azimuth rays use geodesic forward coordinates.']))
