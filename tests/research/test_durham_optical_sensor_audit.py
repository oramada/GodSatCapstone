import json
import pathlib
import zipfile

import pytest

from scripts.validation.audit_durham_widefield_ssa import audit


ROOT = pathlib.Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data/ground_sensor/durham_widefield_ssa/all_data.zip"


@pytest.fixture(scope="module")
def audited_source():
    return audit(SOURCE)


def test_durham_source_archive_integrity_and_inventory(audited_source):
    assert audited_source["status"] == "completed_conditional_on_sky_detection_gap_audit"
    assert audited_source["source"]["md5"] == "1a566e244a1b368730a24de0bc07d962"
    assert audited_source["source"]["sha256"] == (
        "a17abbf503eedb373414a0068a99608c436448a177deb70e2b69fe20fd7705d1"
    )
    assert audited_source["coverage"]["night_count"] == 10
    assert audited_source["coverage"]["reported_detection_rows"] == 202627
    assert audited_source["coverage"]["identified_norad_catalogue_files"] == 338
    assert audited_source["coverage"]["unidentified_track_catalogue_files"] == 20
    assert audited_source["source"]["tle_files_found_in_released_nightly_archives"] == 0


def test_durham_conditional_in_field_gap_estimate_reconciles(audited_source):
    result = audited_source["conditional_in_field_detection_gap_proxy"]
    assert result["target_frame_opportunities"] == 161805
    assert result["recorded_detections"] == 138258
    assert result["unrecorded_target_frames"] == 23547
    assert result["conditional_unrecorded_fraction"] == pytest.approx(23547 / 161805)
    assert result["night_cluster_bootstrap_replicates"] == 10000
    low, high = result["night_cluster_bootstrap_ci95"]
    assert 0.11 < low < result["conditional_unrecorded_fraction"] < high < 0.17
    assert "not shutter failures" in result["interpretation"]
    assert len(audited_source["pooled_sensitivity"]) == 9
