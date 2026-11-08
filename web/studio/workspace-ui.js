import {collections,artifactCategory,sceneCandidate,compareNumbers} from './workspace.js';
const $=id=>document.getElementById(id);
function el(tag,text,className){const node=document.createElement(tag);if(text!==undefined)node.textContent=text;if(className)node.className=className;return node;}
const date=t=>new Date(t*1000).toLocaleDateString(undefined,{month:'short',day:'numeric',year:'numeric'});
export class WorkspaceUI {
 constructor({onFilter,onScene,inspect}){
  Object.assign(this,{onFilter,onScene,inspect,artifacts:[],groups:[],selected:null,page:'overview',comparison:0});
  this.panels=[['experiment-panel','experiment-toggle'],['workspace-sidebar','sidebar-toggle'],['data-panel','data-toggle'],['inspect-panel','inspect-toggle']];
  this.setPanel=(id,open=true,focus=true)=>{
   for(const [panelId,buttonId] of this.panels){const active=panelId===id&&open;$(panelId).hidden=!active;$(buttonId).setAttribute('aria-expanded',String(active));}
   if(open&&id&&focus){const heading=$(id).querySelector('h2');heading.tabIndex=-1;heading.focus({preventScroll:true});}
  };
  for(const [id,button] of this.panels)$(button).onclick=()=>this.setPanel(id,$(id).hidden);
  document.querySelectorAll('[data-close-panel]').forEach(button=>button.onclick=()=>{const id=button.closest('.overlay-panel').id;this.setPanel(null,false);$(this.panels.find(p=>p[0]===id)[1]).focus();});
  document.addEventListener('keydown',event=>{if(event.key==='Escape'){const active=this.panels.find(([id])=>!$(id).hidden);if(active){this.setPanel(null,false);$(active[1]).focus();event.preventDefault();}}});
  $('selection-chip').onclick=()=>this.setPanel('inspect-panel');
  this.setPanel(null,false,false);
  $('run-search').oninput=()=>this.renderRuns();$('artifact-category').onchange=onFilter;
  $('clear-run').onclick=()=>{this.selected=null;this.renderScope();onFilter();};
  $('compare-button').onclick=()=>this.compare();
  for(const id of ['compare-a','compare-b'])$(id).onchange=()=>{++this.comparison;this.setComparing(false);$('comparison-table').replaceChildren();$('comparison-status').textContent='Selection changed. Compare products to read the selected files.';};
  this.reveal('visualization',{focus:false});
 }
 reveal(page,{focus=true}={}){
  this.page=page;
  if(page==='visualization'){this.setPanel(null,false,false);return;}
  this.setPanel('data-panel',true,false);
  const target=page==='runs'?$('collections-panel'):$(page+'-drawer');
  if(target){target.open=true;if(focus){const summary=target.querySelector('summary');summary.focus({preventScroll:true});summary.scrollIntoView({block:'nearest'});}}
 }
 setArtifacts(artifacts){
  this.artifacts=artifacts;this.groups=collections(artifacts);
  if(this.selected)this.selected=this.groups.find(g=>g.id===this.selected.id)||null;
  for(const [id,count] of [['stat-collections',this.groups.length],['stat-artifacts',artifacts.length],['stat-tables',artifacts.filter(a=>artifactCategory(a)==='tables').length],['stat-inputs',artifacts.filter(a=>artifactCategory(a)==='inputs').length]])$(id).textContent=count.toLocaleString();
  this.renderRuns();this.renderScope();
  const candidates=artifacts.filter(a=>a.local&&a.format==='json'&&!sceneCandidate(a)&&!/-window-\d{5}\.json$/.test(a.path));
  candidates.sort((a,b)=>Number(!/summary|benchmark|result|response/i.test(a.name))-Number(!/summary|benchmark|result|response/i.test(b.name))||b.modified-a.modified);
  let changed=false;for(const [index,id] of ['compare-a','compare-b'].entries()){
   const old=$(id).value;$(id).replaceChildren(...candidates.map(a=>new Option(a.path,a.id)));
   if(candidates.some(a=>a.id===old))$(id).value=old;else if(candidates[index])$(id).value=candidates[index].id;
   if(old&&$(id).value!==old)changed=true;
  }
  if(changed){++this.comparison;this.setComparing(false);$('comparison-table').replaceChildren();$('comparison-status').textContent='Available products changed. Compare again to read the selected files.';}
  this.canCompare=candidates.length>=2;$('compare-button').disabled=this.comparing||!this.canCompare;
 }
 filter(artifacts){
  const category=$('artifact-category').value;
  const ids=this.selected?new Set(this.selected.artifacts.map(a=>a.id)):null;
  return artifacts.filter(a=>(!ids||ids.has(a.id))&&(category==='all'||artifactCategory(a)===category));
 }
 renderScope(){
  $('library-title').textContent=this.selected?this.selected.name:'Data library';
  $('library-context').textContent=this.selected?`${this.selected.path} · ${this.selected.artifacts.length} artifacts`:'Inputs, saved outputs, reports and source products across the workspace.';
  $('clear-run').hidden=!this.selected;
 }
 openCollection(group){this.selected=group;$('artifact-category').value='all';$('search').value='';this.renderScope();this.onFilter();this.reveal('library');}
 card(group){
  const card=el('article',undefined,'run-card'),top=el('div',undefined,'run-card-top');top.append(el('span',group.kind,'collection-kind'),el('span',date(group.modified),'collection-date'));
  const title=el('h3',group.name),path=el('p',group.path,'collection-path'),stats=el('p',`${group.artifacts.length} artifacts · ${group.artifacts.filter(a=>artifactCategory(a)==='tables').length} tables · ${group.artifacts.filter(a=>artifactCategory(a)==='figures').length} figures`,'collection-stats');
  const actions=el('div',undefined,'run-actions'),open=el('button','Inspect collection');open.onclick=()=>this.openCollection(group);actions.append(open);
  const priority=a=>/^(scene-sequence|scene|replay)\.json$/.test(a.name)?0:1;
  const spatial=group.artifacts.filter(a=>a.local&&sceneCandidate(a)).sort((a,b)=>priority(a)-priority(b)||b.modified-a.modified)[0];
  if(spatial){const visualize=el('button','Open visualization');visualize.className='quiet';visualize.onclick=()=>this.onScene(spatial.id);actions.append(visualize);}
  card.append(top,title,path,stats,actions);return card;
 }
 renderRuns(){
  const query=$('run-search').value.trim().toLowerCase(),groups=this.groups.filter(g=>`${g.name} ${g.path}`.toLowerCase().includes(query));
  $('run-grid').replaceChildren(...groups.map(g=>this.card(g)));
  $('runs-empty').hidden=groups.length>0;$('run-count').textContent=`${groups.length} collections`;
 }
 setComparing(busy){
  this.comparing=busy;
  $('compare-button').disabled=busy||!this.canCompare;
  $('compare-button').textContent=busy?'Reading products…':'Compare products';
  $('comparison-table').setAttribute('aria-busy',String(busy));
 }
 async compare(){
  if(this.comparing||!this.canCompare)return;
  this.setComparing(true);
  const serial=++this.comparison,a=$('compare-a').value,b=$('compare-b').value;
  $('comparison-status').textContent='Reading saved products…';$('comparison-table').replaceChildren();
  try{
   const responses=await Promise.all([a,b].map(id=>fetch(`/api/studio/inspect?id=${encodeURIComponent(id)}`,{cache:'no-store'}).then(async response=>{const value=await response.json();if(!response.ok)throw Error(value.error||'Artifact unavailable');return value;})));
   if(serial!==this.comparison)return;
   if(responses.some(r=>r.data?.truncated||!r.data||typeof r.data!=='object'||Array.isArray(r.data)))throw Error('Choose two bounded JSON objects. Large arrays, raw tables and truncated previews remain available in the data library.');
   const rows=compareNumbers(responses[0].data,responses[1].data);
   const table=el('table'),head=el('tr');for(const text of ['Field','A','B','B − A'])head.append(el('th',text));table.append(head);
   const format=v=>v===null?'—':Number.isInteger(v)?v.toLocaleString():v.toLocaleString(undefined,{maximumSignificantDigits:8});
   for(const row of rows){const tr=el('tr');for(const [index,value] of [row.field,format(row.a),format(row.b),format(row.delta)].entries()){const cell=el('td',value);if(index)cell.title=String([row.a,row.b,row.delta][index-1]??'Unavailable');tr.append(cell);}table.append(tr);}
   $('comparison-table').append(table);
   $('comparison-status').textContent=rows.length?`${rows.length} numeric fields, read at ${new Date().toLocaleTimeString()}. Arrays are excluded. Matching field names do not establish matching units or experimental conditions.`:'No scalar numeric fields in these products. Inspect their tables or documents in the data library.';
  }catch(error){if(serial===this.comparison)$('comparison-status').textContent=error.message;}
  finally{if(serial===this.comparison)this.setComparing(false);}
 }
}
