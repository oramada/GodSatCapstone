"""Fill canonical future cells of the registered measured Markov replay."""

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))

import argparse
from concurrent.futures import ProcessPoolExecutor,as_completed
import hashlib
import json
import multiprocessing
from pathlib import Path

from godsat.orbits import ROOT,History
from scripts.experiments.parallel_catalog_cells import CODE_PATHS,publish_exact_cell
from scripts.experiments.run_full_catalog_tasking import (REGIMES,SIMULATOR_VERSION,
    configuration_signature,host_ids_by_regime,read_inputs,sha256,simulate_condition)
from scripts.experiments.run_measured_profile_tasking import validate_source_gate


def reconcile_profile(design,profile,profile_hash):
    expected={'outage_rates':design['outage_rates'],'dropout_profile_sha256':profile_hash,
        'dropout_burst_persistence':profile['simulator_markov_persistence_parameter'],
        'reference_step_seconds':60}
    digest=hashlib.sha256(json.dumps(expected,sort_keys=True).encode()).hexdigest()
    if (digest!=design['dropout_design_sha256']
            or design['outage_rates']!=[0.,profile['one_minute_attitude_solution_dropout_rate']]
            or design['config']['dropout_burst_persistence']!=expected['dropout_burst_persistence']
            or design['config']['dropout_burst_reference_step_seconds']!=60):
        raise ValueError('Registered cells do not match this fitted Markov profile')


def compute_date(folder,index,hashes,pilot=False):
    for name,digest in hashes.items():
        if sha256(ROOT/name)!=digest:raise ValueError('Bound worker code changed')
    folder=Path(folder);design=json.loads((folder/'tasking_design.json').read_text())
    date=design['dates'][index];config=design['config']
    hosts,source_hashes,_=host_ids_by_regime(date,config)
    history=History(ROOT,'all');outcomes=[]
    try:
        ids,states,ages,valid,times=read_inputs(date,history,config)
        for regime_index,regime in enumerate(REGIMES):
            rows=[simulate_condition(index,regime_index,rate,ids,states,ages,valid,times,
                hosts[regime],config,seed=73129) for rate in design['outage_rates']]
            payload={'simulator_version':SIMULATOR_VERSION,'source_sha256':source_hashes[regime],
                'rows':rows,'configuration_signature':design['configuration_signature'],
                'design_sha256':design['dropout_design_sha256']}
            path=folder/'cells'/date[:10]/f'{regime}.json'
            if pilot:
                if json.loads(path.read_text())!=payload:raise ValueError('Canonical Markov pilot differs')
                outcomes.append('pilot_exact')
            else:outcomes.append(publish_exact_cell(path,payload))
    finally:history.db.close()
    return {'date_index':index,'date':date,'outcomes':outcomes}


def run(folder,first_index,workers=2,data=ROOT/'data/attitude/cassiope_epop'):
    folder,data=Path(folder).resolve(),Path(data).resolve()
    validate_source_gate(data)
    design=json.loads((folder/'tasking_design.json').read_text())
    profile=json.loads((data/'dropout_profile_1minute.json').read_text())
    if profile['source_audit_sha256']!=sha256(data/'independent_audit.json'):
        raise ValueError('Measured profile source audit changed')
    reconcile_profile(design,profile,sha256(data/'dropout_profile_1minute.json'))
    if design['target_cohort']!='all' or sha256(ROOT/'data/raw/manifest.json')!=design['archive_sha256']:
        raise ValueError('Registered orbit source changed')
    signature=configuration_signature(design['config'],design['dates'],'all',design['outage_rates'],
        design['archive_sha256'],design['dropout_design_sha256'])
    if signature!=design['configuration_signature']:raise ValueError('Tasking signature differs')
    if not 0<=first_index<len(design['dates']) or not 1<=workers<=3:raise ValueError('Invalid shard')
    hashes={p:sha256(ROOT/p) for p in [*CODE_PATHS,'scripts/experiments/parallel_catalog_cells.py',
                                    'scripts/experiments/parallel_markov_cells.py']}
    receipt={'status':'verifying_canonical_pilot','configuration_signature':signature,
        'tasking_design_sha256':sha256(folder/'tasking_design.json'),'code_hashes':hashes,
        'first_index':first_index,'workers':workers,'completed_dates':[],
        'scope':'Canonical future measured-Markov cells, original full-design indices and seeds. Original coordinator assembles all results and runs its existing final audit.'}
    def save():
        path=folder/'parallel_cell_execution.json';tmp=path.with_suffix('.tmp')
        tmp.write_text(json.dumps(receipt,indent=2)+'\n');tmp.replace(path)
    save()
    try:
        receipt['pilot']=compute_date(folder,0,hashes,pilot=True)
        receipt['status']='running';save();print('Markov pilot exactly matched all eight canonical responses',flush=True)
        with ProcessPoolExecutor(max_workers=workers,mp_context=multiprocessing.get_context('spawn')) as pool:
            futures=[pool.submit(compute_date,folder,index,hashes) for index in range(len(design['dates'])-1,first_index-1,-1)]
            for future in as_completed(futures):
                item=future.result();receipt['completed_dates'].append(item);save()
                print(f'Canonical Markov cells complete: {item["date"]} ({len(receipt["completed_dates"])})',flush=True)
        receipt['status']='completed_canonical_cells';save()
    except Exception as error:
        receipt.update(status='failed_requires_inspection',error=f'{type(error).__name__}: {error}');save();raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True);parser.add_argument('--first-index',type=int,required=True)
    parser.add_argument('--workers',type=int,default=2)
    args=parser.parse_args();run(args.input,args.first_index,args.workers)
