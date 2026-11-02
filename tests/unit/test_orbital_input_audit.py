import json

import duckdb
import pytest

from scripts.validation.audit_orbital_inputs import audit, sha256


def make_archive(tmp_path):
    raw = tmp_path / "data/raw"
    raw.mkdir(parents=True)
    path = raw / "tle_2023.parquet"
    db = duckdb.connect()
    db.sql("""SELECT 1 AS norad_id, TIMESTAMPTZ '2023-01-01' AS epoch,
        30.0 AS inclination, 10.0 AS raan, 0.01 AS eccentricity,
        0.0 AS arg_perigee, 0.0 AS mean_anomaly, 15.0 AS mean_motion,
        0.0 AS mean_motion_dot, 0.0 AS bstar
        UNION ALL SELECT 2, TIMESTAMPTZ '2023-01-02',
            30.0, 10.0, 1.1, 0.0, 0.0, 15.0, 0.0, 0.0
        UNION ALL SELECT 3, TIMESTAMPTZ '2021-01-01',
            30.0, 10.0, 0.01, 0.0, 0.0, 15.0, 0.0, 0.0""").write_parquet(str(path))
    db.close()
    manifest = {"repository": "test/history", "revision": "pinned", "files": [
        {"path": "data/tle_2023.parquet", "lfs": {"size": path.stat().st_size,
                                                   "oid": sha256(path)}}]}
    (raw / "source-manifest.json").write_text(json.dumps(manifest))
    return path


def test_audit_distinguishes_all_source_rows_and_requested_window(tmp_path):
    make_archive(tmp_path)
    result = audit(tmp_path)
    assert result["archive_sha256_verified"]
    assert result["source_records"] == 3
    assert result["window_records"] == 2
    assert result["quality_flag_totals"]["invalid_eccentricity_rows"] == 1
    assert result["status"] == "verified_inputs_with_quality_flags"


def test_pinned_source_corruption_fails_before_reporting_verified(tmp_path):
    path = make_archive(tmp_path)
    with path.open("r+b") as stream:
        stream.write(b"BAD!")
    with pytest.raises(ValueError, match="Pinned source verification failed"):
        audit(tmp_path)


def test_audit_rejects_unqualified_window_dates(tmp_path):
    with pytest.raises(ValueError, match="timezone-qualified"):
        audit(tmp_path, start="2023-01-01", end="2024-01-01")
