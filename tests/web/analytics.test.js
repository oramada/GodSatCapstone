import test from 'node:test';
import assert from 'node:assert/strict';
import {geodetic,telemetry,groundTrack,timeStep,screenSamples,csvRows} from '../../web/studio/analytics.js';
test('WGS84 positions retain geodetic altitude and reject undefined origin',()=>{
 assert.equal(geodetic([0,0,0]),null);
 const equator=geodetic([6778.137,0,0]);assert.ok(Math.abs(equator.altitude-400)<1e-9);assert.equal(equator.latitude,0);assert.equal(equator.longitude,0);
 const pole=geodetic([0,0,6756.752314245]);assert.equal(pole.latitude,90);assert.ok(Math.abs(pole.altitude-400)<1e-9);
 const lat=.7,lon=-1.2,h=800,a=6378.137,b=6356.752314245,e2=1-b*b/(a*a),n=a/Math.sqrt(1-e2*Math.sin(lat)**2);
 const check=geodetic([(n+h)*Math.cos(lat)*Math.cos(lon),(n+h)*Math.cos(lat)*Math.sin(lon),(n*(1-e2)+h)*Math.sin(lat)]);
 assert.ok(Math.abs(check.altitude-h)<1e-8);assert.ok(Math.abs(check.latitude-lat*180/Math.PI)<1e-10);
});
const times=['2026-01-01T00:00:00Z','2026-01-01T00:00:10Z','2026-01-01T00:01:00Z'];
test('time navigation uses nonuniform time grids and rejects out-of-window instants',()=>{
 assert.equal(timeStep(times,'2026-01-01T00:00:35Z'),1.5);assert.equal(timeStep(times,times[2]),2);
 assert.equal(timeStep(times,'not a date'),null);assert.equal(timeStep(times,'2025-12-31T23:59:59Z'),null);
});
test('telemetry keeps coordinate frames explicit and does not fill gaps',()=>{
 const object={positions_km:[[7000,0,0],null,[7000,0,0]],velocities_km_s:[[0,7,0],null,[0,7,0]]};
 assert.equal(telemetry({times,frame:'TEME'},object,0).geodetic,null);
 assert.equal(telemetry({times,frame:'ITRS'},object,0).sampleSpeed,7);
 assert.equal(telemetry({times,frame:'ITRS'},object,.5),null);
});
test('ground tracks split at dateline and missing coordinates',()=>{
 const p=lon=>[7000*Math.cos(lon*Math.PI/180),7000*Math.sin(lon*Math.PI/180),0];
 const object={positions_km:[p(170),p(179),p(-179),null,p(0)]};
 assert.deepEqual(groundTrack({frame:'ITRS'},object).map(s=>s.length),[2,1,1]);assert.deepEqual(groundTrack({frame:'GCRS'},object),[]);
});
test('screening preserves missing epochs, sorts minima and does not infer crossings between samples',()=>{
 const positions=new Float64Array([0,0,0, 0,0,0, 4,0,0, 1,0,0, -10,0,0, 10,0,0, NaN,NaN,NaN, NaN,NaN,NaN]);
 const result=screenSamples({positions,focus:positions.slice(0,6),objects:4,frames:2,focusIndex:0,threshold:5});
 assert.deepEqual(result.rows,[{objectIndex:1,distanceKm:1,index:1,validSamples:2}]);assert.equal(result.unavailableObjects,1);assert.equal(result.comparisons,4);
 assert.throws(()=>screenSamples({positions,focus:new Float64Array(1),objects:4,frames:2,threshold:5}),/bounds/);
});
test('twenty-thousand-object scan remains bounded and limits result rows',()=>{
 const positions=new Float64Array(20000*3);for(let j=0;j<20000;j++)positions[j*3]=j;
 const r=screenSamples({positions,focus:positions.slice(0,3),objects:20000,frames:1,focusIndex:0,threshold:50000});
 assert.equal(r.comparisons,19999);assert.equal(r.matchingObjects,19999);assert.equal(r.rows.length,100);assert.equal(r.rows[0].distanceKm,1);
});
test('CSV escapes quotes and mitigates spreadsheet formula strings without changing numeric values',()=>{
 assert.equal(csvRows([['=2+2','a"b',-3,null]]),'"\'=2+2","a""b","-3",""\r\n');
});
