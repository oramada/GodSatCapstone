import numpy as np

from scripts.analysis.analyze_epop_block_model import markov_occupancy, source_window_distribution


def test_within_day_windows_do_not_create_interday_transitions():
    counts,probability=source_window_distribution([[True,True,True],[False,False,False]],2)
    np.testing.assert_array_equal(counts,[2,0,2])
    np.testing.assert_allclose(probability,[.5,0,.5])


def test_window_sampling_marginal_can_differ_from_uniform_minute_sampling():
    _,probability=source_window_distribution([[False,True,True],[False,False,False]],2)
    assert probability@np.arange(3)/2 == .375


def test_exact_markov_distribution_preserves_stationary_mean_and_endpoint_probabilities():
    rate,persistence,steps=.2,.8,60
    result=markov_occupancy(rate,persistence,steps)
    entry=rate*(1-persistence)/(1-rate)
    np.testing.assert_allclose(result.sum(),1,atol=1e-14)
    np.testing.assert_allclose(result@np.arange(steps+1)/steps,rate,atol=1e-14)
    np.testing.assert_allclose(result[0],(1-rate)*(1-entry)**(steps-1),atol=1e-14)
    np.testing.assert_allclose(result[-1],rate*persistence**(steps-1),atol=1e-14)
