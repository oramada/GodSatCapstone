import {interpolatePosition} from './interpolation.js';

// WGS84 ellipsoid. Input/output distance units are km, angles degrees.
export function geodetic(p){
 if(!p||!p.every(Number.isFinite)||Math.hypot(...p)<1)return null;
 const [x,y,z]=p,a=6378.137,b=6356.752314245,e2=1-b*b/(a*a),ep2=(a*a-b*b)/(b*b),r=Math.hypot(x,y);
 if(r<1e-10)return {latitude:Math.sign(z)*90,longitude:0,altitude:Math.abs(z)-b};
 const theta=Math.atan2(z*a,r*b);let lat=Math.atan2(z+ep2*b*Math.sin(theta)**3,r-e2*a*Math.cos(theta)**3);
 for(let i=0;i<10;i++){const n=a/Math.sqrt(1-e2*Math.sin(lat)**2),next=Math.atan2(z+e2*n*Math.sin(lat),r);if(Math.abs(next-lat)<1e-14){lat=next;break;}lat=next;}
 const n=a/Math.sqrt(1-e2*Math.sin(lat)**2);
 return {latitude:lat*180/Math.PI,longitude:Math.atan2(y,x)*180/Math.PI,altitude:r/Math.cos(lat)-n};
}
export function telemetry(scene,object,time){
 if(!object)return null;const position=interpolatePosition(object,scene.times,time);if(!position)return null;
 const velocity=object.velocities_km_s?.[Math.floor(time)];
 return {position,radius:Math.hypot(...position),geodetic:scene.frame==='ITRS'?geodetic(position):null,sampleSpeed:velocity?Math.hypot(...velocity):null};
}
export function groundTrack(scene,object){
 if(scene.frame!=='ITRS'||!object)return [];
 const segments=[];let segment=[];
 for(const p of object.positions_km){const g=geodetic(p);if(!g){if(segment.length)segments.push(segment);segment=[];continue;}
  if(segment.length&&Math.abs(g.longitude-segment.at(-1).longitude)>180){segments.push(segment);segment=[];}
  segment.push(g);
 }if(segment.length)segments.push(segment);return segments;
}
export function timeStep(times,instant){
 const target=typeof instant==='number'?instant:Date.parse(instant),stamps=times.map(Date.parse);
 if(!Number.isFinite(target)||target<stamps[0]||target>stamps.at(-1))return null;
 let lo=0,hi=stamps.length-1;while(lo<hi){const mid=Math.ceil((lo+hi)/2);if(stamps[mid]<=target)lo=mid;else hi=mid-1;}
 return lo===stamps.length-1?lo:lo+(target-stamps[lo])/(stamps[lo+1]-stamps[lo]);
}
// Compare positions only at saved epochs, in a shared frame and time grid.
// These are not continuous closest approaches, collision probabilities or warnings.
export function screenSamples({positions,focus,objects,frames,focusIndex,threshold},progress=()=>{}){
 if(!Number.isInteger(objects)||!Number.isInteger(frames)||objects<1||objects>20000||frames<1||objects*frames>1200000||positions.length!==objects*frames*3||focus.length!==frames*3||!Number.isFinite(threshold)||threshold<0)throw Error('Invalid screening bounds');
 const rows=[];let comparisons=0,unavailableObjects=0;
 for(let j=0;j<objects;j++){
  if(j===focusIndex)continue;let best=Infinity,index=-1,valid=0;
  for(let k=0;k<frames;k++){const o=(j*frames+k)*3,f=k*3;const d=Math.hypot(positions[o]-focus[f],positions[o+1]-focus[f+1],positions[o+2]-focus[f+2]);if(!Number.isFinite(d))continue;valid++;comparisons++;if(d<best){best=d;index=k;}}
  if(index<0)unavailableObjects++;else if(best<=threshold)rows.push({objectIndex:j,distanceKm:best,index,validSamples:valid});
  if(j%256===0)progress(j/objects);
 }
 rows.sort((a,b)=>a.distanceKm-b.distanceKm||a.objectIndex-b.objectIndex);
 return {rows:rows.slice(0,100),matchingObjects:rows.length,unavailableObjects,comparisons};
}
export function csvRows(rows){return rows.map(row=>row.map(value=>{let s=String(value??'');if(typeof value==='string'&&/^[\s]*[=+@-]/.test(s))s="'"+s;return '"'+s.replaceAll('"','""')+'"';}).join(',')).join('\r\n')+'\r\n';}
