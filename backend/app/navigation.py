"""Navigation aids and an explicitly requested preserved-data demonstration."""
from functools import lru_cache
from pathlib import Path
from fastapi import APIRouter
from app.integration.grid import Dataset
from app.integration.engine import AnalysisEngine, Scenario
from celestial_engine.celestial_service import CelestialService
from celestial_engine.horizons_client import HorizonsClient
from types import SimpleNamespace

router = APIRouter(prefix='/api/v1/navigation', tags=['navigation'])
ROOT = Path(__file__).resolve().parents[1]

@router.get('/locations')
def locations():
    rows = [
        ('Apollo 11', .674, 23.473, 'historical_landing_point', 'https://nssdc.gsfc.nasa.gov/planetary/lunar/apolloland.html'),
        ('Apollo 17', 20.1908, 30.77168, 'historical_landing_point', 'https://www.nasa.gov/wp-content/uploads/static/history/SP-4029/Apollo_18-27_LM_Lunar_Landing.htm'),
        ('Tycho', -43.30, -11.22, 'feature_representative_location', 'https://planetarynames.wr.usgs.gov/Feature/6163'),
        ('Mare Tranquillitatis', 8.35, 30.83, 'feature_representative_location', 'https://planetarynames.wr.usgs.gov/Feature/3691'),
        ('Chandrayaan-3 planned region', -69.367621, 32.348126, 'candidate_study_region', 'https://www.isro.gov.in/media_isro/pdf/Missions/LVM3/LVM3M4_Chandrayaan3_brochure.pdf'),
    ]
    return {'locations': [dict(name=n, latitude_deg=lat, longitude_deg=lon, kind=k, source=url) for n,lat,lon,k,url in rows],
            'limitations': 'Rounded navigation coordinates in source conventions; not landing suitability or a cell-center observation. Named points navigate to the containing grid cell.'}

@lru_cache(maxsize=1)
def demo_dataset():
    return Dataset.read(ROOT.parent / 'docs/evidence/unified/real_v3_two_cells.json')

@router.get('/demo/cells')
def demo_cells():
    d = demo_dataset()
    return dict(metadata=d.metadata.model_dump(), cells=[c.model_dump() for c in d.cells], mode='PRESERVED_REAL_DATA', sha256=d.digest)

@router.post('/demo/delay')
def demo_delay():
    d = demo_dataset()
    engine = AnalysisEngine(SimpleNamespace(datasets={d.metadata.dataset_id:d}),
        CelestialService(HorizonsClient(ROOT/'tests/fixtures/unified_nasa', offline=True)))
    req = Scenario(dataset_id=d.metadata.dataset_id, cell_ids=[c.cell_id for c in d.cells],
        start_utc='2026-11-15T00:00:00Z', end_utc='2026-11-22T00:00:00Z', step_minutes=60,
        minimum_shared_minutes=60, filters={'qualities':['source_lola_count_and_uncertainty_not_supplied']})
    return dict(engine.delay(req, d.cells[0].cell_id), delivery_mode='PRESERVED_REAL_DATA_OFFLINE',
        demo_note='Exact recorded NASA responses and two original Site04 cells. Fixed dates and cadence; no live retrieval, synthetic data, or terrain clearance.')

@router.get('/terrain/model')
def terrain_model():
    """Serve only the original package mesh after its manifest checksum passes."""
    import os, json, hashlib
    from fastapi import HTTPException
    from fastapi.responses import FileResponse
    root = Path(os.getenv('WISPR_GRID_DIR', 'data/grids')).resolve()
    relative = 'baseline/terrain_site04_5m.glb'
    try:
        manifest = json.loads((root/'SHA256_MANIFEST.json').read_text())['files']
        path = root/relative
        if hashlib.sha256(path.read_bytes()).hexdigest() != manifest[relative]:
            raise ValueError('Terrain mesh checksum mismatch')
        return FileResponse(path, media_type='model/gltf-binary')
    except (OSError, KeyError, ValueError) as exc:
        raise HTTPException(503, 'Original manifest-verified Site04 mesh unavailable') from exc

from app.providers.interpret import InterpretRequest
from app.mission_intent import interpret_mission

@router.post('/interpret')
async def selected_cell_intent(request: InterpretRequest):
    return await interpret_mission(request)
