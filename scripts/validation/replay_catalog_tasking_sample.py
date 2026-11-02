"""Rebuild selected completed tasking episodes from archived elements and replay actions."""
from __future__ import annotations

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))


import argparse
import json
from pathlib import Path

import numpy as np

from godsat.orbits import ROOT, History
from scripts.validation.audit_full_catalog_tasking import REGIMES, sha256, verify_rows
from scripts.experiments.run_full_catalog_tasking import read_inputs, simulate_condition


def compare_response(expected, actual):
    if set(expected) != set(actual):
        raise ValueError('Replayed response fields differ')
    for field in expected:
        if expected[field] != actual[field]:
            raise ValueError(f'Replayed response mismatch: {field}')


def replay(folder, date_indices=None):
    folder = Path(folder).resolve()
    summary_path = folder/'summary.json'
    audit_path = folder/'independent_audit.json'
    summary = json.loads(summary_path.read_text())
    audit = json.loads(audit_path.read_text())
    if summary['status'] != 'completed' or audit['status'] != 'passed_structural_and_statistical':
        raise ValueError('Completed tasking and structural/statistical audit required')
    if sha256(ROOT/'data/raw/manifest.json') != summary['raw_archive_manifest_sha256']:
        raise ValueError('Archived source manifest changed')
    dates = summary['dates']
    design = json.loads((folder/'tasking_design.json').read_text())
    rates = design['outage_rates']
    indexed = verify_rows(summary['rows'], dates, rates)
    indices = sorted(set(date_indices if date_indices is not None else [0,len(dates)//2,len(dates)-1]))
    if not indices or any(index < 0 or index >= len(dates) for index in indices):
        raise ValueError('Sample date index outside completed design')
    masks = mask_dates = None
    profile = summary.get('dropout_profile')
    if profile and profile['mode'] == 'empirical_block':
        path = Path(profile['mask_archive_path'])
        if sha256(path) != profile['mask_archive_sha256']:
            raise ValueError('Bound empirical masks changed')
        with np.load(path,allow_pickle=False) as archive:
            masks,mask_dates = archive['dropout'].astype(bool),archive['dates'].astype(str).tolist()
    checked = []
    history = History(ROOT,summary['target_cohort'])
    try:
        for index in indices:
            date = dates[index]
            ids,states,ages,valid,times = read_inputs(date,history,summary['config'])
            for regime_index,regime in enumerate(REGIMES):
                for rate in rates:
                    expected = indexed[date,regime,float(rate)]
                    actual = simulate_condition(index,regime_index,float(rate),ids,states,
                        ages,valid,times,expected['sensor_host_ids'],summary['config'],seed=73129,
                        empirical_dropout_masks=masks,empirical_dropout_dates=mask_dates)
                    compare_response(expected,actual)
                    checked.append({'date':date,'regime':regime,'rate':rate})
                print(f'Exact tasking replay passed: {date} {regime}',flush=True)
    finally:
        history.db.close()
    result = {'status':'passed_sampled_source_and_action_replay',
              'scope':'Fresh historical SGP4 reconstruction and exact deterministic rerun of the production scheduler for sampled dates, all four regimes and both conditions. This tests reproducibility, not an independent scheduler implementation or orbital truth. Unsampled actions are not replayed.',
              'summary_sha256':sha256(summary_path),'structural_audit_sha256':sha256(audit_path),
              'tasking_design_sha256':sha256(folder/'tasking_design.json'),
              'simulation_code_sha256':sha256(ROOT/'scripts/experiments/run_full_catalog_tasking.py'),
              'orbit_code_sha256':sha256(ROOT/'godsat/orbits.py'),
              'date_indices':indices,'response_rows_replayed':len(checked),
              'response_rows_total':len(indexed),'all_returned_fields_exact':True,'checked':checked}
    (folder/'sampled_action_replay.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--date-indices',type=int,nargs='+')
    args = parser.parse_args()
    replay(args.input,args.date_indices)
