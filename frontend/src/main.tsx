import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { api, BASE, MOCK, type Cell, type Features, type Grid, type MissionRequest, type Outcome, type Recovery, type Scenario } from './lib/api';
import { fixture, fixtureGrids, fixtureFeatures } from './mocks/recovery';

import { MissionControl } from './MissionControl';

const outcomes: globalThis.Record<Outcome,string> = {KEEP_SITE_AFTER_DELAY:'Keep the original site',SWITCH_SITE_AFTER_DELAY:'Switch the delayed site',POSTPONE_AND_REEVALUATE:'Postpone and reevaluate',NO_QUALIFYING_OPTION_WITHIN_SEARCH:'No qualifying option in this search',INSUFFICIENT_DATA:'More data is needed',NEEDS_INPUT:'Complete the mission inputs'};
const utc = (value?:string|null) => value ? value.replace('T',' ').replace('.000','') : '—';
const hours = (value:number|null|undefined) => value == null ? '—' : `${(value/60).toFixed(2)} h`;
const percent = (value:number) => `${(100*value).toFixed(0)}%`;
const initial: MissionRequest = {original_site_id:'R01',original_arrival_utc:null,study_duration_hours:24,delay_hours:168,min_continuous_overlap_minutes:180,candidate_site_ids:['R01','R04'],horizon_model:'GEOMETRIC',observer_height_m:1,step_minutes:5,future_search_days:0};

function ElevationChart({scenario}:{scenario:Scenario}) {
  const rows = scenario.visibility_series;
  const start=Date.parse(scenario.arrival_utc), span=Date.parse(scenario.end_utc)-start;
  const elevations=rows.flatMap(r=>[r.sun?.el_deg,r.earth?.el_deg]).filter((n):n is number=>n!=null);
  const bound=Math.max(2, ...elevations.map(Math.abs))*1.2;
  const y=(n:number)=>105-n/bound*75;
  function paths(target:'sun'|'earth') {
    const segments:string[]=[]; let current=''; let previous=0;
    for (const r of rows) {
      const t=Date.parse(r.timestamp_utc), el=r[target]?.el_deg;
      if(el==null || (previous && t-previous>scenario.provenance.sample_step_minutes!*60000+1)) {if(current)segments.push(current);current='';}
      if(el!=null)current+=`${current?'L':'M'}${48+(t-start)/span*580},${y(el)} `;
      previous=t;
    }
    if(current)segments.push(current);return segments;
  }
  return <svg viewBox="0 0 660 230" role="img" aria-label="Sun and Earth elevation against UTC, with gaps left blank">
    {[-bound,0,bound].map(n=><g key={n}><line x1="48" x2="628" y1={y(n)} y2={y(n)} className={n===0?'zero':'gridline'}/><text x="38" y={y(n)+4} textAnchor="end">{n.toFixed(1)}°</text></g>)}
    {(['sun','earth'] as const).map(t=>paths(t).map((d,i)=><path key={t+i} d={d} fill="none" stroke={t==='sun'?'var(--sun)':'var(--earth)'} strokeWidth="2"/>))}
    {[0,.25,.5,.75,1].map(f=><text key={f} x={48+f*580} y="214" textAnchor="middle">{new Date(start+span*f).toISOString().slice(11,16)}</text>)}
    {!elevations.length&&<text x="330" y="72" textAnchor="middle">No source-backed observations available</text>}
  </svg>;
}

function Timeline({scenario}:{scenario:Scenario}) {
  const start=Date.parse(scenario.arrival_utc),duration=Date.parse(scenario.end_utc)-start;
  const bar=(s:string,e:string)=>({left:`${(Date.parse(s)-start)/duration*100}%`,width:`${(Date.parse(e)-Date.parse(s))/duration*100}%`});
  return <div className="timelines">{[['Sun',scenario.sun_windows],['Earth',scenario.earth_windows],['Shared',scenario.shared_windows]].map(([label,windows])=><div className="timeline-row" key={label as string}><span>{label as string}</span><div className="track">{(windows as Scenario['shared_windows']).map((w,i)=><span className={`window ${(label as string).toLowerCase()}`} key={i} style={bar(w.start_utc,w.end_utc)} title={`${utc(w.start_utc)} → ${utc(w.end_utc)}; ${w.duration_minutes.toFixed(1)} min; MODEL_ESTIMATE`}/>)}{scenario.unknown_intervals?.map((w,i)=><span key={'u'+i} className="unknown-window" style={bar(w.start_utc,w.end_utc)} title={w.reason}/>)}</div></div>)}<p className="small">Hatching = unknown interval · boundaries estimated to ±{scenario.provenance.sample_step_minutes??5} min</p></div>;
}

