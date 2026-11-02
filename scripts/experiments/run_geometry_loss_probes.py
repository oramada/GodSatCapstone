"""Paired single-observation suppression probes stratified by pre-loss geometry."""
from __future__ import annotations

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))


import argparse
from collections import defaultdict
import copy
import csv
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.stats import t
import torch

from godsat.environment import TaskingEnv
from godsat.learning import Agent
from godsat.orbits import ROOT
from godsat.scenario import load, prepare
from scripts.experiments.run_dropout_campaign import sha256

METRICS = ('custody_continuity','observable_custody','slew_energy_proxy','objective')


def geometry_group(distance_km, slew_deg):
    if not np.isfinite([distance_km,slew_deg]).all() or distance_km <= 0 or slew_deg < 0:
        raise ValueError('Invalid observation geometry')
    return int(np.searchsorted([2000.,4000.],distance_km,side='right')), int(np.searchsorted([40.,80.],slew_deg,side='right'))


def action_for(model,obs,mask):
    with torch.no_grad():
        return model.distribution(torch.tensor(obs),torch.tensor(mask)).probs.argmax(-1).numpy()


def episode(model,scenario,config,hp,seed,forced=None,baseline=None):
    env=TaskingEnv(scenario,config,hp['claim_resolution'],seed)
    obs,mask=env.reset()
    events=[]
    for step in range(env.steps):
        action=action_for(model,obs,mask)
        _,ranges,angles,_,allowed=env.geometry()
        priority=copy.deepcopy(env.priority_rng).permutation(env.a)
        if forced is not None and step <= forced['step']:
            if action.tolist() != baseline['actions'][step]:
                raise ValueError('Counterfactual diverged before the forced observation')
        if forced is not None and step == forced['step']:
            i,j=forced['agent'],forced['target']
            if action[i] != j or not allowed[i,j]:
                raise ValueError('Forced baseline observation is no longer eligible')
            # A draw of one suppresses this observation for every probability
            # allowed by the simulator. Other draws and priority remain paired.
            env.detection_uniforms[step,i,j]=1.
        (obs,mask),_,_=env.step(action)
        observed=set(env.trace[-1]['detected'])
        if forced is not None and step == forced['step']:
            expected=set(baseline['detected'][step])-{forced['target']}
            if observed != expected:
                raise ValueError('Forced step did not remove exactly one successful observation')
        if forced is None:
            claimed=set()
            for i in priority:
                j=int(action[i])
                if j == env.k or not allowed[i,j] or j in claimed:
                    continue
                claimed.add(j)
                if j not in observed:
                    continue
                distance,slew=float(ranges[i,j]),float(np.rad2deg(angles[i,j]))
                group=geometry_group(distance,slew)
                events.append({'step':step,'agent':int(i),'target':j,
                    'host_id':int(scenario['ids'][i]),'target_id':int(scenario['ids'][env.a+j]),
                    'range_km':distance,'slew_deg':slew,'range_bin':group[0],'slew_bin':group[1]})
    return {'metrics':env.metrics(),'events':events,
            'actions':[item['actions'] for item in env.trace],
            'detected':[item['detected'] for item in env.trace]}


def probe_model(model,scenario,config,hp,seed,selection_seed):
    baseline=episode(model,scenario,config,hp,seed)
    groups=defaultdict(list)
    for event in baseline['events']:
        groups[event['range_bin'],event['slew_bin']].append(event)
    rng=np.random.default_rng(selection_seed)
    probes=[]
    for key,events in sorted(groups.items()):
        event=events[int(rng.integers(len(events)))]
        counter=episode(model,scenario,config,hp,seed,forced=event,baseline=baseline)
        probes.append({**event,'eligible_successes_in_joint_bin':len(events),
            'counterfactual_metrics':counter['metrics'],
            'changes':{metric:counter['metrics'][metric]-baseline['metrics'][metric] for metric in METRICS}})
    return {'baseline_metrics':baseline['metrics'],'baseline_successful_observations':len(baseline['events']),
            'baseline_actions':baseline['actions'],'baseline_detected':baseline['detected'],'probes':probes}


def summarize(cells):
    grouped=defaultdict(lambda:defaultdict(list))
    rows=[]
    for cell in cells:
        for model in cell['models']:
            for probe in model['probes']:
                key=cell['regime'],probe['range_bin'],probe['slew_bin']
                grouped[key][cell['date']].append(probe['changes'])
                rows.append({'date':cell['date'],'regime':cell['regime'],'model_seed':model['model_seed'],
                    **{k:v for k,v in probe.items() if k not in ('counterfactual_metrics','changes')},
                    **{f'{metric}_change':value for metric,value in probe['changes'].items()}})
    result=[]
    for (regime,range_bin,slew_bin),by_date in sorted(grouped.items()):
        item={'regime':regime,'range_bin':range_bin,'slew_bin':slew_bin,'dates':len(by_date),
              'probes':sum(map(len,by_date.values())),'metrics':{}}
        for metric in METRICS:
            means=np.asarray([np.mean([row[metric] for row in values]) for _,values in sorted(by_date.items())])
            half=float(t.ppf(.975,len(means)-1)*means.std(ddof=1)/np.sqrt(len(means))) if len(means)>1 else None
            item['metrics'][metric]={'mean_date_change':float(means.mean()),
                'date_cluster_ci95':None if half is None else [float(means.mean()-half),float(means.mean()+half)]}
        result.append(item)
    return result,rows


