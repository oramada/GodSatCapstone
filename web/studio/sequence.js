// At most two resident windows; obsolete requests are cancelled during scrubbing.
export class WindowSequence {
 constructor(initial,loader){this.meta=initial.sequence;this.loader=loader;this.cache=new Map([[this.meta.index,initial]]);this.pending=new Map();this.current=this.meta.index;this.closed=false;}
 position(global){const step=Math.max(0,Math.min(global,this.meta.total_frames-1));let lo=0,hi=this.meta.windows.length;while(lo<hi){const m=(lo+hi)>>>1;if(this.meta.windows[m].offset<=step)lo=m+1;else hi=m;}const index=Math.max(0,lo-1);return {index,local:step-this.meta.windows[index].offset};}
 async load(index){
  if(this.closed)throw Error('Sequence closed');
  if(this.cache.has(index))return this.cache.get(index);
  if(this.pending.has(index))return this.pending.get(index).promise;
  while(this.pending.size>=2){const [old,request]=this.pending.entries().next().value;request.controller.abort();this.pending.delete(old);}
  const controller=new AbortController();const entry={controller};
  entry.promise=this.loader(this.meta.id,index,controller.signal).then(scene=>{
   if(controller.signal.aborted||this.closed)throw new DOMException('Obsolete window','AbortError');
   if(scene.sequence?.id!==this.meta.id||scene.sequence.index!==index)throw Error('Unexpected sequence window');
   this.cache.set(index,scene);
   while(this.cache.size>2){const old=[...this.cache.keys()].find(k=>k!==index&&k!==this.current);this.cache.delete(old===undefined?this.cache.keys().next().value:old);}
   return scene;
  }).finally(()=>{if(this.pending.get(index)===entry)this.pending.delete(index);});
  this.pending.set(index,entry);return entry.promise;
 }
 async seek(global){const {index,local}=this.position(global);this.current=index;return {scene:await this.load(index),local};}
 prefetch(global){const {index}=this.position(global);if(index+1<this.meta.windows.length)this.load(index+1).catch(()=>{});}
 clear(){this.closed=true;for(const entry of this.pending.values())entry.controller.abort();this.pending.clear();this.cache.clear();}
}
