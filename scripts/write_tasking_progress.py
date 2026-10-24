#!/usr/bin/env python3
"""Write a nonfinal, integrity-checked progress snapshot from tasking cell files."""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

from godsat.orbits import ROOT
from scripts.run_full_catalog_tasking import REGIMES, OUTAGE_RATES, SIMULATOR_VERSION
from scripts.audit_full_catalog_tasking import sha256


def write_progress(output: Path, dates: list[str] | None = None) -> dict:
    summary_path = output / "summary.json"
    if summary_path.exists():
        summary = json.loads(summary_path.read_text())
        if summary.get("status") == "completed":
            raise ValueError("Campaign is complete; use its final summary and independent audit")
        dates = summary.get("dates", dates)
    if not dates:
        raise ValueError("Pass the complete planned date list or provide summary.json")
    rates = list(OUTAGE_RATES)
    cells = output / "cells"
    completed_dates = []
    verified_groups = 0
    source_hashes = {}
    for date in dates:
        per_date = []
        for regime in REGIMES:
            path = cells / date[:10] / f"{regime}.json"
            try:
                cell = json.loads(path.read_text())
                rows = cell.get("rows", [])
                good = (cell.get("simulator_version") == SIMULATOR_VERSION
                        and len(rows) == len(rates)
                        and {float(row["requested_outage_rate"]) for row in rows} == set(rates)
                        and bool(cell.get("source_sha256"))
                        and all(row.get("date") == date and row.get("orbit_regime_sensor_hosts") == regime
                                for row in rows))
            except (OSError, ValueError, KeyError, TypeError):
                good = False
            if not good:
                per_date = []
                break
            per_date.append(path)
            source_hashes[f"{date}/{regime}"] = json.loads(path.read_text()).get("source_sha256")
        if len(per_date) != len(REGIMES):
            break
        completed_dates.append(date)
        verified_groups += len(REGIMES)

    result = {
        "status": "running_checkpointed", "final_results": False,
        "simulator_version": SIMULATOR_VERSION,
        "expected_date_regime_groups": len(dates) * len(REGIMES),
        "verified_completed_date_regime_groups": verified_groups,
        "expected_date_count": len(dates), "complete_date_count": len(completed_dates),
        "completed_date_range": [completed_dates[0], completed_dates[-1]] if completed_dates else None,
        "outage_rates": rates,
        "source_scenario_sha256": source_hashes,
        "cell_files_sha256": {str(path.relative_to(output)): sha256(path)
                               for date in completed_dates for path in
                               [cells / date[:10] / f"{regime}.json" for regime in REGIMES]},
        "updated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "interpretation": "Nonfinal progress snapshot. The final independent audit is still required.",
    }
    target = output / "progress.json"
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(result, indent=2) + "\n")
    tmp.replace(target)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/full-catalog-tasking-daily-2022-2026")
    parser.add_argument("--dates", help="comma-separated planned date starts, required until final summary exists")
    args = parser.parse_args()
    output = args.output if args.output.is_absolute() else ROOT / args.output
    dates = [item.strip() for item in args.dates.split(",") if item.strip()] if args.dates else None
    result = write_progress(output, dates)
    print(json.dumps({key: result[key] for key in (
        "status", "expected_date_regime_groups", "verified_completed_date_regime_groups",
        "expected_date_count", "complete_date_count", "completed_date_range")}, indent=2))


if __name__ == "__main__":
    main()