function Sky({scenario,index}:{scenario:Scenario;index:number}) {
  const row=scenario.visibility_series[index];
  return <svg viewBox="0 0 320 260" role="img" aria-label="Local azimuth and elevation sky plot">
    {[30,60,90].map(r=><circle key={r} cx="160" cy="124" r={r} fill="none" className="gridline"/>)}
    <path d="M160 25V224M61 124H259" className="gridline"/><text x="160" y="18" textAnchor="middle">N · 0°</text><text x="270" y="129">E</text><text x="160" y="244" textAnchor="middle">S · 180°</text><text x="43" y="129">W</text>
    {(['sun','earth'] as const).map(target=>{const p=row?.[target];if(p?.east==null||p.north==null||p.el_deg==null)return null;return <g key={target}><circle cx={160+90*p.east} cy={124-90*p.north} r="6" fill={target==='sun'?'var(--sun)':'var(--earth)'} opacity={p.el_deg>0?1:.35}/><text x={171+90*p.east} y={124-90*p.north}>{target} {p.el_deg.toFixed(2)}°</text></g>;})}
  </svg>;
}

function GridMap({grids,selected,onSelect}:{grids:Grid[];selected:Cell|null;onSelect:(c:Cell)=>void}) {
  const cells=grids.flatMap(g=>g.cells);if(!cells.length)return <div className="empty compact">Grid requires a reachable backend. No cells have been fabricated.</div>;
  const minX=Math.min(...cells.map(c=>c.center_x_m))-1500,maxX=Math.max(...cells.map(c=>c.center_x_m))+1500,minY=Math.min(...cells.map(c=>c.center_y_m))-1500,maxY=Math.max(...cells.map(c=>c.center_y_m))+1500;
  const scale=Math.min(540/(maxX-minX),280/(maxY-minY)),x=(v:number)=>60+(v-minX)*scale,y=(v:number)=>330-(v-minY)*scale;
  return <svg viewBox="0 0 660 380" role="img" aria-label="Canonical lunar south-polar stereographic grid">
    <defs><pattern id="mapgrid" width="30" height="30" patternUnits="userSpaceOnUse"><path d="M 30 0 L 0 0 0 30" fill="none" stroke="#29332b" strokeWidth=".5"/></pattern></defs><rect x="25" y="25" width="610" height="330" fill="url(#mapgrid)"/>
    {cells.map(c=><rect key={c.cell_id} x={x(c.center_x_m-500)} y={y(c.center_y_m+500)} width={1000*scale} height={1000*scale} className={`cell ${selected?.cell_id===c.cell_id?'selected':''}`} tabIndex={0} role="button" aria-label={`${c.cell_id}, ${c.ephemeris_status}`} onClick={()=>onSelect(c)} onKeyDown={e=>{if(e.key==='Enter'||e.key===' ') {e.preventDefault();onSelect(c);}}}><title>{c.cell_id} · center unevaluated</title></rect>)}
    {grids.map(g=>{const c=g.cells.find(c=>c.cell_id===g.center_cell_id)!;return <text key={g.site_id} x={x(c.center_x_m)} y={y(c.center_y_m)-1000*scale*1.8} textAnchor="middle" className="maplabel">{g.site_id} neighborhood</text>;})}
    <text x="40" y="371">1 km cells · lunar sphere R = 1,737.4 km · projected metres</text>
  </svg>;
}

