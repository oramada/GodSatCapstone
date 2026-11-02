"""Compare paired simulated dropout effects across all-catalog and active targets.

The source studies share monthly epochs and sensor hosts, but differ in target
cohort. This script estimates a descriptive target-cohort-by-outage interaction;
it does not turn simulated dropout into an observed sensor failure rate.
"""
from __future__ import annotations

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))


import argparse
import csv
import datetime as dt
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from scipy.stats import t as student_t

ROOT = Path(__file__).resolve().parents[2]
REGIMES = ("leo", "meo", "geo", "heo")
COHORTS = {
    "all_catalog": "full-catalog-tasking-monthly-2022-2026",
    "current_active_payload": "current-active-payload-tasking-monthly-2022-2026",
}
METRICS = ("custody_continuity", "observable_custody")
BOOTSTRAP_REPLICATES = 20_000
BOOTSTRAP_SEED = 20261011


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def mean_ci(values: np.ndarray) -> tuple[float, list[float]]:
    if values.ndim != 1 or len(values) < 2 or not np.isfinite(values).all():
        raise ValueError("date-cluster effects must be a finite one-dimensional sample")
    mean = float(values.mean())
    half = float(student_t.ppf(.975, len(values) - 1) * values.std(ddof=1) / math.sqrt(len(values)))
    return mean, [mean - half, mean + half]


def moving_block_ci(values: np.ndarray, block_length: int, replicates: int,
                    seed: int) -> list[float]:
    """Non-circular moving-block bootstrap interval for monthly date effects."""
    values = np.asarray(values, dtype=float)
    n = len(values)
    if block_length < 1 or block_length > n or replicates < 100:
        raise ValueError("invalid block-bootstrap design")
    blocks = np.asarray([values[i:i + block_length]
                         for i in range(n - block_length + 1)])
    rng = np.random.default_rng(seed + block_length)
    number_blocks = math.ceil(n / block_length)
    means = np.empty(replicates, dtype=float)
    for i in range(replicates):
        sampled = blocks[rng.integers(0, len(blocks), size=number_blocks)].reshape(-1)[:n]
        means[i] = sampled.mean()
    low, high = np.quantile(means, [.025, .975])
    return [float(low), float(high)]


def load_cohort(name: str, folder: Path) -> tuple[dict, dict, dict, dict]:
    summary_path = folder / "summary.json"
    audit_path = folder / "independent_audit.json"
    response_path = folder / "responses.csv"
    summary = json.loads(summary_path.read_text())
    audit = json.loads(audit_path.read_text())
    if summary.get("status") != "completed" or audit.get("status") != "passed_structural_and_statistical":
        raise ValueError(f"{name}: source tasking study is not independently audited")
    expected_cohort = "all" if name == "all_catalog" else "current_active_payload"
    if audit.get("target_cohort") != expected_cohort:
        raise ValueError(f"{name}: target cohort does not match its label")
    if audit.get("response_rows_checked") != 384 or audit.get("dates_checked") != 48:
        raise ValueError(f"{name}: unexpected audited study dimensions")
    dates = summary.get("dates", [])
    if len(dates) != 48 or len(set(dates)) != 48:
        raise ValueError(f"{name}: expected 48 unique monthly dates")
    if summary.get("regimes") != list(REGIMES) or summary.get("outage_rates") != [0.0, 0.2]:
        raise ValueError(f"{name}: unexpected tasking design")
    indexed = {}
    with response_path.open(newline="") as stream:
        for row in csv.DictReader(stream):
            key = (row["date"], row["orbit_regime_sensor_hosts"], float(row["requested_outage_rate"]))
            if key in indexed:
                raise ValueError(f"{name}: duplicate response {key}")
            indexed[key] = row
    expected = {(date, regime, rate) for date in dates for regime in REGIMES for rate in (0.0, 0.2)}
    if set(indexed) != expected:
        raise ValueError(f"{name}: response rows do not cover the complete paired design")
    for key, row in indexed.items():
        if row.get("outage_mode") != "burst":
            raise ValueError(f"{name}: response row is not a burst-outage treatment at {key}")
        for metric in (*METRICS, "observed_dropout_rate"):
            value = float(row[metric])
            if not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"{name}: invalid {metric} at {key}")
        if float(row["requested_outage_rate"]) == 0 and int(row["dropout_misses"]) != 0:
            raise ValueError(f"{name}: zero-outage row contains injected misses at {key}")
    hashes = {str(path): sha256(path) for path in (summary_path, audit_path, response_path)}
    return summary, audit, indexed, hashes


