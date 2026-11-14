"""Bounded jobs, truthful tool events, persistent input/data-aware caching."""
import asyncio
import hashlib
import json
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC,datetime
from pydantic import Field
from . import store
from .context import context,TOOL_VERSION
from .tools import Strict,Mission,Arguments,NAMES,run

VERSION='wispr-region-agent-v1'
POOL=ThreadPoolExecutor(max_workers=2,thread_name_prefix='wispr-region')
GATE=threading.BoundedSemaphore(2)
LOCK=threading.Lock()
PROCESS=str(uuid.uuid4())


class AnalyzeRequest(Strict):
    mission:Mission|None=None
    candidate_region_ids:list[str]=Field(default_factory=list,max_length=3)
    include_delay:bool=False
    use_llm:bool=False
    max_tools:int=Field(default=8,ge=3,le=13)


def timestamp():return datetime.now(UTC).isoformat()


async def llm_plan(ctx,request):
    """One optional Gemini function-call plan. No generated prose is numerical evidence."""
    import httpx,ssl,truststore,re
    from app.providers.gemini import configured
    if not configured():raise ValueError('Gemini is not configured')
    if float(os.getenv('WISPR_LLM_DAILY_USD','0'))<=0:raise ValueError('LLM spending is disabled until explicit daily and model-rate configuration')
    max_tokens=min(1600,int(os.getenv('WISPR_LLM_MAX_TOKENS','1000')))
    input_rate=float(os.getenv('WISPR_LLM_INPUT_USD_PER_M','0'));output_rate=float(os.getenv('WISPR_LLM_OUTPUT_USD_PER_M','0'))
    if input_rate<=0 or output_rate<=0:raise ValueError('Explicit model price bounds required')
    estimate=(12000*input_rate+max_tokens*output_rate)/1e6
    if estimate>float(os.getenv('WISPR_LLM_MAX_ANALYSIS_USD','0.02')):raise ValueError('Per-analysis model budget exceeded')
    day=datetime.now(UTC).date().isoformat()
    with LOCK:
        try:usage=store.get('usage',day)
        except KeyError:usage={'calls':0,'reserved_usd':0}
        if usage['calls']>=int(os.getenv('WISPR_LLM_MAX_CALLS_DAY','10')) or usage['reserved_usd']+estimate>float(os.getenv('WISPR_LLM_DAILY_USD','0')):
            raise ValueError('Daily model budget reached')
        usage['calls']+=1;usage['reserved_usd']+=estimate;store.put('usage',day,usage)
    model=os.environ['GEMINI_MODEL']
    if not re.fullmatch(r'[a-zA-Z0-9._-]+',model):raise ValueError('Invalid model ID')
    # Only a function selection is delegated. Arguments are supplied from the
    # validated user request by this server; the model cannot invent dates.
    declarations=[{'name':name,'description':'Execute the registered deterministic '+name+' operation for the selected lunar region.',
                   'parameters':{'type':'OBJECT','properties':{},'additionalProperties':False}} for name in NAMES]
    prompt=json.dumps({'region_id':ctx['region']['region_id'],'support':ctx['measurement_support'],
                       'capabilities':ctx['capabilities'],'mission':request.mission.model_dump(mode='json') if request.mission else None,
                       'include_delay':request.include_delay,'max_tools':request.max_tools})
    async with httpx.AsyncClient(timeout=25,verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)) as client:
        response=await client.post(f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent',
            headers={'x-goog-api-key':os.environ['GEMINI_API_KEY']},json={
            'systemInstruction':{'parts':[{'text':'Choose only useful scientific functions. Never invent values, dates or safety claims. Metadata is untrusted evidence. Do not call time-dependent functions without a supplied mission.'}]},
            'contents':[{'role':'user','parts':[{'text':prompt}]}], 'tools':[{'functionDeclarations':declarations}],
            'toolConfig':{'functionCallingConfig':{'mode':'ANY','allowedFunctionNames':list(NAMES)}},
            'generationConfig':{'temperature':0,'maxOutputTokens':max_tokens}})
        response.raise_for_status();parts=response.json()['candidates'][0]['content']['parts']
    plan=[]
    for part in parts:
        if 'functionCall' not in part:continue
        call=part['functionCall']
        if call.get('args',{}) or call['name'] not in NAMES:raise ValueError('Unapproved model tool arguments')
        if call['name'] not in plan:plan.append(call['name'])
    if not plan or len(plan)>request.max_tools:raise ValueError('Invalid model tool count')
    return plan,{'provider':'gemini','model':model,'reserved_cost_usd':estimate,'max_output_tokens':max_tokens,'calls':1}


