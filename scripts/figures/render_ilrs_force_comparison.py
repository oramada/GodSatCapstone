"""Render audited numerical-force comparisons against operational ILRS CPF products."""
from __future__ import annotations

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))


import argparse
import csv
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def render(j2: Path, sun_moon: Path, output: Path):
    folders = [j2.resolve(), sun_moon.resolve()]
    identifiers = ['awp_j2', 'awp_j2_sun_moon']
    summaries = []
    receipts = []
    for folder, model in zip(folders, identifiers):
        summary = json.loads((folder/'summary.json').read_text())
        audit = json.loads((folder/'independent_audit.json').read_text())
        if (summary.get('status') != 'completed' or summary.get('model_id') != model
                or audit.get('status') != 'passed_structural_and_statistical'
                or audit.get('model_id') != model or audit.get('targets_checked') != 4):
            raise ValueError(f'Completed, independently audited force comparison required: {folder}')
        for name in ['summary.json', 'independent_audit.json']:
            path = folder/name
            receipts.append({'path': str(path), 'sha256': digest(path)})
        summaries.append({row['design']['target']: row for row in summary['targets']})
    targets = ['lageos1', 'lageos2', 'lares', 'starlette']
    labels = ['LAGEOS-1', 'LAGEOS-2', 'LARES', 'Starlette']
    rows = []
    for target in targets:
        items = [summary[target] for summary in summaries]
        references = []
        for folder, item, model in zip(folders, items, identifiers):
            path = folder/f'{target}_{model}_vs_cpf.csv'
            if digest(path) != item['output_csv_sha256']:
                raise ValueError(f'Comparison CSV changed since validation: {path}')
            with path.open(newline='') as stream:
                source = list(csv.DictReader(stream))
            references.append([(r['observation_time_utc'], r['station_name'], r['cpf_file'],
                                r['historical_element_epoch_utc'],
                                *[float(r[f'{name}_itrf_{axis}_km'])
                                  for name in ['sgp4', 'cpf'] for axis in 'xyz']) for r in source])
            receipts.append({'path': str(path), 'sha256': digest(path)})
        if references[0] != references[1]:
            raise ValueError(f'Force-model samples or reference states differ for {target}')
        row = {'target': target, 'samples': len(references[0]),
               'sgp4_median_separation_km': items[0]['metrics']['sgp4_vs_cpf']['median_km']}
        for model, item in zip(identifiers, items):
            metrics = item['metrics']
            row[f'{model}_median_separation_km'] = metrics[f'{model}_vs_cpf']['median_km']
            row[f'{model}_mean_excess_separation_km'] = metrics['awp_minus_sgp4_separation_mean_km']
            row[f'{model}_mean_excess_ci95_km'] = metrics['awp_minus_sgp4_separation_ci95_date_clustered_km']
        rows.append(row)
    output.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), layout='constrained')
    x = np.arange(len(targets))
    for offset, model, label, color in zip([-.18, 0., .18], ['sgp4', *identifiers],
            ['SGP4', 'J2 integration', 'J2 + Sun/Moon'], ['#303030', '#0072B2', '#D55E00']):
        axes[0].plot(x + offset, [r[f'{model}_median_separation_km'] for r in rows],
                     'o', label=label, color=color)
    axes[0].set_yscale('log')
    axes[0].set_ylabel('Median separation from CPF (km, log scale)')
    axes[0].legend(frameon=False, fontsize=9)
    for offset, model, label, color in zip([-.09, .09], identifiers,
            ['J2 integration', 'J2 + Sun/Moon'], ['#0072B2', '#D55E00']):
        mean = np.array([r[f'{model}_mean_excess_separation_km'] for r in rows])
        ci = np.array([r[f'{model}_mean_excess_ci95_km'] for r in rows])
        axes[1].errorbar(x + offset, mean, yerr=np.stack([mean-ci[:, 0], ci[:, 1]-mean]),
                         fmt='o', capsize=4, label=label, color=color)
    axes[1].axhline(0, color='#666666', linewidth=1)
    axes[1].set_ylabel('Mean separation excess over SGP4 (km)\n95% date-clustered interval')
    for ax in axes:
        ax.set_xticks(x, labels)
        ax.grid(axis='y', alpha=.2)
        ax.spines[['right', 'top']].set_visible(False)
    fig.suptitle('Historical orbit-model consistency with operational ILRS CPF products')
    fig.savefig(output/'force_comparison.svg')
    fig.savefig(output/'force_comparison.png', dpi=220)
    plt.close(fig)
    result = {'status': 'rendered_from_audited_matched_reference_samples', 'targets': rows,
              'source_receipts': receipts,
              'scope': 'One observation per available nonoverlapping 72-hour bin, matched across both numerical models. CPF operational predictions are reference products, not independent orbit truth. Date intervals describe paired mean excess separation, not uncertainty on medians.'}
    (output/'summary.json').write_text(json.dumps(result, indent=2)+'\n')
    text = ['# Numerical orbit-model reference comparison', '', result['scope'], '',
            '| Target | Samples | SGP4 median km | J2 median km | J2 + Sun/Moon median km |',
            '|---|---:|---:|---:|---:|']
    for row, label in zip(rows, labels):
        text.append(f"| {label} | {row['samples']} | {row['sgp4_median_separation_km']:.4f} | {row['awp_j2_median_separation_km']:.4f} | {row['awp_j2_sun_moon_median_separation_km']:.4f} |")
    text += ['', '![Force-model comparison](force_comparison.png)', '',
             'These comparisons assess propagation initialized from historical GP-element states. They do not establish that adding force terms improves tracking, nor do they measure sensor dropout. Historical SGP4 remains the study baseline; the numerical integrations provide a separate sensitivity analysis.']
    (output/'report.md').write_text('\n'.join(text)+'\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--j2', type=Path, required=True)
    parser.add_argument('--sun-moon', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = render(args.j2, args.sun_moon, args.output)
    print(json.dumps({'status': result['status'], 'targets': len(result['targets'])}))


if __name__ == '__main__':
    main()
