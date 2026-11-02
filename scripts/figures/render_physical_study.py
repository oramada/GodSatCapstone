"""Render the supplied-PDF followthrough from audited physical-response results."""

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))

import csv
import json
from pathlib import Path

import numpy as np
from scipy.stats import t

from godsat.orbits import ROOT
from scripts.experiments.run_physical_sensitivity import sha


def render(output):
    output=Path(output);sources={}
    def read(relative,status=None):
        path=ROOT/relative;value=json.loads(path.read_text());sources[relative]=sha(path)
        if status and value.get('status')!=status:raise ValueError('Incomplete report source: '+relative)
        return value
    folder='outputs/governing-design-physical-leo-20261025'
    summary=read(folder+'/summary.json','completed')
    physical=read(folder+'/independent_physical_audit.json','passed_all_checkpoint_selection_and_heldout_physical_replays')
    training=read(folder+'/training_replay_audit.json','passed_all_treatment_signatures_and_sampled_training_replay')
    if physical['summary_sha256']!=sources[folder+'/summary.json']:raise ValueError('Physical audit stale')
    center_dir='outputs/governing-design-physical-leo-center-20261025'
    read(center_dir+'/independent_validation.json','completed')
    surfaces=read(center_dir+'/response_surfaces_augmented.json')
    sensitivity_dir='outputs/physical-sensor-sensitivity-20261025'
    sensitivity=read(sensitivity_dir+'/summary.json','completed_frozen_policy_physical_parameter_and_loss_sensitivity')
    sensitivity_audit=read(sensitivity_dir+'/independent_audit.json','passed_source_response_and_parameter_sensitivity_reproduction')
    if sensitivity_audit['summary_sha256']!=sources[sensitivity_dir+'/summary.json']:raise ValueError('Sensitivity audit stale')
    supplement=read('outputs/governing-design-followthrough-20261025/summary.json','completed_source_bound_screening_and_compute_prefix_analysis')
    for source in [physical,sensitivity,training]:
        for path,digest in source.get('source_hashes',{}).items():
            if sha(ROOT/path)!=digest:raise ValueError('Underlying report source changed: '+path)
            sources[path]=digest
    config=read(folder+'/config.json')
    path=ROOT/folder/'validation.csv';sources[str(path.relative_to(ROOT))]=sha(path)
    with path.open() as f:validation=list(csv.DictReader(f))
    def pair(policy,metric):
        base={int(r['seed']):float(r[metric]) for r in validation if r['configuration']=='baseline'}
        chosen={int(r['seed']):float(r[metric]) for r in validation if r['configuration']==policy}
        values=np.array([chosen[s]-base[s] for s in sorted(base)])
        mean=float(values.mean());half=float(t.ppf(.975,4)*values.std(ddof=1)/np.sqrt(5))
        return mean,mean-half,mean+half
    custody=pair('doe_recommended','custody_continuity');energy=pair('doe_recommended','slew_energy_joules')
    lines=['# GoDSAT: execution of the supplied factorial/RSM design','',
        'The six-page governing PDF has been read and executed as a documented simulation adaptation. The user authorized assumptions for the unavailable published actor–critic baseline, sensor hardware and false-track definition. The original PDF is preserved; its placeholder improvement claims are replaced here by measured simulation outcomes. [Protocol audit](../docs/governing-pdf-audit.md).','',
        f'The DOE recommendation changes held-out true custody by {custody[0]*100:+.4f} percentage points (paired 95% interval [{custody[1]*100:+.4f}, {custody[2]*100:+.4f}]) and mean modeled slew energy by {energy[0]:+.6f} J per host-step (interval [{energy[1]:+.6f}, {energy[2]:+.6f}]). These five-seed results do not establish the manuscript’s claimed custody gain or energy reduction.','',
        '## Design and source corrections','',
        'The exact treatment design has 16 randomized seven-factor resolution-IV screening runs, 15 face-centered CCD runs, 31 Bayesian trials and 15 independent learned-policy validation retrains (five each for baseline, DOE and BO). Greedy/random controls add ten evaluation rows. Three historical training windows, a separate 2025 selection window and a held-out 2026 test window retain six catalogue-payload hosts, 18 orbital targets, 60-second steps and 40 training episodes per treatment. All source arrays and checkpoint bytes are hashed.','',
        'The source generators E=ABC, F=ABD, G=ACD produce I=ABCE=ABDF=ACDG=AEFG=BCFG=BDEG=CDEF. This corrects the printed equation 4. All 15 independent contrast chains are retained: seven main, seven two-factor and one three-factor chain. The high-order-only noise estimate has one df; the full-residual estimate assumes all eight remaining chains are inactive. Neither is replicated pure error. Confounded two-factor terms remain alias chains.','',
        'The source’s asserted learning-rate/discount/width ranking is not imposed. The new measured objective ranking selects '+', '.join(summary['selected_factors'])+'. Coefficients, full covariance/ANOVA and responses are retained for every recorded response.','',
        '![All 15 contrasts](../outputs/governing-design-followthrough-20261025/governing-design-physical-leo-20261025-half-normal.png)','',
        '![Confounded interactions](../outputs/governing-design-followthrough-20261025/governing-design-physical-leo-20261025-interactions.png)','',
        '## Physical response assumptions','',
        '[Complete assumptions and equations](../docs/physical-sensor-assumptions.md). Slews are torque/speed-limited rest-to-rest rotations with 2 kg m² inertia, 0.02 N m torque, 2 deg/s maximum rate, 0.65 efficiency and 0.05 W moving-drive power. Energy is acceleration work divided by efficiency plus moving electronics energy. No regeneration, holding/tracking power, friction or wheel momentum-management budget is modeled.','',
        'Conditional on a nominal missed look without dropout, a 0.005 Bernoulli probability produces an incorrectly associated clutter report. Declared tracks last 180 seconds; the latest report determines the simulated true/false label. False-track rate counts false active declared-track slots over all active declared-track slots. The policy sees reported age, including clutter; true custody uses a separate truth state. False-observation rate is separately recorded. These are simulated association errors, not measured operational failure rates.','',
        'Geometry and custody are evaluated on 60-second slots, without resolving continuous slew/exposure timestamps or within-slot target motion. The fixed 40-episode budget supports comparison within that budget; it does not establish convergence. The greedy control outperforms the learned policies on held-out custody, so these results do not establish a learned-policy advantage.','',
        '## Held-out results','',
        'Mean ± 95% Student-t half-width over five independently retrained seeds. Energy is joules per host per 60-second step; false-track rate is a fraction. A zero observed rate and zero t interval mean no events in those five replicates, not proof of zero population risk.','',
        '| Policy | True custody | Slew J / host-step | False-track fraction | Wall seconds / seed |','|---|---:|---:|---:|---:|']
    for policy,stats in summary['test_summary'].items():
        cells=[f"{stats[m]['mean']:.6f} ± {stats[m]['ci95_half_width']:.6f}" for m in ['custody_continuity','slew_energy_joules','false_track_rate','wall_seconds']]
        lines.append('| '+policy+' | '+' | '.join(cells)+' |')
    lines+=['','Learned-policy runtime includes retraining, validation and held-out evaluation per seed; heuristic runtime covers evaluation only. These scopes are disclosed rather than pooled into an efficiency ranking.','',
            '| Comparison | Custody change (pp), paired 95% interval | Slew change (J), paired 95% interval | False-track fraction change, paired 95% interval |','|---|---:|---:|---:|']
    for policy in ['doe_recommended','bayesian_best']:
        cells=[]
        for metric,scale in [('custody_continuity',100),('slew_energy_joules',1),('false_track_rate',1)]:
            mean,lo,hi=pair(policy,metric);cells.append(f'{mean*scale:+.6f} [{lo*scale:+.6f}, {hi*scale:+.6f}]')
        lines.append('| '+policy+' − baseline | '+' | '.join(cells)+' |')
    lines+=['','## Pure-error diagnostics and ridge recommendation','',
            'The original 15-point CCD has one center and cannot support a pure-error lack-of-fit test. Twelve separately randomized, independently seeded center retrains give 13 center observations, 12 pure-error df and five lack-of-fit df when variance is positive. These extra diagnostics are outside the original 31-treatment optimization budget.','',
            '| Response | Canonical classification | Lack-of-fit p | Pure-error df |','|---|---|---:|---:|']
    for metric in ['objective','custody_continuity','slew_energy_joules','false_track_rate']:
        surface=surfaces[metric];lof=surface['lack_of_fit'];p=lof.get('p_value')
        lines.append(f"| {metric} | {surface['classification']} | {p if p is not None else 'not estimable'} | {lof.get('pure_error_df','not estimable')} |")
    lines+=['','Failure to reject lack of fit is not proof of adequacy. Saddles, flat responses, sparse false events and weak pure-error assumptions do not establish a validated optimum. Bounded/ridge recommendations are evaluated empirically on holdout, without promoting placeholder gains into findings.','',
            '```json',json.dumps(summary['recommended_hyperparameters'],indent=2),'```','',
            '![Residual diagnostics](../outputs/governing-design-physical-leo-20261025/plots/residual_diagnostics.png)','',
            '![Quadratic contour slices](../outputs/governing-design-physical-leo-20261025/plots/response_contours.png)','',
            '## Compute cost and energy accounting','',
            '| Cost basis | DOE search cost | BO trials within that cap | Selected BO trial | Same five-seed recommendation |','|---|---:|---:|---|---|']
    budgets=supplement['campaigns']['governing-design-physical-leo-20261025']['compute_budget_prefixes']
    for metric,b in budgets.items():lines.append(f"| {metric} | {b['budget']:.3f} s | {b['completed_treatments']} | {b['selected_treatment']} | {b['same_as_original_five_seed_BO_selection']} |")
    lines+=['','These are retrospective complete-trial prefixes of measured treatment cost. They exclude acquisition/orchestration overhead and do not equalize contemporaneous load. Full BO still has 31 trials; equal trial count alone does not imply equal seconds. CPU execution records zero GPU-hours, with no GPU speedup claim. The 128-run full factorial versus 31-run DOE ratio is 4.13×, not an order of magnitude.','',
            'Each treatment additionally records a host-energy scenario estimate of 50 W × measured wall duration. That is an authorized assumed-power calculation, not a calibrated power measurement or incremental process-energy attribution. All calibrated-energy fields remain unavailable. Host energy and gimbal energy have separate units and meanings. Cost-performance ratios retain their accounting boundaries.','',
            '| Learned policy | Custody / end-to-end wall second, mean ± 95% half-width | Assumed host Wh / seed, mean |','|---|---:|---:|']
    for policy in ['baseline','doe_recommended','bayesian_best']:
        ratio=summary['cost_performance_ratios'][policy]['custody_per_wall_second']
        wh=summary['test_summary'][policy]['wall_seconds']['mean']*config['assumed_host_power_watts']/3600
        lines.append(f"| {policy} | {ratio['mean']:.6f} ± {ratio['ci95_half_width']:.6f} | {wh:.6f} |")
    lines += ['',
            '## Parameter and loss-process sensitivity','',
            f"The frozen-policy extension has {sensitivity['response_rows']:,} responses: 17 quarterly dates × three learned configurations × five training seeds × nine nominal/parameter/loss variants. No policy retraining is performed under changed hardware or losses. These dates include the original training/selection/test epochs; this is sensitivity analysis, not 17 independent holdouts. Average paired seeds within date before computing pointwise circular moving-block intervals; blocks of six sampled dates are not six calendar days.",'',
            '| Policy | Variant − nominal | Custody change (pp) | Six-date block interval (pp) |','|---|---|---:|---:|']
    for effect in sensitivity['paired_effects']:
        if effect['metric']!='custody_continuity':continue
        lo,hi=effect['circular_block_ci95']['6']
        lines.append(f"| {effect['policy']} | {effect['variant']} | {effect['mean']*100:+.5f} | [{lo*100:+.5f}, {hi*100:+.5f}] |")
    lines+=['','The raw summary also contains modeled-energy and false-track effects with 1-/3-/6-date intervals. No-clutter controls must produce zero false reports. Changing inertia changes both slew feasibility and energy. Clutter changes reported ages and can change later actions. No single parameter contrast is a calibrated fleet effect.','',
            '## Validation and release','',
            f"All {physical['checkpoint_selection_responses_replayed']} saved checkpoint selection responses and all {physical['heldout_response_rows_replayed']} held-out policy/seed responses were replayed. All 77 treatment signatures and finite 40-episode loss histories were verified; three complete training reruns matched every history value and checkpoint tensor exactly. Independent action reconstruction checks accepted looks, positive torque work, nominal/clutter draws, true custody and false-track slots. Sensitivity audit verifies all {sensitivity_audit['response_rows_checked']:,} rows, {sensitivity_audit['paired_effect_vectors_checked']} paired effect vectors and {sensitivity_audit['temporal_intervals_checked']} block intervals; {sensitivity_audit['sampled_policy_and_independent_physical_action_replays']} sampled policy/physics replays cover first/middle/last dates, all policies and variants at the first model seed.",'',
            '[Physical campaign inputs, raw responses and checkpoints](../outputs/governing-design-physical-leo-20261025/) · [Center diagnostics](../outputs/governing-design-physical-leo-center-20261025/center_replication_report.md) · [Sensitivity source and statistics](../outputs/physical-sensor-sensitivity-20261025/summary.json) · [Complete screening and compute-prefix analysis](../outputs/governing-design-followthrough-20261025/report.md).','',
            'The earlier four-regime optimization, all-catalogue historical reconstruction, daily/quarterly injected loss studies, measured-product availability, optical and ILRS reference checks remain separate audited experiments. [Combined scientific report](current-study-20261024.md). This new experiment does not retroactively change their sensor model or denominators.','']
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text('\n'.join(lines))
    receipt={'status':'rendered_from_audited_governing_design_followthrough','report_sha256':sha(output),'generator_sha256':sha(Path(__file__)),'source_hashes':sources}
    output.with_suffix('.provenance.json').write_text(json.dumps(receipt,indent=2)+'\n')
    return receipt


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,default=ROOT/'reports/governing-design-study-20261025.md')
    args=p.parse_args();result=render(args.output);print(json.dumps({'status':result['status'],'sources':len(result['source_hashes'])}))
