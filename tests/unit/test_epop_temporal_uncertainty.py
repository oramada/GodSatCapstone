import numpy as np

from scripts.analysis.analyze_epop_temporal_uncertainty import block_interval


def test_unknown_days_are_excluded_without_imputing_available_or_unavailable_states():
    values = np.array([.25, .25, np.nan, .25, .25, .25, .25])
    assert block_interval(values, 3, replicates=50)['ci95'] == [.25, .25]


def test_long_calendar_blocks_expose_uncertainty_hidden_by_independent_day_resampling():
    values = np.r_[np.zeros(50), np.ones(50)]
    independent = block_interval(values, 1, replicates=1000)['ci95']
    persistent = block_interval(values, 50, replicates=1000)['ci95']
    assert persistent[1]-persistent[0] > 3*(independent[1]-independent[0])
