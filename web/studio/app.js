import {CesiumObservatory} from './cesium-renderer.js';
import {trackState} from './model.js';
import {initializeCompute,prepareScene,computeFrame,computeBackend} from './compute.js';
import {WindowSequence} from './sequence.js';
import {WorkspaceUI} from './workspace-ui.js';
import {sceneCandidate} from './workspace.js';
import {tablePlot} from './charts.js';
import {ExperimentPanel} from './experiment-panel.js';
import {AnalysisPanel} from './analysis-panel.js';
const $=id=>document.getElementById(id);
function put(id,value){const element=$(id),text=String(value);if(element.textContent!==text)element.textContent=text;}
let scene=null, mode='system', time=0, playing=false, previous=0, artifacts=[],selectedArtifact=null,sceneRequest=0,inspectRequest=0,currentModified=null, activeSource='demo',sceneLoading=false;
let sequence=null,windowLoading=false,windowRequest=0;
let linkResult=null,linkController=null,linkSerial=0,linkMessage='',lastLinkRow=null,lastLinkMessage=null,lastLinkResult=null;
const globalTime=()=>time+(scene?.sequence?.offset||0);
const layers=()=>Object.fromEntries(['atmosphere','ionosphere','celestial','trails','ghosts'].map(k=>[k,$(k).checked]).concat([['clouds',$('clouds').value],['environment',$('environment').value]]));
function notify(message){$('toast').textContent=message;$('toast').hidden=false;clearTimeout(notify.timer);notify.timer=setTimeout(()=>$('toast').hidden=true,6500);}
async function api(url,signal){const r=await fetch(url,{cache:'no-store',signal});const body=await r.json();if(!r.ok)throw Error(body.error||`Request failed (${r.status})`);return body;}
let view;
function initializeView(){
 try{view=new CesiumObservatory($('cesium-globe'),$('detail'));}
 catch(error){view=null;notify('Renderer unavailable: '+error.message);$('loading').textContent='3D rendering is unavailable. Check that WebGL is enabled and reload Studio.';$('loading').hidden=false;}
}
document.addEventListener('renderererror',e=>notify(e.detail));
document.addEventListener('objectselected',e=>{renderFocusOptions(e.detail);changeFocus();$('selection-chip').hidden=false;});
let platform,analysis;
function openSpatial(id){if(![...$('source').options].some(o=>o.value===id))$('source').add(new Option(artifacts.find(a=>a.id===id)?.path||id,id));$('source').value=id;platform.reveal('visualization');loadScene(id);}

let focusObjects=[];
function focalObjects(){return focusObjects;}
function renderFocusOptions(selected=$('focus').value){const query=$('focus-search').value.trim().toLowerCase(),matches=focusObjects.filter(o=>`${o.name} ${o.id}`.toLowerCase().includes(query)),visible=matches.slice(0,200),current=focusObjects.find(o=>o.id===selected);if(current&&!visible.some(o=>o.id===selected))visible.unshift(current);$('focus').replaceChildren(...visible.map(o=>new Option(o.name,o.id)));if(current)$('focus').value=selected;put('focus-count',`${matches.length.toLocaleString()} matches · ${visible.length} listed`);}
function changeFocus(){if(view)view.selectedByUser=true;$('selection-chip').hidden=false;renderFocusOptions();analysis?.setFocus($('focus').value);view?.setFocus($('focus').value);drawEvents();updateText();refreshLinks();}
async function loadScene(value='demo',preserve=false){
 const before=globalTime();const request=++sceneRequest;++windowRequest;windowLoading=false;sceneLoading=true;$('loading').hidden=false;$('loading').textContent='Preparing scene…';
 try{const next=await api(value==='demo'?`/api/studio/scene?demo=${mode}`:`/api/studio/scene?id=${encodeURIComponent(value)}`);if(request!==sceneRequest)return;
  sequence?.clear();sequence=next.sequence?new WindowSequence(next,(id,index,signal)=>api(`/api/studio/window?id=${encodeURIComponent(id)}&index=${index}`,signal)):null;const selected=sequence&&preserve?await sequence.seek(before):{scene:next,local:preserve?time:0};if(request!==sceneRequest)return;installScene(selected.scene,value,preserve,false,selected.local);
 }catch(e){if(request!==sceneRequest)return;sceneLoading=false;$('loading').hidden=true;if([...$('source').options].some(o=>o.value===activeSource))$('source').value=activeSource;notify(e.message);}
}

