"""Render audited attitude availability with unpublished days left unknown."""
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

import matplotlib
matplotlib.use('Agg')
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[2]


def render(data, output):
    profile_path = data/'dropout_profile_1minute.json'
    bounds_path = data/'archive_coverage_bounds.json'
    profile = json.loads(profile_path.read_text()); coverage = json.loads(bounds_path.read_text())
    if coverage.get('status') != 'passed_date_reconciliation_and_missingness_bounds':
        raise ValueError('Complete date-grid and unknown-day bounds must pass before rendering')
    for item in coverage['source_receipts']:
        if hashlib.sha256(Path(item['path']).read_bytes()).hexdigest() != item['sha256']:
            raise ValueError(f'Availability source changed: {item["path"]}')
    manifest = json.loads((data/'manifest.json').read_text())
    dates = [dt.date.fromisoformat(row['date']) for row in profile['per_day']]
    rates = np.array([row['dropout_minutes']/row['samples'] for row in profile['per_day']])
    if len(dates) != coverage['published_days']:
        raise ValueError('Profile and coverage day counts differ')
    output.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(2, 1, figsize=(11, 6.5), layout='constrained',
                             gridspec_kw={'height_ratios': [2.3, 1]})
    for index, day in enumerate(manifest['not_published_dates']):
        start = dt.date.fromisoformat(day)
        axes[0].axvspan(start, start+dt.timedelta(days=1), color='#bbbbbb', alpha=.7,
                       linewidth=0, label='Publisher product unavailable' if index == 0 else None)
    axes[0].scatter(dates, rates, s=5, color='#0072B2', alpha=.75,
                    label='Published-day unavailable-solution fraction', rasterized=True)
    axes[0].set_ylim(-.02, 1.02)
    axes[0].set_ylabel('Unavailable attitude solutions\n(fraction of minute samples)')
    axes[0].xaxis.set_major_locator(mdates.MonthLocator(interval=6))
    axes[0].xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    axes[0].legend(frameon=False, fontsize=8, loc='upper left')
    axes[0].set_title('CASSIOPE definitive attitude products: published and unknown days')
    observed = 100*profile['one_minute_attitude_solution_dropout_rate']
    ci = 100*np.array(profile['one_minute_dropout_rate_date_cluster_bootstrap_ci95'])
    lower, upper = 100*np.array(coverage['one_minute']['whole_window_unavailability_fraction_bounds'])
    axes[1].errorbar([observed], [1], xerr=[[observed-ci[0]], [ci[1]-observed]],
                     fmt='o', color='#0072B2', capsize=4)
    axes[1].plot([lower, upper], [0, 0], color='#D55E00', linewidth=3)
    axes[1].plot([lower, upper], [0, 0], '|', color='#D55E00', markersize=12)
    axes[1].set_yticks([0, 1], ['Whole-window missing-data bounds\n(deterministic, not a confidence interval)',
                              'Published-day estimate\nand 95% day-bootstrap interval'])
    axes[1].set_ylim(-.6, 1.6)
    axes[1].set_xlim(min(lower, ci[0])-.5, max(upper, ci[1])+.5)
    axes[1].set_xlabel('Unavailable attitude-solution fraction (%)')
    for ax in axes:
        ax.spines[['right', 'top']].set_visible(False)
        ax.grid(axis='y', alpha=.2)
    fig.savefig(output/'availability_and_coverage.svg')
    fig.savefig(output/'availability_and_coverage.png', dpi=220)
    plt.close(fig)
    lines = ['# CASSIOPE attitude-solution availability', '',
        f"All {coverage['published_days']:,} acquired daily CDF products were fully replayed, and all {coverage['publisher_unpublished_days']} unpublished-day records were verified. The requested window contains {coverage['requested_days']:,} UTC days.", '',
        f"Minute-sampled unavailable solutions occur in {observed:.2f}% of published samples, with a 95% published-day bootstrap interval of {ci[0]:.2f}–{ci[1]:.2f}%. This interval is conditional on the published days. Leaving all unpublished-day states unknown gives a full-window missing-data bound of {lower:.2f}–{upper:.2f}%; this is a deterministic bound rather than a confidence interval.", '',
        '![Availability and coverage](availability_and_coverage.png)', '',
        'The source is one spacecraft’s definitive, retrospectively interpolated attitude solution. Finite solutions and their absence do not establish real-time onboard availability, ground-sensor acquisition outcomes, fleet reliability, or calibrated pointing errors. The measured sequence is used only as a hypothetical tasking sensitivity profile. Unpublished days are not classified as outages.', '',
        f"At one-minute cadence, the empirical within-day unavailable-state persistence is {profile['empirical_dropout_persistence_probability_per_minute']:.6f}. Transition counts exclude day boundaries; the empirical-block study retains observed 60-minute sequences rather than replacing them with a fitted Markov process.", '',
        'The [publisher product handbook](https://epop.phys.ucalgary.ca/data-handbook/attitude-quaternion-file-cas_attquat/) describes a definitive 1 Hz spline and NaN handling for long solution gaps. The mask measures validity of that published product; it does not count every missing instantaneous sensor reading. No exclusive ten-minute cutoff is imposed on the observed masks.']
    temporal_path = data/'temporal_uncertainty_1minute.json'
    if temporal_path.exists():
        temporal = json.loads(temporal_path.read_text())
        for item in temporal['source_receipts']:
            if hashlib.sha256(Path(item['path']).read_bytes()).hexdigest() != item['sha256']:
                raise ValueError('Temporal sensitivity is not bound to the current availability sources')
        lines += ['', 'Serial-dependence sensitivity uses consecutive calendar-day blocks while retaining unpublished days as unknown. These conditional resampling intervals are wider than the independent-day interval:', '',
                  '| Resampled calendar block | 95% resampling interval |', '|---|---:|']
        for item in temporal['calendar_block_bootstrap']:
            low, high = item['ci95']
            lines.append(f"| {item['calendar_block_days']} days | {100*low:.2f}–{100*high:.2f}% |")
        lines += ['', '| Calendar year | Published / requested days | Observed unavailable fraction |', '|---|---:|---:|']
        for item in temporal['yearly_observed_estimates']:
            lines.append(f"| {item['year']} | {item['published_days']} / {item['requested_days']} | {100*item['published_sample_unavailability_fraction']:.2f}% |")
        lines += ['', 'The 2022 and 2026 coverage is partial-year. The observed yearly differences also limit a stationary-process interpretation. The block lengths are sensitivity choices; the pooled tasking profile is a hypothetical stress distribution applied to historical scenes, rather than a date-matched reconstruction of actual sensor service or a prospective failure forecast.']
    (output/'report.md').write_text('\n'.join(lines)+'\n')
    summary = {'status': 'rendered_audited_availability_and_unknown_day_bounds',
               'published_days': coverage['published_days'], 'unknown_days': coverage['publisher_unpublished_days'],
               'source_receipts': [{'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
                                   for path in [profile_path, bounds_path]],
               'published_minute_fraction': observed/100, 'whole_window_fraction_bounds': [lower/100, upper/100]}
    if temporal_path.exists():
        summary['source_receipts'].append({'path': str(temporal_path), 'sha256': hashlib.sha256(temporal_path.read_bytes()).hexdigest()})
    (output/'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=ROOT/'data/attitude/cassiope_epop')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); print(json.dumps(render(args.data.resolve(), args.output.resolve())))


if __name__ == '__main__':
    main()
