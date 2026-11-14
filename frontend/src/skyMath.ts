import {moonXYZ} from './moonMath';
// East/north/up to the same Moon-fixed axes used by the DEM renderer.
export function skyDirection(lat:number,lon:number,az:number,el:number):[number,number,number]{
 const p=lat*Math.PI/180,l=lon*Math.PI/180,a=az*Math.PI/180,e=el*Math.PI/180;
 const east=[-Math.sin(l),0,-Math.cos(l)],north=[-Math.sin(p)*Math.cos(l),Math.cos(p),Math.sin(p)*Math.sin(l)],up=moonXYZ(lat,lon);
 return [0,1,2].map(i=>east[i]*Math.cos(e)*Math.sin(a)+north[i]*Math.cos(e)*Math.cos(a)+up[i]*Math.sin(e)) as [number,number,number];
}
