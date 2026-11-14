import type { MissionRequest, Outcome, Recovery, Scenario, Sky, Window, Features, Grid, Feature } from '../lib/api';
import grids from './grids.json';
export const fixtureGrids = grids as Grid[];
const source = { source_type: 'SYNTHETIC_TEST_ONLY', calculation_mode: 'GEOMETRIC_IDEAL', data_quality: 'SYNTHETIC_TEST_ONLY', provenance: { source_urls: [], raw_sha256: [] }, limitations: ['SYNTHETIC EXAMPLE — NOT NASA DATA'] };
function sky(el: number, az: number): Sky { const a = az * Math.PI/180, e = el * Math.PI/180; return { az_deg: az, el_deg: el, east: Math.cos(e)*Math.sin(a), north: Math.cos(e)*Math.cos(a), up: Math.sin(e), status: 'KNOWN' }; }
export function fixture(request: MissionRequest, outcome: Outcome): Recovery {
  const original = new Date(request.original_arrival_utc ?? '2026-11-20T00:00:00Z');
  const duration = request.study_duration_hours ?? 24;
  const scenario = (site: 'R01' | 'R04', delayed: boolean): Scenario => {
    const start = new Date(+original + (delayed ? 168 : 0)*3600000);
    const end = new Date(+start + duration*3600000);
    const unknown = outcome === 'INSUFFICIENT_DATA' || request.horizon_model === 'LOCAL_TERRAIN';
    const passes = !unknown && (outcome === 'KEEP_SITE_AFTER_DELAY' ? site === request.original_site_id : outcome === 'SWITCH_SITE_AFTER_DELAY' ? site !== request.original_site_id : !delayed);
    const length = Math.min(duration*60, passes ? 240 : 120);
    const w: Window = { start_utc: start.toISOString(), end_utc: new Date(+start+length*60000).toISOString(), duration_minutes: length, kind: 'BOTH', estimate_status: 'MODEL_ESTIMATE', boundary_uncertainty_seconds: 300, model: 'GEOMETRIC_IDEAL' };
    return { ...source, scenario_id: `SYNTHETIC-${site}-${delayed}`, site_id: site, arrival_utc: start.toISOString(), end_utc: end.toISOString(), horizon_model: request.horizon_model,
      sun_windows: unknown ? [] : [{...w,kind:'SUN'}], earth_windows: unknown ? [] : [{...w,kind:'EARTH'}], shared_windows: unknown ? [] : [w], longest_shared_minutes: unknown ? null : length,
      earliest_qualifying_window: passes && length >= request.min_continuous_overlap_minutes ? w : null, known_fraction: unknown ? 0 : 1, unknown_fraction: unknown ? 1 : 0,
      qualifying_status: unknown ? 'UNKNOWN' : passes && length >= request.min_continuous_overlap_minutes ? 'QUALIFIES' : 'FAILS', reason_codes: unknown ? ['SYNTHETIC_MISSING_DATA'] : passes ? [] : ['SYNTHETIC_NO_QUALIFYING_WINDOW'], time_to_first_qualifying_minutes: passes ? 0 : null,
      unknown_intervals: unknown ? [{start_utc:start.toISOString(),end_utc:end.toISOString(),reason:'SYNTHETIC_UNKNOWN'}] : [],
      visibility_series: Array.from({length: Math.floor(duration*12)+1},(_,i) => ({timestamp_utc:new Date(+start+i*300000).toISOString(),sun:unknown?null:sky(i*5<length?2:-1, (120+i*.12)%360),earth:unknown?null:sky(1,220),status:unknown?'UNKNOWN' as const:'KNOWN' as const,gap_reason:unknown?'SYNTHETIC_UNKNOWN':null})) };
  };
  const originals = [scenario('R01',false),scenario('R04',false)], delayed = [scenario('R01',true),scenario('R04',true)];
  const future = outcome === 'POSTPONE_AND_REEVALUATE' && request.horizon_model === 'GEOMETRIC' && request.future_search_days > 0 ? [scenario('R01',false)] : [];
  if(future[0]) {
    const f=future[0], shift=(stamp:string)=>new Date(Date.parse(stamp)+192*3600000).toISOString();
    f.scenario_id='SYNTHETIC-FUTURE';f.arrival_utc=shift(f.arrival_utc);f.end_utc=shift(f.end_utc);
    f.sun_windows=f.sun_windows.map(w=>({...w,start_utc:shift(w.start_utc),end_utc:shift(w.end_utc)}));
    f.earth_windows=f.earth_windows.map(w=>({...w,start_utc:shift(w.start_utc),end_utc:shift(w.end_utc)}));
    f.shared_windows=f.shared_windows.map(w=>({...w,start_utc:shift(w.start_utc),end_utc:shift(w.end_utc)}));
    f.earliest_qualifying_window=f.shared_windows[0]??null;
    f.visibility_series=f.visibility_series.map(r=>({...r,timestamp_utc:shift(r.timestamp_utc)}));
  }
  const picked = future[0] ?? delayed.find(s=>s.qualifying_status==='QUALIFIES');
  return {...source,request,original_scenarios: originals,delayed_scenarios:delayed,future_scenarios:future,ranked_eligible:[...delayed,...future].filter(s=>s.qualifying_status==='QUALIFIES'),recommended_outcome:unknownOutcome(),recommended_site_id:picked?.site_id??null,recommended_window:picked?.earliest_qualifying_window??null,
    recommendation_reason:'Synthetic interface example. No lunar conditions have been calculated.',missing_fields:outcome==='NEEDS_INPUT'?['original_arrival_utc']:[],search_scope:{original_arrival_utc:original.toISOString(),delayed_arrival_utc:new Date(+original+168*3600000).toISOString(),study_duration_hours:duration,future_search_days:request.future_search_days},rejections:[],unknowns:[],scientific_disclaimer:'SYNTHETIC EXAMPLE — NOT NASA DATA'};
  function unknownOutcome() { return request.horizon_model==='LOCAL_TERRAIN' ? 'INSUFFICIENT_DATA' as const : outcome==='POSTPONE_AND_REEVALUATE' && request.future_search_days===0 ? 'NO_QUALIFYING_OPTION_WITHIN_SEARCH' as const : outcome; }
}

export function fixtureFeatures(scenario:Scenario):Features {
  const grid=fixtureGrids.find(g=>g.site_id===scenario.site_id)!;
  const names=['sun_visible_fraction','earth_visible_fraction','shared_visible_fraction','longest_shared_hours','unknown_fraction','terrain_slope_deg'];
  const total=(Date.parse(scenario.end_utc)-Date.parse(scenario.arrival_utc))/60000;
  const fraction=(windows:Window[])=>scenario.known_fraction===1?windows.reduce((sum,w)=>sum+w.duration_minutes,0)/total:null;
  const reference:Feature={cell_id:grid.center_cell_id,scenario_id:scenario.scenario_id,feature_names:names,values:[fraction(scenario.sun_windows),fraction(scenario.earth_windows),fraction(scenario.shared_windows),scenario.longest_shared_minutes==null?null:scenario.longest_shared_minutes/60,scenario.unknown_fraction,null],quality:'SYNTHETIC_TEST_ONLY',site_id:scenario.site_id,observation_point_type:'REFERENCE_SITE'};
  return {points:grid.cells.map(c=>({...reference,cell_id:c.cell_id,values:Array(6).fill(null),quality:'UNEVALUATED',observation_point_type:'CELL_CENTER'})),reference_points:[reference],scatter_axes:{x:names[0],y:names[3],z:names[1]}};
}
