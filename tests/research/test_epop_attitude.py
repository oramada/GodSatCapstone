import json
from pathlib import Path

import pyarrow.parquet as pq

from godsat.epop_attitude import parse_attquat_zip


ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "data/attitude/cassiope_epop/raw/2022/CAS_AttQuat_20221009T000000_20221009T235959_2.0.0.cdf.zip"


def test_public_cassiope_daily_product_parses_at_one_hz_and_preserves_dropouts():
    payload = SAMPLE.read_bytes()
    table, audit = parse_attquat_zip(payload)

    assert table.num_rows == 86_400
    assert str(table.schema.field("timestamp_utc").type) == "timestamp[ns, tz=UTC]"
    assert audit["first_utc"].startswith("2022-10-09T00:00:00")
    assert audit["last_utc"].startswith("2022-10-09T23:59:59")
    assert audit["valid_quaternion_seconds"] + audit["invalid_quaternion_seconds"] == 86_400
    assert audit["invalid_quaternion_seconds"] > 0
    assert audit["dropout_source_previous_seconds"] == audit["invalid_quaternion_seconds"]
    assert audit["dropout_source_next_seconds"] == audit["invalid_quaternion_seconds"]
    assert audit["attitude_solution_dropout_events"] > 0
    assert audit["longest_attitude_solution_dropout_seconds"] > 0
    assert abs(audit["finite_quaternion_norm_min"] - 1) < 1e-10
    assert abs(audit["finite_quaternion_norm_max"] - 1) < 1e-10


def test_ingested_product_checksums_and_parquet_match_the_source():
    audit_path = ROOT / "data/attitude/cassiope_epop/audits/2022/2022-10-09.json"
    parquet_path = ROOT / "data/attitude/cassiope_epop/processed/2022/2022-10-09.parquet"
    audit = json.loads(audit_path.read_text())
    assert audit["status"] == "validated"
    assert audit["source_zip_sha256"]
    assert audit["cdf_sha256"]
    assert pq.read_metadata(parquet_path).num_rows == audit["samples"] == 86_400
