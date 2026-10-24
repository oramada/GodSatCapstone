"""Independently audit persisted multi-date robustness evaluation results."""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import math
import pathlib

import numpy as np
from scipy.stats import t as student_t


METRICS = ['objective', 'custody_continuity', 'observable_custody',
           'slew_energy_proxy', 'false_track_proxy', 'conflict_rate']


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def audit(output: pathlib.Path) -> dict:
    output = output.expanduser().resolve()
    manifest = json.loads((output / 'manifest.json').read_text())
    if manifest.get('status') != 'completed':
        raise RuntimeError('Robustness run is not marked completed')
    design = manifest['design']
    dates, regimes = design['dates'], design['regimes']
    policies, seeds = design['policies'], [int(seed) for seed in design['seeds']]
    expected = {(date, regime, policy, seed)
                for date in dates for regime in regimes
                for policy in policies for seed in seeds}

    with (output / 'responses.csv').open(newline='') as stream:
        rows = list(csv.DictReader(stream))
    index = {}
    duplicate_keys = []
    invalid_metrics = []
    fallback_rows = 0
    for line_number, row in enumerate(rows, start=2):
        key = (row['date'], row['regime'], row['configuration'], int(row['seed']))
        if key in index:
            duplicate_keys.append(key)
        index[key] = row
        fallback_rows += str(row.get('sensor_host_fallback_to_all', '')).lower() == 'true'
        for metric in METRICS:
            try:
                if not math.isfinite(float(row[metric])):
                    raise ValueError('non-finite')
            except (KeyError, ValueError, TypeError):
                invalid_metrics.append({'line': line_number, 'metric': metric})

    keys = set(index)
    missing, unexpected = sorted(expected - keys), sorted(keys - expected)
    completed_cells = {(cell['date'], cell['regime'])
                       for cell in manifest.get('completed_cells', [])}
    expected_cells = {(date, regime) for date in dates for regime in regimes}
    duplicate_cells = len(manifest.get('completed_cells', [])) != len(completed_cells)
    unavailable = manifest.get('unavailable_cells', [])

    campaign = pathlib.Path(design['campaign']).resolve()
    hash_checks = {}
    for filename, expected_hash in design['checkpoint_sha256'].items():
        path = campaign / 'models' / filename
        observed_hash = sha256(path) if path.is_file() else None
        hash_checks[filename] = {'expected': expected_hash, 'observed': observed_hash,
                                 'matches': observed_hash == expected_hash}

    # Recompute matched policy contrasts from raw rows, clustering by date.
    comparisons = {}
    baseline = 'baseline'
    for policy in policies:
        if policy == baseline:
            continue
        comparisons[policy] = {}
        for metric in METRICS:
            date_means = []
            for date in dates:
                paired = []
                for regime in regimes:
                    for seed in seeds:
                        a = index.get((date, regime, baseline, seed))
                        b = index.get((date, regime, policy, seed))
                        if a is not None and b is not None:
                            paired.append(float(b[metric]) - float(a[metric]))
                if paired:
                    date_means.append(float(np.mean(paired)))
            n = len(date_means)
            half = (float(student_t.ppf(.975, n - 1) * np.std(date_means, ddof=1)
                           / math.sqrt(n)) if n > 1 else None)
            comparisons[policy][metric] = {
                'paired_change_vs_baseline': float(np.mean(date_means)) if n else None,
                'date_clustered_ci95_half_width': half,
                'n_independent_dates': n,
            }

    summary_matches = True
    saved = manifest.get('date_clustered_comparisons', {})
    for policy, metric_rows in comparisons.items():
        for metric, result in metric_rows.items():
            prior = saved.get(policy, {}).get(metric, {})
            for field in ('paired_change_vs_baseline', 'date_clustered_ci95_half_width'):
                value, reference = result[field], prior.get(field)
                if value is None or reference is None:
                    summary_matches &= value is reference
                else:
                    summary_matches &= math.isclose(value, float(reference),
                                                    rel_tol=1e-11, abs_tol=1e-12)
            summary_matches &= result['n_independent_dates'] == prior.get('n_independent_dates')

    valid = (len(rows) == len(expected) and not duplicate_keys and not missing
             and not unexpected and not invalid_metrics and fallback_rows == 0
             and completed_cells == expected_cells and not duplicate_cells
             and not unavailable
             and all(item['matches'] for item in hash_checks.values())
             and summary_matches)
    report = {
        'status': 'completed_valid' if valid else 'failed_validation',
        'audited_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'design_signature': manifest.get('design_signature'),
        'dimensions': {'dates': len(dates), 'regimes': len(regimes),
                       'policies': len(policies), 'seeds_per_policy': len(seeds),
                       'expected_rows': len(expected), 'observed_rows': len(rows)},
        'row_audit': {'unique_design_rows': len(keys), 'duplicate_rows': len(duplicate_keys),
                      'missing_rows': len(missing), 'unexpected_rows': len(unexpected),
                      'invalid_metric_values': len(invalid_metrics),
                      'fallback_rows': fallback_rows},
        'cell_audit': {'expected_cells': len(expected_cells),
                       'observed_cells': len(completed_cells),
                       'duplicate_cells': duplicate_cells,
                       'unavailable_cells': len(unavailable)},
        'checkpoint_hashes': hash_checks,
        'independent_date_clustered_comparisons': comparisons,
        'saved_comparison_summary_matches': bool(summary_matches),
    }
    path = output / 'independent_integrity_audit.json'
    temp = path.with_suffix('.json.tmp')
    temp.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    temp.replace(path)
    if not valid:
        raise AssertionError(f'Robustness validation integrity audit failed; see {path}')
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=pathlib.Path,
                        help='Completed robustness output directory')
    args = parser.parse_args()
    result = audit(args.output)
    print(json.dumps({'status': result['status'], 'dimensions': result['dimensions'],
                      'row_audit': result['row_audit'], 'cell_audit': result['cell_audit'],
                      'saved_comparison_summary_matches': result['saved_comparison_summary_matches'],
                      'output': str(args.output.resolve() / 'independent_integrity_audit.json')},
                     indent=2))


if __name__ == '__main__':
    main()
