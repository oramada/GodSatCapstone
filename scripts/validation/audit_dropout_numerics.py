"""Recompute dropout statistics and replay stratified frozen-policy responses.

This checks source consistency and numerical reproducibility. It does not
validate hypothetical sensor probabilities against real hardware telemetry.
"""
from __future__ import annotations

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))


import argparse
import collections
import csv
import datetime as dt
import hashlib
import io
import json
import math
from pathlib import Path

import numpy as np
from scipy.stats import t
import torch

from godsat.dropout import evaluate_policy, parse_response_row
from godsat.experiment import runtime_provenance, write_json
from godsat.learning import Agent
from godsat.orbits import ROOT
from godsat.scenario import cache_key, load
from scripts.validation.audit_dropout_results import audit as audit_design
from scripts.experiments.run_dropout_campaign import sha256

METRICS = ("custody_continuity", "observable_custody", "slew_energy_proxy",
           "false_track_proxy", "conflict_rate", "dropout_rate_observed")
PAIRED = METRICS[:4]


def interval(values):
    values = np.asarray(values, dtype=float)
    if not len(values) or not np.isfinite(values).all():
        raise ValueError("Dropout responses must be nonempty and finite")
    half = float(t.ppf(.975, len(values)-1) * values.std(ddof=1) / np.sqrt(len(values))) if len(values) > 1 else None
    return float(values.mean()), half


def reproduce_statistics(rows):
    grouped = collections.defaultdict(list)
    lookup = {}
    for row in rows:
        for metric in METRICS:
            if not math.isfinite(float(row[metric])) or not 0 <= float(row[metric]) <= 1:
                raise ValueError(f"Invalid dropout metric: {metric}")
        key = (row['date'], row['regime'], row['mode'], int(row['replicate']),
               int(row['model_seed']), float(row['dropout_probability']))
        if key in lookup:
            raise ValueError("Duplicate dropout response key")
        lookup[key] = row
        grouped[(row['regime'], row['mode'], float(row['dropout_probability']))].append(row)
    metrics, effects = {}, {}
    for (regime, mode, rate), subset in sorted(grouped.items()):
        condition = f"{regime}:{mode}:{rate:g}"
        metrics[condition] = {}
        for metric in METRICS:
            by_date = collections.defaultdict(list)
            for row in subset:
                by_date[row['date']].append(float(row[metric]))
            mean, half = interval([float(row[metric]) for row in subset])
            daily_mean, daily_half = interval([np.mean(values) for _, values in sorted(by_date.items())])
            metrics[condition][metric] = {'mean': mean, 'ci95_half_width': half, 'n': len(subset),
                'date_clustered_mean': daily_mean, 'date_clustered_ci95_half_width': daily_half,
                'n_dates': len(by_date)}
            if metric not in PAIRED:
                continue
            paired = collections.defaultdict(list)
            for row in subset:
                baseline_key = (row['date'], regime, mode, int(row['replicate']), int(row['model_seed']), 0.)
                if baseline_key not in lookup:
                    raise ValueError("Dropout response has no matched zero-outage reference")
                paired[row['date']].append(float(row[metric]) - float(lookup[baseline_key][metric]))
            differences = [value for _, values in sorted(paired.items()) for value in values]
            paired_mean, paired_half = interval(differences)
            date_mean, date_half = interval([np.mean(values) for _, values in sorted(paired.items())])
            effects.setdefault(f"{regime}:{mode}:{metric}", {})[str(rate)] = {
                'paired_mean_change': paired_mean, 'ci95_half_width': paired_half,
                'n_pairs': len(differences), 'date_clustered_mean_change': date_mean,
                'date_clustered_ci95_half_width': date_half, 'n_dates': len(paired)}
    return {'metrics': metrics, 'paired_vs_zero_dropout': effects}


def compare_statistics(reproduced, summary):
    def check(expected, actual, location):
        if isinstance(expected, dict):
            if not isinstance(actual, dict):
                raise ValueError(f"Missing summary object: {location}")
            for key, value in expected.items():
                check(value, actual.get(key), f"{location}/{key}")
        elif expected is None:
            if actual is not None:
                raise ValueError(f"Unreproduced summary interval: {location}")
        elif actual is None or not math.isclose(float(expected), float(actual), rel_tol=1e-10, abs_tol=1e-12):
            raise ValueError(f"Unreproduced summary statistic: {location}")
    for section in ('metrics', 'paired_vs_zero_dropout'):
        if set(reproduced[section]) != set(summary.get(section, {})):
            raise ValueError(f"Summary treatment groups differ: {section}")
        check(reproduced[section], summary[section], section)


