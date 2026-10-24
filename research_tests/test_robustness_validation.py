from scripts.robustness_validation import clustered_comparisons
from scripts.robustness_validation import METRICS


def test_robustness_effect_uses_dates_as_independent_clusters():
    rows = []
    for date, change in [('2025-02-15', 1.0), ('2025-05-15', 3.0)]:
        for regime in ('leo', 'geo'):
            for seed in range(5):
                baseline = {metric: 0.5 for metric in METRICS}
                optimized = {metric: 0.5 for metric in METRICS}
                optimized['custody_continuity'] += change
                rows.append({'date': date, 'regime': regime, 'seed': seed,
                    'configuration': 'baseline', **baseline})
                rows.append({'date': date, 'regime': regime, 'seed': seed,
                    'configuration': 'doe_recommended', **optimized})
    result = clustered_comparisons(rows)['doe_recommended']['custody_continuity']
    assert result['paired_change_vs_baseline'] == 2.0
    assert result['n_independent_dates'] == 2
    assert result['cluster_definition'].startswith('mean paired change')
