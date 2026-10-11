"""Independently audit monthly or quarterly AWP/SGP4 policy and dropout results."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import pathlib
import subprocess
import sys

import numpy as np
from scipy.stats import t as student_t

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from godsat.dropout import monthly_dates, quarterly_dates
from godsat.scenario import cache_key

REGIMES = ("leo", "meo", "geo", "heo")


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_csv(path):
    with pathlib.Path(path).open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def assert_close(actual, expected, label, failures, tolerance=1e-10):
    if expected is None or not math.isclose(float(actual), float(expected),
                                             rel_tol=tolerance, abs_tol=tolerance):
        failures.append(f"{label} does not reproduce")


def mean_and_ci(values):
    values = np.asarray(values, dtype=float)
    if len(values) < 2:
        return float(np.mean(values)), None
    half = float(student_t.ppf(0.975, len(values) - 1)
                 * np.std(values, ddof=1) / np.sqrt(len(values)))
    return float(np.mean(values)), [float(np.mean(values) - half),
                                    float(np.mean(values) + half)]


def dropout_design(summary):
    """Resolve the paired simulated outage treatment from a run summary."""
    outage_rate = float(summary.get("dropout_outage_rate", 0.2))
    if not 0.0 < outage_rate <= 1.0:
        raise ValueError("dropout_outage_rate must be in (0, 1]")
    return outage_rate, f"{100 * outage_rate:g}pct"


def audit(output_dir, dates=None):
    output_dir = pathlib.Path(output_dir).resolve()
    summary_path = output_dir / "summary.json"
    summary = json.loads(summary_path.read_text())
    comparison_model = summary.get("comparison_model", "awp_j2")
    if comparison_model not in {"awp_j2", "awp_j2_sun_moon"}:
        raise ValueError(f"Unsupported comparison model in summary: {comparison_model}")
    policy_rows = read_csv(output_dir / "policy_evaluation.csv")
    dropout_rows = read_csv(output_dir / "dropout_evaluation.csv")
    failures = []

    dates = list(dates or quarterly_dates())
    seeds = list(map(int, summary.get("validation_training_seeds", [])))
    replicates = int(summary.get("dropout_replicates_per_checkpoint_date_regime", 0))
    outage_rate, rate_label = dropout_design(summary)
    if summary.get("status") != "completed":
        failures.append("source summary is not completed")
    if summary.get("dates") != dates:
        failures.append("date grid differs from the requested registered date grid")
    if summary.get("scenario_failures"):
        failures.append("source summary contains scenario failures")
    expected_scenarios = {(date, regime) for date in dates for regime in REGIMES}
    scenario_keys = {(row.get("date"), row.get("orbit_regime"))
                     for row in summary.get("regimes", [])}
    if scenario_keys != expected_scenarios or len(summary.get("regimes", [])) != len(expected_scenarios):
        failures.append("scenario date/regime grid is incomplete or duplicated")
    expected_policy = {(date, regime, seed, dynamics)
        for date, regime in expected_scenarios for seed in seeds
        for dynamics in ("sgp4", comparison_model)}
    observed_policy = {(row.get("date"), row.get("orbit_regime"),
                        int(row["training_seed"]), row.get("dynamics"))
                       for row in policy_rows}
    if observed_policy != expected_policy or len(policy_rows) != len(expected_policy):
        failures.append("policy evaluation rows are incomplete, duplicated, or out of design")
    expected_dropout = {(date, regime, seed, replicate, dynamics, rate)
        for date, regime in expected_scenarios for seed in seeds
        for replicate in range(replicates) for dynamics in ("sgp4", comparison_model)
        for rate in (0.0, outage_rate)}
    observed_dropout = {(row.get("date"), row.get("orbit_regime"),
        int(row["training_seed"]), int(row["simulation_replicate"]),
        row.get("dynamics"), float(row["requested_outage_rate"]))
        for row in dropout_rows}
    if observed_dropout != expected_dropout or len(dropout_rows) != len(expected_dropout):
        failures.append("dropout rows are incomplete, duplicated, or out of design")

    campaign = pathlib.Path(summary["source_campaign"])
    config_path = campaign / "config.json"
    if sha256(config_path) != summary.get("source_campaign_config_sha256"):
        failures.append("campaign config hash mismatch")
    for seed, expected_hash in summary.get("validation_checkpoint_sha256", {}).items():
        path = campaign / "models" / f"validate_doe_recommended_{seed}.pt"
        if sha256(path) != expected_hash:
            failures.append(f"validation checkpoint hash mismatch: seed {seed}")

    cache_checks = 0
    config = summary["config"]
    for date, regime in expected_scenarios:
        key = date + "|" + regime
        for model, hash_key in (("sgp4", "sgp4_scenario_sha256"),
                                (comparison_model, f"{comparison_model}_scenario_sha256")):
            scenario_config = {**config, "propagation_model": model}
            path = ROOT / "data/scenarios" / (cache_key(date, scenario_config, regime) + ".npz")
            metadata_path = path.with_suffix(".json")
            if not path.is_file() or not metadata_path.is_file():
                failures.append(f"scenario cache missing: {date} {regime} {model}")
                continue
            if sha256(path) != summary.get("scenario_cache_sha256", {}).get(key, {}).get(hash_key):
                expected_hash = summary.get("scenario_cache_sha256", {}).get(key, {}).get(hash_key)
                if model == "awp_j2" and expected_hash is None:
                    expected_hash = summary.get("scenario_cache_sha256", {}).get(key, {}).get("awp_scenario_sha256")
                if sha256(path) != expected_hash:
                    failures.append(f"scenario cache hash mismatch: {date} {regime} {model}")
            metadata = json.loads(metadata_path.read_text())
            expected_frame = "GCRS" if model.startswith("awp_") else "TEME"
            if metadata.get("frame") != expected_frame:
                failures.append(f"scenario frame mismatch: {date} {regime} {model}")
            if metadata.get("date") != date or metadata.get("orbit_regime") != regime:
                failures.append(f"scenario metadata date/regime mismatch: {date} {regime} {model}")
            # Earlier cache metadata omitted the regime even though the cache
            # filename included it. Accept that legacy key only alongside exact
            # date/regime metadata and the independently checked file hash.
            allowed_config_keys = {cache_key(date, scenario_config),
                                   cache_key(date, scenario_config, regime)}
            if metadata.get("config_key") not in allowed_config_keys:
                failures.append(f"scenario metadata config key mismatch: {date} {regime} {model}")
            model_description = metadata.get("propagation_model", "")
            if model.startswith("awp_") and not model_description.startswith("AWP Spacecraft"):
                failures.append(f"scenario force-model metadata mismatch: {date} {regime} {model}")
            if model == "awp_j2_sun_moon" and "solar/lunar point-mass gravity" not in model_description:
                failures.append(f"scenario solar/lunar-force metadata missing: {date} {regime}")
            if model == "sgp4" and not model_description.startswith("SGP4"):
                failures.append(f"scenario SGP4 metadata mismatch: {date} {regime}")
            cache_checks += 1

    awp_revision = subprocess.run(["git", "-C", str(ROOT / "vendor/AWP"),
        "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    if awp_revision != summary.get("awp_revision"):
        failures.append("vendored AWP revision mismatch")

    # Recompute the five-checkpoint paired policy effects and date-clustered CIs.
    policy_index = {(row["date"], row["orbit_regime"], int(row["training_seed"]),
                     row["dynamics"]): row for row in policy_rows}
    policy_effects = []
    for regime in REGIMES:
        date_means = []
        for date in dates:
            deltas = [float(policy_index[(date, regime, seed, comparison_model)]["custody_continuity"])
                      - float(policy_index[(date, regime, seed, "sgp4")]["custody_continuity"])
                      for seed in seeds]
            date_means.append(float(np.mean(deltas)))
        mean, ci = mean_and_ci(date_means)
        saved = next((row for row in summary["policy_custody_effects_by_regime"]
                      if row["orbit_regime"] == regime), {})
        assert_close(mean, saved.get("mean_custody_delta_awp_minus_sgp4"),
                     f"policy effect mean {regime}", failures)
        if ci is None or saved.get("ci95_date_clustered") is None:
            if len(dates) >= 2:
                failures.append(f"policy date-cluster interval missing: {regime}")
        else:
            for index, value in enumerate(ci):
                assert_close(value, saved["ci95_date_clustered"][index],
                             f"policy interval {regime} endpoint {index}", failures)
        policy_effects.append({"orbit_regime": regime,
            "mean_awp_minus_sgp4_custody": mean, "ci95_date_clustered": ci})

    # Recompute paired zero-to-observed-rate burst effects and model interaction.
    dropout_index = {}
    for row in dropout_rows:
        key = (row["date"], row["orbit_regime"], int(row["training_seed"]),
               int(row["simulation_replicate"]), row["dynamics"])
        dropout_index.setdefault(key, {})[float(row["requested_outage_rate"])] = row
    dropout_effects = []
    for regime in REGIMES:
        by_dynamics = {"sgp4": {}, comparison_model: {}}
        for date in dates:
            for dynamics in by_dynamics:
                impacts = []
                for seed in seeds:
                    for replicate in range(replicates):
                        pair = dropout_index[(date, regime, seed, replicate, dynamics)]
                        if 0.0 not in pair or outage_rate not in pair:
                            failures.append(f"unpaired dropout treatment: {date} {regime} {dynamics}")
                            continue
                        if (float(pair[0.0]["dropout_misses"]) != 0
                                or float(pair[0.0]["dropout_rate_observed"]) != 0):
                            failures.append(f"nonzero loss in dropout control: {date} {regime} {dynamics}")
                        impacts.append(float(pair[outage_rate]["custody_continuity"])
                                       - float(pair[0.0]["custody_continuity"]))
                by_dynamics[dynamics][date] = float(np.mean(impacts))
        dynamics_results = {}
        for dynamics in by_dynamics:
            mean, ci = mean_and_ci(list(by_dynamics[dynamics].values()))
            dynamics_results[dynamics] = {"mean": mean, "ci95": ci}
        interaction_values = [by_dynamics[comparison_model][date] - by_dynamics["sgp4"][date]
                              for date in dates]
        interaction_mean, interaction_ci = mean_and_ci(interaction_values)
        saved = next((row for row in summary["dropout_custody_effects_by_regime"]
                      if row["orbit_regime"] == regime), {})
        for dynamics in by_dynamics:
            saved_item = saved.get(f"zero_to_{rate_label}_burst_effect_by_dynamics", {}).get(dynamics, {})
            assert_close(dynamics_results[dynamics]["mean"],
                saved_item.get("mean_custody_change_at_requested_burst_rate"),
                f"dropout effect mean {regime} {dynamics}", failures)
            if saved_item.get("ci95_date_clustered") is None or dynamics_results[dynamics]["ci95"] is None:
                if len(dates) >= 2:
                    failures.append(f"dropout date-cluster interval missing: {regime} {dynamics}")
            else:
                for index, value in enumerate(dynamics_results[dynamics]["ci95"]):
                    assert_close(value, saved_item["ci95_date_clustered"][index],
                        f"dropout interval {regime} {dynamics} endpoint {index}", failures)
        interaction = saved.get("awp_minus_sgp4_dropout_effect_interaction", {})
        assert_close(interaction_mean, interaction.get("mean"),
                     f"dropout interaction mean {regime}", failures)
        if interaction.get("ci95_date_clustered") is None or interaction_ci is None:
            if len(dates) >= 2:
                failures.append(f"dropout interaction interval missing: {regime}")
        else:
            for index, value in enumerate(interaction_ci):
                assert_close(value, interaction["ci95_date_clustered"][index],
                    f"dropout interaction interval {regime} endpoint {index}", failures)
        dropout_effects.append({"orbit_regime": regime,
            "custody_change": dynamics_results,
            "awp_minus_sgp4_interaction": {"mean": interaction_mean, "ci95": interaction_ci}})

    result = {
        "status": "completed_valid" if not failures else "failed",
        "source_summary_sha256": sha256(summary_path),
        "policy_rows": len(policy_rows),
        "dropout_rows": len(dropout_rows),
        "scenario_cache_hashes_checked": cache_checks,
        "checkpoint_hashes_checked": len(summary.get("validation_checkpoint_sha256", {})),
        "uncertainty_note": ("A single date/regime has no date-clustered interval; results are descriptive."
                             if len(dates) < 2 else None),
        "policy_effects_recomputed": policy_effects,
        "dropout_effects_recomputed": dropout_effects,
        "failures": failures,
    }
    (output_dir / "independent_audit.json").write_text(
        json.dumps(result, indent=2, allow_nan=False) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    cadence = parser.add_mutually_exclusive_group()
    cadence.add_argument("--monthly", action="store_true",
                         help="audit the registered 48 monthly dates")
    cadence.add_argument("--quarterly", action="store_true",
                         help="audit the registered 17 quarterly dates (default)")
    parser.add_argument("--output")
    args = parser.parse_args()
    if args.monthly:
        dates = monthly_dates()
        default_output = ROOT / "outputs/awp-policy-monthly-validation-2022-2026"
    else:
        dates = quarterly_dates()
        default_output = ROOT / "outputs/awp-policy-quarterly-validation-2022-2026"
    result = audit(pathlib.Path(args.output or default_output), dates=dates)
    print(json.dumps({key: result[key] for key in
        ("status", "policy_rows", "dropout_rows", "scenario_cache_hashes_checked",
         "checkpoint_hashes_checked", "failures")}, indent=2))
    if result["status"] != "completed_valid":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
