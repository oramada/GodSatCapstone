"""Reproduce every daily tasking mean, annual mean and circular block interval."""

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

from scripts.validation.audit_measured_comparison import circular_interval
from scripts.experiments.run_dropout_campaign import sha256

REGIMES=('leo','meo','geo','heo')
METRICS=('custody_continuity','observable_custody','mean_slew_energy_proxy')
LENGTHS=(1,7,14,30)


def audit(folder):
    folder=Path(folder)
    temporal=json.loads((folder/'temporal_uncertainty.json').read_text())
    summary=json.loads((folder/'summary.json').read_text())
    source_audit=json.loads((folder/'independent_audit.json').read_text())
    if (temporal['status']!='completed_temporal_block_bootstrap'
            or summary['status']!='completed'
            or source_audit['status']!='passed_structural_and_statistical'
            or source_audit['dates_checked']!=1462
            or source_audit['response_rows_checked']!=11696
            or temporal['dates']!=1462):raise ValueError('Complete daily study required')
    for name,digest in temporal['source_sha256'].items():
        if sha256(folder/name)!=digest:raise ValueError('Temporal source binding changed')
    dates=summary['dates']
    if len(dates)!=1462 or len(set(dates))!=1462:raise ValueError('Daily date grid differs')
    with (folder/'responses.csv').open(newline='') as stream:raw=list(csv.DictReader(stream))
    rows={}
    for row in raw:
        key=(row['date'],row['orbit_regime_sensor_hosts'],float(row['requested_outage_rate']))
        if key in rows:raise ValueError('Duplicate daily response')
        rows[key]=row
        for metric in METRICS:
            if not np.isfinite(float(row[metric])) or not 0<=float(row[metric])<=1:raise ValueError('Invalid metric')
    if set(rows)!={(d,r,p) for d in dates for r in REGIMES for p in (0.,.2)}:
        raise ValueError('Daily response grid is incomplete')
    if (temporal['resampling']['block_lengths_days']!=list(LENGTHS)
            or temporal['resampling']['replicates']!=10000
            or temporal['resampling']['seed']!=20261011):
        raise ValueError('Temporal bootstrap design differs')
    vectors=annual=intervals=0
    for regime_index,regime in enumerate(REGIMES):
        if set(temporal['effects'][regime])!=set(METRICS):raise ValueError('Reported metric grid differs')
        for metric_index,metric in enumerate(METRICS):
            values=np.array([float(rows[d,regime,.2][metric])-float(rows[d,regime,0.][metric]) for d in dates])
            target=temporal['effects'][regime][metric]
            np.testing.assert_allclose(target['mean'],values.sum()/len(values),atol=1e-12,rtol=0)
            np.testing.assert_allclose(target['date_sd'],np.sqrt(np.sum((values-values.mean())**2)/(len(values)-1)),atol=1e-12,rtol=0)
            years=sorted({date[:4] for date in dates})
            if set(target['annual_means'])!=set(years) or set(target['moving_block_ci95'])!=set(map(str,LENGTHS)):
                raise ValueError('Reported annual or block grid differs')
            for year in years:
                subset=values[[d[:4]==year for d in dates]]
                np.testing.assert_allclose(target['annual_means'][year],subset.sum()/len(subset),atol=1e-12,rtol=0);annual+=1
            for block_index,length in enumerate(LENGTHS):
                seed=20261011+block_index+100*regime_index+1000*metric_index
                expected=circular_interval(values,length,replicates=10000,seed=seed)
                np.testing.assert_allclose(target['moving_block_ci95'][str(length)],expected,atol=1e-12,rtol=0);intervals+=1
            vectors+=1
        print(f'Daily temporal statistics independently reproduced: {regime}',flush=True)
    result={'status':'passed_all_daily_temporal_statistics','dates':len(dates),'response_rows':len(rows),
        'effect_vectors_checked':vectors,'annual_means_checked':annual,'block_intervals_checked':intervals,
        'source_temporal_sha256':sha256(folder/'temporal_uncertainty.json'),
        'source_summary_sha256':sha256(folder/'summary.json'),'source_responses_sha256':sha256(folder/'responses.csv'),
        'auditor_sha256':sha256(Path(__file__)),
        'scope':'All reported means, annual means and 48 circular block intervals independently recomputed from response CSV with cumulative block sums. This checks statistical reproducibility, not interval coverage under nonstationarity, physical sensor validity or unsampled tasking actions.'}
    (folder/'independent_temporal_audit.json').write_text(json.dumps(result,indent=2)+'\n');return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--input',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(audit(args.input),indent=2))
