// Compare the actual production WASM bridge and JS fallback with direct SGP4 samples.
import {readFile,writeFile} from 'node:fs/promises';
import {initializeCompute,prepareScene,computeFrame,computedPosition,releaseScene} from '../../web/studio/compute.js';
import {interpolatePosition} from '../../web/studio/interpolation.js';
const path=process.argv[2];
if(!path)throw Error('Usage: node scripts/studio/validate_interpolation.mjs reference.json [report.json]');
const {scene,cases}=JSON.parse(await readFile(path,'utf8'));
if(!await initializeCompute(await readFile(new URL('../../web/studio/wasm/godsat_studio_core.wasm',import.meta.url))))throw Error('WASM unavailable');
prepareScene(scene);
let wasmMax=0,jsMax=0,disagreement=0,squared=0,count=0;
for(const row of cases){computeFrame(scene,row.step);scene.objects.forEach((o,j)=>{
 const a=computedPosition(scene,o.id,row.step),b=interpolatePosition(o,scene.times,row.step),r=row.positions_km[j];
 if(!a||!b||!r)throw Error('Unexpected missing reference sample');
 const error=Math.hypot(...a.map((v,k)=>v-r[k]))*1000;
 wasmMax=Math.max(wasmMax,error);squared+=error*error;count++;
 jsMax=Math.max(jsMax,Math.hypot(...b.map((v,k)=>v-r[k]))*1000);
 disagreement=Math.max(disagreement,Math.hypot(...a.map((v,k)=>v-b[k]))*1000);
});}
releaseScene();
const report={reference:path,samples:count,wasm_max_error_m:wasmMax,wasm_rms_error_m:Math.sqrt(squared/count),js_max_error_m:jsMax,backend_disagreement_m:disagreement,scope:'Interpolation error against direct SGP4/Astropy positions; not real-world orbit accuracy'};
console.log(JSON.stringify(report,null,2));
if(process.argv[3])await writeFile(process.argv[3],JSON.stringify(report,null,2)+'\n');
if(disagreement>1e-6||wasmMax>1)throw Error('Interpolation validation exceeds 1 m reference error or 1 micrometre backend agreement');
