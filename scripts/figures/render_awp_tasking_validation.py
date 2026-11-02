"""Render independently audited, common-frame force-model tasking sensitivity."""
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


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def interval_text(mean, interval):
    return f'{100*mean:+.5f} [{100*interval[0]:+.5f}, {100*interval[1]:+.5f}]'


def render(folder, output):
    folder,output=folder.resolve(),output.resolve()
    summary_path,audit_path=folder/'summary.json',folder/'independent_audit.json'
    summary=json.loads(summary_path.read_text());audit=json.loads(audit_path.read_text())
    if (summary.get('status')!='completed' or audit.get('status')!='completed_valid'
            or audit.get('source_summary_sha256')!=sha256(summary_path)
            or audit.get('failures') or summary.get('policy_feature_frame')!='TEME'):
        raise ValueError('Completed independent audit of the common trained feature frame is required')
    csv_paths=[folder/name for name in ['policy_evaluation.csv','dropout_evaluation.csv','regime_comparison.csv']]
    for path,key in zip(csv_paths[:2],['policy_rows','dropout_rows']):
        with path.open(newline='') as stream:rows=list(csv.DictReader(stream))
        if len(rows)!=audit[key] or any(row.get('feature_frame')!='TEME' for row in rows):
            raise ValueError('Policy response dimensions or feature frames differ from the audit')
    regimes=['leo','meo','geo','heo'];model=summary['comparison_model']
    labels={'awp_j2':'J2','awp_j2_sun_moon':'J2 + Sun/Moon'}
    if model not in labels:raise ValueError('Unsupported audited comparison model')
    comparison_label=labels[model]
    effects={row['orbit_regime']:row for row in audit['dropout_effects_recomputed']}
    policies={row['orbit_regime']:row for row in audit['policy_effects_recomputed']}
    if set(effects)!=set(regimes) or set(policies)!=set(regimes):
        raise ValueError('Four-regime policy and dropout effects are required')
    output.mkdir(parents=True,exist_ok=True)
    fig,axes=plt.subplots(1,2,figsize=(11,4.3),layout='constrained')
    x=np.arange(4)
    for offset,dynamics,label,color in [(-.08,'sgp4','SGP4','#0072B2'),(.08,model,comparison_label,'#D55E00')]:
        means=100*np.array([effects[r]['custody_change'][dynamics]['mean'] for r in regimes])
        ci=100*np.array([effects[r]['custody_change'][dynamics]['ci95'] for r in regimes])
        axes[0].errorbar(x+offset,means,yerr=np.stack([means-ci[:,0],ci[:,1]-means]),
                         fmt='o',capsize=4,label=label,color=color)
    means=100*np.array([effects[r]['awp_minus_sgp4_interaction']['mean'] for r in regimes])
    ci=100*np.array([effects[r]['awp_minus_sgp4_interaction']['ci95'] for r in regimes])
    axes[1].errorbar(x,means,yerr=np.stack([means-ci[:,0],ci[:,1]-means]),
                     fmt='o',capsize=4,color='#303030')
    axes[1].axhline(0,color='#888888',linewidth=1)
    axes[0].set_ylabel('Custody change from injected burst outage\n(percentage points)')
    axes[1].set_ylabel('AWP minus SGP4 change in outage effect\n(percentage points)')
    axes[0].legend(frameon=False,fontsize=9)
    for ax in axes:
        ax.set_xticks(x,[r.upper() for r in regimes]);ax.grid(axis='y',alpha=.2)
        ax.spines[['right','top']].set_visible(False)
    count=len(summary['dates']);rate=100*summary['dropout_outage_rate']
    fig.suptitle(f'{count} monthly dates: {rate:g}% burst-outage sensitivity, common TEME policy inputs')
    fig.savefig(output/'force_dropout_sensitivity.svg');fig.savefig(output/'force_dropout_sensitivity.png',dpi=220);plt.close(fig)
    targets=sorted({int(row['target_count']) for row in summary['regimes']})
    agents=sorted({int(row['agent_count']) for row in summary['regimes']})
    target_text=', '.join(map(str,targets));agent_text=', '.join(map(str,agents))
    text=['# Common-frame numerical-force tasking sensitivity','',
        f"The completed experiment covers {count} monthly dates, four orbit regimes, {len(summary['validation_training_seeds'])} frozen trained checkpoints, {summary['policy_evaluation_design_rows']:,} policy responses and {summary['dropout_evaluation_design_rows']:,} paired dropout responses. Each episode lasts {summary['episode_duration_minutes']} minutes at {summary['sample_step_seconds']}-second cadence. Targets per scene: {target_text}; sensor hosts per scene: {agent_text}. The independent audit passed with no failures.",'',
        'Both policy feature streams are in TEME, matching training. Raw numerical orbit states are compared in GCRS. This assesses model sensitivity under fixed scenario and sensor assumptions; neither orbit model is independent orbital truth.','',
        f'| Host regime | {rate:g}% minus zero outage: SGP4 | {rate:g}% minus zero outage: {comparison_label} | Change in outage effect |',
        '|---|---:|---:|---:|']
    for regime in regimes:
        row=effects[regime];a=row['custody_change']['sgp4'];b=row['custody_change'][model];delta=row['awp_minus_sgp4_interaction']
        text.append(f"| {regime.upper()} | {interval_text(a['mean'],a['ci95'])} | {interval_text(b['mean'],b['ci95'])} | {interval_text(delta['mean'],delta['ci95'])} |")
    text+=['','Values are custody percentage points with 95% date-clustered t intervals. Checkpoints and paired simulation replicates are averaged within each monthly date before computing the interval. These intervals describe the sampled scenes conditional on the frozen checkpoints; they do not establish prospective coverage or operational equivalence.','',
        '![Force-model dropout sensitivity](force_dropout_sensitivity.png)','',
        '| Host regime | AWP minus SGP4 custody without injected outage |','|---|---:|']
    for regime in regimes:
        row=policies[regime]
        text.append(f"| {regime.upper()} | {interval_text(row['mean_awp_minus_sgp4_custody'],row['ci95_date_clustered'])} |")
    text+=['','A zero-width interval can result from identical discrete custody outputs; it does not establish zero physical-model uncertainty. The independent orbit-product benchmark and the all-catalogue greedy tasking reference are separate analyses.','',
        '| Host regime | Scenes with position comparison | Median of scene-median separations (km) |','|---|---:|---:|']
    for regime in regimes:
        available=[float(row['position_separation_median_km']) for row in summary['regimes']
                   if row['orbit_regime']==regime and row['position_separation_median_km'] is not None]
        value=f'{np.median(available):.6f}' if available else 'not estimable'
        text.append(f'| {regime.upper()} | {len(available)} / {count} | {value} |')
    text+=['','The last table aggregates scene-level medians and is not a pooled-state error estimate. Sensor detection, custody and angular-slew models remain simulation assumptions. The one-hour horizon does not establish long-horizon orbit-prediction accuracy.','',
            '[Independent audit](independent_audit.json) · [Policy responses](policy_evaluation.csv) · [Dropout responses](dropout_evaluation.csv)']
    (output/'report.md').write_text('\n'.join(text)+'\n')
    result={'status':'rendered_from_completed_common_frame_audit','dates':count,
        'source_receipts':[{'path':str(path),'sha256':sha256(path)} for path in [summary_path,audit_path,*csv_paths]],
        'dropout_effects':audit['dropout_effects_recomputed'],'policy_effects':audit['policy_effects_recomputed']}
    (output/'report-provenance.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args();result=render(args.input,args.output or args.input)
    print(json.dumps({'status':result['status'],'dates':result['dates']}))


if __name__=='__main__':main()
