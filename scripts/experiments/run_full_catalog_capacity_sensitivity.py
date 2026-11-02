"""Compare 6/12/24 nested hypothetical host teams against all catalog targets.

Each capacity uses a nested set from the same regime-specific active-payload
cluster, so the target catalog, host geometry ordering, episode cadence, and
paired dropout design stay fixed while sensor count changes.
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
from pathlib import Path
import sys
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from godsat.dropout import monthly_dates, quarterly_dates
from godsat.orbits import History
from godsat.scenario import prepare
from scripts.experiments.run_full_catalog_tasking import (OUTAGE_RATES, REGIMES, read_inputs,
    sha256, simulate_condition, write_csv)

CAPACITY_LEVELS = (6, 12, 24)
SIMULATOR_VERSION = 2


def run(output: Path, selected_dates: list[str] | None = None, max_groups: int | None = None,
        date_grid: str = "quarterly"):
    if date_grid not in {"quarterly", "monthly"}:
        raise ValueError("date_grid must be quarterly or monthly")
    campaign = ROOT / "outputs/all-orbits-paper-exact-active-hosts"
    config_path = campaign / "config.json"
    config = json.loads(config_path.read_text())
    config.update(duration_minutes=60, step_seconds=60, propagation_model="sgp4")
    registered = monthly_dates() if date_grid == "monthly" else quarterly_dates()
    dates = selected_dates or registered
    if not dates or any(date not in registered for date in dates):
        raise ValueError("Dates must be selected from the registered quarterly grid")
    output.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    scenario_hashes: dict[str, dict[str, str]] = {}
    metadata_hashes: dict[str, dict[str, str]] = {}
    history = History(ROOT, "all")
    completed = 0
    expected_groups = 0
    try:
        for date_index, date in enumerate(dates):
            date_scenario_hashes: dict[str, str] = {}
            date_metadata_hashes: dict[str, str] = {}
            print(f"Preparing catalog input at {date}", flush=True)
            ids, states, ages, valid, times = read_inputs(date, history, config)
            for regime_index, regime in enumerate(REGIMES):
                host_config = {**config, "agents": max(CAPACITY_LEVELS)}
                attainable = list(CAPACITY_LEVELS)
                try:
                    scenario_path = prepare(date, host_config, regime=regime)
                except ValueError as error:
                    # The regime may not contain 24 eligible payload candidates.
                    # Fall back to the largest supported nested team and keep the
                    # attainable levels explicit in the saved design.
                    if "sensor candidates" not in str(error):
                        raise
                    available = int(str(error).split("sensor candidates,", 1)[0].strip().rsplit(" ", 1)[-1])
                    maximum = min(max(CAPACITY_LEVELS), available)
                    attainable = sorted({n for n in CAPACITY_LEVELS if n < maximum} | {maximum})
                    host_config = {**config, "agents": maximum}
                    scenario_path = prepare(date, host_config, regime=regime)
                metadata_path = scenario_path.with_suffix(".json")
                metadata = json.loads(metadata_path.read_text())
                nested_hosts = list(map(int, metadata.get("agents", [])))
                if len(nested_hosts) != int(host_config["agents"]) or len(set(nested_hosts)) != len(nested_hosts):
                    raise ValueError(f"Invalid host set at {date} {regime}")
                expected_groups += len(attainable)
                date_scenario_hashes[regime] = sha256(scenario_path)
                date_metadata_hashes[regime] = sha256(metadata_path)
                for capacity in attainable:
                    cell = output / "cells" / date[:10] / f"{regime}_hosts{capacity}.json"
                    host_ids = nested_hosts[:capacity]
                    source_sig = hashlib.sha256((date_scenario_hashes[regime]
                        + date_metadata_hashes[regime] + str(capacity)).encode()).hexdigest()
                    saved = None
                    if cell.is_file():
                        candidate = json.loads(cell.read_text())
                        if (candidate.get("simulator_version") == SIMULATOR_VERSION
                                and candidate.get("source_signature") == source_sig
                                and candidate.get("host_ids") == host_ids):
                            saved = candidate
                    if saved is not None:
                        rows.extend(saved["rows"])
                        completed += 1
                        continue
                    capacity_config = {**config, "agents": capacity}
                    cell_rows = [simulate_condition(date_index, regime_index, rate, ids,
                        states, ages, valid, times, host_ids, capacity_config, seed=73129,
                        target_exclude_ids=nested_hosts)
                        for rate in OUTAGE_RATES]
                    for row in cell_rows:
                        row["sensor_count"] = capacity
                        row["capacity_scenario"] = "nested active-payload host set; hypothetical sensor payloads"
                    cell.parent.mkdir(parents=True, exist_ok=True)
                    temp = cell.with_suffix(".json.tmp")
                    temp.write_text(json.dumps({"simulator_version": SIMULATOR_VERSION,
                        "source_signature": source_sig,
                        "scenario_sha256": date_scenario_hashes[regime],
                        "scenario_metadata_sha256": date_metadata_hashes[regime],
                        "host_ids": host_ids, "rows": cell_rows}, indent=2) + "\n")
                    temp.replace(cell)
                    rows.extend(cell_rows)
                    completed += 1
                    print(f"{date} {regime} {capacity} hosts: {len(ids):,} catalog IDs; paired outage replay complete ({completed})", flush=True)
                    if max_groups is not None and completed >= max_groups:
                        break
                if max_groups is not None and completed >= max_groups:
                    break
            scenario_hashes[date] = date_scenario_hashes
            metadata_hashes[date] = date_metadata_hashes
            if max_groups is not None and completed >= max_groups:
                break
    finally:
        history.db.close()
    complete = completed == expected_groups
    result = {
        "status": "completed" if complete else "partial",
        "scope": f"{date_grid.title()} one-hour all-catalog target episodes; four host orbit regimes; nested teams targeting 6, 12, and up to 24 hosts (regime/date limited); paired 0%/20% burst loss.",
        "method": "SGP4 WGS-72; same greedy urgency-minus-slew scheduler as the full-catalog 6-host reference. Host IDs are nested prefixes of the maximum available dense-cluster selection for each date/regime.",
        "interpretation": "Sensor-count capacity sensitivity with hypothetical sensors hosted on current-active-payload objects. The host spacecraft are real catalog objects, but sensor payload and historical host operation are assumed.",
        "paper_policy_relation": "Separate greedy scale test; does not alter or claim to generalize the trained 18-target DOE policy.",
        "simulator_version": SIMULATOR_VERSION,
        "date_grid": date_grid,
        "dates": dates,
        "nominal_capacity_levels": list(CAPACITY_LEVELS),
        "regimes": list(REGIMES),
        "outage_rates": list(OUTAGE_RATES),
        "expected_date_regime_capacity_groups": expected_groups,
        "completed_date_regime_capacity_groups": completed,
        "config": config,
        "config_sha256": sha256(config_path),
        "raw_archive_manifest_sha256": sha256(ROOT / "data/raw/manifest.json"),
        "scenario_cache_sha256": scenario_hashes,
        "scenario_metadata_sha256": metadata_hashes,
        "rows": rows,
        "capacity_effects": summarize_capacity(rows),
        "maximum_team_size_by_date_regime": maximum_team_sizes(rows, dates),
        "limits": [
            "The additional host candidates are current active-payload objects backcast through history; past operation is unverified.",
            "Their sensor payload, field calibration, weather, daylight, and ground-support schedule are hypothetical.",
            f"{date_grid.title()} one-hour samples are not continuous operations; outages are injected rather than measured.",
            "The policy is greedy and is not the paper's actor-critic or original MATLAB GoDSAT implementation.",
        ],
    }
    output.joinpath("summary.json").write_text(json.dumps(result, indent=2) + "\n")
    write_csv(output / "responses.csv", rows)
    return result


def maximum_team_sizes(rows, dates):
    result = {}
    for date in dates:
        result[date] = {}
        for regime in REGIMES:
            sizes = [int(row["sensor_count"]) for row in rows
                     if row["date"] == date
                     and row["orbit_regime_sensor_hosts"] == regime
                     and float(row["requested_outage_rate"]) == 0.0]
            if sizes:
                result[date][regime] = max(sizes)
    return result


def summarize_capacity(rows):
    from scipy.stats import t as student_t
    indexed = {(row["date"], row["orbit_regime_sensor_hosts"], row["sensor_count"],
                float(row["requested_outage_rate"])): row for row in rows}
    result = []
    for regime in REGIMES:
        for capacity in sorted({int(row["sensor_count"]) for row in rows
                                if row["orbit_regime_sensor_hosts"] == regime}):
            by_date = []
            for date in sorted({row["date"] for row in rows}):
                zero = indexed.get((date, regime, capacity, 0.0))
                loss = indexed.get((date, regime, capacity, 0.2))
                if zero is None or loss is None:
                    continue
                by_date.append({"date": date,
                    "zero_loss_custody": zero["custody_continuity"],
                    "burst_loss_custody": loss["custody_continuity"],
                    "burst_minus_zero_custody": loss["custody_continuity"] - zero["custody_continuity"],
                    "zero_loss_observable_custody": zero["observable_custody"],
                    "burst_loss_observable_custody": loss["observable_custody"]})
            if len(by_date) != len({row["date"] for row in rows}):
                # Variable maximum HEO teams are retained in raw responses, but
                # only fixed capacities with full date coverage support a
                # like-for-like clustered effect estimate.
                continue
            samples = np.asarray([row["burst_minus_zero_custody"] for row in by_date])
            half = (float(student_t.ppf(.975, len(samples)-1) * samples.std(ddof=1) / np.sqrt(len(samples)))
                    if len(samples) > 1 else None)
            means = {name: float(np.mean([row[name] for row in by_date])) if by_date else None
                     for name in ("zero_loss_custody", "burst_loss_custody",
                                  "zero_loss_observable_custody", "burst_loss_observable_custody")}
            result.append({"sensor_host_regime": regime, "sensor_count": capacity,
                "n_date_clusters": len(by_date), **means,
                "burst_minus_zero_custody_mean": float(samples.mean()) if len(samples) else None,
                "burst_minus_zero_custody_ci95": ([float(samples.mean()-half), float(samples.mean()+half)]
                                                    if half is not None else None),
                "date_effects": by_date})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date-grid", choices=("quarterly", "monthly"), default="quarterly",
                        help="sample all dates on the selected historical grid")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--dates", help="optional comma-separated dates from the selected grid")
    parser.add_argument("--max-groups", type=int, help="smoke-run limit for date/regime/host-count cells")
    args = parser.parse_args()
    output = args.output or ROOT / f"outputs/full-catalog-capacity-sensitivity-{args.date_grid}-2022-2026"
    output = output if output.is_absolute() else ROOT / output
    dates = [item.strip() for item in args.dates.split(",") if item.strip()] if args.dates else None
    result = run(output, dates, args.max_groups, args.date_grid)
    print(json.dumps({"status": result["status"], "output": str(output),
                      "completed_groups": result["completed_date_regime_capacity_groups"],
                      "response_rows": len(result["rows"])}, indent=2))


if __name__ == "__main__":
    main()
