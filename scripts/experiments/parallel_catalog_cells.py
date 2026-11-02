"""Fill registered catalogue tasking cells without changing the coordinating study design."""
from __future__ import annotations

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))


import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import datetime as dt
import json
import multiprocessing
import os
from pathlib import Path

from godsat.orbits import ROOT, History
from scripts.experiments.run_full_catalog_tasking import (REGIMES, SIMULATOR_VERSION,
    configuration_signature, host_ids_by_regime, read_inputs, sha256, simulate_condition)

CODE_PATHS = ('scripts/experiments/run_full_catalog_tasking.py', 'godsat/orbits.py',
              'godsat/scenario.py', 'godsat/dropout.py')


def check_design(design):
    if design['target_cohort'] != 'all' or design.get('dropout_design_sha256') is not None:
        raise ValueError('Only the fixed-rate all-catalogue reference is supported')
    signature = configuration_signature(design['config'], design['dates'],
        design['target_cohort'], design['outage_rates'], design['archive_sha256'], None)
    if signature != design['configuration_signature']:
        raise ValueError('Registered design signature does not reconcile')
    if sha256(ROOT/'data/raw/manifest.json') != design['archive_sha256']:
        raise ValueError('Bound archive manifest changed')


def publish_exact_cell(path, payload):
    """Use unique temporary files; an existing cell must have identical content."""
    if path.exists():
        if json.loads(path.read_text()) != payload:
            raise ValueError(f'Existing cell differs from fresh calculation: {path}')
        return 'existing_exact'
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary = path.with_name(f'{path.name}.{os.getpid()}.tmp')
    temporary.write_text(json.dumps(payload,indent=2)+'\n')
    try:
        if path.exists():
            if json.loads(path.read_text()) != payload:
                raise ValueError(f'Concurrent cell differs: {path}')
            return 'concurrent_exact'
        temporary.replace(path)
        return 'published'
    finally:
        temporary.unlink(missing_ok=True)


def compute_date(folder, index, code_hashes, verify_only=False):
    from godsat.scope import validate_execution
    validate_execution()
    folder = Path(folder)
    for name,digest in code_hashes.items():
        if sha256(ROOT/name) != digest:
            raise ValueError(f'Bound simulation code changed: {name}')
    design = json.loads((folder/'tasking_design.json').read_text())
    check_design(design)
    date = design['dates'][index]
    config = design['config']
    hosts,hashes,_ = host_ids_by_regime(date,config)
    history = History(ROOT,'all')
    try:
        ids,states,ages,valid,times = read_inputs(date,history,config)
        outcomes = []
        for regime_index,regime in enumerate(REGIMES):
            rows = [simulate_condition(index,regime_index,rate,ids,states,ages,valid,
                times,hosts[regime],config,seed=73129) for rate in design['outage_rates']]
            payload = {'simulator_version':SIMULATOR_VERSION,'source_sha256':hashes[regime],
                       'rows':rows,'configuration_signature':design['configuration_signature']}
            path = folder/'cells'/date[:10]/f'{regime}.json'
            if verify_only:
                if not path.exists() or json.loads(path.read_text()) != payload:
                    raise ValueError(f'Pilot does not match canonical cell: {path}')
                outcomes.append('pilot_exact')
            else:
                outcomes.append(publish_exact_cell(path,payload))
    finally:
        history.db.close()
    return {'date_index':index,'date':date,'outcomes':outcomes}


def run(folder,first_index,workers=6,pilot_index=0):
    folder = Path(folder).resolve()
    design = json.loads((folder/'tasking_design.json').read_text())
    check_design(design)
    if not 0 <= first_index < len(design['dates']) or not 1 <= workers <= 8:
        raise ValueError('Invalid date range or worker count')
    hashes = {name:sha256(ROOT/name) for name in CODE_PATHS}
    receipt = {'status':'verifying_canonical_pilot','started_utc':dt.datetime.now(dt.timezone.utc).isoformat(),
        'design_sha256':sha256(folder/'tasking_design.json'),'code_hashes':hashes,
        'first_index':first_index,'workers':workers,'completed_dates':[],
        'scope':'Supplementary workers calculate canonical cells using original full-design date indices and seed 73129. The original coordinator remains responsible for final assembly and its existing final audit pipeline.'}
    receipt_path = folder/'parallel_cell_execution.json'
    def save():
        tmp = receipt_path.with_suffix('.json.tmp')
        tmp.write_text(json.dumps(receipt,indent=2)+'\n');tmp.replace(receipt_path)
    save()
    try:
        receipt['pilot'] = compute_date(folder,pilot_index,hashes,verify_only=True)
        receipt['status'] = 'running';save()
        print('Canonical pilot exactly matched all eight responses',flush=True)
        # Start at the far end to minimize overlap with the forward coordinator.
        indices = list(range(len(design['dates'])-1,first_index-1,-1))
        with ProcessPoolExecutor(max_workers=workers,mp_context=multiprocessing.get_context('spawn')) as pool:
            futures = {pool.submit(compute_date,folder,index,hashes):index for index in indices}
            for future in as_completed(futures):
                item = future.result();receipt['completed_dates'].append(item);save()
                print(f'Parallel canonical cells complete: {item["date"]} ({len(receipt["completed_dates"])}/{len(indices)})',flush=True)
        receipt['status']='completed_canonical_cells';save()
    except Exception as error:
        receipt.update(status='failed_requires_inspection',error=f'{type(error).__name__}: {error}');save()
        raise
    return receipt


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--first-index',type=int,required=True)
    parser.add_argument('--workers',type=int,default=6)
    parser.add_argument('--pilot-index',type=int,default=0)
    args=parser.parse_args()
    run(args.input,args.first_index,args.workers,args.pilot_index)
