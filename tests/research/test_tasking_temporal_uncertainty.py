import numpy as np
import pytest

from scripts.analysis.analyze_tasking_temporal_uncertainty import moving_block_means


def test_moving_block_bootstrap_is_reproducible_and_preserves_mean():
    values=np.array([1.0,2.0,3.0,4.0])
    first=moving_block_means(values,1,replicates=500,seed=7)
    second=moving_block_means(values,1,replicates=500,seed=7)
    assert np.array_equal(first,second)
    assert first.mean()==pytest.approx(values.mean(),abs=0.1)


def test_moving_block_bootstrap_rejects_invalid_series():
    with pytest.raises(ValueError,match='non-empty finite'):
        moving_block_means([1.0,float('nan')],1)
    with pytest.raises(ValueError,match='block length'):
        moving_block_means([1.0,2.0],3)
