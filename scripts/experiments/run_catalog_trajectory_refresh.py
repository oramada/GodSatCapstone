#!/usr/bin/env python3
"""Rebuild the final two days of the catalog ephemeris from the latest TLE snapshot."""
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

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from godsat.orbits import ROOT, orbit_regime, utc
from godsat.trajectory import trajectory_rows


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "data/raw/snapshots/2026-10-11/tle_2026.parquet")
    parser.add_argument("--start", default="2026-10-08T00:00:00Z")
    parser.add_argument("--end", default="2026-10-10T00:00:00Z")
    parser.add_argument("--step-seconds", type=int, default=14400)
    parser.add_argument("--max-age-hours", type=float, default=72)
    parser.add_argument("--baseline", type=Path, default=ROOT / "outputs/catalog-trajectory-all-4hour-2022-2026")
    parser.add_argument("--source-revision", help="immutable publisher revision; may instead be supplied by the source .manifest.json receipt")
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/catalog-trajectory-source-refresh-2026-10-08-10")
    args = parser.parse_args()
    source, output = args.source.resolve(), args.output.resolve()
    receipt_path = source.with_suffix('.manifest.json')
    receipt = json.loads(receipt_path.read_text()) if receipt_path.exists() else None
    source_revision = args.source_revision or (receipt or {}).get('source_revision')
    if not source_revision:
        parser.error('--source-revision or a checksum-verified source .manifest.json receipt is required')
    source_hash = digest(source)
    if receipt and (receipt.get('sha256') != source_hash or receipt.get('source_revision') != source_revision
                    or receipt.get('size_bytes') != source.stat().st_size):
        raise ValueError('Source snapshot does not match its revision/checksum/size receipt')
    start, end = utc(args.start), utc(args.end)
    if not source.is_file() or start >= end or args.step_seconds <= 0 or 86400 % args.step_seconds:
        parser.error("source must exist, start < end, and step-seconds must divide one day")
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"Refusing to overwrite nonempty output: {output}")
    output.mkdir(parents=True, exist_ok=True)

    ids = set()
    with (ROOT / "data/state_vector_object_coverage.csv").open(newline="") as stream:
        ids.update(int(row["norad_id"]) for row in csv.DictReader(stream)
                   if int(row["historical_element_rows"]) > 0)
    con = duckdb.connect()
    con.execute("SET TimeZone='UTC'")
    lower = start - dt.timedelta(hours=args.max_age_hours)
    query = """select norad_id, epoch, inclination, raan, eccentricity,
                      arg_perigee, mean_anomaly, mean_motion, mean_motion_dot,
                      bstar, intl_designator, altitude_km
               from read_parquet(?) where epoch >= ? and epoch < ?
               order by norad_id, epoch, inclination, raan, eccentricity, arg_perigee,
                        mean_anomaly, mean_motion, mean_motion_dot, bstar, intl_designator, altitude_km"""
    records = con.execute(query, [str(source), lower, end]).fetch_arrow_table().to_pylist()
    source_bounds = con.execute('select min(epoch),max(epoch),count(distinct norad_id) from read_parquet(?)', [str(source)]).fetchone()
    con.close()
    by_id: dict[int, list[dict]] = {}
    for record in records:
        oid = int(record["norad_id"])
        ids.add(oid)
        by_id.setdefault(oid, []).append(record)
    ordered_ids = sorted(ids)
    schema = pa.schema([
        ("norad_id", pa.int32()), ("time_utc", pa.string()),
        ("element_epoch", pa.string()), ("element_age_hours", pa.float64()),
        ("orbit_regime", pa.string()), ("sgp4_error", pa.int16()),
        ("x_teme_km", pa.float64()), ("y_teme_km", pa.float64()),
        ("z_teme_km", pa.float64()), ("vx_teme_km_s", pa.float64()),
        ("vy_teme_km_s", pa.float64()), ("vz_teme_km_s", pa.float64()),
    ])
    part = output / "part-00000.parquet"
    counts = {"successful": 0, "sgp4_errors": 0, "stale_or_missing": 0}
    sample_times = []
    instant = start
    while instant < end:
        sample_times.append(instant.isoformat())
        instant += dt.timedelta(seconds=args.step_seconds)
    writer = pq.ParquetWriter(part, schema, compression="zstd", compression_level=3,
                              use_dictionary=["orbit_regime"])
    try:
        batch = []
        for oid in ordered_ids:
            object_records = by_id.get(oid, [])
            regimes = {utc(item["epoch"]).isoformat(): orbit_regime(item)
                       for item in object_records}
            for row in trajectory_rows(object_records, oid, start, end,
                                       args.step_seconds, args.max_age_hours):
                row["orbit_regime"] = regimes.get(row["element_epoch"], "unknown")
                if row["sgp4_error"] == -1:
                    counts["stale_or_missing"] += 1
                elif row["sgp4_error"] == 0:
                    counts["successful"] += 1
                else:
                    counts["sgp4_errors"] += 1
                batch.append(row)
                if len(batch) >= 100_000:
                    writer.write_table(pa.Table.from_pylist(batch, schema=schema), row_group_size=100_000)
                    batch.clear()
        if batch:
            writer.write_table(pa.Table.from_pylist(batch, schema=schema), row_group_size=100_000)
    finally:
        writer.close()
    expected = len(ordered_ids) * len(sample_times)
    actual = pq.ParquetFile(part).metadata.num_rows
    if actual != expected:
        raise RuntimeError(f"wrote {actual:,} rows; expected {expected:,}")
    pinned_root = args.baseline.resolve()
    pinned_manifest = json.loads((pinned_root / "manifest.json").read_text())
    pinned_parts = [pinned_root / p["file"] for p in pinned_manifest["parts"]
                    if start.isoformat() <= p["start_inclusive"] < end.isoformat()]
    if len(pinned_parts) != 2:
        raise RuntimeError("Expected the two pinned daily trajectory parts for the refresh interval")
    old_con = duckdb.connect()
    old_files = [str(path) for path in pinned_parts]
    comparison = old_con.execute("""with old as (select * from read_parquet(?)),
        refreshed as (select * from read_parquet(?))
        select count(*) compared_rows,
          count(*) filter(where old.element_epoch is distinct from refreshed.element_epoch) changed_element_epochs,
          count(*) filter(where old.sgp4_error is distinct from refreshed.sgp4_error) changed_statuses,
          count(*) filter(where old.sgp4_error=0 and refreshed.sgp4_error=0 and
            (old.x_teme_km is distinct from refreshed.x_teme_km or
             old.y_teme_km is distinct from refreshed.y_teme_km or
             old.z_teme_km is distinct from refreshed.z_teme_km or
             old.vx_teme_km_s is distinct from refreshed.vx_teme_km_s or
             old.vy_teme_km_s is distinct from refreshed.vy_teme_km_s or
             old.vz_teme_km_s is distinct from refreshed.vz_teme_km_s)) changed_successful_states,
          count(*) filter(where old.sgp4_error=-1 and refreshed.sgp4_error=0) stale_to_fresh,
          count(*) filter(where old.sgp4_error=0 and refreshed.sgp4_error=-1) fresh_to_stale
        from old join refreshed using(norad_id,time_utc)""", [old_files, str(part)]).fetchone()
    old_con.close()
    comparison = dict(zip(("compared_rows", "changed_element_epochs", "changed_statuses",
                          "changed_successful_states", "stale_to_fresh", "fresh_to_stale"),
                         map(int, comparison)))
    manifest = {
        "status": "completed", "source_dataset": "juliensimon/space-track-tle-history",
        "source_revision": source_revision,
        "source_file": str(source.relative_to(ROOT)), "source_file_sha256": source_hash,
        "source_receipt_sha256": digest(receipt_path) if receipt else None,
        "source_total_records": pq.ParquetFile(source).metadata.num_rows,
        "source_latest_epoch_utc": utc(source_bounds[1]).isoformat(),
        "source_earliest_epoch_utc": utc(source_bounds[0]).isoformat(),
        "source_total_objects": int(source_bounds[2]),
        "duplicate_resolution": "Equal epochs are sorted by all recorded orbital fields; select the lexicographically greatest tuple.",
        "start_inclusive": start.isoformat(), "end_exclusive": end.isoformat(),
        "sample_times_utc": sample_times, "step_seconds": args.step_seconds,
        "max_element_age_hours": args.max_age_hours, "frame": "TEME",
        "position_units": "km", "velocity_units": "km/s",
        "model": "SGP4 WGS-72 using latest available 2026 orbital element at or before each sample",
        "objects": len(ordered_ids), "new_source_records_loaded": len(records),
        "rows": actual, "status_counts": counts,
        "pinned_baseline_revision": pinned_manifest["source_revision"],
        "pinned_baseline_root": str(pinned_root),
        "pinned_baseline_parts": [{"file": path.name, "sha256": digest(path)} for path in pinned_parts],
        "comparison_to_pinned_archive": comparison,
        "part": {"file": part.name, "sha256": digest(part), "size_bytes": part.stat().st_size},
        "limitations": [
            "This is a two-day source-refresh overlay, not a replacement of the pinned four-year archive.",
            "The 2026 snapshot is used for the refresh; older yearly source files remain those in the pinned archive.",
            "The catalog includes payloads and debris and is not a complete operational-satellite census.",
            "These are reconstructed SGP4 states, not precision orbit truth; stale rows are explicit.",
        ],
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"status": "completed", "output": str(output), "objects": len(ordered_ids),
                      "rows": actual, "source_records": len(records), "status_counts": counts,
                      "source_sha256": manifest["source_file_sha256"]}, indent=2))


if __name__ == "__main__":
    main()
