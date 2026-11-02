"""Source-bound supplementary analysis of the supplied GoDSAT design manuscript.

Preserves frozen campaign outputs. Computes all 15 independent screening
contrasts and retrospective compute-budget prefixes from actual treatment logs.
"""
from __future__ import annotations

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))


import csv
import datetime as dt
import hashlib
import itertools
import json
from pathlib import Path

import numpy as np
from scipy.stats import halfnorm

from godsat.orbits import ROOT


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def complete_contrasts(x, y):
    """Enumerate unique Walsh contrasts using observed columns, independent of design.py."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if x.shape != (16, 7) or y.shape != (16,):
        raise ValueError('Expected the 16-run seven-factor screening design')
    groups = {}
    for degree in range(1, 8):
        for indices in itertools.combinations(range(7), degree):
            column = np.prod(x[:, indices], axis=1)
            # Actual defining words have constant +1 and belong to intercept.
            if np.all(column == 1):
                continue
            if not np.all(np.isin(column, [-1, 1])) or column.sum() != 0:
                raise ValueError('Invalid two-level balanced design column')
            key = tuple(column.tolist())
            label = ''.join(chr(65 + i) for i in indices)
            groups.setdefault(key, []).append(label)
    if len(groups) != 15:
        raise ValueError('Screen must identify exactly 15 orthogonal contrasts')
    columns = np.asarray(list(groups))
    if not np.array_equal(columns @ columns.T, np.eye(15) * 16):
        raise ValueError('Contrast basis is not orthogonal')
    rows = []
    for column, labels in groups.items():
        effect = float(np.dot(column, y) / 8)
        rows.append({'representative': labels[0], 'aliases': labels,
                     'minimum_order': len(labels[0]), 'effect': effect,
                     'contrast_sum_of_squares': 4 * effect * effect})
    absolute = np.abs([r['effect'] for r in rows])
    s0 = 1.5 * float(np.median(absolute))
    retained = absolute[absolute < 2.5 * s0]
    pse = 1.5 * float(np.median(retained)) if len(retained) else None
    higher = [r for r in rows if r['minimum_order'] >= 3]
    # This design has seven main, seven two-factor, ONE three-factor contrast.
    # A nominal high-order-only estimate consequently has only one noise df.
    variance = sum(r['contrast_sum_of_squares'] for r in higher) / len(higher) if higher else None
    order = np.argsort(absolute)
    for rank, index in enumerate(order):
        rows[index]['half_normal_quantile'] = float(halfnorm.ppf((rank + .5) / 15))
        rows[index]['lenth_active_descriptive'] = bool(pse is not None and abs(rows[index]['effect']) > 2.5 * pse)
    return {'contrasts': rows, 'lenth_pse': pse, 'initial_scale': s0,
            'higher_order_only_noise_df': len(higher),
            'higher_order_only_noise_variance': variance,
            'noise_scope': 'Unreplicated screen. The sole high-order alias chain is assumed inactive for the one-df variance; Lenth flags are descriptive, not multiplicity-adjusted significance tests.',
            'corrected_legacy_issue': 'The frozen analysis pools seven two-factor alias contrasts, omits the eighth residual (a three-factor chain), and incorrectly describes eight pooled two-factor contrasts. Main-effect estimates and selection are unaffected.'}


def budget_prefix(rows, limit, metric):
    if limit <= 0:
        raise ValueError('Budget must be positive')
    elapsed = 0.
    eligible = []
    for row in rows:
        cost = float(row[metric])
        if cost < 0 or not np.isfinite(cost):
            raise ValueError('Invalid measured cost')
        elapsed += cost
        if elapsed > limit:
            break
        eligible.append(row)
    if not eligible:
        raise ValueError('No completed treatment fits the budget')
    best = max(eligible, key=lambda r: r['objective'])
    return {'budget': limit, 'metric': metric, 'completed_treatments': len(eligible),
            'consumed_budget': sum(float(r[metric]) for r in eligible),
            'remaining_budget': limit - sum(float(r[metric]) for r in eligible),
            'selected_treatment': best['name'], 'selected_hyperparameters': best['hyperparameters'],
            'selection_response': best['objective'],
            'scope': 'Retrospective sequential prefix of recorded training/selection treatment costs; excludes search orchestration overhead and independent retraining/test costs. A completed trial is never credited before its full cost fits. This does not equalize contemporaneous machine load.'}


def analyze(output):
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    sources = {}
    def read(path):
        sources[str(path.relative_to(ROOT))] = digest(path)
        return json.loads(path.read_text())
    metadata = read(ROOT/'outputs/study-execution/source-inventory/governing-design-pdf.json')
    pdf = Path(metadata['path'])
    if digest(pdf) != metadata['sha256']:
        raise ValueError('Governing PDF changed')
    sources[str(pdf.relative_to(ROOT))] = digest(pdf)
    campaigns = {}
    names=['paper-reference-cpu-20261024', 'all-orbits-active-hosts-cpu-20261024']
    if (ROOT/'outputs/governing-design-physical-leo-20261025/summary.json').exists():
        names.append('governing-design-physical-leo-20261025')
    for name in names:
        folder = ROOT/'outputs'/name
        summary = read(folder/'summary.json')
        audit = read(folder/'campaign_integrity_audit.json')
        if audit['status'] != 'completed':
            raise ValueError('Campaign audit incomplete')
        records = {prefix: [read(p) for p in sorted((folder/'runs').glob(prefix+'_*.json'))]
                   for prefix in ['screen', 'rsm', 'bo']}
        design = folder/'screening_design.csv'; sources[str(design.relative_to(ROOT))] = digest(design)
        with design.open() as f:
            x = np.array([[float(r[k]) for k in 'ABCDEFG'] for r in csv.DictReader(f)])
        metric_names=['objective', 'custody_continuity', 'slew_energy_proxy', 'false_track_proxy', 'wall_seconds', 'gpu_hours']+summary.get('additional_responses',[])
        stats = {metric: complete_contrasts(x, [r[metric] for r in records['screen']]) for metric in metric_names}
        frozen_screen=read(folder/'screening_analysis.json')
        if len(frozen_screen['objective'].get('residual_alias_effects',{}))==8:
            for analysis in stats.values():analysis['corrected_legacy_issue']='This campaign uses the corrected eight-residual-chain kernel; no residual contrast is omitted.'
        budgets = {}
        original_best = max(records['bo'], key=lambda r: r['objective'])
        for metric in ['wall_seconds', 'cpu_seconds']:
            cap = sum(r[metric] for prefix in ['screen', 'rsm'] for r in records[prefix])
            budgets[metric] = budget_prefix(records['bo'], cap, metric)
            budgets[metric]['same_as_original_five_seed_BO_selection'] = (
                budgets[metric]['selected_hyperparameters'] == original_best['hyperparameters'])
            if budgets[metric]['same_as_original_five_seed_BO_selection']:
                for seed in [101, 211, 307, 401, 503]:
                    v = read(folder/'runs'/f'validate_bayesian_best_{seed}.json')
                    if v['hyperparameters'] != original_best['hyperparameters']:
                        raise ValueError('Five-seed validation uses different BO hyperparameters')
        campaigns[name] = {'complete_screening': stats, 'compute_budget_prefixes': budgets,
                           'original_BO_treatment_count': len(records['bo']),
                           'selected_factors': summary['selected_factors'],
                           'original_equal_trial_budget': 31}
        # Show conditional interaction means, with their confounding explicit.
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        pairs=[r['representative'] for r in stats['objective']['contrasts'] if r['minimum_order']==2]
        fig,axes=plt.subplots(3,3,figsize=(12,10),layout='constrained')
        y=np.array([r['objective'] for r in records['screen']])
        for ax,label in zip(axes.flat,pairs):
            i,j=[ord(k)-65 for k in label]
            for level in [-1,1]:
                values=[y[(x[:,i]==a)&(x[:,j]==level)].mean() for a in [-1,1]]
                ax.plot([-1,1],values,marker='o',label=f'{label[1]}={level:+d}')
            ax.set(xlabel=label[0]+' coded level',ylabel='Mean objective',title=label+' alias chain');ax.legend()
        for ax in list(axes.flat)[len(pairs):]:ax.set_visible(False)
        fig.suptitle('Confounded two-factor interaction means: '+name)
        fig.savefig(output/f'{name}-interactions.png');plt.close(fig)
    result = {'status': 'completed_source_bound_screening_and_compute_prefix_analysis',
              'generated_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
              'source_pdf_sha256': metadata['sha256'], 'source_hashes': sources,
              'campaigns': campaigns}
    (output/'summary.json').write_text(json.dumps(result, indent=2, allow_nan=False)+'\n')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    lines = ['# Governing design: supplementary analysis', '',
             'The supplied six-page manuscript specifies 16 screening runs and 15 CCD runs. Its printed defining relation is inconsistent with E=ABC, F=ABD, G=ACD. Multiplication gives I=ABCE=ABDF=ACDG=AEFG=BCFG=BDEG=CDEF.', '',
             'The complete contrast space has seven main-effect chains, seven two-factor chains and one remaining three-factor chain. The frozen screening reports omitted that final chain and mislabeled the seven pooled two-factor chains as eight. This supplement includes all 15 independent contrasts without modifying any frozen treatment or fitted recommendation.', '',
             'A high-order-only noise estimate has one degree of freedom here. All effects are displayed on the half-normal plot; treating the lone high-order chain as inactive is an explicit, weak assumption. Lenth flags provide an additional descriptive sensitivity check.', '']
    for name, value in campaigns.items():
        rows = value['complete_screening']['objective']['contrasts']
        fig, ax = plt.subplots(figsize=(8, 5))
        for row in rows:
            ax.scatter(row['half_normal_quantile'], abs(row['effect']), color='C0')
            ax.annotate(row['representative'], (row['half_normal_quantile'], abs(row['effect'])), fontsize=8)
        ax.set(xlabel='Half-normal quantile (all 15 contrasts)', ylabel='Absolute objective effect', title=name)
        fig.tight_layout(); fig.savefig(output/f'{name}-half-normal.png'); plt.close(fig)
        lines += [f'## {name}', '', f'![All screening contrasts]({name}-half-normal.png)', '',
                  f'![Confounded interaction means]({name}-interactions.png)', '',
                  '| Budget basis | DOE cost cap | BO trials completed | Selected trial | Existing five-seed validation applies |',
                  '|---|---:|---:|---|---|']
        for metric, b in value['compute_budget_prefixes'].items():
            lines.append(f"| {metric} | {b['budget']:.3f} s | {b['completed_treatments']} | {b['selected_treatment']} | {b['same_as_original_five_seed_BO_selection']} |")
    lines += ['', 'The compute prefixes are sensitivity comparisons using measured treatment logs. They are not new contemporaneous equal-load experiments. Search orchestration is outside recorded treatment costs. CPU execution supplies no informative GPU-cost budget. No unmeasured electrical energy is inferred.', '']
    (output/'report.md').write_text('\n'.join(lines))
    return result


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'outputs/governing-design-followthrough-20261025')
    args = parser.parse_args()
    result = analyze(args.output)
    print(json.dumps({'status': result['status'], 'campaigns': list(result['campaigns'])}))
