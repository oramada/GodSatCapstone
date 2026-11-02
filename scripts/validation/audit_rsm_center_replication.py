"""Independently recheck supplementary RSM center-point retrains and refit."""
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
import math
import pathlib
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from godsat.design import FACTORS, decode, fit_surface
from godsat.experiment import RESPONSES, runtime_provenance, device_provenance, scenario_fingerprint
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


def equivalent(left, right, tolerance=1e-5):
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(
            equivalent(left[key], right[key], tolerance) for key in left)
    if isinstance(left, (list, tuple)) and isinstance(right, (list, tuple)):
        return len(left) == len(right) and all(
            equivalent(a, b, tolerance) for a, b in zip(left, right))
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return math.isclose(float(left), float(right), rel_tol=tolerance,
                            abs_tol=tolerance)
    return left == right


def audit(output_dir, write=True):
    output_dir = pathlib.Path(output_dir).resolve()
    manifest_path = output_dir / "replication_manifest.json"
    saved_audit = output_dir / "replication_integrity_audit.json"
    manifest = json.loads(manifest_path.read_text())
    claims = json.loads(saved_audit.read_text())
    campaign = pathlib.Path(manifest["source_campaign"])
    campaign_config = json.loads((campaign / "config.json").read_text())
    response_metrics=list(dict.fromkeys(RESPONSES+campaign_config.get('additional_responses',[])))
    screening = json.loads((campaign / "screening_analysis.json").read_text())
    source_summary = json.loads((campaign / "summary.json").read_text())
    source_design_path = campaign / "rsm_design.csv"
    source_design = read_csv(source_design_path)
    failures = []

    if manifest.get("status") != "completed":
        failures.append("replication manifest is not completed")
    if claims.get("status") != "completed":
        failures.append("saved integrity audit is not completed")
    for path, expected in claims.get("source_sha256", {}).items():
        try:
            if digest(path) != expected:
                failures.append(f"source input hash mismatch: {path}")
        except OSError:
            failures.append(f"source input missing: {path}")
    for key, path in (("source_campaign_config_sha256", campaign / "config.json"),
                      ("source_rsm_design_sha256", source_design_path),
                      ("source_screening_analysis_sha256", campaign / "screening_analysis.json")):
        if digest(path) != manifest.get(key):
            failures.append(f"replication manifest source hash mismatch: {path}")

    selected = list(map(int, screening["objective"]["selected_indices"]))
    center = np.zeros(7)
    center[selected] = 0.0
    center_hp = decode(center)
    if center_hp != manifest.get("center_hyperparameters"):
        failures.append("center configuration does not match selected-factor center")

    original_centers = []
    x_rows = []
    metric_values = {metric: [] for metric in response_metrics}
    for row in source_design:
        run_id = int(row["run"])
        record = json.loads((campaign / "runs" / f"rsm_{run_id:02d}.json").read_text())
        x_rows.append([float(row[f"x{i}"]) for i in (1, 2, 3)])
        if np.all(np.asarray(x_rows[-1]) == 0.0):
            original_centers.append(record)
        for metric in response_metrics:
            metric_values[metric].append(float(record[metric]))
    if len(original_centers) != source_summary.get("rsm_center_replicates"):
        failures.append("original center replicates do not match source campaign summary")

    planned = int(manifest.get("additional_replicates", -1))
    expected_name_set = {f"center_rep_{i:02d}" for i in range(planned)}
    expected_names = list(claims.get("new_run_signatures", {}))
    if set(expected_names) != expected_name_set:
        failures.append("saved run-signature index does not match the planned replicate names")
    new_records = []
    scenarios = {split: [load(prepare(date, campaign_config, regime=regime))
        for date in campaign_config[split + "_dates"]
        for regime in campaign_config.get(split + "_regimes", ["leo"])]
        for split in ("training", "validation", "test")}
    scenarios["train"] = scenarios.pop("training")
    scenario_hash = scenario_fingerprint(scenarios)
    runtime = runtime_provenance()
    device = device_provenance(campaign_config)
    for name in expected_names:
        record_path = output_dir / "runs" / f"{name}.json"
        checkpoint_path = output_dir / "models" / f"{name}.pt"
        try:
            record = json.loads(record_path.read_text())
            if digest(record_path) != claims.get("run_record_sha256", {}).get(name):
                failures.append(f"run record hash mismatch: {name}")
            if digest(checkpoint_path) != claims.get("checkpoint_sha256", {}).get(name):
                failures.append(f"checkpoint hash mismatch: {name}")
        except (OSError, json.JSONDecodeError):
            failures.append(f"run record or checkpoint missing/invalid: {name}")
            continue
        if record.get("name") != name:
            failures.append(f"run name mismatch: {name}")
        if record.get("hyperparameters") != center_hp:
            failures.append(f"hyperparameter mismatch: {name}")
        expected_signature = hashlib.sha256(json.dumps({
            "hp": center_hp, "config": campaign_config, "seed": record.get("seed"),
            "runtime": runtime, "device": device, "scenario_sha256": scenario_hash,
        }, sort_keys=True).encode()).hexdigest()
        if record.get("runtime") != runtime or record.get("device_provenance") != device:
            failures.append(f"software or device provenance mismatch: {name}")
        if record.get("signature") != expected_signature:
            failures.append(f"run signature mismatch: {name}")
        new_records.append(record)

    seeds = [int(row["seed"]) for row in original_centers + new_records]
    if len(seeds) != len(set(seeds)):
        failures.append("center replication seeds are not unique")
    if len(new_records) != planned or claims.get("observed_additional_replicates") != planned:
        failures.append("additional center run count does not match the design")

    x_rows.extend([[0.0, 0.0, 0.0]] * len(new_records))
    for record in new_records:
        for metric in response_metrics:
            metric_values[metric].append(float(record[metric]))
    recomputed = {metric: fit_surface(np.asarray(x_rows), np.asarray(values))
                  for metric, values in metric_values.items()}
    model_path = output_dir / "response_surfaces_augmented.json"
    saved_model = json.loads(model_path.read_text())
    if digest(model_path) != claims.get("response_surfaces_sha256"):
        failures.append("saved augmented response surface hash mismatch")
    report_path = output_dir / "center_replication_report.md"
    try:
        report_hash = digest(report_path)
        if report_hash != claims.get("report_sha256"):
            failures.append("center replication report hash mismatch")
    except OSError:
        report_hash = None
        failures.append("center replication report missing")
    if not equivalent(recomputed, saved_model):
        failures.append("augmented response surfaces do not reproduce from saved response rows")

    total_centers = len(original_centers) + len(new_records)
    expected_df = total_centers - 1
    observed_df = {metric: recomputed[metric]["lack_of_fit"].get("pure_error_df")
                   for metric in response_metrics}
    for metric in response_metrics:
        if metric == "gpu_hours":
            if observed_df[metric] is not None:
                failures.append("GPU-hour pure error should be unavailable when all runs use CPU")
        elif observed_df[metric] != expected_df:
            failures.append(f"pure-error degrees of freedom mismatch for {metric}")

    result = {
        "status": "completed" if not failures else "invalid",
        "campaign": str(campaign),
        "additional_replicates_expected": planned,
        "additional_replicates_validated": len(new_records),
        "center_observations": total_centers,
        "unique_center_seeds": len(set(seeds)),
        "model_rank": {metric: fit["rank"] for metric, fit in recomputed.items()},
        "pure_error_df": observed_df,
        "lack_of_fit_df": {metric: fit["lack_of_fit"].get("lack_of_fit_df")
                           for metric, fit in recomputed.items()},
        "response_surfaces_reproduced": equivalent(recomputed, saved_model),
        "report_sha256": report_hash,
        "failures": failures,
    }
    if write:
        path = output_dir / "independent_validation.json"
        path.write_text(json.dumps(result, indent=2) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(ROOT / "outputs/full-paper-study-center-replication"))
    args = parser.parse_args()
    result = audit(args.output)
    print(json.dumps(result, indent=2))
    if result["status"] != "completed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
