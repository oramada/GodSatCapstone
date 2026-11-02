import datetime as dt

import duckdb
import numpy as np
import pytest

from godsat.orbits import History, julian, satellite
from godsat.scenario import cache_key, prepare
from godsat.dropout import quarterly_dates, monthly_dates


def write_history(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    db = duckdb.connect()
    db.execute("""CREATE TABLE history (
        norad_id INTEGER, epoch TIMESTAMPTZ, inclination FLOAT, raan FLOAT,
        eccentricity FLOAT, arg_perigee FLOAT, mean_anomaly FLOAT,
        mean_motion FLOAT, mean_motion_dot FLOAT, bstar FLOAT)""")
    db.executemany("INSERT INTO history VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    db.execute("COPY history TO ? (FORMAT PARQUET)", [str(path)])
    db.close()


def test_history_can_read_all_catalog_and_payload_cohorts(tmp_path):
    epoch = dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc)
    row = (123, epoch, 50., 20., .001, 40., 60., 15., 0., 0.)
    write_history(tmp_path / "data/raw/tle_2025.parquet", [row])
    write_history(tmp_path / "data/current_payload_orbit_history.parquet", [row])
    write_history(tmp_path / "data/current_active_payload_orbit_history.parquet", [row])

    all_history = History(tmp_path, "all")
    payload_history = History(tmp_path, "current_payload")
    active_history = History(tmp_path, "current_active_payload")
    try:
        assert [r["norad_id"] for r in all_history.snapshot(epoch)] == [123]
        assert [r["norad_id"] for r in payload_history.snapshot(epoch)] == [123]
        assert [r["norad_id"] for r in active_history.snapshot(epoch)] == [123]
    finally:
        all_history.db.close()
        payload_history.db.close()
        active_history.db.close()


def test_windowed_history_reads_only_years_covering_query_and_freshness_lookback(tmp_path):
    start = dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc)
    end = start + dt.timedelta(hours=1)
    write_history(tmp_path / "data/raw/tle_2022.parquet", [
        (25544, dt.datetime(2022, 12, 31, 20, tzinfo=dt.timezone.utc),
         50., 20., .001, 40., 60., 15., 0., 0.)])
    write_history(tmp_path / "data/raw/tle_2023.parquet", [
        (25544, start - dt.timedelta(minutes=30),
         50., 20., .001, 40., 60., 15., 0., 0.)])
    write_history(tmp_path / "data/raw/tle_2024.parquet", [
        (25544, start + dt.timedelta(minutes=30),
         50., 20., .001, 40., 60., 15., 0., 0.)])

    history = History(tmp_path, "all", window=(start, end), max_age_hours=2)
    try:
        assert [path.name for path in history.paths] == [
            "tle_2023.parquet", "tle_2024.parquet"]
        rows = history.records(start, end, max_age=2, ids=[25544])
        assert [row["epoch"] for row in rows] == [
            start - dt.timedelta(minutes=30), start + dt.timedelta(minutes=30)]
    finally:
        history.db.close()


def test_duplicate_object_epochs_use_stable_element_tiebreak(tmp_path):
    epoch = dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc)
    base = (25544, epoch, 50., 20., .001, 40.)
    first = base + (10., 15., 0., 0.)
    last = base + (20., 15., 0., 0.)
    write_history(tmp_path / "data/raw/tle_2025.parquet", [first, last])
    history = History(tmp_path, "all")
    try:
        rows = history.records(epoch, epoch)
        assert [row["mean_anomaly"] for row in rows] == [10., 20.]
        assert history.snapshot(epoch)[0]["mean_anomaly"] == 20.
    finally:
        history.db.close()


def test_history_replay_vectorized_sgp4_matches_direct_per_object_results(tmp_path):
    start = dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc)
    later = start + dt.timedelta(hours=6)
    rows = [
        (123, start, 50., 20., .001, 40., 60., 15., 0., 0.),
        (456, later, 70., 80., .01, 90., 120., 2., 0., 0.),
    ]
    write_history(tmp_path / "data/raw/tle_2025.parquet", rows)
    history = History(tmp_path, "all")
    times = [start, later + dt.timedelta(hours=6)]
    try:
        states, ages, errors, epochs = history.replay([123, 456], times, max_age=24)
        grouped = {123: [], 456: []}
        for record in history.records(times[0], times[-1], max_age=24, ids=[123, 456]):
            grouped[record["norad_id"]].append(record)
        cached = history.replay([123, 456], times, max_age=24, grouped_records=grouped)
        assert np.array_equal(states, cached[0], equal_nan=True)
        assert np.array_equal(ages, cached[1])
        assert np.array_equal(errors, cached[2])
        assert np.array_equal(epochs, cached[3])
        assert errors.tolist() == [[0, -1], [0, 0]]
        assert ages[0, 1] == float("inf")
        assert epochs[0, 1] == ""
        for time_index, time in enumerate(times):
            for object_index, row in enumerate(rows):
                if time < row[1]:
                    continue
                expected_error, expected_position, expected_velocity = satellite(
                    history.records(row[1], row[1], ids=[row[0]])[0]
                ).sgp4(*julian(time))
                assert errors[time_index, object_index] == expected_error
                assert np.allclose(
                    states[time_index, object_index],
                    [*expected_position, *expected_velocity],
                    rtol=0,
                    atol=1e-12,
                )
    finally:
        history.db.close()


def test_scenario_cache_separates_cohort_choices():
    base = {
        "agents": 6, "targets": 18, "duration_minutes": 60,
        "step_seconds": 60, "max_element_age_hours": 72,
        "max_range_km": 6000,
    }
    payload_targets = {**base, "target_cohort": "current_payload"}
    all_targets = {**base, "target_cohort": "all"}
    assert cache_key("2026-10-01T00:00:00Z", payload_targets, "geo") != cache_key(
        "2026-10-01T00:00:00Z", all_targets, "geo"
    )
    assert cache_key("2026-10-01T00:00:00Z", base, "geo") != cache_key(
        "2026-10-01T00:00:00Z", {**base, "propagation_model": "awp_j2"}, "geo"
    )


def test_scenario_requires_explicit_opt_in_before_using_non_payload_sensor_hosts(tmp_path):
    with pytest.raises(ValueError, match="allow_non_payload_sensor_hosts=true"):
        prepare("2026-10-01T00:00:00Z", {"sensor_cohort": "all"}, root=tmp_path)

    with pytest.raises(FileNotFoundError, match="Historical TLE/OMM archives"):
        prepare("2026-10-01T00:00:00Z", {
            "agents": 1, "targets": 1, "duration_minutes": 2,
            "step_seconds": 60, "max_element_age_hours": 72,
            "max_range_km": 6000, "sensor_cohort": "all",
            "allow_non_payload_sensor_hosts": True,
        }, root=tmp_path)


def test_quarterly_dropout_dates_span_archive_and_keep_calendar_day():
    dates=quarterly_dates()
    assert len(dates)==17
    assert dates[0]=='2022-10-15T00:00:00Z'
    assert dates[-1]=='2026-10-01T00:00:00Z'


def test_monthly_dropout_dates_cover_four_year_history_with_valid_utc_samples():
    dates=monthly_dates()
    assert len(dates)==48
    assert dates[0]=='2022-10-15T00:00:00Z'
    assert dates[-1]=='2026-09-15T00:00:00Z'
    assert len(set(dates))==len(dates)
    assert all(date.endswith('T00:00:00Z') for date in dates)
