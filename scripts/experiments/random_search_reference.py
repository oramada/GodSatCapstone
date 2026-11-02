"""Run an equal-budget random hyperparameter-search reference campaign.

The campaign uses the same four-regime cohort, training/validation dates,
episode budget, training seed, and five held-out test seeds as the exact DOE
study. The best of 31 candidates is selected only on the validation split.
"""

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))

import argparse
import csv
import hashlib
import json
import pathlib
import sys
import time

import numpy as np
import torch
from scipy.stats import t as student_t

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from godsat.experiment import run_treatment, write_json  # noqa: E402
from godsat.learning import Agent, compute_device, evaluate  # noqa: E402
from godsat.scenario import load, prepare  # noqa: E402
from godsat.design import decode  # noqa: E402


def read_csv(path):
    with pathlib.Path(path).open(newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv(path, rows):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def ci95(values):
    values = np.asarray(values, dtype=float)
    margin = (float(student_t.ppf(.975, len(values) - 1) *
                    values.std(ddof=1) / np.sqrt(len(values)))
              if len(values) > 1 else None)
    return {"mean": float(values.mean()), "ci95_half_width": margin,
            "n": int(len(values))}


def run(config_path, baseline_campaign, output, budget=31):
    config_path = pathlib.Path(config_path)
    baseline_campaign = pathlib.Path(baseline_campaign)
    output = pathlib.Path(output)
    config = json.loads(config_path.read_text())
    source_summary = json.loads((baseline_campaign / "summary.json").read_text())
    if source_summary.get("status") != "completed":
        raise ValueError("Reference campaign must be a completed exact-budget run")
    if source_summary.get("screening_runs") + source_summary.get("rsm_runs") != budget:
        raise ValueError("Random-search budget must match screening plus CCD treatment count")
    if source_summary.get("bayesian_runs") != budget:
        raise ValueError("Random-search budget must match Bayesian treatment count")
    if config.get("study_kind", "").find("four orbit regimes") < 0:
        raise ValueError("Expected the four-regime exact-budget study config")

    output.mkdir(parents=True, exist_ok=True)
    run_config = {"config": config, "budget": budget,
                  "selection_split": "validation", "search_seed": int(config["design_seed"])}
    config_file = output / "config.json"
    if config_file.exists() and json.loads(config_file.read_text()) != run_config:
        raise ValueError("Output directory contains a different search configuration")
    write_json(config_file, run_config)

    scenarios = {
        split: [load(prepare(date, config, regime=regime))
                for date in config[f"{split}_dates"]
                for regime in config.get(f"{split}_regimes", ["leo"])]
        for split in ("training", "validation", "test")
    }
    scenarios["train"] = scenarios.pop("training")
    rng = np.random.default_rng(config["design_seed"])
    treatments = []
    design = []
    for index in range(budget):
        coded = rng.uniform(-1.0, 1.0, 7)
        hp = decode(coded)
        name = f"random_{index:02d}"
        record = run_treatment(name, hp, scenarios, config, output,
                               config["training_seed"])
        treatments.append(record)
        design.append({"run": index, "name": name,
                       **{f"x{i + 1}": float(value) for i, value in enumerate(coded)},
                       **hp, "validation_objective": float(record["objective"])})
    write_csv(output / "random_search_design.csv", design)
    write_csv(output / "responses.csv", [
        {key: value for key, value in row.items()
         if not isinstance(value, (dict, list))}
        for row in treatments
    ])

    best = max(treatments, key=lambda row: float(row["objective"]))
    validation_rows = []
    for seed in map(int, config["validation_seeds"]):
        retrained = run_treatment(f"validate_random_search_best_{seed}",
                                  best["hyperparameters"], scenarios, config,
                                  output, seed)
        checkpoint = output / "models" / f"{retrained['name']}.pt"
        saved = torch.load(checkpoint, map_location="cpu", weights_only=True)
        model = Agent(saved["obs_dim"], saved["actions"], saved["hp"])
        model.load_state_dict(saved["state_dict"])
        model = model.to(compute_device(config))
        test_started = time.perf_counter()
        metrics, _, gpu_seconds = evaluate(model, scenarios["test"], config,
                                           best["hyperparameters"], seed + 50000)
        test_wall_seconds = time.perf_counter() - test_started
        validation_rows.append({"configuration": "random_search_best", "seed": seed,
                                **metrics, "test_wall_seconds": float(test_wall_seconds),
                                "wall_seconds": float(retrained["wall_seconds"] + test_wall_seconds),
                                "test_gpu_hours": float(gpu_seconds / 3600),
                                "gpu_hours": float(retrained["gpu_hours"] + gpu_seconds / 3600),
                                "compute_device": str(next(model.parameters()).device)})
    write_csv(output / "validation.csv", validation_rows)

    existing = read_csv(baseline_campaign / "validation.csv")
    by_policy_seed = {(row["configuration"], int(row["seed"])): row
                      for row in existing}
    comparisons = {}
    for policy in ("baseline", "doe_recommended", "bayesian_best"):
        for metric in ("objective", "custody_continuity", "slew_energy_proxy",
                       "false_track_proxy"):
            delta = [float(random_row[metric]) -
                     float(by_policy_seed[(policy, int(random_row["seed"]))][metric])
                     for random_row in validation_rows]
            comparisons[f"random_search_best_minus_{policy}_{metric}"] = ci95(delta)

    retraining_records = [json.loads(path.read_text())
        for path in (output / "runs").glob("validate_random_search_best_*.json")]
    run_hashes = {}
    for treatment in treatments + retraining_records:
        path = output / "models" / f"{treatment['name']}.pt"
        run_hashes[treatment["name"]] = hashlib.sha256(path.read_bytes()).hexdigest()
    summary = {
        "status": "completed",
        "study_kind": "supplementary equal-budget random hyperparameter search",
        "budget": budget,
        "matched_reference": str(baseline_campaign.resolve()),
        "matched_bayesian_budget": int(source_summary["bayesian_runs"]),
        "matched_doe_budget": int(source_summary["screening_runs"] + source_summary["rsm_runs"]),
        "selection_split": "validation",
        "heldout_test_dates": config["test_dates"],
        "test_regimes": config.get("test_regimes", ["leo"]),
        "validation_seeds": list(map(int, config["validation_seeds"])),
        "selected_run": best["name"],
        "selected_hyperparameters": best["hyperparameters"],
        "selected_validation_objective": float(best["objective"]),
        "test_metrics": {metric: ci95([row[metric] for row in validation_rows])
                         for metric in ("objective", "custody_continuity",
                                        "slew_energy_proxy", "false_track_proxy")},
        "paired_test_comparisons": comparisons,
        "search_training_wall_seconds": float(sum(row["wall_seconds"] for row in treatments)),
        "heldout_retraining_and_test_wall_seconds": float(sum(row["wall_seconds"] for row in validation_rows)),
        "search_and_validation_wall_seconds": float(
            sum(row["wall_seconds"] for row in treatments)
            + sum(row["wall_seconds"] for row in validation_rows)),
        "search_and_validation_gpu_hours": float(
            sum(row["gpu_hours"] for row in treatments + retraining_records)
            + sum(row["test_gpu_hours"] for row in validation_rows)),
        "source_campaign_signature": source_summary["study_kind"],
        "checkpoint_sha256": run_hashes,
        "limitations": [
            "Replacement actor-critic implementation, not original GoDSAT",
            "Five held-out seeds and one test date; inferential precision is limited",
            "Search evaluates validation scenarios and reports held-out test once",
            "Synthetic sensor and slew assumptions are inherited from the matched study",
        ],
    }
    write_json(output / "summary.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="exact-budget campaign config.json")
    parser.add_argument("--baseline-campaign", required=True,
                        help="completed campaign used for matched design and test evaluation")
    parser.add_argument("--output", required=True)
    parser.add_argument("--budget", type=int, default=31)
    args = parser.parse_args()
    print(json.dumps(run(args.config, args.baseline_campaign, args.output, args.budget),
                     indent=2))


if __name__ == "__main__":
    main()
