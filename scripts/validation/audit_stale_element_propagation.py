"""Measure long-gap SGP4 disagreement against the next historical element set.

For every adjacent historical element pair with a 3-30 day gap overlapping the
study period, propagate the older set to the newer set's epoch and compare the
result with the newer set evaluated at its own epoch. This is an inter-element
consistency diagnostic, not independent orbit truth or a maneuver classifier.
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
import pathlib

import duckdb
import numpy as np

from godsat.orbits import ROOT, julian, orbit_regime, satellite, utc
from godsat.trajectory import source_revision


ELEMENT_FIELDS = (
    "inclination", "raan", "eccentricity", "arg_perigee", "mean_anomaly",
    "mean_motion", "mean_motion_dot", "bstar",
)
FIELDS = ("norad_id", "epoch", *ELEMENT_FIELDS)
CSV_FIELDS = (
    "norad_id", "orbit_regime", "old_epoch_utc", "new_epoch_utc",
    "gap_hours", "old_prediction_sgp4_error", "new_epoch_sgp4_error",
    "position_disagreement_km", "velocity_disagreement_km_s",
)
START = "2022-10-09T00:00:00Z"
END = "2026-10-10T00:00:00Z"
AGE_BINS = ((72, 168, "3_to_7_days"), (168, 336, "7_to_14_days"),
            (336, 720, "14_to_30_days"))


def query_intervals(root, start, end, memory_limit="5GB"):
    raw = pathlib.Path(root) / "data/raw"
    paths = sorted(raw.glob("tle_*.parquet"))
    if len(paths) != 5:
        raise FileNotFoundError(f"Expected five annual source files, found {len(paths)}")
    columns = ", ".join(FIELDS)
    order = ", ".join(ELEMENT_FIELDS)
    sql_template = """
        WITH ranked AS (
            SELECT {columns},
                   row_number() OVER (PARTITION BY norad_id, epoch ORDER BY {order}) AS rn
            FROM read_parquet({paths_sql})
            WHERE epoch >= CAST(? AS TIMESTAMPTZ)
              AND epoch < CAST(? AS TIMESTAMPTZ)
        ), unique_epochs AS (
            SELECT {columns} FROM ranked WHERE rn = 1
        ), adjacent AS (
            SELECT *, lead(epoch) OVER (PARTITION BY norad_id ORDER BY epoch) AS next_epoch,
                   lead(inclination) OVER (PARTITION BY norad_id ORDER BY epoch) AS next_inclination,
                   lead(raan) OVER (PARTITION BY norad_id ORDER BY epoch) AS next_raan,
                   lead(eccentricity) OVER (PARTITION BY norad_id ORDER BY epoch) AS next_eccentricity,
                   lead(arg_perigee) OVER (PARTITION BY norad_id ORDER BY epoch) AS next_arg_perigee,
                   lead(mean_anomaly) OVER (PARTITION BY norad_id ORDER BY epoch) AS next_mean_anomaly,
                   lead(mean_motion) OVER (PARTITION BY norad_id ORDER BY epoch) AS next_mean_motion,
                   lead(mean_motion_dot) OVER (PARTITION BY norad_id ORDER BY epoch) AS next_mean_motion_dot,
                   lead(bstar) OVER (PARTITION BY norad_id ORDER BY epoch) AS next_bstar
            FROM unique_epochs
        )
        SELECT {columns}, next_epoch, next_inclination, next_raan, next_eccentricity,
               next_arg_perigee, next_mean_anomaly, next_mean_motion,
               next_mean_motion_dot, next_bstar
        FROM adjacent
        WHERE epoch >= CAST(? AS TIMESTAMPTZ)
          AND epoch < CAST(? AS TIMESTAMPTZ)
          AND next_epoch > CAST(? AS TIMESTAMPTZ)
          AND next_epoch < CAST(? AS TIMESTAMPTZ)
          AND next_epoch IS NOT NULL
          AND date_diff('microseconds', epoch, next_epoch) > 259200000000
          AND date_diff('microseconds', epoch, next_epoch) <= 2592000000000
        ORDER BY norad_id, epoch
    """
    db = duckdb.connect()
    all_rows = []
    try:
        db.execute("SET TimeZone='UTC'")
        db.execute("SET threads=2")
        db.execute(f"SET memory_limit='{memory_limit}'")
        db.execute("SET preserve_insertion_order=false")
        db.execute("SET temp_directory='/tmp/godsat-stale-propagation-duckdb'")
        lower = start - dt.timedelta(hours=720)
        cursor_year = lower.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        while cursor_year < end:
            next_year = cursor_year.replace(year=cursor_year.year + 1)
            slice_start = max(cursor_year, lower)
            slice_end = min(next_year, end)
            source_end = min(slice_end + dt.timedelta(hours=720), end)
            source_years = range(slice_start.year, (source_end - dt.timedelta(microseconds=1)).year + 1)
            year_paths = [raw / f"tle_{year}.parquet" for year in source_years]
            missing = [str(path) for path in year_paths if not path.is_file()]
            if missing:
                raise FileNotFoundError(f"Missing source files for interval batch: {missing}")
            paths_sql = "[" + ",".join("'" + str(p).replace("'", "''") + "'" for p in year_paths) + "]"
            sql = sql_template.format(columns=columns, order=order, paths_sql=paths_sql)
            batch = db.execute(sql, [slice_start.isoformat(), source_end.isoformat(),
                slice_start.isoformat(), slice_end.isoformat(), start.isoformat(),
                end.isoformat()]).fetchall()
            all_rows.extend(batch)
            cursor_year = next_year
        return paths, all_rows
    finally:
        db.close()


def summarize(values):
    values = np.asarray(values, dtype=float)
    if not len(values):
        return {"n": 0}
    return {
        "n": int(len(values)), "median": float(np.median(values)),
        "p90": float(np.quantile(values, .90)), "p95": float(np.quantile(values, .95)),
        "p99": float(np.quantile(values, .99)), "max": float(np.max(values)),
        "mean": float(np.mean(values)),
    }


def run(output=None, root=ROOT, start=START, end=END, memory_limit="5GB"):
    root, start, end = pathlib.Path(root).resolve(), utc(start), utc(end)
    paths, pairs = query_intervals(root, start, end, memory_limit)
    out = pathlib.Path(output or root / "outputs/stale-element-propagation-audit-2022-2026").resolve()
    out.mkdir(parents=True, exist_ok=True)
    csv_path = out / "adjacent_element_disagreement.csv"
    grouped = {}
    counts = {"all": 0, "sgp4_valid": 0, "sgp4_errors": 0}
    with csv_path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for record in pairs:
            norad_id, old_epoch = int(record[0]), record[1]
            old = {"norad_id": norad_id, "epoch": old_epoch,
                   **{name: float(record[i]) for i, name in enumerate(ELEMENT_FIELDS, 2)}}
            new_epoch = record[10]
            new = {"norad_id": norad_id, "epoch": new_epoch,
                   **{name: float(record[i]) for i, name in enumerate(ELEMENT_FIELDS, 11)}}
            age = (new_epoch - old_epoch).total_seconds() / 3600
            regime = orbit_regime(old)
            old_sat, new_sat = satellite(old), satellite(new)
            error_old, pos_old, vel_old = old_sat.sgp4(*julian(new_epoch))
            error_new, pos_new, vel_new = new_sat.sgp4(*julian(new_epoch))
            valid = error_old == 0 and error_new == 0 and np.isfinite(
                np.r_[pos_old, vel_old, pos_new, vel_new]).all()
            pos_delta = float(np.linalg.norm(np.asarray(pos_old) - pos_new)) if valid else None
            vel_delta = float(np.linalg.norm(np.asarray(vel_old) - vel_new)) if valid else None
            bucket = next((label for lo, hi, label in AGE_BINS if lo < age <= hi), "other")
            key = (regime, bucket)
            acc = grouped.setdefault(key, {"position": [], "velocity": [], "n": 0,
                                           "sgp4_errors": 0, "over_1km": 0,
                                           "over_10km": 0, "over_100km": 0})
            counts["all"] += 1
            acc["n"] += 1
            if valid:
                counts["sgp4_valid"] += 1
                acc["position"].append(pos_delta)
                acc["velocity"].append(vel_delta)
                for threshold, name in ((1, "over_1km"), (10, "over_10km"), (100, "over_100km")):
                    if pos_delta > threshold:
                        acc[name] += 1
            else:
                counts["sgp4_errors"] += 1
                acc["sgp4_errors"] += 1
            writer.writerow({
                "norad_id": norad_id, "orbit_regime": regime,
                "old_epoch_utc": old_epoch.isoformat(), "new_epoch_utc": new_epoch.isoformat(),
                "gap_hours": age, "old_prediction_sgp4_error": int(error_old),
                "new_epoch_sgp4_error": int(error_new),
                "position_disagreement_km": pos_delta,
                "velocity_disagreement_km_s": vel_delta,
            })
    csv_hash = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    summary = []
    for (regime, age_bin), acc in sorted(grouped.items()):
        n_valid = len(acc["position"])
        summary.append({
            "orbit_regime": regime, "gap_bin": age_bin, "n_intervals": acc["n"],
            "n_valid": n_valid, "sgp4_errors": acc["sgp4_errors"],
            "position_disagreement_km": summarize(acc["position"]),
            "velocity_disagreement_km_s": summarize(acc["velocity"]),
            "fraction_over_1km": acc["over_1km"] / n_valid if n_valid else None,
            "fraction_over_10km": acc["over_10km"] / n_valid if n_valid else None,
            "fraction_over_100km": acc["over_100km"] / n_valid if n_valid else None,
        })
    source_manifest = root / "data/raw/manifest.json"
    report = {
        "status": "completed", "analysis": "SGP4 propagation from older element to next catalog element epoch",
        "comparison_period_start_inclusive": start.isoformat(),
        "comparison_period_end_exclusive": end.isoformat(),
        "gap_range_hours": [72, 720], "all_candidate_intervals": counts["all"],
        "valid_comparisons": counts["sgp4_valid"], "sgp4_error_comparisons": counts["sgp4_errors"],
        "source_revision": source_revision(root),
        "source_manifest_sha256": hashlib.sha256(source_manifest.read_bytes()).hexdigest(),
        "source_files": [str(path.relative_to(root)) for path in paths],
        "deduplication": "one row per NORAD ID and epoch; ascending element-field tie-break, matching History.records ordering",
        "comparison_frame": "TEME at the later element epoch",
        "groups": summary, "csv": csv_path.name, "csv_sha256": csv_hash,
        "output_directory": str(out),
        "interpretation_limits": [
            "The later catalog element is a second estimated solution, not independent truth or a precision ephemeris.",
            "Disagreement measures consistency across element updates and can reflect maneuvers, estimation changes, reduced source precision, or model error.",
            "Intervals without a subsequent update cannot be assessed by this method and are excluded.",
            "Older-element states remain unsuitable for operational tasking or collision avoidance without independent orbit determination and covariance.",
        ],
    }
    (out / "summary.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--output", default=None)
    parser.add_argument("--start", default=START)
    parser.add_argument("--end", default=END)
    parser.add_argument("--memory-limit", default="5GB")
    args = parser.parse_args()
    report = run(args.output, args.root, args.start, args.end, args.memory_limit)
    print(json.dumps({"status": report["status"], "candidate_intervals": report["all_candidate_intervals"],
                      "valid_comparisons": report["valid_comparisons"],
                      "groups": report["groups"], "output": report["output_directory"]}, indent=2))


if __name__ == "__main__":
    main()
