"""Evaluate saved DOE/Bayesian policies across post-training dates and regimes."""
import argparse
import csv
import hashlib
import json
import pathlib
import time

import numpy as np
import torch
from scipy.stats import t as student_t

from godsat.learning import Agent, evaluate
from godsat.scenario import load, prepare


DEFAULT_DATES = [
    '2025-02-15T00:00:00Z', '2025-05-15T00:00:00Z',
    '2025-08-15T00:00:00Z', '2025-11-15T00:00:00Z',
    '2026-02-15T00:00:00Z', '2026-05-15T00:00:00Z',
    '2026-08-15T00:00:00Z',
]
REGIMES = ['leo', 'meo', 'geo', 'heo']
LABELS = ['baseline', 'doe_recommended', 'bayesian_best']
METRICS = ['objective', 'custody_continuity', 'observable_custody',
           'slew_energy_proxy', 'false_track_proxy', 'conflict_rate']


def sha256(path):
    digest = hashlib.sha256()
    with pathlib.Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def clustered_comparisons(rows, baseline='baseline'):
    """Pair by date/regime/seed, then use date as the uncertainty cluster."""
    keys = {(r['date'], r['regime'], int(r['seed'])) for r in rows}
    index = {(r['configuration'], r['date'], r['regime'], int(r['seed'])): r for r in rows}
    result = {}
    for label in LABELS:
        if label == baseline:
            continue
        result[label] = {}
        for metric in METRICS:
            by_date = {}
            for date, regime, seed in keys:
                left = index.get((baseline, date, regime, seed))
                right = index.get((label, date, regime, seed))
                if left is not None and right is not None:
                    by_date.setdefault(date, []).append(float(right[metric]) - float(left[metric]))
            values = np.array([np.mean(v) for v in by_date.values()], dtype=float)
            n = len(values)
            margin = (float(student_t.ppf(.975, n - 1) * values.std(ddof=1) / np.sqrt(n))
                      if n > 1 else None)
            result[label][metric] = {
                'paired_change_vs_baseline': float(values.mean()) if n else None,
                'date_clustered_ci95_half_width': margin,
                'n_independent_dates': n,
                'cluster_definition': 'mean paired change across seeds and orbit regimes within date',
            }
    return result


def mean_ci(values):
    values = np.asarray(values, dtype=float)
    n = len(values)
    if not n:
        return None, None, 0
    margin = (float(student_t.ppf(.975, n - 1) * values.std(ddof=1) / np.sqrt(n))
              if n > 1 else None)
    return float(values.mean()), margin, n


