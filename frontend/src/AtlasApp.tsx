import {useState} from 'react';
import {AdaptiveAtlas} from './AdaptiveAtlas';
import {Explorer} from './Explorer';
export function AtlasApp(){const [mode,setMode]=useState<'atlas'|'3d'>('atlas');return <><div className="wi-app-switch"><button onClick={()=>setMode(mode==='atlas'?'3d':'atlas')}>{mode==='atlas'?'Open 3D lunar explorer ↗':'← Whole-Moon atlas'}</button><span>WISPR · atlas integration v2</span></div>{mode==='atlas'?<AdaptiveAtlas/>:<Explorer/>}</>;}
