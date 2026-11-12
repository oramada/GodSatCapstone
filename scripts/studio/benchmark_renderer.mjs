// CPU-only renderer workload: real WASM and renderer logic, stubbed GPU submission.
// Usage: node scripts/studio/benchmark_renderer.mjs [scene.json]
import {readFileSync} from 'node:fs';
import {initializeCompute,prepareScene,computeFrame} from '../../web/studio/compute.js';
class Cartesian3 {constructor(x=0,y=0,z=0){Object.assign(this,{x,y,z});}}
globalThis.window={Cesium:{Cartesian3,Color:{fromBytes:(r,g,b,a)=>({r,g,b,a})},JulianDate:class {
 static secondsDifference(a,b){return a-b;}
 static addSeconds(a,b){return a+b;}
}}};
const {CesiumObservatory}=await import('../../web/studio/cesium-renderer.js');
const data=process.argv[2]?JSON.parse(readFileSync(process.argv[2],'utf8')):{frame:'ITRS',custody_seconds:180,observations:null,times:['2026-11-08T00:00:00Z','2026-11-08T00:00:30Z'],objects:Array.from({length:16896},(_,j)=>({id:String(j),kind:'satellite',positions_km:[[7000,j/10,0],[6997,j/10+210,0]],velocities_km_s:[[0,7,0],[-.2,7,0]]}))};
await initializeCompute(readFileSync(new URL('../../web/studio/wasm/godsat_studio_core.wasm',import.meta.url)));prepareScene(data);
const layers={atmosphere:true,celestial:false,clouds:'clear',ionosphere:false,environment:'none',trails:false,ghosts:false};
for(const mode of ['paused','playing']){
 const counts={pointWrites:0,requests:0,widgetUpdates:0,detailCalls:0,resizeCalls:0};
 const point=()=>new Proxy({},{set(t,k,v){counts.pointWrites++;t[k]=v;return true;}});
 const view=Object.assign(Object.create(CesiumObservatory.prototype),{data,items:data.objects.map((object,index)=>({object,index,point:point(),lines:[]})),dates:data.times.map(t=>Date.parse(t)/1000),focus:data.objects[0].id,mode:'system',colors:Object.fromEntries(['observed','stale','lost','unknown','unavailable'].map(k=>[k,[1,2,3]])),scene:{skyAtmosphere:{},globe:{},sun:{},moon:{},requestRender(){counts.requests++;}},widget:{clock:{},resize(){counts.resizeCalls++;},render(){counts.widgetUpdates++;}},clouds:{appearance:{material:{uniforms:{color:{}}}}},ionosphere:{},environment:{update:()=>''},focusLabel:{},radioLine:{},ghostPoint:{},detail:{update(){counts.detailCalls++;}},generation:1});
 const sample=(k)=>{const step=mode==='paused'?0:k%100/100;computeFrame(data,step);view.update(step,layers);};
 for(let k=0;k<20;k++)sample(k);
 Object.keys(counts).forEach(k=>counts[k]=0);const times=[];
 for(let k=20;k<120;k++){const t=performance.now();sample(k);times.push(performance.now()-t);}
 times.sort((a,b)=>a-b);console.log(JSON.stringify({mode,objects:data.objects.length,frames:times.length,medianMs:times[50],p95Ms:times[95],...counts}));
}