function installScene(next,value,preserve,keepCamera=false,local=null){
  const old=$('focus').value;$('selection-chip').hidden=true;if(view)view.selectedByUser=false;scene=next;prepareScene(scene);$('compute-backend').textContent=computeBackend();if(!preserve){time=0;playing=false;}if(local!==null)time=local;$('play').textContent=playing?'Ⅱ':'▶';$('play').setAttribute('aria-label',playing?'Pause animation':'Play animation');time=Math.min(time,scene.times.length-1);
  $('scene-title').textContent=scene.title;$('source-badge').textContent=scene.source.kind==='illustrative'?'ILLUSTRATIVE':scene.source.kind==='modeled'?'MODELED':'SAVED DATA';$('frame-label').textContent=`${scene.frame} · KM`;
  focusObjects=scene.objects.filter(o=>!['station','sensor'].includes(o.kind));renderFocusOptions(old);
  if(!$('focus').value&&scene.objects.length)$('focus').append(new Option(scene.objects[0].name,scene.objects[0].id));
  $('scrub').max=scene.sequence?scene.sequence.total_frames-1:scene.times.length-1;view?.setScene(scene,$('focus').value,keepCamera);if(view){view.mode=mode;if(!keepCamera)view.reset();}activeSource=value;$('sequence-status').textContent=scene.sequence?`Window ${scene.sequence.index+1} of ${scene.sequence.windows.length}`:'';$('export').textContent=scene.sequence?'Export window ↓':'Export scene ↓';
  $('provenance').textContent=JSON.stringify({source:scene.source,frame:scene.frame,units:scene.units,custody_seconds:scene.custody_seconds,warnings:scene.warnings,environment:scene.environment?.sources||[],celestial:'CesiumJS built-in celestial rendering at scene UTC',renderer:'CesiumJS',display:'Earth texture and cloud pattern are static visual assets, not observations at the scene epoch. Ionosphere is qualitative. Cesium converts source frames for display. Spacecraft sizes are exaggerated. No antenna or propagation physics is inferred.'},null,2);
  $('celestial-note').textContent='CesiumJS · built-in atmosphere, lighting, Sun & Moon';
  analysis?.setScene(scene,$('focus').value);sceneLoading=false;$('loading').hidden=view?.readyToDisplay!==false;drawEvents();updateText();if(sequence)sequence.prefetch(globalTime());refreshLinks();
}
async function seekWindow(global){
 if(!sequence)return;const player=sequence,{index,local}=player.position(global);
 const request=++windowRequest;if(scene.sequence.index===index){sequence.current=index;time=local;windowLoading=false;sceneLoading=false;$('loading').hidden=true;return;}
 windowLoading=true;sceneLoading=true;$('loading').hidden=false;$('loading').textContent='Loading next time window…';
 try{const result=await player.seek(global);if(request!==windowRequest||sequence!==player)return;installScene(result.scene,activeSource,true,true,result.local);}
 catch(e){if(request===windowRequest&&e.name!=='AbortError'){playing=false;$('play').textContent='▶';$('play').setAttribute('aria-label','Play animation');notify(e.message);}}
 finally{if(request===windowRequest){windowLoading=false;sceneLoading=false;$('loading').hidden=true;}}
}


