import asyncio
from collections import OrderedDict
import csv
import io
import os
from fastapi import FastAPI, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from celestial_engine.api import router as celestial_router
from app.integration.api import router as science_router
from lunar_global.api import router as global_router
from app.catalog import SITES, SITE_WARNING
from app.metadata import metadata, aggregate
from app.schemas import (RecoveryRequest, RecoveryResponse, AnalyzeRequest, EphemerisRequest,
    SitesResponse, GridResponse, EphemerisResponse, AnalyzeResponse, FeaturesResponse)
from app.providers.horizons import Horizons, SourceUnavailable
from app.providers import terrain
from app.providers.interpret import InterpretRequest, interpret
from app.science.analysis import analyze_scenario
from app.science.recovery import recover_mission
from app.science.grid import neighborhood, lookup
from app.science.features import feature_space

app = FastAPI(title='WISPR lunar visibility', version='0.1.0', description='Sampled geometric estimates with explicit provenance and unknown states. No mission commands.')
app.add_middleware(CORSMiddleware, allow_origins=os.getenv('CORS_ORIGINS','http://localhost:5173,http://127.0.0.1:5173').split(','),
    allow_methods=['GET','POST'],allow_headers=['Content-Type'])
app.include_router(celestial_router)
app.include_router(science_router)
app.include_router(global_router)
from app.navigation import router as navigation_router
app.include_router(navigation_router)
provider = Horizons()
scenarios = OrderedDict()
requests_gate = asyncio.Semaphore(2)


def remember(scenario):
    scenarios[scenario['scenario_id']] = scenario
    scenarios.move_to_end(scenario['scenario_id'])
    while len(scenarios)>128:
        scenarios.popitem(last=False)


@app.exception_handler(HTTPException)
async def http_error(request, exc):
    if request.url.path.startswith('/api/v1/science/'):
        codes = {404: 'NOT_FOUND', 422: 'INVALID_SCIENTIFIC_REQUEST', 429: 'CAPACITY_EXCEEDED'}
        return JSONResponse(status_code=exc.status_code, headers=exc.headers,
            content=dict(error_code=codes.get(exc.status_code, 'HTTP_ERROR'),
                         detail=exc.detail, missing_fields=[]))
    from fastapi.exception_handlers import http_exception_handler
    return await http_exception_handler(request, exc)


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    return JSONResponse(status_code=422,content=dict(error_code='INVALID_REQUEST',detail=[{'loc':list(e['loc']),'msg':e['msg']} for e in exc.errors()],missing_fields=[]))


@app.get('/health')
async def health():
    return dict(status='OK' if provider.live else 'DEGRADED',horizons_live=provider.live is True,
        horizons_probe_status='NOT_TESTED' if provider.live is None else 'REACHABLE' if provider.live else 'UNAVAILABLE',
        cache_available=provider.root.exists() and any(provider.root.glob('*.meta.json')),
        dem_status_by_site={s:'CONFIGURED_NOT_PROBED' if os.getenv('DEM_'+s) else 'UNAVAILABLE' for s in SITES},
        llm_provider_status='CONFIGURED_NOT_TESTED' if any(os.getenv(p+'_API_KEY') and os.getenv(p+'_MODEL') for p in ('GROQ','NVIDIA')) else 'UNCONFIGURED',
        mode='GEOMETRIC',warnings=[SITE_WARNING]+([] if provider.live else ['Live Horizons has not succeeded in this process.']))


@app.get('/api/v1/sites',response_model=SitesResponse)
async def sites():
    return dict(sites=list(SITES.values()),**metadata(limitations=[SITE_WARNING]))


@app.post('/api/v1/ephemeris',response_model=EphemerisResponse)
async def ephemeris(request: EphemerisRequest):
    try:
        return await provider.ephemeris(request)
    except ValueError as exc:
        raise HTTPException(422,detail=str(exc)) from exc
    except SourceUnavailable as exc:
        return JSONResponse(status_code=503,content=dict(error_code='SOURCE_UNAVAILABLE',detail=str(exc),fallback='NONE',**metadata()))


async def analyze_one(site,start,end,request):
    result = await analyze_scenario(site,start,end,request,provider)
    remember(result)
    return result


@app.post('/api/v1/analyze',response_model=AnalyzeResponse)
async def analyze(request: AnalyzeRequest):
    async with requests_gate:
        results = [await analyze_one(s,request.start_utc,request.end_utc,request) for s in request.site_ids]
    return dict(scenarios=results,**aggregate(results))


