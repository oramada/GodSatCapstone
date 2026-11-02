import json
import sys
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[2]
from scripts.data.export_current_active_state_vectors import export
from scripts.data.export_current_active_payload_history import export as export_history


def test_exports_only_current_gp_undecayed_earth_payloads(tmp_path):
    data = tmp_path / "data"
    year = data / "historical_state_vectors_all/year=2022"
    raw = data / "raw"
    year.mkdir(parents=True)
    raw.mkdir(parents=True)
    db = duckdb.connect()
    db.execute(f'''COPY (SELECT * FROM (VALUES
        (10, TIMESTAMPTZ '2022-11-01 00:00:00+00', 0, 1.0),
        (11, TIMESTAMPTZ '2022-11-01 00:00:00+00', 0, 2.0),
        (12, TIMESTAMPTZ '2022-11-01 00:00:00+00', 0, 3.0)
    ) t(norad_id, epoch, sgp4_error, x_teme_km)) TO '{year / 'part-00000.parquet'}' (FORMAT PARQUET)''')
    db.close()
    source = data / "historical_state_vectors_all"
    (source / "manifest.json").write_text(json.dumps({
        "status": "completed", "signature": "source-sha", "records_written": 3,
        "start": "2022-10-09T00:00:00+00:00", "end_exclusive": "2023-01-01T00:00:00+00:00",
        "years": {"2022": {"complete": True}}, "model": "test SGP4", "frame": "TEME"}))
    (source / "validation.json").write_text(json.dumps({
        "status": "validated_complete", "records_validated": 3,
        "snapshot_matches_current_export_at_validation_completion": True}))
    (raw / "satcat.csv").write_text(
        "NORAD_CAT_ID,OBJECT_TYPE,ORBIT_CENTER,DECAY_DATE\n"
        "10,PAY,EA,\n11,DEB,EA,\n12,PAY,EA,2022-12-01\n")
    (raw / "current_active_gp.json").write_text(json.dumps([
        {"NORAD_CAT_ID": 10}, {"NORAD_CAT_ID": 11}, {"NORAD_CAT_ID": 12}]))
    (data / "current_payload_status_audit.json").write_text(json.dumps({
        "cohorts": {"current_gp_snapshot_intersection_with_no_decay_payloads": {
            "history_records_in_requested_window": 1,
            "with_history_in_requested_window": 1}}}))

    result = export(tmp_path, data / "current_active_payload_state_vectors")

    assert result["status"] == "completed"
    assert result["current_gp_snapshot_ids"] == 3
    assert result["current_gp_no_decay_payload_candidate_ids"] == 1
    assert result["selected_objects_with_states"] == 1
    assert result["selected_state_records"] == 1
    selected = duckdb.connect()
    rows = selected.execute(
        f"SELECT norad_id FROM read_parquet('{data / 'current_active_payload_state_vectors/year=2022.parquet'}')"
    ).fetchall()
    selected.close()
    assert rows == [(10,)]


@pytest.mark.parametrize("with_context", [False, True])
def test_exports_history_for_current_active_payload_intersection(tmp_path, with_context):
    data = tmp_path / "data"
    raw = data / "raw"
    raw.mkdir(parents=True)
    rows = [
        (10, "2025-01-01T00:00:00Z", 50., 20., .001, 40., 60., 15., 0., 0.),
        (11, "2025-01-01T00:00:00Z", 50., 20., .001, 40., 60., 15., 0., 0.),
        (12, "2025-01-01T00:00:00Z", 50., 20., .001, 40., 60., 15., 0., 0.),
    ]
    history = data / "current_payload_orbit_history.parquet"
    write_db = duckdb.connect()
    write_db.execute("""CREATE TABLE history (
        norad_id INTEGER, epoch TIMESTAMPTZ, inclination FLOAT, raan FLOAT,
        eccentricity FLOAT, arg_perigee FLOAT, mean_anomaly FLOAT,
        mean_motion FLOAT, mean_motion_dot FLOAT, bstar FLOAT)""")
    write_db.executemany("INSERT INTO history VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    write_db.execute("COPY history TO ? (FORMAT PARQUET)", [str(history)])
    if with_context:
        write_db.execute("""INSERT INTO history VALUES
            (10, TIMESTAMPTZ '2022-10-08', 50, 20, .001, 40, 60, 15, 0, 0),
            (10, TIMESTAMPTZ '2022-10-05', 50, 20, .001, 40, 60, 15, 0, 0)""")
        write_db.execute("COPY history TO ? (FORMAT PARQUET)", [str(raw / "tle_2022.parquet")])
    write_db.close()
    (raw / "satcat.csv").write_text(
        "NORAD_CAT_ID,OBJECT_TYPE,ORBIT_CENTER,DECAY_DATE,OPS_STATUS_CODE\n"
        "10,PAY,EA,,+\n11,PAY,EA,,-\n12,DEB,EA,,+\n")
    (raw / "current_active_gp.json").write_text(json.dumps([
        {"NORAD_CAT_ID": 10}, {"NORAD_CAT_ID": 12}]))
    (data / "current_payload_status_audit.json").write_text(json.dumps({
        "cohorts": {"current_gp_snapshot_intersection_with_no_decay_payloads": {
            "catalog_ids": 1, "with_history_in_requested_window": 1,
            "history_records_in_requested_window": 1}}}))

    output = data / "current_active_payload_orbit_history.parquet"
    result = export_history(tmp_path, output)

    assert result["historical_object_count"] == 1
    assert result["historical_record_count"] == (2 if with_context else 1)
    assert result["requested_window_record_count"] == 1
    assert result["past_context_record_count"] == int(with_context)
    assert result["satcat_ops_status_codes"] == ["+"]
    db = duckdb.connect()
    selected = db.execute(f"SELECT norad_id FROM read_parquet('{output}')").fetchall()
    db.close()
    assert selected == [(10,)] * (2 if with_context else 1)
    if with_context:
        from godsat.orbits import History
        replay = History(tmp_path, "current_active_payload")
        try:
            # The first requested midnight must have a past-only seed element.
            assert [row["norad_id"] for row in replay.snapshot("2022-10-09T00:00:00Z")] == [10]
        finally:
            replay.db.close()
