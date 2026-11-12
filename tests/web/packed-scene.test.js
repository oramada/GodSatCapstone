import test from 'node:test';
import assert from 'node:assert/strict';
import {decodePackedScene} from '../../web/studio/packed-scene.js';
import {readFileSync} from 'node:fs';
import {initializeCompute,prepareScene,computeFrame} from '../../web/studio/compute.js';

const scene={times:['2026-11-08T00:00:00Z','2026-11-08T00:00:30Z'],custody_seconds:180,observations:null,objects:[{id:'a'},{id:'b'}],source:{kind:'modeled',description:'Fixture π'}};
function packet(values){
 const header=new TextEncoder().encode(JSON.stringify({scene,velocities:[true,false]}));
 const buffer=new ArrayBuffer(8+header.length+8*values.length),data=new DataView(buffer);
 data.setUint32(0,0x47445331);data.setUint32(4,header.length,true);new Uint8Array(buffer,8,header.length).set(header);
 values.forEach((x,i)=>data.setFloat64(8+header.length+i*8,x,true));return buffer;
}
const values=[7000.123456789123,-0,2, NaN,NaN,NaN, 0,7,0, NaN,NaN,NaN, 1,2,3, 4,5,6];
test('Float64 transport preserves exact vectors, missing samples, mixed tracks and metadata',()=>{
 const decoded=decodePackedScene(packet(values));
 assert.deepEqual(decoded.objects,[{id:'a',positions_km:[[values[0],-0,2],null],velocities_km_s:[[0,7,0],null]}, {id:'b',positions_km:[[1,2,3],[4,5,6]]}]);
 assert.deepEqual(decoded.source,scene.source);
});
test('packed decoder rejects length mismatches and partially invalid vectors',()=>{
 assert.throws(()=>decodePackedScene(packet(values.slice(1))),/payload length/);
 const broken=[...values];broken[3]=1;
 assert.throws(()=>decodePackedScene(packet(broken)),/Invalid packed scene vector/);
});

test('staged and ordinary WASM preparation produce identical mixed-mode frames',async()=>{
 await initializeCompute(readFileSync(new URL('../../web/studio/wasm/godsat_studio_core.wasm',import.meta.url)));
 const packed=decodePackedScene(packet(values)),ordinary=structuredClone(packed);
 const steps=[0,.125,.5,.875,1];
 prepareScene(ordinary);const reference=steps.map(t=>computeFrame(ordinary,t).slice());
 prepareScene(packed);
 steps.forEach((t,i)=>assert.deepEqual(computeFrame(packed,t),reference[i]));
 // Revisiting a consumed window follows the unchanged ordinary packing path.
 prepareScene(packed);steps.forEach((t,i)=>assert.deepEqual(computeFrame(packed,t),reference[i]));
});
