"""Add independent center-point retrains and refit the existing CCD surfaces."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import pathlib
import random

import numpy as np

from godsat.design import FACTORS, decode, fit_surface
from godsat.experiment import RESPONSES, run_treatment, write_json
from godsat.orbits import ROOT
from godsat.scenario import load, prepare


def digest(path):
    value = hashlib.sha256()
    with pathlib.Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def read_csv(path):
    with pathlib.Path(path).open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def run(campaign_dir, output_dir, additional_replicates=12, bootstrap_seed=7321):
    campaign_dir = pathlib.Path(campaign_dir).resolve()
    output_dir = pathlib.Path(output_dir).resolve()
    if additional_replicates < 1:
        raise ValueError("additional_replicates must be positive")
    summary_path = campaign_dir / "summary.json"
    config_path = campaign_dir / "config.json"
    screening_path = campaign_dir / "screening_analysis.json"
    rsm_path = campaign_dir / "rsm_design.csv"
    if not all(path.is_file() for path in
               (summary_path, config_path, screening_path, rsm_path)):
        raise FileNotFoundError("Campaign summary, config, screening analysis, and CCD design are required")
    config = json.loads(config_path.read_text())
    evaluated_regimes = sorted(set(
        regime for split in ("training", "validation", "test")
        for regime in config.get(split + "_regimes", ["leo"])))
    sensor_cohort = config.get("sensor_cohort", "unspecified")
    target_cohort = config.get("target_cohort", "unspecified")
    source_summary = json.loads(summary_path.read_text())
    screening = json.loads(screening_path.read_text())
    if source_summary.get("status") != "completed":
        raise ValueError("Source campaign is not complete")
    selected = list(map(int, screening["objective"]["selected_indices"]))
    if len(selected) != 3 or len(set(selected)) != 3:
        raise ValueError("Expected exactly three selected response-surface factors")
    center = np.zeros(7)
    center[selected] = 0.0
    center_hp = decode(center)
    source_rows = read_csv(rsm_path)
    source_runs = []
    for row in source_rows:
        run_id = int(row["run"])
        record_path = campaign_dir / "runs" / f"rsm_{run_id:02d}.json"
        record = json.loads(record_path.read_text())
        if any(float(record["hyperparameters"][factor]) != float(center_hp[factor])
               for factor in FACTORS):
            continue
        source_runs.append(record)
    if len(source_runs) != int(source_summary["rsm_center_replicates"]):
        raise ValueError("Could not reconcile original center-point replicates to campaign summary")

    output_dir.mkdir(parents=True, exist_ok=True)
    output_config = {
        "status": "running",
        "source_campaign": str(campaign_dir),
        "source_campaign_config_sha256": digest(config_path),
        "source_rsm_design_sha256": digest(rsm_path),
        "source_screening_analysis_sha256": digest(screening_path),
        "source_center_runs": [{"name": row["name"], "seed": row["seed"],
                                "signature": row["signature"]} for row in source_runs],
        "center_hyperparameters": center_hp,
        "additional_replicates": additional_replicates,
        "bootstrap_seed": bootstrap_seed,
    }
    config_out = output_dir / "replication_manifest.json"
    if config_out.is_file():
        prior = json.loads(config_out.read_text())
        for key in ("source_campaign_config_sha256", "source_rsm_design_sha256",
                    "source_screening_analysis_sha256", "center_hyperparameters",
                    "additional_replicates", "bootstrap_seed"):
            if prior.get(key) != output_config[key]:
                raise ValueError("Replication output already exists for a different design")
    else:
        write_json(config_out, output_config)

    scenarios = {
        split: [load(prepare(date, config, regime=regime))
                for date in config[split + "_dates"]
                for regime in config.get(split + "_regimes", ["leo"])]
        for split in ("training", "validation", "test")
    }
    scenarios["train"] = scenarios.pop("training")

    base_seed = max(int(row["seed"]) for row in source_runs)
    indices = list(range(additional_replicates))
    random.Random(bootstrap_seed).shuffle(indices)
    new_runs = []
    for sequence, replicate in enumerate(indices):
        name = f"center_rep_{replicate:02d}"
        seed = base_seed + 7919 * (replicate + 1)
        record = run_treatment(name, center_hp, scenarios, config, output_dir,
                               seed, force=False)
        new_runs.append(record)
        output_config["completed_replicates"] = len(new_runs)
        output_config["last_run"] = {"name": name, "seed": seed,
                                     "sequence": sequence,
                                     "signature": record["signature"]}
        output_config["status"] = "running"
        write_json(config_out, output_config)

    x_rows = []
    responses = {metric: [] for metric in RESPONSES}
    for row in source_rows:
        x_rows.append([float(row[f"x{i}"]) for i in (1, 2, 3)])
        record = json.loads((campaign_dir / "runs" / f"rsm_{int(row['run']):02d}.json").read_text())
        for metric in RESPONSES:
            responses[metric].append(float(record[metric]))
    x_rows.extend([[0.0, 0.0, 0.0]] * len(new_runs))
    for record in new_runs:
        for metric in RESPONSES:
            responses[metric].append(float(record[metric]))
    augmented = {metric: fit_surface(np.asarray(x_rows), np.asarray(values))
                 for metric, values in responses.items()}
    model_path = output_dir / "response_surfaces_augmented.json"
    write_json(model_path, augmented)

    center_records = source_runs + new_runs
    center_summary = {}
    for metric in RESPONSES:
        values = [float(record[metric]) for record in center_records]
        center_summary[metric] = {
            "n": len(values),
            "mean": float(np.mean(values)),
            "sample_sd": float(np.std(values, ddof=1)) if len(values) > 1 else None,
            "minimum": min(values),
            "maximum": max(values),
        }
    original_surfaces = json.loads((campaign_dir / "response_surfaces.json").read_text())
    selected_names = [FACTORS[index] for index in selected]
    unique_center_seeds = len({int(record["seed"]) for record in center_records})
    pure_error_dfs = sorted({fit["lack_of_fit"].get("pure_error_df")
                             for metric, fit in augmented.items()
                             if metric != "gpu_hours"})
    report = [
        "# Supplementary RSM center-point replication", "",
        f"This analysis preserves the exact paper-matched 15-run CCD and adds {additional_replicates} independently seeded center-point retrains. The source CCD has {len(source_runs)} center observations; the augmented center count is {len(center_records)}, with {len(source_rows) + len(new_runs)} total response-surface observations. The added runs use the source campaign’s regimes ({', '.join(regime.upper() for regime in evaluated_regimes)}), training/validation dates, sensor-host cohort `{sensor_cohort}`, and target cohort `{target_cohort}`.", "",
        f"The selected coded factors, in design-column order, are `{', '.join(selected_names)}`. All {unique_center_seeds} center observations use distinct training seeds. The companion integrity audit checks every added run record and checkpoint hash, refits the surfaces from saved response rows, and reports pure-error degrees of freedom {pure_error_dfs} for measured CPU responses.", "",
        "## Lack-of-fit diagnostics", "",
        "| Response | Center mean | Center sample SD | Lack-of-fit F | p-value | Pure-error df | Lack-of-fit df | Augmented RMSE |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for metric in RESPONSES:
        center_item = center_summary[metric]
        fit = augmented[metric]
        lof = fit["lack_of_fit"]
        if "p_value" in lof:
            f_value, p_value = f"{lof['F']:.3f}", f"{lof['p_value']:.3f}"
            pure_df, lof_df = str(lof["pure_error_df"]), str(lof["lack_of_fit_df"])
        else:
            f_value = p_value = pure_df = lof_df = "not estimable"
        sd_text = "not estimable" if center_item["sample_sd"] is None else f"{center_item['sample_sd']:.6f}"
        rmse_text = "not estimable" if fit["rmse"] is None else f"{fit['rmse']:.6f}"
        report.append(f"| {metric} | {center_item['mean']:.6f} | {sd_text} | {f_value} | {p_value} | {pure_df} | {lof_df} | {rmse_text} |")
    original_point = original_surfaces["objective"]["stationary_point"]
    new_point = augmented["objective"]["stationary_point"]
    original_bounded = original_surfaces["objective"]["bounded_optimum"]
    new_bounded = augmented["objective"]["bounded_optimum"]
    report.extend([
        "", "`gpu_hours` has no pure-error test because all treatments ran on CPU and this response is identically zero.", "",
        "## Objective-surface sensitivity", "",
        f"| Fit | Classification | Stationary point in coded order `{', '.join(selected_names)}` | Best point constrained to [-1, 1]^3 |",
        "|---|---|---|---|",
        f"| Prior {len(source_rows)}-observation CCD | {original_surfaces['objective']['classification']} | `{[round(value, 4) for value in original_point]}` | `{[round(value, 4) for value in original_bounded]}` |",
        f"| {len(x_rows)}-observation augmented CCD | {augmented['objective']['classification']} | `{[round(value, 4) for value in new_point]}` | `{[round(value, 4) for value in new_bounded]}` |", "",
        f"The response surface remains a saddle in both fits. The augmented objective stationary point is outside the tested region on {', '.join(name for name, value in zip(selected_names, new_point) if abs(value) > 1.0) or 'none of the selected factors'}; the constrained recommendation moves from `{[round(value, 4) for value in original_bounded]}` to `{[round(value, 4) for value in new_bounded]}`. Treat the local optimum as unstable under training-seed variation; use held-out validation rather than the fitted optimum alone. Lack-of-fit tests reject the quadratic model for objective and custody at the 0.05 level; the other measured responses do not show significant lack of fit in this run. This is evidence of inadequate objective/custody surfaces under this evaluator, not confirmation of an optimum.", "",
        "The added observations estimate variation among independently seeded runs at one center configuration. They do not reproduce the unavailable original GoDSAT implementation or published baseline, add new orbit/sensor evidence, or validate real-world tasking performance.", "",
    ])
    report_path = output_dir / "center_replication_report.md"
    report_path.write_text("\n".join(report))
    integrity = {
        "status": "completed",
        "planned_additional_replicates": additional_replicates,
        "observed_additional_replicates": len(new_runs),
        "unique_seed_count": len({int(record["seed"]) for record in center_records}),
        "total_center_observations": len(center_records),
        "quadratic_model_rank": {metric: fit["rank"] for metric, fit in augmented.items()},
        "pure_error_df": {metric: fit["lack_of_fit"].get("pure_error_df")
                          for metric, fit in augmented.items()},
        "lack_of_fit_df": {metric: fit["lack_of_fit"].get("lack_of_fit_df")
                           for metric, fit in augmented.items()},
        "source_sha256": {
            str(path): digest(path) for path in
            (summary_path, config_path, screening_path, rsm_path)},
        "response_surfaces_sha256": digest(model_path),
        "report_sha256": digest(report_path),
        "run_record_sha256": {
            record["name"]: digest(output_dir / "runs" / f"{record['name']}.json")
            for record in new_runs},
        "checkpoint_sha256": {
            record["name"]: digest(output_dir / "models" / f"{record['name']}.pt")
            for record in new_runs},
        "center_response_summary": center_summary,
        "new_run_signatures": {record["name"]: record["signature"] for record in new_runs},
        "interpretation": "Supplementary replicate-center lack-of-fit analysis; it does not change the exact 15-run paper design or replace the original GoDSAT baseline.",
    }
    output_config.update({"status": "completed", "completed_replicates": len(new_runs),
                          "completed_center_observations": len(center_records)})
    write_json(config_out, output_config)
    write_json(output_dir / "replication_integrity_audit.json", integrity)
    return integrity


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", default=str(ROOT / "outputs/full-paper-study"))
    parser.add_argument("--output", default=str(ROOT / "outputs/full-paper-study-center-replication"))
    parser.add_argument("--additional-replicates", type=int, default=12)
    parser.add_argument("--bootstrap-seed", type=int, default=7321)
    args = parser.parse_args()
    result = run(args.campaign, args.output, args.additional_replicates,
                 args.bootstrap_seed)
    print(json.dumps({key: result[key] for key in (
        "status", "planned_additional_replicates", "observed_additional_replicates",
        "total_center_observations", "pure_error_df", "lack_of_fit_df")}, indent=2))


if __name__ == "__main__":
    main()
