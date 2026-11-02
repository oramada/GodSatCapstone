import json

from scripts.experiments.run_full_catalog_tasking import configuration_signature, load_cached_cell


def test_tasking_cache_signature_changes_with_sensor_model_and_seed_date_order(tmp_path):
    dates = ["2023-01-01T00:00:00Z", "2023-02-01T00:00:00Z"]
    config = {"detection_probability": 0.98, "slew_rate_deg_s": 2}

    def signature(settings=config, timeline=dates, cohort="all"):
        return configuration_signature(settings, timeline, cohort, [0, 0.2], "archive")

    expected = signature()
    assert signature({**config, "detection_probability": 0.5}) != expected
    assert signature(timeline=dates[::-1]) != expected
    assert signature(cohort="current_active_payload") != expected
    assert signature() == expected
    path = tmp_path / "cell.json"
    path.write_text(json.dumps({"simulator_version": 2, "source_sha256": "scenario",
                                "rows": [{"sensor_host_ids": [1, 2]}],
                                "configuration_signature": expected}))
    assert load_cached_cell(path, "scenario", [1, 2], expected_configuration_signature=expected)
    assert load_cached_cell(path, "scenario", [1, 2], expected_configuration_signature=signature(timeline=dates[::-1])) is None


def test_unversioned_configuration_cache_is_not_reused_in_a_signed_run(tmp_path):
    path = tmp_path / "cell.json"
    path.write_text(json.dumps({"simulator_version": 2, "source_sha256": "scenario",
                                "rows": [{"sensor_host_ids": [1, 2]}]}))
    assert load_cached_cell(path, "scenario", [1, 2], expected_configuration_signature="required") is None
