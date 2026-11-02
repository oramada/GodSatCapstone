"""Compare exact source-window occupancy with the fitted tasking Markov reference."""
from __future__ import annotations

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))


import argparse
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[2]


def source_window_distribution(masks, steps=60):
    masks = np.asarray(masks, dtype=bool)
    if masks.ndim != 2 or not len(masks) or not 1 <= steps <= masks.shape[1]:
        raise ValueError('Require complete daily masks and a valid within-day window')
    prefix = np.pad(np.cumsum(masks, axis=1, dtype=np.int32), ((0,0),(1,0)))
    counts = prefix[:, steps:]-prefix[:, :-steps]
    histogram = np.bincount(counts.ravel(), minlength=steps+1)
    return histogram, histogram/histogram.sum()


def markov_occupancy(rate, persistence, steps=60):
    if not 0<rate<1 or not 0<=persistence<1 or steps<1:
        raise ValueError('Invalid stationary two-state model')
    entry = rate*(1-persistence)/(1-rate)
    if not 0<=entry<=1:raise ValueError('Invalid stationary entry probability')
    available, missing = np.zeros(steps+1), np.zeros(steps+1)
    available[0], missing[1] = 1-rate, rate
    for _ in range(1, steps):
        next_available = available*(1-entry)+missing*(1-persistence)
        next_missing = np.zeros_like(missing)
        next_missing[1:] = available[:-1]*entry+missing[:-1]*persistence
        available, missing = next_available, next_missing
    return available+missing


def analyze(data, output):
    paths = [data/'dropout_profile_1minute.json', data/'dropout_masks_independent_audit.json',
             data/'dropout_masks_1minute.npz']
    profile, audit = [json.loads(path.read_text()) for path in paths[:2]]
    sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    if (audit.get('status') != 'passed_independent_source_replay'
            or audit.get('source_profile_sha256') != sha(paths[0])
            or audit.get('mask_archive_sha256') != sha(paths[2]) or audit.get('cadence_seconds') != 60):
        raise ValueError('Current source masks and profile must pass their independent audit')
    with np.load(paths[2], allow_pickle=False) as archive:
        masks = archive['dropout'].astype(bool)
    counts, empirical = source_window_distribution(masks)
    rate = profile['one_minute_attitude_solution_dropout_rate']
    persistence = profile['simulator_markov_persistence_parameter']
    fitted = markov_occupancy(rate,persistence)
    indices = np.arange(61)
    interior_runs = []
    for row in masks:
        edges = np.flatnonzero(np.diff(np.r_[False,row,False].astype(np.int8)))
        interior_runs.extend(end-start for start,end in zip(edges[::2],edges[1::2]) if start>0 and end<len(row))
    result = {'status': 'completed_exact_source_window_and_markov_comparison',
        'steps_per_window': 60, 'overlapping_source_window_count': int(counts.sum()),
        'source_minute_fraction': float(masks.mean()),
        'uniform_within_day_window_expected_fraction': float(empirical@indices/60),
        'fitted_stationary_expected_fraction': float(fitted@indices/60),
        'empirical_zero_unavailable_probability': float(empirical[0]),
        'markov_zero_unavailable_probability': float(fitted[0]),
        'empirical_all_unavailable_probability': float(empirical[-1]),
        'markov_all_unavailable_probability': float(fitted[-1]),
        'descriptive_total_variation_distance': float(np.abs(empirical-fitted).sum()/2),
        'empirical_count_histogram': counts.tolist(), 'fitted_count_probabilities': fitted.tolist(),
        'interior_minute_sampled_unavailable_runs': len(interior_runs),
        'interior_runs_shorter_than_ten_minute_samples': int(sum(length<10 for length in interior_runs)),
        'source_receipts': [{'path':str(path),'sha256':sha(path)} for path in paths],
        'scope': 'Exact descriptive distribution over all overlapping 60-minute windows wholly inside published days. Those windows are not independent observations. Markov reference uses the fitted stationary rate and persistence with the tasking simulator initial-state convention. No hypothesis-test p-value or hardware outage inference is implied. Source masks can contain short interior sampled runs; a strict ten-minute-only interpretation is not imposed.'}
    output.mkdir(parents=True,exist_ok=True)
    (output/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    fig,ax = plt.subplots(figsize=(9,4),layout='constrained')
    ax.plot(indices,np.where(empirical>0,empirical,np.nan),'o',markersize=3,
            label='Overlapping published source windows',color='#0072B2')
    ax.plot(indices,np.where(fitted>0,fitted,np.nan),label='Fitted stationary Markov reference',color='#D55E00')
    ax.set(yscale='log',xlabel='Unavailable minute samples in a 60-minute window',
           ylabel='Probability mass (log scale)',title='CASSIOPE source-window occupancy and Markov approximation')
    ax.grid(axis='y',alpha=.2);ax.legend(frameon=False,fontsize=9);ax.spines[['right','top']].set_visible(False)
    fig.savefig(output/'hour_window_distribution.svg');fig.savefig(output/'hour_window_distribution.png',dpi=220);plt.close(fig)
    text = ['# Source-window model sensitivity','',result['scope'],'',
        '| Quantity | Empirical source windows | Fitted Markov reference |','|---|---:|---:|',
        f"| Mean unavailable fraction | {100*result['uniform_within_day_window_expected_fraction']:.4f}% | {100*result['fitted_stationary_expected_fraction']:.4f}% |",
        f"| No unavailable minutes | {result['empirical_zero_unavailable_probability']:.6g} | {result['markov_zero_unavailable_probability']:.6g} |",
        f"| All 60 minutes unavailable | {result['empirical_all_unavailable_probability']:.6g} | {result['markov_all_unavailable_probability']:.6g} |",'',
        '![Hour-window occupancy](hour_window_distribution.png)','',
        'Uniform within-day window sampling weights interior minute positions differently from day edges, so its exact expected fraction can differ slightly from the unweighted minute fraction. The tasking comparison must retain the observed attempt-loss fraction as well as the nominal pooled rate. Occupancy differences describe a limitation of the pooled first-order approximation; the two replay campaigns are sensitivity analyses, not reconstructed fleet service.']
    (output/'report.md').write_text('\n'.join(text)+'\n')
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data',type=Path,default=ROOT/'data/attitude/cassiope_epop')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();x=analyze(args.data,args.output)
    print(json.dumps({k:v for k,v in x.items() if not isinstance(v,(list,dict))},indent=2))


if __name__=='__main__':main()
