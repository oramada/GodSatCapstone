"""Execute the registered ground-tracking/NEXT factorial and dropout rerun."""
from __future__ import annotations

if __package__ in (None, ''):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import os
os.environ['OPENBLAS_NUM_THREADS'] = '1'
os.environ['OMP_NUM_THREADS'] = '1'

import argparse
import hashlib
import json
import multiprocessing
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import shutil
import time

import numpy as np
from scipy.stats import t
import torch

from godsat.design import ccd, fit_surface
from godsat.experiment import (campaign, export_csv, runtime_provenance,
                               scenario_fingerprint, treatment_batch, write_json)
from godsat.learning import Agent, evaluate
from godsat.orbits import ROOT, utc
from godsat.scenario import prepare, load
from godsat.scope import validate_execution, validate_selected
from scripts.validation.audit_physical_campaign import reconstruct_trace


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def mean_interval(values):
    values = np.asarray(values, dtype=float)
    half = float(t.ppf(.975, len(values)-1)*values.std(ddof=1)/np.sqrt(len(values)))
    return {'mean': float(values.mean()), 'ci95': [float(values.mean()-half), float(values.mean()+half)], 'n': len(values)}


def audit_scenes(config, output):
    """Round-trip ground positions and independently evaluate elevation in ITRS."""
    from astropy import units as u
    from astropy.coordinates import CartesianRepresentation, EarthLocation, ITRS, TEME
    from astropy.time import Time
    from astropy.utils import iers
    items=[]
    with iers.conf.set_temp('auto_download',False):
        for date in config['training_dates']+config['validation_dates']+config['test_dates']:
            path=prepare(date,config)
            scene=load(path)
            agents=int(scene['agents'])
            validate_selected(scene['ids'][agents:])
            position_error=elevation_error=0.
            for k in [0,(len(scene['times'])-1)//2,len(scene['times'])-1]:
                at=Time(utc(str(scene['times'][k])))
                ground=scene['states'][k,:agents,:3]
                recovered=TEME(CartesianRepresentation(ground.T*u.km),obstime=at).transform_to(ITRS(obstime=at)).cartesian.xyz.to_value(u.m).T
                xyz=scene['ground_itrs_m'][k]
                position_error=max(position_error,float(np.max(np.abs(recovered-xyz))))
                location=EarthLocation.from_geocentric(xyz[:,0]*u.m,xyz[:,1]*u.m,xyz[:,2]*u.m)
                lon,lat,_=location.geodetic
                up=np.asarray(np.column_stack([np.cos(lat)*np.cos(lon),np.cos(lat)*np.sin(lon),np.sin(lat)]))
                targets=scene['states'][k,agents:,:3]
                valid=np.isfinite(targets).all(axis=-1)
                terrestrial=TEME(CartesianRepresentation(targets[valid].T*u.km),obstime=at).transform_to(ITRS(obstime=at)).cartesian.xyz.to_value(u.km).T
                delta=terrestrial[None,:,:]-xyz[:,None,:]/1000
                direction=delta/np.linalg.norm(delta,axis=-1,keepdims=True)
                expected=np.sum(direction*up[:,None,:],axis=-1)
                inertial=targets[valid][None,:,:]-ground[:,None,:]
                inertial/=np.linalg.norm(inertial,axis=-1,keepdims=True)
                actual=np.sum(inertial*scene['ground_up'][k,:,None,:],axis=-1)
                elevation_error=max(elevation_error,float(np.max(np.abs(expected-actual))))
            if position_error>1e-5 or elevation_error>1e-10:
                raise ValueError('Independent ground frame/elevation audit failed')
            items.append({'date':date,'scenario_path':str(path.relative_to(ROOT)),
                          'scenario_sha256':sha(path),'metadata_sha256':sha(path.with_suffix('.json')),
                          'ground_position_roundtrip_max_m':position_error,
                          'elevation_sine_max_difference':elevation_error,
                          'target_valid_fraction':float(np.isfinite(scene['states'][:,agents:,0]).mean()),
                          'ground_sites':agents,'target_members':len(scene['ids'])-agents})
    write_json(output/'scenario-audit.json',{'status':'passed','scenes':items,
        'scope':'Three sampled times per scene: all six sites and every valid target checked in an independent terrestrial frame. Full arrays hashed. Not external orbit truth or calibrated sensor validation.'})


def dropout_group(arguments):
    folder, config, scene_path, date, label, model_seed, plan_hash = arguments
    folder = Path(folder)
    path = folder/'dropout/groups'/f'{date[:10]}_{label}_{model_seed}.json'
    torch.set_num_threads(1)
    checkpoint = None if label == 'greedy' else folder/'models'/f'validate_{label}_{model_seed}.pt'
    signature = {'plan_sha256': plan_hash, 'checkpoint_sha256': sha(checkpoint) if checkpoint else None,
                 'scene_sha256': sha(scene_path)}
    if path.exists():
        prior = json.loads(path.read_text())
        if prior['signature'] != signature:
            raise ValueError('Dropout cache does not match the registered run')
        return prior
    if checkpoint:
        saved = torch.load(checkpoint, map_location='cpu', weights_only=True)
        model = Agent(saved['obs_dim'], saved['actions'], saved['hp'])
        model.load_state_dict(saved['state_dict'])
        model.eval()
        hp = saved['hp']
    else:
        model, hp = None, config['baseline']
    scenario = load(scene_path)
    rows, audited = [], 0
    for mode in ['independent', 'burst']:
        for replicate in range(20):
            seed = 7441+replicate
            for rate in config['dropout_rates']:
                traces = replicate == 0 and rate in [0., .2]
                metrics, trace, _ = evaluate(model, [scenario], config, hp, seed,
                    policy='greedy' if label == 'greedy' else 'learned', traces=traces,
                    dropout_probability=rate, dropout_mode=mode)
                if traces:
                    independent = reconstruct_trace(scenario, config, seed, trace[0], probability=rate, mode=mode)
                    for key, value in independent.items():
                        if not np.isclose(value, metrics[key], rtol=1e-10, atol=1e-12):
                            raise ValueError('Dropout action reconstruction mismatch: '+key)
                    audited += 1
                rows.append({'date': date, 'configuration': label, 'model_seed': model_seed,
                             'mode': mode, 'replicate': replicate, 'seed': seed, 'rate': rate, **metrics})
    result = {'signature': signature, 'rows': rows, 'independent_action_reconstructions': audited}
    write_json(path, result)
    print(f'Dropout complete: {date[:10]} {label} seed {model_seed}', flush=True)
    return result


def run(config_path, output):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    config = json.loads(Path(config_path).read_text())
    validate_execution(config=config)
    protocol = {
        'study': 'Iridium NEXT targets observed by six hypothetical ground tracking sensors',
        'config': config, 'runtime': runtime_provenance(),
        'methodology_pdf_sha256': sha(ROOT/'docs/papers/methodology.pdf'),
        'source_hashes': {str(p.relative_to(ROOT)): sha(p) for p in sorted((ROOT/'godsat').glob('*.py'))},
        'runner_sha256': sha(__file__),
        'screening_treatments': 16, 'ccd_unique_treatments': 15, 'bo_treatments': 31,
        'validation_retrains': 15, 'independent_ccd_diagnostic_runs': 45,
        'diagnostic_seed_rule': '120000 + 1000*point_index + replicate_index; all 45 seeds distinct',
        'diagnostic_use': 'Development-only adequacy check; never used to change the candidate using final test responses',
        'dropout_design': {'replicates': 20, 'rates': config['dropout_rates'], 'modes': ['independent', 'burst'],
                           'policies': ['baseline', 'doe_recommended', 'greedy'], 'dates': config['test_dates']},
        'primary_claims': ['custody increase versus implemented reference', 'modeled pointing-energy reduction versus implemented reference'],
        'multiplicity': 'Two primary paired comparisons: use 97.5% intervals for each (Bonferroni family alpha .05); also retain ordinary 95% descriptive intervals',
        'budget': '40 episodes per treatment/retrain for a finite-budget rerun; no claim of convergence. Extra diagnostics reported outside 31-versus-31 search count.',
        'parallel_cost': 'Screen/CCD/retrains use four workers; BO remains sequential. Equal trial counts are not equal elapsed compute. Report aggregate treatment wall time and actual total elapsed separately.',
        'ground_model': 'Published station monuments; hypothetical detection, clutter and gimbal. 10-degree geometric elevation cutoff, no refraction/weather/illumination. No measured NEXT observations.',
        'position_information': 'Historical ephemeris positions remain available as predicted geometry; dropout suppresses sensor returns, not the simulator truth or ephemeris features.',
        'limits': 'Two held-out one-hour scenes, 60-second geometry slots, spares as targets, missing elements remain missing. No MEO and no published neural checkpoint reproduced.',
    }
    plan_path = output/'registered-plan.json'
    if plan_path.exists() and json.loads(plan_path.read_text()) != protocol:
        raise ValueError('Run definition/source changed; use a new output folder')
    write_json(plan_path, protocol)
    plan_hash = sha(plan_path)
    snapshot = output/'source-snapshot'
    for folder in ['godsat', 'configs']:
        for p in (ROOT/folder).glob('*'):
            if p.is_file():
                target = snapshot/folder/p.name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(p, target)
    for p in [Path(__file__), ROOT/'scripts/validation/audit_physical_campaign.py']:
        target = snapshot/p.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, target)
    start = time.perf_counter()
    audit_scenes(config,output)
    result = campaign(config, output, center_replicates=1)
    print('Primary factorial/BO/validation campaign complete', flush=True)
    scenes = {key: [load(prepare(date, config)) for date in config[dates]]
              for key, dates in [('train', 'training_dates'), ('validation', 'validation_dates'), ('test', 'test_dates')]}
    execution = {**config, '_scenario_sha256': scenario_fingerprint(scenes)}
    local = ccd(1, config['design_seed'])
    point_records = [json.loads((output/'runs'/f'rsm_{i:02d}.json').read_text()) for i in range(15)]
    jobs = []
    for point, record in enumerate(point_records):
        for replicate in range(3):
            seed = 120000+1000*point+replicate
            jobs.append((f'adequacy_{point:02d}_{replicate}', record['hyperparameters'], scenes,
                         execution, output, seed, False))
    np.random.default_rng(config['design_seed']+73).shuffle(jobs)
    write_json(output/'adequacy-run-order.json', [job[0] for job in jobs])
    diagnostic = treatment_batch(jobs, config['parallel_treatments'])
    by_name = {r['name']: r for r in diagnostic}
    x = np.repeat(local, 3, axis=0)
    ordered = [by_name[f'adequacy_{i:02d}_{r}'] for i in range(15) for r in range(3)]
    export_csv(output/'adequacy-responses.csv', [{k:v for k,v in r.items() if not isinstance(v, (dict, list))} for r in ordered])
    fits = {metric: fit_surface(x, [r[metric] for r in ordered])
            for metric in ['objective', 'custody_continuity', 'slew_energy_joules', 'false_track_rate']}
    write_json(output/'independent-ccd-adequacy.json', fits)
    print('Independent replicated CCD diagnostic complete', flush=True)
    # Every original development selection and final held-out response is replayed.
    replayed, traces_checked = 0, 0
    for path in sorted((output/'runs').glob('*.json')):
        r = json.loads(path.read_text())
        saved = torch.load(output/'models'/(r['name']+'.pt'), map_location='cpu', weights_only=True)
        model = Agent(saved['obs_dim'], saved['actions'], saved['hp'])
        model.load_state_dict(saved['state_dict'])
        observed, _, _ = evaluate(model, scenes['validation'], config, saved['hp'], 9001)
        for metric, value in observed.items():
            if not np.isclose(value, r[metric], atol=1e-12, rtol=0):
                raise ValueError('Development replay mismatch: '+r['name']+' '+metric)
        replayed += 1
    import csv
    validation = list(csv.DictReader((output/'validation.csv').open()))
    for row in validation:
        label, seed = row['configuration'], int(row['seed'])
        if label in ['greedy', 'random']:
            model, hp = None, config['baseline']
        else:
            saved = torch.load(output/'models'/f'validate_{label}_{seed}.pt', map_location='cpu', weights_only=True)
            model = Agent(saved['obs_dim'], saved['actions'], saved['hp'])
            model.load_state_dict(saved['state_dict'])
            hp = saved['hp']
        observed, traces, _ = evaluate(model, scenes['test'], config, hp, seed+50000,
                                      policy=label if label in ['greedy', 'random'] else 'learned', traces=True)
        for metric, value in observed.items():
            if not np.isclose(value, float(row[metric]), atol=1e-12, rtol=0):
                raise ValueError('Held-out replay mismatch: '+label+' '+metric)
        for scene_index, (scene, trace) in enumerate(zip(scenes['test'], traces)):
            reconstruct_trace(scene, config, seed+50000+1009*scene_index, trace)
            traces_checked += 1
    groups = []
    for date in config['test_dates']:
        path = prepare(date, config)
        for label in ['baseline', 'doe_recommended', 'greedy']:
            for seed in config['validation_seeds'] if label != 'greedy' else [0]:
                groups.append((str(output), config, str(path), date, label, seed, plan_hash))
    with ProcessPoolExecutor(max_workers=config['parallel_treatments'], mp_context=multiprocessing.get_context('spawn')) as pool:
        dropout = list(pool.map(dropout_group, groups))
    rows = [r for group in dropout for r in group['rows']]
    export_csv(output/'dropout-responses.csv', rows)
    indexed = {(r['date'], r['configuration'], r['model_seed'], r['mode'], r['replicate'], r['rate']):r for r in rows}
    if len(indexed) != len(rows):
        raise ValueError('Duplicate dropout condition rows')
    effects = []
    for label in ['baseline', 'doe_recommended', 'greedy']:
        seeds = config['validation_seeds'] if label != 'greedy' else [0]
        for mode in ['independent', 'burst']:
            for rate in config['dropout_rates']:
                for metric in ['custody_continuity', 'observable_custody', 'slew_energy_joules']:
                    differences = []
                    for replicate in range(20):
                        delta = []
                        for date in config['test_dates']:
                            for seed in seeds:
                                base = indexed[date,label,seed,mode,replicate,0]
                                changed = indexed[date,label,seed,mode,replicate,rate]
                                delta.append(changed[metric]-base[metric])
                        differences.append(float(np.mean(delta)))
                    effects.append({'configuration':label,'mode':mode,'rate':rate,'metric':metric,
                                    **mean_interval(differences),'scope':'Monte Carlo noise interval conditional on frozen checkpoints and two scenes; not uncertainty across training or scenario populations'})
    write_json(output/'dropout-effects.json', effects)
    primary = {}
    for metric in ['custody_continuity', 'slew_energy_joules']:
        before = np.asarray([float(r[metric]) for r in validation if r['configuration']=='baseline'])
        after = np.asarray([float(r[metric]) for r in validation if r['configuration']=='doe_recommended'])
        delta = after-before
        half = float(t.ppf(.9875, len(delta)-1)*delta.std(ddof=1)/np.sqrt(len(delta)))
        primary[metric] = {'paired_mean_change': float(delta.mean()), 'family_adjusted_ci': [float(delta.mean()-half),float(delta.mean()+half)],
                           'relative_change_percent': float(100*(after.mean()/before.mean()-1)) if before.mean() else None}
    audit = {'status':'passed', 'development_models_replayed':replayed,'heldout_rows_replayed':len(validation),
             'independent_heldout_action_reconstructions':traces_checked,
             'dropout_rows':len(rows),'independent_dropout_action_reconstructions':sum(g['independent_action_reconstructions'] for g in dropout),
             'all_pinned_next_targets_per_scene':80,'ground_sites_per_scene':6,'meo_included':False,
             'elapsed_wall_seconds':time.perf_counter()-start,'primary_comparisons':primary,'registered_plan_sha256':plan_hash,
             'adequacy_scope':'Classical lack-of-fit diagnostics conditional on fixed development geometry/noise; independence/normality/homoscedasticity are not proved.'}
    write_json(output/'rerun-audit.json', audit)
    print(json.dumps(audit, indent=2), flush=True)
    return result, audit


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=ROOT/'configs/iridium-next-ground.json')
    parser.add_argument('--output',type=Path,default=ROOT/'outputs/iridium-next-ground-20261104')
    args = parser.parse_args()
    run(args.config,args.output)
