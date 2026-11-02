import datetime as dt
import hashlib
import json
import sys

import pyarrow as pa
import pyarrow.parquet as pq

from scripts.validation import audit_catalog_trajectory_refresh as auditor
from scripts.experiments import run_catalog_trajectory_refresh as runner


def test_refreshed_snapshot_uses_actual_revision_counts_dates_and_deterministic_duplicates(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, 'ROOT', tmp_path)
    monkeypatch.setattr(auditor, 'ROOT', tmp_path)
    (tmp_path/'data').mkdir()
    (tmp_path/'data/state_vector_object_coverage.csv').write_text('norad_id,historical_element_rows\n7,1\n8,1\n')
    first = dt.datetime(2026, 10, 8, tzinfo=dt.timezone.utc)
    source = tmp_path/'source.parquet'
    def record(oid, epoch, anomaly):
        return {'norad_id': oid, 'epoch': epoch, 'inclination': 98., 'raan': 30.,
                'eccentricity': .001, 'arg_perigee': 10., 'mean_anomaly': anomaly,
                'mean_motion': 15., 'mean_motion_dot': 0., 'bstar': 0.,
                'intl_designator': 'TEST', 'altitude_km': 500.}
    pq.write_table(pa.Table.from_pylist([record(7, first, 2.), record(7, first, 1.),
                                       record(8, first+dt.timedelta(days=1), 0.)]), source)
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    source.with_suffix('.manifest.json').write_text(json.dumps({'source_revision': 'new-immutable-revision',
        'sha256': source_hash, 'size_bytes': source.stat().st_size}))
    baseline = tmp_path/'baseline'; baseline.mkdir()
    parts = []
    for day in range(2):
        start = first+dt.timedelta(days=day)
        rows = []
        for oid in [7, 8]:
            for index in range(6):
                rows.append({'norad_id': oid, 'time_utc': (start+dt.timedelta(hours=4*index)).isoformat(),
                             'element_epoch': None, 'sgp4_error': -1,
                             **{f'{axis}_teme_km': None for axis in 'xyz'},
                             **{f'v{axis}_teme_km_s': None for axis in 'xyz'}})
        path = baseline/f'part-{day}.parquet';pq.write_table(pa.Table.from_pylist(rows), path)
        parts.append({'file': path.name, 'start_inclusive': start.isoformat()})
    (baseline/'manifest.json').write_text(json.dumps({'source_revision': 'pinned-revision', 'parts': parts}))
    output = tmp_path/'refresh'
    monkeypatch.setattr(sys, 'argv', ['refresh', '--source', str(source), '--baseline', str(baseline),
        '--output', str(output), '--max-age-hours', '24'])
    runner.main()
    manifest = json.loads((output/'manifest.json').read_text())
    assert manifest['source_revision'] == 'new-immutable-revision'
    assert manifest['source_total_records'] == 3
    assert manifest['rows'] == 24
    result = auditor.audit(output)
    assert result['status'] == 'passed_source_and_baseline_reconciliation'
    assert result['trajectory_rows_checked'] == 24
    assert result['maximum_position_difference_km'] == 0
    assert result['independent_state_replays'] > 0
