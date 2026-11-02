import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
from scripts.data.finalize_state_vectors import require_complete_export, verify_final_artifacts


def setup_final_fixture(root, export_status='completed'):
    raw = root / 'data/raw'
    raw.mkdir(parents=True)
    for year in (2022, 2023):
        (raw / f'tle_{year}.parquet').touch()
    (raw / 'manifest.json').write_text(json.dumps({'files': [
        {'path': f'data/tle_{year}.parquet'} for year in (2022, 2023)
    ]}))
    output = root / 'data/historical_state_vectors_all'
    output.mkdir(parents=True)
    manifest = {'status': export_status, 'signature': 'same', 'records_written': 3,
        'start': '2022-01-01T00:00:00+00:00',
        'end_exclusive': '2024-01-01T00:00:00+00:00',
        'years': {'2022': {'records': 1, 'complete': True, 'error_counts': {'0': 1}},
                  '2023': {'records': 2, 'complete': True, 'error_counts': {'0': 2}}}}
    (output / 'manifest.json').write_text(json.dumps(manifest))
    (root / 'data/state_vector_object_coverage.json').write_text(json.dumps({
        'status': 'completed', 'snapshot_matches_manifest': True,
        'parquet_records_scanned': 3, 'historical_element_rows_indexed': 3,
        'historical_objects_indexed': 2}))
    (output / 'validation.json').write_text(json.dumps({
        'status': 'validated_complete',
        'snapshot_matches_current_export_at_validation_completion': True,
        'records_validated': 3,
        'years': {
            '2022': {'sgp4_error_counts': {'0': 1}, 'successful_state_rows': 1,
                     'failed_state_rows': 0, 'successful_state_rows_all_finite': True,
                     'failed_state_rows_all_nonfinite': True, 'manifest_error_counts_match': True,
                     'source_failure_status_validation': {'unique_failed_codes_verified': 0}},
            '2023': {'sgp4_error_counts': {'0': 2}, 'successful_state_rows': 2,
                     'failed_state_rows': 0, 'successful_state_rows_all_finite': True,
                     'failed_state_rows_all_nonfinite': True, 'manifest_error_counts_match': True,
                     'source_failure_status_validation': {'unique_failed_codes_verified': 0}}
        }}))
    (root / 'data/coverage.json').write_text(json.dumps({
        'history': {'records': 3, 'objects': 2},
        'state_vector_export': {'manifest_matches_parquet': True,
                                'parquet_records': 3,
                                'successful_sgp4_states': 3,
                                'failed_sgp4_states': 0}}))
    return manifest


def test_finalization_refuses_an_incomplete_export(tmp_path):
    setup_final_fixture(tmp_path, export_status='running')

    with pytest.raises(RuntimeError, match='Export is not complete'):
        require_complete_export(tmp_path)


def test_finalization_verifies_all_full_export_audits(tmp_path):
    manifest = setup_final_fixture(tmp_path)

    result = verify_final_artifacts(tmp_path, manifest)

    assert result['status'] == 'finalized'
    assert result['records'] == 3
    assert all(result['checks'].values())
