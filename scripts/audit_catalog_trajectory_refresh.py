#!/usr/bin/env python3
"""Independently reconcile the final-interval orbit refresh to its source and baseline."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path

import duckdb
import pyarrow.parquet as pq

from godsat.orbits import ROOT, satellite, utc
from godsat.trajectory import julian


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def audit(output: Path | None = None) -> dict:
    output = output or ROOT / "outputs/catalog-trajectory-source-refresh-2026-10-08-10"
    manifest = json.loads((output / "manifest.json").read_text())
    source = ROOT / manifest["source_file"]
    part = output / manifest["part"]["file"]
    if sha256(source) != manifest["source_file_sha256"]:
        raise ValueError("Refreshed source snapshot checksum mismatch")
    if sha256(part) != manifest["part"]["sha256"]:
        raise ValueError("Refreshed trajectory part checksum mismatch")
    source_pf = pq.ParquetFile(source)
    source_rows = source_pf.metadata.num_rows
    if source_rows != 19_308_845:
        raise ValueError(f"Unexpected refreshed source row count: {source_rows}")
    con = duckdb.connect()
    source_bounds = con.execute("select min(epoch), max(epoch), count(distinct norad_id) from read_parquet(?)",
                                [str(source)]).fetchone()
    if utc(source_bounds[1]).isoformat() != "2026-10-09T23:59:54.957696+00:00":
        raise ValueError(f"Unexpected source endpoint: {source_bounds[1]}")
    part_rows = pq.ParquetFile(part).metadata.num_rows
    if part_rows != manifest["rows"] or part_rows != manifest["objects"] * len(manifest["sample_times_utc"]):
        raise ValueError("Refresh row count does not equal object/date cross product")
    actual_counts = con.execute("""select
        count(*) filter(where sgp4_error=0),
        count(*) filter(where sgp4_error>0),
        count(*) filter(where sgp4_error=-1),
        count(*) filter(where element_epoch is null),
        count(*) filter(where sgp4_error=-1 and x_teme_km is not null),
        count(*) filter(where sgp4_error=0 and (x_teme_km is null or y_teme_km is null or z_teme_km is null
          or vx_teme_km_s is null or vy_teme_km_s is null or vz_teme_km_s is null)),
        count(distinct norad_id), count(distinct time_utc), count(distinct (norad_id,time_utc))
        from read_parquet(?)""", [str(part)]).fetchone()
    count_names = ("successful", "sgp4_errors", "stale_or_missing", "null_element_epoch",
                   "stale_rows_with_state", "successful_rows_with_null_state", "objects", "sample_times", "unique_rows")
    actual = dict(zip(count_names, map(int, actual_counts)))
    if actual["objects"] != manifest["objects"] or actual["sample_times"] != len(manifest["sample_times_utc"]):
        raise ValueError("Refresh does not cover the declared object/time axes")
    if actual["unique_rows"] != part_rows or actual["stale_rows_with_state"] or actual["successful_rows_with_null_state"]:
        raise ValueError("Refresh has duplicate keys or inconsistent state/null semantics")
    if actual["successful"] != manifest["status_counts"]["successful"] or actual["sgp4_errors"] != manifest["status_counts"]["sgp4_errors"] or actual["stale_or_missing"] != manifest["status_counts"]["stale_or_missing"]:
        raise ValueError("Status counts do not reconcile")
    bad_age = con.execute("""select count(*) from read_parquet(?) where
        (element_epoch is not null and cast(element_epoch as timestamptz) > cast(time_utc as timestamptz))
        or (sgp4_error=-1 and element_epoch is not null and
            date_diff('microsecond', cast(element_epoch as timestamptz), cast(time_utc as timestamptz)) <= 72::bigint*3600*1000000)
        or (sgp4_error<>-1 and (element_epoch is null or
            date_diff('microsecond', cast(element_epoch as timestamptz), cast(time_utc as timestamptz)) > 72::bigint*3600*1000000))""", [str(part)]).fetchone()[0]
    if bad_age:
        raise ValueError(f"{bad_age} rows have inconsistent element age/status")
    old_manifest = json.loads((ROOT / "outputs/catalog-trajectory-all-4hour-2022-2026/manifest.json").read_text())
    old_parts = [ROOT / "outputs/catalog-trajectory-all-4hour-2022-2026" / item["file"]
                 for item in old_manifest["parts"]
                 if manifest["start_inclusive"] <= item["start_inclusive"] < manifest["end_exclusive"]]
    if [{"file": path.name, "sha256": sha256(path)} for path in old_parts] != manifest["pinned_baseline_parts"]:
        raise ValueError("Pinned comparison parts changed after refresh")
    old_con = duckdb.connect()
    old_counts = old_con.execute("""with old as (select * from read_parquet(?)),
        refreshed as (select * from read_parquet(?))
        select count(*) compared_rows,
          count(*) filter(where old.element_epoch is distinct from refreshed.element_epoch) changed_element_epochs,
          count(*) filter(where old.sgp4_error is distinct from refreshed.sgp4_error) changed_statuses,
          count(*) filter(where old.sgp4_error=0 and refreshed.sgp4_error=0 and
            (old.x_teme_km is distinct from refreshed.x_teme_km or old.y_teme_km is distinct from refreshed.y_teme_km or
             old.z_teme_km is distinct from refreshed.z_teme_km or old.vx_teme_km_s is distinct from refreshed.vx_teme_km_s or
             old.vy_teme_km_s is distinct from refreshed.vy_teme_km_s or old.vz_teme_km_s is distinct from refreshed.vz_teme_km_s)) changed_successful_states,
          count(*) filter(where old.sgp4_error=-1 and refreshed.sgp4_error=0) stale_to_fresh,
          count(*) filter(where old.sgp4_error=0 and refreshed.sgp4_error=-1) fresh_to_stale
        from old join refreshed using(norad_id,time_utc)""", [[str(p) for p in old_parts], str(part)]).fetchone()
    old_con.close()
    comparison = dict(zip(("compared_rows", "changed_element_epochs", "changed_statuses",
                           "changed_successful_states", "stale_to_fresh", "fresh_to_stale"), map(int, old_counts)))
    if comparison != manifest["comparison_to_pinned_archive"]:
        raise ValueError("Comparison to pinned four-year trajectory does not reproduce")

    # Independently recompute 500 deterministic successful states against the exact refreshed source record.
    sample = con.execute("""select norad_id,time_utc,element_epoch,sgp4_error,x_teme_km,y_teme_km,z_teme_km,
        vx_teme_km_s,vy_teme_km_s,vz_teme_km_s from read_parquet(?) where sgp4_error=0
        order by hash(norad_id::varchar || time_utc) limit 500""", [str(part)]).fetchall()
    source_records = con.execute("""select norad_id,epoch,inclination,raan,eccentricity,arg_perigee,
        mean_anomaly,mean_motion,mean_motion_dot,bstar,intl_designator,altitude_km from read_parquet(?)
        where epoch >= ? and epoch < ?""", [str(source), utc(manifest["start_inclusive"]) - dt.timedelta(hours=72),
                                             utc(manifest["end_exclusive"])]).fetchall()
    by_key = {(int(row[0]), utc(row[1]).isoformat()): {
        "norad_id": int(row[0]), "epoch": row[1], "inclination": row[2], "raan": row[3],
        "eccentricity": row[4], "arg_perigee": row[5], "mean_anomaly": row[6],
        "mean_motion": row[7], "mean_motion_dot": row[8], "bstar": row[9],
        "intl_designator": row[10], "altitude_km": row[11]} for row in source_records}
    con.close()
    max_position_error = 0.0
    max_velocity_error = 0.0
    for row in sample:
        oid, time_text, epoch_text, error, *state = row
        source_row = by_key.get((int(oid), utc(epoch_text).isoformat()))
        if source_row is None:
            raise ValueError("Sampled output element epoch is absent from refreshed source")
        code, position, velocity = satellite(source_row).sgp4(*julian(utc(time_text)))
        if code != error:
            raise ValueError("Sampled SGP4 error code differs on source replay")
        max_position_error = max(max_position_error, *(abs(a-b) for a, b in zip(position, state[:3])))
        max_velocity_error = max(max_velocity_error, *(abs(a-b) for a, b in zip(velocity, state[3:])))
    result = {
        "status": "passed_source_and_baseline_reconciliation",
        "source_revision": manifest["source_revision"], "source_sha256": manifest["source_file_sha256"],
        "start_inclusive": manifest["start_inclusive"], "end_exclusive": manifest["end_exclusive"],
        "source_records": source_rows, "source_object_count": int(source_bounds[2]),
        "source_latest_epoch_utc": utc(source_bounds[1]).isoformat(),
        "source_records_loaded_for_refresh": manifest["new_source_records_loaded"],
        "objects_checked": actual["objects"], "sample_times_checked": actual["sample_times"],
        "trajectory_rows_checked": part_rows, "status_counts": manifest["status_counts"],
        "element_age_status_mismatches": int(bad_age), "independent_state_replays": len(sample),
        "maximum_position_difference_km": max_position_error,
        "maximum_velocity_difference_km_s": max_velocity_error,
        "comparison_to_pinned_archive": comparison,
        "checks": {
            "source_and_output_hashes": True, "all_object_time_rows_unique": True,
            "explicit_stale_state_semantics": True, "fresh_elements_within_72h_limit": True,
            "full_interval_comparison_recomputed": True, "sampled_states_recomputed_from_refreshed_source": True,
        },
        "scope_limit": "Independent source replay is sampled at 500 successful states; row counts, keys, statuses, freshness semantics, and pinned-baseline deltas are checked across all 482472 rows.",
    }
    (output / "independent_audit.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/catalog-trajectory-source-refresh-2026-10-08-10")
    args = parser.parse_args()
    result = audit(args.output.resolve())
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
