import React, { useEffect, useMemo, useRef, useState } from 'react';
import { api as scienceAPI, BASE } from './lib/api';
import './adaptive-atlas.css';
import {MoonScene} from './MoonScene';
import { SignalPanel,type Observation } from './SignalPanel';

type Layer = {
  color_legend?:string[];
  id:string; status:string; units?:string|null; minimum?:number|null; maximum?:number|null;
  source_id?:string|null; native_resolution_m?:number|null; description?:string; image_path?:string|null;
};
type Region = {
  region_id:string; kind:string; nominal_width_m:number; area_m2:number;
  center:{latitude_deg:number;longitude_deg:number}; coarse_context_cell_id:string; boundary_lonlat:number[][];
};
type Screening = { results:{cell_id:string;latitude_deg:number;longitude_deg:number;slope_deg:number;roughness_m:number}[]; scientific_warning:string; snapshot_id:string|null };
type Analysis = {
  scientific_status:string; summary:string; limitations:string[];
  regional_dem?:{status:string; elevation_m?:Record<string,number>; sample_count?:number; reason?:string; native_pixel_spacing_m?:number[]};
  coarse_context?:{status:string; measurement?:Record<string,unknown>};
  tool_trace:{tool:string;status:string}[]; explanation?:string|null; explanation_status?:string;
};
const ATLAS_FOCUS={lat:0,lon:0,key:0};
const ROOT = `${BASE}/api/v1/science/adaptive`;
const OPTIONS = [
  { id:'lroc', label:'Lunar imagery', note:'Grayscale mosaic' },
  { id:'elevation_m', label:'Elevation', note:'Relative lunar height' },
  { id:'slope_deg', label:'Slope', note:'Terrain inclination' },
  { id:'roughness_m', label:'Roughness', note:'Height variation' },
  { id:'elevation_m_coverage', label:'Coverage', note:'Source support' },
  { id:'thermal', label:'Thermal', note:'Historical observations' },
  { id:'quality', label:'Data quality', note:'Available source classification' },
];
const nf = (value:number|undefined|null, decimals=2) => value==null ? 'Unknown' : value.toLocaleString(undefined,{maximumFractionDigits:decimals});
async function api<T>(path:string, body?:unknown):Promise<T> {
  const response=await fetch(`${ROOT}${path}`, {method:body===undefined?'GET':'POST',
    headers:body===undefined?{}:{'Content-Type':'application/json'},
    body:body===undefined?undefined:JSON.stringify(body), signal:AbortSignal.timeout(35000)});
  if (!response.ok) {
    const text=await response.text(); throw new Error(`Scientific API ${response.status}: ${text.slice(0,350)}`);
  }
  return response.json() as Promise<T>;
}

