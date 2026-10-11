import json
import pathlib
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scipy.linalg import qr, solve_triangular
from scipy.stats import halfnorm, norm
from .design import FACTORS, quadratic_matrix

plt.rcParams.update({'figure.dpi':140,'savefig.bbox':'tight','axes.grid':True,'grid.alpha':.2})

def generate(folder,x,screen,local,responses,analyses,surfaces,summary):
    folder=pathlib.Path(folder);plots=folder/'plots';plots.mkdir(exist_ok=True)
    ground_summary_path=folder.parent.parent/'data/ground_sensor/ilrs_lageos1_npt/sensor_summary.json'
    ground_summary=json.loads(ground_summary_path.read_text()) if ground_summary_path.exists() else None
    if ground_summary and ground_summary.get('status')=='completed':
        sensor_provenance=(f"**Ground-sensor data:** the workspace includes {ground_summary['raw_measurement_records']:,} ILRS LAGEOS-1 laser-ranging normal points from {ground_summary['ground_stations']} stations. These observations were not used to fit the tasking policy or dropout model. The tasking study still assumes hypothetical satellite-hosted optical/radar sensors; no catalog-wide calibration or failed-acquisition telemetry is available.")
    else:
        sensor_provenance=('**Ground-sensor data:** no ground-ranging archive was available at this run’s execution time. This study assumes hypothetical satellite-hosted optical/radar sensors; no catalog-wide calibration or failed-acquisition telemetry is available.')
    effects=np.array([analyses['objective']['main_effects'][f] for f in FACTORS])
    fig,ax=plt.subplots(figsize=(10,4));ax.bar(FACTORS,effects);ax.tick_params(axis='x',rotation=25);ax.set_ylabel('Objective high-minus-low effect');fig.savefig(plots/'main_effects.png');plt.close(fig)
    absolute=np.sort(np.abs(effects));q=halfnorm.ppf((np.arange(1,len(effects)+1)-.5)/len(effects))
    fig,ax=plt.subplots();ax.scatter(q,absolute);ax.set(xlabel='Half-normal quantile',ylabel='Absolute main effect',title='Exploratory screening; seven effects, no pure-error replication');fig.savefig(plots/'half_normal.png');plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(10,4));res=np.array(surfaces['objective']['residuals']);pred=np.array(surfaces['objective']['predicted'])
    axes[0].scatter(pred,res);axes[0].axhline(0,color='black');axes[0].set(xlabel='Fitted objective',ylabel='Residual')
    axes[1].scatter(norm.ppf((np.arange(1,len(res)+1)-.5)/len(res)),np.sort(res));axes[1].set(xlabel='Normal quantile',ylabel='Ordered residual');fig.savefig(plots/'residual_diagnostics.png');plt.close(fig)
    selected=summary['selected_factors'];beta=np.array(surfaces['objective']['coefficients']);values=np.linspace(-1,1,65);xx,yy=np.meshgrid(values,values)
    fig,axes=plt.subplots(1,3,figsize=(17,5),constrained_layout=True)
    for ax,(a,b) in zip(axes,[(0,1),(0,2),(1,2)]):
        points=np.zeros((xx.size,3));points[:,a]=xx.ravel();points[:,b]=yy.ravel();zz=np.sum(quadratic_matrix(points)*beta[None,:],axis=1).reshape(xx.shape)
        contour=ax.contourf(xx,yy,zz,levels=15);ax.set(xlabel=selected[a]+' (coded)',ylabel=selected[b]+' (coded)');fig.colorbar(contour,ax=ax)
    fig.savefig(plots/'response_contours.png');plt.close(fig)
    metric_names=[m for m in responses[0] if m in analyses and m in surfaces]
    fig,axes=plt.subplots(len(metric_names),1,figsize=(12,3.2*len(metric_names)),
        squeeze=False,sharex=True,constrained_layout=True)
    positions=np.arange(len(FACTORS))
    for ax,metric in zip(axes[:,0],metric_names):
        vals=[analyses[metric]['main_effects'][f] for f in FACTORS]
        ax.bar(positions,vals);ax.axhline(0,color='black',linewidth=.7)
        ax.set_ylabel(metric)
    axes[-1,0].set_xticks(positions,FACTORS,rotation=28,ha='right')
    fig.savefig(plots/'all_response_main_effects.png');plt.close(fig)
    fig,axes=plt.subplots(1,5,figsize=(22,4.5),constrained_layout=True);labels=list(summary['test_summary'])
    display_labels={'baseline':'Base','doe_recommended':'DOE','bayesian_best':'BO',
        'greedy':'Greedy','random':'Random'}
    for ax,metric in zip(axes,['custody_continuity','slew_energy_proxy','false_track_proxy','wall_seconds','gpu_hours']):
        stats=[summary['test_summary'][l][metric] for l in labels]
        means=[s['mean'] for s in stats]
        if any(v is None for v in means):
            positions=np.arange(len(labels));heights=[0. if v is None else v for v in means]
            errors=[0. if s['ci95_half_width'] is None else s['ci95_half_width'] for s in stats]
            ax.bar(positions,heights,yerr=errors,capsize=3)
            for i,value in enumerate(means):
                if value is None:ax.text(i,0,'N/R',ha='center',va='bottom',fontsize=8)
            ax.set_xticks(positions,[display_labels.get(label,label) for label in labels])
        else:
            positions=np.arange(len(labels))
            ax.bar(positions,means,yerr=[s['ci95_half_width'] or 0 for s in stats],capsize=3)
            ax.set_xticks(positions,[display_labels.get(label,label) for label in labels])
        ax.set_ylabel(metric);ax.tick_params(axis='x',rotation=0)
    fig.savefig(plots/'validation.png');plt.close(fig)
    matrix=quadratic_matrix(local);anova_all={};uncertainty_all={}
    for metric in metric_names:
        y=np.array([r[metric] for r in responses]);fit=surfaces[metric]
        sse=fit['sse'];sst=float(((y-y.mean())**2).sum());df=fit['residual_df']
        anova_all[metric]={'regression':{'df':9,'ss':max(0,sst-sse),'ms':max(0,sst-sse)/9},
            'residual':{'df':df,'ss':sse,'ms':sse/df if df else None},
            'total':{'df':len(y)-1,'ss':sst},
            'note':'Model decomposition; regression significance depends on independent errors and an adequate model.'}
        _,triangular=qr(matrix,mode='economic');inverse=solve_triangular(triangular,np.eye(triangular.shape[0]),lower=False)
        covariance=np.einsum('ik,jk->ij',inverse,inverse)*sse/df if df>0 else np.full((10,10),np.nan)
        uncertainty_all[metric]={'standard_errors':np.sqrt(np.diag(covariance)).tolist(),
            'covariance':covariance.tolist(),
            'assumption':'Independent homoscedastic residuals; exploratory for stochastic RL.'}
    (folder/'anova_all_responses.json').write_text(json.dumps(anova_all,indent=2,allow_nan=False))
    (folder/'coefficient_uncertainty_all_responses.json').write_text(json.dumps(uncertainty_all,indent=2,allow_nan=False))
    (folder/'anova.json').write_text(json.dumps(anova_all['objective'],indent=2))
    (folder/'coefficient_uncertainty.json').write_text(json.dumps(uncertainty_all['objective'],indent=2))
    awp_path=folder.parent/'awp_check_frame_gcrs_leo.json'
    if not awp_path.exists():
        awp_path=folder.parent/'awp_check.json'
    awp_note=''
    regimes=summary.get('scenario_regimes',{}).get('test',['leo'])
    regime_checks=[]
    for regime in regimes:
        path=folder.parent/f'awp_check_frame_gcrs_{regime}.json'
        if not path.exists():
            candidates=sorted(folder.parent.glob(f'awp_check_frame_gcrs_{regime}_*.json'))
            if candidates:
                path=candidates[0]
        if not path.exists():
            path=folder.parent/('awp_check.json' if regime=='leo' else f'awp_check_{regime}.json')
        if path.exists():
            item=json.loads(path.read_text());regime_checks.append(f"{regime.upper()} NORAD {item['norad_id']}: {item['max_separation_km']:.3f} km")
    if len(regime_checks)>1:
        awp_note='AWP two-body plus J2 was compared with historical SGP4 over one hour after transforming the SGP4 TEME states to GCRS with Astropy: '+ '; '.join(regime_checks)+'. These are model separations, not errors against measured truth.'
    elif awp_path.exists():
        awp=json.loads(awp_path.read_text())
        awp_note=f"A separate AWP two-body plus J2 propagation check covered NORAD {awp['norad_id']} on {awp['date']}; after transforming SGP4 TEME states to GCRS with Astropy, maximum separation over the one-hour window was {awp['max_separation_km']:.3f} km. This is model sensitivity, not error against measured truth."
    lines=['# GoDSAT historical-orbit research run','',f"Study: **{summary['study_kind']}**. All reported values were measured in this implementation.",'',
        'This is a new shared-policy multi-agent actor-critic implementation. The original GoDSAT code, published baseline configuration, and calibrated sensor model were not supplied. The manuscript contains placeholder results; its 11–14% custody and 9% energy claims are not reproduced or assumed here.','',
        sensor_provenance,'',
        f"Executed {summary['screening_runs']} screening treatments, {summary['rsm_runs']} response-surface treatments, {summary['bayesian_runs']} Bayesian treatments, and {summary['validation_retrains']} independent retrains. Training wall time: {summary['total_training_wall_seconds']:.1f} seconds on {summary.get('compute_device','cpu')}; measured accelerator-active time: {summary.get('total_gpu_hours',0.):.6f} GPU-hours. No calibrated machine energy estimate is available.",'',
        '## Data and scenario','',
        'Historical source spans October 2022–October 2026. Training windows are separated by date from the 2025 selection window and 2026 held-out test window. Scenario orbit regimes: '+json.dumps(summary.get('scenario_regimes',{}))+f". Sensor-host candidates come from the `{summary.get('sensor_cohort','current_payload')}` cohort; targets come from the `{summary.get('target_cohort','current_payload')}` cohort, which includes debris and rocket bodies when set to `all`. Each episode selects a dense observable cluster with hypothetical sensor hardware. These are short sampled windows, not four years of continuous training. All inference uses element epochs at or before the sampled time.",
        ('The sensor-host set intersects the current CelesTrak active-GP snapshot with no-decay Earth payloads in SATCAT. This current snapshot is backcast through historical element records; it does not establish that each spacecraft was operational at every sampled historical date.' if summary.get('sensor_cohort')=='current_active_payload' else ''),awp_note,'',
        '## Screening','',
        'Correct defining relation from E=ABC, F=ABD, G=ACD: '+ ' = '.join(analyses['objective']['defining_relation'])+'.',
        'The manuscript’s printed relation differs from its generators. Main effects are clear of two-factor interactions, but two-factor aliases cannot be individually identified.','',
        '| Factor | Objective effect | Custody effect | Slew-proxy effect | False-track effect | Runtime effect |',
        '|---|---:|---:|---:|---:|---:|']
    lines += [f"| {name} | "+' | '.join(f"{analyses[m]['main_effects'][name]:.6f}" for m in metric_names)+' |' for name in FACTORS]
    lines += ['', 'Factors selected by measured absolute objective effect: '+', '.join(selected)+'.',
        'Their identities are selected from these observations; the manuscript’s learning-rate/discount/width ranking is not imposed.','',
        '![Main effects](plots/main_effects.png)','![All response main effects](plots/all_response_main_effects.png)',
        '![Half-normal](plots/half_normal.png)','',
        '## Response surface','',
        (f"The response-surface design has eight factorial and six axial points, plus {summary['rsm_center_replicates']} independently trained center-point observations ({summary['rsm_runs']} treatments total). The two added center runs estimate pure training error, enabling a formal lack-of-fit test with only two pure-error degrees of freedom." if summary['rsm_center_replicates']>1 else "The exact paper-matched 15-run face-centered CCD has eight factorial points, six axial points, and one center observation. With no replicated center, pure training error and a formal lack-of-fit test cannot be estimated; see the augmented follow-up campaign for that extension.")+f" Bayesian optimization receives the matched {summary['bayesian_runs']}-treatment budget.",'',
        '| Response | Canonical classification | Residual RMSE | Lack-of-fit result |',
        '|---|---|---:|---|']
    for metric in metric_names:
        fit=surfaces[metric];lof=fit['lack_of_fit']
        lof_text=(f"F={lof['F']:.3f}, p={lof['p_value']:.3f}, pure-error df={lof['pure_error_df']}"
            if lof.get('available',True) and 'p_value' in lof else 'not estimable')
        lines.append(f"| {metric} | {fit['classification']} | {fit['rmse']:.6f} | {lof_text} |")
    lines += [
        'Bounded local recommendation (integer factors rounded before retraining):','',
        '```json',json.dumps(summary['recommended_hyperparameters'],indent=2),'```','',
        'The constrained numerical optimum is exploratory. Review residuals and holdout performance before accepting it; an optimizer returning a point is not evidence of model adequacy.','',
        '![Surface contours](plots/response_contours.png)','![Residual diagnostics](plots/residual_diagnostics.png)','',
        '## Held-out comparison','',
        'Means with 95% Student-t interval half-widths over five independent training/evaluation seeds. Slew energy is a normalized squared-angle proxy; false-track rate is the failed-observation proxy, not measured false positives. Wall time is end-to-end per seed: training, validation, and held-out evaluation for learned policies; held-out evaluation for non-learning baselines. “not recorded” marks legacy results whose non-learning baseline runtimes were not measured.','',
        '| Configuration | Custody | Slew proxy | False-track proxy | Mean end-to-end wall seconds per seed | GPU-hours per seed |',
        '|---|---:|---:|---:|---:|---:|']
    for label,s in summary['test_summary'].items():
        cells=[f"{s[m]['mean']:.4f} ± {s[m]['ci95_half_width']:.4f}" for m in ['custody_continuity','slew_energy_proxy','false_track_proxy']]
        wall=s['wall_seconds']
        cells.append('not recorded' if wall['mean'] is None else f"{wall['mean']:.3f} ± {wall['ci95_half_width']:.3f}")
        gpu=s.get('gpu_hours',{'mean':0.,'ci95_half_width':0.})
        cells.append('not recorded' if gpu['mean'] is None else f"{gpu['mean']:.6f} ± {gpu['ci95_half_width'] or 0.:.6f}")
        lines.append('| '+label+' | '+' | '.join(cells)+' |')
    lines += ['', '![Validation](plots/validation.png)','',
        'Descriptive cost-performance ratios use held-out custody or normalized slew proxy divided by measured end-to-end wall seconds for the same seed. They are not electrical energy efficiency. Learned-policy time includes training and test evaluation; greedy/random time covers evaluation only, so these accounting scopes differ. No calibrated energy measurement or GPU-hours are available for this CPU campaign.','',
        '| Configuration | Custody per wall second | Slew proxy per wall second |','|---|---:|---:|']
    for label,ratios in summary.get('cost_performance_ratios',{}).items():
        custody=ratios['custody_per_wall_second'];slew=ratios['slew_proxy_per_wall_second']
        def fmt(item):
            return 'not recorded' if item['mean'] is None else f"{item['mean']:.6f} ± {item['ci95_half_width']:.6f}"
        lines.append(f'| {label} | {fmt(custody)} | {fmt(slew)} |')
    lines += ['', 'Paired DOE-minus-baseline changes:','',
        '```json',json.dumps(summary['paired_comparisons'],indent=2),'```','',
        'Bayesian optimization uses a fixed-prior Matérn-3/2 Gaussian process with expected improvement over a 2,048-point candidate pool and the same number of training treatments. The kernel uses a unit length scale and 0.1 observation noise with Cholesky stabilization. It is budget-matched by run count and episode count, not equal wall time. Hyperparameter widths/depths change compute cost.','',
        f"A 128-run two-level full factorial versus {summary['screening_runs']+summary['rsm_runs']} DOE runs is about a {128/(summary['screening_runs']+summary['rsm_runs']):.1f}× reduction, not an order of magnitude. A separate 31-trial random-search reference is reported in `outputs/all-orbits-random-search-31/`.",'',
        '## Reproducibility','',
        'See design CSVs, per-run JSON metadata, model checkpoints, validation seeds, raw responses, coefficients/covariance, ANOVA, and cached scenario source epochs. The baseline is an explicitly chosen reference configuration, not the unpublished original baseline.','',
        'The full campaign completed as configured, but the results remain exploratory. Short episode windows, one date in each validation/test split, unavailable published baseline implementation/configuration, missing catalog-wide sensor calibration, and reduced-precision orbital elements limit scientific conclusions. The ILRS observations are not used as sensor-model calibration or dropout labels. Original raw TLE/OMM and representative calibrated sensor data are needed for operational claims.',
        'The independent center-point replication and lack-of-fit audit is reported separately in `outputs/all-orbits-active-hosts-center-replication/center_replication_report.md`; it rejects the quadratic fit for both objective and custody, so this campaign’s fitted optimum is not accepted as validated.']
    (folder/'report.md').write_text('\n'.join(lines)+'\n')
