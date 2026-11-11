import test from 'node:test';
import assert from 'node:assert/strict';
import {trackState,trackStates,sample} from '../../web/studio/model.js';
const scene={times:Array.from({length:7},(_,i)=>new Date(Date.UTC(2026,0,1,0,i)).toISOString()),custody_seconds:180,objects:[{id:'1',positions_km:Array(7).fill([7000,0,0])}],observations:Array.from({length:7},(_,i)=>({detected:i===0||i===6?['1']:[]}))};
test('custody retains boundary, expires after 180 seconds, and reacquires',()=>{assert.equal(trackState(scene,'1',0).state,'observed');assert.equal(trackState(scene,'1',3).state,'stale');assert.equal(trackState(scene,'1',4).state,'lost');assert.equal(trackState(scene,'1',6).state,'observed');});
test('geometry never implies detection',()=>assert.equal(trackState({...scene,observations:null},'1',2).state,'unknown'));
test('missing state and absent initial sightings are explicit',()=>{assert.equal(trackState({...scene,objects:[{id:'1',positions_km:[null]}]},'1',0).state,'unavailable');assert.equal(trackState({...scene,observations:[{detected:[]}]},'1',0).state,'lost');});
test('interpolation does not bridge missing source samples',()=>assert.equal(sample([[7000,0,0],null,[7100,0,0]],.5),null));
test('per-epoch states in one pass match trackState at every step',()=>{
 let seed=7;const rand=()=>(seed=(seed*1103515245+12345)%2147483648)/2147483648;
 const frames=40,ids=['a','b','c','d'];
 const big={times:Array.from({length:frames},(_,i)=>new Date(Date.UTC(2026,0,1,0,i)).toISOString()),custody_seconds:150,
  objects:ids.map(id=>({id,positions_km:Array.from({length:frames},()=>rand()<.1?null:[7000,0,0])})),
  observations:Array.from({length:frames},()=>rand()<.15?null:{detected:ids.filter(()=>rand()<.3)})};
 for(const id of [...ids,'missing']){const all=trackStates(big,id);assert.equal(all.length,frames);all.forEach((s,i)=>assert.deepEqual(s,trackState(big,id,i),`${id}@${i}`));}
 assert.ok(trackStates(big,'a').some(s=>s.state==='stale')&&trackStates(big,'a').some(s=>s.state==='observed'));
 assert.deepEqual(trackStates({...big,observations:null},'a').map(s=>s.state).filter(s=>s!=='unavailable'),Array(trackStates(big,'a').filter(s=>s.state!=='unavailable').length).fill('unknown'));
});
test('the id lookup picks the first object with an id and follows a replaced object list',()=>{
 const dup={...scene,objects:[{id:'1',positions_km:[null,null,null,null,null,null,null]},{id:'1',positions_km:Array(7).fill([7000,0,0])}]};
 assert.equal(trackState(dup,'1',0).state,'unavailable');
 dup.objects=[{id:'1',positions_km:Array(7).fill([7000,0,0])}];
 assert.equal(trackState(dup,'1',0).state,'observed');
});
