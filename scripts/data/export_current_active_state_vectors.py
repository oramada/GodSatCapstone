"""Select four-year state vectors for payloads in the current CelesTrak GP snapshot."""
from __future__ import annotations

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))


import csv
import datetime as dt
import hashlib
import json
import pathlib

import duckdb

ROOT = pathlib.Path(__file__).resolve().parents[2]
INPUT = ROOT / "data/historical_state_vectors_all"
DEFAULT_OUTPUT = ROOT / "data/current_active_payload_state_vectors"


def read_candidates(root):
    raw = root / "data/raw"
    with (raw / "satcat.csv").open(newline="", encoding="utf-8") as stream:
        catalog = {int(row["NORAD_CAT_ID"]): row for row in csv.DictReader(stream)
                   if row.get("NORAD_CAT_ID", "").isdigit()}
    current_gp = json.loads((raw / "current_active_gp.json").read_text())
    current_gp_ids = {int(row["NORAD_CAT_ID"]) for row in current_gp
                      if row.get("NORAD_CAT_ID") is not None}
    candidates = {
        norad_id for norad_id in current_gp_ids
        if norad_id in catalog
        and catalog[norad_id].get("OBJECT_TYPE") == "PAY"
        and catalog[norad_id].get("ORBIT_CENTER") == "EA"
        and not catalog[norad_id].get("DECAY_DATE")
    }
    return candidates, catalog, current_gp_ids


def sql_path(path):
    return "'" + str(path).replace("'", "''") + "'"


def export(root=ROOT, output=DEFAULT_OUTPUT):
    root, output = pathlib.Path(root).resolve(), pathlib.Path(output).resolve()
    input_dir = root / "data/historical_state_vectors_all"
    manifest_path = input_dir / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)
    source_manifest = json.loads(manifest_path.read_text())
    if source_manifest.get("status") != "completed":
        raise RuntimeError("All-catalog state-vector export must be complete before selecting the current-payload cohort")
    validation_path = input_dir / "validation.json"
    validation = json.loads(validation_path.read_text())
    if (validation.get("status") != "validated_complete"
            or validation.get("snapshot_matches_current_export_at_validation_completion") is not True
            or validation.get("records_validated") != source_manifest.get("records_written")):
        raise RuntimeError("All-catalog export needs a complete validation matching its current manifest")

    candidates, catalog, current_gp_ids = read_candidates(root)
    if not candidates:
        raise RuntimeError("Current-GP/no-decay payload intersection is empty")
    ids_digest = hashlib.sha256(",".join(map(str, sorted(candidates))).encode()).hexdigest()
    output.mkdir(parents=True, exist_ok=True)
    db = duckdb.connect()
    db.execute("SET TimeZone='UTC'")
    db.execute("SET threads=2")
    db.execute("SET memory_limit='1GB'")
    years = sorted(map(int, source_manifest["years"]))
    by_year = {}
    total_rows = total_successful = total_failed = 0
    try:
        for year in years:
            source_year = source_manifest["years"][str(year)]
            if not source_year.get("complete"):
                raise RuntimeError(f"Source year {year} is marked incomplete")
            parts = sorted((input_dir / f"year={year}").glob("part-*.parquet"))
            if not parts:
                continue
            input_glob = str(input_dir / f"year={year}" / "part-*.parquet")
            destination = output / f"year={year}.parquet"
            temporary = destination.with_suffix(".parquet.tmp")
            temporary.unlink(missing_ok=True)
            db.execute(f'''COPY (
                SELECT * FROM read_parquet({sql_path(input_glob)})
                WHERE norad_id IN (SELECT unnest(?))
            ) TO {sql_path(temporary)} (FORMAT PARQUET, COMPRESSION ZSTD)''',
                [sorted(candidates)])
            temporary.replace(destination)
            rows, success, failed, objects = db.execute(
                f'''SELECT count(*), count(*) FILTER (WHERE sgp4_error=0),
                    count(*) FILTER (WHERE sgp4_error<>0), count(DISTINCT norad_id)
                    FROM read_parquet({sql_path(destination)})''').fetchone()
            by_year[str(year)] = {"records": int(rows), "successful_states": int(success),
                                  "failed_states": int(failed), "objects_with_records": int(objects)}
            total_rows += int(rows)
            total_successful += int(success)
            total_failed += int(failed)
    finally:
        db.close()

    audit = json.loads((root / "data/current_payload_status_audit.json").read_text())
    expected = audit["cohorts"]["current_gp_snapshot_intersection_with_no_decay_payloads"]
    if total_rows != expected["history_records_in_requested_window"]:
        raise RuntimeError(f"Selected {total_rows} state rows; catalog/history audit expects {expected['history_records_in_requested_window']}")
    if total_failed:
        raise RuntimeError(f"Current-payload subset includes {total_failed} failed SGP4 states")
    source_after = json.loads(manifest_path.read_text())
    if (source_after.get("status") != "completed"
            or source_after.get("signature") != source_manifest.get("signature")
            or source_after.get("records_written") != source_manifest.get("records_written")):
        raise RuntimeError("Source export status changed during subset export")
    db = duckdb.connect()
    try:
        selected_objects = db.execute(
            f"SELECT count(DISTINCT norad_id) FROM read_parquet({sql_path(str(output / 'year=*.parquet'))})"
        ).fetchone()[0]
    finally:
        db.close()

    result = {
        "status": "completed",
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source_dataset": "data/historical_state_vectors_all",
        "source_export_signature": source_manifest["signature"],
        "source_records_written": source_manifest["records_written"],
        "source_validation_records": validation["records_validated"],
        "source_validation_matches_manifest": True,
        "cohort_definition": "NORAD IDs in data/raw/current_active_gp.json intersected with SATCAT OBJECT_TYPE=PAY, ORBIT_CENTER=EA, and blank DECAY_DATE",
        "current_gp_snapshot_ids": len(current_gp_ids),
        "current_gp_no_decay_payload_candidate_ids": len(candidates),
        "candidate_ids_with_historical_records": int(expected["with_history_in_requested_window"]),
        "selected_objects_with_states": int(selected_objects),
        "candidate_ids_without_historical_records": len(candidates) - int(expected["with_history_in_requested_window"]),
        "candidate_id_sha256": ids_digest,
        "expected_historical_element_records": expected["history_records_in_requested_window"],
        "selected_state_records": total_rows,
        "successful_sgp4_states": total_successful,
        "failed_sgp4_states": total_failed,
        "years": by_year,
        "model": source_manifest["model"],
        "frame": source_manifest["frame"],
        "limitations": [
            "The current-GP list and SATCAT status are dated catalog snapshots, not proof of mission operation at every historical epoch.",
            "Each state is reconstructed at an archived element epoch; this is not a uniform-cadence ephemeris.",
            "The source element mirror omits precision present in original TLE/OMM records.",
        ],
    }
    (output / "manifest.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    print(json.dumps(export(args.root, args.output), indent=2))


if __name__ == "__main__":
    main()
