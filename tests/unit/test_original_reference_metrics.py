import pytest

from scripts.experiments.run_original_framework_reference import validate_metrics


def test_reference_ticks_must_reproduce_reported_custody_fraction():
    result={'custody_fraction':.5,'live_ticks':100,'custody_ticks':50,'q_active_ticks':60,
        'availability_ticks':80,'failure':True,'handoff_count':0,'handoff_latency_s':0,
        'qmode_reacquisition_s':0,'claimmap_conflicts':0}
    validate_metrics(result,.8)
    result['custody_fraction']=.6
    with pytest.raises(ValueError,match='does not reproduce'):
        validate_metrics(result,.8)