@app.post('/api/v1/recovery',response_model=RecoveryResponse)
@app.post('/api/v1/search',response_model=RecoveryResponse)
async def recovery(request: RecoveryRequest):
    async with requests_gate:
        return await recover_mission(request,analyze_one)


@app.get('/api/v1/grid',response_model=GridResponse)
async def grid(site_id: str=Query('R01',pattern='^R0[14]$'),radius_cells: int=Query(1,ge=1,le=1),cell_size_m: int=Query(1000,ge=1000,le=1000)):
    return neighborhood(site_id,radius_cells)


@app.get('/api/v1/grid/{cell_id}')
async def grid_cell(cell_id: str):
    try:
        cell = lookup(cell_id)
    except ValueError as exc:
        raise HTTPException(422,detail=str(exc)) from exc
    return dict(cell=cell,static_features=dict(elevation_m=None,slope_deg=None,data_status='UNVERIFIED'),available_scenarios=[],**metadata())


@app.get('/api/v1/features',response_model=FeaturesResponse)
async def features(scenario_id: str):
    if scenario_id not in scenarios:
        raise HTTPException(404,detail='Scenario absent or expired; run analysis again')
    return feature_space(scenarios[scenario_id])


def site_exists(site_id):
    if site_id not in SITES:
        raise HTTPException(404,detail='Unknown site')


@app.get('/api/v1/terrain/{site_id}/metadata')
def terrain_meta(site_id: str):
    site_exists(site_id)
    return terrain.terrain_metadata(site_id)


def terrain_error(exc):
    return JSONResponse(status_code=503,content=dict(error_code='TERRAIN_UNAVAILABLE',detail=str(exc),fallback='NONE',**metadata(mode='TERRAIN_UNAVAILABLE')))


@app.get('/api/v1/terrain/{site_id}/heightmap')
def heightmap(site_id: str,size_m: float=Query(1000,ge=100,le=16000),max_points: int=Query(128,ge=2,le=128)):
    site_exists(site_id)
    try:
        # Probe before optional imports so missing deps still return structured 503.
        if terrain.terrain_metadata(site_id)['coverage']=='UNAVAILABLE':
            raise terrain.TerrainUnavailable('Verified DEM unavailable')
        return terrain.heightmap(site_id,size_m,max_points)
    except (terrain.TerrainUnavailable,ImportError) as exc:
        return terrain_error(exc)


@app.get('/api/v1/terrain/{site_id}/horizon')
def horizon(site_id: str,observer_height_m: float=Query(1,ge=0,le=100),az_step_deg: int=Query(5,ge=1,le=30)):
    site_exists(site_id)
    try:
        if terrain.terrain_metadata(site_id)['coverage']=='UNAVAILABLE':
            raise terrain.TerrainUnavailable('Verified DEM unavailable')
        return terrain.horizon(site_id,observer_height_m,az_step_deg)
    except (terrain.TerrainUnavailable,ImportError) as exc:
        return terrain_error(exc)


@app.post('/api/v1/interpret')
async def interpret_route(request: InterpretRequest):
    return await interpret(request)


@app.get('/api/v1/export/{scenario_id}.csv')
async def export(scenario_id: str):
    if scenario_id not in scenarios:
        raise HTTPException(404,detail='Scenario absent or expired')
    scenario=scenarios[scenario_id]
    output=io.StringIO()
    output.write('# source_type='+scenario['source_type']+'; raw_sha256='+','.join(scenario['provenance'].get('raw_sha256',[]))+'\n')
    writer=csv.writer(output)
    writer.writerow(['timestamp_utc','sun_az_deg','sun_el_deg','earth_az_deg','earth_el_deg','status'])
    for r in scenario['visibility_series']:
        writer.writerow([r['timestamp_utc']]+[(r[t] or {}).get(k,'') for t in ('sun','earth') for k in ('az_deg','el_deg')]+[r['status']])
    return Response(output.getvalue(),media_type='text/csv',headers={'Content-Disposition':f'attachment; filename="{scenario_id}.csv"'})

# Optional single-service production package. API routes stay ahead of the SPA.
if os.getenv('WISPR_STATIC_DIR'):
    from fastapi.staticfiles import StaticFiles
    app.mount('/', StaticFiles(directory=os.environ['WISPR_STATIC_DIR'], html=True), name='ui')
