import pytest

from scripts.validation.replay_catalog_tasking_sample import compare_response


@pytest.mark.parametrize('field,value', [('detections',31),
                                       ('observable_custody',.31),
                                       ('empirical_block_replay',[{'source_date':'other'}])])
def test_action_replay_rejects_numerical_or_source_block_mutation(field,value):
    expected = dict(detections=30,observable_custody=.3,
                    empirical_block_replay=[{'source_date':'2023-01-01'}])
    with pytest.raises(ValueError,match=field):
        compare_response(expected,{**expected,field:value})
