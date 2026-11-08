import test from 'node:test';
import assert from 'node:assert/strict';
import {attitudeAt,displayAttitude,attitudeCaption} from '../../web/studio/attitude.js';
const object={attitude:{frame:'ITRS',source:{kind:'observed',reference:'Fixture telemetry'},body_axes:{x:'panel axis',y:'bus top',z:'completes right-handed triad'},quaternions:[[0,0,0,1],[0,0,1,0],null,[0,0,0,-1]]}};
const close=(a,b)=>a.forEach((x,k)=>assert.ok(Math.abs(x-b[k])<1e-12));
function rotate(q,v){const [x,y,z,w]=q;const u=[x,y,z],dot=u.reduce((s,a,i)=>s+a*v[i],0),norm=u.reduce((s,a)=>s+a*a,0),cross=[y*v[2]-z*v[1],z*v[0]-x*v[2],x*v[1]-y*v[0]];return v.map((a,i)=>2*dot*u[i]+(w*w-norm)*a+2*w*cross[i]);}
test('Hamilton active rotations and display basis preserve handedness',()=>{
 close(rotate(displayAttitude([0,0,0,1]),[1,0,0]),[1,0,0]);
 close(rotate(displayAttitude([0,0,0,1]),[0,1,0]),[0,0,-1]);
 close(rotate(displayAttitude([0,0,0,1]),[0,0,1]),[0,1,0]);
 close(rotate(displayAttitude(attitudeAt(object,.5)),[1,0,0]),[0,0,-1]);
});
test('shortest-path SLERP is unit length, sign invariant and leaves gaps',()=>{
 close(attitudeAt(object,.5),[0,0,Math.SQRT1_2,Math.SQRT1_2]);
 const same={attitude:{quaternions:[[0,0,0,1],[0,0,0,-1]]}};
 close(attitudeAt(same,.5),[0,0,0,1]);
 for(const t of [-1,1.1,2,2.5,4,NaN])assert.equal(attitudeAt(object,t),null);
 assert.deepEqual(attitudeAt(object,3),[0,0,0,-1]);
 assert.match(attitudeCaption(object,2),/unavailable/);
 assert.match(attitudeCaption(object,.5),/OBSERVED.*intermediate motion is modeled/);
 assert.match(attitudeCaption({},0),/generic illustrations/);
});
