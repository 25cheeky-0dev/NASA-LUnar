import {useEffect,useState} from 'react';
import {api} from './lib/api';
import type {Region,RegionContext} from './RegionIntelligence';
type Saved={region:Region;name:string};
export function RegionLibrary({current,onRestore}:{current:Region|null;onRestore:(ctx:RegionContext)=>void}){
 const [items,setItems]=useState<Saved[]>([]),[name,setName]=useState('Research polygon'),[geometry,setGeometry]=useState(''),[error,setError]=useState(''),[busy,setBusy]=useState(false);
 const refresh=()=>api<{regions:Saved[]}>('/api/v1/science/terrain-regions').then(r=>setItems(r.regions)).catch(e=>setError(String(e)));
 useEffect(()=>{refresh();},[current?.region_id]);
 useEffect(()=>{if(current)setGeometry(JSON.stringify(current.geometry,null,2));},[current?.region_id]);
 async function restore(id:string){setBusy(true);setError('');try{onRestore(await api<RegionContext>(`/api/v1/science/regions/${encodeURIComponent(id)}`));}catch(e){setError(String(e));}finally{setBusy(false);}}
 async function edit(){setBusy(true);setError('');try{const result=await api<RegionContext>('/api/v1/science/regions/select',{geometry:JSON.parse(geometry),target_width_m:30000});onRestore(result);refresh();}catch(e){setError(String(e));}finally{setBusy(false);}}
 async function rename(){if(!current)return;setError('');try{await api('/api/v1/science/terrain-regions/name',{region_id:current.region_id,name});refresh();}catch(e){setError(String(e));}}
 return <details><summary>Saved regions & geographic editor</summary>{error&&<p role="alert">{error}</p>}<select aria-label="Saved region" value={current?.region_id??''} disabled={busy} onChange={e=>restore(e.target.value)}><option value="" disabled>Select a saved region</option>{items.map(({region,name})=><option value={region.region_id} key={region.region_id}>{name} · {region.latitude_deg.toFixed(3)}°, {region.longitude_deg.toFixed(3)}°</option>)}</select>{current&&<><label>Region name<input value={name} maxLength={80} onChange={e=>setName(e.target.value)}/></label><button onClick={rename}>Save name</button><p>Edit longitude/latitude vertices, add or remove vertices, or add hole rings. Apply creates a new validated region; the original remains saved.</p><textarea aria-label="Lunar polygon geometry" value={geometry} onChange={e=>setGeometry(e.target.value)} style={{height:180,fontFamily:'monospace'}}/><button disabled={busy} onClick={edit}>Apply geographic geometry</button></>}</details>;
}
