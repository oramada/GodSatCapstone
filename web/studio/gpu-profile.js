// Opt-in diagnostic. WebGL timings exclude browser compositing and presentation.
export class GpuProfile {
 constructor(canvas){
  this.gl=canvas.getContext('webgl2');
  this.ext=this.gl?.getExtension('EXT_disjoint_timer_query_webgl2');
  this.pending=null;this.samples=[];
 }
 begin(){
  const {gl,ext}=this;if(!ext||gl.isContextLost())return null;
  if(this.pending){
   if(!gl.getQueryParameter(this.pending,gl.QUERY_RESULT_AVAILABLE))return null;
   if(!gl.getParameter(ext.GPU_DISJOINT_EXT))this.samples.push(gl.getQueryParameter(this.pending,gl.QUERY_RESULT)/1e6);
   gl.deleteQuery(this.pending);this.pending=null;
  }
  const query=gl.createQuery();if(query)gl.beginQuery(ext.TIME_ELAPSED_EXT,query);return query;
 }
 end(query,drew){
  if(!query)return;
  this.gl.endQuery(this.ext.TIME_ELAPSED_EXT);
  if(drew)this.pending=query;else this.gl.deleteQuery(query);
 }
 readout(){
  if(!this.ext)return 'GPU timing unavailable';
  const samples=this.samples.splice(0).sort((a,b)=>a-b);
  if(!samples.length)return 'GPU timing: no completed draws';
  return `GPU p50 ${samples[Math.floor(samples.length*.5)].toFixed(1)} / p95 ${samples[Math.floor(samples.length*.95)].toFixed(1)} ms (${samples.length} draws)`;
 }
 destroy(){if(this.pending)this.gl.deleteQuery(this.pending);this.pending=null;}
}