def verify_shared_hosts(name: str, folder: Path, dates: list[str],
                        other_folder: Path) -> int:
    checked = 0
    for date in dates:
        for regime in REGIMES:
            path = folder / "cells" / date[:10] / f"{regime}.json"
            other_path = other_folder / "cells" / date[:10] / f"{regime}.json"
            cell = json.loads(path.read_text())
            other = json.loads(other_path.read_text())
            hosts = cell["rows"][0].get("sensor_host_ids")
            other_hosts = other["rows"][0].get("sensor_host_ids")
            if (not hosts or len(hosts) != 6 or len(set(hosts)) != 6
                    or hosts != other_hosts):
                raise ValueError(f"Sensor-host IDs differ for {date} {regime} in {name}")
            if any(row.get("sensor_host_ids") != hosts for row in cell["rows"] + other["rows"]):
                raise ValueError(f"Paired tasking cell changed host IDs for {date} {regime}")
            checked += 1
    return checked


def summarize_episode_mechanism(index: dict, dates: list[str], regime: str) -> dict:
    baseline = [index[(date, regime, 0.0)] for date in dates]
    outage = [index[(date, regime, 0.2)] for date in dates]
    for before, after in zip(baseline, outage):
        if before["catalog_objects_in_episode"] != after["catalog_objects_in_episode"]:
            raise ValueError("Paired outage rows changed the episode target count")
    total_trials = sum(int(row["dropout_trials"]) for row in outage)
    total_misses = sum(int(row["dropout_misses"]) for row in outage)
    if total_trials <= 0 or total_misses > total_trials:
        raise ValueError("Invalid assigned-observation dropout counts")
    return {
        "episode_count": len(dates),
        "target_count_min_median_max": {
            "minimum": min(int(row["catalog_objects_in_episode"]) for row in baseline),
            "median": float(np.median([int(row["catalog_objects_in_episode"]) for row in baseline])),
            "maximum": max(int(row["catalog_objects_in_episode"]) for row in baseline),
        },
        "mean_geometrically_observable_object_steps": float(np.mean([
            int(row["target_observable_step_count"]) for row in outage])),
        "mean_assigned_observations_no_added_outage": float(np.mean([
            int(row["sensor_actions"]) for row in baseline])),
        "mean_assigned_observations_20pct_burst": float(np.mean([
            int(row["sensor_actions"]) for row in outage])),
        "mean_injected_misses_per_episode": float(np.mean([
            int(row["dropout_misses"]) for row in outage])),
        "pooled_realized_dropout_percent_of_assigned_observations": 100 * total_misses / total_trials,
        "assigned_observations_as_percent_of_geometric_opportunities": (
            100 * total_trials / sum(int(row["target_observable_step_count"]) for row in outage)),
    }


