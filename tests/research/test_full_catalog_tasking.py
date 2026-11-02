import datetime as dt

import numpy as np

from scripts.experiments.run_full_catalog_tasking import load_cached_cell, simulate_condition, summarize_effects
from scripts.validation.audit_full_catalog_tasking import recompute_effects


def test_greedy_catalog_replay_skips_host_when_its_historical_state_goes_missing():
    ids = np.asarray([100, 200], dtype=np.int64)
    states = np.asarray([
        [[7000.0, 0.0, 0.0, 0.0, 7.0, 0.0],
         [8000.0, 0.0, 0.0, 0.0, 7.0, 0.0]],
        [[np.nan] * 6, [8001.0, 0.0, 0.0, 0.0, 7.0, 0.0]],
        [[np.nan] * 6, [8002.0, 0.0, 0.0, 0.0, 7.0, 0.0]],
    ])
    ages = np.zeros((3, 2), dtype=float)
    valid = np.asarray([[True, True], [False, True], [False, True]])
    times = [dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc),
             dt.datetime(2025, 1, 1, 0, 1, tzinfo=dt.timezone.utc),
             dt.datetime(2025, 1, 1, 0, 2, tzinfo=dt.timezone.utc)]
    config = {
        "agents": 1, "step_seconds": 60, "max_range_km": 6000,
        "field_of_regard_deg": 180, "slew_rate_deg_s": 2,
        "custody_seconds": 180, "slew_penalty": 0.03,
        "detection_probability": 0.98, "range_detection_penalty": 0.1,
        "stale_detection_penalty": 0.08, "max_element_age_hours": 72,
        "dropout_burst_persistence": 0.8,
    }
    result = simulate_condition(0, 0, 0.0, ids, states, ages, valid, times,
                                [100], config, seed=17)
    assert result["sensor_actions"] == 1
    assert result["host_state_missing_agent_steps"] == 1


def test_capacity_replay_keeps_the_maximum_host_cohort_out_of_every_target_denominator():
    ids = np.asarray([100, 200, 300], dtype=np.int64)
    states = np.asarray([
        [[7000.0, 0.0, 0.0, 0.0, 7.0, 0.0],
         [8000.0, 0.0, 0.0, 0.0, 7.0, 0.0],
         [9000.0, 0.0, 0.0, 0.0, 7.0, 0.0]],
        [[7001.0, 0.0, 0.0, 0.0, 7.0, 0.0],
         [8001.0, 0.0, 0.0, 0.0, 7.0, 0.0],
         [9001.0, 0.0, 0.0, 0.0, 7.0, 0.0]],
    ])
    ages = np.zeros((2, 3), dtype=float)
    valid = np.asarray([[True, True, False], [True, True, False]])
    times = [dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc),
             dt.datetime(2025, 1, 1, 0, 1, tzinfo=dt.timezone.utc)]
    config = {
        "agents": 1, "step_seconds": 60, "max_range_km": 6000,
        "field_of_regard_deg": 180, "slew_rate_deg_s": 2,
        "custody_seconds": 180, "slew_penalty": 0.03,
        "detection_probability": 0.98, "range_detection_penalty": 0.1,
        "stale_detection_penalty": 0.08, "max_element_age_hours": 72,
        "dropout_burst_persistence": 0.8,
    }
    one_host = simulate_condition(0, 0, 0.0, ids, states, ages, valid, times,
                                  [100], config, seed=17)
    nested_capacity = simulate_condition(0, 0, 0.0, ids, states, ages, valid,
                                         times, [100], config, seed=17,
                                         target_exclude_ids=[100, 200])
    assert one_host["valid_target_fraction"] == 0.5
    assert nested_capacity["valid_target_fraction"] == 0.0


def test_completed_legacy_cells_are_migrated_only_when_source_hash_matches(tmp_path):
    path = tmp_path / "cell.json"
    path.write_text('{"source_sha256":"abc","rows":[{"sensor_actions":2,"sensor_host_ids":[1,2]}]}\n')
    saved = load_cached_cell(path, "abc", [1, 2])
    assert saved["simulator_version"] == 2
    assert saved["rows"][0]["host_state_missing_agent_steps"] == 0
    assert load_cached_cell(path, "wrong", [1, 2]) is None


def test_empirical_profile_design_hash_invalidates_a_cell_from_another_dropout_model(tmp_path):
    path = tmp_path / "profile-cell.json"
    path.write_text('{"source_sha256":"abc","design_sha256":"profile-one",'
                    '"rows":[{"sensor_host_ids":[1,2]}]}\n')
    assert load_cached_cell(path, "abc", [1, 2], "profile-one") is not None
    assert load_cached_cell(path, "abc", [1, 2], "profile-two") is None


def test_empirical_profile_tasking_effects_use_profile_labels_and_paired_rate():
    dates = ["2022-10-22T00:00:00Z", "2022-10-29T00:00:00Z"]
    rows = []
    indexed = {}
    rate = 0.195
    for date in dates:
        for regime in ("leo", "meo", "geo", "heo"):
            baseline = {"date": date, "orbit_regime_sensor_hosts": regime,
                "requested_outage_rate": 0.0, "custody_continuity": 0.5,
                "observable_custody": 0.6, "mean_slew_energy_proxy": 0.1}
            treatment = {"date": date, "orbit_regime_sensor_hosts": regime,
                "requested_outage_rate": rate, "custody_continuity": 0.4,
                "observable_custody": 0.5, "mean_slew_energy_proxy": 0.2}
            rows.extend([baseline, treatment])
            indexed[(date, regime, 0.0)] = baseline
            indexed[(date, regime, rate)] = treatment
    direct = summarize_effects(rows, rate)
    audited = recompute_effects(indexed, dates, (0.0, rate))
    for actual, expected in zip(direct, audited):
        assert actual["custody_change_dropout_profile_minus_0"] == expected["custody_change_dropout_profile_minus_0"]
        assert np.isclose(actual["custody_change_dropout_profile_minus_0"]["mean"], -0.1)


def test_single_date_tasking_grid_is_descriptive_without_clustered_interval():
    date = "2022-10-22T00:00:00Z"
    indexed = {}
    for regime in ("leo", "meo", "geo", "heo"):
        for rate, custody, observable, slew in ((0.0, 0.5, 0.6, 0.1),
                                                (0.2, 0.4, 0.5, 0.2)):
            indexed[(date, regime, rate)] = {
                "custody_continuity": custody,
                "observable_custody": observable,
                "mean_slew_energy_proxy": slew,
            }
    results = recompute_effects(indexed, [date])
    assert len(results) == 4
    assert np.isclose(results[0]["custody_change_20pct_minus_0"]["mean"], -0.1)
    assert results[0]["custody_change_20pct_minus_0"]["ci95_date_clustered"] is None
