import copy

import pytest

from scripts.validation.audit_dropout_numerics import METRICS, PAIRED, compare_statistics, reproduce_statistics


def fixture():
    rows = []
    summary = {'metrics': {}, 'paired_vs_zero_dropout': {}}
    for rate in (0., .2):
        values = {'custody_continuity': .5 if rate == 0 else .25,
                  'observable_custody': .5 if rate == 0 else .25,
                  'slew_energy_proxy': .1, 'false_track_proxy': .1,
                  'conflict_rate': 0., 'dropout_rate_observed': rate}
        for date in ('d1', 'd2'):
            for replicate in range(2):
                rows.append(dict(date=date, regime='leo', mode='burst', model_seed=101,
                                 replicate=replicate, dropout_probability=rate, **values))
        condition = f'leo:burst:{rate:g}'
        summary['metrics'][condition] = {
            metric: {'mean': value, 'ci95_half_width': 0., 'n': 4,
                     'date_clustered_mean': value, 'date_clustered_ci95_half_width': 0., 'n_dates': 2}
            for metric, value in values.items()}
        for metric in PAIRED:
            change = -.25 if rate and metric in ('custody_continuity', 'observable_custody') else 0.
            summary['paired_vs_zero_dropout'].setdefault(f'leo:burst:{metric}', {})[str(rate)] = {
                'paired_mean_change': change, 'ci95_half_width': 0., 'n_pairs': 4,
                'date_clustered_mean_change': change, 'date_clustered_ci95_half_width': 0., 'n_dates': 2}
    return rows, summary


def test_numerical_audit_reproduces_paired_effects_and_detects_tampered_summary():
    rows, summary = fixture()
    reproduced = reproduce_statistics(rows)
    compare_statistics(reproduced, summary)
    corrupted = copy.deepcopy(summary)
    corrupted['metrics']['leo:burst:0.2']['custody_continuity']['mean'] = .99
    with pytest.raises(ValueError, match='Unreproduced summary statistic'):
        compare_statistics(reproduced, corrupted)


def test_numerical_audit_rejects_missing_baseline_and_nonfinite_response():
    rows, _ = fixture()
    with pytest.raises(ValueError, match='matched zero-outage'):
        reproduce_statistics([row for row in rows if row['dropout_probability']])
    rows[0][METRICS[0]] = float('nan')
    with pytest.raises(ValueError, match='Invalid dropout metric'):
        reproduce_statistics(rows)