def compare(root: Path, output: Path) -> dict:
    folders = {name: root / "outputs" / folder for name, folder in COHORTS.items()}
    loaded = {name: load_cohort(name, folder) for name, folder in folders.items()}
    summaries = {name: item[0] for name, item in loaded.items()}
    if summaries["all_catalog"]["dates"] != summaries["current_active_payload"]["dates"]:
        raise ValueError("Target cohorts do not use identical monthly dates")
    if summaries["all_catalog"]["config"] != summaries["current_active_payload"]["config"]:
        raise ValueError("Target cohorts do not use the same sensor/tasking configuration")
    dates = summaries["all_catalog"]["dates"]
    shared_cells = verify_shared_hosts("all_catalog", folders["all_catalog"], dates,
                                       folders["current_active_payload"])
    indices = {name: item[2] for name, item in loaded.items()}
    target_denominators = {}
    for cohort, index in indices.items():
        target_denominators[cohort] = {}
        for regime in REGIMES:
            counts = np.asarray([int(index[(date, regime, 0.0)]["catalog_objects_in_episode"])
                                 for date in dates], dtype=int)
            target_denominators[cohort][regime] = {
                "minimum": int(counts.min()),
                "median": float(np.median(counts)),
                "maximum": int(counts.max()),
            }
    results = []
    mechanism = {cohort: {regime: summarize_episode_mechanism(
        indices[cohort], dates, regime) for regime in REGIMES} for cohort in COHORTS}
    for regime in REGIMES:
        for metric in METRICS:
            effects = {}
            for cohort, index in indices.items():
                effects[cohort] = np.asarray([
                    float(index[(date, regime, 0.2)][metric])
                    - float(index[(date, regime, 0.0)][metric])
                    for date in dates], dtype=float)
            interaction = effects["all_catalog"] - effects["current_active_payload"]
            mean, ci95 = mean_ci(interaction)
            results.append({
                "orbit_regime": regime,
                "metric": metric,
                "unit": "percentage_points",
                "date_clusters": len(dates),
                "mean_dropout_effect": {
                    cohort: {
                        "mean": float(values.mean() * 100),
                        "ci95_date_clustered": [float(x * 100) for x in mean_ci(values)[1]],
                    } for cohort, values in effects.items()
                },
                "interaction_all_catalog_minus_active_payload": {
                    "mean": float(mean * 100),
                    "ci95_date_clustered": [float(x * 100) for x in ci95],
                    "moving_block_bootstrap_ci95": {
                        str(block): [float(x * 100) for x in moving_block_ci(
                            interaction, block, BOOTSTRAP_REPLICATES, BOOTSTRAP_SEED)]
                        for block in (3, 6, 12)
                    },
                },
                "date_effects": [
                    {"date": date,
                     "all_catalog": float(effects["all_catalog"][i] * 100),
                     "current_active_payload": float(effects["current_active_payload"][i] * 100),
                     "interaction_all_catalog_minus_active_payload": float(interaction[i] * 100)}
                    for i, date in enumerate(dates)
                ],
            })
    result = {
        "status": "completed",
        "estimand": "difference in paired 20%-minus-0% simulated burst-dropout effect between two target populations",
        "dates": dates,
        "regimes": list(REGIMES),
        "target_cohorts": {
            "all_catalog": "all fresh, valid historical catalog targets; includes payloads, rocket bodies, and debris",
            "current_active_payload": "IDs in the current active-GP/SATCAT no-decay payload snapshot, backcast through history; not proof of historical operation",
        },
        "shared_sensor_hosts_verified_date_regime_cells": shared_cells,
        "metric_denominators": {
            "custody_continuity": "all valid cohort targets in the simulated episode",
            "observable_custody": "cohort targets geometrically observable during the episode",
        },
        "target_denominators_by_cohort_and_regime": target_denominators,
        "tasking_mechanism_by_cohort_and_regime": mechanism,
        "tasking_capacity": {
            "configured_sensor_hosts": int(summaries["all_catalog"]["config"]["agents"]),
            "episode_steps": int(summaries["all_catalog"]["config"]["duration_minutes"] * 60
                                   / summaries["all_catalog"]["config"]["step_seconds"]),
            "maximum_assigned_observations_per_episode": int(
                summaries["all_catalog"]["config"]["agents"]
                * summaries["all_catalog"]["config"]["duration_minutes"] * 60
                / summaries["all_catalog"]["config"]["step_seconds"]),
        },
        "method": {
            "outage_mode": "burst",
            "requested_outage_rates": [0.0, 0.2],
            "date_cluster_interval": "Student-t interval over 48 monthly date-level paired effects",
            "moving_block_bootstrap": {"replicates": BOOTSTRAP_REPLICATES,
                "seed": BOOTSTRAP_SEED, "block_lengths_dates": [3, 6, 12],
                "sampling": "non-circular consecutive monthly blocks"},
        },
        "interpretation_limits": [
            "Both studies are synthetic greedy tasking references, not the learned paper policy or original GoDSAT implementation.",
            "The intervention injects simulated burst losses; it is not calibrated to natural sensor failures.",
            "Target-cohort metrics use different denominators, so compare absolute dropout effects and their interaction as scenario-specific outputs, not intrinsic sensor reliability.",
            "The current-active-payload cohort is a present-day catalog snapshot backcast through historical elements.",
            "Monthly date intervals and block bootstrap quantify temporal sensitivity but do not add independent hardware observations.",
            "Intervals are descriptive and are not adjusted for the eight regime/metric comparisons.",
        ],
        "source_audits": {name: loaded[name][1]["status"] for name in COHORTS},
        "source_sha256": {name: loaded[name][3] for name in COHORTS},
        "results": results,
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    (output / "report.md").write_text(render_report(result))
    return result


def render_report(result: dict) -> str:
    lines = [
        "# Monthly full-catalog versus active-payload dropout sensitivity",
        "",
        "This compares the change in modeled custody under 20% burst loss versus no added loss across two target populations, holding the six sensor hosts, dates, and tasking configuration matched. Both runs use a synthetic greedy tasking reference. The result is a target-cohort sensitivity, not a real sensor failure rate or a comparison of learned policies.",
        "",
        "Effects and confidence intervals are percentage points (pp). Each cohort’s metric uses its own target denominator. The interaction is (all-catalog 20%-minus-0% effect) minus (current-active-payload 20%-minus-0% effect). The 95% interval clusters by 48 monthly dates; the block-bootstrap columns test sensitivity to temporal correlation.",
        "",
        "| Regime | Metric | All-catalog effect (95% date CI) | Active-payload effect (95% date CI) | All minus active interaction (95% date CI) | 3-month block CI | 6-month block CI | 12-month block CI |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for item in result["results"]:
        cohort = item["mean_dropout_effect"]
        interaction = item["interaction_all_catalog_minus_active_payload"]
        def fmt(span):
            return f"{span[0]:+.3f} to {span[1]:+.3f}"
        lines.append(
            f"| {item['orbit_regime'].upper()} | {item['metric']} | "
            f"{cohort['all_catalog']['mean']:+.3f} ({fmt(cohort['all_catalog']['ci95_date_clustered'])}) | "
            f"{cohort['current_active_payload']['mean']:+.3f} ({fmt(cohort['current_active_payload']['ci95_date_clustered'])}) | "
            f"{interaction['mean']:+.3f} ({fmt(interaction['ci95_date_clustered'])}) | "
            f"{fmt(interaction['moving_block_bootstrap_ci95']['3'])} | "
            f"{fmt(interaction['moving_block_bootstrap_ci95']['6'])} | "
            f"{fmt(interaction['moving_block_bootstrap_ci95']['12'])} |"
        )
    lines += [
        "",
        "## Target counts per one-hour episode",
        "",
        "| Regime | All-catalog min / median / max | Active-payload min / median / max |",
        "|---|---:|---:|",
    ]
    denominators = result["target_denominators_by_cohort_and_regime"]
    for regime in REGIMES:
        def fmt_counts(row):
            return f"{row['minimum']:,} / {row['median']:,.1f} / {row['maximum']:,}"
        lines.append(f"| {regime.upper()} | {fmt_counts(denominators['all_catalog'][regime])} | {fmt_counts(denominators['current_active_payload'][regime])} |")
    lines += [
        "",
        f"All {result['shared_sensor_hosts_verified_date_regime_cells']} date/regime cells use the same six sensor-host IDs across cohorts. Inputs are the independently audited monthly tasking runs; their response files, summaries, and audits are checksum-recorded in `summary.json`.",
        "",
        "## Assignment and opportunity counts",
        "",
        f"The simulator allows at most {result['tasking_capacity']['maximum_assigned_observations_per_episode']} assigned observations per one-hour episode ({result['tasking_capacity']['configured_sensor_hosts']} hosts × {result['tasking_capacity']['episode_steps']} steps). `Observable object-steps` counts target-time opportunities with at least one geometric sensor view; many opportunities cannot be assigned within this action budget.",
        "",
        "| Regime | Target cohort | Mean observable object-steps | Mean assigned observations | Mean injected misses | Realized dropout among assignments | Assigned observations / geometric opportunities |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for regime in REGIMES:
        for cohort in COHORTS:
            row = result["tasking_mechanism_by_cohort_and_regime"][cohort][regime]
            lines.append(
                f"| {regime.upper()} | {cohort} | {row['mean_geometrically_observable_object_steps']:,.0f} | "
                f"{row['mean_assigned_observations_20pct_burst']:.1f} | "
                f"{row['mean_injected_misses_per_episode']:.1f} | "
                f"{row['pooled_realized_dropout_percent_of_assigned_observations']:.2f}% | "
                f"{row['assigned_observations_as_percent_of_geometric_opportunities']:.3f}% |"
            )
    lines += [
        "",
        "These results quantify the synthetic tasking model’s sensitivity to target-population definition. They do not estimate real dropout effectiveness. The all-catalog and active-payload values also have different target denominators, and the active cohort is selected from a current snapshot and backcast historically.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path,
                        default=ROOT / "outputs/catalog-dropout-cohort-comparison-2022-2026")
    args = parser.parse_args()
    root = args.root.resolve()
    output = args.output if args.output.is_absolute() else root / args.output
    result = compare(root, output.resolve())
    print(json.dumps({"status": result["status"], "date_regime_cells": result[
        "shared_sensor_hosts_verified_date_regime_cells"], "results": len(result["results"]),
        "output": str(output.resolve())}, indent=2))


if __name__ == "__main__":
    main()