def audit(output, allow_partial=False, replays_per_stratum=1):
    output = Path(output).resolve()
    integrity = audit_design(output)
    completed = integrity['status'] == 'completed_valid'
    if not completed and not (allow_partial and integrity['status'] in {'partial_checkpoint', 'all_rows_present_summary_pending'}):
        raise ValueError(f"Dropout design is not ready for this audit: {integrity['status']}")
    if replays_per_stratum < 1:
        raise ValueError("At least one source-policy replay per stratum is required")
    design_doc = json.loads((output/'dropout_design.json').read_text())
    design, config = design_doc['design'], design_doc['design']['config']
    if hashlib.sha256(json.dumps(design, sort_keys=True).encode()).hexdigest() != design_doc['design_signature']:
        raise ValueError("Dropout design content does not match its signature")
    bound = config.get('dropout_input_provenance')
    if not bound:
        raise ValueError("Byte-bound input provenance is required")
    campaign = Path(json.loads((output/'checkpoint_provenance.json').read_text())['baseline_output']) if completed else None
    if campaign is None:
        # The design's configured binding predates the final provenance file;
        # locate its actual source campaign through a saved checkpoint name.
        matches = [path.parent for path in (ROOT/'outputs').glob('*/config.json')
                   if sha256(path) == bound['campaign_config_sha256']
                   and (path.parent/'summary.json').is_file()
                   and sha256(path.parent/'summary.json') == bound['campaign_summary_sha256']]
        if len(matches) != 1:
            raise ValueError("Cannot uniquely locate the bound source campaign")
        campaign = matches[0]
    if sha256(campaign/'config.json') != bound['campaign_config_sha256'] or sha256(campaign/'summary.json') != bound['campaign_summary_sha256']:
        raise ValueError("Source campaign bytes differ from the dropout binding")
    if sha256(ROOT/'data/raw/manifest.json') != bound['raw_archive_receipt_sha256']:
        raise ValueError("Orbital archive receipt differs from the dropout binding")
    if runtime_provenance() != bound['runtime']:
        raise ValueError("Software/source version differs from the dropout binding")
    if sha256(ROOT/'scripts/experiments/run_dropout_campaign.py') != bound['orchestration_script_sha256']:
        raise ValueError("Dropout orchestration source differs from the binding")
    cohort = config.get('sensor_cohort', 'current_payload')
    cohort_manifest = ROOT/'data'/f'{cohort}_orbit_history.parquet.manifest.json'
    if cohort == 'current_payload':
        cohort_manifest = ROOT/'data/current_payload_orbit_history.manifest.json'
    expected_cohort_hash = bound.get('sensor_cohort_manifest_sha256')
    if expected_cohort_hash is not None and sha256(cohort_manifest) != expected_cohort_hash:
        raise ValueError("Sensor-cohort provenance differs from the binding")
    scenarios = {}
    for date in design['dates']:
        for regime in design['regimes']:
            path = ROOT/'data/scenarios'/f'{cache_key(date, config, regime)}.npz'
            hashes = bound['scenarios'][f'{date}:{regime}']
            if sha256(path) != hashes['arrays_sha256'] or sha256(path.with_suffix('.json')) != hashes['metadata_sha256']:
                raise ValueError(f"Scenario bytes differ for {date} {regime}")
            scenarios[(date, regime)] = path
    payload = (output/'dropout_responses.csv').read_bytes()
    rows = [parse_response_row(row) for row in csv.DictReader(io.StringIO(payload.decode()))]
    seeds = list(map(int, design.get('model_seeds', config.get('dropout_model_seeds', [101]))))
    for row in rows:
        row.setdefault('model_seed', seeds[0])
        if int(row['seed']) != int(config.get('dropout_seed', 7441)) + int(row['replicate']):
            raise ValueError("Simulation seed differs from the declared paired design")
        steps = float(row['steps'])
        attempts, trials, misses = (float(row[key]) for key in ('attempts', 'dropout_trials', 'dropout_misses'))
        if (steps != config['duration_minutes'] * 60 / config['step_seconds']
                or not 0 <= misses <= trials <= attempts <= steps * config['agents']
                or any(value != int(value) for value in (steps, attempts, trials, misses))
                or not math.isclose(float(row['dropout_rate_observed']), misses/max(trials, 1), abs_tol=1e-12)
                or (float(row['dropout_probability']) == 0 and misses != 0)
                or not math.isfinite(float(row['objective']))
                or not 0 <= float(row['valid_target_fraction']) <= 1):
            raise ValueError("Impossible dropout response counts or metrics")
    if len(rows) != integrity['rows_read']:
        raise ValueError("Response file changed during snapshot capture; retry this audit")
    statistics = reproduce_statistics(rows)
    if completed:
        compare_statistics(statistics, json.loads((output/'dropout_summary.json').read_text()))
    torch.set_num_threads(1)
    models = {}
    for seed in seeds:
        path = campaign/'models'/f'validate_doe_recommended_{seed}.pt'
        if sha256(path) != bound['checkpoints_sha256'][str(seed)]:
            raise ValueError(f"Checkpoint bytes differ for training seed {seed}")
        checkpoint = torch.load(path, map_location='cpu', weights_only=True)
        model = Agent(checkpoint['obs_dim'], checkpoint['actions'], checkpoint['hp'])
        model.load_state_dict(checkpoint['state_dict']); model.eval()
        models[seed] = (model, checkpoint['hp'])
    strata = collections.defaultdict(list)
    for row in rows:
        strata[(row['date'], row['regime'], row['mode'], float(row['dropout_probability']), int(row['model_seed']))].append(row)
    replay_keys = []
    for stratum, candidates in sorted(strata.items()):
        candidates.sort(key=lambda row: hashlib.sha256(json.dumps([stratum, row['replicate']]).encode()).hexdigest())
        for row in candidates[:replays_per_stratum]:
            model, hp = models[int(row['model_seed'])]
            actual = evaluate_policy(model, load(scenarios[(row['date'], row['regime'])]), config,
                hp, int(row['seed']), float(row['dropout_probability']), row['mode'])
            for metric, value in actual.items():
                if metric not in row or not math.isclose(float(value), float(row[metric]), rel_tol=1e-10, abs_tol=1e-12):
                    raise ValueError(f"Source-policy replay differs: {stratum} replicate {row['replicate']} {metric}")
            replay_keys.append([*stratum, int(row['replicate'])])
    snapshot_hash = hashlib.sha256(payload).hexdigest()
    (output/'numerical_audit_response_snapshot.csv').write_bytes(payload)
    result = {'status': 'completed_numerically_validated_and_sample_replayed' if completed else 'validated_partial_dropout_cells',
        'audited_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'full_study_complete': completed, 'design_signature': design_doc['design_signature'],
        'response_snapshot_sha256': snapshot_hash, 'rows_checked': len(rows),
        'completed_cells': integrity['completed_cells'], 'expected_cells': integrity['expected_cells'],
        'scenario_hash_pairs_checked': len(scenarios), 'checkpoint_hashes_checked': len(models),
        'summary_statistics_reproduced': completed, 'source_policy_replays': len(replay_keys),
        'source_policy_replay_keys': replay_keys, 'recomputed_statistics': statistics,
        'snapshot_still_current': sha256(output/'dropout_responses.csv') == snapshot_hash,
        'scope': 'All snapshot metric domains and paired statistics were checked. Policy replay covers the recorded stratified sample. This establishes numerical/source consistency, not sensor-model validity or real-world outage rates.'}
    write_json(output/'numerical_replay_audit.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--allow-partial', action='store_true')
    parser.add_argument('--replays-per-stratum', type=int, default=1)
    args = parser.parse_args()
    result = audit(args.output, args.allow_partial, args.replays_per_stratum)
    print(json.dumps({key: result[key] for key in ('status', 'rows_checked', 'completed_cells', 'source_policy_replays', 'snapshot_still_current')}, indent=2))


if __name__ == '__main__':
    main()
