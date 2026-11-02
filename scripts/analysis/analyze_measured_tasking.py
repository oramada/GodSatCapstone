"""Report audited weekly measured-availability tasking and paired process sensitivity."""
from __future__ import annotations

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))


import argparse
import csv
import datetime as dt
import json
from pathlib import Path

import numpy as np

from scripts.analysis.analyze_tasking_temporal_uncertainty import moving_block_means
from scripts.validation.audit_full_catalog_tasking import REGIMES, sha256, verify_rows

METRICS = ('custody_continuity', 'observable_custody', 'mean_slew_energy_proxy')


def describe(values):
    values = np.asarray(values, dtype=float)
    return {'mean': float(values.mean()), 'weekly_effects': values.tolist(),
            'circular_moving_block_ci95': {
                str(length): np.quantile(moving_block_means(values, length, 5000,
                    seed=20261024 + length), [.025, .975]).tolist()
                for length in (1, 4, 13)}}


def paired_process_effect(empirical, markov, metric):
    """Compare treatment changes using identical episode baselines and denominators."""
    for field in (*METRICS, 'sensor_host_ids', 'catalog_objects_in_episode',
                  'target_valid_step_count', 'target_observable_step_count'):
        if empirical[0][field] != markov[0][field]:
            raise ValueError(f'Process baselines differ: {field}')
    for pair in (empirical, markov):
        for field in ('target_valid_step_count', 'target_observable_step_count'):
            if pair[0][field] != pair[1][field]:
                raise ValueError(f'Treatment changes metric denominator: {field}')
    return ((markov[1][metric] - markov[0][metric])
            - (empirical[1][metric] - empirical[0][metric]))


def attempt_loss(rows):
    trials = np.asarray([row['dropout_trials'] for row in rows],dtype=np.int64)
    misses = np.asarray([row['dropout_misses'] for row in rows],dtype=np.int64)
    if np.any(trials < 0) or np.any(misses < 0) or np.any(misses > trials) or trials.sum() == 0:
        raise ValueError('Invalid attempted-observation dropout counts')
    valid = trials > 0
    return {'lost_attempts':int(misses.sum()), 'attempts':int(trials.sum()),
            'pooled_attempt_loss_fraction':float(misses.sum()/trials.sum()),
            'mean_date_attempt_loss_fraction':float(np.mean(misses[valid]/trials[valid])),
            'dates_without_attempts':int((~valid).sum())}


def load(folder):
    summary = json.loads((folder/'summary.json').read_text())
    audit = json.loads((folder/'independent_audit.json').read_text())
    dates = summary['dates']
    if (summary['status'] != 'completed'
            or audit['status'] != 'passed_structural_and_statistical'
            or audit['dates_checked'] != len(dates)
            or audit['response_rows_checked'] != len(dates)*8
            or not audit['date_cluster_effects_independently_recomputed']):
        raise ValueError('Complete independently audited weekly tasking is required')
    parsed = [dt.datetime.fromisoformat(value.replace('Z', '+00:00')) for value in dates]
    if len(dates) < 13 or any((b-a).days != 7 for a,b in zip(parsed,parsed[1:])):
        raise ValueError('Expected ordered consecutive weekly episodes')
    rate = float(summary['dropout_profile']['rate'])
    if summary['dropout_profile']['mode'] not in ('empirical_block', 'markov'):
        raise ValueError('Expected a measured-profile process')
    indexed = verify_rows(summary['rows'], dates, (0., rate))
    with (folder/'responses.csv').open(newline='') as stream:
        csv_rows = list(csv.DictReader(stream))
    seen = set()
    for row in csv_rows:
        key = row['date'], row['orbit_regime_sensor_hosts'], float(row['requested_outage_rate'])
        if key in seen or key not in indexed:
            raise ValueError('CSV keys disagree with audited summary')
        seen.add(key)
        for field in (*METRICS, 'dropout_trials', 'dropout_misses'):
            if float(row[field]) != indexed[key][field]:
                raise ValueError(f'CSV/summary mismatch: {field}')
    if seen != set(indexed):
        raise ValueError('Incomplete response CSV')
    return summary, indexed, rate


