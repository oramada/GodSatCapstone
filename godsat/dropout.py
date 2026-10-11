"""Controlled sensor-dropout study over historical orbital replay scenarios."""
import csv
import json
import pathlib
import hashlib
from collections import defaultdict
import numpy as np
from scipy.stats import t as student_t
from .scenario import prepare, load
from .environment import TaskingEnv
from .learning import Agent
from .orbits import ROOT
import torch


def sample_empirical_dropout_blocks(masks, steps, agents, seed, return_indices=False):
    """Seeded, independent per-host block bootstrap from measured daily masks."""
    import numpy as np
    masks = np.asarray(masks, dtype=bool)
    steps, agents = int(steps), int(agents)
    if masks.ndim != 2 or masks.shape[0] < 1 or masks.shape[1] < steps:
        raise ValueError('Empirical masks must contain daily rows at least as long as an episode')
    if steps < 1 or agents < 1:
        raise ValueError('steps and agents must be positive')
    rng = np.random.default_rng(seed)
    selected_days = rng.integers(0, masks.shape[0], size=agents)
    max_start = masks.shape[1] - steps
    starts = rng.integers(0, max_start + 1, size=agents)
    blocks = np.column_stack([masks[day, start:start + steps]
                              for day, start in zip(selected_days, starts)])
    if return_indices:
        return blocks, selected_days, starts
    return blocks


def quarterly_dates(start='2022-10-15', end='2026-10-01'):
    import datetime as dt
    cursor=dt.date.fromisoformat(start);last=dt.date.fromisoformat(end);dates=[]
    while cursor<=last:
        dates.append(dt.datetime.combine(cursor,dt.time(),tzinfo=dt.timezone.utc).isoformat().replace('+00:00','Z'))
        month=cursor.month+3;year=cursor.year+(month-1)//12;month=(month-1)%12+1
        day=min(cursor.day,[31,29 if year%4==0 and (year%100!=0 or year%400==0) else 28,31,30,31,30,31,31,30,31,30,31][month-1])
        cursor=dt.date(year,month,day)
    final=dt.datetime.combine(last,dt.time(),tzinfo=dt.timezone.utc).isoformat().replace('+00:00','Z')
    if dates and dates[-1] != final:
        dates.append(final)
    return dates


def monthly_dates(start='2022-10-15', end='2026-09-15'):
    """Return UTC monthly samples spanning nearly the full four-year archive."""
    import datetime as dt
    cursor=dt.date.fromisoformat(start);last=dt.date.fromisoformat(end);dates=[]
    if cursor>last:
        raise ValueError('start must be on or before end')
    day=cursor.day
    while cursor<=last:
        dates.append(dt.datetime.combine(cursor,dt.time(),tzinfo=dt.timezone.utc).isoformat().replace('+00:00','Z'))
        month=cursor.month+1;year=cursor.year+(month-1)//12;month=(month-1)%12+1
        day=min(day,[31,29 if year%4==0 and (year%100!=0 or year%400==0) else 28,31,30,31,30,31,31,30,31,30,31][month-1])
        cursor=dt.date(year,month,day)
    return dates


def evaluate_policy(model, scenario, config, hp, seed, probability, mode):
    env = TaskingEnv(scenario, config, hp['claim_resolution'], seed,
                     dropout_probability=probability, dropout_mode=mode)
    obs, mask = env.reset()
    for _ in range(env.steps):
        with torch.no_grad():
            action = model.distribution(torch.tensor(obs), torch.tensor(mask)).probs.argmax(-1).numpy()
        (obs, mask), _, _ = env.step(action)
    return env.metrics()


def build_checkpoint_provenance(baseline_output, summary, checkpoint_path, seed):
    try: path_in_workspace=pathlib.Path(checkpoint_path).resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError: path_in_workspace=str(pathlib.Path(checkpoint_path).resolve())
    return {
        'baseline_output':str(baseline_output),
        'checkpoint_path':path_in_workspace,
        'checkpoint_sha256':hashlib.sha256(pathlib.Path(checkpoint_path).read_bytes()).hexdigest(),
        'source_study_kind':summary.get('study_kind'),
        'source_campaign_counts':{key:summary.get(key) for key in ['screening_runs','rsm_runs','bayesian_runs','validation_retrains']},
        'source_cohorts':{'sensor':summary.get('sensor_cohort'),'target':summary.get('target_cohort')},
        'source_training_regimes':summary.get('scenario_regimes',{}).get('training'),
        'source_test_dates':summary.get('heldout_test_dates'),
        'policy':'DOE-recommended checkpoint, seed '+str(seed),
    }


