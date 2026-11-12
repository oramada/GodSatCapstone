// Uses Cesium's maintained globe, atmosphere, materials and celestial renderers.
// No handwritten GLSL is used in this renderer.
import {DetailView} from './detail.js';
import {computedPosition,computeFrame,TRACK_STATES} from './compute.js';
import {trackState} from './model.js';
import {EnvironmentLayer} from './environment.js';
import {GpuProfile} from './gpu-profile.js';
import {interpolatePosition} from './interpolation.js';
const C=window.Cesium;
const radius=6378137;
// Colours come from the page: the window reads its design tokens and hands them over as
// [red, green, blue] bytes (palette keys below), so the globe, the timeline marks and the state
// labels speak one palette.
const PALETTE_KEYS=['observed','stale','lost','unknown','station','trail','label','labelBackground','background','globe','ionosphere','outline'];
const isBytes=value=>Array.isArray(value)&&value.length===3&&value.every(v=>Number.isInteger(v)&&v>=0&&v<=255);
function color(rgb,alpha=1){return C.Color.fromBytes(rgb[0],rgb[1],rgb[2],Math.round(alpha*255));}
export class CesiumObservatory {
 constructor(container,detail,{credits,palette}){
  for(const key of PALETTE_KEYS)if(!isBytes(palette?.[key]))throw Error(`Renderer palette is missing ${key}`);
  this.palette=palette;this.colors={observed:palette.observed,stale:palette.stale,lost:palette.lost,unknown:palette.unknown,unavailable:palette.unknown};
  this.station=null;this.environmentMessage='';this.profile=null;
  this.assetsReady=false;this.container=container;this.detail=new DetailView(detail);this.mode='single';this.framing='earth';this.generation=0;
  const probeOptions=new URLSearchParams(window.location.search);
  this.widget=new C.CesiumWidget(container,{baseLayer:false,terrainProvider:new C.EllipsoidTerrainProvider(),useDefaultRenderLoop:false,requestRenderMode:true,contextOptions:{webgl:{alpha:true,antialias:true,preserveDrawingBuffer:false}},creditContainer:credits});
  this.scene=this.widget.scene;this.scene.backgroundColor=color(palette.background);this.scene.globe.enableLighting=true;this.scene.globe.dynamicAtmosphereLighting=true;this.scene.globe.dynamicAtmosphereLightingFromSun=true;this.scene.globe.showGroundAtmosphere=true;this.scene.globe.baseColor=color(palette.globe);this.scene.light=new C.SunLight({intensity:1.5});this.scene.fog.enabled=false;this.scene.highDynamicRange=true;
  this.gpuProbe=probeOptions.get('gpu-profile')==='1'?new GpuProfile(this.scene.canvas):null;
  const isolate=probeOptions.get('isolate');
  this.probeIsolation=this.gpuProbe&&['globe-off','points-off','atmosphere-off'].includes(isolate)?isolate:null;
  if(this.probeIsolation==='globe-off')this.scene.globe.show=false;
  this.drawCount=0;this.scene.postRender.addEventListener(()=>{this.drawCount++;});
  this.scene.postProcessStages.fxaa.enabled=true;
  this.widget.clock.shouldAnimate=false;
  if(this.scene.skyBox)this.scene.skyBox.show=false;
  this.picker=new C.ScreenSpaceEventHandler(this.scene.canvas);
  this.picker.setInputAction(event=>{const picked=this.scene.pick(event.position);if(picked?.id&&this.data?.objects.some(o=>o.id===picked.id)){this.selectedByUser=true;this.container.dispatchEvent(new CustomEvent('objectselected',{detail:picked.id,bubbles:true}));}},C.ScreenSpaceEventType.LEFT_CLICK);

  this.points=this.scene.primitives.add(new C.PointPrimitiveCollection());this.points.show=this.probeIsolation!=='points-off';this.labels=this.scene.primitives.add(new C.LabelCollection());this.lines=this.scene.primitives.add(new C.PolylineCollection());
  this.environment=new EnvironmentLayer(this.scene,C);
  this.stationPoints=this.scene.primitives.add(new C.PointPrimitiveCollection());this.radioLines=this.scene.primitives.add(new C.PolylineCollection());this.radioLine=this.radioLines.add({positions:[],width:1.5,show:false,material:C.Material.fromType('PolylineDash',{color:color(palette.station,.65)})});
  this.ghostPoint=this.points.add({show:false,color:color(palette.stale,.6),pixelSize:16,outlineColor:color(palette.stale),outlineWidth:1});
  this.focusLabel=this.labels.add({text:'',show:false,font:'12px sans-serif',fillColor:color(palette.label),showBackground:true,backgroundColor:color(palette.labelBackground,.6),pixelOffset:new C.Cartesian2(0,-35),verticalOrigin:C.VerticalOrigin.BOTTOM});
  this.ionosphere=this.scene.primitives.add(new C.Primitive({geometryInstances:new C.GeometryInstance({geometry:new C.EllipsoidGeometry({radii:new C.Cartesian3(radius+350000,radius+350000,6356752+350000),vertexFormat:C.MaterialAppearance.MaterialSupport.TEXTURED.vertexFormat})}),appearance:new C.MaterialAppearance({material:C.Material.fromType('Grid',{color:color(palette.ionosphere,.1),cellAlpha:0,lineCount:new C.Cartesian2(48,24),lineThickness:new C.Cartesian2(.5,.5)}),translucent:true,closed:true}),show:false}));
  this.clouds=this.scene.primitives.add(new C.Primitive({geometryInstances:new C.GeometryInstance({geometry:new C.EllipsoidGeometry({radii:new C.Cartesian3(radius+12000,radius+12000,6356752+12000),vertexFormat:C.MaterialAppearance.MaterialSupport.TEXTURED.vertexFormat})}),appearance:new C.MaterialAppearance({material:C.Material.fromType('Image',{image:'/studio/assets/earth-clouds.png',color:C.Color.WHITE.withAlpha(.5),transparent:true}),translucent:true,closed:true})}));
  C.SingleTileImageryProvider.fromUrl('/studio/assets/earth-day.jpg',{credit:'Earth imagery: Three.js example texture'}).then(provider=>{if(!this.widget.isDestroyed()){this.scene.imageryLayers.addImageryProvider(provider);this.assetsReady=true;this.scene.requestRender();}}).catch(error=>this.notify(error.message));
  this.setQuality('high');this.observer=new ResizeObserver(()=>{this.widget.resize();this.scene.requestRender();});this.observer.observe(container);
 }
 get readyToDisplay(){return this.assetsReady&&(!this.scene.globe.show||this.scene.globe.tilesLoaded);}
 notify(message){this.container.dispatchEvent(new CustomEvent('renderererror',{detail:message,bubbles:true}));}
 setQuality(q){this.widget.resolutionScale=q==='high'?Math.min(devicePixelRatio,2):1;this.detail.setQuality(q);this.widget.resize();this.scene.requestRender();}
 fixed(p,time){if(!p)return undefined;const v=new C.Cartesian3(p[0]*1000,p[1]*1000,p[2]*1000);if(this.data.frame==='ITRS')return v;
  const transform=this.data.frame==='TEME'?C.CelestialFrameTransforms.computeTemeToPseudoFixedMatrix(time):C.CelestialFrameTransforms.computeIcrfToFixedMatrix(time);
  return transform?C.Matrix3.multiplyByVector(transform,v,new C.Cartesian3()):undefined;
 }
 sample(object,step){const accelerated=computedPosition(this.data,object.id,step);return this.fixed(accelerated!==undefined?accelerated:interpolatePosition(object,this.data.times,step),this.widget.clock.currentTime);}
 setScene(data,focus,keepCamera=false){
  const previous=this.data;
  const reuse=keepCamera&&this.ready&&data.sequence?.id&&previous?.sequence?.id===data.sequence.id&&previous.frame===data.frame&&data.frame!=='GCRS'&&this.items.length===data.objects.length&&this.items.every(({object},i)=>object.id===data.objects[i].id&&object.kind===data.objects[i].kind);
  this.lastFrame=null;this.radioKey=null;this.data=data;this.environment.setScene(data);this.stationPoints.removeAll();this.radioLine.show=false;this.groundStations=new Map((data.ground_links?.stations||[]).map(s=>{const position=C.Cartesian3.fromDegrees(s.longitude_deg,s.latitude_deg,s.altitude_km*1000);this.stationPoints.add({position,pixelSize:7,color:color(this.palette.station)});return [s.id,position];}));this.focus=focus;
  this.dates=data.times.map(t=>C.JulianDate.fromIso8601(t));this.widget.clock.startTime=this.dates[0];this.widget.clock.stopTime=this.dates.at(-1);this.widget.clock.currentTime=this.dates[0];
  if(reuse){
   for(let i=0;i<this.items.length;i++)this.items[i].object=data.objects[i];
   this.setFocus(focus);return;
  }
  this.generation++;const generation=this.generation;
  this.points.removeAll();this.labels.removeAll();this.lines.removeAll();if(this.model)this.scene.primitives.remove(this.model);if(this.ghostModel)this.scene.primitives.remove(this.ghostModel);this.model=this.ghostModel=null;
  const make=()=>{if(generation!==this.generation)return;this.items=data.objects.map((object,index)=>({object,index,point:this.points.add({id:object.id,pixelSize:object.kind==='station'?6:data.objects.length>2000?2:data.objects.length>500?3:7,color:color(object.kind==='station'?this.palette.station:this.palette.observed),outlineColor:color(this.palette.outline),outlineWidth:data.objects.length>500?0:1}),lines:[]}));
   this.ghostPoint=this.points.add({show:false,color:color(this.palette.stale,.3),pixelSize:18,outlineColor:color(this.palette.stale),outlineWidth:2});this.focusLabel=this.labels.add({text:'',show:false,font:'12px sans-serif',fillColor:color(this.palette.label),showBackground:true,backgroundColor:color(this.palette.labelBackground,.65),pixelOffset:new C.Cartesian2(0,-35),verticalOrigin:C.VerticalOrigin.BOTTOM});this.ready=true;this.setFocus(focus);if(!keepCamera)this.reset();};
  this.ready=false;this.items=[];
  if(data.frame==='GCRS')C.CelestialFrameTransforms.preloadIcrfFixed(new C.TimeInterval({start:this.dates[0],stop:this.dates.at(-1)})).then(make).catch(e=>this.notify('Frame transform unavailable: '+e.message));else make();
  for(const ghost of [false,true])C.Model.fromGltfAsync({url:'/studio/assets/iridium-illustrative.gltf',minimumPixelSize:ghost?40:44,maximumScale:2000000,scale:18000,show:false,upAxis:C.Axis.Z,color:ghost?color(this.palette.stale,.35):C.Color.WHITE,colorBlendMode:C.ColorBlendMode.MIX,colorBlendAmount:ghost?.6:0,enableVerticalExaggeration:false}).then(model=>{if(generation!==this.generation||this.widget.isDestroyed()){model.destroy();return;}this.scene.primitives.add(model);if(ghost)this.ghostModel=model;else this.model=model;}).catch(e=>this.notify('Spacecraft model unavailable: '+e.message));
 }
 setFocus(id){this.focus=id;if(this.focusLabel)this.focusLabel.text=this.data?.objects.find(o=>o.id===id)?.name||'';this.rebuildTrails();}
 rebuildTrails(){if(!this.items)return;this.lines.removeAll();for(const item of this.items){item.lines=[];if(this.items.length>500&&item.object.id!==this.focus)continue;let run=[];const flush=()=>{if(run.length>1)item.lines.push(this.lines.add({positions:run,width:1,material:C.Material.fromType('Color',{color:color(this.palette.trail,.35)})}));run=[];};item.object.positions_km.forEach((p,i)=>{const v=this.fixed(p,this.dates[i]);if(v)run.push(v);else flush();});flush();}}
 reset(){if(!this.data)return;const object=this.data.objects.find(o=>o.id===this.focus);let extent=radius*1.15;const objects=this.mode==='single'&&object?[object]:this.framing==='all'?this.data.objects:[];for(const o of objects)for(const p of o.positions_km)if(p)extent=Math.max(extent,Math.hypot(...p)*1000);const p=object?.positions_km.find(Boolean);const center=p?this.fixed(p,this.dates[object.positions_km.indexOf(p)]):undefined;const direction=center?C.Cartesian3.normalize(center,new C.Cartesian3()):C.Cartesian3.fromDegrees(110,-25);C.Cartesian3.normalize(direction,direction);const destination=C.Cartesian3.multiplyByScalar(direction,extent*3.4,new C.Cartesian3());this.scene.camera.setView({destination,orientation:{direction:C.Cartesian3.negate(direction,new C.Cartesian3()),up:C.Cartesian3.UNIT_Z}});this.scene.requestRender();}
 pose(object,step,position){const i=Math.floor(step),j=Math.min(i+1,this.dates.length-1);const a=this.fixed(object.positions_km[i],this.dates[i]),b=this.fixed(object.positions_km[j],this.dates[j]);const y=C.Cartesian3.normalize(position,new C.Cartesian3());let x=a&&b?C.Cartesian3.subtract(b,a,new C.Cartesian3()):new C.Cartesian3(1,0,0);x=C.Cartesian3.subtract(x,C.Cartesian3.multiplyByScalar(y,C.Cartesian3.dot(x,y),new C.Cartesian3()),x);if(C.Cartesian3.magnitude(x)<1e-6)x=C.Cartesian3.cross(y,C.Cartesian3.UNIT_Z,x);C.Cartesian3.normalize(x,x);const z=C.Cartesian3.normalize(C.Cartesian3.cross(x,y,new C.Cartesian3()),new C.Cartesian3());return C.Matrix4.fromRotationTranslation(C.Matrix3.fromColumnMajorArray([x.x,x.y,x.z,y.x,y.y,y.z,z.x,z.y,z.z]),position);}
 update(step,layers){if(!this.data)return;const profileStart=performance.now();let profileEnvironment,profileObjects,profileDetails;
  // Keep Cesium's update loop alive for camera input, inertia and asynchronous tiles.
  // Request a draw only when our scene content changes; the widget detects camera changes itself.
  const last=this.lastFrame;
  if(last&&last.step===step&&last.layers===layers&&last.items===this.items&&last.mode===this.mode&&last.focus===this.focus&&last.selected===this.selectedByUser&&last.station===this.station&&last.model===this.model&&last.ghostModel===this.ghostModel){
   if(this.detail.dirty)this.detail.update(this.data,this.focus,step);
   const beforeRender=performance.now();this.renderWidget();this.profile={environment:0,objects:0,details:beforeRender-profileStart,render:performance.now()-beforeRender};return;
  }
  this.lastFrame={step,layers,items:this.items,mode:this.mode,focus:this.focus,selected:this.selectedByUser,station:this.station,model:this.model,ghostModel:this.ghostModel};
  const i=Math.floor(step),j=Math.min(i+1,this.dates.length-1);this.widget.clock.currentTime=C.JulianDate.addSeconds(this.dates[i],C.JulianDate.secondsDifference(this.dates[j],this.dates[i])*(step-i),new C.JulianDate());this.scene.skyAtmosphere.show=layers.atmosphere&&this.probeIsolation!=='atmosphere-off';this.scene.globe.showGroundAtmosphere=layers.atmosphere&&this.probeIsolation!=='atmosphere-off';this.scene.sun.show=layers.celestial;this.scene.moon.show=layers.celestial;this.clouds.show=layers.clouds!=='clear';this.clouds.appearance.material.uniforms.color.alpha=layers.clouds==='dense'?.9:.45;this.ionosphere.show=layers.ionosphere;
  const message=this.environment.update(Date.parse(this.data.times[i])+(Date.parse(this.data.times[j])-Date.parse(this.data.times[i]))*(step-i),layers.environment||'none');this.environmentMessage=message;
  profileEnvironment=performance.now();
  const packed=computeFrame(this.data,step),fixedFrame=this.data.frame==='ITRS',now=this.widget.clock.currentTime;
  const transform=fixedFrame?null:this.data.frame==='TEME'?C.CelestialFrameTransforms.computeTemeToPseudoFixedMatrix(now):C.CelestialFrameTransforms.computeIcrfToFixedMatrix(now);
  const scratch=this.pointScratch??=new C.Cartesian3();
  for(const item of this.items){
   const {object,point,index}=item,focused=object.id===this.focus,shown=this.mode==='system'||focused||object.kind==='station'||object.kind==='sensor';
   for(const line of item.lines){const show=layers.trails&&shown;if(line.show!==show)line.show=show;}
   if(!shown){if(point.show)point.show=false;continue;}
   let position,state;
   if(packed){
    const offset=index*6,x=packed[offset];state=TRACK_STATES[packed[offset+3]];
    if(Number.isFinite(x)&&(fixedFrame||transform)){
     scratch.x=x*1000;scratch.y=packed[offset+1]*1000;scratch.z=packed[offset+2]*1000;
     position=fixedFrame?scratch:C.Matrix3.multiplyByVector(transform,scratch,scratch);
    }
   }else{position=this.sample(object,step);state=trackState(this.data,object.id,step).state;}
   if(point.show!==!!position)point.show=!!position;
   // PointPrimitive copies the position; this scratch is safe to reuse for every point.
   if(position)point.position=position;
   if(item.focused!==focused||item.state!==state){
    point.pixelSize=focused?8:object.kind==='station'?6:this.items.length>2000?1.5:this.items.length>500?3:7;
    point.color=color(object.kind==='station'?this.palette.station:this.colors[state],state==='lost'?.25:focused?1:.7);
    item.focused=focused;item.state=state;
   }
  }
  profileObjects=performance.now();const object=this.data.objects.find(o=>o.id===this.focus),position=object?this.sample(object,step):undefined,st=trackState(this.data,this.focus,step);this.focusLabel.show=!!position&&this.selectedByUser;if(position)this.focusLabel.position=position;
  const radioKey=`${this.generation}:${this.focus}:${this.station}:${step}`;if(radioKey!==this.radioKey){this.radioKey=radioKey;const ground=this.groundStations?.get(this.station);this.radioLine.show=false;if(ground&&position){const ray=C.Cartesian3.subtract(position,ground,new C.Cartesian3()),normal=C.Ellipsoid.WGS84.geodeticSurfaceNormal(ground,new C.Cartesian3());const sine=C.Cartesian3.magnitude(ray)>0?C.Cartesian3.dot(C.Cartesian3.normalize(ray,ray),normal):-1;if(sine>=Math.sin((this.data.ground_links.minimum_elevation_deg??15)*Math.PI/180)){this.radioLine.positions=[ground,position];this.radioLine.show=true;}}}
  if(this.model){this.model.show=!!position&&(this.selectedByUser||this.mode==='single');if(this.model.show){this.model.modelMatrix=this.pose(object,step,position);this.model.color=C.Color.WHITE.withAlpha(st.state==='lost'?.18:1);}}
  const ghost=layers.ghosts&&st.last>=0&&st.state!=='observed'&&object?this.fixed(object.positions_km[st.last],this.dates[st.last]):undefined;this.ghostPoint.show=!!ghost;if(ghost)this.ghostPoint.position=ghost;if(this.ghostModel){this.ghostModel.show=!!ghost;if(ghost)this.ghostModel.modelMatrix=this.pose(object,st.last,ghost);}
  this.detail.update(this.data,this.focus,step);profileDetails=performance.now();this.scene.requestRender();this.renderWidget();const done=performance.now();this.profile={environment:profileEnvironment-profileStart,objects:profileObjects-profileEnvironment,details:profileDetails-profileObjects,render:done-profileDetails};
 }
 renderWidget(){
  if(!this.gpuProbe){this.widget.render();return;}
  const before=this.drawCount,query=this.gpuProbe.begin();
  try{this.widget.render();}finally{this.gpuProbe.end(query,this.drawCount!==before);}
 }
 gpuReadout(){const value=this.gpuProbe?.readout();return this.probeIsolation&&value?`${value} · ${this.probeIsolation}`:value;}
 destroy(){this.gpuProbe?.destroy();this.generation++;this.observer.disconnect();this.picker.destroy();this.detail.destroy();this.widget.destroy();}
}