async function refreshLinks(){
 const serial=++linkSerial;linkController?.abort();linkResult=null;linkMessage='Calculating propagation estimates…';
 const config=scene?.ground_links;$('link-panel').hidden=!config;if(!config)return;
 const selected=$('link-station').value;$('link-station').replaceChildren(...config.stations.map(s=>new Option(s.name,s.id)));
 if(config.stations.some(s=>s.id===selected))$('link-station').value=selected;
 $('link-frequency').textContent=`${(config.frequency_hz/1e9).toFixed(5)} GHz`;updateLinks();
 if(!scene.source.artifact_id){linkMessage='Save this scene to a local artifact to calculate propagation estimates.';return;}
 linkController=new AbortController();const requestScene=scene;
 try{const data=await api(`/api/studio/links?id=${encodeURIComponent(scene.source.artifact_id)}&window=${scene.sequence?.index||0}&object=${encodeURIComponent($('focus').value)}&station=${encodeURIComponent($('link-station').value)}`,linkController.signal);
  if(serial!==linkSerial||scene!==requestScene)return;
  if(data.scene_sha256!==scene.source.sha256)throw Error('Scene changed during calculation; reload the source.');
  linkResult=data;linkMessage='';updateLinks();
 }catch(e){if(serial===linkSerial&&e.name!=='AbortError'){linkMessage=e.message;updateLinks();}}
}
function updateLinks(){
 if(!scene?.ground_links)return;const i=Math.min(Math.floor(time),scene.times.length-1),row=linkResult?.rows[i];if(row===lastLinkRow&&linkMessage===lastLinkMessage&&linkResult===lastLinkResult)return;lastLinkRow=row;lastLinkMessage=linkMessage;lastLinkResult=linkResult;
 for(const [id,key,suffix,digits] of [['link-elevation','elevation_deg','°',2],['link-vacuum','vacuum_time_ms',' ms',3],['link-dry','dry_slant_delay_m',' m',3],['link-ionosphere','ionosphere_group_delay_m',' m',3],['link-faraday','uplink_faraday_deg','°',3],['link-cloud','cloud_fraction','',2]]){const value=row?.[key];$(id).textContent=Number.isFinite(value)?value.toFixed(digits)+suffix:'—';}
 $('link-status').textContent=linkMessage||(row?`Sample epoch ${linkResult.times[i]}. ${Object.values(row.unavailable).join('. ')}`:'No propagation estimate.');
 $('link-inputs').textContent=JSON.stringify(row?{inputs:row.inputs,station:linkResult.station,limits:linkResult.limits}:{status:linkMessage},null,2);
}
$('link-station').onchange=refreshLinks;

function drawEvents(){if(!scene)return;$('timeline-events').style.display=scene.sequence?'none':'';const nodes=scene.times.map((_,i)=>{const x=document.createElement('i'),s=trackState(scene,$('focus').value,i).state;x.style.background=({observed:'#83e3cf',stale:'#ffcf88',lost:'#ff788a',unknown:'#536775',unavailable:'#283542'})[s];x.title=`${scene.times[i]}: ${s}`;return x;});$('timeline-events').replaceChildren(...nodes);}
function updateText(){if(!scene)return;analysis?.update(time);const i=Math.min(Math.floor(time),scene.times.length-1),state=trackState(scene,$('focus').value,time),object=scene.objects.find(o=>o.id===$('focus').value),colors={observed:'#83e3cf',stale:'#ffcf88',lost:'#ff788a',unknown:'#97adbc',unavailable:'#97adbc'};
 const next=Math.min(i+1,scene.times.length-1),instant=Date.parse(scene.times[i])+(Date.parse(scene.times[next])-Date.parse(scene.times[i]))*(time-i);
 const seconds=(instant-Date.parse(scene.sequence?.start||scene.times[0]))/1000,duration=(Date.parse(scene.sequence?.end||scene.times.at(-1))-Date.parse(scene.sequence?.start||scene.times[0]))/60000;
 if(Number($('scrub').value)!==globalTime())$('scrub').value=globalTime();put('elapsed',`${String(Math.floor(seconds/60)).padStart(2,'0')}:${String(Math.floor(seconds%60)).padStart(2,'0')}`);put('utc',new Date(instant).toISOString().replace('T',' ').replace('Z',' UTC'));$('sequence-status').dataset.cachedWindows=String(sequence?.cache.size||0);put('duration',`${duration.toFixed(duration%1?1:0)} MINUTES`);
 put('object-title',object?.name||'No target');put('selection-chip',`${object?.name||'Selected satellite'} · Inspect →`);put('object-meta',object?`${object.kind.toUpperCase()} · ${object.id}`:'');
 put('state-name',({observed:'Observed now',stale:'Last sighting',lost:'Track lost',unknown:'Status unknown',unavailable:'Position unavailable'})[state.state]);$('state-dot').style.background=colors[state.state];put('age',state.age===null?'No known sighting':state.age===0?'Just now':`${Math.round(state.age)}s ago`);
 const copy={observed:['A fresh observation','The sensor sees this object. Its track has just been updated.'],stale:['No new sighting','The object keeps moving. The amber marker stays at the last observed position while the track ages.'],lost:['The track expires','The object is still in space, but its last sighting is older than the custody window. The tracker no longer has a current track.'],unknown:['Geometry without observation history','This source contains positions but no observation record at this step. We cannot tell whether the tracker sees the object.'],unavailable:['No position at this step','The source has no valid position for this object. We leave the gap visible rather than inventing a trajectory.']};
 put('state-caption',copy[state.state][1]);put('step-title',copy[state.state][0]);put('step-body',scene.observations?.[i]?.cause||copy[state.state][1]);put('step-number',String(Math.floor(globalTime())+1).padStart(2,'0'));$('lost-overlay').hidden=state.state!=='lost';
 updateLinks();
 const targets=focalObjects();put('object-count',targets.length);put('custody-count',scene.observations?.[i]?targets.filter(o=>['observed','stale'].includes(trackState(scene,o.id,time).state)).length:'—');
}
let lastPaint=0, performanceStart=0, frameDurations=[],lastReadout=0;
function render(ts){if(ts-lastPaint<16){requestAnimationFrame(render);return;}lastPaint=ts;const frameStart=performance.now();const dt=Math.min((ts-previous)/1000,.2);previous=ts;if(scene){if(playing&&!windowLoading){time+=dt*Number($('speed').value);if(time>=scene.times.length-1){const target=globalTime();time=scene.times.length-1;if(sequence&&target<sequence.meta.total_frames-1){seekWindow(target);}else{playing=false;$('play').textContent='▶';$('play').setAttribute('aria-label','Play animation');}}}computeFrame(scene,time);view?.update(time,layers());if(!sceneLoading&&view?.readyToDisplay!==undefined){$('loading').hidden=view.readyToDisplay;if(!view.readyToDisplay)$('loading').textContent='Loading globe textures and engine assets…';}if(ts-lastReadout>=100){updateText();lastReadout=ts;}frameDurations.push(performance.now()-frameStart);if(!performanceStart)performanceStart=ts;if(ts-performanceStart>=2000){const sorted=[...frameDurations].sort((a,b)=>a-b),fps=frameDurations.length*1000/(ts-performanceStart),p95=sorted[Math.min(sorted.length-1,Math.floor(sorted.length*.95))];$('frame-performance').textContent=`${fps.toFixed(1)} FPS · CPU p95 ${p95.toFixed(1)} ms`;performanceStart=ts;frameDurations=[];}}requestAnimationFrame(render);}

