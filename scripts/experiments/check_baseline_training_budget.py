"""Development-only actor-critic budget diagnostic, with frozen prospective scope.

Uses the existing documented implementation, not an unidentified published
baseline. Does not consume test scenarios or select on their outcomes.
"""
from __future__ import annotations

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))


import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.stats import t
import torch

from godsat.experiment import (export_csv, run_treatment, scenario_fingerprint,
                               write_json, runtime_provenance)
from godsat.learning import Agent, evaluate
from godsat.scenario import load, prepare


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def interval(values):
    values = np.asarray(values, dtype=float)
    mean = float(values.mean())
    half = float(t.ppf(.975, len(values)-1)*values.std(ddof=1)/np.sqrt(len(values)))
    return {'mean': mean, 'ci95': [mean-half, mean+half], 'n_training_seeds': len(values)}


def run(config_path, output):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    config = json.loads(Path(config_path).read_text())
    # The final test scenes are deliberately absent from this diagnostic.
    config.pop('test_dates', None)
    config.pop('test_regimes', None)
    budgets, seeds = [40, 160, 640], [101, 211, 307]
    evaluation_seeds = [9001, 9011, 9021]
    plan = {
        'purpose': 'Training-budget diagnostic for our documented actor-critic reference; not published-baseline reproduction',
        'budgets_episodes': budgets, 'training_seeds': seeds,
        'development_evaluation_seeds': evaluation_seeds,
        'training_dates': config['training_dates'], 'development_dates': config['validation_dates'],
        'hyperparameters': config['baseline'], 'randomized_run_order_seed': 20261101,
        'test_data_used': False,
        'interpretation': 'Report all curves and paired budget contrasts; three seeds and one development date cannot certify convergence or generalization. No extra budgets added in response to a desired result.',
        'provisional_stability_margin_custody': .02,
        'stability_rule': 'The paired 95% interval for 640 minus 160 episodes must be wholly within +/-0.02 custody before calling the final two budgets provisionally stable. This is not a convergence proof or a performance threshold.',
        'config_input_sha256': digest(config_path), 'script_sha256': digest(__file__),
        'runtime': runtime_provenance(),
    }
    plan_path = output/'prospective-plan.json'
    if plan_path.exists() and json.loads(plan_path.read_text()) != plan:
        raise ValueError('Diagnostic definition/software changed; use a new output folder')
    write_json(plan_path, plan)
    write_json(output/'development-config.json', config)
    scenes = {
        'train': [load(prepare(date, config)) for date in config['training_dates']],
        'validation': [load(prepare(date, config)) for date in config['validation_dates']],
    }
    config['_scenario_sha256'] = scenario_fingerprint(scenes)
    jobs = [(budget, seed) for budget in budgets for seed in seeds]
    np.random.default_rng(20261101).shuffle(jobs)
    write_json(output/'run-order.json', jobs)
    rows = []
    for budget, seed in jobs:
        execution = {**config, 'training_episodes': budget}
        name = f'baseline_episodes_{budget}_seed_{seed}'
        r = run_treatment(name, config['baseline'], scenes, execution, output, seed)
        saved = torch.load(output/'models'/(name+'.pt'), map_location='cpu', weights_only=True)
        model = Agent(saved['obs_dim'], saved['actions'], saved['hp'])
        model.load_state_dict(saved['state_dict'])
        for evaluation_seed in evaluation_seeds:
            metrics, _, _ = evaluate(model, scenes['validation'], config, saved['hp'], evaluation_seed)
            rows.append({'budget': budget, 'training_seed': seed, 'evaluation_seed': evaluation_seed, **metrics})
        export_csv(output/'development-responses.csv', rows)
    controls = []
    for policy in ['greedy', 'random']:
        for seed in evaluation_seeds:
            metrics, _, _ = evaluate(None, scenes['validation'], config, config['baseline'], seed, policy=policy)
            controls.append({'policy': policy, 'evaluation_seed': seed, **metrics})
    export_csv(output/'development-controls.csv', controls)
    metrics = ['custody_continuity', 'objective', 'slew_energy_joules']
    seed_means = {(budget, seed, key): float(np.mean([r[key] for r in rows
                  if r['budget'] == budget and r['training_seed'] == seed]))
                  for budget in budgets for seed in seeds for key in metrics}
    summaries = {str(b): {key: interval([seed_means[b, s, key] for s in seeds])
                         for key in metrics} for b in budgets}
    contrasts = {}
    for low, high in zip(budgets, budgets[1:]):
        contrasts[f'{high}_minus_{low}'] = {key: interval([
            seed_means[high, s, key]-seed_means[low, s, key] for s in seeds]) for key in metrics}
    bound = contrasts['640_minus_160']['custody_continuity']['ci95']
    result = {
        'status': 'completed_development_only_budget_diagnostic',
        'scenario_sha256': config['_scenario_sha256'],
        'budget_summaries': summaries, 'paired_budget_contrasts': contrasts,
        'final_two_budgets_meet_provisional_stability_rule': bound[0] >= -.02 and bound[1] <= .02,
        'control_custody_means': {p: float(np.mean([r['custody_continuity'] for r in controls if r['policy'] == p]))
                                 for p in ['greedy', 'random']},
        'test_data_used': False, 'plan_sha256': digest(plan_path),
        'artifacts_sha256': {str(p.relative_to(output)): digest(p) for p in sorted(output.rglob('*'))
                             if p.is_file() and p.name != 'summary.json'},
        'scope': 'Nine complete training runs, 27 development evaluations and six heuristic evaluations. Seed intervals condition on one development geometry and three training seeds; no claim of final validation, convergence, original equivalence or physical calibration.',
    }
    write_json(output/'summary.json', result)
    print(json.dumps({k: result[k] for k in ['status', 'budget_summaries', 'control_custody_means',
                                            'final_two_budgets_meet_provisional_stability_rule']}), flush=True)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path('configs/archive/governing-design-physical-leo.json'))
    parser.add_argument('--output', type=Path, default=Path('outputs/baseline-training-budget-20261101'))
    args = parser.parse_args()
    run(args.config, args.output)
