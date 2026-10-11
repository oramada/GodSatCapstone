import hashlib
import json

from godsat.dropout import build_checkpoint_provenance, parse_response_row


def test_checkpoint_provenance_identifies_model_source_and_hash(tmp_path):
    checkpoint = tmp_path / 'policy.pt'
    checkpoint.write_bytes(b'fixture checkpoint bytes')
    summary = {
        'study_kind': 'four-regime study',
        'screening_runs': 16,
        'rsm_runs': 15,
        'bayesian_runs': 31,
        'validation_retrains': 15,
        'sensor_cohort': 'current_payload',
        'target_cohort': 'all',
        'scenario_regimes': {'training': ['leo', 'meo', 'geo', 'heo']},
        'heldout_test_dates': ['2026-10-01T00:00:00Z'],
    }

    result = build_checkpoint_provenance('outputs/study', summary, checkpoint, 101)

    assert result['checkpoint_sha256'] == hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    assert result['source_study_kind'] == 'four-regime study'
    assert result['source_campaign_counts']['rsm_runs'] == 15
    assert result['source_cohorts'] == {'sensor': 'current_payload', 'target': 'all'}
    assert result['source_training_regimes'] == ['leo', 'meo', 'geo', 'heo']
    json.dumps(result)


def test_resumed_dropout_response_rows_restore_numeric_types():
    result = parse_response_row({
        'date': '2026-10-01T00:00:00Z', 'regime': 'leo', 'mode': 'burst',
        'replicate': '3', 'seed': '7444', 'model_seed': '211',
        'dropout_probability': '0.2', 'custody_continuity': '0.75',
    })

    assert result['replicate'] == 3
    assert result['seed'] == 7444
    assert result['model_seed'] == 211
    assert result['dropout_probability'] == 0.2
    assert result['custody_continuity'] == 0.75
