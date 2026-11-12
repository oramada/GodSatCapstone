// CPU-only sequence install: real WASM and renderer, stubbed Cesium primitives.
import {readFileSync} from 'node:fs';
import {initializeCompute,prepareScene} from '../../web/studio/compute.js';
const [first,second]=process.argv.slice(2).map(path=>JSON.parse(readFileSync(path,'utf8')));
if(!second)throw Error('Pass two adjacent canonical window JSON files');
first.sequence={id:'benchmark',index:0};second.sequence={id:'benchmark',index:1};
let adds=0,clears=0,models=0;
const collection=()=>({add(options){adds++;return options;},removeAll(){clears++;}});
globalThis.window={Cesium:{Cartesian3:class {},Cartesian2:class {},Color:{fromBytes(){},WHITE:{}},Axis:{Z:2},ColorBlendMode:{MIX:1},VerticalOrigin:{BOTTOM:1},JulianDate:{fromIso8601:Date.parse},Material:{fromType(){}},Model:{fromGltfAsync(){models++;return Promise.resolve({destroy(){}});}}}};
const {CesiumObservatory}=await import('../../web/studio/cesium-renderer.js');
const view=Object.assign(Object.create(CesiumObservatory.prototype),{points:collection(),labels:collection(),lines:collection(),stationPoints:collection(),radioLine:{},palette:{},environment:{setScene(){}},widget:{clock:{},isDestroyed:()=>false},scene:{primitives:{add(){},remove(){}}},generation:0,reset(){}});
for(const key of ['observed','station','stale','outline','label','labelBackground','trail'])view.palette[key]=[1,2,3];
await initializeCompute(readFileSync(new URL('../../web/studio/wasm/godsat_studio_core.wasm',import.meta.url)));
const focus=first.objects[0].id;
prepareScene(first);view.setScene(first,focus);await Promise.resolve();adds=clears=models=0;
const pack=[],install=[];
for(let i=0;i<12;i++){
 const data=i%2?first:second;
 let t=performance.now();prepareScene(data);pack.push(performance.now()-t);
 t=performance.now();view.setScene(data,focus,true);install.push(performance.now()-t);
 await Promise.resolve();
}
const median=values=>values.sort((a,b)=>a-b)[Math.floor(values.length/2)];
console.log(JSON.stringify({objects:first.objects.length,transitions:12,packMedianMs:median(pack),installMedianMs:median(install),primitiveAdds:adds,collectionClears:clears,modelLoads:models}));
