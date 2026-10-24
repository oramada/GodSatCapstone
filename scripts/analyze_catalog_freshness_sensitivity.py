"""Count catalog trajectory grid slots supported by elements of varying age.

This measures source-element freshness only. Longer thresholds show the
additional slots one would propagate from older TLE/OMM elements; they do not
certify those extrapolated states as accurate or suitable for operations.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import pathlib
import statistics

import duckdb

from godsat.catalog_trajectory import catalog_object_ids, source_revision
from godsat.orbits import ROOT, utc


DEFAULT_START = "2022-10-09T00:00:00Z"
DEFAULT_END = "2026-10-10T00:00:00Z"
DEFAULT_THRESHOLDS = (72, 168, 336, 720)
EARTH_MU_KM3_S2 = 398600.4418
EARTH_RADIUS_KM = 6378.135


def quantiles(values):
    ordered = sorted(values)
    if not ordered:
        return {"count": 0}
    def at(p):
        return ordered[min(len(ordered) - 1, math.ceil(p * len(ordered)) - 1)]
    return {"count": len(ordered), "min": ordered[0],
            "p10": at(.10), "median": statistics.median(ordered),
            "p90": at(.90), "max": ordered[-1]}


def year_bounds(start, end):
    lower = start.replace(month=1, day=1, hour=0, minute=0,
                          second=0, microsecond=0)
    values = []
    while lower < end:
        upper = min(lower.replace(year=lower.year + 1), end)
        values.append((lower.year, max(lower, start), upper))
        lower = lower.replace(year=lower.year + 1)
    return values


def analyze(root=ROOT, output=None, start=DEFAULT_START, end=DEFAULT_END,
            step_seconds=14400, thresholds_hours=DEFAULT_THRESHOLDS,
            memory_limit="3GB"):
    root = pathlib.Path(root).resolve()
    start, end = utc(start), utc(end)
    thresholds_hours = tuple(sorted(set(map(int, thresholds_hours))))
    if start >= end or step_seconds <= 0 or 86400 % step_seconds:
        raise ValueError("Invalid interval or cadence; cadence must divide one day")
    if not thresholds_hours or thresholds_hours[0] < 0:
        raise ValueError("At least one nonnegative age threshold is required")
    trajectory_dir = root / "outputs/catalog-trajectory-all-4hour-2022-2026"
    trajectory_manifest = json.loads((trajectory_dir / "manifest.json").read_text())
    trajectory_validation = json.loads((trajectory_dir / "validation.json").read_text())
    if trajectory_validation.get("status") != "validated_complete":
        raise RuntimeError("Reference four-hour trajectory export is not independently validated")
    if (trajectory_manifest.get("start") != start.isoformat()
            or trajectory_manifest.get("end_exclusive") != end.isoformat()
            or trajectory_manifest.get("step_seconds") != step_seconds):
        raise ValueError("Requested interval/cadence differs from validated reference trajectory")
    if trajectory_manifest.get("source_revision") != source_revision(root):
        raise RuntimeError("Raw orbital-element source revision differs from trajectory export")
    cohort_ids = catalog_object_ids(root, start, end, trajectory_manifest["max_age_hours"])

    raw_paths = sorted((root / "data/raw").glob("tle_*.parquet"))
    if len(raw_paths) != 5:
        raise FileNotFoundError(f"Expected five annual source files; found {len(raw_paths)}")
    lower_source = start - dt.timedelta(hours=max(thresholds_hours))
    step_us = step_seconds * 1_000_000
    total_samples = math.ceil((end - start).total_seconds() / step_seconds)
    years = year_bounds(start, end)
    object_count = int(trajectory_manifest["object_count"])
    object_ids = cohort_ids
    if len(object_ids) != object_count:
        raise AssertionError(f"Freshness query cohort has {len(object_ids)} objects; trajectory manifest has {object_count}")
    year_slots = {year: math.ceil((hi - lo).total_seconds() / step_seconds)
                  for year, lo, hi in years}
    total_scheduled = sum(year_slots.values()) * object_count
    if total_scheduled != trajectory_manifest["projected_rows"]:
        raise AssertionError("Computed freshness grid denominator differs from trajectory manifest")

    per_threshold_year_object = {threshold: {} for threshold in thresholds_hours}
    start_iso = start.isoformat()
    for year, year_start, year_end in years:
        lookback = year_start - dt.timedelta(hours=max(thresholds_hours))
        source_years = range(lookback.year, (year_end - dt.timedelta(microseconds=1)).year + 1)
        year_paths = [root / f"data/raw/tle_{source_year}.parquet"
                      for source_year in source_years]
        missing_paths = [str(path) for path in year_paths if not path.is_file()]
        if missing_paths:
            raise FileNotFoundError(f"Missing annual source archive(s): {missing_paths}")
        paths_sql = "[" + ",".join("'" + str(path).replace("'", "''") + "'" for path in year_paths) + "]"
        age_columns = []
        for threshold in thresholds_hours:
            age_end = (f"floor(date_diff('microseconds', TIMESTAMPTZ '{start_iso}', "
                       f"epoch + {threshold} * INTERVAL '1 hour')::DOUBLE / {step_us}) + 1")
            age_columns.append(
                "sum(greatest(0, least("
                f"{total_samples}, "
                f"ceil(date_diff('microseconds', TIMESTAMPTZ '{start_iso}', "
                f"least(next_epoch, TIMESTAMPTZ '{year_end.isoformat()}'))::DOUBLE / {step_us}), "
                f"{age_end}) - greatest(0, "
                f"ceil(date_diff('microseconds', TIMESTAMPTZ '{start_iso}', "
                f"greatest(epoch, TIMESTAMPTZ '{year_start.isoformat()}'))::DOUBLE / {step_us})))"
                f")::BIGINT AS fresh_{threshold}h")
        sql = f"""
            WITH source_epochs AS (
                SELECT DISTINCT norad_id, epoch
                FROM read_parquet({paths_sql})
                WHERE epoch >= CAST(? AS TIMESTAMPTZ)
                  AND epoch < CAST(? AS TIMESTAMPTZ)
                  AND norad_id IN (SELECT unnest(?))
            ), intervals AS (
                SELECT norad_id, epoch,
                       coalesce(lead(epoch) OVER (PARTITION BY norad_id ORDER BY epoch),
                                CAST(? AS TIMESTAMPTZ)) AS next_epoch
                FROM source_epochs
            )
            SELECT norad_id, {', '.join(age_columns)}
            FROM intervals
            GROUP BY norad_id
        """
        db = duckdb.connect()
        try:
            db.execute("SET TimeZone='UTC'")
            db.execute("SET threads=2")
            db.execute(f"SET memory_limit='{memory_limit}'")
            db.execute("SET preserve_insertion_order=false")
            db.execute("SET temp_directory='/tmp/godsat-freshness-duckdb'")
            year_rows = db.execute(sql, [lookback.isoformat(), year_end.isoformat(),
                                          object_ids, year_end.isoformat()]).fetchall()
        finally:
            db.close()
        for row in year_rows:
            norad_id = int(row[0])
            for index, threshold in enumerate(thresholds_hours, start=1):
                count = int(row[index] or 0)
                if count:
                    per_threshold_year_object[threshold].setdefault(year, {})[norad_id] = count
    results = []
    for threshold in thresholds_hours:
        year_summary = []
        total_fresh = 0
        full_window_per_object = {oid: 0 for oid in object_ids}
        for year, lower, upper in years:
            counts = per_threshold_year_object.get(threshold, {}).get(year, {})
            fresh = sum(counts.values())
            total_fresh += fresh
            for oid, value in counts.items():
                full_window_per_object[oid] += value
            denominator = object_count * year_slots[year]
            year_summary.append({
                "year": year,
                "fresh_source_slots": fresh,
                "scheduled_slots": denominator,
                "fresh_fraction": fresh / denominator if denominator else None,
            })
        per_object = [value / total_samples for value in full_window_per_object.values()]
        results.append({
            "max_element_age_hours": threshold,
            "fresh_source_slots": total_fresh,
            "scheduled_slots": total_scheduled,
            "fresh_fraction": total_fresh / total_scheduled,
            "fresh_fraction_object_distribution": quantiles(per_object),
            "objects_with_any_fresh_sample": sum(value > 0 for value in full_window_per_object.values()),
            "objects_fully_fresh_for_entire_window": sum(value == total_samples for value in full_window_per_object.values()),
            "by_year": year_summary,
        })
    base = next((row for row in results if row["max_element_age_hours"] == trajectory_manifest["max_age_hours"]), None)
    reference_fresh = trajectory_validation["successful"] + trajectory_validation["sgp4_errors"]
    if base is None:
        raise ValueError("Threshold list must include the validated baseline max element age")
    if base["fresh_source_slots"] != reference_fresh:
        raise AssertionError(
            f"72-hour freshness count {base['fresh_source_slots']:,} differs from validated export "
            f"non-stale slots {reference_fresh:,}; source deduplication/grid semantics need review")
    baseline_slots = base["fresh_source_slots"]
    for row in results:
        row["additional_fresh_slots_vs_validated_baseline"] = row["fresh_source_slots"] - baseline_slots
        row["additional_fraction_of_full_grid_vs_baseline"] = (
            row["additional_fresh_slots_vs_validated_baseline"] / total_scheduled)

    report = {
        "status": "completed",
        "analysis": "Historical catalog source-element age sensitivity on the validated four-hour UTC grid",
        "source_revision": source_revision(root),
        "source_files": [str(path.relative_to(root)) for path in raw_paths],
        "source_lower_bound_inclusive": lower_source.isoformat(),
        "start_inclusive": start.isoformat(),
        "end_exclusive": end.isoformat(),
        "step_seconds": step_seconds,
        "object_count": object_count,
        "scheduled_rows": total_scheduled,
        "baseline_max_element_age_hours": trajectory_manifest["max_age_hours"],
        "baseline_export_signature": trajectory_manifest["signature"],
        "baseline_validation_signature": trajectory_validation["signature"],
        "source_freshness_counts_match_validated_baseline": True,
        "thresholds": results,
        "interpretation_limits": [
            "Fresh-source counts mean a historical element epoch is at or before a grid sample and no older than the chosen cutoff.",
            "This audit does not propagate or validate SGP4 states beyond the current 72-hour cutoff; additional slots are sensitivity counts only.",
            "Long-age propagation omits updated orbit-determination solutions, maneuvers, and unmodeled perturbations; do not equate the added counts with accurate trajectories.",
            "The global per-object freshness distribution includes objects with no in-window source and is not an operational satellite-status cohort.",
        ],
    }
    output = pathlib.Path(output or root / "outputs/catalog-freshness-sensitivity-2022-2026.json").resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--output", default=str(ROOT / "outputs/catalog-freshness-sensitivity-2022-2026.json"))
    parser.add_argument("--start", default=DEFAULT_START)
    parser.add_argument("--end", default=DEFAULT_END)
    parser.add_argument("--step-seconds", type=int, default=14400)
    parser.add_argument("--thresholds-hours", type=int, nargs="+", default=list(DEFAULT_THRESHOLDS))
    parser.add_argument("--memory-limit", default="3GB")
    args = parser.parse_args()
    result = analyze(args.root, args.output, args.start, args.end,
                     args.step_seconds, args.thresholds_hours, args.memory_limit)
    print(json.dumps({
        "status": result["status"], "objects": result["object_count"],
        "scheduled_rows": result["scheduled_rows"],
        "thresholds": [{key: row[key] for key in (
            "max_element_age_hours", "fresh_source_slots", "fresh_fraction",
            "additional_fresh_slots_vs_validated_baseline")}
            for row in result["thresholds"]],
        "output": args.output,
    }, indent=2))


if __name__ == "__main__":
    main()
