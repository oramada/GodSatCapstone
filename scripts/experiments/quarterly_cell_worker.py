"""Compute canonical frozen-policy dropout cells from an existing bound design."""

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))

import csv
import io
import json
from pathlib import Path

import numpy as np
import torch

from godsat.dropout import evaluate_policy,parse_response_row
from godsat.experiment import runtime_provenance
from godsat.learning import Agent
from godsat.orbits import ROOT
from godsat.scenario import cache_key,load
from scripts.experiments.run_dropout_campaign import sha256


def row_key(row):
    return (row['date'],row['regime'],row['mode'],int(row['replicate']),
            int(row['model_seed']),float(row['dropout_probability']))


def checked_rows(payload,design):
    parsed=list(csv.DictReader(io.StringIO(payload.decode())))
    rows=[parse_response_row(row) for row in parsed]
    expected={(d,r,m,k,s,float(p)) for d in design['dates'] for r in design['regimes']
        for m in design['modes'] for k in range(design['replicates'])
        for s in design['model_seeds'] for p in design['rates']}
    keys=[row_key(row) for row in rows]
    if len(set(keys))!=len(keys) or not set(keys)<=expected:raise ValueError('Invalid treatment keys in checkpoint')
    counts={}
    for row in rows:
        key=row['date'],row['regime'];counts[key]=counts.get(key,0)+1
        if row['seed']!=int(design['config'].get('dropout_seed',7441))+row['replicate']:
            raise ValueError('Checkpoint simulation seed differs')
        for field in ('custody_continuity','observable_custody','slew_energy_proxy','false_track_proxy',
                      'conflict_rate','valid_target_fraction','dropout_rate_observed'):
            if not np.isfinite(row[field]) or not 0<=row[field]<=1:raise ValueError('Invalid normalized response')
        if not np.isfinite(row['objective']):raise ValueError('Invalid objective')
    per_cell=design['replicates']*len(design['modes'])*len(design['rates'])*len(design['model_seeds'])
    if any(value!=per_cell for value in counts.values()):raise ValueError('Checkpoint contains an incomplete cell')
    return rows,counts


def validate_bound_sources(design,campaign):
    campaign=Path(campaign);bound=design['config']['dropout_input_provenance']
    if runtime_provenance()!=bound['runtime']:raise ValueError('Bound software fingerprint changed')
    for name,key in [('config.json','campaign_config_sha256'),('summary.json','campaign_summary_sha256')]:
        if sha256(campaign/name)!=bound[key]:raise ValueError('Source learning campaign changed')
    if sha256(ROOT/'data/raw/manifest.json')!=bound['raw_archive_receipt_sha256']:
        raise ValueError('Orbital archive receipt changed')
    if sha256(ROOT/'scripts/experiments/run_dropout_campaign.py')!=bound['orchestration_script_sha256']:
        raise ValueError('Original orchestration code changed')
    for seed in design['model_seeds']:
        if sha256(campaign/'models'/f'validate_doe_recommended_{seed}.pt')!=bound['checkpoints_sha256'][str(seed)]:
            raise ValueError('Frozen checkpoint changed')
    for date in design['dates']:
        for regime in design['regimes']:
            path=ROOT/'data/scenarios'/(cache_key(date,design['config'],regime)+'.npz')
            source=bound['scenarios'][f'{date}:{regime}']
            if sha256(path)!=source['arrays_sha256'] or sha256(path.with_suffix('.json'))!=source['metadata_sha256']:
                raise ValueError('Bound scenario changed')


def compute_cell(design,campaign,date,regime):
    campaign=Path(campaign);config=design['config'];bound=config['dropout_input_provenance']
    if runtime_provenance()!=bound['runtime']:raise ValueError('Worker software fingerprint differs')
    path=ROOT/'data/scenarios'/(cache_key(date,config,regime)+'.npz')
    if sha256(path)!=bound['scenarios'][f'{date}:{regime}']['arrays_sha256']:
        raise ValueError('Worker scenario bytes changed')
    scenario=load(path);summary=json.loads((campaign/'summary.json').read_text())
    hp=summary['comparison_configurations']['doe_recommended'];models={}
    torch.set_num_threads(1)
    for seed in design['model_seeds']:
        path=campaign/'models'/f'validate_doe_recommended_{seed}.pt'
        if sha256(path)!=bound['checkpoints_sha256'][str(seed)]:raise ValueError('Worker checkpoint changed')
        ckpt=torch.load(path,map_location='cpu',weights_only=True)
        model=Agent(ckpt['obs_dim'],ckpt['actions'],ckpt['hp']);model.load_state_dict(ckpt['state_dict']);model.eval();models[seed]=model
    rows=[]
    for mode in design['modes']:
        for replicate in range(design['replicates']):
            seed=int(config.get('dropout_seed',7441))+replicate
            for rate in design['rates']:
                for model_seed in design['model_seeds']:
                    metrics=evaluate_policy(models[model_seed],scenario,config,hp,seed,float(rate),mode)
                    rows.append({'date':date,'regime':regime,'mode':mode,'replicate':replicate,'seed':seed,
                                 **metrics,'model_seed':model_seed})
    return rows
