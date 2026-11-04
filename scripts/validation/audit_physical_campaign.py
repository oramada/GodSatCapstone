"""Audit actual physical-response campaigns and independently reconstruct action metrics."""
from __future__ import annotations

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))


import argparse
import csv
import hashlib
import json
from pathlib import Path

import numpy as np
import torch
from scipy.stats import t

from godsat.experiment import runtime_provenance, scenario_fingerprint
from godsat.learning import Agent, evaluate
from godsat.orbits import EARTH_RADIUS, ROOT
from godsat.scenario import load, prepare
from scripts.validation.audit_campaign import audit as audit_structure


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def reconstruct_trace(scenario, config, seed, trace, probability=0., mode='independent'):
    """Rebuild accepted looks, motion work and true/false track slots from actions.

    No call to TaskingEnv, PhysicalTaskingEnv or slew_profile in this calculation.
    """
    agents=int(scenario['agents']);targets=len(scenario['ids'])-agents
    steps=len(scenario['times'])-1;dt=config['step_seconds']
    streams=np.random.SeedSequence(seed).spawn(6)
    priority=np.random.default_rng(streams[1])
    detection=np.random.default_rng(streams[2]).random((steps,agents,targets))
    losses=np.random.default_rng(streams[3]).random((steps,agents,targets))
    burst=np.random.default_rng(streams[4]).random(agents)<probability
    transitions=np.random.default_rng(streams[5]).random((steps,agents))
    clutter=np.random.default_rng(np.random.SeedSequence([seed,502183])).random((steps,agents,targets))
    ground=config.get('scenario_kind')=='ground_tracks_iridium_next_v1'
    pointing=scenario['ground_up'][0].copy() if ground else np.tile([1.,0.,0.],(agents,1))
    true_seen=np.full(targets,-np.inf);reported_seen=true_seen.copy()
    latest_false=np.zeros(targets,bool)
    false_slots=reported_slots=false_obs=reported_obs=0
    energies=[];custody=[]
    inertia=config['gimbal_inertia_kg_m2'];torque=config['gimbal_max_torque_nm']
    rate=np.deg2rad(config['slew_rate_deg_s']);acceleration=torque/inertia
    for index,record in enumerate(trace):
        if ground and index:
            rotation=scenario['itrs_to_teme'][index] @ scenario['itrs_to_teme'][index-1].T
            pointing=pointing @ rotation.T
        if mode=='burst' and index>0:
            persistence=config.get('dropout_burst_persistence',.8)
            entry=probability*(1-persistence)/max(1-probability,1e-12)
            burst=np.where(burst,transitions[index]<persistence,transitions[index]<entry)
        xyz=scenario['states'][index,:,:3]
        delta=xyz[None,agents:]-xyz[:agents,None]
        distance=np.linalg.norm(delta,axis=-1)
        directions=delta/np.maximum(distance[...,None],1e-9)
        angle=np.arccos(np.clip(np.sum(directions*pointing[:,None],axis=-1),-1,1))
        fraction=np.clip(-np.sum(xyz[:agents,None]*delta,axis=-1)/np.maximum(distance**2,1e-12),0,1)
        nearest=xyz[:agents,None]+fraction[...,None]*delta
        outward=xyz[:agents]/np.maximum(np.linalg.norm(xyz[:agents],axis=-1)[:,None],1)
        mount=np.arccos(np.clip(np.sum(directions*outward[:,None],axis=-1),-1,1))
        visible=(np.isfinite(directions).all(axis=-1)&(np.linalg.norm(nearest,axis=-1)>EARTH_RADIUS+20)&
                 (distance<=config['max_range_km'])&(distance>1))
        if ground:
            elevation=np.sum(directions*scenario['ground_up'][index,:,None],axis=-1)
            visible=(np.isfinite(directions).all(axis=-1)&(distance<=config['max_range_km'])&
                     (distance>1)&(elevation>=np.sin(np.deg2rad(config['ground_min_elevation_deg']))))
            mount=np.arccos(np.clip(elevation,-1,1))
        peak=np.minimum(np.sqrt(angle*acceleration),rate)
        ramp=peak/acceleration
        cruise=np.maximum(0,(angle-peak*ramp)/rate)
        duration=2*ramp+cruise
        allowed=visible&(angle<=rate*dt)&(duration<=dt+1e-10)&(mount<=np.deg2rad(config['field_of_regard_deg']))
        claimed=set();true=[];false=[];joules=0.
        for host in priority.permutation(agents):
            target=int(record['actions'][host])
            if target==targets or target in claimed or not allowed[host,target]:continue
            claimed.add(target);pointing[host]=np.nan_to_num(directions[host,target])
            # Independent integration of constant-torque acceleration work.
            acceleration_distance=.5*acceleration*ramp[host,target]**2
            work=torque*acceleration_distance/config['gimbal_efficiency']
            joules+=work+config['gimbal_drive_power_watts']*duration[host,target]
            detection_probability=np.clip(config['detection_probability']-
                config['range_detection_penalty']*distance[host,target]/config['max_range_km']-
                config['stale_detection_penalty']*scenario['ages'][index,agents+target]/config['max_element_age_hours'],0,1)
            dropped=bool(burst[host]) if mode=='burst' else losses[index,host,target]<probability
            if detection[index,host,target]<detection_probability and not dropped:true.append(target)
            elif not dropped and clutter[index,host,target]<config['false_association_probability_per_missed_look']:false.append(target)
        if sorted(true)!=sorted(record['detected']) or sorted(false)!=sorted(record['false_observations']):
            raise ValueError('Independent detection/clutter draws differ from action trace')
        if not np.isclose(joules/agents,record['slew_energy_joules_mean'],rtol=1e-11,atol=1e-13):
            raise ValueError('Independent torque-work integration differs from action trace')
        true_seen[true]=index*dt
        reported_seen[true]=index*dt;reported_seen[false]=index*dt
        latest_false[true]=False;latest_false[false]=True
        valid=np.isfinite(xyz[agents:,0])
        active=valid&((index*dt-reported_seen)<=config['custody_seconds'])
        false_active=active&latest_false
        false_slots+=int(false_active.sum());reported_slots+=int(active.sum())
        false_obs+=len(false);reported_obs+=len(true)+len(false)
        value=float(((index*dt-true_seen)<=config['custody_seconds'])[valid].mean()) if valid.any() else 0.
        if not np.isclose(value,record['custody'],atol=1e-14):
            raise ValueError('Clutter contaminated true custody or independent custody differs')
        energies.append(joules/agents);custody.append(value)
    return {'slew_energy_joules':float(np.mean(energies)),
            'custody_continuity':float(np.mean(custody)),
            'false_track_rate':false_slots/max(reported_slots,1),
            'false_observation_rate':false_obs/max(reported_obs,1)}


