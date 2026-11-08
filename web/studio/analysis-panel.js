import {telemetry,groundTrack,csvRows,timeStep} from './analytics.js';
const $=id=>document.getElementById(id),svgNS='http://www.w3.org/2000/svg';
function text(id,value){if($(id).textContent!==value)$(id).textContent=value;}
function node(tag,value){const n=document.createElement(tag);if(value!==undefined)n.textContent=value;return n;}
const number=(v,d=2)=>Number.isFinite(v)?v.toLocaleString(undefined,{maximumFractionDigits:d,minimumFractionDigits:d}):'—';
export class AnalysisPanel{
 constructor({onFocus,onSeek,onPause}){
  Object.assign(this,{onFocus,onSeek,onPause,scene:null,focus:null,worker:null,result:null,lastUpdate:0,storageKey:null,watched:[],generation:0});
  $('watch-add').onclick=()=>this.addWatch();$('screen-run').onclick=()=>this.screen();$('screen-cancel').onclick=()=>this.cancel();
  $('screen-export').onclick=()=>this.exportScreen();$('telemetry-export').onclick=()=>this.exportTelemetry();
  $('time-jump').onclick=()=>this.jump();$('step-back').onclick=()=>this.step(-1);$('step-forward').onclick=()=>this.step(1);
  $('time-input').onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();this.jump();}};
  $('screen-threshold').onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();this.screen();}};
  $('watch-clear').onclick=()=>{this.watched=[];this.persist();this.renderWatch();};
  $('screen-threshold').oninput=()=>{this.cancel();this.result=null;$('screen-export').disabled=true;$('screen-results').replaceChildren();text('screen-status','Threshold changed. Run screening to calculate new results.');};
 }
 setScene(scene,id){
  this.cancel();this.scene=scene;this.objects=new Map(scene.objects.map(o=>[o.id,o]));this.focus=id;this.result=null;this.lastUpdate=0;
  this.storageKey='godsat.watch.v1:'+String(scene.sequence?.id||scene.source.artifact_id||scene.title);
  try{const saved=JSON.parse(localStorage.getItem(this.storageKey)||'[]');this.watched=Array.isArray(saved)?saved.filter(x=>typeof x==='string').slice(0,12):[];}catch{this.watched=[];}
  this.drawTrack();this.renderWatch();$('screen-results').replaceChildren();$('screen-export').disabled=true;
  text('screen-status',`Ready: ${scene.objects.length.toLocaleString()} objects × ${scene.times.length} saved epochs. Current window only.`);
  $('time-input').value='';$('time-input').placeholder=scene.times[0];text('time-status',`${scene.times[0]} to ${scene.times.at(-1)} · current window`);
 }
 setFocus(id){if(this.focus===id)return;this.cancel();this.focus=id;this.result=null;$('screen-export').disabled=true;$('screen-results').replaceChildren();text('screen-status','Focus changed. Run screening for this object.');this.drawTrack();this.renderWatch();this.lastUpdate=0;}
 update(time,force=false){
  if(!this.scene)return;this.time=time;const now=performance.now();if(!force&&now-this.lastUpdate<500)return;this.lastUpdate=now;
  const t=telemetry(this.scene,this.objects.get(this.focus),time),geo=t?.geodetic;
  text('telemetry-radius',number(t?.radius)+' km');text('telemetry-altitude',number(geo?.altitude)+' km');text('telemetry-latitude',number(geo?.latitude,3)+'°');text('telemetry-longitude',number(geo?.longitude,3)+'°');text('telemetry-speed',number(t?.sampleSpeed,4)+' km/s');
  text('telemetry-frame',`${this.scene.frame} · speed at preceding saved epoch, in this frame${this.scene.frame==='ITRS'?' (Earth-fixed, not inertial)':''}. Geodetic values require ITRS.`);
  const marker=$('track-current');if(geo){marker.setAttribute('cx',(geo.longitude+180)*2);marker.setAttribute('cy',(90-geo.latitude)*2);marker.style.display='';}else marker.style.display='none';
  for(const row of $('watch-list').children){if(!row.dataset.id)continue;const other=telemetry(this.scene,this.objects.get(row.dataset.id),time);const distance=t&&other?Math.hypot(...t.position.map((x,i)=>x-other.position[i])):null;row.querySelector('.watch-distance').textContent=distance===null?'Position unavailable':`${number(distance)} km from focus`;}
 }
 drawTrack(){
  const layer=$('track-lines');layer.replaceChildren();const segments=groundTrack(this.scene,this.objects.get(this.focus));
  for(const points of segments){const p=document.createElementNS(svgNS,'polyline');p.setAttribute('points',points.map(g=>`${(g.longitude+180)*2},${(90-g.latitude)*2}`).join(' '));layer.append(p);}
  text('track-caption',this.scene.frame==='ITRS'?'WGS84 sub-satellite points at saved epochs. Gaps and dateline crossings are separated; current window only.':'Ground track unavailable: this scene is not in ITRS.');
 }
 addWatch(){if(!this.focus)return;if(this.watched.includes(this.focus)){text('watch-status','This object is already watched.');return;}if(this.watched.length>=12){text('watch-status','Watchlist limit reached: remove an object before adding another.');return;}this.watched.push(this.focus);this.persist();this.renderWatch();}
 persist(){try{localStorage.setItem(this.storageKey,JSON.stringify(this.watched));text('watch-status',`${this.watched.length} watched objects, saved in this browser for this source.`);}catch{text('watch-status','Watchlist is available this session; browser storage is unavailable.');}}
 renderWatch(){
  $('watch-list').replaceChildren(...this.watched.map(id=>{const row=node('li');row.dataset.id=id;const o=this.objects.get(id),select=node('button',o?.name||id);select.disabled=!o;select.onclick=()=>this.onFocus(id);const d=node('span',o?'—':'Not in this window');d.className='watch-distance';const remove=node('button','Remove');remove.setAttribute('aria-label',`Remove ${o?.name||id} from watchlist`);remove.onclick=()=>{this.watched=this.watched.filter(x=>x!==id);this.persist();this.renderWatch();};row.append(select,d,remove);return row;}));
  if(!this.watched.length)$('watch-list').append(node('li','No watched objects yet. Add the focused satellite.'));this.lastUpdate=0;
 }
 cancel(){this.generation++;if(this.busy)text('screen-status','Screening cancelled.');this.busy=false;if(this.worker){this.worker.terminate();this.worker=null;}$('screen-run').disabled=false;$('screen-cancel').disabled=true;}
 async screen(){
  if(!this.scene)return;this.cancel();const threshold=Number($('screen-threshold').value);
  if($('screen-threshold').value.trim()===''||!Number.isFinite(threshold)||threshold<0){text('screen-status','Enter a nonnegative separation in km.');return;}
  const scene=this.scene,id=this.focus,focusIndex=scene.objects.findIndex(o=>o.id===id);if(focusIndex<0)return;
  this.result=null;this.busy=true;$('screen-export').disabled=true;$('screen-results').replaceChildren();this.onPause();$('screen-run').disabled=true;$('screen-cancel').disabled=false;text('screen-status','Preparing position samples…');
  const generation=this.generation,frames=scene.times.length,positions=new Float64Array(scene.objects.length*frames*3).fill(NaN);
  // Yield while packing large catalogs; changed source/focus cancels obsolete work.
  for(let j=0;j<scene.objects.length;j++){for(let k=0;k<frames;k++){const p=scene.objects[j].positions_km[k];if(p)positions.set(p,(j*frames+k)*3);}if(j%512===0){await new Promise(requestAnimationFrame);if(generation!==this.generation)return;}}
  const focus=positions.slice(focusIndex*frames*3,(focusIndex+1)*frames*3);
  try{const worker=new Worker(new URL('./screen-worker.js',import.meta.url),{type:'module'});this.worker=worker;
   worker.onerror=()=>{if(generation!==this.generation)return;this.cancel();text('screen-status','Screening worker failed. Reload Studio and retry.');};
   worker.onmessage=({data})=>{if(generation!==this.generation)return;if(data.progress!==undefined){text('screen-status',`Screening saved epochs… ${Math.round(data.progress*100)}%`);return;}this.cancel();if(data.error){text('screen-status',data.error);return;}this.result={...data.result,threshold,focusId:id,scene};this.renderResults();};
   worker.postMessage({positions,focus,objects:scene.objects.length,frames,focusIndex,threshold},[positions.buffer,focus.buffer]);
  }catch(error){this.cancel();text('screen-status',error.message);}
 }
 renderResults(){
  const r=this.result;text('screen-status',`${r.matchingObjects} objects within ${number(r.threshold)} km at a saved epoch; showing ${r.rows.length}. ${r.comparisons.toLocaleString()} comparisons, ${r.unavailableObjects} objects with no shared valid epoch.`);
  const table=node('table'),head=node('tr');for(const s of ['Object','Minimum sampled separation','UTC epoch','Valid epochs','Inspect'])head.append(node('th',s));table.append(head);
  for(const hit of r.rows){const o=r.scene.objects[hit.objectIndex],row=node('tr');for(const value of [o.name,number(hit.distanceKm,3)+' km',r.scene.times[hit.index],String(hit.validSamples)])row.append(node('td',value));const cell=node('td'),button=node('button','Go to epoch');button.onclick=()=>this.onSeek(hit.index);cell.append(button);row.append(cell);table.append(row);}
  $('screen-results').replaceChildren(table);$('screen-export').disabled=false;
 }
 download(name,rows){const url=URL.createObjectURL(new Blob([csvRows(rows)],{type:'text/csv;charset=utf-8'}));const a=node('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
 exportScreen(){const r=this.result;if(!r)return;this.download('sampled-approaches.csv',[['focus_id','other_id','utc','sampled_distance_km','valid_epochs','frame','source_kind','scope'],...r.rows.map(h=>[r.focusId,r.scene.objects[h.objectIndex].id,r.scene.times[h.index],h.distanceKm,h.validSamples,r.scene.frame,r.scene.source.kind,'saved epochs only; current window; not collision prediction'])]);}
 exportTelemetry(){if(!this.scene)return;const scene=this.scene,object=this.objects.get(this.focus);if(!object)return;this.download('satellite-telemetry.csv',[['object_id','utc','frame','x_km','y_km','z_km','wgs84_lat_deg','wgs84_lon_deg','wgs84_alt_km','frame_speed_km_s','source_kind'],...scene.times.map((t,k)=>{const v=telemetry(scene,object,k);return [object.id,t,scene.frame,...(v?.position||['','','']),v?.geodetic?.latitude,v?.geodetic?.longitude,v?.geodetic?.altitude,v?.sampleSpeed,scene.source.kind];})]);}
 jump(){if(!this.scene)return;const raw=$('time-input').value.trim();if(!/(Z|[+-]\d\d:\d\d)$/i.test(raw)){text('time-status','Include a UTC offset, for example 2026-11-08T18:56:00Z.');return;}const step=timeStep(this.scene.times,raw);if(step===null){text('time-status','Enter a valid instant inside the current window.');return;}this.onPause();this.onSeek(step);text('time-status',`Jumped to ${new Date(Date.parse(raw)).toISOString()}`);}
 step(direction){if(!this.scene)return;this.onPause();this.onSeek(Math.max(0,Math.min(this.scene.times.length-1,direction>0?Math.floor(this.time||0)+1:Math.ceil(this.time||0)-1)));}
}
