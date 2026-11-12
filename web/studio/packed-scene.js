// Versioned wire format. Metadata stays JSON; coordinates are exact little-endian Float64.
export const PACKED_SCENE_MIME = 'application/vnd.godsat.scene-f64';
const STAGING_LIMIT=16*1024*1024;
const staging=new WeakMap();
// Single-use buffers: the scene retains ordinary arrays for export and analysis.
export function takePackedCoordinates(scene){
 const value=staging.get(scene);staging.delete(scene);return value;
}
export function decodePackedScene(buffer) {
 const data=new DataView(buffer);
 if(data.byteLength<8||data.getUint32(0)!==0x47445331)throw Error('Invalid packed scene signature');
 const bytes=data.getUint32(4,true),start=8+bytes;
 if(bytes>64*1024*1024||start>data.byteLength)throw Error('Invalid packed scene metadata length');
 const {scene,velocities}=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(new Uint8Array(buffer,8,bytes)));
 const frames=scene?.times?.length,count=scene?.objects?.length;
 if(!Array.isArray(scene?.times)||!Array.isArray(scene?.objects)||frames<1||frames>1200||count>20000||frames*count>1200000||!Array.isArray(velocities)||velocities.length!==count||velocities.some(v=>typeof v!=='boolean'))throw Error('Invalid packed scene dimensions');
 const velocityCount=velocities.filter(Boolean).length,tracks=count+velocityCount;
 const coordinates=frames*count*3;
 const stage=coordinates*8*(velocityCount?2:1)<=STAGING_LIMIT;
 const positions=stage?new Float64Array(coordinates):null;
 const rates=stage&&velocityCount?new Float64Array(coordinates):null;
 if(rates&&velocityCount<count)rates.fill(NaN);
 if(start+tracks*frames*24!==data.byteLength)throw Error('Invalid packed scene payload length');
 let offset=start;
 const track=(target,objectIndex)=>{
  const rows=new Array(frames);
  for(let i=0;i<frames;i++){
   const x=data.getFloat64(offset,true),y=data.getFloat64(offset+8,true),z=data.getFloat64(offset+16,true);offset+=24;
   if(Number.isFinite(x)&&Number.isFinite(y)&&Number.isFinite(z))rows[i]=[x,y,z];
   else if(Number.isNaN(x)&&Number.isNaN(y)&&Number.isNaN(z))rows[i]=null;
   else throw Error('Invalid packed scene vector');
   if(target){const j=(i*count+objectIndex)*3;target[j]=x;target[j+1]=y;target[j+2]=z;}
  }
  return rows;
 };
 for(let i=0;i<count;i++){
  const obj=scene.objects[i];obj.positions_km=track(positions,i);
  if(velocities[i])obj.velocities_km_s=track(rates,i);
 }
 if(stage)staging.set(scene,{positions,velocities:rates});
 return scene;
}
