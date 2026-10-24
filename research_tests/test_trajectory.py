import datetime as dt
import hashlib
import json
from types import SimpleNamespace
from pathlib import Path

import pytest

import godsat.trajectory as trajectory
from godsat.trajectory import trajectory_rows


UTC = dt.timezone.utc


def elements(epoch, mean_anomaly=0.0):
    return {
        'norad_id': 25544, 'epoch': epoch,
        'inclination': 51.64, 'raan': 120.0, 'eccentricity': 0.0005,
        'arg_perigee': 80.0, 'mean_anomaly': mean_anomaly,
        'mean_motion': 15.5, 'mean_motion_dot': 0.0, 'bstar': 0.00001,
    }


def test_trajectory_refreshes_at_historical_element_epochs():
    start = dt.datetime(2026, 1, 1, tzinfo=UTC)
    records = [elements(start), elements(start + dt.timedelta(seconds=120), 20.0)]
    rows = list(trajectory_rows(records, 25544, start,
        start + dt.timedelta(seconds=240), step_seconds=60))
    assert len(rows) == 4
    assert [row['sgp4_error'] for row in rows] == [0, 0, 0, 0]
    assert [row['element_epoch'] for row in rows] == [
        start.isoformat(), start.isoformat(),
        (start + dt.timedelta(seconds=120)).isoformat(),
        (start + dt.timedelta(seconds=120)).isoformat(),
    ]
    assert all(row['x_teme_km'] is not None for row in rows)


def test_trajectory_marks_missing_or_stale_elements_explicitly():
    start = dt.datetime(2026, 1, 1, tzinfo=UTC)
    old = start - dt.timedelta(hours=2)
    rows = list(trajectory_rows([elements(old)], 25544, start,
        start + dt.timedelta(minutes=2), step_seconds=60, max_age_hours=1))
    assert [row['sgp4_error'] for row in rows] == [-1, -1]
    assert all(row['x_teme_km'] is None for row in rows)


@pytest.mark.parametrize('value', ['2026-01-01T00:00:00', 'bad timestamp'])
def test_trajectory_rejects_timestamps_without_utc_timezone(value):
    end = dt.datetime(2026, 1, 2, tzinfo=UTC)
    with pytest.raises((ValueError, TypeError)):
        list(trajectory_rows([], 25544, value, end))


def test_trajectory_rejects_empty_interval_and_nonpositive_cadence():
    start = dt.datetime(2026, 1, 1, tzinfo=UTC)
    with pytest.raises(ValueError, match='start must be before end'):
        list(trajectory_rows([], 25544, start, start))
    with pytest.raises(ValueError, match='step_seconds must be positive'):
        list(trajectory_rows([], 25544, start, start + dt.timedelta(seconds=1), 0))


def test_export_manifest_hash_matches_written_csv(tmp_path, monkeypatch):
    start = dt.datetime(2026, 1, 1, tzinfo=UTC)
    record = elements(start)

    class FakeHistory:
        def __init__(self, root, cohort, window=None, max_age_hours=None):
            assert cohort == 'all'
            assert window == (start, start + dt.timedelta(minutes=2))
            assert max_age_hours == 72
            self.db = SimpleNamespace(close=lambda: None)

        def records(self, *args, **kwargs):
            return [record]

    monkeypatch.setattr(trajectory, 'History', FakeHistory)
    output = tmp_path / 'track.csv'
    manifest = trajectory.export_trajectory(
        25544, start, start + dt.timedelta(minutes=2), output,
        step_seconds=60, root=tmp_path)
    sidecar = json.loads(Path(str(output) + '.json').read_text())
    assert manifest['sample_counts']['successful'] == 2
    assert sidecar['csv_sha256'] == hashlib.sha256(output.read_bytes()).hexdigest()
