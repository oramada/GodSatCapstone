import test from 'node:test';
import assert from 'node:assert/strict';
import {WindowSequence} from '../../web/studio/sequence.js';
const meta={id:'fixture',index:0,offset:0,total_frames:19,windows:Array.from({length:6},(_,i)=>({offset:i*3,frames:4}))};
const scene=i=>({objects:[],sequence:{...meta,index:i,offset:i*3}});
test('forward and backward seeks share one boundary frame and keep two cached windows',async()=>{
 const calls=[];const seq=new WindowSequence(scene(0),async(_,i)=>{calls.push(i);return scene(i);});
 for(const step of [0,2.9,3,8,15,18,4,0]){const result=await seq.seek(step);assert.equal(result.local,step-result.scene.sequence.offset);assert.ok(seq.cache.size<=2);}
 assert.equal(seq.position(3).index,1);assert.equal(seq.position(999).local,3);assert.equal(seq.position(-1).index,0);
 seq.clear();assert.equal(seq.cache.size,0);assert.ok(calls.length>0);
});
test('out-of-order requests are bounded and obsolete responses cannot repopulate closed cache',async()=>{
 const releases=[];const seq=new WindowSequence(scene(0),(_,i)=>new Promise(resolve=>releases.push(()=>resolve(scene(i)))));
 const a=seq.load(1).catch(e=>e.name),b=seq.load(2).catch(e=>e.name),c=seq.load(3).catch(e=>e.name);
 assert.equal(seq.pending.size,2);seq.clear();for(const release of releases)release();
 assert.deepEqual(await Promise.all([a,b,c]),['AbortError','AbortError','AbortError']);assert.equal(seq.cache.size,0);
});
test('window failures surface and can be retried without changing cache',async()=>{
 let failed=true;const seq=new WindowSequence(scene(0),async(_,i)=>{if(failed)throw Error('missing');return scene(i);});
 await assert.rejects(()=>seq.seek(3),/missing/);assert.equal(seq.cache.size,1);failed=false;
 assert.equal((await seq.seek(3)).scene.sequence.index,1);
});
