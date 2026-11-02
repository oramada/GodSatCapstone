"""Independently recompute every reported date-cluster and moving-block dropout interval."""
from __future__ import annotations

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))


import argparse
import collections
import csv
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from scipy.stats import t

METRICS = ['custody_continuity', 'observable_custody', 'slew_energy_proxy',
           'false_track_proxy', 'conflict_rate', 'dropout_rate_observed']


def close(actual, expected):
    if actual is None or expected is None:
        if actual != expected:raise ValueError('Reported undefined interval differs')
    elif not math.isclose(float(actual), float(expected), abs_tol=1e-12, rel_tol=0):
        raise ValueError(f'Reported uncertainty statistic differs: {actual} != {expected}')


def block_reference(values, length, samples, seed):
    """Use cumulative block sums, independently of the report's expanded-index implementation."""
    values = np.asarray(values, dtype=float)
    n = len(values)
    if not 1 <= length <= n or samples < 1 or not np.isfinite(values).all():
        raise ValueError('Invalid moving-block reference inputs')
    blocks = (n+length-1)//length
    starts = np.random.default_rng(seed).integers(0, n-length+1, size=(samples, blocks))
    prefix = np.r_[0., np.cumsum(values)]
    totals = (prefix[starts[:, :-1]+length]-prefix[starts[:, :-1]]).sum(axis=1)
    tail = n-length*(blocks-1)
    totals += prefix[starts[:, -1]+tail]-prefix[starts[:, -1]]
    return np.quantile(totals/n, [.025, .975]).tolist()


def check_date_statistics(target, values, mean_name, expected_dates):
    values = np.asarray(values, dtype=float)
    if not np.isfinite(values).all():raise ValueError('Date estimates are nonfinite')
    close(target[mean_name], values.mean())
    half = float(t.ppf(.975, len(values)-1)*np.std(values, ddof=1)/np.sqrt(len(values))) if len(values)>1 else None
    close(target['date_clustered_ci95_half_width'], half)
    if target['n_dates'] != expected_dates:raise ValueError('Reported date-cluster count differs')


def audit(folder):
    summary_path, responses = folder/'dropout_summary.json', folder/'dropout_responses.csv'
    summary = json.loads(summary_path.read_text())
    dates, regimes, modes, rates = [summary[key] for key in ['dates', 'orbit_regimes', 'modes', 'rates']]
    if len(set(dates)) != len(dates) or not dates:raise ValueError('Duplicate or absent study dates')
    grouped = collections.defaultdict(dict)
    with responses.open(newline='') as stream:
        rows = list(csv.DictReader(stream))
    for row in rows:
        condition = (row['date'], row['regime'], row['mode'], float(row['dropout_probability']))
        pair = (int(row.get('model_seed') or 0), int(row['replicate']))
        if pair in grouped[condition]:raise ValueError('Duplicate model/replicate response')
        values = {metric: float(row[metric]) for metric in METRICS}
        if not all(math.isfinite(value) and 0<=value<=1 for value in values.values()):
            raise ValueError('Invalid normalized response metric')
        grouped[condition][pair] = values
    expected = {(date, regime, mode, float(rate)) for date in dates
                for regime in regimes for mode in modes for rate in rates}
    if set(grouped) != expected:raise ValueError('Response condition grid differs from the report')
    checked_metrics = checked_pairs = checked_blocks = 0
    for regime in regimes:
        for mode in modes:
            for rate in rates:
                for metric in METRICS:
                    daily = [np.mean([row[metric] for row in grouped[date, regime, mode, float(rate)].values()])
                             for date in dates]
                    target = summary['metrics'][f'{regime}:{mode}:{rate:g}'][metric]
                    check_date_statistics(target, daily, 'date_clustered_mean', len(dates))
                    checked_metrics += 1
                for metric in METRICS[:4]:
                    daily = []
                    for date in dates:
                        treated = grouped[date, regime, mode, float(rate)]
                        control = grouped[date, regime, mode, 0.]
                        if treated.keys() != control.keys():raise ValueError('Unmatched paired checkpoint/replicate keys')
                        daily.append(np.mean([treated[key][metric]-control[key][metric] for key in sorted(treated)]))
                    target = summary['paired_vs_zero_dropout'][f'{regime}:{mode}:{metric}'][str(rate)]
                    check_date_statistics(target, daily, 'date_clustered_mean_change', len(dates))
                    reported = target['moving_block_bootstrap_ci95_by_date_block']
                    lengths = [length for length in [3, 6, 12] if length <= len(dates)]
                    if set(reported) != set(map(str, lengths)):raise ValueError('Missing or unexpected temporal block lengths')
                    for length in lengths:
                        item = reported[str(length)]
                        if item['bootstrap_samples'] != 5000:raise ValueError('Bootstrap replicate design differs')
                        material = f'{regime}|{mode}|{metric}|{rate:g}|{length}'.encode()
                        seed = int.from_bytes(hashlib.sha256(material).digest()[:4], 'big')
                        low, high = block_reference(daily, length, item['bootstrap_samples'], seed)
                        close(item['lower'], low);close(item['upper'], high)
                        close(item['half_width'], (high-low)/2)
                        checked_blocks += 1
                    checked_pairs += 1
    result = {'status': 'passed_all_reported_temporal_uncertainty_statistics',
        'response_rows': len(rows), 'independent_dates': len(dates),
        'condition_metric_estimates_checked': checked_metrics,
        'paired_effect_estimates_checked': checked_pairs,
        'moving_block_intervals_checked': checked_blocks,
        'source_summary_sha256': hashlib.sha256(summary_path.read_bytes()).hexdigest(),
        'source_responses_sha256': hashlib.sha256(responses.read_bytes()).hexdigest(),
        'scope': 'Independently recomputes every reported date-cluster mean/t interval, matched checkpoint/replicate contrast and temporal block interval. Bootstrap reference uses cumulative block sums instead of expanded resampled indices. Complements design/source-policy replay checks; it does not validate sensor assumptions or guarantee interval coverage under nonstationarity.'}
    (folder/'uncertainty_independent_audit.json').write_text(json.dumps(result, indent=2)+'\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args();print(json.dumps(audit(args.output.resolve()), indent=2))


if __name__ == '__main__':
    main()
