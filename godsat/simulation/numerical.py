"""Separate Newtonian orbit experiments with explicit spacecraft properties.

The catalog SGP4 path is unchanged. This integrator starts from a supplied
osculating Cartesian state in GCRS axes and never treats TLE mean elements as
numerical osculating elements. Internal and output units are km and seconds.
"""
import argparse
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import warnings
import numpy as np
from .environment import utc,finite
from .atmosphere import SpaceWeather,MsisAtmosphere
from .forces import (zonal_gravity, solar_radiation_acceleration, schwarzschild_acceleration,
                     C_KM_S, AU_KM, SUN_RADIUS_KM, SOLAR_PRESSURE_N_M2)
from godsat.studio.scene import base,MAX_SAMPLES,MAX_OBJECTS,MAX_FRAMES

MU=398600.4418
RADIUS=6378.1366
J2=1.0826359e-3
BODY_MU={'sun':1.32712440018e11,'moon':4902.800066}


def validate_experiment(value):
    if not isinstance(value,dict) or value.get('schema')!='godsat.numerical.v1' or value.get('frame')!='GCRS':
        raise ValueError('Numerical experiment requires godsat.numerical.v1 and GCRS initial states')
    epoch=utc(value['epoch']);objects=value['objects'];source=value['source']
    if not isinstance(objects,list) or not 1<=len(objects)<=MAX_OBJECTS:raise ValueError('Invalid numerical object count')
    if not isinstance(source,dict) or source.get('kind') not in {'observed','modeled','illustrative'} or not isinstance(source.get('reference'),str) or not source['reference'].strip():
        raise ValueError('Initial states require source kind and reference')
    h=value['integration_step_seconds'];cadence=value['output_step_seconds'];duration=value['duration_seconds']
    if not all(finite(v) and v>0 for v in [h,cadence,duration]) or not .1<=h<=30 or duration>86400:
        raise ValueError('Positive integration step <=30 s and duration <=24 hours required')
    if not math.isclose(cadence/h,round(cadence/h),abs_tol=1e-9) or not math.isclose(duration/cadence,round(duration/cadence),abs_tol=1e-9):
        raise ValueError('Output cadence must be an integer integration-step multiple and divide duration')
    frames=round(duration/cadence)+1
    if frames>MAX_FRAMES or frames*len(objects)>MAX_SAMPLES:raise ValueError('Numerical output exceeds scene bounds')
    if round(duration/h)>100000:raise ValueError('Numerical experiment exceeds 100,000 integration steps')
    forces=value.get('forces',{})
    if not isinstance(forces,dict) or set(forces)-{'j2','drag','third_bodies','zonal_gravity','solar_radiation_pressure','schwarzschild'} or any(type(v) is not bool for v in forces.values()):
        raise ValueError('Force switches must be known, explicit booleans')
    if forces.get('zonal_gravity'):
        model=value.get('gravity_model')
        if not isinstance(model,dict) or not isinstance(model.get('reference'),str) or not model['reference'].strip():
            raise ValueError('Zonal gravity requires an explicit gravity_model with reference')
        if model.get('normalization')!='unnormalized_Jn':raise ValueError('Gravity coefficients must use unnormalized_Jn convention')
        if forces.get('j2'):raise ValueError('Zonal gravity includes J2; do not enable the separate j2 switch')
        if not finite(model.get('mu_km3_s2')) or not 390000<model['mu_km3_s2']<410000:raise ValueError('Invalid Earth gravity mu')
        if not finite(model.get('reference_radius_km')) or not 6300<model['reference_radius_km']<6400:raise ValueError('Invalid gravity reference radius')
        coefficients=model.get('coefficients')
        if not isinstance(coefficients,dict) or not coefficients or any(k not in {str(i) for i in range(2,9)} or not finite(v) or abs(v)>.01 for k,v in coefficients.items()):
            raise ValueError('Gravity requires finite unnormalized degree 2–8 Jn coefficients')
    ids=set()
    for obj in objects:
        if not isinstance(obj,dict):raise ValueError('Numerical objects must be records')
        if not isinstance(obj.get('id'),str) or obj['id'] in ids or not obj['id']:raise ValueError('Object IDs must be unique strings')
        ids.add(obj['id'])
        for key in ['position_gcrs_km','velocity_gcrs_km_s']:
            if not isinstance(obj[key],list) or len(obj[key])!=3 or not all(finite(v) for v in obj[key]):raise ValueError('Initial position and velocity require finite three-vectors')
        if np.linalg.norm(obj['position_gcrs_km'])<RADIUS+100:raise ValueError('Initial state must be above 100 km geocentric altitude')
        if forces.get('solar_radiation_pressure'):
            for key in ['mass_kg','radiation_area_m2','radiation_coefficient']:
                if not finite(obj.get(key)) or obj[key]<=0:raise ValueError(f'Solar radiation pressure requires positive explicit {key}')
        if forces.get('drag'):
            for key in ['mass_kg','drag_area_m2','drag_coefficient']:
                if not finite(obj.get(key)) or obj[key]<=0:raise ValueError(f'Drag requires positive explicit {key}')
    return epoch


