"""Typed scientific tools; LLM text never enters numerical result fields."""
from datetime import datetime
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,model_validator
from app.integration.engine import AnalysisEngine,Scenario
from app.integration.grid import Dataset
from app.integration.api import engine
from celestial_engine.schemas import EphemerisRequest
from app.science.windows import summarize
from . import store
from .context import context,dem_window,statistics
from .local import window as local_window

class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)


class Mission(Strict):
    start_utc:datetime
    end_utc:datetime
    step_minutes:int=Field(default=60,ge=1,le=1440,strict=True)
    minimum_shared_minutes:float=Field(default=60,ge=0,le=44640)
    @model_validator(mode='after')
    def valid_interval(self):
        EphemerisRequest(latitude_deg=0,longitude_east_deg=0,**self.model_dump(exclude={'minimum_shared_minutes'}))
        return self


class Arguments(Strict):
    region_id:str
    region_ids:list[str]=Field(default_factory=list,max_length=4)
    observer_height_m:float=Field(default=1,ge=0,le=100)
    mission:Mission|None=None
    limit:int=Field(default=5,ge=1,le=10)

NAMES=('get_region_metadata','get_region_sources','load_dem_window','calculate_elevation_statistics',
       'calculate_slope','calculate_roughness','calculate_horizon_profile','get_sun_ephemeris',
       'get_earth_ephemeris','calculate_visibility_windows','compare_candidate_regions',
       'calculate_delay_impact','find_similar_regions')


class ToolResult(Strict):
    tool:str
    region_id:str
    status:Literal['COMPLETE','INSUFFICIENT_DATA','NEEDS_INPUT','UNAVAILABLE']
    data:dict
    provenance:dict
    limitations:list[str]=Field(default_factory=list)


