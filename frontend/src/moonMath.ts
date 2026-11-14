// Renderer adapter only: source coordinates are never rewritten.
// +X = 0°E equator, +Y = north, -Z = 90°E, sphere radius in renderer units.
export function moonXYZ(lat:number,lon:number,r=1):[number,number,number]{
  const p=lat*Math.PI/180,l=lon*Math.PI/180;
  return [r*Math.cos(p)*Math.cos(l),r*Math.sin(p),-r*Math.cos(p)*Math.sin(l)];
}
export function moonLatLon(x:number,y:number,z:number):[number,number]{
  return [Math.asin(y/Math.hypot(x,y,z))*180/Math.PI,((Math.atan2(-z,x)*180/Math.PI)%360+360)%360];
}
export const palette=['#284ce9','#665cf6','#db4ea0','#fa6d36','#ffe15b'];
export function measurementColor(value:number|null,min:number,max:number){
  if(value==null||!Number.isFinite(value))return '#52606c';
  return palette[Math.min(4,Math.max(0,Math.floor((value-min)/(max-min)*5)))];
}
