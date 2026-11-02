"""Verify downloaded orbital inputs and report full-window source quality."""
from __future__ import annotations

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))


import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[2]
START = "2022-10-09T00:00:00Z"
END = "2026-10-10T00:00:00Z"
ELEMENTS = ("inclination", "raan", "eccentricity", "arg_perigee",
            "mean_anomaly", "mean_motion", "mean_motion_dot", "bstar")


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def audit(root=ROOT, start=START, end=END):
    root = Path(root).resolve()
    lower = dt.datetime.fromisoformat(start.replace("Z", "+00:00"))
    upper = dt.datetime.fromisoformat(end.replace("Z", "+00:00"))
    if lower.tzinfo is None or upper.tzinfo is None or lower >= upper:
        raise ValueError("Use timezone-qualified start < end timestamps")
    source_path = root / "data/raw/source-manifest.json"
    manifest = json.loads(source_path.read_text())
    if not manifest["files"]:
        raise ValueError("The source manifest contains no archives")
    files = []
    db = duckdb.connect()
    db.execute("SET threads=2")
    db.execute("SET memory_limit='1GB'")
    db.execute("SET TimeZone='UTC'")
    try:
        for item in manifest["files"]:
            path = root / "data/raw" / Path(item["path"]).name
            actual_hash = sha256(path)
            if path.stat().st_size != item["lfs"]["size"] or actual_hash != item["lfs"]["oid"]:
                raise ValueError(f"Pinned source verification failed: {path.name}")
            db.read_parquet(str(path)).create_view("source", replace=True)
            fields = {row[0] for row in db.execute("DESCRIBE source").fetchall()}
            missing = set(ELEMENTS) | {"norad_id", "epoch"}
            missing -= fields
            if missing:
                raise ValueError(f"{path.name} is missing columns: {sorted(missing)}")
            finite = " AND ".join(f"coalesce(isfinite({field}), false)" for field in ELEMENTS)
            result = db.execute(f"""SELECT count(*) AS records,
                count(DISTINCT norad_id) AS objects,
                min(epoch)::VARCHAR AS first_epoch, max(epoch)::VARCHAR AS last_epoch,
                count(*) FILTER (WHERE norad_id IS NULL OR norad_id <= 0) AS invalid_ids,
                count(*) FILTER (WHERE NOT ({finite})) AS nonfinite_element_rows,
                count(*) FILTER (WHERE inclination < 0 OR inclination > 180) AS invalid_inclination_rows,
                count(*) FILTER (WHERE eccentricity < 0 OR eccentricity >= 1) AS invalid_eccentricity_rows,
                count(*) FILTER (WHERE mean_motion <= 0) AS nonpositive_mean_motion_rows,
                count(*) FILTER (WHERE raan < 0 OR raan >= 360 OR arg_perigee < 0
                    OR arg_perigee >= 360 OR mean_anomaly < 0 OR mean_anomaly >= 360)
                    AS noncanonical_angle_rows
                FROM source WHERE epoch >= ? AND epoch < ?""", [lower, upper])
            quality = dict(zip([column[0] for column in result.description], result.fetchone()))
            full = db.execute("SELECT count(*), count(*) FILTER (WHERE epoch IS NULL), "
                              "min(epoch)::VARCHAR, max(epoch)::VARCHAR FROM source").fetchone()
            files.append({"path": str(path.relative_to(root)), "sha256": actual_hash,
                          "bytes": path.stat().st_size, "source_records": full[0],
                          "null_epoch_records": full[1], "source_first_epoch": full[2],
                          "source_last_epoch": full[3], "requested_window": quality})
    finally:
        db.close()
    flags = ("invalid_ids", "nonfinite_element_rows", "invalid_inclination_rows",
             "invalid_eccentricity_rows", "nonpositive_mean_motion_rows", "noncanonical_angle_rows")
    totals = {name: sum(file["requested_window"][name] for file in files) for name in flags}
    null_epochs = sum(file["null_epoch_records"] for file in files)
    return {
        "status": "verified_inputs_with_quality_flags" if any(totals.values()) or null_epochs else "verified_inputs",
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "repository": manifest["repository"], "revision": manifest["revision"],
        "source_manifest_sha256": sha256(source_path), "archive_sha256_verified": True,
        "start_inclusive": lower.isoformat(), "end_exclusive": upper.isoformat(),
        "source_records": sum(file["source_records"] for file in files),
        "window_records": sum(file["requested_window"]["records"] for file in files),
        "null_epoch_records": null_epochs,
        "quality_flag_totals": totals, "files": files,
        "interpretation": "All pinned file hashes and every source row were checked for the stated counts. Quality flags overlap. Noncanonical angles may be periodically equivalent; they are retained and reported, not silently discarded. This verifies source integrity and basic domains, not orbital accuracy, historical operational status, or continuous trajectory coverage.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--start", default=START)
    parser.add_argument("--end", default=END)
    parser.add_argument("--output", type=Path, default=Path("outputs/study-execution/orbital-input-audit.json"))
    args = parser.parse_args()
    result = audit(args.root, args.start, args.end)
    output = args.output if args.output.is_absolute() else args.root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    temporary.replace(output)
    print(json.dumps({key: result[key] for key in ("status", "source_records", "window_records", "quality_flag_totals")}, indent=2))


if __name__ == "__main__":
    main()
