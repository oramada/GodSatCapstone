"""Audit completeness and compute provenance for one DOE campaign output."""

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))

import argparse
import csv
import hashlib
import json
import math
import pathlib


def load_json(path):
    return json.loads(pathlib.Path(path).read_text())


def read_csv(path):
    with pathlib.Path(path).open(newline='') as stream:
        return list(csv.DictReader(stream))


def sha256(path):
    digest = hashlib.sha256()
    with pathlib.Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def audit(root):
    root = pathlib.Path(root).expanduser().resolve()
    config = load_json(root / 'config.json')
    summary = load_json(root / 'summary.json')
    screen_count = 16
    rsm_count = 8 + 6 + int(config.get('response_surface_center_replicates', 1))
    bayes_count = screen_count + rsm_count
    validation_seeds = list(map(int, config['validation_seeds']))
    validation_names = [
        f'validate_{label}_{seed}'
        for label in ('baseline', 'doe_recommended', 'bayesian_best')
        for seed in validation_seeds
    ]
    treatment_names = (
        [f'screen_{i:02d}' for i in range(screen_count)]
        + [f'rsm_{i:02d}' for i in range(rsm_count)]
        + [f'bo_{i:02d}' for i in range(bayes_count)]
    )
    expected_names = set(treatment_names + validation_names)
    run_paths = {path.stem: path for path in (root / 'runs').glob('*.json')}
    missing_runs = sorted(expected_names - set(run_paths))
    unexpected_runs = sorted(set(run_paths) - expected_names)
    if missing_runs or unexpected_runs:
        raise ValueError(f'Run files differ from design: missing={missing_runs}, unexpected={unexpected_runs}')

    response_rows = read_csv(root / 'responses.csv')
    response_names = [row['name'] for row in response_rows]
    if len(response_rows) != len(treatment_names) or set(response_names) != set(treatment_names):
        raise ValueError('responses.csv does not contain each screening, CCD, and Bayesian treatment exactly once')
    screen_design = read_csv(root / 'screening_design.csv')
    rsm_design = read_csv(root / 'rsm_design.csv')
    if len(screen_design) != screen_count or sorted(int(row['run']) for row in screen_design) != list(range(screen_count)):
        raise ValueError('screening_design.csv is incomplete or duplicated')
    if len(rsm_design) != rsm_count or sorted(int(row['run']) for row in rsm_design) != list(range(rsm_count)):
        raise ValueError('rsm_design.csv is incomplete or duplicated')

    validation = read_csv(root / 'validation.csv')
    expected_validation = {
        (label, seed)
        for label in ('baseline', 'doe_recommended', 'bayesian_best', 'greedy', 'random')
        for seed in validation_seeds
    }
    validation_pairs = [(row['configuration'], int(row['seed'])) for row in validation]
    if len(validation) != len(expected_validation) or set(validation_pairs) != expected_validation:
        raise ValueError('validation.csv lacks an exact five-seed held-out comparison for each policy')

    device = config.get('compute_device', 'cpu')
    if summary.get('status') != 'completed':
        raise ValueError('Campaign summary is not marked completed')
    if (summary.get('screening_runs'), summary.get('rsm_runs'), summary.get('bayesian_runs')) != (
        screen_count, rsm_count, bayes_count
    ):
        raise ValueError('Campaign summary run counts disagree with the design')
    if summary.get('validation_retrains') != len(validation_names):
        raise ValueError('Campaign summary validation retrain count is incorrect')

    per_run = {}
    for name, path in run_paths.items():
        record = load_json(path)
        expected_device_prefix = 'mps' if device == 'mps' else device
        if not str(record.get('compute_device', '')).startswith(expected_device_prefix):
            raise ValueError(f'{name} compute device {record.get("compute_device")} disagrees with config {device}')
        gpu_seconds = float(record['gpu_active_seconds'])
        gpu_hours = float(record['gpu_hours'])
        if not math.isfinite(gpu_seconds + gpu_hours) or gpu_seconds < 0 or gpu_hours < 0:
            raise ValueError(f'{name} has invalid accelerator time')
        if not math.isclose(gpu_hours, gpu_seconds / 3600, rel_tol=1e-10, abs_tol=1e-14):
            raise ValueError(f'{name} GPU-hours disagree with measured device-active seconds')
        if device == 'mps' and gpu_seconds <= 0:
            raise ValueError(f'{name} has no measured MPS-active time')
        if device == 'cpu' and gpu_seconds != 0:
            raise ValueError(f'{name} reports GPU activity for a CPU campaign')
        if record.get('energy_estimate_kwh') is not None:
            raise ValueError(f'{name} reports energy without an available calibrated energy meter')
        per_run[name] = {'compute_device': record['compute_device'],
                         'gpu_active_seconds': gpu_seconds, 'gpu_hours': gpu_hours,
                         'checkpoint_sha256': sha256(root / 'models' / f'{name}.pt')}

    for row in validation:
        learned = row['configuration'] in {'baseline', 'doe_recommended', 'bayesian_best'}
        gpu_hours = float(row['gpu_hours'])
        if not math.isfinite(gpu_hours) or gpu_hours < 0:
            raise ValueError('validation.csv contains invalid GPU-hours')
        if device == 'mps' and learned and gpu_hours <= 0:
            raise ValueError(f"{row['configuration']} seed {row['seed']} has no MPS time")
        if device == 'cpu' and gpu_hours != 0:
            raise ValueError(f"{row['configuration']} seed {row['seed']} reports GPU time for a CPU campaign")
        if row.get('energy_estimate_kwh') not in {'', 'None', None}:
            raise ValueError('validation.csv reports unavailable energy as a value')

    primary_gpu_hours = sum(per_run[name]['gpu_hours'] for name in treatment_names)
    validation_gpu_hours = sum(
        float(row['gpu_hours']) for row in validation
        if row['configuration'] in {'baseline', 'doe_recommended', 'bayesian_best'}
    )
    expected_gpu_hours = primary_gpu_hours + validation_gpu_hours
    if not math.isclose(float(summary.get('total_gpu_hours', -1)), expected_gpu_hours,
                        rel_tol=1e-10, abs_tol=1e-12):
        raise ValueError('Summary total GPU-hours do not match persisted treatment and validation records')
    if summary.get('energy_estimates_available') is not False:
        raise ValueError('Summary must explicitly disclose unavailable calibrated energy estimates')
    accelerator_time_check = all(
        (per_run[name]['gpu_active_seconds'] > 0 if device == 'mps'
         else per_run[name]['gpu_active_seconds'] == 0)
        for name in expected_names
    )

    result = {
        'status': 'completed',
        'output': str(root),
        'compute_device': device,
        'screening_treatments': screen_count,
        'ccd_treatments': rsm_count,
        'bayesian_treatments': bayes_count,
        'validation_retrains': len(validation_names),
        'heldout_policy_seed_rows': len(validation),
        'treatment_rows_in_responses': len(response_rows),
        'checkpoint_count': len(per_run),
        'total_gpu_active_hours': expected_gpu_hours,
        'calibrated_energy_available': False,
        'checks': {
            'planned_run_files_exactly_once': True,
            'design_csv_rows_complete': True,
            'responses_csv_rows_complete': True,
            'five_seed_heldout_rows_complete': True,
            'all_checkpoints_exist_and_hashed': True,
            'device_time_matches_gpu_hours': True,
            'accelerator_time_matches_campaign_device': accelerator_time_check,
            'summary_compute_time_reconciles': True,
            'unavailable_energy_disclosed': True,
        },
        'runs': per_run,
    }
    path = root / 'campaign_integrity_audit.json'
    path.write_text(json.dumps(result, indent=2) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, help='campaign output folder')
    args = parser.parse_args()
    result = audit(args.output)
    print(json.dumps({key: value for key, value in result.items() if key != 'runs'}, indent=2))


if __name__ == '__main__':
    main()
