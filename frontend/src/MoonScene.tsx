import {useEffect,useRef,useState} from 'react';
import * as THREE from 'three';
import {OrbitControls} from 'three/examples/jsm/controls/OrbitControls.js';
import {moonXYZ,moonLatLon,measurementColor} from './moonMath';
export type MoonCell={cell_id:string;latitude_deg:number;longitude_deg:number;boundary_lonlat?:number[][];elevation_m?:number|null;slope_deg?:number|null;roughness_m?:number|null;quality?:string;geometry?:{coordinates:number[][][]};projected_x?:number;projected_y?:number};
type Props={cells:MoonCell[];selected:MoonCell|null;onPick:(lat:number,lon:number)=>void;layer:string;focus:{lat:number;lon:number;key:number};bars:{cell:MoonCell;fraction:number}[]};
export function MoonScene({cells,selected,onPick,layer,focus,bars}:Props){
 const host=useRef<HTMLDivElement>(null), sceneRef=useRef<{scene:THREE.Scene;camera:THREE.PerspectiveCamera;controls:OrbitControls}|null>(null),pick=useRef(onPick),[error,setError]=useState('');pick.current=onPick;
 useEffect(()=>{if(!host.current)return;const div=host.current;let renderer:THREE.WebGLRenderer;
 try{renderer=new THREE.WebGLRenderer({antialias:true,alpha:true});}catch{setError('3D rendering unavailable. Use named-location or coordinate navigation.');return;}
 renderer.setPixelRatio(Math.min(devicePixelRatio,2));div.appendChild(renderer.domElement);
 const scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera(36,1,.01,100);camera.position.set(3,.6,1.6);
 const controls=new OrbitControls(camera,renderer.domElement);controls.enableDamping=true;controls.minDistance=1.18;controls.maxDistance=6;controls.enablePan=false;
 const texture=new THREE.TextureLoader().load('/moon/lroc_color_2k.jpg',undefined,undefined,()=>setError('NASA texture unavailable; coordinate sphere remains usable.'));texture.colorSpace=THREE.SRGBColorSpace;
 // SphereGeometry u=.5 is +X; NASA centered-0° texture matches the adapter.
 const globe=new THREE.Mesh(new THREE.SphereGeometry(1,128,64),new THREE.MeshStandardMaterial({map:texture,roughness:1}));scene.add(globe);
 scene.add(new THREE.AmbientLight(0xffffff,2));const light=new THREE.DirectionalLight(0xc5d9ff,2.4);light.position.set(4,3,5);scene.add(light);
 const ray=new THREE.Raycaster();let down=[0,0];const start=(e:PointerEvent)=>{down=[e.clientX,e.clientY];};
 const end=(e:PointerEvent)=>{if(Math.hypot(e.clientX-down[0],e.clientY-down[1])>5)return;const r=renderer.domElement.getBoundingClientRect();ray.setFromCamera(new THREE.Vector2((e.clientX-r.left)/r.width*2-1,-(e.clientY-r.top)/r.height*2+1),camera);const hit=ray.intersectObject(globe)[0];if(hit)pick.current(...moonLatLon(hit.point.x,hit.point.y,hit.point.z));};
 renderer.domElement.addEventListener('pointerdown',start);renderer.domElement.addEventListener('pointerup',end);
 const resize=new ResizeObserver(()=>{const w=div.clientWidth,h=div.clientHeight;renderer.setSize(w,h);camera.aspect=w/h;camera.updateProjectionMatrix();});resize.observe(div);sceneRef.current={scene,camera,controls};
 let frame=0;const draw=()=>{frame=requestAnimationFrame(draw);controls.update();renderer.render(scene,camera);};draw();
 return()=>{cancelAnimationFrame(frame);resize.disconnect();controls.dispose();texture.dispose();globe.geometry.dispose();(globe.material as THREE.Material).dispose();renderer.dispose();renderer.domElement.remove();sceneRef.current=null;};},[]);
 useEffect(()=>{const context=sceneRef.current;if(!context)return;const group=new THREE.Group();
 const edges:number[]=[];for(const cell of cells){const ring=cell.boundary_lonlat;if(!ring)continue;for(let i=1;i<ring.length;i++){edges.push(...moonXYZ(ring[i-1][1],ring[i-1][0],1.003),...moonXYZ(ring[i][1],ring[i][0],1.003));}}const geometry=new THREE.BufferGeometry();geometry.setAttribute("position",new THREE.Float32BufferAttribute(edges,3));group.add(new THREE.LineSegments(geometry,new THREE.LineBasicMaterial({color:0x96aebd,transparent:true,opacity:.26})));
 if(selected){const marker=new THREE.Mesh(new THREE.SphereGeometry(.009,12,8),new THREE.MeshBasicMaterial({color:0xffe35b}));marker.position.set(...moonXYZ(selected.latitude_deg,selected.longitude_deg,1.016));group.add(marker);
 if(selected.boundary_lonlat)group.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(selected.boundary_lonlat.map(([lon,lat])=>new THREE.Vector3(...moonXYZ(lat,lon,1.008)))),new THREE.LineBasicMaterial({color:0xffe35b})));}
 for(const {cell,fraction} of bars){const height=.03+.35*fraction,dir=new THREE.Vector3(...moonXYZ(cell.latitude_deg,cell.longitude_deg));const bar=new THREE.Mesh(new THREE.CylinderGeometry(.008,.008,height,6),new THREE.MeshBasicMaterial({color:measurementColor(fraction,0,1)}));bar.position.copy(dir.multiplyScalar(1+height/2));bar.quaternion.setFromUnitVectors(new THREE.Vector3(0,1,0),bar.position.clone().normalize());group.add(bar);}
 context.scene.add(group);return()=>{context.scene.remove(group);group.traverse(o=>{if(o instanceof THREE.Mesh||o instanceof THREE.Line){o.geometry.dispose();o.material.dispose();}});};},[cells,selected,layer,bars]);
 useEffect(()=>{const c=sceneRef.current;if(c){c.camera.position.set(...moonXYZ(focus.lat,focus.lon,Math.max(3.8,3.2/c.camera.aspect)));c.controls.update();}},[focus]);
 return <><div className="moon-canvas" ref={host} aria-label="Interactive 3D Moon: drag to rotate, scroll to zoom, click to select"/>{error&&<p className="texture-warning" role="alert">{error}</p>}</>;
}
