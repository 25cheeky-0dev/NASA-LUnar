import {useState} from 'react';
import {AdaptiveAtlas} from './AdaptiveAtlas';
import {DigitalMoon} from './DigitalMoon';
import {MissionControl} from './MissionControl';
export function AtlasApp(){const [view,setView]=useState<'moon'|'atlas'|'workbench'>('moon');return view==='moon'?<DigitalMoon onAtlas={()=>setView('atlas')}/>:<><div className="wi-app-switch"><button onClick={()=>setView('moon')}>← 3D Moon workspace</button><button onClick={()=>setView(view==='atlas'?'workbench':'atlas')}>{view==='atlas'?'Advanced mission workbench':'Scientific atlas'}</button><span>WISPR · measured lunar atlas</span></div>{view==='atlas'?<AdaptiveAtlas/>:<MissionControl/>}</>;}
