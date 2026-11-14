import assert from 'node:assert/strict';
import { createServer } from 'vite';

const server=await createServer({server:{middlewareMode:true,hmr:false,ws:false},optimizeDeps:{noDiscovery:true},appType:'custom'});
try {
  const {fixture,fixtureFeatures,fixtureGrids}=await server.ssrLoadModule('/src/mocks/recovery.ts');
  const request={original_site_id:'R01',original_arrival_utc:'2026-11-20T00:00:00Z',study_duration_hours:24,delay_hours:168,min_continuous_overlap_minutes:180,candidate_site_ids:['R01','R04'],horizon_model:'GEOMETRIC',observer_height_m:1,step_minutes:5,future_search_days:1};
  for(const outcome of ['KEEP_SITE_AFTER_DELAY','SWITCH_SITE_AFTER_DELAY','POSTPONE_AND_REEVALUATE','NO_QUALIFYING_OPTION_WITHIN_SEARCH','INSUFFICIENT_DATA','NEEDS_INPUT']) {
    const result=fixture(request,outcome);
    assert.equal(result.recommended_outcome,outcome);
    assert.equal(result.source_type,'SYNTHETIC_TEST_ONLY');
    assert.equal(result.original_scenarios.length+result.delayed_scenarios.length,4);
    assert.equal(Date.parse(result.delayed_scenarios[0].arrival_utc)-Date.parse(result.original_scenarios[0].arrival_utc),168*3600000);
    for(const scenario of [...result.original_scenarios,...result.delayed_scenarios,...result.future_scenarios]) {
      assert.equal(scenario.longest_shared_minutes,scenario.qualifying_status==='UNKNOWN'?null:Math.max(...scenario.shared_windows.map(w=>w.duration_minutes),0));
      if(scenario.earliest_qualifying_window)assert(scenario.earliest_qualifying_window.duration_minutes>=180);
      const features=fixtureFeatures(scenario),ids=new Set(fixtureGrids.flatMap(g=>g.cells).map(c=>c.cell_id));
      assert(features.points.every(p=>p.values.every(v=>v===null)));
      assert(features.reference_points.every(p=>ids.has(p.cell_id)));
    }
  }
  const bounded=fixture({...request,future_search_days:0},'POSTPONE_AND_REEVALUATE');
  assert.equal(bounded.future_scenarios.length,0);
  assert.equal(bounded.recommended_outcome,'NO_QUALIFYING_OPTION_WITHIN_SEARCH');
  console.log('Six synthetic outcomes: UTC shifts, window consistency, missing features and shared grid IDs passed.');
} finally {await server.close();}

const mathServer=await createServer({server:{middlewareMode:true,hmr:false,ws:false},optimizeDeps:{noDiscovery:true},appType:'custom'});
try {
 const {moonXYZ,moonLatLon,measurementColor}=await mathServer.ssrLoadModule('/src/moonMath.ts');
 for(const [lat,lon,expected] of [[0,0,[1,0,0]],[0,90,[0,0,-1]],[90,0,[0,1,0]],[-90,0,[0,-1,0]]]){
  moonXYZ(lat,lon).forEach((x,i)=>assert(Math.abs(x-expected[i])<1e-12));
 }
 for(const lat of [-89.9,-45,0,45,89.9])for(const lon of [0,45,180,270,359.99]){
  const back=moonLatLon(...moonXYZ(lat,lon));assert(Math.abs(back[0]-lat)<1e-8);assert(Math.abs(back[1]-lon)<1e-8);
 }
 assert.equal(measurementColor(null,0,90),'#52606c');
 console.log('Moon coordinate registration, wrap and unknown-color checks passed');
}finally{await mathServer.close();}