def parse_response_row(row):
    """Restore numeric types when resuming completed cells from CSV."""
    parsed=dict(row)
    for key,value in parsed.items():
        if key in {'replicate','seed','model_seed'}:
            parsed[key]=int(value)
        elif key not in {'date','regime','mode'}:
            parsed[key]=float(value)
    return parsed


def run_dropout_study(config, baseline_output, output, rates=None, replicates=20):
    """Evaluate the paper's selected policy across historical dates/outage scenarios.

    No dropout model is trained into the policy; this is an intervention study
    that holds tasking policy, orbital scenario, and random seed paired fixed.
    """
    baseline_output = pathlib.Path(baseline_output)
    out = pathlib.Path(output); out.mkdir(parents=True, exist_ok=True)
    summary = json.loads((baseline_output/'summary.json').read_text())
    hp = summary['comparison_configurations']['doe_recommended']
    seed0 = int(config.get('dropout_model_seed', 101))
    model_seeds=list(map(int,config.get('dropout_model_seeds',[seed0])))
    if not model_seeds or len(set(model_seeds))!=len(model_seeds):
        raise ValueError('dropout_model_seeds must be a non-empty list of unique training seeds')
    models={};checkpoint_provenances=[]
    for model_seed in model_seeds:
        checkpoint_path=baseline_output/'models'/f'validate_doe_recommended_{model_seed}.pt'
        checkpoint=torch.load(checkpoint_path,map_location='cpu',weights_only=True)
        model=Agent(checkpoint['obs_dim'],checkpoint['actions'],checkpoint['hp'])
        model.load_state_dict(checkpoint['state_dict']);model.eval()
        models[model_seed]=model
        checkpoint_provenances.append(build_checkpoint_provenance(baseline_output,summary,checkpoint_path,model_seed))
    if len(model_seeds)==1:
        checkpoint_provenance=checkpoint_provenances[0]
    else:
        aggregate_hash=hashlib.sha256(json.dumps(
            {str(item['policy'].rsplit(' ',1)[-1]):item['checkpoint_sha256'] for item in checkpoint_provenances},
            sort_keys=True).encode()).hexdigest()
        checkpoint_provenance={
            'baseline_output':str(baseline_output),
            'source_study_kind':summary.get('study_kind'),
            'source_campaign_counts':{key:summary.get(key) for key in ['screening_runs','rsm_runs','bayesian_runs','validation_retrains']},
            'source_cohorts':{'sensor':summary.get('sensor_cohort'),'target':summary.get('target_cohort')},
            'source_training_regimes':summary.get('scenario_regimes',{}).get('training'),
            'model_seeds':model_seeds,
            'checkpoints':checkpoint_provenances,
            'checkpoint_sha256':aggregate_hash,
            'checkpoint_sha256_note':'SHA-256 of the sorted model-seed to checkpoint-SHA256 mapping',
        }
    rates = rates or config.get('dropout_rates', [0.0, .05, .1, .2, .4, .6])
    modes = config.get('dropout_modes', ['independent', 'burst'])
    regimes = config.get('dropout_regimes', ['leo'])
    dates = config.get('dropout_dates', config['training_dates']+config['validation_dates']+config['test_dates'])
    rows=[]
    design={'version':3,'dates':dates,'regimes':regimes,'rates':list(rates),
        'modes':modes,'replicates':replicates,
        'checkpoint':f'validate_doe_recommended_{seed0}.pt' if len(model_seeds)==1 else [f'validate_doe_recommended_{seed}.pt' for seed in model_seeds],
        'config':config,'randomization':'Independent priority, detection, and dropout streams; per-step-agent-target uniforms are paired across rates. Burst outages transition each simulation timestep even without an assigned observation.',
        'sensor_host_fallback':'disabled; unavailable sensor-host date/regime cells fail rather than substituting debris or rocket bodies'}
    if len(model_seeds)>1:
        design['model_seeds']=model_seeds
    signature=hashlib.sha256(json.dumps(design,sort_keys=True).encode()).hexdigest()
    response_path=out/'dropout_responses.csv'
    # Resuming a multi-year factorial campaign should not throw away completed
    # historical windows after an interruption. Retain only rows with the
    # exact design signature; regenerate any incomplete date/regime cells.
    design_path=out/'dropout_design.json'
    old_summary=out/'dropout_summary.json'
    missing={(d,g) for d in design['dates'] for g in regimes}
    if design_path.exists():
        prior_design=json.loads(design_path.read_text())
        if prior_design.get('design_signature') == signature and response_path.exists():
            with response_path.open(newline='') as f:
                rows=[parse_response_row(row) for row in csv.DictReader(f)]
            cell_counts={}
            for r in rows:
                key=(r['date'],r['regime'])
                cell_counts[key]=cell_counts.get(key,0)+1
            expected=replicates*len(modes)*len(rates)*len(model_seeds)
            complete={key for key,n in cell_counts.items() if n==expected}
            missing={(d,g) for d in dates for g in regimes if (d,g) not in complete}
            if not missing:
                if old_summary.exists():
                    prior=json.loads(old_summary.read_text())
                    if prior.get('design_signature')==signature:
                        return prior
            rows=[r for r in rows if (r['date'],r['regime']) in complete]
        elif response_path.exists():
            raise ValueError('Existing dropout responses belong to a different design; choose another output folder')
    design_path.write_text(json.dumps({'design_signature':signature,'design':design},indent=2)+'\n')
    for date, regime in sorted(missing):
            scenario=load(prepare(date,config,regime=regime))
            for mode in modes:
                for replicate in range(replicates):
                    seed=int(config.get('dropout_seed', 7441))+replicate
                    for rate in rates:
                        for model_seed in model_seeds:
                            metrics=evaluate_policy(models[model_seed],scenario,config,hp,seed,float(rate),mode)
                            row={'date':date,'regime':regime,'mode':mode,'replicate':replicate,'seed':seed,**metrics}
                            if len(model_seeds)>1:row['model_seed']=model_seed
                            rows.append(row)
            print(f'completed dropout replay {date} {regime}',flush=True)
            with response_path.open('w',newline='') as f:
                writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    if not rows:
        raise ValueError('No dropout scenarios were evaluated')
    with response_path.open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    grouped={};rows_by_condition=defaultdict(list);row_index={}
    for row in rows:
        model_seed=int(row.get('model_seed',model_seeds[0]))
        rate=float(row['dropout_probability'])
        rows_by_condition[(row['regime'],row['mode'],rate)].append(row)
        row_index[(row['date'],row['regime'],row['mode'],int(row['replicate']),model_seed,rate)]=row
    for regime in regimes:
        for mode in modes:
            for rate in rates:
                key=f'{regime}:{mode}:{rate:g}'; values=rows_by_condition[(regime,mode,float(rate))]
                grouped[key]={}
                for metric in ['custody_continuity','observable_custody','slew_energy_proxy','false_track_proxy','conflict_rate','dropout_rate_observed']:
                    x=np.array([r[metric] for r in values],float);n=len(x)
                    margin=float(student_t.ppf(.975,n-1)*x.std(ddof=1)/np.sqrt(n)) if n>1 else None
                    by_date=defaultdict(list)
                    for row in values:by_date[row['date']].append(float(row[metric]))
                    daily=np.array([np.mean(by_date[date]) for date in design['dates'] if by_date[date]])
                    cluster_margin=float(student_t.ppf(.975,len(daily)-1)*daily.std(ddof=1)/np.sqrt(len(daily))) if len(daily)>1 else None
                    grouped[key][metric]={'mean':float(x.mean()),'ci95_half_width':margin,'n':n,
                        'date_clustered_mean':float(daily.mean()),'date_clustered_ci95_half_width':cluster_margin,'n_dates':len(daily)}
    effects={}
    for regime in regimes:
        for mode in modes:
            for metric in ['custody_continuity','observable_custody','slew_energy_proxy','false_track_proxy']:
                effects[f'{regime}:{mode}:{metric}']={}
                for rate in rates:
                    differences=[];by_date=defaultdict(list)
                    for date in design['dates']:
                        for model_seed in model_seeds:
                            for rep in range(replicates):
                                baseline=row_index[(date,regime,mode,rep,model_seed,0.0)][metric]
                                result=row_index[(date,regime,mode,rep,model_seed,float(rate))][metric]
                                difference=float(result)-float(baseline)
                                differences.append(difference);by_date[date].append(difference)
                    x=np.asarray(differences,dtype=float);n=len(x)
                    daily=np.array([np.mean(by_date[date]) for date in design['dates'] if by_date[date]])
                    effects[f'{regime}:{mode}:{metric}'][str(rate)]={'paired_mean_change':float(x.mean()),
                        'ci95_half_width':float(student_t.ppf(.975,n-1)*x.std(ddof=1)/np.sqrt(n)) if n>1 else None,'n_pairs':n,
                        'date_clustered_mean_change':float(daily.mean()),
                        'date_clustered_ci95_half_width':float(student_t.ppf(.975,len(daily)-1)*daily.std(ddof=1)/np.sqrt(len(daily))) if len(daily)>1 else None,
                        'n_dates':len(daily)}
    result={'status':'completed','design_signature':signature,'design':design,'interpretation':'Controlled simulated sensor outage intervention; synthetic sensor assumptions and historical orbital geometry, not observed sensor telemetry.',
        'policy':'frozen DOE-recommended checkpoints; no retraining by dropout level' if len(model_seeds)>1 else 'frozen DOE-recommended checkpoint, no retraining by dropout level',
        'checkpoint':design['checkpoint'],'model_seeds':model_seeds,
        'checkpoint_provenance':checkpoint_provenance,
        'dates':design['dates'],'completed_dates':[d for d in design['dates'] if any(r['date']==d for r in rows)],
        'orbit_regimes':regimes,'replicates_per_date_regime_mode_rate':replicates,'model_checkpoint_count':len(model_seeds),'rates':rates,'modes':modes,
        'dropout_definition':{'independent':'each eligible assigned observation is suppressed when its pre-drawn per-step, agent, and target uniform is below the configured rate',
            'burst':'per-sensor persistent Markov outage that transitions at every simulation timestep, including idle timesteps; entry probability is calibrated to the configured stationary target rate'},
        'paired_randomness':'Per-step, agent, target detection and independent-dropout draws are common across outage-rate treatments. Sensor-priority randomness is on an independent stream. Burst outages share transition uniforms across rates.',
        'configuration':{k:config.get(k) for k in ['dropout_burst_persistence','agents','targets','duration_minutes','step_seconds','max_element_age_hours']},
        'uncertainty_note':'Pooled intervals treat simulation-seed, model-training-seed, and date runs as independent. Date-clustered intervals average simulation seeds and frozen model checkpoints within each fixed historical date first; n_dates is the number of sampled dates, not independent orbit trajectories.',
        'metrics':grouped,'paired_vs_zero_dropout':effects}
    (out/'dropout_summary.json').write_text(json.dumps(result,indent=2,allow_nan=False))
    (out/'checkpoint_provenance.json').write_text(json.dumps(checkpoint_provenance,indent=2)+'\n')
    lines=['# Simulated sensor-dropout study','',result['interpretation'],'',
        f"Frozen policy: `{result['policy']}` from `{checkpoint_provenance['source_study_kind']}` (`{checkpoint_provenance['checkpoint_sha256'][:12]}…`). Historical windows: {', '.join(d[:10] for d in dates)}. Orbit regimes: {', '.join(regimes)}. {replicates} paired simulation seeds per date, checkpoint, and regime-condition.",'',
        'Dropout is applied to eligible, conflict-free assigned observations. Exogenous detection, dropout, and priority randomness use separate streams, with per-step/agent/target random numbers paired across independent-dropout rates. Burst outage state transitions on every simulation timestep, including when a sensor is idle. Custody is the fraction of modeled targets remaining within the configured custody interval. Slew is a normalized angle proxy; false-track is a failed-observation proxy. Neither represents calibrated hardware telemetry. Confidence intervals below cluster by historical date, averaging the paired seeds within each annual window first.','',
        '| Orbit | Outage process | Requested rate | Observed rate | Mean custody | Custody change vs 0% (date-clustered 95% CI) |','|---|---|---:|---:|---:|---:|']
    def format_clustered_effect(effect):
        margin=effect['date_clustered_ci95_half_width']
        interval='n/a' if margin is None else f"{margin:.3f}"
        return f"{effect['date_clustered_mean_change']:+.3f} ± {interval}"
    for regime in regimes:
        for mode in modes:
            for rate in rates:
                key=f'{regime}:{mode}:{rate:g}'; metric=result['metrics'][key];effect=result['paired_vs_zero_dropout'][f'{regime}:{mode}:custody_continuity'][str(rate)]
                lines.append(f"| {regime.upper()} | {mode} | {rate:.0%} | {metric['dropout_rate_observed']['date_clustered_mean']:.1%} | {metric['custody_continuity']['date_clustered_mean']:.3f} | {format_clustered_effect(effect)} |")
    lines += ['', 'Orbit classes use approximate mean-element bins, with high eccentricity taking precedence. This estimates how one frozen policy responds to injected sensor outages in the simulated scenarios. It does not establish real sensor outage behavior, attitude knowledge, or operational constellation performance. The sampled windows are discrete historical snapshots, not continuous four-year playback.']
    (out/'dropout_report.md').write_text('\n'.join(lines)+'\n')
    return result
