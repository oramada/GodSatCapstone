// Collections describe folders, never inferred execution status or experimental success.
export function sceneCandidate(a){return ['json','csv','parquet','npz'].includes(a.format)&&!/-window-\d{5}\.json$/.test(a.path)&&!/audit|reference|diagnostic|summary|browser|benchmark|config/i.test(a.name)&&/replay|scenario|trajectory|ephemeris|scene|state/i.test(a.name);}
export function artifactCategory(a){
 if(/^(data|configs)\//.test(a.path))return 'inputs';
 if(['csv','parquet'].includes(a.format))return 'tables';
 if(['png','jpg','jpeg','pdf'].includes(a.format))return 'figures';
 if(['md','txt','xml'].includes(a.format))return 'reports';
 if(sceneCandidate(a))return 'spatial';
 return 'other';
}
export function collections(artifacts){
 const groups=new Map();
 for(const artifact of artifacts){
  const p=artifact.path.split('/');let prefix,kind,name;
  if(p[0]==='outputs'&&p.length>=3){prefix=p.slice(0,2).join('/');name=p[1];kind='Local outputs';}
  else if(p[0]==='reports'&&['evidence','archive'].includes(p[1])&&p.length>=4){prefix=p.slice(0,3).join('/');name=p[2];kind=p[1]==='archive'?'Archived study':'Saved evidence';}
  else if(!['outputs','reports','configs','data'].includes(p[0])&&artifact.root){prefix=artifact.root+(p.length>1?'/'+p[0]:'');name=p.length>1?p[0]:artifact.root.split('/').filter(Boolean).at(-1);kind='External collection';}
  else continue;
  if(!groups.has(prefix))groups.set(prefix,{id:prefix,name:name.replaceAll('-',' ').replaceAll('_',' '),path:prefix,kind,artifacts:[],modified:0});
  const group=groups.get(prefix);group.artifacts.push(artifact);group.modified=Math.max(group.modified,artifact.modified||0);
 }
 return [...groups.values()].sort((a,b)=>b.modified-a.modified||a.id.localeCompare(b.id));
}
export function numericFields(value,prefix='',result=new Map(),depth=0){
 if(!value||typeof value!=='object'||Array.isArray(value)||depth>6)return result;
 for(const [key,item] of Object.entries(value)){
  const path=prefix+'/'+key.replaceAll('~','~0').replaceAll('/','~1');
  if(typeof item==='number'&&Number.isFinite(item))result.set(path,item);
  else if(item&&typeof item==='object'&&!Array.isArray(item))numericFields(item,path,result,depth+1);
 }
 return result;
}
export function compareNumbers(a,b){
 const left=numericFields(a),right=numericFields(b);
 return [...new Set([...left.keys(),...right.keys()])].sort().map(field=>{const delta=left.has(field)&&right.has(field)?right.get(field)-left.get(field):NaN;return {field,a:left.get(field)??null,b:right.get(field)??null,delta:Number.isFinite(delta)?delta:null};});
}
