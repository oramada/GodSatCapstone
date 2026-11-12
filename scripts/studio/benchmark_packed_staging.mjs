// Compare decoding and WASM preparation on the same packed window bytes.
import {readFileSync} from 'node:fs';
import assert from 'node:assert/strict';
import {decodePackedScene} from '../../web/studio/packed-scene.js';
import {initializeCompute,prepareScene,computeFrame} from '../../web/studio/compute.js';
const bytes=readFileSync(process.argv[2]),buffer=bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength);
await initializeCompute(readFileSync(new URL('../../web/studio/wasm/godsat_studio_core.wasm',import.meta.url)));
const decode=[],pack=[];let scene;
for(let i=0;i<15;i++){
 let t=performance.now();scene=decodePackedScene(buffer);const d=performance.now()-t;
 t=performance.now();prepareScene(scene);const p=performance.now()-t;
 if(i>=3){decode.push(d);pack.push(p);}
}
const steps=Array.from({length:scene.times.length*2-1},(_,i)=>i/2);
const fresh=decodePackedScene(buffer);prepareScene(fresh);const stagedFrames=steps.map(t=>computeFrame(fresh,t).slice());
const ordinary=structuredClone(fresh);prepareScene(ordinary);
steps.forEach((t,i)=>assert.deepStrictEqual(computeFrame(ordinary,t),stagedFrames[i]));
const output=stagedFrames[1],median=rows=>rows.sort((a,b)=>a-b)[Math.floor(rows.length/2)];
console.log(JSON.stringify({objects:scene.objects.length,epochs:scene.times.length,decodeMedianMs:median(decode),prepareMedianMs:median(pack),equivalentFrames:steps.length,frameChecksum:output.reduce((n,x)=>Number.isFinite(x)?n+x:n,0)}));
