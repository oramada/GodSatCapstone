import hashlib
import json

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

pytest.importorskip('cdflib')

from scripts.validation import audit_epop_attitude as auditor


def make_day(tmp_path, monkeypatch):
    data = tmp_path/'epop'
    parquet = data/'processed/2024/2024-01-01.parquet'
    saved_audit = data/'audits/2024/2024-01-01.json'
    parquet.parent.mkdir(parents=True); saved_audit.parent.mkdir(parents=True)
    times = np.datetime64('2024-01-01T00:00:00', 'ns') + np.arange(86400)*np.timedelta64(1, 's')
    table = pa.table({'timestamp_utc': pa.array(times, type=pa.timestamp('ns', tz='UTC')),
        'q1': np.ones(86400), 'q2': np.zeros(86400),
        'q3': np.zeros(86400), 'q4': np.zeros(86400),
        'data_source_previous': np.full(86400, 4, dtype=np.int8),
        'data_source_next': np.full(86400, 4, dtype=np.int8)})
    pq.write_table(table, parquet)
    raw = data/'source.zip'; raw.write_bytes(b'source bytes checked before the mocked CDF parser')
    counts = {str(code): (86400 if code == 4 else 0) for code in range(7)}
    saved_audit.write_text(json.dumps({'status': 'validated', 'date_utc': '2024-01-01',
        'parquet_path': str(parquet), 'samples': 86400,
        'source_zip_path': str(raw), 'source_zip_sha256': hashlib.sha256(raw.read_bytes()).hexdigest(),
        'source_previous_counts': counts, 'source_next_counts': counts,
        'attitude_solution_dropout_events': 0, 'longest_attitude_solution_dropout_seconds': 0}))
    manifest = {'status': 'completed', 'requested_days': 1, 'days_processed': 1,
        'not_published_dates': [], 'per_day_status': {'2024-01-01': 'validated'}}
    (data/'manifest.json').write_text(json.dumps(manifest))
    monkeypatch.setattr(auditor, 'ROOT', tmp_path)
    monkeypatch.setattr(auditor, 'parse_attquat_zip', lambda payload: (table, {}))
    return data, table, parquet, manifest


def test_source_replay_catches_changed_orientation_that_preserves_unit_norm_and_counts(tmp_path, monkeypatch):
    data, table, parquet, _ = make_day(tmp_path, monkeypatch)
    assert auditor.audit(data, reparse_sources=True)['source_cdf_days_replayed'] == 1
    changed = table.set_column(table.schema.get_field_index('q1'), 'q1', pa.array(np.zeros(86400)))
    changed = changed.set_column(changed.schema.get_field_index('q2'), 'q2', pa.array(np.ones(86400)))
    pq.write_table(changed, parquet)
    assert auditor.audit(data)['status'] == 'passed_structural_and_statistical'
    result = auditor.audit(data, reparse_sources=True)
    assert result['status'] == 'failed'
    assert any('does not reproduce Parquet column q1' in item['error'] for item in result['failures'])


def test_absence_audit_rejects_a_listing_that_actually_contains_an_attitude_product(tmp_path, monkeypatch):
    data, _, _, manifest = make_day(tmp_path, monkeypatch)
    day = '2024-01-02'; manifest['not_published_dates'] = [day]
    manifest['per_day_status'][day] = 'not_published'
    (data/'manifest.json').write_text(json.dumps(manifest))
    path = data/f'availability/2024/{day}.json'; path.parent.mkdir(parents=True)
    body = b'<table><tr><td>CAS_AttQuat_20240102_product.cdf.zip</td></tr></table>'
    path.with_suffix('.html').write_bytes(body)
    path.write_text(json.dumps({'date_utc': day, 'directory_url': 'https://epop-data.phys.ucalgary.ca/2024/01/02/',
        'checked_utc': '2026-10-24T00:00:00Z', 'products': [], 'http_status': 200,
        'recognized_directory_listing': True, 'listing_sha256': hashlib.sha256(body).hexdigest()}))
    result = auditor.audit(data, verify_absence=True)
    assert result['status'] == 'failed'
    assert result['publisher_absence_probes_verified'] == 0


def test_absence_audit_accepts_publishers_explicit_not_available_marker(tmp_path, monkeypatch):
    data, _, _, manifest = make_day(tmp_path, monkeypatch)
    day = '2024-01-02'
    manifest['not_published_dates'] = [day]
    manifest['per_day_status'][day] = 'not_published'
    (data/'manifest.json').write_text(json.dumps(manifest))
    path = data/f'availability/2024/{day}.json'; path.parent.mkdir(parents=True)
    body = b'<table><a href="/2024/01/02/CAS_AttQuat_20240102_not_available.txt">unavailable</a></table>'
    path.with_suffix('.html').write_bytes(body)
    path.write_text(json.dumps({'date_utc': day, 'directory_url': 'https://epop-data.phys.ucalgary.ca/2024/01/02/',
        'checked_utc': '2026-10-24T00:00:00Z', 'products': [], 'http_status': 200,
        'recognized_directory_listing': True, 'listing_sha256': hashlib.sha256(body).hexdigest()}))
    result = auditor.audit(data, verify_absence=True)
    assert result['status'] == 'passed_structural_and_statistical'
    assert result['publisher_absence_probes_verified'] == 1
