import csv
import json
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from index_state_vector_coverage import build


def make_fixture(root, manifest_rows=2):
    source = root / 'data/historical_state_vectors_all/year=2022'
    source.mkdir(parents=True)
    part = source / 'part-00000.parquet'
    db = duckdb.connect()
    db.execute(f'''COPY (
        SELECT * FROM (VALUES
            (5, TIMESTAMPTZ '2022-10-10 00:00:00+00', 0),
            (6, TIMESTAMPTZ '2022-10-11 00:00:00+00', 2)
        ) AS t(norad_id, epoch, sgp4_error)
    ) TO '{part}' (FORMAT PARQUET)''')
    db.close()

    raw = root / 'data/raw'
    raw.mkdir(parents=True)
    archive = raw / 'tle_2022.parquet'
    db = duckdb.connect()
    db.execute(f'''COPY (
        SELECT * FROM (VALUES
            (5, TIMESTAMPTZ '2022-10-10 00:00:00+00'),
            (6, TIMESTAMPTZ '2022-10-11 00:00:00+00'),
            (7, TIMESTAMPTZ '2022-10-12 00:00:00+00')
        ) AS t(norad_id, epoch)
    ) TO '{archive}' (FORMAT PARQUET)''')
    db.close()

    manifest = {'status': 'completed', 'signature': 'fixture-signature',
                'start': '2022-01-01T00:00:00+00:00',
                'end_exclusive': '2023-01-01T00:00:00+00:00',
                'years': {'2022': {'complete': True}},
                'cohort': 'all', 'records_written': manifest_rows,
                'model': 'fixture SGP4', 'frame': 'TEME'}
    (root / 'data/historical_state_vectors_all/manifest.json').write_text(
        json.dumps(manifest))
    with (root / 'data/history_coverage.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=[
            'norad_id', 'records', 'first_epoch', 'last_epoch'])
        writer.writeheader()
        writer.writerows([
            {'norad_id': 5, 'records': 1, 'first_epoch': '2022-10-10',
             'last_epoch': '2022-10-10'},
            {'norad_id': 6, 'records': 1, 'first_epoch': '2022-10-11',
             'last_epoch': '2022-10-11'},
            {'norad_id': 7, 'records': 1, 'first_epoch': '2022-10-12',
             'last_epoch': '2022-10-12'},
        ])


def test_index_matches_manifest_and_keeps_unmaterialized_objects(tmp_path):
    make_fixture(tmp_path)
    output = tmp_path / 'data/state_vector_object_coverage.csv'

    summary = build(tmp_path, output)

    assert summary['status'] == 'completed'
    assert summary['snapshot_matches_manifest'] is True
    assert summary['parquet_records_scanned'] == 2
    assert summary['historical_objects_indexed'] == 3
    with output.open(newline='') as stream:
        rows = {int(row['norad_id']): row for row in csv.DictReader(stream)}
    assert int(rows[5]['successful_states']) == 1
    assert int(rows[6]['failed_states']) == 1
    assert int(rows[7]['state_vector_rows']) == 0
    assert float(rows[7]['materialized_fraction']) == 0.0
    assert int(rows[5]['historical_element_rows_2022']) == 1
    assert int(rows[5]['state_vector_rows_2022']) == 1
    assert int(rows[7]['historical_element_rows_2022']) == 1
    assert int(rows[7]['state_vector_rows_2022']) == 0


def test_index_flags_a_manifest_parquet_count_mismatch(tmp_path):
    make_fixture(tmp_path, manifest_rows=3)

    summary = build(tmp_path, tmp_path / 'data/index.csv')

    assert summary['status'] == 'snapshot_mismatch'
    assert summary['snapshot_matches_manifest'] is False
    assert summary['parquet_records_scanned'] == 2
    assert summary['indexed_state_rows'] == 2
