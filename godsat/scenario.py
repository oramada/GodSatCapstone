import datetime as dt
import csv
import hashlib
import json
import pathlib
import numpy as np
from .orbits import (ROOT, EARTH_RADIUS, History, satellite, julian, utc,
                     orbit_regime, teme_to_gcrs, awp_propagate)

def line_of_sight(a,b):
    delta=b-a
    denom=np.sum(delta*delta,axis=-1)
    f=np.clip(-np.sum(a*delta,axis=-1)/np.maximum(denom,1e-12),0,1)
    nearest=a+f[...,None]*delta
    return np.linalg.norm(nearest,axis=-1)>EARTH_RADIUS+20

def cache_key(date,config,regime='leo'):
    fields={k:config[k] for k in ['agents','targets','duration_minutes','step_seconds','max_element_age_hours','max_range_km']}
    fields.update(date=date,regime=regime,
                  sensor_cohort=config.get('sensor_cohort','current_payload'),
                  target_cohort=config.get('target_cohort','current_payload'),
                  allow_non_payload_sensor_hosts=bool(config.get('allow_non_payload_sensor_hosts',False)),
                  propagation_model=config.get('propagation_model','sgp4'),
                  version=5)
    if str(fields['propagation_model']).startswith('awp_'):
        # Invalidate only numerical AWP caches after changing its force model.
        fields['awp_force_model_version']=2
    return hashlib.sha256(json.dumps(fields,sort_keys=True).encode()).hexdigest()[:16]

def replay_with_awp_model(states, source_epochs, times, step_seconds, *, third_bodies=False):
    """Replace valid TEME SGP4 segments with an AWP numerical force model.

    Each new historical element epoch starts a new short propagation arc from
    the corresponding SGP4 state. Missing or failed source samples remain
    missing; AWP does not bridge gaps or invent source observations.
    """
    states=np.asarray(states,dtype=float)
    epochs=np.asarray(source_epochs)
    if states.ndim!=3 or states.shape[2]!=6 or epochs.shape!=states.shape[:2]:
        raise ValueError('states and source epochs must have matching (time, object[, six-state]) shapes')
    if len(times)!=states.shape[0] or step_seconds<=0:
        raise ValueError('times and positive step_seconds must match the state timeline')
    normalized_times=[utc(value) for value in times]
    if any((right-left).total_seconds()!=float(step_seconds)
           for left,right in zip(normalized_times,normalized_times[1:])):
        raise ValueError('AWP replay times must be strictly spaced by step_seconds')
    result=np.full_like(states,np.nan)
    for object_index in range(states.shape[1]):
        index=0
        while index<len(times):
            if not np.isfinite(states[index,object_index]).all() or not str(epochs[index,object_index]):
                index+=1
                continue
            source_epoch=str(epochs[index,object_index])
            end=index+1
            while (end<len(times)
                   and np.isfinite(states[end,object_index]).all()
                   and str(epochs[end,object_index])==source_epoch):
                end+=1
            start_time=normalized_times[index]
            initial=teme_to_gcrs(states[index,object_index],start_time)
            offsets=np.arange(end-index,dtype=float)*float(step_seconds)
            if len(offsets)==1:
                # A single sample at a new element epoch is only a frame
                # conversion; solve_ivp has no positive integration interval.
                propagated=initial[None,:]
            else:
                propagated=awp_propagate(initial,offsets[-1],offsets,j2=True,drag=False,
                    third_bodies=third_bodies,epoch=start_time if third_bodies else None)
            result[index:end,object_index]=propagated
            index=end
    return result

def replay_with_awp_j2(states, source_epochs, times, step_seconds):
    """Replay arcs with central gravity and Earth's J2 term."""
    return replay_with_awp_model(states,source_epochs,times,step_seconds)

def replay_with_awp_j2_sun_moon(states, source_epochs, times, step_seconds):
    """Replay arcs with J2 and date-specific solar/lunar point-mass gravity."""
    return replay_with_awp_model(states,source_epochs,times,step_seconds,third_bodies=True)


