import io
import zipfile

from scripts.audit_durham_tle_temporal_consistency import audit


def test_audit_flags_tle_epoch_after_observation_and_missing_bundle_tles(tmp_path):
    archive = tmp_path / "observations.zip"
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w") as nightly:
        nightly.writestr("norad_12345_final.csv", (
            "TIME_JD,MATCH_TLE_EPOCH_JD,MATCH_NORAD\n"
            "2460000.0,2460000.25,12345\n"
            "2460001.0,2460000.5,12345\n"))
        nightly.writestr("track_1.csv", "TIME_JD,MATCH_TLE_EPOCH_JD\n2460000,2459999\n")
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("test_rawDetect_output.zip", inner.getvalue())

    output = tmp_path / "audit.json"
    result = audit(archive, output)

    assert result["rows"] == {
        "total": 3,
        "identified_norad_rows": 2,
        "unidentified_track_rows": 1,
        "identified_rows_with_finite_observation_and_tle_epochs": 2,
    }
    assert result["matched_tle_epoch_age_days"]["future_by_more_than_60_seconds"] == 1
    assert result["separate_tle_files_in_nested_archives"] == 0
    assert output.is_file()
