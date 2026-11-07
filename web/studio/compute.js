// Rust/WASM owns packed interpolation and custody state. Rendering remains GPU-side.
// The reference JavaScript path remains usable when WebAssembly is unavailable.
const states=['unavailable','unknown','observed','stale','lost'];
let wasm=null,active=null,serial=0;
export async function initializeCompute(binary){
 try{const result=await WebAssembly.instantiate(binary||await (await fetch('/studio/wasm/godsat_studio_core.wasm')).arrayBuffer(),{});wasm=result.instance.exports;return true;}catch{return false;}
}
export function releaseScene(){
 if(!active||!wasm)return;
 const {positions,times,observations,history,output,frames,objects}=active;
 wasm.free_f64(positions,frames*objects*3);wasm.free_f64(times,frames);wasm.free_u8(observations,frames*objects);wasm.free_i32(history,frames*objects);wasm.free_f64(output,objects*6);active=null;
}
export function prepareScene(scene){
 releaseScene();if(!wasm)return false;
 const frames=scene.times.length,objects=scene.objects.length;
 if(frames<1||frames>1200||objects>2000)throw Error('Scene exceeds WASM bounds');
 const positions=wasm.alloc_f64(frames*objects*3),times=wasm.alloc_f64(frames),observations=wasm.alloc_u8(frames*objects),history=wasm.alloc_i32(frames*objects),output=wasm.alloc_f64(objects*6);
 const p=new Float64Array(wasm.memory.buffer,positions,frames*objects*3),t=new Float64Array(wasm.memory.buffer,times,frames),o=new Uint8Array(wasm.memory.buffer,observations,frames*objects);
 const indices=new Map(scene.objects.map((object,j)=>[object.id,j])),tracks=new Map(scene.objects.map((object,j)=>[object.positions_km,j]));
 for(let k=0;k<frames;k++){t[k]=Date.parse(scene.times[k]);const seen=scene.observations?.[k];for(let j=0;j<objects;j++){const point=scene.objects[j].positions_km[k];for(let a=0;a<3;a++)p[(k*objects+j)*3+a]=point?.[a]??NaN;o[k*objects+j]=seen?1:0;}for(const id of seen?.detected||[]){const j=indices.get(id);if(j!==undefined)o[k*objects+j]=2;}}
 wasm.prepare(observations,history,frames,objects);active={scene,frames,objects,positions,times,observations,history,output,indices,tracks,step:NaN,serial:++serial};return true;
}
export function computeFrame(scene,step){if(!active||active.scene!==scene)return null;if(active.step!==step){wasm.evaluate(active.positions,active.times,active.observations,active.history,active.frames,active.objects,step,scene.custody_seconds,active.output);active.step=step;}return new Float64Array(wasm.memory.buffer,active.output,active.objects*6);}
export function computedState(scene,id,step){if(!active||active.scene!==scene||active.step!==step)return null;const index=active.indices.get(id);if(index===undefined)return null;const v=new Float64Array(wasm.memory.buffer,active.output+index*48,6);return {state:states[v[3]],last:v[4],age:Number.isFinite(v[5])?v[5]:null};}
export function computedPosition(scene,id,step){if(!active||active.scene!==scene||active.step!==step)return undefined;const index=active.indices.get(id);if(index===undefined)return undefined;const v=new Float64Array(wasm.memory.buffer,active.output+index*48,3);return Number.isFinite(v[0])?[v[0],v[1],v[2]]:null;}
export function computedTrack(track,step){if(!active||active.step!==step)return undefined;const index=active.tracks.get(track);return index===undefined?undefined:computedPosition(active.scene,active.scene.objects[index].id,step);}
export function computeBackend(){return wasm?'Rust · WebAssembly':'JavaScript fallback';}
