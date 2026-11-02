"""Verify treatment signatures/histories and repeat sampled full training trajectories."""

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import torch

from godsat.experiment import device_provenance, runtime_provenance, scenario_fingerprint
from godsat.learning import train
from godsat.orbits import ROOT
from godsat.scenario import load, prepare
from scripts.experiments.run_physical_sensitivity import sha


def audit(folder):
    folder=Path(folder).resolve();config=json.loads((folder/'config.json').read_text())
    config.pop('response_surface_center_replicates',None)
    scenes={split:[load(prepare(date,config,regime=regime)) for date in config[split+'_dates']
                  for regime in config.get(split+'_regimes',['leo'])] for split in ['training','validation','test']}
    scenes['train']=scenes.pop('training');fingerprint=scenario_fingerprint(scenes)
    runtime=runtime_provenance();device=device_provenance(config)
    execution_config={**config,'_scenario_sha256':fingerprint};records={};hashes={}
    for path in sorted((folder/'runs').glob('*.json')):
        r=json.loads(path.read_text());records[r['name']]=r
        signature=hashlib.sha256(json.dumps({'hp':r['hyperparameters'],'config':execution_config,
            'seed':r['seed'],'runtime':runtime,'device':device,'scenario_sha256':fingerprint},sort_keys=True).encode()).hexdigest()
        if signature!=r['signature']:raise ValueError('Treatment signature differs: '+r['name'])
        if len(r['training_history'])!=config['training_episodes']:raise ValueError('Incomplete training history')
        if any(not np.isfinite(h['loss']) for h in r['training_history']):raise ValueError('Nonfinite training loss')
        hashes[str(path.relative_to(ROOT))]=sha(path)
    repeats=[]
    for name in ['screen_00','screen_01','rsm_00']:
        r=records[name];model,history,_,_=train(scenes['train'],config,r['hyperparameters'],r['seed'])
        saved=torch.load(folder/'models'/(name+'.pt'),map_location='cpu',weights_only=True)
        if any(not torch.equal(tensor.cpu(),saved['state_dict'][key]) for key,tensor in model.state_dict().items()):
            raise ValueError('Repeated training weights differ: '+name)
        if history!=r['training_history']:raise ValueError('Repeated training metrics/losses differ: '+name)
        hashes[str((folder/'models'/(name+'.pt')).relative_to(ROOT))]=sha(folder/'models'/(name+'.pt'))
        repeats.append({'name':name,'episodes':len(history),'all_checkpoint_tensors_exact':True,'entire_training_history_exact':True})
        print('Exact training replay: '+name,flush=True)
    result={'status':'passed_all_treatment_signatures_and_sampled_training_replay',
            'source_hashes':hashes,'runtime':runtime,'scenario_sha256':fingerprint,
            'treatment_signatures_verified':len(records),'complete_finite_training_histories':len(records),
            'full_training_replays':repeats,
            'scope':'All 77 original treatment/retrain signatures and 40-episode finite loss histories verified. Three selected complete training trajectories and checkpoint tensors repeated exactly; the remaining training trajectories were not all rerun.'}
    (folder/'training_replay_audit.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',type=Path,default=ROOT/'outputs/governing-design-physical-leo-20261025')
    args=p.parse_args();r=audit(args.input);print(json.dumps({k:v for k,v in r.items() if k not in ['source_hashes','runtime']}))
