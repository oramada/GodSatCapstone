import test from 'node:test';
import assert from 'node:assert/strict';
import {buildExperiment} from '../../web/studio/experiment-config.js';
const values={epoch:'2026-11-08T18:55:00Z',duration:10,step:10,cadence:30,count:100,altitude:400,inclination:53,gravity:'zonal',drag:false,thirdBodies:true,srp:true,relativity:true,applyProperties:true,mass:120,dragArea:1.2,cd:2.2,radiationArea:1.2,cr:1.3};
test('generated constellation preserves circular energy and labels hypothetical inputs',()=>{
 const c=buildExperiment(values);assert.equal(c.objects.length,100);assert.equal(c.source.kind,'illustrative');assert.equal(c.forces.j2,false);
 for(const o of c.objects){const r=Math.hypot(...o.position_gcrs_km),v=Math.hypot(...o.velocity_gcrs_km_s);assert.ok(Math.abs(v*v-c.gravity_model.mu_km3_s2/r)<1e-12);assert.equal(o.mass_kg,120);}
 assert.throws(()=>buildExperiment({...values,count:2001}),/2,000/);
});
test('saved state mode retains object data unless spacecraft override is explicit',()=>{
 const original=buildExperiment(values),saved=structuredClone(original);saved.objects[0].mass_kg=400;
 const preserved=buildExperiment({...values,gravity:'saved',applyProperties:false},saved);
 assert.deepEqual(preserved.objects,saved.objects);assert.deepEqual(preserved.gravity_model,saved.gravity_model);
 const overridden=buildExperiment({...values,gravity:'saved'},saved);assert.equal(overridden.objects[0].mass_kg,120);assert.equal(saved.objects[0].mass_kg,400);
});
