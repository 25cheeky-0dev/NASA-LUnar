"""Read only explicitly configured, source-documented local NASA rasters."""
import hashlib
import json
import math
import os
from functools import lru_cache
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


def horizon(site_id, observer_height_m, az_step_deg, *, position=None, azimuths_deg=None):
    """Compatible provider entry point, now using the shared full-raster engine.

    Existing callers retain diagnostic angular steps. New callers can request
    exact azimuths. Use compare_ephemeris for reference-checked target decisions.
    """
    import numpy as np

    from .terrain_horizon import TerrainHorizonEngine

    if not math.isfinite(az_step_deg) or not 0.018 <= az_step_deg <= 360:
        raise ValueError('Invalid diagnostic azimuth step')
    raster, manifest, x, y, digest = load(site_id, position=position)
    path = raster.name
    raster.close()
    latitude, longitude = position if position is not None else (SITES[site_id]['lat_deg'], SITES[site_id]['lon_east_deg'])
    engine = TerrainHorizonEngine(path, {site_id: dict(latitude_deg=latitude,
        longitude_east_deg=longitude, x_m=x, y_m=y)}, digest, provenance=manifest)
    result = engine.compute_horizon(site_id, observer_height_m,
        np.arange(0, 360, az_step_deg) if azimuths_deg is None else azimuths_deg)
    if azimuths_deg is None:
        result.update(angular_resolution_deg=az_step_deg, direction_mode='DIAGNOSTIC_SKYLINE')
    for ray in result['azimuth_samples']:
        obstruction = ray.get('obstruction') or {}
        ray['controlling_obstruction_distance_m'] = obstruction.get('distance_m')
        ray['controlling_obstruction_elevation_m'] = obstruction.get('source_elevation_m')
    # Retain provider metadata and original provenance without asserting a datum.
    base = metadata('NASA_LOLA_DEM', 'TERRAIN_PARTIAL', 'PARTIAL')
    return dict(base, **result)


def compute_horizon(cell_id, observer_height_m, azimuths_deg, *, engine=None):
    """V3 library entry point; reuse an explicit engine for bounded cached calls."""
    if engine is None:
        root = os.getenv('WISPR_TERRAIN_V3_DIR')
        if not root:
            raise TerrainUnavailable('Configure WISPR_TERRAIN_V3_DIR or pass a V3 engine')
        root = Path(root).resolve()
        files = [root / 'SHA256_MANIFEST.json', root / 'Site04_final_adj_5mpp_surf.tif']
        generation = tuple((p.stat().st_size, p.stat().st_mtime_ns) for p in files)
        engine = _configured_v3_engine(str(root), generation)
    return engine.compute_horizon(cell_id, observer_height_m, azimuths_deg)


@lru_cache(maxsize=2)
def _configured_v3_engine(root, generation):
    """Bounded process snapshots; changed source/manifest stats trigger revalidation."""
    from .terrain_horizon import TerrainHorizonEngine

    return TerrainHorizonEngine.from_v3(root)
