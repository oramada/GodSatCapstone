"""Add date-clustered uncertainty to a completed simulated dropout campaign."""

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))

import csv
import hashlib
import json
import math
import pathlib
import sys
import numpy as np
from scipy.stats import t

BOOTSTRAP_SAMPLES=5000
DATE_BLOCK_LENGTHS=(3,6,12)


def interval(values):
    x=np.asarray(values,float);n=len(x)
    return float(x.mean()),float(t.ppf(.975,n-1)*x.std(ddof=1)/np.sqrt(n)) if n>1 else None


def moving_block_interval(values,block_length,samples=BOOTSTRAP_SAMPLES,seed=0):
    """Return percentile limits from a non-circular moving-block bootstrap."""
    x=np.asarray(values,float);n=len(x)
    if n==0 or block_length<1 or block_length>n or samples<1:
        raise ValueError('values, block length, and bootstrap sample count must be positive and in range')
    rng=np.random.default_rng(seed)
    blocks=math.ceil(n/block_length)
    starts=rng.integers(0,n-block_length+1,size=(samples,blocks))
    offsets=np.arange(block_length)
    indices=(starts[:,:,None]+offsets).reshape(samples,-1)[:,:n]
    means=x[indices].mean(axis=1)
    lower,upper=np.quantile(means,[.025,.975])
    return float(lower),float(upper)


def paired_differences(treatment_rows, baseline_rows, metric):
    """Match simulation replicates within each frozen model checkpoint."""
    def keyed(rows):
        result={}
        for row in rows:
            key=(int(row.get('model_seed') or 0),int(row['replicate']))
            if key in result:
                raise ValueError(f'duplicate model-seed/replicate pair: {key}')
            result[key]=float(row[metric])
        return result

    treatment=keyed(treatment_rows);baseline=keyed(baseline_rows)
    if not treatment or treatment.keys()!=baseline.keys():
        raise ValueError('treatment and zero-dropout rows do not have matching model-seed/replicate pairs')
    return [treatment[key]-baseline[key] for key in sorted(treatment)]