def analyze(empirical_folder, output, markov_folder=None):
    empirical, rows, rate = load(empirical_folder)
    if empirical['dropout_profile']['mode'] != 'empirical_block':
        raise ValueError('Empirical input must use source-mask blocks')
    dates = empirical['dates']
    result = {'status': 'completed_empirical_analysis', 'dates': dates, 'rate': rate,
              'source_artifacts': {}, 'empirical_effects': {},
              'uncertainty': '5000 circular moving-block resamples of ordered weekly paired effects; block lengths 1, 4, 13 weeks. Pointwise sensitivity intervals are conditional on the sampled episodes and fixed fitted source profile; they do not adjust for multiple regime/metric comparisons.',
              'scope': 'One-hour weekly all-catalogue greedy tasking; independent per-host draws from one spacecraft attitude-solution availability. No fleet hardware reliability, continuous operations, or trained-policy effectiveness claim.'}
    inputs = [('empirical', empirical_folder)]
    other = None
    if markov_folder:
        markov, other, other_rate = load(markov_folder)
        for field in ('dates', 'raw_archive_manifest_sha256'):
            if empirical[field] != markov[field]:
                raise ValueError(f'Process designs differ: {field}')
        if rate != other_rate or empirical['dropout_profile']['source_profile_sha256'] != markov['dropout_profile']['source_profile_sha256']:
            raise ValueError('Processes use different measured profiles')
        if empirical['dropout_profile']['mode'] != 'empirical_block' or markov['dropout_profile']['mode'] != 'markov':
            raise ValueError('Unexpected process assignment')
        result.update(status='completed_paired_process_comparison', markov_effects={},
                      markov_minus_empirical_effects={})
        inputs.append(('markov',markov_folder))
    for label,folder in inputs:
        result['source_artifacts'][label] = {name: sha256(folder/name)
            for name in ('summary.json','responses.csv','independent_audit.json')}
    result['realized_attempt_loss'] = {
        label: {regime: attempt_loss([indexed[date,regime,rate] for date in dates])
                for regime in REGIMES}
        for label,indexed in [('empirical',rows),*([('markov',other)] if other is not None else [])]}
    for regime in REGIMES:
        result['empirical_effects'][regime] = {}
        if other is not None:
            result['markov_effects'][regime] = {}
            result['markov_minus_empirical_effects'][regime] = {}
        for metric in METRICS:
            pairs = [(rows[d,regime,0.],rows[d,regime,rate]) for d in dates]
            result['empirical_effects'][regime][metric] = describe([b[metric]-a[metric] for a,b in pairs])
            if other is not None:
                other_pairs = [(other[d,regime,0.],other[d,regime,rate]) for d in dates]
                result['markov_effects'][regime][metric] = describe([b[metric]-a[metric] for a,b in other_pairs])
                result['markov_minus_empirical_effects'][regime][metric] = describe([
                    paired_process_effect(a,b,metric) for a,b in zip(pairs,other_pairs)])
    output.mkdir(parents=True,exist_ok=True)
    (output/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    lines = ['# Measured availability tasking sensitivity', '', result['scope'], '',
             f'{len(dates)} weekly dates; nominal source-minute unavailability {rate:.3%}.', '',
             result['uncertainty'], '',
             'Custody changes below are percentage points relative to the zero-outage reference. All-target custody uses valid target-time slots; observable custody uses observable target-time slots. Their denominators differ.', '']
    lines.extend(['## Realized loss among simulated attempts', '',
        'The following pooled rates use lost attempts divided by attempted observations. They describe the injected replay at the selected actions, not measured fleet failures. Attempts within a sampled source block are dependent; no independent-trial binomial interval is assumed.', '',
        '| Process | Host regime | Lost attempts | Attempts | Pooled loss | Mean weekly-date loss |',
        '|---|---|---:|---:|---:|---:|'])
    for process,regimes in result['realized_attempt_loss'].items():
        for regime,item in regimes.items():
            lines.append(f'| {process} | {regime.upper()} | {item["lost_attempts"]:,} | {item["attempts"]:,} | {item["pooled_attempt_loss_fraction"]:.3%} | {item["mean_date_attempt_loss_fraction"]:.3%} |')
    lines.append('')
    for label in ('empirical_effects','markov_effects','markov_minus_empirical_effects'):
        if label not in result:
            continue
        lines.extend([f'## {label.replace("_", " ")}', '',
            '| Host regime | All-target custody change (pp) | Observable custody change (pp) | 13-week block CI for observable change (pp) |',
            '|---|---:|---:|---:|'])
        for regime, metrics in result[label].items():
            lo,hi = metrics['observable_custody']['circular_moving_block_ci95']['13']
            lines.append(f'| {regime.upper()} | {100*metrics["custody_continuity"]["mean"]:.5f} | {100*metrics["observable_custody"]["mean"]:.5f} | [{100*lo:.5f}, {100*hi:.5f}] |')
        lines.append('')
    if other is not None:
        lines.extend(['','The process contrast combines differences in realized loss counts, timing and subsequent adaptive task assignments. It does not isolate the effect of burst structure at a matched realized loss frequency. Both processes use the same retrospectively fitted source profile; this does not establish prospective operational prediction.'])
    lines.append('The slew response is a normalized simulation proxy, not measured energy. Intervals omit uncertainty in the source-profile fit and simulator parameters. A fitted Markov comparison, when present, is paired by date, host identity, baseline response and target denominator. Audit provenance does not imply independent task-assignment replay.')
    (output/'report.md').write_text('\n'.join(lines)+'\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--empirical',type=Path,required=True)
    parser.add_argument('--markov',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    result = analyze(args.empirical,args.output,args.markov)
    print(json.dumps({'status':result['status'],'dates':len(result['dates'])}))