def _cache_is_cloud_placeholder(path):
    """Return true for macOS File Provider placeholders that contain no bytes."""
    if not hasattr(pathlib.Path(path).stat(), 'st_flags'):
        return False
    # Darwin's UF_DATALESS flag marks an evicted iCloud/File Provider item.
    return bool(pathlib.Path(path).stat().st_flags & 0x40000000)

def prepare(date,config,root=ROOT,regime='leo'):
    if regime not in {'leo','meo','geo','heo','all'}: raise ValueError('regime must be leo, meo, geo, heo, or all')
    propagation_model=config.get('propagation_model','sgp4')
    if propagation_model not in {'sgp4','awp_j2','awp_j2_sun_moon'}:
        raise ValueError('propagation_model must be sgp4, awp_j2, or awp_j2_sun_moon')
    if (config.get('sensor_cohort','current_payload')=='all'
            and not config.get('allow_non_payload_sensor_hosts',False)):
        raise ValueError('Using debris or rocket bodies as hypothetical sensor hosts requires allow_non_payload_sensor_hosts=true')
    root=pathlib.Path(root);folder=root/'data/scenarios';folder.mkdir(parents=True,exist_ok=True)
    path=folder/(cache_key(date,config,regime)+'.npz')
    metadata_path=path.with_suffix('.json')
    if path.exists() and _cache_is_cloud_placeholder(path):
        # Cached scenarios are deterministic products of the local source
        # history. Remove only the empty local placeholder and rebuild it so a
        # long batch does not block or fail while iCloud tries to hydrate it.
        path.unlink()
        metadata_path.unlink(missing_ok=True)
    if path.exists() and metadata_path.is_file(): return path
    if path.exists():
        # The array and provenance metadata are one cache unit. An orphaned
        # array cannot safely satisfy host selection or downstream audits.
        path.unlink()
    start=utc(date)
    sensor_cohort=config.get('sensor_cohort','current_payload')
    target_cohort=config.get('target_cohort','current_payload')
    sensor_history=History(root,sensor_cohort)
    target_history=sensor_history if target_cohort==sensor_cohort else History(root,target_cohort)
    def eligible(history):
        positions=[];identifiers=[]
        for row in history.snapshot(start,config['max_element_age_hours']):
            if regime!='all' and orbit_regime(row)!=regime: continue
            err,p,v=satellite(row).sgp4(*julian(start))
            altitude=np.linalg.norm(p)-EARTH_RADIUS
            if err==0 and np.isfinite(p+v).all() and 150<altitude<60000:
                positions.append(p);identifiers.append(int(row['norad_id']))
        return np.asarray(positions),np.asarray(identifiers,dtype=np.int32)
    try:
        sensor_pos,sensor_ids=eligible(sensor_history)
        target_pos,target_ids=eligible(target_history)
    finally:
        sensor_history.db.close()
        if target_history is not sensor_history: target_history.db.close()
    n_agents,n_targets=config['agents'],config['targets']
    if len(sensor_ids)<n_agents or len(target_ids)<n_targets:
        raise ValueError(f'Insufficient fresh objects for {regime}: {len(sensor_ids)} sensor candidates, {len(target_ids)} target candidates')
    # Select a dense observable cluster of payload sensor hosts and all-catalog
    # targets. Debris and rocket bodies can be targets, never assumed to be sensors.
    candidates=np.linspace(0,len(sensor_ids)-1,min(256,len(sensor_ids)),dtype=int)
    distances=np.linalg.norm(sensor_pos[candidates,None,:]-target_pos[None,:,:],axis=-1)
    visible=line_of_sight(sensor_pos[candidates,None,:],target_pos[None,:,:])&(distances<config['max_range_km'])&(distances>1)
    anchor=candidates[np.argmax(visible.sum(axis=1))]
    sensor_order=np.argsort(np.linalg.norm(sensor_pos-sensor_pos[anchor],axis=1),kind='stable')
    agent_indices=sensor_order[:n_agents]
    ap=sensor_pos[agent_indices,None,:];tp=target_pos[None,:,:]
    target_ranges=np.linalg.norm(tp-ap,axis=-1)
    quality=(line_of_sight(ap,tp)&(target_ranges<config['max_range_km'])&(target_ranges>1)).sum(axis=0)
    quality[np.isin(target_ids,sensor_ids[agent_indices])]=0
    observable_targets=np.flatnonzero(quality>0)
    if len(observable_targets)<n_targets:
        raise ValueError(f'Only {len(observable_targets)} all-catalog targets are observable in the {regime} scenario; need {n_targets}')
    target_indices=observable_targets[np.argsort(-quality[observable_targets],kind='stable')[:n_targets]]
    selected=np.r_[sensor_ids[agent_indices],target_ids[target_indices]]
    steps=int(config['duration_minutes']*60/config['step_seconds'])
    if steps<2: raise ValueError('Scenario must have at least two steps')
    times=[start+dt.timedelta(seconds=i*config['step_seconds']) for i in range(steps+1)]
    replay_history=History(root,target_cohort)
    try:
        replay,ages,errors,epochs=replay_history.replay(selected,times,config['max_element_age_hours'])
    finally:
        replay_history.db.close()
    if propagation_model=='awp_j2':
        replay=replay_with_awp_j2(replay,epochs,times,config['step_seconds'])
    elif propagation_model=='awp_j2_sun_moon':
        replay=replay_with_awp_j2_sun_moon(replay,epochs,times,config['step_seconds'])
    np.savez_compressed(path,states=replay,ages=ages,errors=errors,source_epochs=epochs,
        ids=selected,times=np.array([t.isoformat() for t in times]),agents=n_agents)
    object_types={};ops_status={}
    satcat=root/'data/raw/satcat.csv'
    if satcat.exists():
        selected_set=set(map(int,selected))
        with satcat.open(newline='') as f:
            for item in csv.DictReader(f):
                try: oid=int(item['NORAD_CAT_ID'])
                except (KeyError,TypeError,ValueError): continue
                if oid in selected_set:
                    object_types[str(oid)]=item.get('OBJECT_TYPE') or 'unknown'
                    ops_status[str(oid)]=item.get('OPS_STATUS_CODE') or 'unknown'
    metadata={'date':date,'orbit_regime':regime,'agents':selected[:n_agents].tolist(),'targets':selected[n_agents:].tolist(),
        'object_types':[object_types.get(str(int(oid)),'unknown') for oid in selected],
        'ops_status_codes':[ops_status.get(str(int(oid)),'unknown') for oid in selected],
        'valid_fraction':float(np.isfinite(replay[:,:,0]).mean()),
        'frame':'GCRS' if propagation_model.startswith('awp_') else 'TEME',
        'propagation_model':({'awp_j2':'AWP Spacecraft two-body + J2, reset from each available historical SGP4 element update',
                              'awp_j2_sun_moon':'AWP Spacecraft two-body + J2 + solar/lunar point-mass gravity using DE432s, reset from each available historical SGP4 element update'}
                             .get(propagation_model,'SGP4 WGS-72 from historical elements')),
        'max_age_hours':config['max_element_age_hours'],'sensor_cohort':sensor_cohort,'target_cohort':target_cohort,
        'selection':f'dense observable {regime.upper()} cluster; {sensor_cohort} sensor-host cohort (non-payload allowed={bool(config.get("allow_non_payload_sensor_hosts",False))}) and {target_cohort} target candidates',
        'source':{'current_payload':'data/current_payload_orbit_history.parquet',
                  'current_active_payload':'data/current_active_payload_orbit_history.parquet',
                  'all':'data/raw/tle_*.parquet'},
        'sensor_host_status_interpretation':(
            'Current active-GP/SATCAT snapshot backcast through the archive; does not establish historical operating status.'
            if sensor_cohort=='current_active_payload' else None),
        'config_key':cache_key(date,config,regime)}
    metadata_path.write_text(json.dumps(metadata,indent=2))
    return path

def load(path):
    with np.load(path,allow_pickle=False) as data: return {k:data[k] for k in data.files}
