import {computedState,computedTrack} from './compute.js';
import * as THREE from './vendor/three.module.js';
export const R = 6378.135;
export function vector(p) { return p ? new THREE.Vector3(p[0]/R, p[2]/R, -p[1]/R) : null; }
export function sample(track, time) {
  const accelerated=computedTrack(track,time);if(accelerated!==undefined)return vector(accelerated);
  const a = Math.floor(time), b = Math.min(a+1, track.length-1), p = vector(track[a]), q = vector(track[b]);
  // Do not bridge missing source samples.
  return time===a?p:(p && q ? p.lerp(q, time-a) : null);
}
export function trackState(scene, id, time) {
  const accelerated=computedState(scene,id,time);if(accelerated)return accelerated;
  const step = Math.min(Math.floor(time), scene.times.length-1);
  const obj = scene.objects.find(o => o.id === id);
  if (!obj || !obj.positions_km[step]) return {state:'unavailable', last:-1, age:null};
  if (!scene.observations || !scene.observations[step]) return {state:'unknown', last:-1, age:null};
  let last=-1;
  for (let i=step; i>=0; i--) if (scene.observations[i]?.detected.includes(id)) {last=i; break;}
  if (last<0) return {state:'lost', last, age:null};
  const seconds = (Date.parse(scene.times[step])-Date.parse(scene.times[last]))/1000;
  return {state: seconds===0 ? 'observed' : seconds <= scene.custody_seconds ? 'stale' : 'lost', last, age:seconds};
}
export function craft() {
  const group = new THREE.Group();
  const metal = new THREE.MeshStandardMaterial({color:0xc6d8df, metalness:.65, roughness:.3});
  const gold = new THREE.MeshStandardMaterial({color:0xb89a5e, metalness:.7, roughness:.42});
  const body = new THREE.Mesh(new THREE.BoxGeometry(.62,.75,.58), metal); group.add(body);
  const antenna = new THREE.Mesh(new THREE.CylinderGeometry(.42,.34,.1,6), gold); antenna.position.y=-.43; group.add(antenna);
  const plate = new THREE.Mesh(new THREE.BoxGeometry(.58,.035,.52),new THREE.MeshStandardMaterial({color:0xe4e8dc, roughness:.8})); plate.position.y=-.49;group.add(plate);
  const canvas=document.createElement('canvas');canvas.width=256;canvas.height=512;
  const ctx=canvas.getContext('2d');ctx.fillStyle='#0d3269';ctx.fillRect(0,0,256,512);
  for(let y=2;y<512;y+=32) for(let x=2;x<256;x+=32){ctx.fillStyle=(x+y)%3?'#164a86':'#1e5795';ctx.fillRect(x,y,29,29);ctx.fillStyle='#6d9dc2';ctx.fillRect(x,y,29,1);}
  const texture=new THREE.CanvasTexture(canvas);texture.colorSpace=THREE.SRGBColorSpace;
  const solar=new THREE.MeshStandardMaterial({map:texture,metalness:.45,roughness:.35,side:THREE.DoubleSide});
  for(const sign of [-1,1]){
    const boom=new THREE.Mesh(new THREE.CylinderGeometry(.02,.02,.56,8),metal);boom.rotation.z=Math.PI/2;boom.position.x=sign*.56;group.add(boom);
    const panel=new THREE.Mesh(new THREE.BoxGeometry(1.18,.035,.73),[solar,solar,solar,solar,solar,solar]);panel.position.x=sign*1.32;group.add(panel);
    const edge=new THREE.LineSegments(new THREE.EdgesGeometry(panel.geometry),new THREE.LineBasicMaterial({color:0x6b8fa8}));edge.position.copy(panel.position);group.add(edge);
  }
  for(const sign of [-1,1]){const dish=new THREE.Mesh(new THREE.SphereGeometry(.14,16,12,0,Math.PI*2,0,Math.PI/2),gold);dish.position.set(sign*.38,.12,.26);dish.rotation.z=sign*Math.PI/2;group.add(dish);}
  return group;
}
export function orient(group, track, time) {
  const p=sample(track,time);if(!p)return;
  const n=Math.max(0,Math.min(track.length-2,Math.floor(time)));
  const a=vector(track[n]),b=vector(track[n+1]);
  const y=p.clone().normalize(), x=a&&b?b.sub(a).normalize():new THREE.Vector3(1,0,0);
  x.addScaledVector(y,-x.dot(y)).normalize();
  if(x.length()<.5) x.set(1,0,0).cross(y).normalize();
  const z=x.clone().cross(y).normalize();
  group.quaternion.setFromRotationMatrix(new THREE.Matrix4().makeBasis(x,y,z));
}
