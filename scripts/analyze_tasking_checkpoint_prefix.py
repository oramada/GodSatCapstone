#!/usr/bin/env python3
"""Summarize paired effects for an independently audited daily-tasking prefix."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.stats import t as student_t

from godsat.orbits import ROOT
from scripts.analyze_tasking_temporal_uncertainty import (
    BLOCK_LENGTHS,
    METRICS,
    moving_block_means,
)
from scripts.audit_full_catalog_tasking import REGIMES

ROW_FIELDS = {
    "custody_continuity": "custody_continuity",
    "observable_custody": "observable_custody",
    "mean_slew_energy_proxy": "mean_slew_energy_proxy",
}


def analyze(output: Path, replicates: int = 10_000) -> dict:
    audit_path = output / "completed_prefix_audit.json"
    audit = json.loads(audit_path.read_text())
    if audit.get("status") != "passed_completed_prefix_independent_audit":
        raise ValueError("A passing independent prefix audit is required")
    dates = [f"{date}T00:00:00Z" for date in audit["date_range"]]
    if (len(dates) != 2 or audit.get("dates_checked") != len(dates)):
        # The audit stores only endpoints. Derive the exact contiguous date grid.
        from datetime import date, timedelta
        start = date.fromisoformat(audit["date_range"][0])
        count = int(audit["dates_checked"])
        dates = [(start + timedelta(days=i)).isoformat() + "T00:00:00Z" for i in range(count)]
    paired = {}
    for day in dates:
        for regime in REGIMES:
            cell_path = output / "cells" / day[:10] / f"{regime}.json"
            relative_path = cell_path.relative_to(output).as_posix()
            expected_hash = audit.get("cell_files_sha256", {}).get(relative_path)
            if expected_hash is None or not cell_path.is_file():
                raise ValueError(f"Cell is not covered by the independent audit: {cell_path}")
            cell = json.loads(cell_path.read_text())
            actual_hash = hashlib.sha256(cell_path.read_bytes()).hexdigest()
            if actual_hash != expected_hash:
                raise ValueError(f"Cell is not covered by the independent audit: {cell_path}")
            indexed = {float(row["requested_outage_rate"]): row for row in cell["rows"]}
            if set(indexed) != {0.0, 0.2}:
                raise ValueError(f"Paired 0%/20% treatments are incomplete: {cell_path}")
            paired[(day, regime)] = indexed

    result = {
        "status": "preliminary_audited_prefix_effects",
        "prefix_audit_status": audit["status"],
        "dates": len(dates),
        "date_range": audit["date_range"],
        "paired_date_regime_cells": audit["paired_date_regime_cells_checked"],
        "treatment": "synthetic paired 20% burst dropout minus no-injected-dropout reference",
        "uncertainty": {"date_cluster_t_interval": "two-sided 95% Student t interval over daily paired effects",
                        "moving_block_bootstrap": "circular daily moving blocks; serial-correlation sensitivity only",
                        "block_lengths_days": list(BLOCK_LENGTHS), "replicates": replicates,
                        "seed": 20261011},
        "effects": {},
        "baseline_context": {},
        "interpretation_limit": "Preliminary effect for the completed, independently audited date prefix; this is a synthetic tasking sensitivity, not natural ground-sensor dropout effectiveness or a complete four-year result.",
    }
    for regime_index, regime in enumerate(REGIMES):
        result["effects"][regime] = {}
        baseline_rows = [paired[(day, regime)][0.0] for day in dates]
        result["baseline_context"][regime] = {
            "mean_catalog_objects_per_episode": float(np.mean([row["catalog_objects_in_episode"] for row in baseline_rows])),
            "mean_targets_valid_across_episode_steps": float(np.mean([row["valid_target_fraction"] for row in baseline_rows])),
            "mean_target_observable_step_fraction": float(np.mean([
                row["target_observable_step_count"] / max(1, row["target_valid_step_count"])
                for row in baseline_rows
            ])),
            "mean_sensor_actions_per_hour": float(np.mean([row["sensor_actions"] for row in baseline_rows])),
            "mean_detected_observations_per_hour": float(np.mean([row["detections"] for row in baseline_rows])),
            "mean_zero_dropout_custody": float(np.mean([row["custody_continuity"] for row in baseline_rows])),
            "mean_zero_dropout_observable_custody": float(np.mean([row["observable_custody"] for row in baseline_rows])),
        }
        for metric_index, (metric, _effect_name) in enumerate(METRICS.items()):
            field = ROW_FIELDS[metric]
            changes = np.asarray([
                float(paired[(day, regime)][0.2][field])
                - float(paired[(day, regime)][0.0][field])
                for day in dates
            ])
            mean = float(changes.mean())
            half = float(student_t.ppf(.975, len(changes)-1) * changes.std(ddof=1) / np.sqrt(len(changes))) if len(changes) > 1 else None
            item = {"mean_change": mean,
                    "date_cluster_ci95": [mean-half, mean+half] if half is not None else None,
                    "date_cluster_sd": float(changes.std(ddof=1)) if len(changes) > 1 else None,
                    "annual_means": {year: float(np.mean([value for day, value in zip(dates, changes) if day[:4] == year]))
                                     for year in sorted({day[:4] for day in dates})},
                    "moving_block_ci95": {}}
            for block_index, length in enumerate(BLOCK_LENGTHS):
                means = moving_block_means(changes, min(length, len(changes)), replicates,
                    seed=20261011 + block_index + 100 * regime_index + 1000 * metric_index)
                lo, hi = np.quantile(means, [.025, .975])
                item["moving_block_ci95"][str(length)] = [float(lo), float(hi)]
            result["effects"][regime][metric] = item
    target = output / "preliminary_prefix_effects.json"
    target.write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/full-catalog-tasking-daily-2022-2026")
    parser.add_argument("--replicates", type=int, default=10_000)
    args = parser.parse_args()
    output = args.output if args.output.is_absolute() else ROOT / args.output
    result = analyze(output, args.replicates)
    print(json.dumps({"status": result["status"], "dates": result["dates"],
                      "date_range": result["date_range"], "output": str(output / "preliminary_prefix_effects.json")}, indent=2))


if __name__ == "__main__":
    main()
