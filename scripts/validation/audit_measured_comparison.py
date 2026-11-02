"""Independently reproduce every measured-process contrast and circular bootstrap CI."""

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

from scripts.experiments.run_dropout_campaign import sha256

REGIMES=('leo','meo','geo','heo')
METRICS=('custody_continuity','observable_custody','mean_slew_energy_proxy')


def circular_interval(values,length,replicates=5000,seed=20261024):
    values=np.asarray(values,float);n=len(values)
    if not 1<=length<=n or not np.isfinite(values).all():raise ValueError('Invalid circular bootstrap input')
    blocks=(n+length-1)//length
    starts=np.random.default_rng(seed).integers(0,n,size=(replicates,blocks))
    prefix=np.r_[0.,np.cumsum(np.r_[values,values[:length]])]
    totals=(prefix[starts[:,:-1]+length]-prefix[starts[:,:-1]]).sum(axis=1)
    tail=n-length*(blocks-1)
    totals+=prefix[starts[:,-1]+tail]-prefix[starts[:,-1]]
    return np.quantile(totals/n,[.025,.975])


def check_effect(reported,values):
    np.testing.assert_allclose(reported['weekly_effects'],values,atol=1e-12,rtol=0)
    np.testing.assert_allclose(reported['mean'],np.sum(values)/len(values),atol=1e-12,rtol=0)
    if set(reported['circular_moving_block_ci95'])!={'1','4','13'}:raise ValueError('Bootstrap grid changed')
    for length in (1,4,13):
        expected=circular_interval(values,length,seed=20261024+length)
        np.testing.assert_allclose(reported['circular_moving_block_ci95'][str(length)],expected,atol=1e-12,rtol=0)


def audit(folder,empirical,markov):
    folder=Path(folder);report=json.loads((folder/'summary.json').read_text())
    if report['status']!='completed_paired_process_comparison':raise ValueError('Completed paired comparison required')
    dates=report['dates'];rate=report['rate'];inputs={};source_summaries={}
    for label,path in [('empirical',Path(empirical)),('markov',Path(markov))]:
        for name,digest in report['source_artifacts'][label].items():
            if sha256(path/name)!=digest:raise ValueError('Comparison source changed')
        source=json.loads((path/'summary.json').read_text());source_summaries[label]=source
        source_audit=json.loads((path/'independent_audit.json').read_text())
        if (source['status']!='completed' or source['dates']!=dates
                or source_audit['status']!='passed_structural_and_statistical'
                or source_audit['dates_checked']!=len(dates)
                or source_audit['response_rows_checked']!=len(dates)*8):
            raise ValueError('Source completion/design audit differs')
        with (path/'responses.csv').open(newline='') as stream:rows=list(csv.DictReader(stream))
        indexed={}
        for row in rows:
            key=(row['date'],row['orbit_regime_sensor_hosts'],float(row['requested_outage_rate']))
            if key in indexed:raise ValueError('Duplicate source response')
            for metric in METRICS:
                if not np.isfinite(float(row[metric])) or not 0<=float(row[metric])<=1:raise ValueError('Invalid metric')
            indexed[key]=row
        if set(indexed)!={(d,r,p) for d in dates for r in REGIMES for p in (0.,rate)}:
            raise ValueError('Source CSV grid differs')
        inputs[label]=indexed
    source_hosts={label:{(r['date'],r['orbit_regime_sensor_hosts']):r['sensor_host_ids']
                         for r in value['rows'] if r['requested_outage_rate']==0}
                  for label,value in source_summaries.items()}
    if source_hosts['empirical']!=source_hosts['markov']:raise ValueError('Host identity changed across processes')
    if source_summaries['empirical']['dropout_profile']['source_profile_sha256']!=source_summaries['markov']['dropout_profile']['source_profile_sha256']:
        raise ValueError('Different fitted source profiles')
    for date in dates:
        for regime in REGIMES:
            for field in (*METRICS,'catalog_objects_in_episode','target_valid_step_count','target_observable_step_count'):
                if inputs['empirical'][date,regime,0.][field]!=inputs['markov'][date,regime,0.][field]:
                    raise ValueError('Paired baseline or denominator differs')
            for label in inputs:
                for field in ('target_valid_step_count','target_observable_step_count'):
                    if inputs[label][date,regime,0.][field]!=inputs[label][date,regime,rate][field]:
                        raise ValueError('Within-process target denominator changed')
    estimates=intervals=0
    for regime in REGIMES:
        for metric in METRICS:
            effects={label:np.array([float(rows[d,regime,rate][metric])-float(rows[d,regime,0.][metric]) for d in dates])
                     for label,rows in inputs.items()}
            for label in ('empirical','markov'):
                check_effect(report[label+'_effects'][regime][metric],effects[label]);estimates+=1;intervals+=3
            check_effect(report['markov_minus_empirical_effects'][regime][metric],effects['markov']-effects['empirical'])
            estimates+=1;intervals+=3
    for label,rows in inputs.items():
        for regime in REGIMES:
            trials=np.array([int(rows[d,regime,rate]['dropout_trials']) for d in dates])
            misses=np.array([int(rows[d,regime,rate]['dropout_misses']) for d in dates])
            if (misses<0).any() or (misses>trials).any():raise ValueError('Invalid loss denominator')
            item=report['realized_attempt_loss'][label][regime];valid=trials>0
            if item['lost_attempts']!=int(misses.sum()) or item['attempts']!=int(trials.sum()) or item['dates_without_attempts']!=int((~valid).sum()):
                raise ValueError('Attempt-loss counts differ')
            np.testing.assert_allclose(item['pooled_attempt_loss_fraction'],misses.sum()/trials.sum(),atol=1e-12,rtol=0)
            np.testing.assert_allclose(item['mean_date_attempt_loss_fraction'],np.mean(misses[valid]/trials[valid]),atol=1e-12,rtol=0)
    result={'status':'passed_all_reported_measured_comparison_statistics',
        'summary_sha256':sha256(folder/'summary.json'),'auditor_sha256':sha256(Path(__file__)),
        'dates_checked':len(dates),'paired_baseline_cells_checked':len(dates)*4,
        'effect_vectors_and_means_checked':estimates,'moving_block_intervals_checked':intervals,
        'attempt_loss_groups_checked':8,
        'scope':'Source hashes and complete response grids checked; all weekly effects, means and 108 circular moving-block intervals recomputed using cumulative block sums instead of expanded sample indices. This is a statistics audit, not independent task-assignment or orbital-truth validation.'}
    (folder/'independent_statistics_audit.json').write_text(json.dumps(result,indent=2)+'\n');return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True);parser.add_argument('--empirical',type=Path,required=True);parser.add_argument('--markov',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(audit(args.input,args.empirical,args.markov),indent=2))