def audit(folder):
    torch.set_num_threads(1)
    folder=Path(folder).resolve();sources={}
    def read(path):
        sources[str(path.relative_to(ROOT))]=sha(path)
        return json.loads(path.read_text())
    structure=audit_structure(folder)
    config=read(folder/'config.json');summary=read(folder/'summary.json')
    if config['sensor_response_model']!='assumed_gimbal_and_clutter_v1':raise ValueError('Wrong sensor model')
    scenes={split:[load(prepare(date,config,regime=regime)) for date in config[split+'_dates']
                   for regime in config.get(split+'_regimes',['leo'])] for split in ['training','validation','test']}
    scenes['train']=scenes.pop('training')
    if scenario_fingerprint(scenes)!=summary['scenario_sha256']:raise ValueError('Source arrays changed')
    metrics=['objective','custody_continuity','slew_energy_proxy','false_track_proxy']+config['additional_responses']
    replayed_runs=0;action_traces=0
    for path in sorted((folder/'runs').glob('*.json')):
        r=read(path)
        if r['runtime']!=runtime_provenance():raise ValueError('Campaign runtime/source changed')
        checkpoint=folder/'models'/(r['name']+'.pt');sources[str(checkpoint.relative_to(ROOT))]=sha(checkpoint)
        saved=torch.load(checkpoint,map_location='cpu',weights_only=True)
        model=Agent(saved['obs_dim'],saved['actions'],saved['hp']);model.load_state_dict(saved['state_dict'])
        actual,_,_=evaluate(model,scenes['validation'],config,saved['hp'],9001)
        for metric in metrics:
            if not np.isclose(actual[metric],r[metric],rtol=1e-11,atol=1e-13):raise ValueError(f'{r["name"]}: {metric} selection response differs')
        if not np.isclose(r['assumed_host_energy_kwh'],r['wall_seconds']*config['assumed_host_power_watts']/3.6e6):raise ValueError('Assumed host energy arithmetic differs')
        replayed_runs+=1
    with (folder/'validation.csv').open() as f:validation=list(csv.DictReader(f))
    sources[str((folder/'validation.csv').relative_to(ROOT))]=sha(folder/'validation.csv')
    for row in validation:
        label=row['configuration'];seed=int(row['seed'])
        hp=summary['comparison_configurations'].get(label,config['baseline']);model=None
        if label in summary['comparison_configurations']:
            saved=torch.load(folder/'models'/f'validate_{label}_{seed}.pt',map_location='cpu',weights_only=True)
            model=Agent(saved['obs_dim'],saved['actions'],saved['hp']);model.load_state_dict(saved['state_dict'])
        actual,traces,_=evaluate(model,scenes['test'],config,hp,seed+50000,
                                 policy='learned' if model is not None else label,traces=True)
        for metric in metrics:
            if not np.isclose(actual[metric],float(row[metric]),rtol=1e-11,atol=1e-13):raise ValueError('Held-out response differs')
        independent=[]
        for index,(scene,trace) in enumerate(zip(scenes['test'],traces)):
            independent.append(reconstruct_trace(scene,config,seed+50000+index*1009,trace));action_traces+=1
        for metric in independent[0]:
            if not np.isclose(np.mean([r[metric] for r in independent]),actual[metric],rtol=1e-11,atol=1e-13):raise ValueError('Independent action metrics differ')
    for label,values in summary['test_summary'].items():
        rows=[r for r in validation if r['configuration']==label]
        for metric in metrics:
            v=np.array([float(r[metric]) for r in rows]);half=float(t.ppf(.975,len(v)-1)*v.std(ddof=1)/np.sqrt(len(v)))
            if not np.isclose(v.mean(),values[metric]['mean']) or not np.isclose(half,values[metric]['ci95_half_width']):raise ValueError('Reported five-seed interval differs')
    result={'status':'passed_all_checkpoint_selection_and_heldout_physical_replays',
            'summary_sha256':sha(folder/'summary.json'),'source_hashes':sources,
            'checkpoint_selection_responses_replayed':replayed_runs,'heldout_response_rows_replayed':len(validation),
            'independent_action_traces_reconstructed':action_traces,
            'independent_quantities':['accepted looks','torque-work slew joules','nominal detection draws','clutter draws','true custody','false track slots','false observation counts'],
            'structure_audit':structure['status'],'calibrated_sensor_or_host_energy':False,
            'limitations':'All saved checkpoint selection responses and held-out action responses replayed. This is not retraining every policy or validating the assumed sensor parameters against hardware.'}
    (folder/'independent_physical_audit.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',type=Path,required=True)
    args=p.parse_args();result=audit(args.input)
    print(json.dumps({k:v for k,v in result.items() if k!='source_hashes'}))
