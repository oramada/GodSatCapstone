#!/usr/bin/env python3
"""Estimate one-minute CASSIOPE attitude-solution dropout statistics from 1 Hz data."""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/attitude/cassiope_epop"


def analyze(data: Path = DATA, bootstrap_replicates: int = 2000) -> dict:
    manifest = json.loads((data / "manifest.json").read_text())
    audit = json.loads((data / "independent_audit.json").read_text())
    if bootstrap_replicates < 1:
        raise ValueError("bootstrap_replicates must be positive")
    if audit.get("status") != "passed_structural_and_statistical":
        raise ValueError("Independent quaternion data audit has not passed")
    statuses = manifest.get("per_day_status", {})
    files = sorted((data / "processed").glob("*/*.parquet"))
    daily: list[tuple[date, np.ndarray]] = []
    source_days = {date.fromisoformat(day) for day in audit.get("validated_dates", [])}
    if not source_days:
        source_days = {date.fromisoformat(day) for day, status in statuses.items()
                       if status in {"validated", "already_validated"}}
    failures = []
    for path in files:
        day = date.fromisoformat(path.stem)
        if day not in source_days:
            continue
        table = pq.read_table(path, columns=["q1", "q2", "q3", "q4"])
        if table.num_rows != 86_400:
            failures.append({"date": day.isoformat(), "reason": f"{table.num_rows} rows"})
            continue
        q = np.column_stack([table[f"q{i}"].to_numpy(zero_copy_only=False) for i in range(1, 5)])
        dropout_60s = ~np.isfinite(q).all(axis=1)[::60]
        if len(dropout_60s) != 1440:
            failures.append({"date": day.isoformat(), "reason": f"{len(dropout_60s)} one-minute samples"})
            continue
        daily.append((day, dropout_60s))
    if failures:
        raise ValueError(f"Cannot analyze incomplete daily products: {failures[:5]}")
    if len(daily) != audit.get("downloaded_days"):
        raise ValueError("Parquet day count disagrees with the independent source audit")

    daily.sort(key=lambda item: item[0])
    states = np.concatenate([mask for _, mask in daily]) if daily else np.array([], dtype=bool)
    if not len(states):
        raise ValueError("No CASSIOPE attitude telemetry products are available")
    rate = float(states.mean())
    transition_counts = np.zeros((2, 2), dtype=np.int64)
    per_day_counts = []
    run_lengths = []
    for day, mask in daily:
        transitions = np.bincount(
            (mask[:-1].astype(np.int8) * 2 + mask[1:].astype(np.int8)), minlength=4)
        counts = transitions.reshape(2, 2)
        padded = np.concatenate(([False], mask, [False])).astype(np.int8)
        edges = np.flatnonzero(np.diff(padded))
        run_lengths.extend((edges[1::2] - edges[::2]).astype(int).tolist())
        transition_counts += counts
        per_day_counts.append({"date": day.isoformat(), "samples": len(mask),
                               "dropout_minutes": int(mask.sum()), "transitions": counts.tolist()})

    n0, n1 = int(transition_counts[0].sum()), int(transition_counts[1].sum())
    p01 = float(transition_counts[0, 1] / n0) if n0 else 0.0
    p11 = float(transition_counts[1, 1] / n1) if n1 else 0.0
    simulated_entry = rate * (1 - p11) / max(1 - rate, 1e-12)
    rng = np.random.default_rng(20261011)
    daily_rate = np.asarray([item["dropout_minutes"] / item["samples"] for item in per_day_counts])
    draws = rng.integers(0, len(daily_rate), size=(bootstrap_replicates, len(daily_rate)))
    daily_ci = np.quantile(daily_rate[draws].mean(axis=1), [0.025, 0.975]).tolist()
    return {
        "status": "completed",
        "source_audit_status": audit["status"],
        "source_date_range": [daily[0][0].isoformat(), daily[-1][0].isoformat()],
        "published_days_analyzed": len(daily),
        "one_hz_samples": int(len(daily) * 86400),
        "one_minute_samples": int(len(states)),
        "one_minute_attitude_solution_dropout_rate": rate,
        "one_minute_dropout_rate_date_cluster_bootstrap_ci95": daily_ci,
        "transition_counts_00_01_10_11": [int(x) for x in transition_counts.ravel()],
        "empirical_dropout_entry_probability_per_minute": p01,
        "empirical_dropout_persistence_probability_per_minute": p11,
        "simulator_entry_probability_implied_by_stationary_rate_and_persistence": simulated_entry,
        "simulator_markov_persistence_parameter": p11,
        "one_minute_dropout_run_count": len(run_lengths),
        "dropout_run_length_minutes": {
            "mean": float(np.mean(run_lengths)) if run_lengths else 0.0,
            "median": float(np.median(run_lengths)) if run_lengths else 0.0,
            "p95": float(np.quantile(run_lengths, 0.95)) if run_lengths else 0.0,
            "max": int(max(run_lengths, default=0)),
        },
        "dropout_run_lengths_are_truncated_at_daily_file_boundaries": True,
        "transition_counts_exclude_interday_boundaries": True,
        "per_day": per_day_counts,
        "interpretation": "One-spacecraft attitude-solution availability pattern sampled at the tasking simulator's one-minute cadence. It can drive a sensor-profile sensitivity case, but is not an estimate of ground-sensor missed acquisitions or fleet-wide failure probability.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DATA)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--bootstrap-replicates", type=int, default=2000)
    args = parser.parse_args()
    data = args.data if args.data.is_absolute() else ROOT / args.data
    result = analyze(data, args.bootstrap_replicates)
    output = args.output or data / "dropout_profile_1minute.json"
    if not output.is_absolute():
        output = ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: result[key] for key in (
        "status", "source_date_range", "published_days_analyzed",
        "one_minute_attitude_solution_dropout_rate",
        "one_minute_dropout_rate_date_cluster_bootstrap_ci95",
        "empirical_dropout_persistence_probability_per_minute",
        "dropout_run_length_minutes")}, indent=2))


if __name__ == "__main__":
    main()
