import datetime as dt

from scripts.audit_catalog_element_gaps import grid_index


UTC = dt.timezone.utc
STEP_US = 4 * 60 * 60 * 1_000_000


def test_grid_index_counts_samples_strictly_before_boundary():
    start = dt.datetime(2022, 10, 9, tzinfo=UTC)
    assert grid_index(start - dt.timedelta(seconds=1), start, STEP_US, 6) == 0
    assert grid_index(start, start, STEP_US, 6) == 0
    assert grid_index(start + dt.timedelta(seconds=1), start, STEP_US, 6) == 1
    assert grid_index(start + dt.timedelta(hours=4), start, STEP_US, 6) == 1
    assert grid_index(start + dt.timedelta(hours=4, seconds=1), start, STEP_US, 6) == 2


def test_grid_index_clamps_to_requested_window():
    start = dt.datetime(2022, 10, 9, tzinfo=UTC)
    assert grid_index(start - dt.timedelta(days=5), start, STEP_US, 6) == 0
    assert grid_index(start + dt.timedelta(days=3), start, STEP_US, 6) == 6