export function AdaptiveAtlas() {
  const [layers,setLayers]=useState<Layer[]>([]);
  const [loaded,setLoaded]=useState(false);
  const [layer,setLayer]=useState('elevation_m');
  const [target,setTarget]=useState(30000);
  const [zoom,setZoom]=useState(1);
  const [region,setRegion]=useState<Region|null>(null);
  const [analysis,setAnalysis]=useState<Analysis|null>(null);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const [mode,setMode]=useState<'cell'|'polygon'>('cell');
  const [vertices,setVertices]=useState<number[][]>([]);
  const [provider,setProvider]=useState<'none'|'auto'>('none');
  const [screen,setScreen]=useState<Screening|null>(null);
  const [maxSlope,setMaxSlope]=useState(5);
  const request=useRef(0);
  const [reportUrl,setReportUrl]=useState('');
  const [globe,setGlobe]=useState(true),[sky,setSky]=useState<Observation|null>(null);

  useEffect(()=>{
    let active=true;
    api<{records:Layer[]}>('/atlas/layers').then(r=>{if(active){
      setLayers(r.records); setLoaded(true);
      if(!r.records.some(x=>x.id==='elevation_m'&&x.status==='AVAILABLE')){
        const first=r.records.find(x=>x.status==='AVAILABLE');if(first)setLayer(first.id);
      }
    }}).catch(e=>{if(active){setLoaded(true);setError(String(e));}});
    return ()=>{active=false};
  },[]);

  const selectedLayer=layers.find(x=>x.id===layer);
  const available=selectedLayer?.status==='AVAILABLE'&&Boolean(selectedLayer.image_path);
  const selectedPoint=useMemo(()=>region ? {
    x:region.center.longitude_deg/360*720,y:(90-region.center.latitude_deg)/180*360
  }:null,[region]);

  async function select(payload:unknown){
    const generation=++request.current;setBusy(true);setError('');setAnalysis(null);setSky(null);setReportUrl('');
    try{
      const selected=await api<Region>('/regions/select',payload);
      if(generation===request.current)setRegion(selected);
    }catch(e){if(generation===request.current)setError(String(e));}
    finally{if(generation===request.current)setBusy(false);}
  }
  function selectFromMap(e:React.MouseEvent<HTMLDivElement>){
    const bounds=e.currentTarget.getBoundingClientRect();
    const x=(e.clientX-bounds.left)/bounds.width;
    const y=(e.clientY-bounds.top)/bounds.height;
    if(x<0||x>1||y<0||y>1)return;
    const lon=x*360, lat=90-y*180;
    if(mode==='polygon')setVertices(v=>v.length>=64?v:[...v,[lon,lat]]);
    else void select({kind:'POINT',latitude_deg:lat,longitude_deg:lon,target_width_m:target});
  }
  async function runScreening(){
    setBusy(true);setError('');
    try {const r=await api<Screening>('/atlas/screen', {maximum_slope_deg:maxSlope,minimum_coverage:1,limit:50});setScreen(r);}
    catch(e){setError(String(e));}finally{setBusy(false);}
  }
  async function runAnalysis(){
    if(!region)return;const generation=++request.current;setBusy(true);setError('');
    try{
      const job=await scienceAPI<{job_id:string}>(`/api/v1/science/regions/${encodeURIComponent(region.region_id)}/analyze`,{use_llm:provider==='auto'});
      for(let attempt=0;attempt<120;attempt++){
        const j=await scienceAPI<any>(`/api/v1/science/region-jobs/${job.job_id}`);
        if(generation!==request.current)return;
        setAnalysis({scientific_status:j.status,summary:'Executing registered scientific tools',limitations:[],tool_trace:j.events.map((e:any)=>({tool:e.tool,status:e.state}))});
        if(j.status==='FAILED')throw Error(j.error);
        if(j.status==='COMPLETE'){
          const elevation=j.result.tools.find((v:any)=>v.tool==='calculate_elevation_statistics')?.data;
          setAnalysis({scientific_status:j.result.evidence_status,summary:j.result.summary,limitations:j.result.limitations,tool_trace:j.events.map((e:any)=>({tool:e.tool,status:e.state})),regional_dem:{status:elevation?.status,elevation_m:elevation?.area_weighted_mean==null?undefined:{mean:elevation.area_weighted_mean,min:elevation.minimum,max:elevation.maximum}}});
          setReportUrl(`${BASE}/api/v1/science/region-jobs/${job.job_id}/report`);return;
        }
        await new Promise(resolve=>setTimeout(resolve,750));
      }
      throw Error('Job is still running. Open region intelligence to inspect its persisted state.');
    }catch(e){if(generation===request.current)setError(String(e));}
    finally{if(generation===request.current)setBusy(false);}
  }
  const plottedVertices=vertices.map(([lon,lat])=>`${lon/360*720},${(90-lat)/180*360}`).join(' ');
  return <section className="wi" aria-label="WISPR whole Moon adaptive scientific atlas">
    <header className="wi-head">
      <div><div className="wi-kicker">WISPR / PLANETARY SCIENCE ATLAS</div><h1>One Moon. Every measurement.</h1>
      <p>NASA-sourced layers · adaptive lunar spatial IDs · evidence-first analysis</p></div>
      <div className="wi-head-meta">MOON ME / DE421<br/>R = 1,737.4 km<br/>East-positive longitude</div>
    </header>
    <div className="wi-workspace">
      <aside className="wi-nav">
        <h2>Scientific layers</h2><div className="wi-nav-desc">Color represents measurements, not decoration.</div>
        {OPTIONS.map(o=>{
          const item=layers.find(x=>x.id===o.id);const ready=item?.status==='AVAILABLE';
          return <button className={'wi-layer '+(layer===o.id?'wi-active':'')} key={o.id} type="button"
            disabled={!ready} onClick={()=>setLayer(o.id)}>
            <span className="wi-layer-symbol"/><span><strong>{o.label}</strong><small>{o.note}</small></span>
            <span className="wi-layer-state">{ready?'VIEW':item?.status==='UNAVAILABLE'?'N/A':'—'}</span>
          </button>;
        })}
        <div className="wi-divider"/><h2>Selection</h2>
        <div className="wi-tabs">
          <button type="button" className={mode==='cell'?'wi-selected':''} onClick={()=>{setMode('cell');setVertices([])}}>Cell</button>
          <button type="button" className={mode==='polygon'?'wi-selected':''} onClick={()=>{setMode('polygon');setGlobe(false);setVertices([])}}>Draw region</button>
        </div>
        {mode==='cell'?<label className="wi-label">Requested grid width
          <select value={target} onChange={e=>setTarget(Number(e.target.value))}>
            {[30000,1000,250,100,50,25].map(w=><option key={w} value={w}>{w.toLocaleString()} metres</option>)}
          </select><small>Spatial IDs can be finer than NASA's measurements.</small>
        </label>:<div className="wi-draw-actions"><p>Click three or more points to outline a lunar region.</p>
          <button type="button" disabled={vertices.length<3||busy} onClick={()=>void select({kind:'POLYGON',coordinates_lonlat:vertices})}>Finish region</button>
          <button type="button" onClick={()=>setVertices([])}>Clear</button></div>}
        <div className="wi-divider"/><h2>Whole-Moon screening</h2>
        <label className="wi-label">Maximum measured slope: {maxSlope}°
          <input type="range" value={maxSlope} min={0} max={30} step={1} onChange={e=>setMaxSlope(Number(e.target.value))}/>
        </label>
        <button type="button" className="wi-screen-button" disabled={busy} onClick={()=>void runScreening()}>Screen available terrain</button>
        <p className="wi-nav-desc">Coarse global candidate exploration only. Not a landing-safety assessment.</p>
        <div className="wi-divider"/><h2>View</h2>
        <label className="wi-label">Map zoom ×{zoom.toFixed(1)}
          <input type="range" value={zoom} min={1} max={3} step={0.25} onChange={e=>setZoom(Number(e.target.value))}/>
        </label>
      </aside>
      <div className="wi-map-column">
        <div className="wi-map-toolbar"><strong>{globe?'GLOBAL / 3D LUNAR SPHERE':'GLOBAL / EQUIRECTANGULAR'}</strong><button onClick={()=>setGlobe(!globe)}>{globe?'2D map / draw polygon':'3D whole Moon'}</button>
          <span>{selectedLayer?.id ?? 'NO LAYER'}{selectedLayer?.units?` · ${selectedLayer.units}`:''}</span></div>
        <div className="wi-map-viewport">
          {globe?<div className="wi-globe"><MoonScene cells={[]} selected={region?{cell_id:region.region_id,latitude_deg:region.center.latitude_deg,longitude_deg:region.center.longitude_deg,boundary_lonlat:region.boundary_lonlat}:null} onPick={(lat,lon)=>void select({kind:'POINT',latitude_deg:lat,longitude_deg:lon,target_width_m:target})} layer={layer} focus={ATLAS_FOCUS} bars={[]} sky={sky} textureUrl={selectedLayer?.image_path?BASE+selectedLayer.image_path:undefined}/></div>:<div className="wi-map-plane" style={{transform:`scale(${zoom})`}} onClick={selectFromMap}
            role="presentation" aria-label="Lunar map; click to select a geographic location">
            {available ? <img className="wi-map-image" src={`${BASE}${selectedLayer!.image_path}`} alt={`NASA source-backed ${layer} lunar map`} draggable={false}
              onError={()=>setError('Layer file unavailable or failed source checksum verification.')}/> :
              <div className="wi-empty-map">{loaded?'No verified raster layer loaded. Ingest source products and build atlas layers.':'Loading scientific layers…'}</div>}
            <svg className="wi-map-overlay" viewBox="0 0 720 360" preserveAspectRatio="none" aria-hidden="true">
              {Array.from({length:12},(_,i)=><line key={'x'+i} x1={i*60} x2={i*60} y1="0" y2="360"/>)}
              {Array.from({length:6},(_,i)=><line key={'y'+i} x1="0" x2="720" y1={i*60} y2={i*60}/>)}
              {vertices.length>1&&<polyline className="wi-poly" points={plottedVertices}/>}
              {vertices.map(([lon,lat],i)=><circle key={i} className="wi-vertex" cx={lon/360*720} cy={(90-lat)/180*360} r="2"/>)}
              {screen?.results.map(c=><circle key={c.cell_id} cx={c.longitude_deg/360*720} cy={(90-c.latitude_deg)/180*360} r="1.8" className="wi-candidate"/>)}
              {region?.boundary_lonlat&&<polyline className="wi-poly" points={region.boundary_lonlat.map(([lon,lat])=>`${((lon%360+360)%360)/360*720},${(90-lat)/180*360}`).join(' ')}/>}
              {selectedPoint&&<><circle className="wi-selection-ring" cx={selectedPoint.x} cy={selectedPoint.y} r="5"/>
                <line className="wi-cross" x1={selectedPoint.x-10} y1={selectedPoint.y} x2={selectedPoint.x+10} y2={selectedPoint.y}/>
                <line className="wi-cross" x1={selectedPoint.x} y1={selectedPoint.y-10} x2={selectedPoint.x} y2={selectedPoint.y+10}/></>}
            </svg>
          </div>}
        </div>
        <div className="wi-map-footer"><span>{globe?'LOLA shape · 4× relief · blue Earth / gold Sun rays (direction only)':'0°E — 360°E · +90°N — −90°S'}</span><span>Click the map to select • Zoom changes display, not evidence resolution</span></div>
        <div className="wi-legend"><span>VALUE RANGE</span>
          <div style={selectedLayer?.color_legend?{background:`linear-gradient(90deg,${selectedLayer.color_legend.join(',')})`}:undefined} className={"wi-ramp "+(layer==='lroc'?'wi-grayscale':layer==='quality'?'wi-category':'')}/><strong>{nf(selectedLayer?.minimum)} → {nf(selectedLayer?.maximum)} {selectedLayer?.units??''}</strong>
          <small>{selectedLayer?.native_resolution_m?`Native source spacing ≈ ${nf(selectedLayer.native_resolution_m,0)} m`:'Source resolution unknown'}</small></div>
        {screen&&<p className="wi-provenance">Showing {screen.results.length} top matching source-backed NSIDE-128 cells; blue dots are exploratory candidates, not safe landing sites. {screen.scientific_warning}</p>}
        <p className="wi-provenance">{selectedLayer?.description??'Scientific imagery is loaded only when a validated layer is available.'} {selectedLayer?.source_id?`Source: ${selectedLayer.source_id}`:''}</p>
      </div>
      <aside className="wi-results">
        <h2>Region intelligence</h2>{busy&&<p role="status">Working — results update here as each tool completes.</p>}
        {!region?<p className="wi-muted">Select a cell or draw a polygon on the map. WISPR will assign a stable geographical ID, then inspect which measurements exist.</p>:<>
          <div className="wi-metric-label">SELECTED REGION</div><div className="wi-id">{region.region_id}</div>
          <div className="wi-metrics"><div><small>Latitude</small><strong>{nf(region.center.latitude_deg,5)}°</strong></div>
            <div><small>Longitude E</small><strong>{nf(region.center.longitude_deg,5)}°</strong></div>
            <div><small>Selected width</small><strong>{nf(region.nominal_width_m,0)} m</strong></div>
            <div><small>Area</small><strong>{nf(region.area_m2/1e6,4)} km²</strong></div></div>
          <p className="wi-muted">Selection is independent of measurement resolution. No high-resolution evidence is assumed.</p>
          <label className="wi-label">Narrative explanation
            <select value={provider} onChange={e=>setProvider(e.target.value as 'none'|'auto')}>
              <option value="none">Deterministic report (no AI cost)</option><option value="auto">Use configured LLM if available</option>
            </select></label>
          <button className="wi-analyze" type="button" disabled={busy} onClick={()=>void runAnalysis()}>{busy?'Running analysis…':'Analyze selected region'}</button>
        </>}
        {region&&<SignalPanel latitude={region.center.latitude_deg} longitude={region.center.longitude_deg} onSample={setSky}/>}
        {reportUrl&&<a className="wi-analyze" href={reportUrl}>Export evidence report ↓</a>}
        {error&&<p className="wi-error" role="alert">{error}</p>}
        {analysis&&<section className="wi-report" aria-live="polite">
          <div className="wi-metric-label">ANALYSIS RESULT</div><strong>{analysis.scientific_status.replaceAll('_',' ')}</strong><p>{analysis.summary}</p>
          {analysis.regional_dem?.elevation_m&&<div className="wi-metrics">
            {Object.entries(analysis.regional_dem.elevation_m).map(([k,v])=><div key={k}><small>{k} elevation</small><strong>{nf(v)} m</strong></div>)}
          </div>}
          {analysis.coarse_context?.status==='COARSE_CONTEXT_ONLY'&&<p className="wi-muted">Parent-grid terrain is context only, not a measurement of your tiny region.</p>}
          <div className="wi-trace">{analysis.tool_trace.map((t,i)=><div key={i}><span>{t.tool.replaceAll('_',' ')}</span><em>{t.status}</em></div>)}</div>
          {analysis.explanation&&<p>{analysis.explanation}</p>}
          <details><summary>Scientific limitations</summary>{analysis.limitations.map((l,i)=><p key={i}>{l}</p>)}</details>
        </section>}
      </aside>
    </div>
  </section>;
}