def write_report(path, rows, manifest):
    comparisons = manifest['date_clustered_comparisons']
    date_count = len(manifest['design']['dates'])
    sensor_cohort = manifest['design']['campaign_config'].get('sensor_cohort', 'unspecified')
    lines = [
        '# Multi-date, multi-regime policy robustness check', '',
        f'This supplemental evaluation reuses the saved five-seed baseline, DOE-recommended, and Bayesian-selected checkpoints. It evaluates {date_count} dates outside the campaign’s designated train/validation/test dates, across LEO, MEO, GEO, and HEO scenarios. Sensor hosts use the campaign’s {sensor_cohort} catalog snapshot, backcast over the study dates; this does not establish historical operational status. The detection and dropout model remains synthetic.', '',
        f'For each paired date/regime/seed, policies see the same orbit scenario and environment seed. Confidence intervals use the {date_count} dates as clusters, averaging seeds and regimes within each date. These intervals describe temporal variation conditional on the saved checkpoints; they do not measure new between-training-seed uncertainty or real hardware performance.', '',
        '| Policy vs baseline | Custody change (95% date-clustered CI) | Observable custody | Objective | Slew proxy | False-track proxy |',
        '|---|---:|---:|---:|---:|---:|',
    ]
    for label in ('doe_recommended', 'bayesian_best'):
        fields = []
        for metric in ('custody_continuity', 'observable_custody', 'objective',
                       'slew_energy_proxy', 'false_track_proxy'):
            result = comparisons[label][metric]
            mean = result['paired_change_vs_baseline']
            half = result['date_clustered_ci95_half_width']
            fields.append(f'{mean:+.4f} ± {half:.4f}' if half is not None else f'{mean:+.4f}')
        lines.append(f"| {label.replace('_', ' ')} | " + ' | '.join(fields) + ' |')
    lines += ['', '## Custody change by orbit regime', '',
              '| Regime | Policy vs baseline | Mean change (95% date-clustered CI) | Dates |',
              '|---|---|---:|---:|']
    for regime in REGIMES:
        for label in ('doe_recommended', 'bayesian_best'):
            by_date = {}
            index = {(r['configuration'], r['date'], r['regime'], int(r['seed'])): r for r in rows}
            dates = sorted({r['date'] for r in rows if r['regime'] == regime})
            for date in dates:
                for seed in manifest['design']['seeds']:
                    left = index.get(('baseline', date, regime, int(seed)))
                    right = index.get((label, date, regime, int(seed)))
                    if left is not None and right is not None:
                        by_date.setdefault(date, []).append(
                            float(right['custody_continuity']) - float(left['custody_continuity']))
            mean, half, n = mean_ci([np.mean(v) for v in by_date.values()])
            if mean is not None:
                interval = f'{mean:+.4f} ± {half:.4f}' if half is not None else f'{mean:+.4f}'
                lines.append(f'| {regime.upper()} | {label.replace("_", " ")} | {interval} | {n} |')
    lines += ['', f"Completed responses: {len(rows)}. Expected: {len(manifest['design']['dates']) * len(REGIMES) * len(LABELS) * len(manifest['design']['seeds'])}. Sensor-host fallback cells: {manifest['fallback_cell_count']}. Unavailable date/regime cells: {len(manifest['unavailable_cells'])}.", '',
              'These results are a supplemental generalization check for this implementation. They neither reproduce the unpublished original GoDSAT baseline nor establish measured sensor dropout effectiveness.']
    pathlib.Path(path).write_text('\n'.join(lines) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign', default='outputs/full-paper-study')
    parser.add_argument('--output', default='outputs/multi-date-robustness')
    parser.add_argument('--dates', default=','.join(DEFAULT_DATES))
    args = parser.parse_args()
    campaign_dir = pathlib.Path(args.campaign).resolve()
    output = pathlib.Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    config = json.loads((campaign_dir / 'config.json').read_text())
    dates = [value.strip() for value in args.dates.split(',') if value.strip()]
    checkpoints = {}
    checkpoint_hashes = {}
    for label in LABELS:
        checkpoints[label] = []
        for seed in config['validation_seeds']:
            path = campaign_dir / 'models' / f'validate_{label}_{seed}.pt'
            if not path.is_file():
                raise FileNotFoundError(f'Missing validation checkpoint: {path}')
            saved = torch.load(path, map_location='cpu', weights_only=True)
            model = Agent(saved['obs_dim'], saved['actions'], saved['hp'])
            model.load_state_dict(saved['state_dict'])
            model.eval()
            checkpoints[label].append((seed, saved['hp'], model))
            checkpoint_hashes[path.name] = sha256(path)

    design = {'campaign': str(campaign_dir), 'campaign_config': config,
              'dates': dates, 'regimes': REGIMES, 'policies': LABELS,
              'seeds': config['validation_seeds'], 'checkpoint_sha256': checkpoint_hashes,
              'evaluation_seed_rule': 'same seed + 50000 for each matched policy/date/regime',
              'sensor_host_selection': 'Use only the configured payload sensor-host cohort; record date/regime cells with insufficient hosts as unavailable.'}
    signature = hashlib.sha256(json.dumps(design, sort_keys=True).encode()).hexdigest()
    manifest_path = output / 'manifest.json'
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text())
        if previous.get('design_signature') != signature:
            raise ValueError('Output folder contains a different robustness design; choose another output path')
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    manifest.update({'status': 'running', 'design_signature': signature, 'design': design,
                     'completed_cells': manifest.get('completed_cells', []),
                     'unavailable_cells': manifest.get('unavailable_cells', [])})
    rows_path = output / 'responses.csv'
    rows = []
    if rows_path.exists():
        with rows_path.open(newline='') as stream:
            rows = list(csv.DictReader(stream))
    done = {(r['date'], r['regime'], r['configuration'], int(r['seed'])) for r in rows}
    fallback_cells = {(r['date'], r['regime']) for r in rows
                      if str(r.get('sensor_host_fallback_to_all', '')).lower() == 'true'}
    torch.set_num_threads(1)
    for date in dates:
        for regime in REGIMES:
            cell_keys = {(date, regime, label, int(seed))
                         for label in LABELS for seed in config['validation_seeds']}
            if cell_keys.issubset(done):
                continue
            started = time.perf_counter()
            try:
                scenario_path = prepare(date, config, regime=regime)
                scenario = load(scenario_path)
            except Exception as error:
                manifest['unavailable_cells'] = [cell for cell in manifest['unavailable_cells']
                    if not (cell['date'] == date and cell['regime'] == regime)]
                manifest['unavailable_cells'].append({'date': date, 'regime': regime,
                                                       'error': f'{type(error).__name__}: {error}'})
                manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
                print(f'unavailable {date} {regime}: {error}', flush=True)
                continue
            for label in LABELS:
                for seed, hp, model in checkpoints[label]:
                    key = (date, regime, label, int(seed))
                    if key in done:
                        continue
                    evaluated, _, _ = evaluate(model, [scenario], config, hp,
                                              int(seed) + 50000)
                    row = {'date': date, 'regime': regime,
                           'configuration': label, 'seed': seed,
                           'sensor_host_fallback_to_all': False,
                           **{metric: evaluated[metric] for metric in METRICS}}
                    rows.append(row)
                    done.add(key)
                    with rows_path.open('w', newline='') as stream:
                        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
                        writer.writeheader()
                        writer.writerows(rows)
            manifest['completed_cells'] = [cell for cell in manifest['completed_cells']
                if not (cell['date'] == date and cell['regime'] == regime)]
            manifest['completed_cells'].append({'date': date, 'regime': regime,
                'sensor_host_fallback_to_all': False,
                'elapsed_seconds': round(time.perf_counter() - started, 3)})
            manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
            print(f'completed {date} {regime}', flush=True)

    complete = all((date, regime, label, int(seed)) in done
                   for date in dates for regime in REGIMES
                   for label in LABELS for seed in config['validation_seeds'])
    manifest.update({'status': 'completed' if complete else 'partial',
                     'response_rows': len(rows),
                     'fallback_cell_count': len(fallback_cells),
                     'date_clustered_comparisons': clustered_comparisons(rows)})
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
    write_report(output / 'report.md', rows, manifest)
    print(json.dumps({'status': manifest['status'], 'response_rows': len(rows),
                      'expected_rows': len(dates) * len(REGIMES) * len(LABELS) * len(config['validation_seeds']),
                      'fallback_cell_count': len(fallback_cells),
                      'unavailable_cells': len(manifest['unavailable_cells']),
                      'manifest': str(manifest_path)}, indent=2))


if __name__ == '__main__':
    main()
