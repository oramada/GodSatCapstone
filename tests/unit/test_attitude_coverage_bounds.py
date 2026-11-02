import pytest

from scripts.validation.audit_epop_coverage_bounds import bounds


def test_missing_days_are_unknown_rather_than_automatically_outages_or_successes():
    result = bounds(100, 50, 200)
    assert result['published_sample_unavailability_fraction'] == .5
    assert result['whole_window_unavailability_fraction_bounds'] == [.25, .75]
    assert result['unobserved_samples'] == 100


def test_complete_coverage_collapses_missingness_bounds_but_not_a_sampling_interval():
    assert bounds(100, 25, 100)['whole_window_unavailability_fraction_bounds'] == [.25, .25]


def test_missingness_bounds_reject_inconsistent_counts():
    with pytest.raises(ValueError):
        bounds(101, 10, 100)
