import datetime as dt

import pytest

from scripts.awp_historical_sensitivity import (
    monthly_intervals, select_monthly_elements, summarize)


UTC = dt.timezone.utc


def test_monthly_intervals_are_start_inclusive_end_exclusive_and_clipped():
    intervals = monthly_intervals('2022-10-09T00:00:00Z', '2023-02-09T00:00:00Z')
    assert len(intervals) == 4
    assert intervals[0] == (dt.datetime(2022, 10, 9, tzinfo=UTC),
                            dt.datetime(2022, 11, 9, tzinfo=UTC))
    assert intervals[-1][1] == dt.datetime(2023, 2, 9, tzinfo=UTC)


def test_monthly_element_selection_chooses_midpoint_nearest_for_each_regime():
    object_ids = {'leo': 22, 'meo': 5, 'geo': 634, 'heo': 503}
    epochs = [dt.datetime(2022, 10, 20, tzinfo=UTC),
              dt.datetime(2022, 10, 30, tzinfo=UTC)]
    records = [{'norad_id': oid, 'epoch': epoch, 'tag': epoch.day}
        for oid in object_ids.values() for epoch in epochs]
    selected = select_monthly_elements(records, object_ids,
        '2022-10-09T00:00:00Z', '2022-11-09T00:00:00Z')
    assert len(selected) == 4
    assert {regime: row['tag'] for regime, _, _, row in selected} == {
        'leo': 20, 'meo': 20, 'geo': 20, 'heo': 20}


def test_monthly_element_selection_fails_instead_of_silently_dropping_gaps():
    with pytest.raises(ValueError, match='Missing source elements'):
        select_monthly_elements([], {'leo': 22},
            '2022-10-09T00:00:00Z', '2022-11-09T00:00:00Z')


def test_summary_reports_case_counts_and_separation_quantiles():
    rows = [{'orbit_regime': 'leo', 'model': 'awp_two_body_j2', 'lead_hours': 1,
             'position_separation_km': value, 'velocity_separation_km_s': value / 10}
            for value in (1.0, 2.0, 3.0)]
    summary = summarize(rows)
    assert summary == [{'orbit_regime': 'leo', 'model': 'awp_two_body_j2',
        'lead_hours': 1, 'n_monthly_cases': 3, 'n_valid_sgp4_comparisons': 3,
        'position_separation_median_km': 2.0,
        'position_separation_p95_km': pytest.approx(2.9),
        'position_separation_max_km': 3.0,
        'velocity_separation_median_km_s': 0.2,
        'velocity_separation_p95_km_s': pytest.approx(0.29)}]
