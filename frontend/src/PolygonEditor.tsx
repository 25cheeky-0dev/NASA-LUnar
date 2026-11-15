import {useState} from 'react';
export type Vertex = [number, number]; // longitude, latitude
export function closedPolygon(vertices:Vertex[]):Vertex[]{
 if(vertices.length<3)throw Error('Add at least three vertices.');
 if(vertices.length>64)throw Error('Use at most 64 vertices.');
 const points:Vertex[]=vertices.map(([lon,lat])=>{if(!Number.isFinite(lon)||!Number.isFinite(lat)||lat< -90||lat>90)throw Error('Enter valid lunar coordinates.');return [((lon+180)%360+360)%360-180,lat];});
 if(new Set(points.map(p=>p.map(v=>v.toFixed(9)).join(','))).size!==points.length)throw Error('Each vertex must be different.');
 return [...points,[...points[0]]];
}
type Props={vertices:Vertex[];busy:boolean;onAdd:(lat:number,lon:number)=>void;onUndo:()=>void;onClear:()=>void;onCancel:()=>void;onFinish:()=>void};
export function PolygonEditor(p:Props){
 const [lat,setLat]=useState(''),[lon,setLon]=useState('');
 return <><p>Click the Moon to add corners in boundary order. Drag to orbit and scroll to zoom. Finish closes the boundary automatically.</p>
 <p role="status">{p.vertices.length} / 64 vertices</p>
 <form onSubmit={e=>{e.preventDefault();p.onAdd(Number(lat),Number(lon));setLat('');setLon('');}}><div className="dm-fields"><label>Latitude (°)<input aria-label="Polygon latitude" type="number" min="-90" max="90" step="any" required value={lat} onChange={e=>setLat(e.target.value)}/></label><label>Longitude east (°)<input aria-label="Polygon longitude" type="number" min="-180" max="360" step="any" required value={lon} onChange={e=>setLon(e.target.value)}/></label></div><button disabled={p.busy||p.vertices.length>=64} type="submit">Add coordinate</button></form>
 {p.vertices.length>0&&<ol className="dm-vertices" aria-label="Polygon vertices">{p.vertices.map(([x,y],i)=><li key={i}>{y.toFixed(5)}° N, {x.toFixed(5)}° E</li>)}</ol>}
 <div className="dm-fields"><button disabled={p.busy||!p.vertices.length} onClick={p.onUndo}>Undo vertex</button><button disabled={p.busy||!p.vertices.length} onClick={p.onClear}>Clear vertices</button></div>
 <button className="dm-primary" disabled={p.busy||p.vertices.length<3} onClick={p.onFinish}>Finish polygon</button><button disabled={p.busy} onClick={p.onCancel}>Cancel drawing</button>
 <p>Use a regional area up to 100,000 km². Crossing edges and oversized regions are rejected. Terrain statistics use the polygon footprint; Sun / Earth calculations use its representative point.</p></>;
}
