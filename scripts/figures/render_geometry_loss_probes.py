"""Render audited single-observation geometry sensitivity without ranking hardware."""

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from scripts.experiments.run_dropout_campaign import sha256


def render(folder):
    folder=Path(folder)
    summary=json.loads((folder/'summary.json').read_text())
    design=json.loads((folder/'geometry_design.json').read_text())['design']
    audit=json.loads((folder/'independent_audit.json').read_text())
    if (audit['status']!='passed_source_statistics_and_sampled_counterfactual_replay'
            or audit['summary_sha256']!=sha256(folder/'summary.json')
            or audit['design_sha256']!=sha256(folder/'geometry_design.json')
            or audit['csv_sha256']!=sha256(folder/'probes.csv')):
        raise ValueError('Current source/statistical and sampled-injection audit required')
    effects=summary['effects'];regimes=('leo','meo','geo','heo')
    limit=max(abs(e['metrics']['custody_continuity']['mean_date_change']*100) for e in effects) or 1
    fig,axes=plt.subplots(2,2,figsize=(11,9),layout='constrained')
    for regime,ax in zip(regimes,axes.flat):
        grid=np.full((3,3),np.nan)
        for e in effects:
            if e['regime']==regime:grid[e['slew_bin'],e['range_bin']]=100*e['metrics']['custody_continuity']['mean_date_change']
        im=ax.imshow(grid,cmap='RdBu',vmin=-limit,vmax=limit,origin='lower')
        for e in effects:
            if e['regime']==regime:
                x,y=e['range_bin'],e['slew_bin'];v=grid[y,x]
                ax.text(x,y,f'{v:+.3f}\nn={e["dates"]} dates',ha='center',va='center',fontsize=9,
                        color='white' if abs(v)>.6*limit else 'black')
        ax.set(title=regime.upper(),xlabel='Range at suppressed observation (km)',ylabel='Slew angle (degrees)',
               xticks=range(3),xticklabels=['<2,000','2,000–4,000','4,000–6,000'],
               yticks=range(3),yticklabels=['<40','40–80','80–120'])
    fig.colorbar(im,ax=axes,shrink=.75,label='Paired mean custody change (percentage points)')
    fig.suptitle('Single successful observation suppressed: full-episode custody change\nExploratory, date-balanced simulated effects; fixed trained policies',fontsize=12)
    fig.savefig(folder/'geometry_custody_sensitivity.png',dpi=180)
    fig.savefig(folder/'geometry_custody_sensitivity.svg');plt.close(fig)
    lines=['# Geometry-specific single-loss sensitivity','',summary['scope'],'',
        f'{summary["cells"]} quarterly date/regime cells; {summary["baseline_episodes"]} baseline episodes across five frozen checkpoints; {summary["counterfactual_probes"]:,} single-observation interventions. Each learned-policy scene contains {design["config"]["targets"]} targets; this is separate from the all-catalogue greedy tasking study.', '',
        'A successful zero-outage observation is sampled uniformly from each occupied joint range/slew bin in each baseline episode. One observation is suppressed, then the same adaptive policy continues with paired random draws. Changes are counterfactual minus baseline, over the entire one-hour episode. Positive effects can arise from changed later decisions; they do not establish a benefit of real sensor failures.', '',
        summary['selection_limit'],'',summary['uncertainty'],'',
        f'All {audit["probes_checked"]:,} stored contrasts and grouped statistics passed audit. A distinct loss-injection branch reproduced {audit["alternate_loss_injection_probes_replayed"]} counterfactuals and {audit["alternate_loss_injection_baselines_replayed"]} baselines for one checkpoint on three dates. Remaining counterfactual actions were not independently rerun. Both branches share the same environment and physics.', '',
        '![Conditional geometry sensitivity](geometry_custody_sensitivity.png)','',
        '| Hosts | Range bin (km) | Slew bin (degrees) | Dates | Probes | Custody change (pp) | Date-cluster 95% interval (pp) |',
        '|---|---|---|---:|---:|---:|---:|']
    ranges=['<2,000','2,000–4,000','4,000–6,000'];angles=['<40','40–80','80–120']
    for e in effects:
        metric=e['metrics']['custody_continuity'];ci=metric['date_cluster_ci95']
        ci_text='not estimable' if ci is None else f'[{ci[0]*100:+.4f}, {ci[1]*100:+.4f}]'
        lines.append(f'| {e["regime"].upper()} | {ranges[e["range_bin"]]} | {angles[e["slew_bin"]]} | {e["dates"]} | {e["probes"]} | {metric["mean_date_change"]*100:+.4f} | {ci_text} |')
    lines.extend(['','Bins include their lower endpoint; the simulator caps range and slew at the configured maxima. The graphic shows descriptive means without significance filtering. Group differences also reflect which dates, targets and checkpoints populate each bin; they do not isolate a causal effect of changing range or angle. The CSV also retains observable custody, normalized slew-proxy and objective changes. No calibrated energy, fleet failure probability or universally best/worst operational geometry is inferred.'])
    (folder/'report.md').write_text('\n'.join(lines)+'\n')
    return {'status':'rendered_audited_geometry_sensitivity','probes':summary['counterfactual_probes']}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--input',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(render(args.input)))