def execute(source,campaign,output):
    source,campaign,output=map(lambda p:Path(p).resolve(),(source,campaign,output))
    original=json.loads((source/'dropout_design.json').read_text())['design']
    bound=original['config']['dropout_input_provenance']
    config=original['config'];seeds=original['model_seeds']
    if sha256(campaign/'config.json') != bound['campaign_config_sha256'] or sha256(campaign/'summary.json') != bound['campaign_summary_sha256']:
        raise ValueError('Learning campaign changed from the bound dropout design')
    for seed in seeds:
        if sha256(campaign/'models'/f'validate_doe_recommended_{seed}.pt') != bound['checkpoints_sha256'][str(seed)]:
            raise ValueError('Frozen model checkpoint changed')
    design={'schema':1,'source_dropout_design_sha256':sha256(source/'dropout_design.json'),
        'code_sha256':sha256(Path(__file__)),'core_code_sha256':{p:sha256(ROOT/p) for p in ['godsat/environment.py','godsat/learning.py','godsat/scenario.py','godsat/orbits.py']},
        'dates':original['dates'],'regimes':original['regimes'],'model_seeds':seeds,'simulation_seed':7441,
        'config':config,'range_edges_km':[0,2000,4000,6000],'slew_edges_deg':[0,40,80,120],
        'selection':'One uniformly chosen successful zero-outage observation per occupied range/slew joint bin, per episode and frozen checkpoint. Selection RNG is independent of environmental draws.',
        'intervention':'Suppress exactly that one otherwise successful observation via its detection draw, then continue the frozen adaptive policy with paired draws. This is a conditional single-loss probe, not a dropout-rate experiment.',
        'scope':'Exploratory simulation sensitivity on quarterly historical scenes, including training dates; not independent held-out validation, hardware effectiveness, or the missing PDF protocol.'}
    signature=hashlib.sha256(json.dumps(design,sort_keys=True).encode()).hexdigest()
    output.mkdir(parents=True,exist_ok=True)
    path=output/'geometry_design.json'
    if path.exists() and json.loads(path.read_text())['signature'] != signature:
        raise ValueError('Output contains a different geometry design')
    path.write_text(json.dumps({'signature':signature,'design':design},indent=2)+'\n')
    torch.set_num_threads(1)
    models={}
    for seed in seeds:
        checkpoint=torch.load(campaign/'models'/f'validate_doe_recommended_{seed}.pt',map_location='cpu',weights_only=True)
        model=Agent(checkpoint['obs_dim'],checkpoint['actions'],checkpoint['hp']);model.load_state_dict(checkpoint['state_dict']);model.eval()
        models[seed]=(model,checkpoint['hp'])
    cells=[]
    for date_index,date in enumerate(design['dates']):
        for regime_index,regime in enumerate(design['regimes']):
            path=output/'cells'/f'{date[:10]}-{regime}.json'
            if path.exists():
                cell=json.loads(path.read_text())
                if cell['signature'] != signature:raise ValueError('Cell design changed')
            else:
                scenario_path=prepare(date,config,regime=regime)
                if sha256(scenario_path) != bound['scenarios'][f'{date}:{regime}']['arrays_sha256']:
                    raise ValueError('Bound scenario arrays changed')
                scenario=load(scenario_path)
                cell={'signature':signature,'date':date,'regime':regime,'scenario_sha256':sha256(scenario_path),'models':[]}
                for seed,(model,hp) in models.items():
                    selection_seed=np.random.SeedSequence([20261024,date_index,regime_index,seed])
                    cell['models'].append({'model_seed':seed,**probe_model(model,scenario,config,hp,7441,selection_seed)})
                path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(cell,indent=2)+'\n');tmp.replace(path)
            cells.append(cell)
            print(f'Geometry single-loss cell complete: {date} {regime} ({len(cells)})',flush=True)
    effects,rows=summarize(cells)
    result={'status':'completed','design_signature':signature,'scope':design['scope'],
        'cells':len(cells),'baseline_episodes':len(cells)*len(seeds),'counterfactual_probes':len(rows),
        'effects':effects,'cells_sha256':{str(p.relative_to(output)):sha256(p) for p in sorted((output/'cells').glob('*.json'))},
        'uncertainty':'Means average selected probes/checkpoints within each available date, then dates equally. Student-t intervals cluster by sampled date and do not correct for serial dependence, source/model uncertainty or multiple exploratory bins. Empty bins are omitted; one-date bins have no interval.',
        'selection_limit':'Conditional on successful baseline observations, with one sample per occupied joint bin/checkpoint. Results do not estimate average loss over all attempted observations or all operational geometries.'}
    (output/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    if rows:
        with (output/'probes.csv').open('w',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    return result


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dropout',type=Path,required=True)
    parser.add_argument('--campaign',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    result=execute(args.source_dropout,args.campaign,args.output)
    print(json.dumps({'status':result['status'],'cells':result['cells'],'probes':result['counterfactual_probes']}))
