"""Reconcile geometry-probe sources/statistics and replay an alternate loss injection."""
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
from godsat.scenario import cache_key,load
from scripts.experiments.run_dropout_campaign import sha256

METRICS=('custody_continuity','observable_custody','slew_energy_proxy','objective')


def alternate_episode(model,scenario,config,hp,seed,baseline,forced=None):
    env=TaskingEnv(scenario,config,hp['claim_resolution'],seed)
    obs,mask=env.reset()
    for step in range(env.steps):
        with torch.no_grad():
            action=model.distribution(torch.tensor(obs),torch.tensor(mask)).probs.argmax(-1).numpy()
        if forced is None or step <= forced['step']:
            if action.tolist() != baseline['baseline_actions'][step]:
                raise ValueError('Replay actions disagree before intervention')
        if forced is not None and step == forced['step']:
            _,ranges,angles,_,allowed=env.geometry()
            i,j=forced['agent'],forced['target']
            if action[i] != j or not allowed[i,j]:raise ValueError('Invalid selected observation')
            priority=copy.deepcopy(env.priority_rng).permutation(env.a)
            owners=[int(a) for a in priority if action[a]==j and allowed[a,j]]
            if not owners or owners[0] != i:raise ValueError('Selected host is not the winning owner')
            np.testing.assert_allclose([ranges[i,j],np.rad2deg(angles[i,j])],
                [forced['range_km'],forced['slew_deg']],rtol=0,atol=1e-12)
            # Independent injection route: force the outage branch instead of
            # replacing the nominal-detection draw used by the production probe.
            env.dropout_uniforms[step,i,j]=-1.
        (obs,mask),_,_=env.step(action)
        if forced is None:
            if env.trace[-1]['detected'] != baseline['baseline_detected'][step]:
                raise ValueError('Baseline detections differ')
        elif step == forced['step']:
            if set(env.trace[-1]['detected']) != set(baseline['baseline_detected'][step])-{forced['target']}:
                raise ValueError('Alternate injection did not remove precisely one detection')
    if forced is not None and env.dropout_misses != 1:
        raise ValueError('Alternate injection did not register exactly one suppressed attempt')
    return env.metrics()


