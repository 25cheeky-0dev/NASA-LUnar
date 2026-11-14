"""Adaptive spatial selection and bounded scientific investigation API."""
from datetime import datetime
from typing import Literal
from fastapi import APIRouter,HTTPException,Query
from fastapi.responses import JSONResponse
from pydantic import Field,model_validator
from celestial_engine.schemas import EphemerisRequest
from lunar_global.grid import lookup,describe
from .geometry import nside_for_width,cell_region,polygon_region
from .context import context
from . import store,local
from .agent import AnalyzeRequest,launch
from .tools import Strict,Mission,Arguments,NAMES

router=APIRouter(prefix='/api/v1/science',tags=['adaptive-regions'])


class PolygonSelection(Strict):
    type:Literal['Polygon']='Polygon'
    coordinates:list[list[tuple[float,float]]]=Field(min_length=1,max_length=5)


class Selection(Strict):
    cell_id:str|None=Field(default=None,max_length=150)
    latitude:float|None=Field(default=None,ge=-90,le=90)
    longitude:float|None=Field(default=None,ge=-180,le=360)
    geometry:PolygonSelection|None=None
    coordinate_frame:Literal['MOON_ME_DE421']='MOON_ME_DE421'
    target_width_m:float=Field(default=1000,ge=25,le=1000000)
    local_grid_id:str|None=Field(default=None,max_length=24)
    observation_time:datetime|None=None
    mission:Mission|None=None
    @model_validator(mode='after')
    def shape(self):
        if sum([self.cell_id is not None,self.geometry is not None,self.latitude is not None])!=1:
            raise ValueError('Choose one cell ID, one point, or one polygon')
        if (self.latitude is None)!=(self.longitude is None):raise ValueError('Both point coordinates are required')
        if self.local_grid_id and self.latitude is None:raise ValueError('Local grid selection requires coordinates')
        if self.observation_time:EphemerisRequest.utc_minute(self.observation_time)
        return self


class RegionContext(Strict):
    region:dict
    available_datasets:list[dict]
    measurement_support:dict
    missing_measurements:list[str]
    quality:str
    source_fingerprint:str
    capabilities:dict[str,bool]
    coordinate_frame:str
    tool_version:str
    observation_time:str|None=None
    mission:dict|None=None


def safe(action,*args,**kwargs):
    try:return action(*args,**kwargs)
    except KeyError as exc:raise HTTPException(404,'Region or job not found') from exc
    except (ValueError,TypeError) as exc:raise HTTPException(422,str(exc)) from exc
    except OverflowError as exc:raise HTTPException(429,str(exc)) from exc
    except RuntimeError as exc:raise HTTPException(503,str(exc)) from exc


@router.get('/regions/tools/catalog')
def catalog():
    return {'tool_version':'region-native-overlap-v1','tools':[{'name':n,'arguments':Arguments.model_json_schema()} for n in NAMES],
            'max_nside':32768,'maximum_region_intersections':512,'max_concurrent_jobs':2,
            'llm_optional':True,'numerical_authority':'deterministic_scientific_tools'}


@router.get('/regions/grid/local')
def local_grids():
    return {'grids':[{k:v for k,v in s.items() if k!='path'} for s in safe(local.catalog)]}


@router.get('/regions/preview')
def preview(latitude:float=Query(ge=-90,le=90),longitude:float=Query(ge=-180,le=360),target_width_m:float=Query(1000,ge=25,le=1000000)):
    info=safe(cell_region,safe(lookup,latitude,longitude,nside_for_width(target_width_m)))
    return {'region':info,'selection_only':True,'measurement_status':'NOT_QUERIED','source_resolution_is_independent':True}


@router.post('/regions/select',response_model=RegionContext)
def select(request:Selection):
    nside=nside_for_width(request.target_width_m)
    if request.local_grid_id:
        region=safe(local.select,request.local_grid_id,request.latitude,request.longitude,request.target_width_m)
    elif request.cell_id:region=safe(local.describe_id if request.cell_id.startswith('MOON:LOCAL:') else cell_region,request.cell_id)
    elif request.geometry:region=safe(polygon_region,request.geometry.model_dump(),nside)
    else:region=safe(cell_region,safe(lookup,request.latitude,request.longitude,nside))
    safe(store.put,'region',region['region_id'],region)
    result=safe(context,region)
    result.update(observation_time=request.observation_time.isoformat() if request.observation_time else None,
                  mission=request.mission.model_dump(mode='json') if request.mission else None)
    return result


@router.get('/regions/{region_id}',response_model=RegionContext)
def metadata(region_id:str):
    return safe(context,safe(store.get,'region',region_id))


@router.post('/regions/{region_id}/analyze',status_code=202)
def analyze(region_id:str,request:AnalyzeRequest):
    return safe(launch,region_id,request)


@router.get('/region-jobs/{job_id}')
def job(job_id:str):
    result=safe(store.get,'job',job_id)
    return {k:v for k,v in result.items() if k!='process'}


@router.get('/region-jobs/{job_id}/report')
def report(job_id:str):
    record=safe(store.get,'job',job_id)
    if record['status']!='COMPLETE':raise HTTPException(409,'Analysis is not complete')
    return JSONResponse(record['result'],headers={'Content-Disposition':f'attachment; filename="wispr-region-{job_id}.json"',
                                                'X-Content-SHA256':record['result_sha256']})
