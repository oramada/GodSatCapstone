"""Reproduce sensitivity pairing/statistics and sampled physical policy actions."""

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))

import argparse
import csv
import json
from pathlib import Path

import numpy as np
import torch

from godsat.learning import Agent
from godsat.orbits import ROOT
from godsat.scenario import load, prepare
from godsat.sensorphysics import PhysicalTaskingEnv
from godsat.experiment import runtime_provenance, scenario_fingerprint
from scripts.validation.audit_physical_campaign import reconstruct_trace
from scripts.experiments.run_physical_sensitivity import METRICS, VARIANTS, sha


def audit(folder):
    folder=Path(folder).resolve();summary=json.loads((folder/'summary.json').read_text())
    if summary['status']!='completed_frozen_policy_physical_parameter_and_loss_sensitivity':raise ValueError('Incomplete sensitivity')
    if sha(folder/'responses.csv')!=summary['responses_sha256']:raise ValueError('Sensitivity responses changed')
    for relative,digest in summary['source_hashes'].items():
        if sha(ROOT/relative)!=digest:raise ValueError('Sensitivity source changed')
    if runtime_provenance()!=summary['runtime']:raise ValueError('Sensitivity runtime changed')
    with (folder/'responses.csv').open() as f:rows=list(csv.DictReader(f))
    dates=summary['dates'];config=summary['config'];seeds=config['validation_seeds']
    policies=['baseline','doe_recommended','bayesian_best']
    keys=[(r['date'],r['policy'],int(r['training_seed']),r['variant']) for r in rows]
    expected={(date,policy,seed,v[0]) for date in dates for policy in policies for seed in seeds for v in VARIANTS}
    if len(keys)!=len(expected) or set(keys)!=expected:raise ValueError('Missing or duplicate sensitivity cells')
    bykey=dict(zip(keys,rows));effects=summary['paired_effects'];interval_count=0
    for effect in effects:
        values=[]
        for date in dates:
            differences=[float(bykey[(date,effect['policy'],seed,effect['variant'])][effect['metric']])-
                         float(bykey[(date,effect['policy'],seed,'nominal')][effect['metric']]) for seed in seeds]
            values.append(sum(differences)/len(differences))
        if not np.allclose(values,effect['paired_date_effects'],rtol=1e-12,atol=1e-14) or not np.isclose(np.mean(values),effect['mean']):raise ValueError('Paired effects differ')
        # Alternate reconstruction: cumulative sums and per-draw full-block
        # sums plus a final partial block, instead of expanded sample indices.
        n=len(values);v=np.asarray(values)
        for text,reported in effect['circular_block_ci95'].items():
            block=int(text);rng=np.random.default_rng(effect['bootstrap_seed']+block)
            starts=rng.integers(0,n,(5000,int(np.ceil(n/block))))
            doubled=np.r_[v,v];sums=np.r_[0.,np.cumsum(doubled)]
            total=np.zeros(5000);remaining=n
            for column in range(starts.shape[1]):
                take=min(block,remaining);begin=starts[:,column]
                total+=sums[begin+take]-sums[begin];remaining-=take
            actual=np.quantile(total/n,[.025,.975])
            if not np.allclose(actual,reported,rtol=1e-10,atol=1e-12):raise ValueError('Temporal interval differs')
            interval_count+=1
    torch.set_num_threads(1);campaign=Path(summary['source_campaign']);replayed=0;scenarios=0
    source_models={}
    for di,date in enumerate(dates):
        scene=load(prepare(date,config,regime='leo'))
        if scenario_fingerprint({'test':[scene]})!=summary['scenario_sha256'][date]:raise ValueError('Scenario source changed')
        scenarios+=1
        if di not in [0,len(dates)//2,len(dates)-1]:continue
        for policy in policies:
            seed=seeds[0]
            if policy not in source_models:
                saved=torch.load(campaign/'models'/f'validate_{policy}_{seed}.pt',map_location='cpu',weights_only=True)
                model=Agent(saved['obs_dim'],saved['actions'],saved['hp']);model.load_state_dict(saved['state_dict'])
                source_models[policy]=(model,saved['hp'])
            model,hp=source_models[policy]
            for variant,patch,probability,mode in VARIANTS:
                row=bykey[(date,policy,seed,variant)];cfg={**config,**patch};sim_seed=int(row['simulation_seed'])
                env=PhysicalTaskingEnv(scene,cfg,hp['claim_resolution'],sim_seed,dropout_probability=probability,dropout_mode=mode)
                ob,mask=env.reset()
                for _ in range(env.steps):
                    with torch.no_grad():actions=model.distribution(torch.tensor(ob),torch.tensor(mask)).probs.argmax(-1).numpy()
                    (ob,mask),_,_=env.step(actions)
                actual=env.metrics()
                for metric in METRICS:
                    if not np.isclose(actual[metric],float(row[metric]),rtol=1e-11,atol=1e-13):raise ValueError('Sampled policy response differs')
                independent=reconstruct_trace(scene,cfg,sim_seed,env.trace,probability,mode)
                for metric in METRICS:
                    if not np.isclose(independent[metric],actual[metric],rtol=1e-11,atol=1e-13):raise ValueError('Independent physical/clutter response differs')
                replayed+=1
    for row in rows:
        if row['variant']=='no_clutter' and (float(row['false_track_rate'])!=0 or float(row['false_observations'])!=0):raise ValueError('False tracks without clutter')
    result={'status':'passed_source_response_and_parameter_sensitivity_reproduction',
            'summary_sha256':sha(folder/'summary.json'),'responses_sha256':sha(folder/'responses.csv'),
            'response_rows_checked':len(rows),'source_scenarios_checked':scenarios,
            'paired_effect_vectors_checked':len(effects),'temporal_intervals_checked':interval_count,
            'sampled_policy_and_independent_physical_action_replays':replayed,
            'scope':'Full source/response grid and reported-statistic reproduction; first/middle/last dates, first training seed for each policy and all variants independently reconstruct actions/physics. Other policies/dates are not all action-replayed. Parameters remain authorized assumptions.'}
    (folder/'independent_audit.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',type=Path,default=ROOT/'outputs/physical-sensor-sensitivity-20261025')
    args=p.parse_args();print(json.dumps(audit(args.input),indent=2))