def audit(folder,campaign,source_dropout=None):
    folder,campaign=Path(folder).resolve(),Path(campaign).resolve()
    summary=json.loads((folder/'summary.json').read_text())
    document=json.loads((folder/'geometry_design.json').read_text());design=document['design']
    if summary['status'] != 'completed' or summary['design_signature'] != document['signature']:
        raise ValueError('Completed matching design required')
    if hashlib.sha256(json.dumps(design,sort_keys=True).encode()).hexdigest() != document['signature']:
        raise ValueError('Design signature does not reconcile')
    if sha256(ROOT/'scripts/experiments/run_geometry_loss_probes.py') != design['code_sha256']:
        raise ValueError('Probe execution code changed')
    for name,digest in design['core_code_sha256'].items():
        if sha256(ROOT/name) != digest:raise ValueError('Core code changed')
    bound=design['config']['dropout_input_provenance']
    source_dropout=Path(source_dropout or ROOT/'outputs/dropout-five-policy-quarterly-20261024')
    source_file=source_dropout/'dropout_design.json'
    if sha256(source_file) != design['source_dropout_design_sha256']:
        raise ValueError('Source dropout design changed')
    source=json.loads(source_file.read_text())['design']
    for key in ('dates','regimes','model_seeds','config'):
        if design[key] != source[key]:raise ValueError('Geometry study differs from bound source design')
    if (sha256(campaign/'config.json') != bound['campaign_config_sha256']
            or sha256(campaign/'summary.json') != bound['campaign_summary_sha256']):
        raise ValueError('Source learning campaign changed')
    for seed in design['model_seeds']:
        if sha256(campaign/'models'/f'validate_doe_recommended_{seed}.pt') != bound['checkpoints_sha256'][str(seed)]:
            raise ValueError('Checkpoint changed')
    cells={};grouped=defaultdict(lambda:defaultdict(list));probe_count=0;expected_csv={}
    for name,digest in summary['cells_sha256'].items():
        if sha256(folder/name) != digest:raise ValueError('Cell bytes changed')
        cell=json.loads((folder/name).read_text());key=cell['date'],cell['regime']
        if key in cells or cell['signature'] != document['signature']:raise ValueError('Duplicate or wrong-design cell')
        cells[key]=cell
        scenario_path=ROOT/'data/scenarios'/(cache_key(key[0],design['config'],key[1])+'.npz')
        if sha256(scenario_path) != cell['scenario_sha256'] or cell['scenario_sha256'] != bound['scenarios'][f'{key[0]}:{key[1]}']['arrays_sha256']:
            raise ValueError('Scenario provenance mismatch')
        seeds=[m['model_seed'] for m in cell['models']]
        if sorted(seeds) != sorted(design['model_seeds']):raise ValueError('Checkpoint grid incomplete')
        for model in cell['models']:
            if sum(map(len,model['baseline_detected'])) != model['baseline_successful_observations']:
                raise ValueError('Baseline event count mismatch')
            if sum(p['eligible_successes_in_joint_bin'] for p in model['probes']) != model['baseline_successful_observations']:
                raise ValueError('Joint-bin coverage mismatch')
            bins=set()
            for probe in model['probes']:
                r=0 if probe['range_km']<2000 else 1 if probe['range_km']<4000 else 2
                a=0 if probe['slew_deg']<40 else 1 if probe['slew_deg']<80 else 2
                if (r,a) != (probe['range_bin'],probe['slew_bin']) or (r,a) in bins:raise ValueError('Probe geometry strata differ')
                bins.add((r,a));probe_count+=1
                values={}
                for metric in METRICS:
                    value=probe['counterfactual_metrics'][metric]-model['baseline_metrics'][metric]
                    if not np.isfinite(value) or value != probe['changes'][metric]:raise ValueError('Probe contrast mismatch')
                    values[metric]=value
                grouped[cell['regime'],r,a][cell['date']].append(values)
                csv_key=(*key,model['model_seed'],r,a)
                expected_csv[csv_key]=probe
    expected={(d,r) for d in design['dates'] for r in design['regimes']}
    if (set(cells) != expected or summary['cells'] != len(expected)
            or summary['baseline_episodes'] != len(expected)*len(design['model_seeds'])
            or summary['counterfactual_probes'] != probe_count):
        raise ValueError('Incomplete geometry design')
    with (folder/'probes.csv').open(newline='') as stream:rows=list(csv.DictReader(stream))
    seen=set()
    for row in rows:
        key=(row['date'],row['regime'],int(row['model_seed']),int(row['range_bin']),int(row['slew_bin']))
        if key in seen or key not in expected_csv:raise ValueError('CSV pairing differs')
        seen.add(key);probe=expected_csv[key]
        for field,value in probe.items():
            if field not in ('counterfactual_metrics','changes') and float(row[field]) != value:
                raise ValueError('CSV geometry or event identity differs')
        for metric in METRICS:
            if float(row[metric+'_change']) != probe['changes'][metric]:raise ValueError('CSV contrast differs')
    if seen != set(expected_csv):raise ValueError('Missing CSV rows')
    effects={(e['regime'],e['range_bin'],e['slew_bin']):e for e in summary['effects']}
    if len(effects) != len(summary['effects']) or set(effects) != set(grouped):raise ValueError('Summary strata differ')
    for key,by_date in grouped.items():
        item=effects[key]
        if item['dates'] != len(by_date) or item['probes'] != sum(map(len,by_date.values())):raise ValueError('Stratum counts differ')
        for metric in METRICS:
            values=np.array([sum(v[metric] for v in group)/len(group) for group in by_date.values()])
            estimate=float(values.sum()/len(values));reported=item['metrics'][metric]
            np.testing.assert_allclose(reported['mean_date_change'],estimate,atol=1e-12,rtol=0)
            if len(values)>1:
                se=np.sqrt(np.sum((values-estimate)**2)/(len(values)*(len(values)-1)))
                half=t.ppf(.975,len(values)-1)*se
                np.testing.assert_allclose(reported['date_cluster_ci95'],[estimate-half,estimate+half],atol=1e-12,rtol=0)
            elif reported['date_cluster_ci95'] is not None:raise ValueError('One-date interval is not estimable')
    torch.set_num_threads(1)
    seed=design['model_seeds'][0]
    ckpt=torch.load(campaign/'models'/f'validate_doe_recommended_{seed}.pt',map_location='cpu',weights_only=True)
    model=Agent(ckpt['obs_dim'],ckpt['actions'],ckpt['hp']);model.load_state_dict(ckpt['state_dict']);model.eval()
    selected_dates=[design['dates'][i] for i in sorted({0,len(design['dates'])//2,len(design['dates'])-1})]
    replayed=0
    for date in selected_dates:
        for regime in design['regimes']:
            cell=cells[date,regime];saved=next(m for m in cell['models'] if m['model_seed']==seed)
            scenario=load(ROOT/'data/scenarios'/(cache_key(date,design['config'],regime)+'.npz'))
            baseline=alternate_episode(model,scenario,design['config'],ckpt['hp'],design['simulation_seed'],saved)
            for metric in baseline:
                if baseline[metric] != saved['baseline_metrics'][metric]:raise ValueError('Fresh baseline differs')
            for probe in saved['probes']:
                counter=alternate_episode(model,scenario,design['config'],ckpt['hp'],design['simulation_seed'],saved,probe)
                for metric in METRICS:
                    if counter[metric] != probe['counterfactual_metrics'][metric]:raise ValueError('Alternate intervention result differs')
                replayed+=1
            print(f'Alternate geometry injection audit passed: {date} {regime}',flush=True)
    result={'status':'passed_source_statistics_and_sampled_counterfactual_replay',
        'auditor_sha256':sha256(Path(__file__)),
        'summary_sha256':sha256(folder/'summary.json'),'design_sha256':sha256(folder/'geometry_design.json'),
        'csv_sha256':sha256(folder/'probes.csv'),'cells_checked':len(cells),'probes_checked':probe_count,
        'all_reported_date_cluster_statistics_recomputed':True,'alternate_loss_injection_baselines_replayed':len(selected_dates)*len(design['regimes']),
        'alternate_loss_injection_probes_replayed':replayed,'sampled_model_seed':seed,'sampled_dates':selected_dates,
        'limits':'All source bindings and reported statistics checked. Numerical counterfactual replay covers only the first checkpoint on three sampled dates and uses an alternate loss branch in the same simulator. It does not establish independent physics or hardware validity.'}
    (folder/'independent_audit.json').write_text(json.dumps(result,indent=2)+'\n');return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True);parser.add_argument('--campaign',type=Path,required=True)
    parser.add_argument('--source-dropout',type=Path)
    args=parser.parse_args();print(json.dumps(audit(args.input,args.campaign,args.source_dropout),indent=2))
