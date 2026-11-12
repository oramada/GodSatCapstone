import * as THREE from './vendor/three.module.js';
import {craft,orient,sample,trackState} from './model.js';
import {attitudeAt,displayAttitude,attitudeCaption} from './attitude.js';
export class DetailView {
 constructor(canvas){this.caption='';this.renderer=new THREE.WebGLRenderer({canvas,antialias:true,alpha:true});this.renderer.setClearColor(0,0);this.renderer.outputColorSpace=THREE.SRGBColorSpace;this.renderer.toneMapping=THREE.ACESFilmicToneMapping;this.renderer.toneMappingExposure=1.1;this.scene=new THREE.Scene();this.camera=new THREE.PerspectiveCamera(32,1,.01,100);this.camera.position.set(2.5,1.5,5.8);this.camera.lookAt(0,0,0);this.scene.add(new THREE.AmbientLight(0xa9c4d4,2));const key=new THREE.DirectionalLight(0xffffff,4);key.position.set(3,4,6);this.scene.add(key);this.craft=craft();this.scene.add(this.craft);this.observer=new ResizeObserver(()=>this.resize());this.observer.observe(canvas.parentElement);this.setQuality('high');}
 resize(){const b=this.renderer.domElement.parentElement.getBoundingClientRect();this.visible=b.width>0&&b.height>0;this.dirty=this.visible;if(!this.visible)return;this.renderer.setSize(b.width,b.height,false);this.camera.aspect=b.width/b.height;this.camera.updateProjectionMatrix();}
 setQuality(q){this.renderer.setPixelRatio(Math.min(devicePixelRatio,q==='high'?2:1));this.resize();}
 update(scene,id,time){
  const object=scene.objects.find(o=>o.id===id);this.dirty=false;this.caption=attitudeCaption(object,time);
  if(!this.visible)return;
  const state=trackState(scene,id,time),q=attitudeAt(object,time);
  this.craft.visible=!!object&&!!sample(object.positions_km,time)&&state.state!=='lost'&&(!object.attitude||!!q);
  if(q)this.craft.quaternion.fromArray(displayAttitude(q));else if(object&&!object.attitude)orient(this.craft,object.positions_km,time);
  this.renderer.render(this.scene,this.camera);
 }
 destroy(){this.observer.disconnect();this.scene.traverse(o=>{o.geometry?.dispose();const ms=Array.isArray(o.material)?o.material:[o.material];ms.forEach(m=>{m?.map?.dispose();m?.dispose();});});this.renderer.dispose();}
}
