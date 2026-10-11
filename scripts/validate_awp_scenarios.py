"""Build four short AWP tasking scenarios and compare them with SGP4 replay."""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import pathlib
import subprocess
import sys

import numpy as np
import torch

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from godsat.dropout import evaluate_policy as evaluate_dropout
from godsat.learning import Agent, evaluate
from godsat.scenario import load, prepare


REGIMES = ("leo", "meo", "geo", "heo")


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def compare(sgp4_scenario, awp_scenario):
    if not np.array_equal(sgp4_scenario["ids"], awp_scenario["ids"]):
        raise ValueError("SGP4 and AWP scenarios selected different object IDs")
    if not np.array_equal(sgp4_scenario["times"], awp_scenario["times"]):
        raise ValueError("SGP4 and AWP scenarios use different sample times")
    import astropy.units as units
    from astropy.coordinates import (CartesianDifferential, CartesianRepresentation,
                                     GCRS, TEME)
    from astropy.time import Time

    reference = sgp4_scenario["states"]
    propagated = awp_scenario["states"]
    valid = np.isfinite(reference).all(axis=2) & np.isfinite(propagated).all(axis=2)
    time_index, object_index = np.where(valid)
    if not len(time_index):
        raise ValueError("No matched valid SGP4/AWP states to compare")
    instants = Time([str(sgp4_scenario["times"][index]).replace("Z", "").replace("+00:00", "")
                     for index in time_index], format="isot", scale="utc")
    states = reference[time_index, object_index]
    representation = CartesianRepresentation(
        states[:, :3].T * units.km,
        differentials=CartesianDifferential(
            states[:, 3:].T * units.km / units.s))
    gcrs = TEME(representation, obstime=instants).transform_to(GCRS(obstime=instants))
    reference_positions = gcrs.cartesian.xyz.to_value(units.km).T
    values = np.linalg.norm(reference_positions - propagated[time_index, object_index, :3],
                            axis=1)
    return {
        "matched_states": int(values.size),
        "position_separation_median_km": float(np.median(values)),
        "position_separation_p95_km": float(np.quantile(values, 0.95)),
        "position_separation_max_km": float(np.max(values)),
    }


