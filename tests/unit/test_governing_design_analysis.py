import itertools

import numpy as np
import pytest

from scripts.analysis.analyze_governing_design import budget_prefix, complete_contrasts
from godsat.design import screening_analysis


def test_complete_alias_space_retains_non_pair_residual_and_parseval_identity():
    base = np.array(list(itertools.product([-1., 1.], repeat=4)))
    a,b,c,d = base.T
    x = np.column_stack([a,b,c,d,a*b*c,a*b*d,a*c*d])
    y = 3 + 2*a + .25*b*c*d
    result = complete_contrasts(x,y)
    assert len(result['contrasts']) == 15
    assert sum(r['minimum_order']==1 for r in result['contrasts']) == 7
    assert sum(r['minimum_order']==2 for r in result['contrasts']) == 7
    assert result['higher_order_only_noise_df'] == 1
    assert sum(r['contrast_sum_of_squares'] for r in result['contrasts']) == pytest.approx(np.sum((y-y.mean())**2))
    main = next(r for r in result['contrasts'] if r['representative']=='A')
    assert main['effect'] == pytest.approx(4)
    future=screening_analysis(x,y)
    assert len(future['two_factor_alias_effects'])==7
    assert len(future['residual_alias_effects'])==8
    expected_variance=sum(r['contrast_sum_of_squares'] for r in result['contrasts'] if r['minimum_order']>1)/8
    assert future['pooled_residual_variance']==pytest.approx(expected_variance)


def test_budget_prefix_never_credits_incomplete_trial_or_skips_expensive_trial():
    rows = [{'name':str(i),'wall_seconds':cost,'objective':score,'hyperparameters':{}}
            for i,(cost,score) in enumerate([(4,1),(7,99),(1,500)])]
    result=budget_prefix(rows,10,'wall_seconds')
    assert result['completed_treatments']==1
    assert result['selected_treatment']=='0'
    assert result['remaining_budget']==6
    with pytest.raises(ValueError):budget_prefix(rows,3,'wall_seconds')
