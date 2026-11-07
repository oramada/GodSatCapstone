import test from 'node:test';
import assert from 'node:assert/strict';
import {trackState,sample} from '../../web/studio/model.js';
const scene={times:Array.from({length:7},(_,i)=>new Date(Date.UTC(2026,0,1,0,i)).toISOString()),custody_seconds:180,objects:[{id:'1',positions_km:Array(7).fill([7000,0,0])}],observations:Array.from({length:7},(_,i)=>({detected:i===0||i===6?['1']:[]}))};
test('custody retains boundary, expires after 180 seconds, and reacquires',()=>{assert.equal(trackState(scene,'1',0).state,'observed');assert.equal(trackState(scene,'1',3).state,'stale');assert.equal(trackState(scene,'1',4).state,'lost');assert.equal(trackState(scene,'1',6).state,'observed');});
test('geometry never implies detection',()=>assert.equal(trackState({...scene,observations:null},'1',2).state,'unknown'));
test('missing state and absent initial sightings are explicit',()=>{assert.equal(trackState({...scene,objects:[{id:'1',positions_km:[null]}]},'1',0).state,'unavailable');assert.equal(trackState({...scene,observations:[{detected:[]}]},'1',0).state,'lost');});
test('interpolation does not bridge missing source samples',()=>assert.equal(sample([[7000,0,0],null,[7100,0,0]],.5),null));
