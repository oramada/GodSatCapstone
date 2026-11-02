from copy import deepcopy

import pytest

from scripts.analysis.analyze_measured_tasking import attempt_loss, paired_process_effect


def baseline():
    return dict(custody_continuity=.2, observable_custody=.4,
                mean_slew_energy_proxy=.1, sensor_host_ids=list(range(6)),
                catalog_objects_in_episode=20, target_valid_step_count=1200,
                target_observable_step_count=600)


def test_pooled_attempt_loss_preserves_trial_denominator_and_excludes_empty_dates():
    result = attempt_loss([{'dropout_trials':10,'dropout_misses':10},
                           {'dropout_trials':90,'dropout_misses':0},
                           {'dropout_trials':0,'dropout_misses':0}])
    assert result['pooled_attempt_loss_fraction'] == .1
    assert result['mean_date_attempt_loss_fraction'] == .5
    assert result['dates_without_attempts'] == 1


def test_process_contrast_is_difference_of_paired_treatment_changes():
    zero = baseline()
    empirical = (zero, {**zero, 'observable_custody': .3})
    markov = (deepcopy(zero), {**zero, 'observable_custody': .35})
    assert paired_process_effect(empirical, markov, 'observable_custody') == pytest.approx(.05)


@pytest.mark.parametrize('field,value', [('sensor_host_ids', [6,7,8,9,10,11]),
                                      ('observable_custody', .5),
                                      ('target_observable_step_count', 700)])
def test_process_contrast_rejects_unpaired_baselines(field, value):
    zero = baseline()
    with pytest.raises(ValueError, match='baselines differ'):
        paired_process_effect((zero,zero), ({**zero,field:value},zero), 'observable_custody')


def test_process_contrast_rejects_denominator_change_within_treatment():
    zero = baseline()
    with pytest.raises(ValueError, match='denominator'):
        paired_process_effect((zero, {**zero, 'target_observable_step_count': 700}),
                              (zero,zero), 'observable_custody')
