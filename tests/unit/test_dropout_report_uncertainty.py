import csv
import json
import sys

import numpy as np
import pytest

from scripts.analysis import analyze_dropout
from scripts.validation.audit_dropout_uncertainty import audit, block_reference


def test_cumulative_block_reference_matches_expanded_indices_with_truncated_last_block():
    values = [.1, .4, -.2, .05, .7, -.3, .2]
    expected = analyze_dropout.moving_block_interval(values, 3, samples=5000, seed=12)
    np.testing.assert_allclose(block_reference(values, 3, 5000, 12), expected, atol=1e-14, rtol=0)


def test_independent_audit_rejects_tampered_report_interval(tmp_path, monkeypatch):
    dates = ['2025-01-01', '2025-01-02', '2025-01-03']
    rates = [0., .2]
    metrics = ['custody_continuity', 'observable_custody', 'slew_energy_proxy',
               'false_track_proxy', 'conflict_rate', 'dropout_rate_observed']
    rows = []
    for index, date in enumerate(dates):
        for rate in rates:
            for model in [11, 22]:
                for replicate in [0, 1]:
                    value = .5+.01*index+.001*model+.01*replicate-rate*(index+1)/4
                    rows.append(dict(date=date, regime='leo', mode='burst', model_seed=model,
                        replicate=replicate, dropout_probability=rate, **{metric: value for metric in metrics}))
    with (tmp_path/'dropout_responses.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    summary = {'dates': dates, 'rates': rates, 'modes': ['burst'], 'orbit_regimes': ['leo'],
        'metrics': {f'leo:burst:{rate:g}': {metric: {} for metric in metrics} for rate in rates},
        'paired_vs_zero_dropout': {f'leo:burst:{metric}': {str(rate): {} for rate in rates} for metric in metrics[:4]},
        'interpretation': 'Test fixture', 'policy': 'fixture', 'model_checkpoint_count': 2,
        'replicates_per_date_regime_mode_rate': 2}
    path = tmp_path/'dropout_summary.json';path.write_text(json.dumps(summary))
    monkeypatch.setattr(sys, 'argv', ['analyze_dropout.py', str(tmp_path)])
    analyze_dropout.main()
    assert audit(tmp_path)['moving_block_intervals_checked'] == 8
    summary = json.loads(path.read_text())
    summary['paired_vs_zero_dropout']['leo:burst:custody_continuity']['0.2']['moving_block_bootstrap_ci95_by_date_block']['3']['upper'] += .01
    path.write_text(json.dumps(summary))
    with pytest.raises(ValueError, match='Reported uncertainty statistic differs'):
        audit(tmp_path)