def main():
    if len(sys.argv)!=2: raise SystemExit('usage: analyze_dropout.py OUTPUT_FOLDER')
    folder=pathlib.Path(sys.argv[1]);summary_path=folder/'dropout_summary.json'
    summary=json.loads(summary_path.read_text())
    rows=list(csv.DictReader((folder/'dropout_responses.csv').open()))
    dates=summary['dates'];rates=summary['rates'];modes=summary['modes']
    if 'orbit_regimes' not in summary:
        summary['orbit_regimes']=['leo']
        summary['replicates_per_date_regime_mode_rate']=summary.pop('replicates_per_date_mode_rate',summary.get('replicates_per_date_regime_mode_rate',20))
        summary['metrics']={f"leo:{mode}:{rate:g}":summary['metrics'][f'{mode}:{rate:g}'] for mode in modes for rate in rates}
        summary['paired_vs_zero_dropout']={f"leo:{mode}:{metric}":summary['paired_vs_zero_dropout'][f'{mode}:{metric}'] for mode in modes for metric in ['custody_continuity','observable_custody','slew_energy_proxy','false_track_proxy']}
        for row in rows: row['regime']='leo'
    regimes=summary['orbit_regimes']
    metrics=['custody_continuity','observable_custody','slew_energy_proxy','false_track_proxy','conflict_rate','dropout_rate_observed']
    by_condition={}
    for row in rows:
        key=(row['date'],row['regime'],row['mode'],float(row['dropout_probability']))
        by_condition.setdefault(key,[]).append(row)
    for regime in regimes:
      for mode in modes:
       for rate in rates:
        key=f'{regime}:{mode}:{rate:g}'
        for metric in metrics:
         daily=[]
         for date in dates:
          subset=by_condition.get((date,regime,mode,float(rate)),[])
          if not subset:raise ValueError(f'missing treatment rows for {date} {regime} {mode} {rate:g}')
          daily.append(np.mean([float(r[metric]) for r in subset]))
         mean,ci=interval(daily);summary['metrics'][key][metric]['date_clustered_mean']=mean
         summary['metrics'][key][metric]['date_clustered_ci95_half_width']=ci
         summary['metrics'][key][metric]['n_dates']=len(daily)
       for metric in ['custody_continuity','observable_custody','slew_energy_proxy','false_track_proxy']:
        effect_key=f'{regime}:{mode}:{metric}'
        for rate in rates:
         daily=[]
         for date in dates:
          treatment=by_condition.get((date,regime,mode,float(rate)),[])
          baseline=by_condition.get((date,regime,mode,0.),[])
          daily.append(np.mean(paired_differences(treatment,baseline,metric)))
         mean,ci=interval(daily);target=summary['paired_vs_zero_dropout'][effect_key][str(rate)]
         target['date_clustered_mean_change']=mean;target['date_clustered_ci95_half_width']=ci;target['n_dates']=len(daily)
         block_intervals={}
         for block_length in DATE_BLOCK_LENGTHS:
          if block_length>len(daily):continue
          seed_material=f'{regime}|{mode}|{metric}|{rate:g}|{block_length}'.encode()
          seed=int.from_bytes(hashlib.sha256(seed_material).digest()[:4],'big')
          lower,upper=moving_block_interval(daily,block_length,seed=seed)
          block_intervals[str(block_length)]={'lower':lower,'upper':upper,
              'half_width':(upper-lower)/2,'bootstrap_samples':BOOTSTRAP_SAMPLES}
         target['moving_block_bootstrap_ci95_by_date_block']=block_intervals
    summary['uncertainty_note']='Pooled intervals treat simulation-seed, model-training-seed, and date runs as independent. Date-clustered intervals pair on both model-training seed and simulation replicate, then average those paired differences within each fixed historical date; n_dates is the number of sampled date windows. Moving-block bootstrap intervals resample adjacent sampled dates in non-circular blocks of 3, 6, and 12 windows to show sensitivity to temporal correlation; they are a sensitivity analysis, not independent new observations.'
    summary_path.write_text(json.dumps(summary,indent=2,allow_nan=False)+'\n')
    lines=['# Simulated sensor-dropout study','',summary['interpretation'],'',
      f"Frozen policy: `{summary['policy']}`. Dates: {', '.join(d[:10] for d in dates)}. Regimes: {', '.join(regimes)}. {summary['replicates_per_date_regime_mode_rate']} paired simulation replicates per date, frozen checkpoint, and regime-condition across {summary.get('model_checkpoint_count', 1)} frozen checkpoint(s).",'',
      f"Dropout is applied to eligible, conflict-free assigned observations. Custody is the fraction of modeled targets remaining within the configured custody interval. Slew is a normalized angle proxy; false-track is a failed-observation proxy. Neither represents calibrated hardware telemetry. Confidence intervals below treat the {len(dates)} sampled historical dates as independent clusters, averaging matched model checkpoints and simulation seeds within each date first.",'',
      '| Orbit | Outage process | Requested rate | Observed rate | Mean custody | Custody change vs 0% (date-clustered 95% CI) |','|---|---|---:|---:|---:|---:|']
    for regime in regimes:
      for mode in modes:
       for rate in rates:
        key=f'{regime}:{mode}:{rate:g}';metric=summary['metrics'][key];effect=summary['paired_vs_zero_dropout'][f'{regime}:{mode}:custody_continuity'][str(rate)]
        lines.append(f"| {regime.upper()} | {mode} | {rate:.0%} | {metric['dropout_rate_observed']['date_clustered_mean']:.1%} | {metric['custody_continuity']['date_clustered_mean']:.3f} | {effect['date_clustered_mean_change']:+.3f} ± {effect['date_clustered_ci95_half_width']:.3f} |")
    if len(dates)>=max(DATE_BLOCK_LENGTHS) and 0.2 in rates:
      lines += ['', 'At 20% burst dropout, paired custody-effect sensitivity to temporal dependence (bootstrap blocks are consecutive sampled dates):','',
        '| Orbit | Mean change | 3-date block 95% interval | 6-date block 95% interval | 12-date block 95% interval |','|---|---:|---:|---:|---:|']
      for regime in regimes:
        effect=summary['paired_vs_zero_dropout'][f'{regime}:burst:custody_continuity']['0.2']
        block=effect['moving_block_bootstrap_ci95_by_date_block']
        formatted=[]
        for length in DATE_BLOCK_LENGTHS:
          ci=block[str(length)]
          formatted.append(f"[{ci['lower']:+.3f}, {ci['upper']:+.3f}]")
        lines.append(f"| {regime.upper()} | {effect['date_clustered_mean_change']:+.3f} | "+' | '.join(formatted)+' |')
      lines += ['', 'Moving-block intervals preserve short-range ordering within each resampled block and complement the date-clustered t intervals above.']
    lines += ['', 'Orbit classes use approximate mean-element bins, with high eccentricity taking precedence. This estimates one frozen policy’s response to injected sensor outages; it does not establish real sensor outage behavior, attitude knowledge, or operational constellation performance. The sampled dates are discrete historical snapshots, not continuous four-year playback.']
    (folder/'dropout_report.md').write_text('\n'.join(lines)+'\n')
    print(f'Added date-clustered intervals and refreshed {folder}/dropout_report.md')

if __name__=='__main__':main()
