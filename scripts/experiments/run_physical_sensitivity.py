"""Frozen-policy assumed-hardware/clutter and loss-process sensitivity on quarterly dates."""
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

from godsat.dropout import evaluate_policy, quarterly_dates
from godsat.experiment import runtime_provenance, scenario_fingerprint, write_json
from godsat.learning import Agent
from godsat.orbits import ROOT
from godsat.scenario import load, prepare

VARIANTS = [
    ('nominal',{},0.,'independent'),
    ('no_clutter',{'false_association_probability_per_missed_look':0.},0.,'independent'),
    ('high_clutter',{'false_association_probability_per_missed_look':.02},0.,'independent'),
    ('low_inertia',{'gimbal_inertia_kg_m2':.5},0.,'independent'),
    ('high_inertia',{'gimbal_inertia_kg_m2':4.},0.,'independent'),
    ('no_drive_power',{'gimbal_drive_power_watts':0.},0.,'independent'),
    ('high_drive_power',{'gimbal_drive_power_watts':.1},0.,'independent'),
    ('independent_loss_20pct',{},.2,'independent'),
    ('burst_loss_20pct',{},.2,'burst'),
]
METRICS=['custody_continuity','slew_energy_joules','false_track_rate']


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def intervals(values,seed,draws=5000):
    values=np.asarray(values);n=len(values);result={}
    for block in [1,3,6]:
        rng=np.random.default_rng(seed+block)
        starts=rng.integers(0,n,(draws,int(np.ceil(n/block))))
        indices=((starts[:,:,None]+np.arange(block))%n).reshape(draws,-1)[:,:n]
        result[str(block)]=np.quantile(values[indices].mean(axis=1),[.025,.975]).tolist()
    return result


def summarize(rows,dates):
    effects=[]
    policies=['baseline','doe_recommended','bayesian_best']
    for pi,policy in enumerate(policies):
        for vi,(variant,_,_,_) in enumerate(VARIANTS[1:],1):
            for mi,metric in enumerate(METRICS):
                values=[]
                for date in dates:
                    left={int(r['training_seed']):float(r[metric]) for r in rows if r['date']==date and r['policy']==policy and r['variant']==variant}
                    right={int(r['training_seed']):float(r[metric]) for r in rows if r['date']==date and r['policy']==policy and r['variant']=='nominal'}
                    if set(left)!=set(right) or len(left)!=5:raise ValueError('Unpaired five-seed sensitivity')
                    values.append(float(np.mean([left[s]-right[s] for s in sorted(left)])))
                seed=5065+vi*101+pi*17+mi
                effects.append({'policy':policy,'variant':variant,'metric':metric,'paired_date_effects':values,
                                'mean':float(np.mean(values)),'bootstrap_seed':seed,
                                'circular_block_ci95':intervals(values,seed)})
    return effects


def run(campaign,output):
    campaign=Path(campaign).resolve();output=Path(output).resolve();output.mkdir(parents=True,exist_ok=True)
    config=json.loads((campaign/'config.json').read_text())
    if config['sensor_response_model']!='assumed_gimbal_and_clutter_v1':raise ValueError('Physical campaign required')
    audit_path=campaign/'independent_physical_audit.json'
    if not audit_path.exists() or json.loads(audit_path.read_text())['status']!='passed_all_checkpoint_selection_and_heldout_physical_replays':raise ValueError('Complete physical campaign audit required')
    source_hashes={str(p.relative_to(ROOT)):sha(p) for p in [campaign/'config.json',campaign/'summary.json',audit_path]}
    torch.set_num_threads(1);models={}
    for policy in ['baseline','doe_recommended','bayesian_best']:
        for seed in config['validation_seeds']:
            path=campaign/'models'/f'validate_{policy}_{seed}.pt'
            source_hashes[str(path.relative_to(ROOT))]=sha(path)
            saved=torch.load(path,map_location='cpu',weights_only=True)
            model=Agent(saved['obs_dim'],saved['actions'],saved['hp']);model.load_state_dict(saved['state_dict'])
            models[(policy,seed)]=(model,saved['hp'])
    dates=quarterly_dates();runtime=runtime_provenance();rows=[];scenarios={}
    signature=hashlib.sha256(json.dumps({'config':config,'sources':source_hashes,'variants':VARIANTS,'dates':dates,'runtime':runtime},sort_keys=True).encode()).hexdigest()
    for di,date in enumerate(dates):
        scene=load(prepare(date,config,regime='leo'));scenarios[date]=scenario_fingerprint({'test':[scene]})
        path=output/f'cell-{di:02d}.json'
        if path.exists():
            cell=json.loads(path.read_text())
            if cell['signature']!=signature or cell['scenario_sha256']!=scenarios[date]:raise ValueError('Sensitivity resume source changed')
            cell_rows=cell['rows']
        else:
            cell_rows=[]
            for (policy,seed),(model,hp) in models.items():
                sim_seed=7441+di*1009+int(seed)*17
                for variant,patch,probability,mode in VARIANTS:
                    result=evaluate_policy(model,scene,{**config,**patch},hp,sim_seed,probability,mode)
                    cell_rows.append({'date':date,'policy':policy,'training_seed':seed,'simulation_seed':sim_seed,'variant':variant,**result})
            write_json(path,{'signature':signature,'scenario_sha256':scenarios[date],'rows':cell_rows})
        rows.extend(cell_rows)
        write_json(output/'progress.json',{'status':'running','dates_completed':di+1,'dates_planned':len(dates),'response_rows':len(rows),'signature':signature})
        print(f'{di+1}/{len(dates)} dates: {len(rows)} responses',flush=True)
    with (output/'responses.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    effects=summarize(rows,dates)
    result={'status':'completed_frozen_policy_physical_parameter_and_loss_sensitivity','signature':signature,
            'source_hashes':source_hashes,'runtime':runtime,'source_campaign':str(campaign),'config':config,
            'dates':dates,'scenario_sha256':scenarios,'variants':VARIANTS,'response_rows':len(rows),
            'responses_sha256':sha(output/'responses.csv'),'paired_effects':effects,
            'scope':'LEO, 18-target frozen policies; assumptions varied without retraining. Five model seeds averaged within each of 17 dates before pointwise 1/3/6 sampled-date block intervals. Quarterly dates are temporally correlated and intervals condition on this assumed model. This is separate from original four-regime proxy-model studies.'}
    write_json(output/'summary.json',result)
    write_json(output/'progress.json',{'status':'completed','dates_completed':len(dates),'response_rows':len(rows),'signature':signature})
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--campaign',type=Path,default=ROOT/'outputs/governing-design-physical-leo-20261025')
    p.add_argument('--output',type=Path,default=ROOT/'outputs/physical-sensor-sensitivity-20261025')
    args=p.parse_args();result=run(args.campaign,args.output)
    print(json.dumps({'status':result['status'],'rows':result['response_rows']}))
