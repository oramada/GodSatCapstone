"""Publish a compact, source-bound report of the completed NEXT/ground run."""
from __future__ import annotations

if __package__ in (None, ''):
    import sys
    from pathlib import Path
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]))

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import tarfile

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from scipy.stats import norm

from godsat.orbits import ROOT


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def render(folder, report, evidence):
    folder,report,evidence=map(lambda p:Path(p).resolve(),[folder,report,evidence])
    evidence.mkdir(parents=True,exist_ok=True)
    summary=json.loads((folder/'summary.json').read_text())
    audit=json.loads((folder/'rerun-audit.json').read_text())
    stats_audit=json.loads((folder/'independent-statistics-audit.json').read_text())
    assert audit['status']==stats_audit['status']=='passed'
    fits=json.loads((folder/'independent-ccd-adequacy.json').read_text())
    effects=json.loads((folder/'dropout-effects.json').read_text())
    labels=['baseline','doe_recommended','bayesian_best','greedy','random']
    names=['Reference','DOE candidate','BO candidate','Greedy','Random']
    fig,axes=plt.subplots(1,2,figsize=(11,4.4),layout='constrained')
    for ax,metric,scale,ylabel in [(axes[0],'custody_continuity',100,'True custody (%)'),
                                  (axes[1],'slew_energy_joules',1,'Modeled pointing J / sensor-step')]:
        means=[summary['test_summary'][label][metric]['mean']*scale for label in labels]
        errors=[summary['test_summary'][label][metric]['ci95_half_width']*scale for label in labels]
        ax.bar(names,means,yerr=errors,capsize=4,color=['#64748b','#2563eb','#7c3aed','#059669','#d97706'])
        ax.set_ylabel(ylabel)
        ax.tick_params(axis='x',rotation=20)
        ax.grid(axis='y',alpha=.2)
    fig.suptitle('Iridium NEXT targets + six hypothetical ground sensors\nFive training/noise seeds; two held-out one-hour scenes; 95% intervals')
    fig.savefig(evidence/'heldout-comparison.png',dpi=180)
    plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(10,4.3),layout='constrained',sharey=True)
    for ax,mode in zip(axes,['independent','burst']):
        for label,color in [('baseline','#64748b'),('doe_recommended','#2563eb'),('greedy','#059669')]:
            selected=sorted([r for r in effects if r['configuration']==label and r['mode']==mode and r['metric']=='custody_continuity'],key=lambda r:r['rate'])
            rates=[100*r['rate'] for r in selected]
            ax.plot(rates,[100*r['mean'] for r in selected],marker='o',color=color,label=label)
            ax.fill_between(rates,[100*r['ci95'][0] for r in selected],[100*r['ci95'][1] for r in selected],color=color,alpha=.15)
        ax.set_title(mode.capitalize()+' loss')
        ax.set_xlabel('Nominal observation loss (%)')
        ax.grid(alpha=.2)
    axes[0].set_ylabel('Paired custody change (percentage points)')
    axes[1].legend(fontsize=8)
    fig.suptitle('20 paired Monte Carlo seeds; frozen checkpoints and scenes')
    fig.savefig(evidence/'dropout-response.png',dpi=180)
    plt.close(fig)
    fig,axes=plt.subplots(3,2,figsize=(10,10),layout='constrained')
    for row,metric in zip(axes,['objective','custody_continuity','slew_energy_joules']):
        residual=np.asarray(fits[metric]['residuals'])
        fitted=np.asarray(fits[metric]['predicted'])
        row[0].scatter(fitted,residual,s=18)
        row[0].axhline(0,color='black',linewidth=.7)
        row[0].set(xlabel='Fitted '+metric,ylabel='Residual')
        row[1].scatter(norm.ppf((np.arange(len(residual))+.5)/len(residual)),np.sort(residual),s=18)
        row[1].set(xlabel='Normal quantile',ylabel='Ordered '+metric+' residual')
    fig.suptitle('Independent 45-run CCD residual diagnostics\nExploratory patterns; assumptions are not certified by a non-significant lack-of-fit test')
    fig.savefig(evidence/'replicated-ccd-residuals.png',dpi=160)
    plt.close(fig)
    files=['registered-plan.json','config.json','summary.json','validation.csv','responses.csv',
           'screening_design.csv','rsm_design.csv','screening_analysis.json','response_surfaces.json',
           'independent-ccd-adequacy.json','adequacy-responses.csv','adequacy-run-order.json',
           'dropout-responses.csv','dropout-effects.json','scenario-audit.json','rerun-audit.json',
           'training-signature-audit.json','independent-statistics-audit.json']
    manifest=[]
    for name in files:
        shutil.copyfile(folder/name,evidence/name)
        manifest.append({'file':name,'sha256':sha(evidence/name),'source':str((folder/name).relative_to(ROOT))})
    # Preserve the exact scientific source before later report/readiness-only edits.
    archive=evidence/'executed-source.tar.gz'
    with tarfile.open(archive,'w:gz') as tar:
        tar.add(folder/'source-snapshot',arcname='source',filter=lambda info:None if '__pycache__' in info.name else info)
    manifest.append({'file':archive.name,'sha256':sha(archive),'source':'Registered execution source snapshot'})
    records=[]
    for path in sorted((folder/'runs').glob('*.json')):
        record=json.loads(path.read_text())
        records.append({'name':record['name'],'seed':record['seed'],'hyperparameters':record['hyperparameters'],
                        'signature':record['signature'],'record_sha256':sha(path),
                        'checkpoint_sha256':sha(folder/'models'/(record['name']+'.pt')),
                        'wall_seconds':record['wall_seconds'],'cpu_seconds':record['cpu_seconds']})
    (evidence/'treatment-index.json').write_text(json.dumps(records,indent=2)+'\n')
    def link(name):
        return os.path.relpath(evidence/name,report.parent)
    lines=['# Iridium NEXT and ground tracking — rerun results, 2026-11-04','',
        '**Completed:** 122 trained models, 25 held-out policy/seed rows, and 5,280 dropout episodes. The two claimed primary gains were not established.',
        '',f"[Registered protocol]({link('registered-plan.json')}) · [Independent statistics audit]({link('independent-statistics-audit.json')}) · [Exact executed source]({link('executed-source.tar.gz')})",'',
        '## Systems and assumptions','',
        'All 80 pinned NEXT spacecraft, including listed spares, are tracking targets. Six hypothetical ground sensors are co-located at published SLRF2020 monument positions: Yarragadee, Greenbelt, Haleakala, Changchun, Hartebeesthoek and Wettzell. No MEO or other orbital constellation is included. Ground tracking is an explicit execution assumption, not an author-supplied architecture or measured station capability.',
        '', 'Training uses three dated hours in 2022–2024, development selection one hour in 2025, and final evaluation two hours on 2026-08-15 and 2026-09-15. Missing element histories stay unavailable. The earliest training scene has 75 valid target histories; all 80 target slots remain in every scene. These are sampled hours, not continuous four-year operations.',
        '', 'Each run has 40 training episodes. Convergence is not established. Published station coordinates are used with assumed detection/clutter and pointing mechanics, a 10-degree elevation mask and 60-second steps. There is no measured NEXT sensor calibration, weather or exposure model. Pointing energy excludes total station power. Historical ephemeris geometry remains available to the policy; dropout suppresses sensor returns, not position truth.',
        '', '## Held-out comparison','',
        'Mean ± 95% Student-t half-width over five seeds, each averaged over the same two held-out scenes. Custody includes every target with a valid state, including targets below the ground network’s horizon; it is not coverage restricted to visible targets.',
        '', '| Policy | True custody | Modeled pointing J / sensor per 60-second step |', '| --- | ---: | ---: |']
    for label,name in zip(labels,names):
        c=summary['test_summary'][label]['custody_continuity'];e=summary['test_summary'][label]['slew_energy_joules']
        lines.append(f"| {name} | {100*c['mean']:.3f}% ± {100*c['ci95_half_width']:.3f} pp | {e['mean']:.6f} ± {e['ci95_half_width']:.6f} |")
    c=audit['primary_comparisons']['custody_continuity'];e=audit['primary_comparisons']['slew_energy_joules']
    lines+=['',f"DOE minus reference custody is **{100*c['paired_mean_change']:+.3f} percentage points**, with family-adjusted interval [{100*c['family_adjusted_ci'][0]:+.3f}, {100*c['family_adjusted_ci'][1]:+.3f}]. The point relative change is {c['relative_change_percent']:+.3f}%.",
        '',f"Modeled pointing energy changes by **{e['paired_mean_change']:+.6f} J / sensor-step**, interval [{e['family_adjusted_ci'][0]:+.6f}, {e['family_adjusted_ci'][1]:+.6f}], a point relative change of {e['relative_change_percent']:+.3f}%. Positive values are increases. Both intervals include zero. The two 97.5% intervals implement the registered Bonferroni family rule; neither the custody-gain nor energy-reduction claim is established.",
        '',f"![Held-out comparison]({link('heldout-comparison.png')})",'',
        'Greedy achieves higher custody while using more modeled pointing energy. This is a trade-off in these scenes, not evidence of a learned-policy advantage or an operational energy budget.',
        '', '## Response-surface diagnostics','',
        'The screen and unique-point CCD contain 16 and 15 treatments; BO has 31 trials. Factors selected by the measured screen were '+', '.join(summary['selected_factors'])+'. Actor width is isolated from a fixed critic width of 128.',
        '', 'An additional 45 development-only runs give three distinct training seeds at every CCD point, with 30 pure-error and five lack-of-fit degrees of freedom. They are outside the original optimization budget. Lack of fit was not detected for objective, custody or energy under the classical test assumptions:',
        '', '| Response | Lack-of-fit p-value |', '| --- | ---: |']
    for metric in ['objective','custody_continuity','slew_energy_joules']:
        lines.append(f"| {metric} | {fits[metric]['lack_of_fit']['p_value']:.4f} |")
    lines+=['', 'Nonrejection does not prove adequacy or an optimum. The false-track diagnostic had no positive pure-error variance, so its test was unavailable; zero observed events do not establish zero risk. No further tuning used final-test outcomes.',
        '',f"![Replicated response-surface residual diagnostics]({link('replicated-ccd-residuals.png')})",
        '', '## Paired observation losses','',
        'At nominal 20% loss, changes below compare each policy to its own paired no-loss Monte Carlo reference, not to a different primary-evaluation noise sample. Intervals cover 20 noise replicates conditional on the frozen checkpoints and scenes; they do not include training- or scenario-population uncertainty.',
        '', '| Policy | Independent loss, custody change (pp) | Burst loss, custody change (pp) |', '| --- | ---: | ---: |']
    for label in ['baseline','doe_recommended','greedy']:
        cells=[]
        for mode in ['independent','burst']:
            row=next(r for r in effects if r['configuration']==label and r['mode']==mode and r['rate']==.2 and r['metric']=='custody_continuity')
            cells.append(f"{100*row['mean']:+.3f} [{100*row['ci95'][0]:+.3f}, {100*row['ci95'][1]:+.3f}]")
        lines.append('| '+label+' | '+' | '.join(cells)+' |')
    lines+=['',f"![Dropout responses]({link('dropout-response.png')})",'',
        'Burst outages caused larger reductions here at equal nominal probability. Realized missed-look counts and adaptive actions differ; this does not isolate timing alone or establish fleet failure rates.',
        '', '## Validation and compute','',
        f"All {audit['development_models_replayed']} saved development model responses and {audit['heldout_rows_replayed']} held-out rows replayed. Independent action reconstruction checked {audit['independent_heldout_action_reconstructions']} held-out traces and {audit['independent_dropout_action_reconstructions']} dropout traces. All 122 treatment signatures and 4,880 finite training losses checked; three entire training trajectories and weight sets repeated exactly. The separate statistic audit reconciles primary intervals, all dropout effects and replicated fits, including {stats_audit['zero_loss_cross_process_control_pairs']} exact zero-loss control pairs.",
        '',f"The registered end-to-end runner took {audit['elapsed_wall_seconds']:.1f} seconds on this machine, including diagnostics/dropout/replays but excluding later reporting and extra training-repeat checks. Primary aggregate treatment/evaluation wall duration was {summary['total_training_wall_seconds']:.1f} seconds. Parallel DOE and sequential BO do not support an elapsed-time efficiency ranking. GPU use was zero; no calibrated machine energy or tenfold compute saving is claimed.",
        '', 'The exact scientific source snapshot is retained because report wording and CLI/data-readiness safeguards were subsequently improved. Numerical outputs are preserved, with file hashes below. Reproduction with changed source requires a new output folder. The original published neural baseline and calibrated hardware improvements remain unverified.',
        '',f"[Raw held-out rows]({link('validation.csv')}) · [Raw dropout responses]({link('dropout-responses.csv')}) · [Model/seed/hash index]({link('treatment-index.json')})",'']
    report.parent.mkdir(parents=True,exist_ok=True)
    report.write_text('\n'.join(lines))
    # Replace generic template wording in the local run folder with this actual report.
    local_lines='\n'.join(lines)
    for name in ['heldout-comparison.png','dropout-response.png','replicated-ccd-residuals.png',*files,'executed-source.tar.gz','treatment-index.json']:
        local_lines=local_lines.replace(link(name),os.path.relpath(evidence/name,folder))
    (folder/'report.md').write_text(local_lines)
    extras=['heldout-comparison.png','dropout-response.png','replicated-ccd-residuals.png','treatment-index.json']
    manifest.extend({'file':name,'sha256':sha(evidence/name),'source':'Generated from audited run inputs'} for name in extras)
    (evidence/'manifest.json').write_text(json.dumps({'files':manifest,'report_sha256':sha(report),
        'renderer_sha256':sha(__file__),'limits':'Full trained checkpoints, raw ephemerides and most per-run histories remain local; input summaries and exact scientific source are shared.'},indent=2)+'\n')
    print('Published report:',report)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,default=ROOT/'outputs/iridium-next-ground-20261104')
    parser.add_argument('--report',type=Path,default=ROOT/'reports/iridium-next-ground-20261104.md')
    parser.add_argument('--evidence',type=Path,default=ROOT/'reports/evidence/iridium-next-ground-20261104')
    args=parser.parse_args()
    render(args.input,args.report,args.evidence)
