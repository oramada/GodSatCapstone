#!/usr/bin/env python3
"""Independently audit completed dates while the full daily tasking run is checkpointing."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from collections import defaultdict
from pathlib import Path

from scripts.audit_full_catalog_tasking import (
    REGIMES,
    recompute_host_state_availability,
    verify_rows,
)
from godsat.orbits import ROOT, utc
from godsat.scenario import cache_key


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def audit_prefix(output: Path, audit_path: Path | None = None) -> dict:
    cells = output / "cells"
    if not cells.is_dir():
        raise FileNotFoundError(f"Tasking checkpoint directory not found: {cells}")
    by_date: dict[str, list[Path]] = defaultdict(list)
    for path in cells.glob("*/*.json"):
        by_date[path.parent.name].append(path)
    complete_dates = sorted(
        date for date, paths in by_date.items()
        if len(paths) == len(REGIMES)
        and {path.stem for path in paths} == set(REGIMES)
    )
    if not complete_dates:
        raise ValueError("No complete daily date checkpoints are available")
    parsed = [dt.date.fromisoformat(date) for date in complete_dates]
    if any((right - left).days != 1 for left, right in zip(parsed, parsed[1:])):
        raise ValueError("Completed daily checkpoints contain a date gap")

    config = json.loads((ROOT / "outputs/all-orbits-paper-exact-active-hosts/config.json").read_text())
    config.update(duration_minutes=60, step_seconds=60, propagation_model="sgp4")

    rows = []
    host_ids_by_date = {}
    scenario_target_counts = {}
    scenario_arrays_verified = 0
    for date in complete_dates:
        date_regimes = set()
        host_ids_by_date[date] = {}
        paths = by_date[date]
        if len(paths) != len(REGIMES):
            raise ValueError(f"Date {date} has an unexpected complete cell count")
        for cell_path in paths:
            cell = json.loads(cell_path.read_text())
            cell_rows = cell.get("rows", [])
            if cell.get("simulator_version") != 2 or len(cell_rows) != 2:
                raise ValueError(f"Cell is incomplete or uses an unknown simulator version: {cell_path}")
            regimes = {row["orbit_regime_sensor_hosts"] for row in cell_rows}
            dates = {row["date"] for row in cell_rows}
            if dates != {date + "T00:00:00Z"} or len(regimes) != 1:
                raise ValueError(f"Cell identity differs from its path: {cell_path}")
            regime = regimes.pop()
            if regime not in REGIMES or regime in date_regimes:
                raise ValueError(f"Duplicate/invalid regime cell: {cell_path}")
            date_regimes.add(regime)
            host_lists = {tuple(map(int, row["sensor_host_ids"])) for row in cell_rows}
            if len(host_lists) != 1:
                raise ValueError(f"Paired conditions use different hosts: {cell_path}")
            hosts = host_lists.pop()
            if len(hosts) != 6 or len(set(hosts)) != 6:
                raise ValueError(f"Invalid six-host scenario: {cell_path}")
            scenario_configs = [config]
            if int(config.get("targets", 1)) > 1:
                # The live runner falls back to targets=1 when fewer than its
                # nominal DOE target count are visible at an episode epoch.
                scenario_configs.append({**config, "targets": 1})
            matched_scenario = None
            for scenario_config in scenario_configs:
                candidate = ROOT / "data/scenarios" / f"{cache_key(date + 'T00:00:00Z', scenario_config, regime)}.npz"
                candidate_metadata = candidate.with_suffix(".json")
                if (not candidate.is_file() or not candidate_metadata.is_file()
                        or sha256(candidate) != cell.get("source_sha256")):
                    continue
                candidate_data = json.loads(candidate_metadata.read_text())
                if tuple(map(int, candidate_data.get("agents", []))) != hosts:
                    continue
                matched_scenario = (candidate, int(scenario_config.get("targets", 1)))
                break
            if matched_scenario is None:
                raise ValueError(f"Scenario source array hash/host identity does not match {cell_path}")
            _scenario_path, scenario_target_count = matched_scenario
            scenario_target_counts[f"{date}/{regime}"] = scenario_target_count
            scenario_arrays_verified += 1
            host_ids_by_date[date][regime] = list(hosts)
            rows.extend(cell_rows)
        if date_regimes != set(REGIMES):
            raise ValueError(f"Date {date} does not contain all four orbit regimes")

    indexed = verify_rows(rows, [date + "T00:00:00Z" for date in complete_dates])
    normalized_host_ids = {
        date + "T00:00:00Z": host_ids_by_date[date] for date in complete_dates
    }
    availability = recompute_host_state_availability(
        indexed, normalized_host_ids, config,
        [date + "T00:00:00Z" for date in complete_dates])
    result = {
        "status": "passed_completed_prefix_independent_audit",
        "full_design_complete": False,
        "dates_checked": len(complete_dates),
        "date_range": [complete_dates[0], complete_dates[-1]],
        "paired_date_regime_cells_checked": len(complete_dates) * len(REGIMES),
        "response_rows_checked": len(rows),
        "scenario_array_hashes_verified": scenario_arrays_verified,
        "scenario_target_counts": scenario_target_counts,
        "cell_files_sha256": {
            str(path.relative_to(output)): sha256(path)
            for date in complete_dates for path in by_date[date]
        },
        "source_hashes": {
            str((ROOT / "outputs/all-orbits-paper-exact-active-hosts/config.json").relative_to(ROOT)):
                sha256(ROOT / "outputs/all-orbits-paper-exact-active-hosts/config.json"),
            "data/raw/manifest.json": sha256(ROOT / "data/raw/manifest.json"),
        },
        "date_gaps": 0,
        "independent_historical_host_state_replay": availability,
        "checks": {
            "consecutive_completed_date_prefix": True,
            "all_four_regimes_per_date": True,
            "paired_zero_and_20pct_conditions": True,
            "scenario_array_hash_and_host_identity": True,
            "response_invariants": True,
            "historical_host_states_recomputed_from_source": True,
        },
        "scope_limit": "This verifies only the completed prefix while the full daily design is running; it does not replace the final whole-grid audit.",
    }
    target = audit_path or output / "completed_prefix_audit.json"
    target.write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "outputs/full-catalog-tasking-daily-2022-2026")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    folder = args.input if args.input.is_absolute() else ROOT / args.input
    destination = args.output if args.output is None or args.output.is_absolute() else ROOT / args.output
    result = audit_prefix(folder, destination)
    print(json.dumps({"status": result["status"], "dates": result["dates_checked"],
                      "cells": result["paired_date_regime_cells_checked"],
                      "responses": result["response_rows_checked"], "output": str(destination or folder / "completed_prefix_audit.json")}, indent=2))


if __name__ == "__main__":
    main()
