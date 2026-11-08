import test from 'node:test';
import assert from 'node:assert/strict';
import {collections,artifactCategory,compareNumbers,numericFields,sceneCandidate} from '../../web/studio/workspace.js';
test('collections scope outputs, evidence and external roots without inventing run states',()=>{
 const files=[{id:'1',path:'outputs/first/summary.json',modified:10},{id:'2',path:'outputs/first/tables/result.csv',modified:20},{id:'3',path:'outputs/second/scene.json',modified:30},{id:'4',path:'reports/evidence/study/report.md',modified:5},{id:'5',path:'configs/settings.json',modified:40},{id:'6',path:'summary.json',root:'/external/run',modified:2}];
 const groups=collections(files);assert.equal(groups.length,4);assert.equal(groups[0].id,'outputs/second');
 assert.deepEqual(groups.find(g=>g.id==='outputs/first').artifacts.map(a=>a.id),['1','2']);
 assert.equal(groups.find(g=>g.kind==='External collection').name,'run');assert.ok(groups.every(g=>!('status' in g)));
});
test('artifact roles keep source inputs separate and exclude sequence windows from playback candidates',()=>{
 assert.equal(artifactCategory({path:'data/catalog.json',name:'catalog.json',format:'json'}),'inputs');
 assert.equal(artifactCategory({path:'outputs/run/results.csv',name:'results.csv',format:'csv'}),'tables');
 assert.equal(sceneCandidate({name:'scene-window-00001.json',path:'outputs/run/scene-window-00001.json',format:'json'}),false);
 assert.equal(sceneCandidate({name:'scenario-audit.json',path:'reports/evidence/run/scenario-audit.json',format:'json'}),false);
});
test('comparison preserves missing quantities, skips arrays and booleans, and escapes field paths',()=>{
 const a={loss:.5,missing:2,nested:{score:3},trace:[100,200],success:true,'a/b':4,'a~b':5};
 const b={loss:.2,nested:{score:4},extra:1};const rows=compareNumbers(a,b);
 assert.equal(rows.find(r=>r.field==='/missing').b,null);assert.equal(rows.find(r=>r.field==='/missing').delta,null);
 assert.equal(rows.find(r=>r.field==='/nested/score').delta,1);assert.equal(numericFields(a).has('/a~1b'),true);
 assert.equal(numericFields(a).has('/a~0b'),true);assert.equal(numericFields(a).has('/trace'),false);assert.equal(numericFields(a).has('/success'),false);
 assert.equal(compareNumbers({x:-1e308},{x:1e308})[0].delta,null);
});
