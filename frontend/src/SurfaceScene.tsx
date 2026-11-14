import {useEffect,useRef,useState} from 'react';
import * as THREE from 'three';
import {OrbitControls} from 'three/examples/jsm/controls/OrbitControls.js';
import {api} from './lib/api';

export type Surface={width:number;height:number;extent_m:number;latitude:number[][];longitude:number[][];elevation_m:(number|null)[][];slope_deg:(number|null)[][];roughness_m:(number|null)[][];reference_radius_m:number;source:{source_id:string;canonical_url:string;source_checksum:string;spatial_resolution_m:number};limitations:string[]};
export type SurfaceLayer='elevation_m'|'slope_deg'|'roughness_m'|'hillshade';
export const ranges={elevation_m:[-8000,6000],slope_deg:[0,30],roughness_m:[0,1500],hillshade:[0,1]};
const stops=['#173c91','#198fcb','#3dd5cc','#97d89d','#e9dd80','#e99654'];
function color(value:number|null,min:number,max:number){if(value===null)return new THREE.Color('#555e68');const t=Math.min(1,Math.max(0,(value-min)/(max-min)))*(stops.length-1),i=Math.min(stops.length-2,Math.floor(t));return new THREE.Color(stops[i]).lerp(new THREE.Color(stops[i+1]),t-i);}
type Props={latitude:number;longitude:number;extent:number;layer:SurfaceLayer;exaggeration:number;split:number;hillshade:number;onPick:(lat:number,lon:number)=>void;onSource:(s:Surface)=>void};
export function SurfaceScene(props:Props){
 const host=useRef<HTMLDivElement>(null),latest=useRef(props);latest.current=props;
 const [surface,setSurface]=useState<Surface|null>(null),[error,setError]=useState('');
 const context=useRef<{renderer:THREE.WebGLRenderer;scene:THREE.Scene;camera:THREE.PerspectiveCamera;controls:OrbitControls;mesh:THREE.Mesh;colored:THREE.MeshStandardMaterial;gray:THREE.MeshStandardMaterial;light:THREE.DirectionalLight}|null>(null);
 useEffect(()=>{let active=true;setError('');api<Surface>(`/api/v1/explorer/surface?latitude=${props.latitude}&longitude=${props.longitude}&extent_km=${props.extent}&resolution=112`).then(s=>{if(active){setSurface(s);latest.current.onSource(s);}}).catch(e=>{if(active){setSurface(null);setError(String(e));}});return()=>{active=false;};},[props.latitude,props.longitude,props.extent]);
 useEffect(()=>{if(!host.current||!surface)return;const div=host.current;let renderer:THREE.WebGLRenderer;
 try{renderer=new THREE.WebGLRenderer({antialias:true,alpha:true});}catch{setError('WebGL unavailable. Use the measured-cell panel and mission workbench.');return;}
 renderer.setPixelRatio(Math.min(devicePixelRatio,1.75));renderer.setClearColor(0x030609);renderer.setScissorTest(true);div.appendChild(renderer.domElement);
 const scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera(42,1,.01,10000),size=surface.extent_m/1000;
 camera.position.set(size*.18,size*.65,size*.87);const controls=new OrbitControls(camera,renderer.domElement);controls.enableDamping=true;controls.minDistance=size*.05;controls.maxDistance=size*2.8;controls.maxPolarAngle=Math.PI*.49;controls.target.set(0,-size*.03,0);
 const geo=new THREE.BufferGeometry(),vertices:number[]=[],indices:number[]=[],uv:number[]=[];
 for(let r=0;r<surface.height;r++)for(let c=0;c<surface.width;c++){vertices.push((c/(surface.width-1)-.5)*size,0,(r/(surface.height-1)-.5)*size);uv.push(c/(surface.width-1),1-r/(surface.height-1));}
 for(let r=0;r<surface.height-1;r++)for(let c=0;c<surface.width-1;c++){const a=r*surface.width+c,b=a+1,d=a+surface.width,e=d+1;if([surface.elevation_m[r][c],surface.elevation_m[r][c+1],surface.elevation_m[r+1][c],surface.elevation_m[r+1][c+1]].every(v=>v!==null))indices.push(a,d,b,b,d,e);}
 geo.setAttribute('position',new THREE.Float32BufferAttribute(vertices,3));geo.setAttribute('uv',new THREE.Float32BufferAttribute(uv,2));geo.setIndex(indices);
 const colored=new THREE.MeshStandardMaterial({vertexColors:true,roughness:1,side:THREE.DoubleSide}),gray=new THREE.MeshStandardMaterial({color:'#c3c5c8',roughness:1,side:THREE.DoubleSide});
 const mesh=new THREE.Mesh(geo,colored);scene.add(mesh);scene.add(new THREE.AmbientLight('#abc4df',.7));const light=new THREE.DirectionalLight('#fff3dc',2.4);scene.add(light);
 const ray=new THREE.Raycaster();let down=[0,0];const start=(e:PointerEvent)=>{down=[e.clientX,e.clientY];};const end=(e:PointerEvent)=>{if(Math.hypot(e.clientX-down[0],e.clientY-down[1])>5)return;const rect=div.getBoundingClientRect();ray.setFromCamera(new THREE.Vector2((e.clientX-rect.left)/rect.width*2-1,1-(e.clientY-rect.top)/rect.height*2),camera);const hit=ray.intersectObject(mesh)[0];if(hit?.uv){const c=Math.round(hit.uv.x*(surface.width-1)),r=Math.round((1-hit.uv.y)*(surface.height-1));latest.current.onPick(surface.latitude[r][c],surface.longitude[r][c]);}};
 renderer.domElement.addEventListener('pointerdown',start);renderer.domElement.addEventListener('pointerup',end);
 context.current={renderer,scene,camera,controls,mesh,colored,gray,light};const resize=new ResizeObserver(()=>{renderer.setSize(div.clientWidth,div.clientHeight);camera.aspect=div.clientWidth/div.clientHeight;camera.updateProjectionMatrix();});resize.observe(div);
 let frame=0;const draw=()=>{frame=requestAnimationFrame(draw);if(document.hidden)return;controls.update();const w=div.clientWidth,h=div.clientHeight,s=latest.current.split;renderer.setScissor(0,0,w,h);renderer.clear();if(s>0){mesh.material=gray;renderer.setScissor(0,0,Math.round(w*s/100),h);renderer.render(scene,camera);}if(s<100){mesh.material=latest.current.layer==='hillshade'?gray:colored;renderer.setScissor(Math.round(w*s/100),0,w-Math.round(w*s/100),h);renderer.render(scene,camera);}};draw();
 return()=>{cancelAnimationFrame(frame);resize.disconnect();controls.dispose();geo.dispose();colored.dispose();gray.dispose();renderer.dispose();renderer.domElement.remove();context.current=null;};
 },[surface]);
 useEffect(()=>{const ctx=context.current;if(!ctx||!surface)return;const positions=ctx.mesh.geometry.getAttribute('position'),colors:number[]=[],range=ranges[props.layer],R=surface.reference_radius_m;
 for(let r=0;r<surface.height;r++)for(let c=0;c<surface.width;c++){const x=(c/(surface.width-1)-.5)*surface.extent_m,y=(r/(surface.height-1)-.5)*surface.extent_m,d=Math.hypot(x,y),theta=d/R,z=surface.elevation_m[r][c]??0,radius=R+z*props.exaggeration,k=d?radius*Math.sin(theta)/d:1;positions.setXYZ(r*surface.width+c,x*k/1000,(radius*Math.cos(theta)-R)/1000,y*k/1000);const col=color(props.layer==='hillshade'?0:surface[props.layer][r][c],range[0],range[1]);colors.push(col.r,col.g,col.b);}
 positions.needsUpdate=true;ctx.mesh.geometry.setAttribute('color',new THREE.Float32BufferAttribute(colors,3));ctx.mesh.geometry.computeVertexNormals();ctx.mesh.geometry.computeBoundingSphere();const a=props.hillshade*Math.PI/180;ctx.light.position.set(Math.cos(a)*200,100,Math.sin(a)*200);
 },[surface,props.layer,props.exaggeration,props.hillshade]);
 return <div ref={host} className="surface-canvas" aria-label="DEM-derived south polar terrain: drag to orbit, right-drag to pan, scroll to zoom, click to inspect">{error&&<div className="surface-error" role="alert">{error}</div>}{!surface&&!error&&<div className="surface-error">Loading verified lunar elevation…</div>}</div>;
}
