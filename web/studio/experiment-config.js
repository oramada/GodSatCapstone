// Generated states are illustrative osculating states, never inferred from catalog elements.
export const ZONAL_MODEL={reference:'WGS-84 zonal J2–J4; Vallado et al., AIAA 2006-6753 Rev 3',normalization:'unnormalized_Jn',mu_km3_s2:398600.5,reference_radius_km:6378.137,coefficients:{'2':.00108262998905,'3':-.00000253215306,'4':-.00000161098761}};
export function buildExperiment(values,template=null){
 const config=template?structuredClone(template):{schema:'godsat.numerical.v1',frame:'GCRS',source:{kind:'illustrative',reference:'Studio-generated circular osculating states with explicit hypothetical spacecraft properties; not a catalog observation.'},objects:[]};
 config.epoch=values.epoch;config.duration_seconds=values.duration*60;config.integration_step_seconds=values.step;config.output_step_seconds=values.cadence;
 config.forces={j2:values.gravity==='j2',zonal_gravity:['zonal','saved'].includes(values.gravity),drag:values.drag,third_bodies:values.thirdBodies,solar_radiation_pressure:values.srp,schwarzschild:values.relativity};
 if(values.gravity==='zonal')config.gravity_model=structuredClone(ZONAL_MODEL);
 else if(values.gravity!=='saved')delete config.gravity_model;
 if(!template){
  if(!Number.isInteger(values.count)||values.count<1||values.count>2000)throw Error('Spacecraft count must be 1–2,000.');
  if(!Number.isFinite(values.altitude)||values.altitude<150||values.altitude>36000)throw Error('Altitude must be 150–36,000 km.');
  if(!Number.isFinite(values.inclination)||values.inclination<0||values.inclination>180)throw Error('Inclination must be 0–180°.');
  const r=(config.gravity_model?.reference_radius_km||6378.1366)+values.altitude,v=Math.sqrt((config.gravity_model?.mu_km3_s2||398600.4418)/r),inc=values.inclination*Math.PI/180;
  config.objects=Array.from({length:values.count},(_,i)=>{const phase=2*Math.PI*i/values.count,node=2*Math.PI*(i%6)/6,cp=Math.cos(phase),sp=Math.sin(phase),ci=Math.cos(inc),si=Math.sin(inc),cn=Math.cos(node),sn=Math.sin(node);const rotate=(x,y,z)=>[x*cn-y*sn,x*sn+y*cn,z];return {id:`synthetic-${i+1}`,name:`Synthetic ${i+1}`,position_gcrs_km:rotate(r*cp,r*sp*ci,r*sp*si),velocity_gcrs_km_s:rotate(-v*sp,v*cp*ci,v*cp*si)};});
 }
 if(!template||values.applyProperties){for(const object of config.objects)Object.assign(object,{mass_kg:values.mass,drag_area_m2:values.dragArea,drag_coefficient:values.cd,radiation_area_m2:values.radiationArea,radiation_coefficient:values.cr});if(template)config.source={...config.source,reference:config.source.reference+'; spacecraft mass/areas/coefficients explicitly overridden in Studio'};}
 return config;
}
