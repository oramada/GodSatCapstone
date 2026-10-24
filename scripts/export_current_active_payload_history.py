"""Export archived orbital elements for the current active-GP payload cohort.

The cohort is a current catalog snapshot backcast through the historical
archive. It does not establish that an object was operational at each past
epoch.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import pathlib

import duckdb

from export_current_active_state_vectors import read_candidates, sql_path

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/current_payload_orbit_history.parquet"
OUTPUT = ROOT / "data/current_active_payload_orbit_history.parquet"


def export(root=ROOT, output=OUTPUT):
    root, output = pathlib.Path(root).resolve(), pathlib.Path(output).resolve()
    source = root / "data/current_payload_orbit_history.parquet"
    source_audit = root / "data/current_payload_status_audit.json"
    if not source.is_file() or not source_audit.is_file():
        raise FileNotFoundError("Current-payload history and its status audit are required")
    candidates, _catalog, current_gp_ids = read_candidates(root)
    audit = json.loads(source_audit.read_text())
    expected = audit["cohorts"]["current_gp_snapshot_intersection_with_no_decay_payloads"]
    if len(candidates) != expected["catalog_ids"]:
        raise RuntimeError("Candidate ID set disagrees with the saved status audit")
    ids_digest = hashlib.sha256(",".join(map(str, sorted(candidates))).encode()).hexdigest()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.unlink(missing_ok=True)
    db = duckdb.connect()
    db.execute("SET TimeZone='UTC'")
    db.execute("SET threads=2")
    db.execute("SET memory_limit='1GB'")
    try:
        db.execute(f'''COPY (
            SELECT * FROM read_parquet({sql_path(source)})
            WHERE norad_id IN (SELECT unnest(?))
        ) TO {sql_path(temporary)} (FORMAT PARQUET, COMPRESSION ZSTD)''',
            [sorted(candidates)])
        records, objects = db.execute(
            f"SELECT count(*), count(DISTINCT norad_id) FROM read_parquet({sql_path(temporary)})"
        ).fetchone()
        min_epoch, max_epoch = db.execute(
            f"SELECT min(epoch), max(epoch) FROM read_parquet({sql_path(temporary)})"
        ).fetchone()
        statuses = db.execute(f'''SELECT DISTINCT c.OPS_STATUS_CODE
            FROM read_parquet({sql_path(temporary)}) h
            JOIN read_csv_auto({sql_path(root / 'data/raw/satcat.csv')}, all_varchar=true) c
              ON CAST(c.NORAD_CAT_ID AS BIGINT)=h.norad_id
            ORDER BY 1''').fetchall()
    finally:
        db.close()
    if records != expected["history_records_in_requested_window"]:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"Exported {records} rows; audit expects {expected['history_records_in_requested_window']}")
    if objects != expected["with_history_in_requested_window"]:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"Exported {objects} objects; audit expects {expected['with_history_in_requested_window']}")
    status_codes = [row[0] for row in statuses]
    if any(code in (None, "", "-") for code in status_codes):
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"Unexpected inactive or unknown SATCAT status in active-GP cohort: {status_codes}")
    temporary.replace(output)
    result = {
        "status": "completed",
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source": "data/current_payload_orbit_history.parquet",
        "output": output.relative_to(root).as_posix() if output.is_relative_to(root) else str(output),
        "cohort_definition": "current_active_gp.json IDs intersected with SATCAT OBJECT_TYPE=PAY, ORBIT_CENTER=EA, blank DECAY_DATE; historical records selected from no-decay Earth payload archive",
        "current_gp_snapshot_id_count": len(current_gp_ids),
        "candidate_id_count": len(candidates),
        "candidate_id_sha256": ids_digest,
        "historical_object_count": int(objects),
        "historical_record_count": int(records),
        "first_epoch": min_epoch.isoformat(),
        "last_epoch": max_epoch.isoformat(),
        "satcat_ops_status_codes": status_codes,
        "expected_records_from_status_audit": expected["history_records_in_requested_window"],
        "expected_objects_from_status_audit": expected["with_history_in_requested_window"],
        "limitations": [
            "Current catalog and active-GP membership are snapshot classifications backcast to historical epochs; neither proves operational status at each past epoch.",
            "Historical orbital elements are irregularly sampled and mirror records may omit precision from original TLE/OMM data.",
        ],
    }
    manifest = output.with_suffix(output.suffix + ".manifest.json")
    manifest.write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=pathlib.Path, default=OUTPUT)
    args = parser.parse_args()
    print(json.dumps(export(output=args.output), indent=2))
