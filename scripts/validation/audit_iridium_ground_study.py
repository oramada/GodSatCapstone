"""Independently reconcile the registered NEXT/ground rerun's saved evidence."""
from __future__ import annotations

if __package__ in (None, ''):
    import sys
    from pathlib import Path
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]))

import argparse
import csv
import hashlib
import json
from pathlib import Path
import statistics

import numpy as np
from scipy.stats import f, t
import torch

from godsat.experiment import device_provenance, scenario_fingerprint
from godsat.learning import train
from godsat.scenario import prepare, load


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def audit(folder):
    folder=Path(folder).resolve()
    plan=json.loads((folder/'registered-plan.json').read_text())
    for relative,digest in plan['source_hashes'].items():
        if sha(folder/'source-snapshot'/relative)!=digest:
            raise ValueError('Registered scientific source snapshot changed: '+relative)
    config=plan['config']
    scenes={key:[load(prepare(date,config)) for date in config[dates]]
            for key,dates in [('train','training_dates'),('validation','validation_dates'),('test','test_dates')]}
    fingerprint=scenario_fingerprint(scenes)
    execution={**config,'_scenario_sha256':fingerprint}
    records={}
    for path in sorted((folder/'runs').glob('*.json')):
        record=json.loads(path.read_text())
        signature=hashlib.sha256(json.dumps({'hp':record['hyperparameters'],'config':execution,
            'seed':record['seed'],'runtime':plan['runtime'],'device':device_provenance(config),
            'scenario_sha256':fingerprint},sort_keys=True).encode()).hexdigest()
        assert signature==record['signature'],record['name']
        assert len(record['training_history'])==config['training_episodes']
        assert all(np.isfinite(row['loss']) for row in record['training_history'])
        records[record['name']]=record
    assert len(records)==122
    repeated=[]
    for name in ['screen_00','rsm_00','validate_baseline_101']:
        record=records[name]
        model,history,_,_=train(scenes['train'],config,record['hyperparameters'],record['seed'])
        saved=torch.load(folder/'models'/(name+'.pt'),map_location='cpu',weights_only=True)
        assert all(torch.equal(value.cpu(),saved['state_dict'][key]) for key,value in model.state_dict().items()),name
        assert history==record['training_history'],name
        repeated.append(name)
        print('Exact complete training replay:',name,flush=True)
    training={'status':'passed','treatment_signatures_checked':len(records),
              'finite_episode_losses':len(records)*config['training_episodes'],
              'exact_full_training_replays':repeated,'scenario_sha256':fingerprint,
              'scope':'All signatures/histories checked against registered execution inputs; three complete training trajectories and weights repeated. Not convergence.'}
    (folder/'training-signature-audit.json').write_text(json.dumps(training,indent=2)+'\n')
    with (folder/'validation.csv').open() as stream:
        validation=list(csv.DictReader(stream))
    assert len(validation)==25
    expected={(label,seed) for label in ['baseline','doe_recommended','bayesian_best','greedy','random']
              for seed in plan['config']['validation_seeds']}
    indexed={(r['configuration'],int(r['seed'])):r for r in validation}
    assert set(indexed)==expected
    summary=json.loads((folder/'summary.json').read_text())
    main=json.loads((folder/'rerun-audit.json').read_text())
    for label,stats in summary['test_summary'].items():
        for metric,reported in stats.items():
            values=[float(r[metric]) for r in validation if r['configuration']==label]
            mean=statistics.mean(values)
            half=t.ppf(.975,len(values)-1)*statistics.stdev(values)/np.sqrt(len(values))
            assert np.isclose(mean,reported['mean'],atol=1e-12,rtol=0)
            assert np.isclose(half,reported['ci95_half_width'],atol=1e-12,rtol=0)
    for metric in ['custody_continuity','slew_energy_joules']:
        delta=[float(indexed['doe_recommended',seed][metric])-float(indexed['baseline',seed][metric])
               for seed in plan['config']['validation_seeds']]
        mean=statistics.mean(delta)
        half=t.ppf(.9875,len(delta)-1)*statistics.stdev(delta)/np.sqrt(len(delta))
        assert np.allclose([mean-half,mean+half],main['primary_comparisons'][metric]['family_adjusted_ci'],atol=1e-12,rtol=0)
    with (folder/'dropout-responses.csv').open() as stream:
        rows=list(csv.DictReader(stream))
    def key(row):
        return (row['date'],row['configuration'],int(row['model_seed']),row['mode'],int(row['replicate']),float(row['rate']))
    dropout={key(r):r for r in rows}
    assert len(dropout)==len(rows)==5280
    zero_controls=0
    for k,r in dropout.items():
        if k[-1]==0 and k[3]=='independent':
            other=dropout[k[:3]+('burst',k[4],0.)]
            for metric in ['custody_continuity','observable_custody','slew_energy_joules','false_track_rate','objective']:
                assert float(r[metric])==float(other[metric])
            zero_controls+=1
    effects=json.loads((folder/'dropout-effects.json').read_text())
    for effect in effects:
        label=effect['configuration']
        seeds=plan['config']['validation_seeds'] if label!='greedy' else [0]
        values=[]
        for replicate in range(20):
            changes=[]
            for date in plan['config']['test_dates']:
                for seed in seeds:
                    k=(date,label,seed,effect['mode'],replicate)
                    changes.append(float(dropout[k+(effect['rate'],)][effect['metric']])-float(dropout[k+(0.,)][effect['metric']]))
            values.append(statistics.mean(changes))
        mean=statistics.mean(values)
        half=t.ppf(.975,19)*statistics.stdev(values)/np.sqrt(20)
        assert np.allclose([mean,mean-half,mean+half],[effect['mean'],*effect['ci95']],atol=1e-12,rtol=0)
    with (folder/'rsm_design.csv').open() as stream:
        design=list(csv.DictReader(stream))
    x=np.repeat([[float(r[k]) for k in ['x1','x2','x3']] for r in design],3,axis=0)
    matrix=np.column_stack([np.ones(len(x)),x,x*x,x[:,0]*x[:,1],x[:,0]*x[:,2],x[:,1]*x[:,2]])
    assert np.linalg.matrix_rank(matrix)==10
    records=[json.loads((folder/'runs'/f'adequacy_{i:02d}_{j}.json').read_text()) for i in range(15) for j in range(3)]
    assert len({r['seed'] for r in records})==45
    fits=json.loads((folder/'independent-ccd-adequacy.json').read_text())
    for metric,fit in fits.items():
        y=np.asarray([r[metric] for r in records])
        beta=np.linalg.lstsq(matrix,y,rcond=None)[0]
        sse=float(np.sum((y-matrix@beta)**2))
        pure=float(np.sum((y.reshape(15,3)-y.reshape(15,3).mean(axis=1,keepdims=True))**2))
        assert np.allclose(beta,fit['coefficients'],atol=1e-10,rtol=0)
        assert np.isclose(sse,fit['sse'],atol=1e-12,rtol=0)
        if pure>0:
            statistic=max(0,sse-pure)/5/(pure/30)
            assert np.isclose(f.sf(statistic,5,30),fit['lack_of_fit']['p_value'],atol=1e-10,rtol=0)
        else:
            assert fit['lack_of_fit'].get('available') is False
    receipt={'status':'passed','validation_summary_statistics_checked':True,'family_adjusted_primary_intervals_checked':True,
             'dropout_rows_checked':len(rows),'zero_loss_cross_process_control_pairs':zero_controls,
             'dropout_effect_intervals_checked':len(effects),'independent_ccd_fit_responses_checked':len(fits),
             'registered_scientific_source_hashes_checked':len(plan['source_hashes']),
             'input_sha256':{name:sha(folder/name) for name in ['registered-plan.json','summary.json','validation.csv','dropout-responses.csv','dropout-effects.json','independent-ccd-adequacy.json','rerun-audit.json','scenario-audit.json','training-signature-audit.json']},
             'scope':'Source/data/statistic reconciliation, not empirical calibration, convergence, or population-wide validity.'}
    (folder/'independent-statistics-audit.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps(receipt,indent=2))
    return receipt


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,default=Path('outputs/iridium-next-ground-20261104'))
    audit(parser.parse_args().input)