function Scatter({features,onSelect}:{features:Features|null;onSelect:(id:string)=>void}) {
  const refs=features?.reference_points??[];
  const valid=refs.filter(p=>p.values[0]!=null&&p.values[3]!=null);
  const ymax=Math.max(4,...valid.map(p=>p.values[3]!))*1.1;
  return <><svg viewBox="0 0 360 245" role="img" aria-label="Physical features: Sun visible fraction versus longest shared hours">
    {[0,.5,1].map(v=><g key={v}><line x1={52+v*270} x2={52+v*270} y1="25" y2="190" className="gridline"/><text x={52+v*270} y="210" textAnchor="middle">{v}</text></g>)}
    <path d="M52 25V190H322" className="zero"/><text x="185" y="237" textAnchor="middle">Sun-visible fraction</text><text x="13" y="120" transform="rotate(-90 13 120)" textAnchor="middle">Longest shared (h)</text><text x="42" y="31" textAnchor="end">{ymax.toFixed(1)}</text><text x="42" y="194" textAnchor="end">0</text>
    {valid.map(p=><g key={p.scenario_id} tabIndex={0} role="button" aria-label={`${p.site_id} reference point in ${p.cell_id}`} onClick={()=>onSelect(p.cell_id)} onKeyDown={e=>{if(e.key==='Enter')onSelect(p.cell_id);}}><circle cx={52+p.values[0]!*270} cy={190-p.values[3]!/ymax*165} r="6" fill="var(--accent)"/><text x={62+p.values[0]!*270} y={186-p.values[3]!/ymax*165}>{p.site_id} reference</text></g>)}
    {!valid.length&&<text x="185" y="106" textAnchor="middle">No complete plot values</text>}
  </svg><p className="small">{features?.points.length??0} cell centers unevaluated. Reference observations remain separate. Missing values stay null.</p></>;
}

