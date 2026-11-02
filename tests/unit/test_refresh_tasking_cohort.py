import numpy as np
import pytest

from scripts.validation.check_tasking_source_refresh import project


def test_shared_cohort_projection_preserves_identity_and_state_slots():
    inputs=(np.array([10,20,30]),np.arange(36).reshape(2,3,6),
            np.array([[1,2,3],[4,5,6]]),np.array([[True,False,True],[False,True,True]]),['a','b'])
    ids,states,ages,valid,times=project(inputs,[10,30])
    np.testing.assert_array_equal(ids,[10,30])
    np.testing.assert_array_equal(states,inputs[1][:,[0,2]])
    np.testing.assert_array_equal(ages,[[1,3],[4,6]])
    np.testing.assert_array_equal(valid,[[True,True],[False,True]])
    assert times==['a','b']
    with pytest.raises(ValueError,match='absent'):project(inputs,[10,40])
    with pytest.raises(ValueError,match='sorted'):project(inputs,[30,10])
