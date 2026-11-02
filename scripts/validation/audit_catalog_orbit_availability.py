"""Classify the complete four-year trajectory grid by catalog lifecycle and SGP4 status.

This prevents pre-launch and post-decay grid slots from being reported as sensor-
usable state coverage. SATCAT lifecycle dates are calendar-day metadata, so the
classification is approximate at each object's launch/decay day.
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

import duckdb

from godsat.orbits import ROOT


def classify_lifecycle(when: dt.datetime, launch: dt.date | None,
                       decay: dt.date | None, catalog_matched: bool = True) -> str:
    """Classify a UTC sample without implying operational spacecraft status."""
    if not catalog_matched or launch is None:
        return "lifecycle_unknown"
    day = when.date()
    if day < launch:
        return "before_launch"
    if decay is not None and day > decay:
        return "after_decay"
    return "catalog_lifetime_estimate"


def audit(root: pathlib.Path = ROOT, output: pathlib.Path | None = None,
          memory_limit: str = "3GB") -> dict:
    root = pathlib.Path(root).resolve()
    traj_dir = root / "outputs/catalog-trajectory-all-4hour-2022-2026"
    manifest_path = traj_dir / "manifest.json"
    validation_path = traj_dir / "validation.json"
    manifest = json.loads(manifest_path.read_text())
    validation = json.loads(validation_path.read_text())
    if manifest.get("status") != "completed" or validation.get("status") != "validated_complete":
        raise RuntimeError("The reference catalog trajectory export is not independently validated")

    satcat_path = root / "data/raw/satcat.csv"
    parts_glob = (traj_dir / "part-*.parquet").as_posix()
    db = duckdb.connect()
    try:
        db.execute("SET TimeZone='UTC'")
        db.execute("SET threads=2")
        db.execute(f"SET memory_limit='{memory_limit}'")
        db.execute("SET preserve_insertion_order=false")
        db.execute("SET temp_directory='/tmp/godsat-lifecycle-audit-duckdb'")
        query = f"""
            WITH satcat AS (
                SELECT
                    try_cast(NORAD_CAT_ID AS INTEGER) AS norad_id,
                    nullif(trim(OBJECT_TYPE), '') AS object_type,
                    try_cast(nullif(trim(LAUNCH_DATE), '') AS DATE) AS launch_date,
                    try_cast(nullif(trim(DECAY_DATE), '') AS DATE) AS decay_date
                FROM read_csv('{satcat_path.as_posix()}', header=true, all_varchar=true)
            ), satcat_audit AS (
                SELECT count(*) AS rows,
                       count(DISTINCT norad_id) AS unique_ids,
                       count(*) FILTER (WHERE norad_id IS NULL) AS invalid_ids
                FROM satcat
            ), trajectories AS (
                SELECT
                    norad_id,
                    cast(time_utc AS TIMESTAMPTZ) AS sample_time,
                    orbit_regime,
                    sgp4_error
                FROM read_parquet('{parts_glob}')
            ), classified AS (
                SELECT
                    t.*,
                    coalesce(s.object_type, 'UNMATCHED') AS object_type,
                    CASE
                        WHEN s.norad_id IS NULL OR s.launch_date IS NULL THEN 'lifecycle_unknown'
                        WHEN cast(t.sample_time AS DATE) < s.launch_date THEN 'before_launch'
                        WHEN s.decay_date IS NOT NULL
                             AND cast(t.sample_time AS DATE) > s.decay_date THEN 'after_decay'
                        ELSE 'catalog_lifetime_estimate'
                    END AS lifecycle,
                    CASE
                        WHEN t.sgp4_error = -1 THEN 'stale_or_missing_element'
                        WHEN t.sgp4_error = 0 THEN 'propagated'
                        ELSE 'sgp4_error'
                    END AS state_status
                FROM trajectories t
                LEFT JOIN satcat s USING (norad_id)
            )
            SELECT
                (SELECT rows FROM satcat_audit) AS satcat_rows,
                (SELECT unique_ids FROM satcat_audit) AS satcat_unique_ids,
                (SELECT invalid_ids FROM satcat_audit) AS satcat_invalid_ids,
                count(*) AS trajectory_rows,
                count(DISTINCT norad_id) AS trajectory_ids,
                count(*) FILTER (WHERE lifecycle='before_launch') AS before_launch_rows,
                count(*) FILTER (WHERE lifecycle='after_decay') AS after_decay_rows,
                count(*) FILTER (WHERE lifecycle='catalog_lifetime_estimate') AS catalog_lifetime_rows,
                count(*) FILTER (WHERE lifecycle='lifecycle_unknown') AS lifecycle_unknown_rows,
                count(*) FILTER (WHERE lifecycle='catalog_lifetime_estimate' AND state_status='propagated') AS lifetime_propagated_rows,
                count(*) FILTER (WHERE lifecycle='catalog_lifetime_estimate' AND state_status='stale_or_missing_element') AS lifetime_stale_or_missing_rows,
                count(*) FILTER (WHERE lifecycle='catalog_lifetime_estimate' AND state_status='sgp4_error') AS lifetime_sgp4_error_rows,
                count(*) FILTER (WHERE lifecycle='lifecycle_unknown' AND state_status='propagated') AS unknown_lifecycle_propagated_rows,
                count(*) FILTER (WHERE lifecycle='lifecycle_unknown' AND state_status='stale_or_missing_element') AS unknown_lifecycle_stale_or_missing_rows,
                count(*) FILTER (WHERE lifecycle='lifecycle_unknown' AND state_status='sgp4_error') AS unknown_lifecycle_sgp4_error_rows
            FROM classified
        """
        totals_row = db.execute(query).fetchone()
        totals = dict(zip([item[0] for item in db.description], totals_row))
        grouped_query = f"""
            WITH satcat AS (
                SELECT try_cast(NORAD_CAT_ID AS INTEGER) AS norad_id,
                       coalesce(nullif(trim(OBJECT_TYPE), ''), 'UNK') AS object_type,
                       try_cast(nullif(trim(LAUNCH_DATE), '') AS DATE) AS launch_date,
                       try_cast(nullif(trim(DECAY_DATE), '') AS DATE) AS decay_date
                FROM read_csv('{satcat_path.as_posix()}', header=true, all_varchar=true)
            ), classified AS (
                SELECT t.norad_id, t.orbit_regime, t.sgp4_error,
                       extract(year FROM cast(t.time_utc AS TIMESTAMPTZ))::INTEGER AS year,
                       coalesce(s.object_type, 'UNMATCHED') AS object_type,
                       CASE
                         WHEN s.norad_id IS NULL OR s.launch_date IS NULL THEN 'lifecycle_unknown'
                         WHEN cast(t.time_utc AS TIMESTAMPTZ)::DATE < s.launch_date THEN 'before_launch'
                         WHEN s.decay_date IS NOT NULL
                              AND cast(t.time_utc AS TIMESTAMPTZ)::DATE > s.decay_date THEN 'after_decay'
                         ELSE 'catalog_lifetime_estimate'
                       END AS lifecycle,
                       CASE WHEN t.sgp4_error=-1 THEN 'stale_or_missing_element'
                            WHEN t.sgp4_error=0 THEN 'propagated'
                            ELSE 'sgp4_error' END AS state_status
                FROM read_parquet('{parts_glob}') t
                LEFT JOIN satcat s USING (norad_id)
            )
            SELECT year, object_type, orbit_regime, lifecycle, state_status,
                   count(*) AS rows
            FROM classified
            GROUP BY ALL
            ORDER BY year, object_type, orbit_regime, lifecycle, state_status
        """
        grouped = [dict(zip([item[0] for item in db.description], row))
                   for row in db.execute(grouped_query).fetchall()]
    finally:
        db.close()

    expected_rows = int(manifest["projected_rows"])
    if int(totals["trajectory_rows"]) != expected_rows:
        raise AssertionError(f"Classified {totals['trajectory_rows']:,} rows; expected {expected_rows:,}")
    if int(totals["trajectory_ids"]) != int(manifest["object_count"]):
        raise AssertionError("Trajectory object count differs from validated manifest")
    if int(totals["satcat_invalid_ids"]):
        raise AssertionError("SATCAT contains rows with invalid NORAD catalog identifiers")
    if int(totals["satcat_rows"]) != int(totals["satcat_unique_ids"]):
        raise AssertionError("SATCAT has duplicate NORAD catalog identifiers")
    status_totals = {key: sum(int(row["rows"]) for row in grouped
                              if row["state_status"] == key)
                     for key in ("propagated", "stale_or_missing_element", "sgp4_error")}
    lifecycle_totals = {key: sum(int(row["rows"]) for row in grouped
                                  if row["lifecycle"] == key)
                        for key in ("before_launch", "after_decay",
                                    "catalog_lifetime_estimate", "lifecycle_unknown")}
    expected_status_totals = {
        "propagated": int(validation["successful"]),
        "stale_or_missing_element": int(validation["stale_or_missing"]),
        "sgp4_error": int(validation["sgp4_errors"]),
    }
    if status_totals != expected_status_totals:
        raise AssertionError(f"State-status counts differ from trajectory validation: {status_totals}")
    if sum(lifecycle_totals.values()) != expected_rows:
        raise AssertionError("Lifecycle groups do not reconcile to the trajectory grid")
    if (int(totals["lifetime_propagated_rows"])
            + int(totals["lifetime_stale_or_missing_rows"])
            + int(totals["lifetime_sgp4_error_rows"])
            + int(totals["unknown_lifecycle_propagated_rows"])
            + int(totals["unknown_lifecycle_stale_or_missing_rows"])
            + int(totals["unknown_lifecycle_sgp4_error_rows"])
            + int(totals["before_launch_rows"])
            + int(totals["after_decay_rows"]) != expected_rows):
        raise AssertionError("Lifecycle/status partitions do not reconcile to the trajectory grid")

    report = {
        "status": "completed_valid",
        "audited_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "trajectory_source": "independently validated four-year all-catalog SGP4 export",
        "trajectory_signature": manifest["signature"],
        "trajectory_validation_signature": validation["signature"],
        "grid": {key: manifest[key] for key in (
            "start", "end_exclusive", "step_seconds", "object_count", "projected_rows",
            "max_age_hours", "source_revision")},
        "totals": totals,
        "status_totals": status_totals,
        "lifecycle_totals": lifecycle_totals,
        "groups": grouped,
        "lifecycle_method": (
            "Each grid sample is classified using CelesTrak SATCAT launch and decay calendar dates. "
            "The decay date is treated as inclusive through that UTC calendar day; unknown launch dates "
            "and absent SATCAT rows stay in lifecycle_unknown. This is a catalog-recorded lifetime "
            "approximation, not proof of operational status or physical presence at a precise time."
        ),
        "state_status_method": (
            "The saved export's sgp4_error value is retained: 0 means propagated, -1 means no element "
            "within the 72-hour cutoff, and positive values are SGP4 propagation errors. Stale and "
            "no-prior-element cases remain combined because the export did not retain that distinction."
        ),
    }
    output = pathlib.Path(output or root / "outputs/catalog-orbit-availability-audit.json").resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_suffix(output.suffix + ".tmp")
    temp.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    temp.replace(output)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=pathlib.Path, default=ROOT)
    parser.add_argument("--output", type=pathlib.Path)
    parser.add_argument("--memory-limit", default="3GB")
    args = parser.parse_args()
    report = audit(args.root, args.output, args.memory_limit)
    print(json.dumps({"status": report["status"], "totals": report["totals"],
                      "output": str(args.output or args.root / "outputs/catalog-orbit-availability-audit.json")},
                     indent=2))


if __name__ == "__main__":
    main()