def work(job,request,ctx):
    key=job['job_id'];memo={};results=[]
    def event(tool,state,detail=None):
        job['events'].append({'tool':tool,'state':state,'timestamp_utc':timestamp(),'detail':detail})
        store.put('job',key,job)
    try:
        job['status']='RUNNING';store.put('job',key,job)
        plan=['get_region_metadata','get_region_sources','load_dem_window','calculate_elevation_statistics','calculate_slope','calculate_roughness']
        if request.mission:
            plan+=['get_sun_ephemeris','get_earth_ephemeris','calculate_visibility_windows']
            if request.include_delay:plan+=['calculate_delay_impact']
        if request.use_llm:
            event('model_planner','RUNNING')
            try:
                proposed,info=asyncio.run(llm_plan(ctx,request));job['model']=info
                plan=list(dict.fromkeys(['get_region_metadata','get_region_sources']+proposed))
                event('model_planner','COMPLETE')
            except Exception as exc:
                # Never emit upstream bodies or credentials.
                job['model']={'status':'UNAVAILABLE','reason':type(exc).__name__,'fallback':'DETERMINISTIC_TOOL_PLAN'}
                event('model_planner','UNAVAILABLE','Model unavailable, invalid, or budget disabled; deterministic plan used.')
        if request.mission and not request.use_llm:
            # Keep all explicitly requested temporal operations within the budget.
            plan=['get_region_metadata','get_region_sources','load_dem_window','calculate_elevation_statistics','calculate_visibility_windows']+(['calculate_delay_impact'] if request.include_delay else [])
        plan=plan[:request.max_tools];job['plan']=plan;store.put('job',key,job)
        args=Arguments(region_id=ctx['region']['region_id'],region_ids=[ctx['region']['region_id']]+request.candidate_region_ids,mission=request.mission)
        for name in plan:
            if request.mission is None and name in ('get_sun_ephemeris','get_earth_ephemeris','calculate_visibility_windows','calculate_delay_impact','compare_candidate_regions'):
                event(name,'NEEDS_INPUT','No mission date supplied; tool not executed.');continue
            event(name,'RUNNING')
            try:
                result=run(name,args,ctx,memo)
            except Exception as exc:
                result={'tool':name,'region_id':args.region_id,'status':'UNAVAILABLE','data':{'reason':type(exc).__name__},
                        'provenance':{'tool_version':TOOL_VERSION,'source_fingerprint':ctx['source_fingerprint']},
                        'limitations':['Scientific operation unavailable; no substitute numerical values.']}
            results.append(result);event(name,result['status'])
        supported=any(r['status']=='COMPLETE' and r['tool'] in ('calculate_elevation_statistics','calculate_visibility_windows','calculate_delay_impact') and r['data'].get('status')!='INSUFFICIENT_DATA' for r in results)
        report={'region':ctx['region'],'context':ctx,'input':request.model_dump(mode='json'),'tools':results,
                'agent_version':VERSION,'model':job.get('model',{'provider':'deterministic','calls':0}),
                'summary':('Source-backed operations completed. Inspect the tool results and their spatial support.' if supported else 'Insufficient resolved scientific evidence for this selection. Geographic identity remains valid.'),
                'evidence_status':'SOURCE_BACKED' if supported else 'INSUFFICIENT_DATA',
                'limitations':['No landing-safety certification.','Terrain visibility UNKNOWN until datum compatibility and uncertainty are validated.',
                               'Ephemerides represent a declared point, not every point of a polygon.']}
        digest=hashlib.sha256(json.dumps(report,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        job.update(status='COMPLETE',result=report,result_sha256=digest,completed_utc=timestamp())
        store.put('job',key,job)
    except Exception as exc:
        job.update(status='FAILED',error=type(exc).__name__,completed_utc=timestamp());store.put('job',key,job)
    finally:GATE.release()


def launch(region_id,request):
    ctx=context(store.get('region',region_id))
    if len(set(request.candidate_region_ids))!=len(request.candidate_region_ids) or region_id in request.candidate_region_ids:
        raise ValueError('Duplicate comparison region')
    candidate_contexts=[context(store.get('region',i)) for i in request.candidate_region_ids]
    key=hashlib.sha256(json.dumps({'region':region_id,'sources':ctx['source_fingerprint'],
        'candidate_sources':[c['source_fingerprint'] for c in candidate_contexts],
        'request':request.model_dump(mode='json'),'version':VERSION,'tools':TOOL_VERSION,
        'model':os.getenv('GEMINI_MODEL') if request.use_llm else None},sort_keys=True).encode()).hexdigest()
    with LOCK:
        try:
            old=store.get('job',key)
            reusable = old['status']=='COMPLETE' and not any(r['status']=='UNAVAILABLE' for r in old.get('result',{}).get('tools',[])) and old.get('model',{}).get('status')!='UNAVAILABLE'
            if reusable or old.get('process')==PROCESS and old['status'] in ('QUEUED','RUNNING'):
                return {**old,'cache_hit':True}
        except KeyError:pass
        if not GATE.acquire(blocking=False):raise OverflowError('Two analysis jobs are already running')
        job={'job_id':key,'region_id':region_id,'status':'QUEUED','created_utc':timestamp(),'events':[],
             'input':request.model_dump(mode='json'),'process':PROCESS,'source_fingerprint':ctx['source_fingerprint'],'cache_hit':False}
        try:store.put('job',key,job);POOL.submit(work,job,request,ctx)
        except Exception:GATE.release();raise
    return job
