import csv
import hashlib
import json
import math

import pytest
from scipy.stats import t as student_t

from scripts.validation.audit_robustness_validation import METRICS, audit


def make_result(tmp_path):
    output = tmp_path / 'robustness'
    output.mkdir()
    campaign = tmp_path / 'campaign'
    models = campaign / 'models'
    models.mkdir(parents=True)
    checkpoint = models / 'validate.pt'
    checkpoint.write_bytes(b'checkpoint')
    digest = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    dates = ['2025-01-15T00:00:00Z', '2025-02-15T00:00:00Z']
    regimes, policies, seeds = ['leo'], ['baseline', 'doe_recommended'], [11]
    rows = []
    for date_index, date in enumerate(dates):
        for policy in policies:
            value = 0.0 if policy == 'baseline' else (1.0 + 2.0 * date_index)
            rows.append({'date': date, 'regime': 'leo', 'configuration': policy,
                         'seed': 11, 'sensor_host_fallback_to_all': False,
                         **{metric: value for metric in METRICS}})
    with (output / 'responses.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    half = float(student_t.ppf(.975, 1))
    comparisons = {
        policy: {metric: {'paired_change_vs_baseline': 2.0,
                          'date_clustered_ci95_half_width': half,
                          'n_independent_dates': 2}
                 for metric in METRICS}
        for policy in ['doe_recommended']
    }
    manifest = {
        'status': 'completed', 'design_signature': 'fixture',
        'design': {'campaign': str(campaign), 'dates': dates,
                   'regimes': regimes, 'policies': policies, 'seeds': seeds,
                   'checkpoint_sha256': {'validate.pt': digest}},
        'completed_cells': [{'date': date, 'regime': 'leo'} for date in dates],
        'unavailable_cells': [], 'fallback_cell_count': 0,
        'date_clustered_comparisons': comparisons,
    }
    (output / 'manifest.json').write_text(json.dumps(manifest))
    return output


def test_robustness_audit_reconciles_rows_hashes_and_effects(tmp_path):
    report = audit(make_result(tmp_path))
    assert report['status'] == 'completed_valid'
    assert report['dimensions']['observed_rows'] == 4
    assert report['row_audit']['unique_design_rows'] == 4
    assert report['saved_comparison_summary_matches'] is True
    assert math.isclose(
        report['independent_date_clustered_comparisons']['doe_recommended']
        ['custody_continuity']['paired_change_vs_baseline'], 2.0)


def test_robustness_audit_rejects_duplicate_rows(tmp_path):
    output = make_result(tmp_path)
    response_path = output / 'responses.csv'
    with response_path.open() as stream:
        existing = stream.read()
    with response_path.open('a') as stream:
        stream.write(existing.splitlines()[1] + '\n')
    with pytest.raises(AssertionError, match='integrity audit failed'):
        audit(output)
    report = json.loads((output / 'independent_integrity_audit.json').read_text())
    assert report['status'] == 'failed_validation'
    assert report['row_audit']['duplicate_rows'] == 1