function App() {
  const [request,setRequest]=useState(initial),[result,setResult]=useState<Recovery|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState(''),[connected,setConnected]=useState(false);
  const [selected,setSelected]=useState(0),[time,setTime]=useState(0),[grids,setGrids]=useState<Grid[]>([]),[cell,setCell]=useState<Cell|null>(null),[features,setFeatures]=useState<Features|null>(null),[featureError,setFeatureError]=useState(''),[gridError,setGridError]=useState('');
  const [text,setText]=useState(''),[interpretBusy,setInterpretBusy]=useState(false),[mockOutcome,setMockOutcome]=useState<Outcome>('KEEP_SITE_AFTER_DELAY');
  const all=result?[...result.original_scenarios,...result.delayed_scenarios,...(result.future_scenarios??[])]:[],scenario=all[selected];
  useEffect(()=>{if(MOCK){setGrids(fixtureGrids);return;}let active=true;api('/health').then(()=>{if(active)setConnected(true);}).catch(()=>{if(active)setConnected(false);});
    Promise.all([api<Grid>('/api/v1/grid?site_id=R01'),api<Grid>('/api/v1/grid?site_id=R04')]).then(g=>{if(active)setGrids(g);}).catch(e=>{if(active)setGridError(String(e));});return()=>{active=false;};},[]);
  useEffect(()=>{setTime(0);setFeatures(null);setFeatureError('');let active=true;if(scenario){if(MOCK)setFeatures(fixtureFeatures(scenario));else api<Features>(`/api/v1/features?scenario_id=${scenario.scenario_id}`).then(f=>{if(active)setFeatures(f);}).catch(e=>{if(active)setFeatureError(String(e));});}return()=>{active=false;};},[scenario?.scenario_id]);
  function update<K extends keyof MissionRequest>(key:K,value:MissionRequest[K]) { setRequest(r=>({...r,[key]:value})); }
  async function run(e:React.FormEvent) {e.preventDefault();setBusy(true);setError('');setResult(null);setSelected(0);try{setResult(MOCK?fixture(request,mockOutcome):await api<Recovery>('/api/v1/recovery',request));}catch(e){setError(e instanceof Error?e.message:String(e));}finally{setBusy(false);}}
  async function translate(){setInterpretBusy(true);setError('');try{const r=await api<{parsed_requirements:MissionRequest;provider_used:string;validation_errors:string[]}>('/api/v1/interpret',{text,provider_preference:'auto'});if(r.provider_used==='unavailable')setError(r.validation_errors.join('; '));else setRequest(r.parsed_requirements);}catch(e){setError(String(e));}finally{setInterpretBusy(false);}}
  return <div className="app"><header><a className="wordmark" href="#main"><span className="orbit">◒</span> WISPR<span className="wordmark-note">LUNAR FIELD NOTES / 01</span></a><div className="connection"><span className={`dot ${connected?'on':''}`}/>{MOCK?'SYNTHETIC MODE':connected?'BACKEND CONNECTED':'BACKEND OFFLINE'}<a href={BASE+'/docs'} target="_blank" rel="noreferrer">API ↗</a></div></header>
    {MOCK&&<div className="synthetic">SYNTHETIC EXAMPLE — NOT NASA DATA</div>}
    <main id="main"><section className="intro"><div><p className="eyebrow">SOUTH POLE / SCHEDULE RECOVERY</p><h1>Seven days later.<br/><span>What still works?</span></h1><p className="lede">Compare two lunar reference regions for a continuous window of sunlight and direct-to-Earth visibility.</p></div><div className="mission-note"><span className="cross">+</span><p>02 reference regions<br/>04 original / delayed scenarios<br/>01 shared visibility requirement</p><small>Geometric estimates. Every result keeps its source.</small></div></section>
    <section className="workspace"><aside className="panel inputs"><div className="panel-title"><span className="index">01</span><h2>Define the schedule</h2></div>
      <details className="language"><summary>Describe the mission</summary><label htmlFor="question">Optional language input</label><textarea id="question" value={text} onChange={e=>setText(e.target.value)} placeholder="My mission is delayed seven days…"/><button className="secondary" disabled={!text||interpretBusy||MOCK} onClick={translate}>{interpretBusy?'Interpreting…':'Fill the form'}</button><p className="small">Requires a configured server-side model. Review all fields before running.</p></details>
      <form onSubmit={run}><label htmlFor="site">Original reference region</label><select required id="site" value={request.original_site_id??''} onChange={e=>update('original_site_id',e.target.value ? e.target.value as 'R01'|'R04' : null)}><option value="" disabled>Select a reference region</option><option value="R01">R01 · Connecting Ridge</option><option value="R04">R04 · Shackleton Rim</option></select>
      <label htmlFor="arrival">Original arrival <span>UTC</span></label><input required id="arrival" type="datetime-local" min="1900-01-01T00:00" max="2100-12-31T23:59" value={request.original_arrival_utc?.slice(0,16)??''} onChange={e=>update('original_arrival_utc',e.target.value?e.target.value+':00Z':null)}/><button type="button" className="text-button" onClick={()=>update('original_arrival_utc','2026-11-20T00:00:00Z')}>Use development example · 20 Nov 2026</button>
      <div className="form-row"><div><label htmlFor="duration">Study length</label><select required id="duration" value={request.study_duration_hours??''} onChange={e=>update('study_duration_hours',e.target.value ? +e.target.value : null)}><option value="" disabled>Select study length</option>{request.study_duration_hours!=null&&![24,48].includes(request.study_duration_hours)&&<option value={request.study_duration_hours}>{request.study_duration_hours} hours</option>}<option value="24">24 hours</option><option value="48">48 hours</option></select></div><div><label htmlFor="step">Sample spacing</label><select id="step" value={request.step_minutes} onChange={e=>update('step_minutes',+e.target.value)}>{![5,10,15].includes(request.step_minutes)&&<option value={request.step_minutes}>{request.step_minutes} minutes</option>}<option value="5">5 minutes</option><option value="10">10 minutes</option><option value="15">15 minutes</option></select></div></div>
      <label htmlFor="model">Horizon model</label><select id="model" value={request.horizon_model} onChange={e=>update('horizon_model',e.target.value as MissionRequest['horizon_model'])}><option value="GEOMETRIC">Geometric · ideal horizon</option><option value="LOCAL_TERRAIN">Local terrain · requires coverage</option></select>
      <div className="constraint"><div><span>Schedule delay</span><strong>+168 h</strong></div><div><span>Minimum shared window</span><strong>{request.min_continuous_overlap_minutes} min</strong></div></div>
      <details><summary>Search and observer settings</summary><label htmlFor="height">Height above DEM ground (m)</label><input id="height" type="number" min="0" max="100" step="0.1" value={request.observer_height_m} onChange={e=>update('observer_height_m',+e.target.value)}/><p className="small">Geometric mode uses the separately documented JPL reference-sphere height.</p><label htmlFor="future">Additional arrival dates</label><select id="future" value={request.future_search_days} onChange={e=>update('future_search_days',+e.target.value)}><option value="0">No future search</option><option value="1">Next 1 day · daily arrivals</option><option value="3">Next 3 days · daily arrivals</option><option value="7">Next 7 days · daily arrivals</option></select></details>
      {MOCK&&<><label htmlFor="fixture">Synthetic outcome</label><select id="fixture" value={mockOutcome} onChange={e=>setMockOutcome(e.target.value as Outcome)}>{Object.entries(outcomes).map(([k,v])=><option key={k} value={k}>{v}</option>)}</select></>}
      <button className="primary" disabled={busy}>{busy?'Calculating four scenarios…':'Compare the schedules'}<span aria-hidden="true">↗</span></button><p className="small">R01 and R04 are evaluated at both arrivals. This issues no mission command.</p></form>
    </aside><div className="results"><div className="panel comparison"><div className="panel-title"><span className="index">02</span><h2>Original → delayed</h2><span className="tag">UTC</span></div>
      {error&&<div className="error" role="alert">{error}</div>}
      {busy&&<div className="empty" role="status"><div className="loader"/><h3>Requesting Sun and Earth observations</h3><p>Eight target series, two regions, two arrival dates.<br/>Missing data will remain unknown.</p></div>}
      {!result&&!busy&&<div className="empty"><div className="empty-orbit">◒</div><p className="eyebrow">A DATE IS THE STARTING POINT</p><h3>Define an arrival.<br/>See what the delay changes.</h3><p>The original date is never assumed.<br/>Use your schedule or the labeled development example.</p></div>}
      {result&&<><div className={`decision ${result.recommended_outcome==='INSUFFICIENT_DATA'?'uncertain':''}`}><p className="eyebrow">{result.source_type.replaceAll('_',' ')}</p><h3>{outcomes[result.recommended_outcome]}</h3><p>{result.recommendation_reason}</p>{result.recommended_window&&<p><strong>{result.recommended_site_id}</strong> · {utc(result.recommended_window.start_utc)}<br/>{result.recommended_window.duration_minutes.toFixed(1)} min modeled shared window</p>}{!!result.missing_fields?.length&&<p>Required: {result.missing_fields.join(', ')}</p>}</div>
      <div className="scenario-grid">{all.map((s,i)=><button key={s.scenario_id} className={`scenario ${selected===i?'active':''}`} onClick={()=>setSelected(i)}><span>{i<2?'ORIGINAL':i<4?'+7 DAYS':'FUTURE'}<span className={`status ${s.qualifying_status.toLowerCase()}`}>{s.qualifying_status}</span></span><strong>{s.site_id}</strong><small>{utc(s.arrival_utc)}</small><div className="scenario-metric">{hours(s.longest_shared_minutes)}<small>longest shared</small></div><small>{percent(s.unknown_fraction)} unknown</small></button>)}</div>
      <p className="small search-scope">Scope: R01 + R04 · {result.search_scope.study_duration_hours} h per arrival · {result.search_scope.future_arrivals_evaluated?.length??0} later arrival dates evaluated.</p></>}
    </div>
    {scenario&&<section className="panel observation"><div className="panel-title"><span className="index">03</span><h2>{scenario.site_id} / visibility</h2><span className="tag">MODEL ESTIMATE</span></div><div className="metric-row"><div><span>First qualifying window</span><strong>{hours(scenario.time_to_first_qualifying_minutes)} <small>after arrival</small></strong></div><div><span>Known interval</span><strong>{percent(scenario.known_fraction)}</strong></div></div><div className="legend"><span className="sun-dot">Sun elevation</span><span className="earth-dot">Earth elevation</span><span>— 0° threshold</span></div><ElevationChart scenario={scenario}/><Timeline scenario={scenario}/>{!!scenario.reason_codes.length&&<p className="reason">{scenario.reason_codes.join(' · ')}</p>}<a className="text-link" href={MOCK?undefined:BASE+`/api/v1/export/${scenario.scenario_id}.csv`} aria-disabled={MOCK}>Download observations CSV ↗</a></section>}
    </div></section>
    <section className="lower"><div className="panel map-panel"><div className="panel-title"><span className="index">04</span><h2>The same ground, indexed</h2><span className="tag">1 KM GRID</span></div><GridMap grids={grids} selected={cell} onSelect={setCell}/>{gridError&&<p className="small error">{gridError}</p>}<div className="map-footer"><p><span className="square"/>Unevaluated cell center</p><span>No imagery or terrain coverage implied</span></div>{cell?<div className="cell-details"><strong>{cell.cell_id}</strong><span>{cell.center_lat_deg.toFixed(5)}° lat / {cell.center_lon_east_deg.toFixed(5)}° E</span><span>Terrain {cell.raster_coverage.toLowerCase()} · ephemeris {cell.ephemeris_status.toLowerCase()}</span><span>Canonical lunar sphere geometry. A region center is not a cell-center observation.</span></div>:<p className="small">Select a cell to inspect its stable ID, coordinates and coverage.</p>}</div>
    <div className="panel"><div className="panel-title"><span className="index">05</span><h2>Physical feature space</h2></div><Scatter features={features} onSelect={id=>{const found=grids.flatMap(g=>g.cells).find(c=>c.cell_id===id);if(found)setCell(found);}}/>{featureError&&<p className="small error">{featureError}</p>}<p className="small">Physical similarity is separate from geographic proximity. No embeddings or inferred terrain values.</p></div></section>
    {scenario&&<section className="panel sky-section"><div><div className="panel-title"><span className="index">06</span><h2>Local sky directions</h2></div><p>ENU vectors from the selected scenario. The circle represents the ideal horizon; faint markers sit below it.</p><p className="small">Local terrain and the far-field horizon are unverified. This view makes no terrain-clearance claim.</p><label htmlFor="time">Observation time · {utc(scenario.visibility_series[time]?.timestamp_utc)}</label><input id="time" type="range" min="0" max={Math.max(0,scenario.visibility_series.length-1)} value={time} disabled={!scenario.visibility_series.length} onChange={e=>setTime(+e.target.value)}/></div><Sky scenario={scenario} index={time}/></section>}
    <section className="method"><details><summary>How calculated, sources and limits <span>+</span></summary><p>At matching UTC instants, target-center Sun and Earth elevations must both exceed 0°. Adjacent known samples support linear model estimates; gaps remain unknown. A shared interval must last at least 180 minutes. Results apply only to the evaluated coordinates and dates.</p><p>The delayed original site is kept if it qualifies. Switching requires the original site to fail and an alternative to qualify. Eligible alternatives are ordered by first qualifying UTC start, shared duration, source coverage and site ID. Unknown data prevents a definitive no-option result.</p><p>Site coordinates are team-supplied reference regions. Geometric visibility does not establish illumination power, communications link margin, terrain clearance or landing safety. Local DEM coverage would still omit distant terrain.</p><a href="https://ssd-api.jpl.nasa.gov/doc/horizons.html" target="_blank" rel="noreferrer">JPL Horizons API ↗</a> · <a href="https://pgda.gsfc.nasa.gov/products/78" target="_blank" rel="noreferrer">NASA LOLA products ↗</a>{scenario&&<><h3>Selected scenario evidence</h3><p>{scenario.source_type} · {scenario.calculation_mode} · {scenario.data_quality}</p>{scenario.provenance.source_urls?.map((url,i)=><a className="source-url" href={url} key={i} target="_blank" rel="noreferrer">Source request {i+1} ↗</a>)}{scenario.provenance.raw_sha256?.map(h=><code className="hash" key={h}>{h}</code>)}<ul>{scenario.limitations.map(l=><li key={l}>{l}</li>)}</ul></>}</details></section>
    <footer><span>WISPR / THE MOON AS A SEARCHABLE MEMORY</span><span>Reference regions. Declared assumptions. Traceable results.</span></footer></main></div>;
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><MissionControl/></React.StrictMode>);
