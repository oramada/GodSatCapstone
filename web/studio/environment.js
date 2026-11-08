// Point samples stay point samples: no invented global field or gap filling.
export const fields={vertical_tec_tecu:'Vertical TEC · TECU',electron_density_m3:'Electron density · m⁻³',cloud_fraction:'Cloud fraction · 0–1',neutral_density_kg_m3:'Neutral density · kg/m³',magnetic:'Magnetic field · nT'};
export class EnvironmentIndex {
 constructor(bundle){this.bundle=bundle||{sources:[],samples:[]};this.samples=this.bundle.samples.map(s=>({...s,start:Date.parse(s.time_utc),end:Date.parse(s.valid_until_utc)}));this.events=this.samples.flatMap(s=>[{time:s.start,end:false},{time:s.end,end:true}]).sort((a,b)=>a.time-b.time||Number(a.end)-Number(b.end));this.key=null;this.active=[];}
 at(time){let lo=0,hi=this.events.length;while(lo<hi){const m=(lo+hi)>>>1;if(this.events[m].time<time||(this.events[m].time===time&&!this.events[m].end))lo=m+1;else hi=m;}if(this.key!==lo){this.key=lo;this.active=this.samples.filter(s=>s.start<=time&&time<=s.end);}return this.active;}
}
export function magnitude(sample,field){if(field==='magnetic'){const v=sample.values;return [v.magnetic_east_nt,v.magnetic_north_nt,v.magnetic_up_nt].every(Number.isFinite)?Math.hypot(v.magnetic_east_nt,v.magnetic_north_nt,v.magnetic_up_nt):null;}return sample.values[field]??null;}

export class EnvironmentLayer {
 constructor(scene,C){this.C=C;this.scene=scene;this.points=scene.primitives.add(new C.PointPrimitiveCollection());this.vectors=scene.primitives.add(new C.PolylineCollection());this.index=new EnvironmentIndex();this.selection=null;}
 setScene(data){this.index=new EnvironmentIndex(data.environment);this.selection=null;this.points.removeAll();this.vectors.removeAll();}
 update(time,field){const active=this.index.at(time);const key=`${this.index.key}:${field}`;if(key===this.selection)return this.legend||'Environmental layer off';this.selection=key;this.points.removeAll();this.vectors.removeAll();if(field==='none'){this.legend='Environmental layer off';return this.legend;}
  const rows=active.filter(s=>magnitude(s,field)!==null),shown=rows.length>2000?Array.from({length:2000},(_,i)=>rows[Math.floor(i*rows.length/2000)]):rows,C=this.C;let min=Infinity,max=-Infinity;for(const s of rows){const v=magnitude(s,field);min=Math.min(min,v);max=Math.max(max,v);}
  for(const s of shown){const value=magnitude(s,field),ratio=max===min?.5:(value-min)/(max-min);const position=C.Cartesian3.fromDegrees(s.longitude_deg,s.latitude_deg,s.altitude_km*1000);const c=C.Color.fromHsl((1-ratio)*.65,.8,.6,.9);this.points.add({position,pixelSize:4,color:c,outlineWidth:1,outlineColor:C.Color.BLACK});
   if(field==='magnetic'&&value>0){const v=s.values,local=new C.Cartesian3(v.magnetic_east_nt/value*300000,v.magnetic_north_nt/value*300000,v.magnetic_up_nt/value*300000);const end=C.Matrix4.multiplyByPoint(C.Transforms.eastNorthUpToFixedFrame(position),local,new C.Cartesian3());this.vectors.add({positions:[position,end],width:2,material:C.Material.fromType('Color',{color:c})});}
  }
  const kinds=[...new Set(shown.map(s=>this.index.bundle.sources.find(x=>x.id===s.source_id)?.kind))].join(', ');
  this.legend=rows.length?`${fields[field]} · ${min.toPrecision(3)}–${max.toPrecision(3)} · ${shown.length}/${rows.length} valid samples · ${kinds}${field==='magnetic'?' · vectors show direction, length exaggerated':''}`:`${fields[field]} · no valid samples at this time`;
  return this.legend;
 }
}