$('play').onclick=()=>{if(!scene)return;if(globalTime()>=(sequence?.meta.total_frames||scene.times.length)-1){if(sequence)seekWindow(0);else time=0;}playing=!playing;$('play').textContent=playing?'Ⅱ':'▶';$('play').setAttribute('aria-label',playing?'Pause animation':'Play animation');};
$('scrub').oninput=()=>{const target=Number($('scrub').value);if(sequence)seekWindow(target);else time=target;updateText();};$('focus').onchange=changeFocus;$('focus-search').oninput=()=>renderFocusOptions();$('quality').onchange=()=>view?.setQuality($('quality').value);$('framing').onchange=()=>{if(view){view.framing=$('framing').value;view.reset();}};$('reset').onclick=()=>view?.reset();
$('modes').onclick=e=>{if(!e.target.dataset.mode)return;mode=e.target.dataset.mode;for(const b of $('modes').children)b.classList.toggle('active',b.dataset.mode===mode);if(view){view.mode=mode;view.reset();}if($('source').value==='demo')loadScene();};
$('source').onchange=()=>loadScene($('source').value);
$('export').onclick=()=>{if(!scene)return;const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(scene,null,2)],{type:'application/json'}));a.download='godsat-scene.json';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);};
async function refresh(){try{const data=await api('/api/studio/catalog');artifacts=data.artifacts;platform.setArtifacts(artifacts);$('inventory-status').textContent=`${artifacts.length} local artifacts${data.truncated?' (limited)':''}`;const chosen=$('source').value;const candidate=artifacts.filter(a=>a.local&&sceneCandidate(a));const opened=artifacts.find(a=>a.id===activeSource);if(opened&&!candidate.some(a=>a.id===opened.id))candidate.unshift(opened);$('source').replaceChildren(new Option('Illustrative demonstration','demo'),...candidate.map(a=>{const option=new Option(a.path.split('/').slice(-2).join(' / '),a.id);option.title=a.path;return option;}));if(candidate.some(a=>a.id===chosen))$('source').value=chosen;renderArtifacts();const active=artifacts.find(a=>a.id===chosen);if(active&&currentModified!==null&&active.modified!==currentModified)await loadScene(chosen,true);currentModified=active?.modified??null;if(selectedArtifact&&artifacts.some(a=>a.id===selectedArtifact))await inspect(selectedArtifact,false);}catch(e){notify(e.message);}}
function renderArtifacts(){const q=$('search').value.toLowerCase();const list=platform.filter(artifacts).filter(a=>`${a.path} ${a.kind}`.toLowerCase().includes(q));$('library-count').textContent=`${Math.min(list.length,500)} of ${list.length} matching artifacts`; if(selectedArtifact&&!list.some(a=>a.id===selectedArtifact)){selectedArtifact=null;++inspectRequest;$('inspect-title').textContent='Select an artifact';$('inspect-body').textContent='Choose an artifact from this view to inspect its contents.';$('load-artifact').hidden=true;}$('artifacts').replaceChildren(...list.slice(0,500).map(a=>{const b=document.createElement('button');b.className='artifact-row'+(a.id===selectedArtifact?' selected':'');const title=document.createElement('strong');title.textContent=a.name;const detail=document.createElement('small');detail.textContent=`${a.format.toUpperCase()} · ${(a.bytes/1024).toFixed(1)} KB${a.local?'':' · CLOUD PLACEHOLDER'} · ${a.path}`;b.append(title,detail);b.onclick=()=>inspect(a.id);return b;}));if(!list.length){const empty=document.createElement('p');empty.className='empty-state';empty.textContent='No artifacts match this view. Change the filter or search to explore more files.';$('artifacts').append(empty);}}
async function inspect(id,highlight=true){const request=++inspectRequest;selectedArtifact=id;if(highlight)renderArtifacts();$('inspect-title').textContent=artifacts.find(a=>a.id===id)?.name||'Artifact';$('load-artifact').hidden=!['json','csv','npz','parquet'].includes(artifacts.find(a=>a.id===id)?.format);try{const data=await api(`/api/studio/inspect?id=${encodeURIComponent(id)}`);if(request!==inspectRequest)return;const body=$('inspect-body');body.replaceChildren();if(data.media){const el=document.createElement(data.name.endsWith('.pdf')?'iframe':'img');el.src=data.media;el.title=data.name;if(el.tagName==='IMG')el.alt=data.name;body.append(el);}else if(data.rows){const wrapper=document.createElement('div');wrapper.className='table-scroll';const table=document.createElement('table'),head=document.createElement('tr');const keys=data.columns||Object.keys(data.rows[0]||{});const plot=tablePlot(data.rows,keys);if(plot)body.append(plot);for(const key of keys){const th=document.createElement('th');th.textContent=key;head.append(th);}table.append(head);for(const row of data.rows){const tr=document.createElement('tr');for(const key of keys){const td=document.createElement('td');td.textContent=typeof row[key]==='object'?JSON.stringify(row[key]):String(row[key]??'');tr.append(td);}table.append(tr);}wrapper.append(table);body.append(wrapper);}else{const pre=document.createElement('pre');pre.textContent=data.text||JSON.stringify(data.data??data,null,2);body.append(pre);}if(data.note){const p=document.createElement('p');p.className='fine';p.textContent=data.note;body.append(p);}}catch(e){if(request!==inspectRequest)return;$('inspect-body').textContent=e.message;}}
$('load-artifact').onclick=()=>{if(selectedArtifact)openSpatial(selectedArtifact);};
$('refresh').onclick=refresh;$('search').oninput=renderArtifacts;
platform=new WorkspaceUI({onFilter:renderArtifacts,onScene:openSpatial,inspect});
new ExperimentPanel({onOpen:async id=>{await refresh();openSpatial(id);}});
analysis=new AnalysisPanel({onFocus:id=>{renderFocusOptions(id);changeFocus();},onSeek:local=>{time=local;updateText();analysis.update(time,true);},onPause:()=>{playing=false;$('play').textContent='▶';$('play').setAttribute('aria-label','Play animation');}});
await initializeCompute();await refresh();initializeView();
const initialScene=[...$('source').options].find(o=>/scene-sequence\.json$/.test(o.text))||[...$('source').options].find(o=>/(?:\/| \/ )(scene|replay)\.json$/.test(o.text));
$('source').value=initialScene?.value||'demo';await loadScene($('source').value);requestAnimationFrame(render);setInterval(()=>{if(!document.hidden)refresh();},15000);
