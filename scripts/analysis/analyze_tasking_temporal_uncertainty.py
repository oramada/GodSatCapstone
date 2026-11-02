#!/usr/bin/env python3
"""Add serial-correlation-aware confidence intervals to audited daily tasking results."""
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
from pathlib import Path

import numpy as np

from godsat.orbits import ROOT, utc

REGIMES = ("leo", "meo", "geo", "heo")
METRICS = {
    "custody_continuity": "custody_change_20pct_minus_0",
    "observable_custody": "observable_custody_change_20pct_minus_0",
    "mean_slew_energy_proxy": "slew_proxy_change_20pct_minus_0",
}
BLOCK_LENGTHS = (1, 7, 14, 30)


def moving_block_means(values, block_length, replicates=10_000, seed=20261011):
    """Circular moving-block bootstrap of a time-ordered mean, with fixed sample size."""
    values = np.asarray(values, dtype=float)
    if values.ndim != 1 or not len(values) or not np.isfinite(values).all():
        raise ValueError("values must be a non-empty finite vector")
    if not 1 <= block_length <= len(values) or replicates < 1:
        raise ValueError("block length and replicate count are outside their valid range")
    rng = np.random.default_rng(seed)
    blocks_per_replicate = int(np.ceil(len(values) / block_length))
    offsets = np.arange(block_length)
    means = np.empty(replicates, dtype=float)
    for start in range(0, replicates, 256):
        batch_size = min(256, replicates - start)
        starts = rng.integers(0, len(values), size=(batch_size, blocks_per_replicate))
        indices = ((starts[:, :, None] + offsets[None, None, :]) % len(values))
        indices = indices.reshape(batch_size, -1)[:, :len(values)]
        means[start:start + batch_size] = values[indices].mean(axis=1)
    return means


def load_daily_effects(folder: Path):
    summary = json.loads((folder / "summary.json").read_text())
    audit = json.loads((folder / "independent_audit.json").read_text())
    dates = summary.get("dates", [])
    if (summary.get("status") != "completed"
            or audit.get("status") != "passed_structural_and_statistical"
            or audit.get("dates_checked") != len(dates)
            or audit.get("response_rows_checked") != len(dates) * len(REGIMES) * 2
            or audit.get("date_cluster_effects_independently_recomputed") is not True):
        raise ValueError("The complete tasking result and independent audit are required")
    parsed = [utc(date) for date in dates]
    if any((right - left).total_seconds() != 86400 for left, right in zip(parsed, parsed[1:])):
        raise ValueError("Daily tasking design contains a missing or irregular date")
    rows = {}
    with (folder / "responses.csv").open(newline="") as stream:
        for row in csv.DictReader(stream):
            key = (row["date"], row["orbit_regime_sensor_hosts"], float(row["requested_outage_rate"]))
            if key in rows:
                raise ValueError(f"Duplicate paired response row: {key}")
            rows[key] = row
    if len(rows) != len(dates) * len(REGIMES) * 2:
        raise ValueError("Daily CSV response grid is incomplete")
    effects = {}
    for regime in REGIMES:
        effects[regime] = {name: [] for name in METRICS}
        for date in dates:
            zero = rows[(date, regime, 0.0)]
            outage = rows[(date, regime, 0.2)]
            for metric in METRICS:
                effects[regime][metric].append(float(outage[metric]) - float(zero[metric]))
    return summary, audit, dates, effects


def analyze(folder: Path, output: Path | None = None, replicates: int = 10_000):
    source_names=('summary.json','responses.csv','independent_audit.json')
    source_hashes={name:hashlib.sha256((folder/name).read_bytes()).hexdigest() for name in source_names}
    summary, audit, dates, effects = load_daily_effects(folder)
    result = {
        "status": "completed_temporal_block_bootstrap",
        "tasking_summary_status": summary["status"],
        "tasking_independent_audit_status": audit["status"],
        "dates": len(dates), "date_range": [dates[0], dates[-1]],
        "responses": audit["response_rows_checked"],
        "source_sha256": source_hashes,
        "treatment": "paired 20% burst-outage simulator minus zero-outage reference",
        "resampling": {"method": "circular moving-block bootstrap over daily paired effects",
                       "block_lengths_days": list(BLOCK_LENGTHS), "replicates": replicates,
                       "seed": 20261011},
        "effects": {},
        "interpretation_limit": "Serial-dependence sensitivity for one-hour/day synthetic tasking episodes; the 20% outage is injected and does not estimate real hardware dropout effectiveness.",
    }
    for regime in REGIMES:
        result["effects"][regime] = {}
        for metric, values in effects[regime].items():
            arr = np.asarray(values, dtype=float)
            item = {"mean": float(arr.mean()), "date_sd": float(arr.std(ddof=1)),
                    "annual_means": {year: float(np.mean([value for date, value in zip(dates, arr)
                                                           if date[:4] == year])
                                                   ) for year in sorted({date[:4] for date in dates})}}
            item["moving_block_ci95"] = {}
            for length in BLOCK_LENGTHS:
                means = moving_block_means(arr, length, replicates,
                    seed=20261011 + BLOCK_LENGTHS.index(length) + 100 * REGIMES.index(regime)
                    + 1000 * list(METRICS).index(metric))
                lo, hi = np.quantile(means, [0.025, 0.975])
                item["moving_block_ci95"][str(length)] = [float(lo), float(hi)]
            result["effects"][regime][metric] = item
    target = output or folder / "temporal_uncertainty.json"
    if any(hashlib.sha256((folder/name).read_bytes()).hexdigest()!=digest
           for name,digest in source_hashes.items()):
        raise ValueError('Completed tasking source changed during temporal uncertainty analysis')
    target.write_text(json.dumps(result, indent=2) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "outputs/full-catalog-tasking-daily-2022-2026")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--replicates", type=int, default=10_000)
    args = parser.parse_args()
    folder = args.input if args.input.is_absolute() else ROOT / args.input
    output = args.output if args.output is None or args.output.is_absolute() else ROOT / args.output
    result = analyze(folder, output, args.replicates)
    print(json.dumps({"status": result["status"], "dates": result["dates"],
                      "responses": result["responses"], "output": str(output or folder / "temporal_uncertainty.json")}, indent=2))


if __name__ == "__main__":
    main()
