// Check every window's decoded scene and full WASM output on the running service.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {decodePackedScene,PACKED_SCENE_MIME} from '../../web/studio/packed-scene.js';
import {initializeCompute,prepareScene,computeFrame} from '../../web/studio/compute.js';
const origin=new URL(process.argv[2]||'http://127.0.0.1:8769');
assert.equal(origin.protocol,'http:');assert.ok(['127.0.0.1','localhost','[::1]'].includes(origin.hostname));
async function read(path,headers){const response=await fetch(new URL(path,origin),{headers});assert.equal(response.status,200);return response;}
const catalog=await (await read('/api/studio/catalog')).json();
const artifact=catalog.artifacts.find(x=>x.name===(process.argv[3]||'scene-sequence.json'));
assert.ok(artifact,'Sequence manifest must be indexed');
await initializeCompute(readFileSync(new URL('../../web/studio/wasm/godsat_studio_core.wasm',import.meta.url)));
let total=1,frames=0,objects=0;
for(let index=0;index<total;index++){
 const route=`/api/studio/window?id=${encodeURIComponent(artifact.id)}&index=${index}`;
 const plain=await (await read(route)).json();
 const response=await read(route,{Accept:PACKED_SCENE_MIME});
 assert.equal(response.headers.get('Content-Type'),PACKED_SCENE_MIME);
 const packed=decodePackedScene(await response.arrayBuffer());
 assert.deepStrictEqual(packed,plain);
 total=plain.sequence.windows.length;objects=plain.objects.length;
 const steps=Array.from({length:plain.times.length*2-1},(_,i)=>i/2);
 assert.ok(prepareScene(packed));const expected=steps.map(step=>computeFrame(packed,step).slice());
 assert.ok(prepareScene(plain));steps.forEach((step,i)=>assert.deepStrictEqual(computeFrame(plain,step),expected[i]));
 frames+=steps.length;
 console.log(JSON.stringify({window:index+1,total,objects,exactFrames:steps.length}));
}
console.log(JSON.stringify({windows:total,objects,exactFrames:frames}));