def run(name,args,ctx,memo):
    args=Arguments.model_validate(args)
    if name not in NAMES:raise ValueError('Unknown scientific tool')
    if args.region_id!=ctx['region']['region_id']:raise ValueError('Tool region differs from selected region')
    provenance={'tool_version':ctx['tool_version'],'source_fingerprint':ctx['source_fingerprint'],
                'coordinate_frame':ctx['coordinate_frame'],'exact_arguments':args.model_dump(mode='json')}
    status='COMPLETE';limitations=[]
    if name=='get_region_metadata':data=ctx['region']
    elif name=='get_region_sources':data={'sources':ctx['available_datasets'],'support':ctx['measurement_support']}
    elif name in ('load_dem_window','calculate_elevation_statistics','calculate_slope','calculate_roughness'):
        if 'window' not in memo:memo['window']=(local_window(ctx) if ctx['region']['kind']=='LOCAL_QUADTREE' else dem_window(ctx))
        window=memo['window']
        if name=='load_dem_window':
            data={k:v for k,v in window.items() if k!='samples'};data['native_pixel_count']=len(window['samples'])
            data['sample_values_sha256']=__import__('hashlib').sha256(__import__('json').dumps(window['samples'],sort_keys=True).encode()).hexdigest()
        else:data=statistics(window,{'calculate_elevation_statistics':'elevation_m','calculate_slope':'slope_deg','calculate_roughness':'roughness_m'}[name])
        if data.get('status')=='INSUFFICIENT_DATA':status='INSUFFICIENT_DATA'
        limitations=['No uncertainty raster has been inferred.','Physical resolution remains source-native.']
    elif name=='calculate_horizon_profile':
        data={'terrain_visibility':'UNKNOWN','profile':None,'reason':'No verified datum-compatible region horizon provider is registered.'}
        status='INSUFFICIENT_DATA'
    elif name in ('get_sun_ephemeris','get_earth_ephemeris','calculate_visibility_windows'):
        if not args.mission:
            status='NEEDS_INPUT';data={'missing_fields':['start_utc','end_utc']}
        else:
            if 'ephemeris' not in memo:
                geo=ctx['region'];req=EphemerisRequest(latitude_deg=geo['latitude_deg'],longitude_east_deg=geo['longitude_deg']%360,
                    **args.mission.model_dump(exclude={'minimum_shared_minutes'}))
                memo['ephemeris']=engine().celestial.ephemeris(req)
            result=memo['ephemeris'];provenance['ephemeris']=result.metadata
            if name=='calculate_visibility_windows':
                rows=[dict(timestamp_utc=r.timestamp_utc.isoformat(),**{body:dict(el_deg=getattr(r,body+'_elevation_deg'),status='KNOWN') if getattr(r,body+'_elevation_deg') is not None else None for body in ('sun','earth')}) for r in result.records]
                data=summarize(rows,args.mission.start_utc,args.mission.end_utc,args.mission.step_minutes,args.mission.minimum_shared_minutes)
            else:
                body='sun' if name=='get_sun_ephemeris' else 'earth'
                data={'records':[{'timestamp_utc':r.timestamp_utc.isoformat(),'azimuth_deg':getattr(r,body+'_azimuth_deg'),'elevation_deg':getattr(r,body+'_elevation_deg')} for r in result.records]}
            data['spatial_support']='REPRESENTATIVE_POINT_ONLY'
            limitations=['Not a polygon-wide visibility claim.','Ideal horizon; terrain occlusion UNKNOWN.']
    elif name in ('compare_candidate_regions','calculate_delay_impact'):
        if not args.mission:status='NEEDS_INPUT';data={'missing_fields':['mission']}
        else:
            ids=args.region_ids or [args.region_id]
            contexts=[context(store.get('region',key)) for key in ids]
            cells=[]
            for c in contexts:
                g=c['region'];values={};coverage=0;source={'region':g,'source_fingerprint':c['source_fingerprint']}
                if c['measurement_support']['detailed_terrain_available']:
                    window=(local_window(c) if g['kind']=='LOCAL_QUADTREE' else dem_window(c))
                    measurements={field:statistics(window,field) for field in ('elevation_m','slope_deg','roughness_m')}
                    values={field:m.get('area_weighted_mean') for field,m in measurements.items()}
                    coverage=min(m.get('coverage_fraction',0) for m in measurements.values())
                    source['measurements']=measurements
                cells.append({'cell_id':g['region_id'],'latitude_deg':g['latitude_deg'],'longitude_deg':g['longitude_deg'],
                    'valid':True,'coverage_fraction':coverage,'quality':'SOURCE_BACKED' if values and all(v is not None for v in values.values()) else 'NO_TERRAIN_EVIDENCE',
                    'source':source,'resolution_m':c['measurement_support']['source_resolution_m'],**values})
            meta={'dataset_id':'SELECTED_REGIONS','grid_version':'adaptive-region-v1','scope':'REGIONAL','coordinate_frame':ctx['coordinate_frame'],
                  'reference_radius_m':ctx['region']['reference_radius_m'],'latitude_type':'planetocentric_spherical','longitude_convention':'east_positive_0_360','elevation_datum':'UNVERIFIED',
                  'source':{'regions':ids},'terrain_definition':'Native pixel area-weighted region statistics where supported; representative-point ephemerides'}
            from types import SimpleNamespace
            from app.persistence import canonical
            import hashlib
            dataset=Dataset(meta,cells,hashlib.sha256(canonical({'metadata':meta,'cells':cells})).hexdigest())
            service=AnalysisEngine(SimpleNamespace(datasets={'SELECTED_REGIONS':dataset}),celestial=engine().celestial)
            req=Scenario(dataset_id='SELECTED_REGIONS',cell_ids=ids,**args.mission.model_dump(),horizon_model='GEOMETRIC_IDEAL',
                filters={'minimum_coverage':0,'qualities':['NO_TERRAIN_EVIDENCE','SOURCE_BACKED']})
            data=service.delay(req,args.region_id) if name=='calculate_delay_impact' else service.analyze(req)
            scenarios=[data.get('original',{}),data.get('delayed',{})] if name=='calculate_delay_impact' else [data]
            if any(r.get('status')=='UNKNOWN' for scenario in scenarios for r in scenario.get('results',[])):status='UNAVAILABLE'
            limitations=['Representative points only; does not certify an entire polygon.','No terrain qualification or landing-safety recommendation.']
    else:
        from lunar_global.api import store as global_store,Similarity
        if not ctx['region']['region_id'].startswith('MOON:HPX:NESTED:128:'):
            status='INSUFFICIENT_DATA';data={'matches':[],'reason':'Compatible source-backed vectors currently registered only at NSIDE 128; no parent-value inheritance.'}
        else:
            data=global_store().similarity(Similarity(reference_cell_id=args.region_id,maximum_results=args.limit,accept_unknown_uncertainty=True))
    return ToolResult(tool=name,region_id=args.region_id,status=status,data=data,provenance=provenance,limitations=limitations).model_dump(mode='json')
