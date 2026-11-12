import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {initializeCompute,prepareScene,computeFrame} from '../../web/studio/compute.js';

class Cartesian3 {constructor(x=0,y=0,z=0){Object.assign(this,{x,y,z});}}
globalThis.window={Cesium:{Cartesian3,Color:{fromBytes:(...rgba)=>rgba},JulianDate:class{
 static secondsDifference(a,b){return a-b;}
 static addSeconds(a,b){return a+b;}
}}};
const {CesiumObservatory}=await import('../../web/studio/cesium-renderer.js');
const layers={atmosphere:true,celestial:false,clouds:'clear',ionosphere:false,environment:'none',trails:false,ghosts:false};
const data={frame:'ITRS',custody_seconds:180,observations:null,times:['2026-11-08T00:00:00Z','2026-11-08T00:00:30Z'],objects:[
 {id:'a',kind:'satellite',positions_km:[[7000,0,0],[7000,30,0]]},
 {id:'b',kind:'satellite',positions_km:[[7100,0,0],null]},
]};
const counters={requests:0,widget:0,detail:0};
function make(){
 return Object.assign(Object.create(CesiumObservatory.prototype),{data,items:data.objects.map((object,index)=>({object,index,point:{set position(p){this.saved={...p};}},lines:[]})),dates:[0,30],focus:'a',mode:'system',colors:{unknown:[1,2,3],unavailable:[1,2,3]},scene:{skyAtmosphere:{},globe:{},sun:{},moon:{},requestRender(){counters.requests++;}},widget:{clock:{},render(){counters.widget++;}},clouds:{appearance:{material:{uniforms:{color:{}}}}},ionosphere:{},environment:{update:()=>''},focusLabel:{},radioLine:{},ghostPoint:{},detail:{dirty:false,update(){counters.detail++;this.dirty=false;}},generation:1});
}

test('paused scene skips unchanged work while widget input and resize invalidations continue',async()=>{
 await initializeCompute(readFileSync(new URL('../../web/studio/wasm/godsat_studio_core.wasm',import.meta.url)));
 prepareScene(data);const v=make();v.update(0,layers);
 assert.deepEqual(v.items.map(x=>x.point.saved.x),[7000000,7100000]);
 const before={...counters};v.update(0,layers);
 assert.deepEqual(counters,{...before,widget:before.widget+1});
 v.detail.dirty=true;v.update(0,layers);
 assert.equal(counters.detail,before.detail+1);assert.equal(counters.requests,before.requests);
 v.update(.5,layers);assert.equal(v.items[0].point.saved.y,15000);assert.equal(v.items[1].point.show,false);
 v.focus='b';v.update(0,layers);assert.equal(v.items[1].point.show,true);assert.equal(v.items[1].point.pixelSize,8);
 v.mode='single';v.update(0,layers);assert.equal(v.items[0].point.show,false);
 v.update(0,{...layers,atmosphere:false});assert.equal(v.scene.skyAtmosphere.show,false);
});

test('same-layout WASM scene replacement overwrites observations and missing coordinates',async()=>{
 await initializeCompute(readFileSync(new URL('../../web/studio/wasm/godsat_studio_core.wasm',import.meta.url)));
 const seen={...data,observations:[{detected:['a']},null]};prepareScene(seen);
 const first=computeFrame(seen,0);assert.equal(first[3],2);
 const next={...data,objects:[{...data.objects[0],id:'new-a',positions_km:[null,[7500,0,0]]},data.objects[1]]};
 prepareScene(next);const current=computeFrame(next,0);
 assert.equal(current.byteOffset,first.byteOffset);
 assert.equal(computeFrame(seen,0),null);
 assert.ok(Number.isNaN(current[0]));assert.equal(current[3],0);
 assert.equal(computeFrame(next,1)[0],7500);assert.equal(computeFrame(next,1)[3],1);
});

test('sequence window retains picking primitives but invalidates its old state',()=>{
 const v=make(),p=v.items[0].point;v.ready=true;v.lastFrame={step:0};v.radioKey='old window';
 v.data={...data,sequence:{id:'one',index:0}};
 v.stationPoints={removeAll(){}};v.environment={setScene(){}};v.setFocus=id=>{v.focus=id;};
 window.Cesium.JulianDate.fromIso8601=Date.parse;
 const next={...data,sequence:{id:'one',index:1},objects:[{...data.objects[0],positions_km:[[8000,0,0],null]},data.objects[1]]};
 v.setScene(next,'a',true);
 assert.equal(v.items[0].point,p);assert.equal(v.items[0].object,next.objects[0]);assert.equal(v.lastFrame,null);assert.equal(v.radioKey,null);
 assert.equal(v.generation,1);assert.equal(v.widget.clock.currentTime,Date.parse(data.times[0]));
});
