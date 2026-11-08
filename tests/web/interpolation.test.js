import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {interpolatePosition} from '../../web/studio/interpolation.js';
import {initializeCompute,prepareScene,computeFrame,computedPosition,releaseScene} from '../../web/studio/compute.js';
const binary=await readFile(new URL('../../web/studio/wasm/godsat_studio_core.wasm',import.meta.url));
const times=['2026-01-01T00:00:00Z','2026-01-01T00:00:02Z','2026-01-01T00:00:05Z'];
const cubic={id:'cubic',positions_km:[[0,0,1],[8,4,1],[125,10,1]],velocities_km_s:[[0,2,0],[12,2,0],[75,2,0]]};
test('nonuniform cubic interpolation uses seconds and agrees across JS and WASM',async()=>{
 assert.equal(await initializeCompute(binary),true);
 const scene={times,objects:[cubic,{id:'legacy',positions_km:cubic.positions_km}],observations:null,custody_seconds:180};
 prepareScene(scene);
 for(const step of [0,.1,.25,.5,.9,1,1.1,1.5,1.9,2]){
  const seconds=step<=1?step*2:2+(step-1)*3,expected=[seconds**3,seconds*2,1];
  computeFrame(scene,step);
  for(const actual of [interpolatePosition(cubic,times,step),computedPosition(scene,'cubic',step)])expected.forEach((v,k)=>assert.ok(Math.abs(actual[k]-v)<1e-10));
  assert.deepEqual(computedPosition(scene,'legacy',step),interpolatePosition(scene.objects[1],times,step));
 }
 releaseScene();
});
test('missing velocities cannot silently downgrade a Hermite interval to linear',()=>{
 const object={...cubic,velocities_km_s:[cubic.velocities_km_s[0],null,cubic.velocities_km_s[2]]};
 const scene={times,objects:[object],observations:null,custody_seconds:180};prepareScene(scene);
 for(const step of [.5,1.5]){computeFrame(scene,step);assert.equal(computedPosition(scene,'cubic',step),null);assert.equal(interpolatePosition(object,times,step),null);}
 computeFrame(scene,1);assert.deepEqual(computedPosition(scene,'cubic',1),[8,4,1]);releaseScene();
});