def frame_table(times,third_bodies=False,solar=False):
    import astropy
    import astropy.units as u
    from astropy.coordinates import CartesianRepresentation,CartesianDifferential,GCRS,ITRS,get_body_barycentric
    from astropy.time import Time
    from astropy.utils import iers
    with warnings.catch_warnings(record=True) as notices,iers.conf.set_temp('auto_download',False):
        warnings.simplefilter('always');t=Time(times)
        xyz=np.repeat(np.eye(3)[:,:,None],len(times),axis=2)
        inertial=GCRS(CartesianRepresentation(xyz*u.km,differentials=CartesianDifferential(np.zeros_like(xyz)*u.km/u.s)),obstime=t)
        earth=inertial.transform_to(ITRS(obstime=t))
        rotation=np.moveaxis(earth.cartesian.xyz.to_value(u.km),-1,0)
        derivative=np.moveaxis(earth.velocity.d_xyz.to_value(u.km/u.s),-1,0)
        table=iers.earth_orientation_table.get();_,status=table.ut1_utc(t,return_status=True)
        path=Path(table.meta.get('data_path',''))
        bodies={}
        if third_bodies or solar:
            origin=get_body_barycentric('earth',t,ephemeris='builtin')
            for name in (BODY_MU if third_bodies else ['sun']):
                bodies[name]=(get_body_barycentric(name,t,ephemeris='builtin')-origin).xyz.to_value(u.km).T
        provenance={'astropy_version':astropy.__version__,'earth_orientation_table':type(table).__name__,
            'eop_sha256':hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None,
            'eop_status_codes':sorted(set(np.asarray(status).tolist())),
            'eop_status_meaning':{'-2':'beyond range','-1':'before range','0':'IERS B','1':'IERS A','2':'IERS A prediction'},
            'warnings':sorted({str(w.message) for w in notices}),
            'third_body_ephemeris':'Astropy builtin instantaneous barycentric position differences; Newtonian GCRS-axis approximation' if third_bodies or solar else None}
    return rotation,derivative,bodies,provenance


def gravity(position,j2=False):
    radius=np.linalg.norm(position,axis=1)
    acceleration=-MU*position/radius[:,None]**3
    if j2:
        q=(position[:,2]/radius)**2
        factor=1.5*J2*MU*RADIUS**2/radius**5
        acceleration+=factor[:,None]*position*np.column_stack((5*q-1,5*q-1,5*q-3))
    return acceleration


def drag_acceleration(velocity_itrs,density,cd_area_mass):
    if not np.isfinite(density).all() or np.any(np.asarray(density)<0):raise ValueError('Drag density must be finite and nonnegative')
    velocity_m_s=velocity_itrs*1000
    return -.5*(density*cd_area_mass*np.linalg.norm(velocity_m_s,axis=1))[:,None]*velocity_m_s/1000


def third_body_acceleration(position,body,mu):
    offset=body-position
    return mu*(offset/np.linalg.norm(offset,axis=1)[:,None]**3-body/np.linalg.norm(body)**3)


