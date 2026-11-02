"""Assess temporal dependence in the published-day attitude availability estimate."""
from __future__ import annotations

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))


import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]


def block_interval(values, length, replicates=5000, seed=20261024):
    values = np.asarray(values, dtype=float)
    if not 1 <= length <= len(values) or replicates < 1 or not np.isfinite(values).any():
        raise ValueError('Require observed data, a valid calendar block length and positive replicates')
    rng = np.random.default_rng(seed)
    means = []
    offsets = np.arange(length)
    blocks = (len(values)+length-1)//length
    for _ in range(replicates):
        starts = rng.integers(0, len(values)-length+1, size=blocks)
        sample = values[(starts[:, None]+offsets).ravel()[:len(values)]]
        available = sample[np.isfinite(sample)]
        if len(available):
            means.append(float(available.mean()))
    if len(means) != replicates:
        raise ValueError('A resampled calendar window contains no observed days')
    return {'calendar_block_days': length, 'replicates': replicates, 'seed': seed,
            'interval_quantiles': [.025, .975], 'ci95': np.quantile(means, [.025, .975]).tolist()}


def analyze(data, replicates=5000):
    profile_path = data/'dropout_profile_1minute.json'
    coverage_path = data/'archive_coverage_bounds.json'
    profile = json.loads(profile_path.read_text()); coverage = json.loads(coverage_path.read_text())
    manifest = json.loads((data/'manifest.json').read_text())
    if coverage.get('status') != 'passed_date_reconciliation_and_missingness_bounds':
        raise ValueError('Complete calendar reconciliation is required')
    first = dt.date.fromisoformat(manifest['requested_start_utc'])
    end = dt.date.fromisoformat(manifest['requested_end_exclusive_utc'])
    days = (end-first).days
    values = np.full(days, np.nan)
    for row in profile['per_day']:
        index = (dt.date.fromisoformat(row['date'])-first).days
        if not 0 <= index < days or np.isfinite(values[index]):
            raise ValueError('Profile contains out-of-window or duplicate calendar days')
        values[index] = row['dropout_minutes']/row['samples']
    if int(np.isfinite(values).sum()) != coverage['published_days']:
        raise ValueError('Calendar mask and audited observed-day count differ')
    if not np.isclose(np.nanmean(values),profile['one_minute_attitude_solution_dropout_rate'],atol=1e-14,rtol=0):
        raise ValueError('Calendar estimate differs from audited profile')
    dates = [first+dt.timedelta(days=index) for index in range(days)]
    yearly = []
    for year in range(first.year, end.year+1):
        subset = values[[day.year == year for day in dates]]
        if not len(subset):continue
        yearly.append({'year': year, 'requested_days': len(subset),
            'published_days': int(np.isfinite(subset).sum()),
            'unpublished_days': int(np.isnan(subset).sum()),
            'published_sample_unavailability_fraction': float(np.nanmean(subset))})
    result = {'status': 'completed_calendar_block_uncertainty_sensitivity',
        'estimate_published_sample_fraction': float(np.nanmean(values)),
        'iid_published_day_bootstrap_ci95': profile['one_minute_dropout_rate_date_cluster_bootstrap_ci95'],
        'calendar_block_bootstrap': [block_interval(values, length, replicates) for length in [7, 30, 90]],
        'yearly_observed_estimates': yearly,
        'source_receipts': [{'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
                            for path in [profile_path, coverage_path]],
        'scope': 'Sensitivity of the observed-day mean to resampling consecutive calendar-day blocks. Unpublished days remain unknown and are omitted from each resample denominator. These are conditional resampling intervals, not whole-window missing-data bounds, hardware outage probabilities or prospective guarantees. Across-year differences can violate stationary-process assumptions; the block lengths are sensitivity choices, not data-calibrated correlation lengths.'}
    (data/'temporal_uncertainty_1minute.json').write_text(json.dumps(result, indent=2)+'\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=ROOT/'data/attitude/cassiope_epop')
    parser.add_argument('--replicates', type=int, default=5000)
    args = parser.parse_args(); print(json.dumps(analyze(args.data, args.replicates), indent=2))


if __name__ == '__main__':
    main()
