import numpy as np
import pytest

from scripts.analysis.analyze_measured_tasking import describe
from scripts.analysis.analyze_tasking_temporal_uncertainty import moving_block_means
from scripts.validation.audit_measured_comparison import check_effect,circular_interval


def test_circular_sum_auditor_matches_wrapped_truncated_sampling():
    values=np.asarray([-.1,.3,.7,-.9,.2]*3)
    expected=np.quantile(moving_block_means(values,4,5000,seed=20261028),[.025,.975])
    np.testing.assert_allclose(circular_interval(values,4,seed=20261028),expected,atol=1e-14)


def test_changed_reported_interval_is_rejected():
    values=np.linspace(-.2,.2,30);reported=describe(values)
    reported['circular_moving_block_ci95']['13'][1]+=.01
    with pytest.raises(AssertionError):check_effect(reported,values)