def integrate_experiment(value,atmosphere=None):
    epoch=validate_experiment(value);objects=value['objects'];forces=value.get('forces',{})
    if forces.get('drag') and atmosphere is None:raise ValueError('Drag requires an explicit atmosphere and driver history')
    h=value['integration_step_seconds'];steps=round(value['duration_seconds']/h);stride=round(value['output_step_seconds']/h)
    half_times=[epoch+dt.timedelta(seconds=k*h/2) for k in range(2*steps+1)]
    rotations,rates,bodies,provenance=frame_table(half_times,forces.get('third_bodies',False),forces.get('solar_radiation_pressure',False))
    model=value.get('gravity_model',{}) if forces.get('zonal_gravity') else {}
    mu=model.get('mu_km3_s2',MU);earth_radius=model.get('reference_radius_km',RADIUS)
    states=np.array([obj['position_gcrs_km']+obj['velocity_gcrs_km_s'] for obj in objects],dtype=float)
    ballistic=np.array([o['drag_coefficient']*o['drag_area_m2']/o['mass_kg'] for o in objects]) if forces.get('drag') else np.zeros(len(objects))
    radiation=np.array([o['radiation_coefficient']*o['radiation_area_m2']/o['mass_kg'] for o in objects]) if forces.get('solar_radiation_pressure') else None
    illumination_range=[1.,0.]
    history=[states.copy()];output_times=[epoch];calls=0;density_range=[float('inf'),0.]
    def rhs(stage,state):
        nonlocal calls
        calls+=1;rotation=rotations[stage];rate=rates[stage]
        r=state[:,:3];v=state[:,3:]
        if not np.isfinite(state).all() or np.any(np.linalg.norm(r,axis=1)<max(RADIUS,earth_radius)+100):raise ValueError('Numerical trajectory left the supported above-100-km domain')
        fixed_r=r@rotation.T
        acceleration=(zonal_gravity(fixed_r,mu,earth_radius,model['coefficients']) if model else gravity(fixed_r,forces.get('j2',False)))@rotation
        if forces.get('third_bodies'):
            for name,positions in bodies.items():acceleration+=third_body_acceleration(r,positions[stage],BODY_MU[name])
        if forces.get('schwarzschild'):acceleration+=schwarzschild_acceleration(r,v,mu)
        if radiation is not None:
            pressure,lit=solar_radiation_acceleration(r,bodies['sun'][stage],radiation,earth_radius)
            acceleration+=pressure
            illumination_range[0]=min(illumination_range[0],float(np.min(lit)))
            illumination_range[1]=max(illumination_range[1],float(np.max(lit)))
        if forces.get('drag'):
            fixed_v=v@rotation.T+r@rate.T
            density=atmosphere.density(half_times[stage],fixed_r)
            density_range[0]=min(density_range[0],float(np.min(density)));density_range[1]=max(density_range[1],float(np.max(density)))
            acceleration+=drag_acceleration(fixed_v,density,ballistic)@rotation
        return np.column_stack((v,acceleration))
    for step in range(steps):
        stage=2*step
        k1=rhs(stage,states);k2=rhs(stage+1,states+h*k1/2);k3=rhs(stage+1,states+h*k2/2);k4=rhs(stage+2,states+h*k3)
        states=states+h*(k1+2*k2+2*k3+k4)/6
        if (step+1)%stride==0:
            if not np.isfinite(states).all():raise ValueError('Numerical integrator produced nonfinite states')
            history.append(states.copy());output_times.append(half_times[stage+2])
    states=np.stack(history);indices=np.arange(0,2*steps+1,2*stride)
    fixed_positions=np.einsum('tij,tnj->tni',rotations[indices],states[:,:,:3])
    fixed_velocities=np.einsum('tij,tnj->tni',rotations[indices],states[:,:,3:])+np.einsum('tij,tnj->tni',rates[indices],states[:,:,:3])
    scene_objects=[{'id':o['id'],'name':o.get('name',o['id']),'kind':'satellite',
        'positions_km':fixed_positions[:,j].tolist(),'velocities_km_s':fixed_velocities[:,j].tolist()} for j,o in enumerate(objects)]
    source={'kind':'illustrative' if value['source']['kind']=='illustrative' else 'modeled',
        'description':'Numerically integrated osculating state experiment; not a modification of SGP4 catalog propagation.',
        'initial_state_source':value['source'],'force_model':forces,'integrator':'Vectorized fixed-step RK4',
        'experiment_sha256':hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
        'additional_forces_source_sha256':hashlib.sha256(Path(__file__).with_name('forces.py').read_bytes()).hexdigest(),
        'numerical_source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'numpy_version':np.__version__,
        'integration_step_seconds':h,'force_evaluations':calls,'constants':{'mu_km3_s2':mu,'earth_radius_km':earth_radius,'J2':J2 if not model else model['coefficients'].get('2',0)},
        'gravity_model':model or None,
        'solar_radiation':{'model':'Cannonball, inverse-square flux, uniform angular-disc overlap; spherical Earth occultor',
            'pressure_at_1au_n_m2':SOLAR_PRESSURE_N_M2,'au_km':AU_KM,'sun_radius_km':SUN_RADIUS_KM,
            'sampled_illumination_range':illumination_range} if radiation is not None else None,
        'relativity':{'model':'Schwarzschild, IERS 2010 Eq 10.12 first line, beta=gamma=1','c_km_s':C_KM_S} if forces.get('schwarzschild') else None,
        'frame_transform':provenance,'spacecraft_parameters':[{'id':o['id'],**{k:o[k] for k in ['mass_kg','drag_area_m2','drag_coefficient','radiation_area_m2','radiation_coefficient'] if k in o}} for o in objects],
        'atmosphere':atmosphere.provenance() if atmosphere and forces.get('drag') else None,
        'sampled_density_range_kg_m3':density_range if forces.get('drag') else None}
    scene=base('Numerical environment-coupled orbit experiment','ITRS',[t.isoformat() for t in output_times],scene_objects,source,
        warnings=['Numerical integration convergence does not establish orbit prediction accuracy.',
        'Atmospheric co-rotation is included when drag is enabled; neutral winds, maneuvers, tides, tesseral/sectoral gravity and thermal recoil are omitted.',
        'Solar pressure is a constant-area cannonball model with spherical Earth shadow, no lunar shadow or atmospheric limb effects. Resolve eclipse transitions with step-convergence tests.',
        'Schwarzschild is the leading spherical correction only; frame dragging, de Sitter precession and a complete relativistic time-scale treatment are omitted.',
        'J2 and optional Sun/Moon terms are Newtonian approximations. Spacecraft properties and initial-state quality determine model fidelity.',
        'No attitude, observation history or covariance supplied. Never mix TLE mean elements directly into this integrator.'])
    if any(code<0 or code==2 for code in provenance['eop_status_codes']):
        scene['warnings'].append('Earth orientation uses predicted or out-of-range data; inspect the recorded EOP status.')
    return scene,states


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--initial',type=Path,required=True)
    parser.add_argument('--space-weather',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.resolve() in {args.initial.resolve(),args.space_weather.resolve() if args.space_weather else args.initial.resolve()}:
        parser.error('Output must not overwrite input states or space-weather data')
    if args.initial.stat().st_size>16*1024*1024:parser.error('Initial experiment exceeds 16 MiB')
    value=json.loads(args.initial.read_text())
    atmosphere=MsisAtmosphere(SpaceWeather(args.space_weather)) if args.space_weather else None
    scene,_=integrate_experiment(value,atmosphere)
    scene['source']['initial_file_sha256']=hashlib.sha256(args.initial.read_bytes()).hexdigest()
    raw=json.dumps(scene,allow_nan=False,separators=(',',':')).encode()
    if len(raw)>64*1024*1024:parser.error('Numerical scene exceeds 64 MiB')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    temporary=args.output.with_suffix('.json.tmp');temporary.write_bytes(raw);temporary.replace(args.output)
    print(f'{args.output}: {len(scene["objects"])} objects, {len(scene["times"])} frames')


if __name__=='__main__':main()
