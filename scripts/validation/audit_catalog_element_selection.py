"""Reconcile every fresh catalog trajectory row to the latest raw element epoch.

The existing catalog audit validates every grid row and part checksum, but only
samples source-element reproduction. This bounded-memory audit independently
checks the latest-at-or-before source epoch and freshness classification for the
entire four-hour trajectory grid. It does not recompute every SGP4 state vector.
"""
from __future__ import annotations

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))


import argparse
import datetime as dt
import json
import pathlib
import sys

import duckdb

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from godsat.catalog_trajectory import catalog_object_ids, manifest_signature
from godsat.orbits import ROOT, utc
from godsat.trajectory import source_revision


def month_bounds(value: dt.datetime) -> tuple[dt.datetime, dt.datetime]:
    start = value.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


def audit(root: pathlib.Path = ROOT, output: pathlib.Path | None = None,
          memory_limit: str = "1GB", threads: int = 2) -> dict:
    root = pathlib.Path(root).resolve()
    trajectory = root / "outputs/catalog-trajectory-all-4hour-2022-2026"
    manifest = json.loads((trajectory / "manifest.json").read_text())
    validation = json.loads((trajectory / "validation.json").read_text())
    if manifest.get("status") != "completed" or validation.get("status") != "validated_complete":
        raise RuntimeError("Full trajectory export and structural validation are required")
    if manifest.get("signature") != validation.get("signature"):
        raise RuntimeError("Trajectory validation signature does not match the export")
    if source_revision(root) != manifest.get("source_revision"):
        raise RuntimeError("Raw source manifest revision differs from the trajectory export")

    start, end = utc(manifest["start"]), utc(manifest["end_exclusive"])
    age_limit = float(manifest["max_age_hours"])
    ids = catalog_object_ids(root, start, end, age_limit)
    signature, _ = manifest_signature(start, end, manifest["step_seconds"], age_limit,
                                      manifest["source_revision"], ids)
    if signature != manifest.get("signature") or len(ids) != manifest.get("object_count"):
        raise RuntimeError("Trajectory catalog cohort does not match its export signature")

    parts = manifest["parts"]
    raw_glob = (root / "data/raw/tle_*.parquet").as_posix()
    database = duckdb.connect()
    database.execute(f"SET threads={int(threads)}")
    database.execute(f"SET memory_limit='{memory_limit}'")
    database.execute("SET preserve_insertion_order=false")
    database.execute("SET TimeZone='UTC'")
    database.execute("SET temp_directory='/tmp/godsat-catalog-element-selection-audit'")

    monthly_results = []
    total_rows = fresh_rows = stale_rows = 0
    total_status_mismatches = epoch_mismatches = age_mismatches = 0
    max_age_difference_hours = 0.0
    try:
        cursor = start
        while cursor < end:
            month_start, month_end = month_bounds(cursor)
            lower, upper = max(month_start, start), min(month_end, end)
            month_parts = [part for part in parts
                           if lower <= utc(part["start_inclusive"]) < upper]
            if not month_parts:
                cursor = month_end
                continue
            expected_month_rows = sum(int(part["rows"]) for part in month_parts)
            paths = [str(trajectory / part["file"]) for part in month_parts]
            sql = f"""
                WITH source_epochs AS (
                    SELECT DISTINCT norad_id, epoch
                    FROM read_parquet('{raw_glob}')
                    WHERE epoch >= TIMESTAMPTZ '{lower.isoformat()}' - INTERVAL '{age_limit} hours'
                      AND epoch <= TIMESTAMPTZ '{upper.isoformat()}'
                ), trajectory_rows AS (
                    SELECT *, CAST(time_utc AS TIMESTAMPTZ) AS sample_time
                    FROM read_parquet(?)
                ), matched AS (
                    SELECT t.norad_id, t.sample_time, t.element_epoch,
                           t.element_age_hours, t.sgp4_error, s.epoch AS source_epoch,
                           CASE WHEN s.epoch IS NOT NULL
                                  AND s.epoch >= t.sample_time - INTERVAL '{age_limit} hours'
                                THEN TRUE ELSE FALSE END AS has_fresh_source
                    FROM trajectory_rows t
                    ASOF LEFT JOIN source_epochs s
                      ON t.norad_id = s.norad_id AND t.sample_time >= s.epoch
                )
                SELECT count(*) AS rows_checked,
                       sum(CASE WHEN has_fresh_source THEN 1 ELSE 0 END) AS fresh_rows,
                       sum(CASE WHEN NOT has_fresh_source THEN 1 ELSE 0 END) AS stale_rows,
                       sum(CASE WHEN has_fresh_source AND sgp4_error = -1
                                     OR NOT has_fresh_source AND sgp4_error <> -1
                                THEN 1 ELSE 0 END) AS status_mismatches,
                       sum(CASE WHEN has_fresh_source AND
                                     CAST(element_epoch AS TIMESTAMPTZ) IS DISTINCT FROM source_epoch
                                THEN 1 ELSE 0 END) AS epoch_mismatches,
                       sum(CASE WHEN has_fresh_source AND
                                     abs(element_age_hours -
                                         date_diff('microsecond', source_epoch, sample_time) / 3600000000.0) > 1e-9
                                THEN 1 ELSE 0 END) AS age_mismatches,
                       max(CASE WHEN has_fresh_source THEN abs(element_age_hours -
                           date_diff('microsecond', source_epoch, sample_time) / 3600000000.0)
                           ELSE 0 END) AS max_age_difference_hours
                FROM matched
            """
            row = database.execute(sql, [paths]).fetchone()
            checked, fresh, stale, bad_status, bad_epoch, bad_age, max_age_delta = row
            checked, fresh, stale = int(checked), int(fresh or 0), int(stale or 0)
            if checked != expected_month_rows or fresh + stale != checked:
                raise AssertionError(f"Monthly row totals do not reconcile for {lower:%Y-%m}")
            if bad_status or bad_epoch or bad_age:
                raise AssertionError(
                    f"Source-element mismatch for {lower:%Y-%m}: status={bad_status}, "
                    f"epoch={bad_epoch}, age={bad_age}")
            monthly_results.append({
                "month": lower.strftime("%Y-%m"), "trajectory_parts": len(month_parts),
                "rows_checked": checked, "fresh_source_rows": fresh,
                "stale_or_missing_source_rows": stale,
                "status_mismatches": int(bad_status or 0),
                "selected_epoch_mismatches": int(bad_epoch or 0),
                "element_age_mismatches": int(bad_age or 0),
                "max_element_age_delta_hours": float(max_age_delta or 0.0),
            })
            total_rows += checked
            fresh_rows += fresh
            stale_rows += stale
            total_status_mismatches += int(bad_status or 0)
            epoch_mismatches += int(bad_epoch or 0)
            age_mismatches += int(bad_age or 0)
            max_age_difference_hours = max(max_age_difference_hours, float(max_age_delta or 0.0))
            print(f"{lower:%Y-%m}: reconciled {checked:,} rows", flush=True)
            cursor = month_end
    finally:
        database.close()

    if total_rows != int(manifest["projected_rows"]):
        raise AssertionError("Raw-source reconciliation did not cover the full trajectory grid")
    if fresh_rows != int(validation["successful"]) + int(validation["sgp4_errors"]):
        raise AssertionError("Fresh raw-source rows differ from validated success plus SGP4 errors")
    if stale_rows != int(validation["stale_or_missing"]):
        raise AssertionError("Stale raw-source rows differ from validated stale/missing count")

    report = {
        "status": "validated_complete_source_epoch_selection",
        "scope": "All scheduled catalog trajectory rows reconciled to the latest raw NORAD orbital-element epoch at or before sample time; freshness status and age also checked. State vectors are not recomputed for every row.",
        "trajectory_signature": manifest["signature"],
        "validation_signature": validation["signature"],
        "source_revision": manifest["source_revision"],
        "start_inclusive": manifest["start"], "end_exclusive": manifest["end_exclusive"],
        "step_seconds": manifest["step_seconds"], "max_element_age_hours": age_limit,
        "object_count": int(manifest["object_count"]),
        "rows_checked": total_rows, "fresh_source_rows": fresh_rows,
        "stale_or_missing_source_rows": stale_rows,
        "status_mismatches": total_status_mismatches,
        "selected_epoch_mismatches": epoch_mismatches,
        "element_age_mismatches": age_mismatches,
        "max_element_age_delta_hours": max_age_difference_hours,
        "duplicate_epoch_rule": "For source-epoch selection, duplicate raw rows at one NORAD ID and epoch collapse to the same epoch; the existing sampled SGP4 reproduction audit separately checks state values and deterministic orbital-element tie ordering.",
        "monthly_results": monthly_results,
        "limitations": [
            "This proves latest-source epoch selection and freshness classification for every scheduled row, not exact SGP4 vector reproduction for every successful row.",
            "TLE/GP source coverage is incomplete and states remain reconstructed SGP4 estimates.",
            "Rows stale or missing under the 72-hour rule remain explicitly invalid; older elements are not promoted to validated states.",
        ],
    }
    target = pathlib.Path(output or trajectory / "source-element-selection-audit.json")
    if not target.is_absolute():
        target = root / target
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(target.suffix + ".tmp")
    temp.write_text(json.dumps(report, indent=2) + "\n")
    temp.replace(target)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=pathlib.Path, default=ROOT)
    parser.add_argument("--output", type=pathlib.Path)
    parser.add_argument("--memory-limit", default="1GB")
    parser.add_argument("--threads", type=int, default=2)
    args = parser.parse_args()
    report = audit(args.root, args.output, args.memory_limit, args.threads)
    print(json.dumps({key: report[key] for key in (
        "status", "rows_checked", "fresh_source_rows", "stale_or_missing_source_rows",
        "selected_epoch_mismatches", "output") if key in report}, indent=2))


if __name__ == "__main__":
    main()