def run(date: str | None, output: pathlib.Path, step_seconds: int = 60,
        dates: list[str] | None = None,
        campaign: pathlib.Path = ROOT / "outputs/all-orbits-paper-exact-active-hosts",
        dropout_replicates: int = 5,
        comparison_model: str = "awp_j2",
        dropout_burst_persistence: float | None = None,
        dropout_outage_rate: float = 0.2,
        dropout_burst_reference_step_seconds: float | None = None):
    if step_seconds <= 0 or 3600 % step_seconds:
        raise ValueError("step_seconds must be a positive divisor of one hour")
    if dropout_replicates < 1:
        raise ValueError("dropout_replicates must be positive")
    if comparison_model not in {"awp_j2", "awp_j2_sun_moon"}:
        raise ValueError("comparison_model must be awp_j2 or awp_j2_sun_moon")
    if not 0.0 < dropout_outage_rate <= 1.0:
        raise ValueError("dropout_outage_rate must be in (0, 1]")
    campaign = pathlib.Path(campaign).resolve()
    config_path = campaign / "config.json"
    if not config_path.is_file():
        raise FileNotFoundError(f"Paper-exact campaign config missing: {config_path}")
    config = json.loads(config_path.read_text())
    config.update(duration_minutes=60, step_seconds=step_seconds,
                  propagation_model="sgp4")
    if dropout_burst_persistence is not None:
        if not 0 <= dropout_burst_persistence < 1:
            raise ValueError("dropout_burst_persistence must be in [0, 1)")
        config["dropout_burst_persistence"] = float(dropout_burst_persistence)
    if dropout_burst_reference_step_seconds is not None:
        if dropout_burst_reference_step_seconds <= 0:
            raise ValueError("dropout_burst_reference_step_seconds must be positive")
        config["dropout_burst_reference_step_seconds"] = float(
            dropout_burst_reference_step_seconds)
    dates = list(dates or ([date] if date else []))
    if not dates:
        raise ValueError("At least one replay date is required")
    output = pathlib.Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    policy_rows = []
    dropout_rows = []
    scenario_failures = []
    cache_hashes = {}
    checkpoint_hashes = {}
    models = {}
    for training_seed in config["validation_seeds"]:
        run_name = f"validate_doe_recommended_{training_seed}"
        run_record = json.loads((campaign / "runs" / f"{run_name}.json").read_text())
        checkpoint_path = campaign / "models" / f"{run_name}.pt"
        checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
        checkpoint_hashes[str(training_seed)] = sha256(checkpoint_path)
        if run_record.get("hyperparameters") != checkpoint.get("hp"):
            raise ValueError(f"Run/checkpoint hyperparameters disagree for {run_name}")
        model = Agent(checkpoint["obs_dim"], checkpoint["actions"], checkpoint["hp"])
        model.load_state_dict(checkpoint["state_dict"])
        models[int(training_seed)] = (model, checkpoint["hp"])

    for date_index, date_value in enumerate(dates):
        for regime in REGIMES:
            try:
                reference_path = prepare(date_value, config, regime=regime)
                reference = load(reference_path)
                awp_config = {**config, "propagation_model": comparison_model}
                propagated_path = prepare(date_value, awp_config, regime=regime)
                propagated = load(propagated_path)
                metadata = json.loads(propagated_path.with_suffix(".json").read_text())
                if metadata.get("frame") != "GCRS" or metadata.get("propagation_model", "").find("AWP") != 0:
                    raise ValueError(f"AWP scenario metadata is invalid for {date_value} {regime}")
                valid = np.isfinite(propagated["states"]).all(axis=2)
                result = {
                    "date": date_value,
                    "orbit_regime": regime,
                    "objects": int(len(propagated["ids"])),
                    "agent_count": int(propagated["agents"]),
                    "target_count": int(len(propagated["ids"]) - propagated["agents"]),
                    "samples_per_object": int(len(propagated["times"])),
                    "valid_state_fraction": float(valid.mean()),
                    "fully_valid_object_count": int(valid.all(axis=0).sum()),
                    "frame": metadata["frame"],
                    "model": metadata["propagation_model"],
                    "comparison_model": comparison_model,
                    **compare(reference, propagated),
                }
                rows.append(result)
                for training_seed, (model, hp) in models.items():
                    mode_metrics = {}
                    for dynamics, scenario in (("sgp4", reference), (comparison_model, propagated)):
                        metrics, _, _ = evaluate(model, [scenario], config, hp,
                            seed=70000 + training_seed + date_index * 100003)
                        mode_metrics[dynamics] = metrics
                        policy_rows.append({"date": date_value, "orbit_regime": regime,
                            "training_seed": training_seed, "dynamics": dynamics, **metrics})
                    delta = (mode_metrics[comparison_model]["custody_continuity"]
                             - mode_metrics["sgp4"]["custody_continuity"])
                    result.setdefault("paired_policy_custody_deltas_awp_minus_sgp4", []).append(
                        {"training_seed": training_seed, "difference": float(delta)})
                    for replicate in range(dropout_replicates):
                        dropout_seed = 90000 + date_index * 100003 + replicate
                        for dynamics, dynamics_scenario in (("sgp4", reference),
                                                            (comparison_model, propagated)):
                            for rate in (0.0, float(dropout_outage_rate)):
                                metrics = evaluate_dropout(model, dynamics_scenario, config,
                                    hp, dropout_seed, rate, "burst")
                                dropout_rows.append({"date": date_value,
                                    "orbit_regime": regime,
                                    "training_seed": training_seed,
                                    "simulation_replicate": replicate,
                                    "simulation_seed": dropout_seed,
                                    "dynamics": dynamics,
                                    "outage_mode": "burst",
                                    "requested_outage_rate": rate,
                                    **metrics})
                cache_hashes[f"{date_value}|{regime}"] = {
                    "sgp4_scenario_sha256": sha256(reference_path),
                    f"{comparison_model}_scenario_sha256": sha256(propagated_path),
                }
                print(f"{date_value} {regime}: {len(models) * 2} policy evaluations complete",
                      flush=True)
            except Exception as error:
                scenario_failures.append({"date": date_value, "orbit_regime": regime,
                                          "error": f"{type(error).__name__}: {error}"})
                print(f"{date_value} {regime}: FAILED {type(error).__name__}: {error}",
                      flush=True)
    from scipy.stats import t as student_t
    for row in rows:
        deltas = np.asarray([item["difference"]
                             for item in row["paired_policy_custody_deltas_awp_minus_sgp4"]])
        half = (float(student_t.ppf(0.975, len(deltas) - 1)
                      * np.std(deltas, ddof=1) / np.sqrt(len(deltas)))
                if len(deltas) > 1 else None)
        row["paired_policy_custody_delta_mean"] = float(np.mean(deltas))
        row["paired_policy_custody_delta_ci95"] = (
            [float(np.mean(deltas) - half), float(np.mean(deltas) + half)]
            if half is not None else None)
    policy_effects = []
    for regime in REGIMES:
        date_means = []
        for row in rows:
            if row["orbit_regime"] == regime and "paired_policy_custody_deltas_awp_minus_sgp4" in row:
                date_means.append(float(np.mean([
                    item["difference"] for item in
                    row["paired_policy_custody_deltas_awp_minus_sgp4"]])))
        if date_means:
            values = np.asarray(date_means)
            half = (float(student_t.ppf(0.975, len(values) - 1)
                          * np.std(values, ddof=1) / np.sqrt(len(values)))
                    if len(values) > 1 else None)
            policy_effects.append({
                "orbit_regime": regime,
                "n_date_clusters": int(len(values)),
                "mean_custody_delta_awp_minus_sgp4": float(np.mean(values)),
                "ci95_date_clustered": ([float(np.mean(values) - half),
                                          float(np.mean(values) + half)]
                                         if half is not None else None),
            })
    dropout_effects = []
    for regime in REGIMES:
        date_impacts = {}
        by_design = {}
        for row in dropout_rows:
            if row["orbit_regime"] != regime:
                continue
            key = (row["date"], row["training_seed"],
                   row["simulation_replicate"], row["dynamics"])
            by_design.setdefault(key, {})[float(row["requested_outage_rate"])] = row
        for (date_value, training_seed, replicate, dynamics), conditions in by_design.items():
            if 0.0 not in conditions or float(dropout_outage_rate) not in conditions:
                raise ValueError(f"Unpaired dropout treatment at {date_value} {regime} {dynamics}")
            impact = (float(conditions[float(dropout_outage_rate)]["custody_continuity"])
                      - float(conditions[0.0]["custody_continuity"]))
            date_impacts.setdefault(date_value, {"sgp4": [], comparison_model: []})[dynamics].append(impact)
        dynamics_summary = {}
        for dynamics in ("sgp4", comparison_model):
            means = np.asarray([float(np.mean(group[dynamics])) for group in
                date_impacts.values() if group[dynamics]])
            half = (float(student_t.ppf(0.975, len(means) - 1)
                          * np.std(means, ddof=1) / np.sqrt(len(means)))
                    if len(means) > 1 else None)
            dynamics_summary[dynamics] = {
                "n_date_clusters": int(len(means)),
                "mean_custody_change_at_requested_burst_rate": float(np.mean(means)) if len(means) else None,
                "ci95_date_clustered": ([float(np.mean(means) - half),
                    float(np.mean(means) + half)] if half is not None else None),
            }
        interactions = np.asarray([float(np.mean(group[comparison_model])
                                          - np.mean(group["sgp4"]))
                                   for group in date_impacts.values()
                                   if group[comparison_model] and group["sgp4"]])
        half = (float(student_t.ppf(0.975, len(interactions) - 1)
                      * np.std(interactions, ddof=1) / np.sqrt(len(interactions)))
                if len(interactions) > 1 else None)
        rate_label = f"{100 * dropout_outage_rate:g}pct"
        dropout_effects.append({"orbit_regime": regime,
            f"zero_to_{rate_label}_burst_effect_by_dynamics": dynamics_summary,
            "awp_minus_sgp4_dropout_effect_interaction": {
                "n_date_clusters": int(len(interactions)),
                "mean": float(np.mean(interactions)) if len(interactions) else None,
                "ci95_date_clustered": ([float(np.mean(interactions) - half),
                    float(np.mean(interactions) + half)] if half is not None else None),
            }})
    awp_root = ROOT / "vendor/AWP"
    revision = subprocess.run(["git", "-C", str(awp_root), "rev-parse", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()
    expected_scenarios = len(dates) * len(REGIMES)
    summary = {
        "status": "completed" if len(rows) == expected_scenarios and not scenario_failures else "partial",
        "dates": dates,
        "episode_duration_minutes": 60,
        "sample_step_seconds": step_seconds,
        "source_campaign": str(campaign),
        "source_campaign_config_sha256": sha256(config_path),
        "validation_training_seeds": list(map(int, config["validation_seeds"])),
        "validation_checkpoint_sha256": checkpoint_hashes,
        "config": config,
        "awp_revision": revision,
        "comparison_model": comparison_model,
        "dropout_outage_rate": float(dropout_outage_rate),
        "comparison_interpretation": "AWP-vs-SGP4 model separation after TEME-to-GCRS transformation; neither is independent orbit truth.",
        "expected_scenarios": expected_scenarios,
        "completed_scenarios": len(rows),
        "scenario_failures": scenario_failures,
        "regimes": rows,
        "policy_evaluation_design_rows": len(policy_rows),
        "dropout_evaluation_design_rows": len(dropout_rows),
        "dropout_replicates_per_checkpoint_date_regime": dropout_replicates,
        "policy_custody_effects_by_regime": policy_effects,
        "dropout_custody_effects_by_regime": dropout_effects,
        "scenario_cache_sha256": cache_hashes,
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n")
    with (output / "regime_comparison.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    with (output / "policy_evaluation.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(policy_rows[0]))
        writer.writeheader()
        writer.writerows(policy_rows)
    with (output / "dropout_evaluation.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(dropout_rows[0]))
        writer.writeheader()
        writer.writerows(dropout_rows)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default="2026-10-01T00:00:00Z")
    cadence = parser.add_mutually_exclusive_group()
    cadence.add_argument("--quarterly", action="store_true",
                         help="run 17 quarterly dates from 2022-10 through 2026-10")
    cadence.add_argument("--monthly", action="store_true",
                         help="run 48 monthly dates from 2022-10 through 2026-09")
    parser.add_argument("--step-seconds", type=int, default=60)
    parser.add_argument("--dropout-replicates", type=int, default=5)
    parser.add_argument("--comparison-model", choices=("awp_j2", "awp_j2_sun_moon"),
                        default="awp_j2", help="AWP force model compared with SGP4")
    parser.add_argument("--dropout-burst-persistence", type=float,
                        help="override burst persistence at its reference cadence")
    parser.add_argument("--dropout-burst-reference-step-seconds", type=float,
                        help="cadence at which the supplied persistence was measured")
    parser.add_argument("--dropout-outage-rate", type=float, default=0.2,
                        help="paired burst-loss rate; defaults to 0.2")
    parser.add_argument("--campaign", default=str(ROOT / "outputs/all-orbits-paper-exact-active-hosts"))
    parser.add_argument("--output")
    args = parser.parse_args()
    if args.quarterly:
        from godsat.dropout import quarterly_dates
        dates = quarterly_dates()
        default_output = ROOT / ("outputs/awp-policy-quarterly-validation-2022-2026"
            if args.comparison_model == "awp_j2" else "outputs/awp-sun-moon-quarterly-validation-2022-2026")
    elif args.monthly:
        from godsat.dropout import monthly_dates
        dates = monthly_dates()
        default_output = ROOT / ("outputs/awp-policy-monthly-validation-2022-2026"
            if args.comparison_model == "awp_j2" else "outputs/awp-sun-moon-monthly-validation-2022-2026")
    else:
        dates = [args.date]
        default_output = ROOT / ("outputs/awp-scenario-validation-2026-10-01"
            if args.comparison_model == "awp_j2" else "outputs/awp-sun-moon-scenario-validation-2026-10-01")
    output = pathlib.Path(args.output) if args.output else default_output
    result = run(args.date, output, args.step_seconds, dates=dates,
                 campaign=pathlib.Path(args.campaign),
                 dropout_replicates=args.dropout_replicates,
                 comparison_model=args.comparison_model,
                 dropout_burst_persistence=args.dropout_burst_persistence,
                 dropout_outage_rate=args.dropout_outage_rate,
                 dropout_burst_reference_step_seconds=args.dropout_burst_reference_step_seconds)
    print(json.dumps({"status": result["status"], "dates": result["dates"],
                      "completed_scenarios": result["completed_scenarios"],
                      "scenario_failures": result["scenario_failures"],
                      "awp_revision": result["awp_revision"],
                      "comparison_model": result["comparison_model"],
                      "dropout_outage_rate": result["dropout_outage_rate"],
                      "policy_evaluation_design_rows": result["policy_evaluation_design_rows"],
                      "policy_custody_effects_by_regime": result["policy_custody_effects_by_regime"],
                      "dropout_evaluation_design_rows": result["dropout_evaluation_design_rows"],
                      "dropout_custody_effects_by_regime": result["dropout_custody_effects_by_regime"]}, indent=2))


if __name__ == "__main__":
    main()
