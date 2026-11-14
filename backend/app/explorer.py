"""Small, traceable rendering and report adapters around the canonical science."""
import hashlib
import json
import os
from functools import lru_cache
from pathlib import Path

import numpy as np
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from app import persistence
from app.integration.api import DelayRequest, delay
from app.navigation import demo_delay
from lunar_global.api import delay as global_delay, GlobalDelay
from lunar_global.sources import SourceProduct
from lunar_global.features import native_terrain

router = APIRouter(prefix='/api/v1/explorer', tags=['explorer'])


class ReportRef(BaseModel):
    model_config = ConfigDict(extra='forbid')
    report_id: str
    result: dict
    report_url: str


def record(result):
    envelope = {'schema_version': 'wispr-evidence-1', 'result': result,
                'limitations': ['Geometric visibility is not landing safety.',
                                'Terrain visibility: UNKNOWN — insufficient verified geometry.'],
                'software_revision': os.getenv('WISPR_REVISION', 'local-release'),
                'coordinate_frame': 'MOON_ME_DE421', 'delay_hours': 168}
    key = persistence.save(envelope, 'delay')
    return {'report_id': key, 'result': result, 'report_url': f'/api/v1/explorer/reports/{key}'}


@router.post('/demo', response_model=ReportRef)
def recorded_demo():
    return record(demo_delay())


@router.post('/delay', response_model=ReportRef)
def compare(request: DelayRequest):
    return record(global_delay(GlobalDelay.model_validate(request.model_dump())) if request.dataset_id == 'GLOBAL_SELECTED' else delay(request))


@router.get('/reports/{key}')
def report(key: str):
    try:
        value = persistence.read(key)
        return JSONResponse(value, headers={'Content-Disposition': f'attachment; filename="wispr-{key}.json"',
                                            'X-Content-SHA256': key, 'Cache-Control': 'private, max-age=31536000, immutable'})
    except KeyError as exc:
        raise HTTPException(404, 'Report not found') from exc
    except ValueError as exc:
        raise HTTPException(503, 'Report integrity validation failed') from exc


@lru_cache(maxsize=2)
def terrain_source(root, image_size, image_mtime):
    directory = Path(root) / 'source_products/lola'
    source = SourceProduct.model_validate_json((directory / 'source.json').read_text())
    arrays = native_terrain(directory / 'ldem_4.img', source)
    return source, arrays


@router.get('/surface')
def surface(latitude: float = Query(-88, ge=-89.5, le=89.5),
            longitude: float = Query(0, ge=-180, le=360),
            extent_km: float = Query(450, ge=20, le=900),
            resolution: int = Query(96, ge=16, le=160)):
    """Bounded projected mesh of the validated LOLA product; no fake detail.

    Grid samples use nearest native pixels. The renderer interpolates triangles,
    which is display interpolation, not a new measurement or accuracy claim.
    """
    from pyproj import CRS, Transformer
    from lunar_global.grid import FRAME, GRID_VERSION, RADIUS_M
    root = os.getenv('WISPR_GLOBAL_ROOT', 'data/lunar-v1')
    image = Path(root) / 'source_products/lola/ldem_4.img'
    try:
        stat = image.stat()
        source, arrays = terrain_source(root, stat.st_size, stat.st_mtime_ns)
    except (OSError, ValueError) as exc:
        raise HTTPException(503, 'Verified LOLA surface unavailable; configure WISPR_GLOBAL_ROOT') from exc
    crs = CRS.from_proj4(f'+proj=aeqd +lat_0={latitude} +lon_0={longitude} +R={RADIUS_M} +units=m')
    transformer = Transformer.from_crs(crs, crs.geodetic_crs, always_xy=True)
    axis = np.linspace(-extent_km * 500, extent_km * 500, resolution)
    xx, yy = np.meshgrid(axis, -axis)
    lon, lat = transformer.transform(xx, yy)
    rows = np.clip(np.floor((90-lat)*4).astype(int), 0, 719)
    cols = np.floor((lon % 360)*4).astype(int) % 1440
    fields = {name: [[float(v) if np.isfinite(v) else None for v in row] for row in array[rows, cols]]
              for name, array in zip(('elevation_m', 'slope_deg', 'roughness_m'), arrays)}
    # Explicit bilinear display interpolation of native height pixels. Physical
    # cell measurements continue to come from canonical source-backed features.
    rr=np.clip((90-lat)*4-.5,0,719); cc=(lon%360)*4-.5
    r0=np.floor(rr).astype(int); r1=np.minimum(r0+1,719)
    c0=np.floor(cc).astype(int)%1440; c1=(c0+1)%1440
    fr=rr-r0; fc=cc-np.floor(cc); z=arrays[0]
    display=(1-fr)*((1-fc)*z[r0,c0]+fc*z[r0,c1])+fr*((1-fc)*z[r1,c0]+fc*z[r1,c1])
    fields['elevation_m']=display.tolist()
    return {'width': resolution, 'height': resolution, 'extent_m': extent_km*1000,
            'latitude': lat.tolist(), 'longitude': (lon % 360).tolist(), **fields,
            'coordinate_frame': FRAME, 'grid_version': GRID_VERSION, 'projection': crs.to_wkt(),
            'reference_radius_m': RADIUS_M, 'source': source.model_dump(),
            'render_sampling': 'bilinear native 0.25-degree elevation for display; nearest native derivative pixels; not new measurements',
            'terrain_visibility': 'UNKNOWN', 'uncertainty': None,
            'limitations': ['Global LDEM_4 overview; 7.58 km nominal latitude spacing, not local landing terrain.',
                            'Slope and 3x3 roughness computed at native source resolution.',
                            'Polar first/last row slope and roughness unavailable.',
                            'Display mesh spacing is not source resolution.']}


@router.get('/runtime')
def runtime():
    from app.providers.gemini import configured
    return {'gemini': 'CONFIGURED_NOT_TESTED' if configured() else 'UNCONFIGURED',
            'gemini_model': os.getenv('GEMINI_MODEL') if configured() else None,
            'evidence_storage': 'GCS' if os.getenv('WISPR_EVIDENCE_BUCKET') else 'SQLITE',
            'terrain_visibility': 'UNKNOWN', 'revision': os.getenv('WISPR_REVISION', 'local-release')}
