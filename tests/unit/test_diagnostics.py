import json
from pathlib import Path

from godsat.diagnostics import environment_report


def test_environment_report_explains_missing_paper_inputs(tmp_path):
    data = tmp_path / 'data'
    (data / 'raw').mkdir(parents=True)
    source_root = Path(__file__).resolve().parents[2]
    manifest = json.loads((source_root / 'data/raw/source-manifest.json').read_text())
    (data / 'raw/source-manifest.json').write_text(json.dumps(manifest))

    report = environment_report({'sensor_cohort': 'current_payload'}, root=tmp_path)

    assert report['python_supported']
    assert not report['archive_ready']
    assert not report['catalog_snapshot_ready']
    assert not report['cohort_ready']
    assert not report['data_ready']
    assert report['next_data_step'] == (
        f'Run: "{report["python_executable"]}" scripts/data/fetch_four_year_data.py'
    )
    assert report['next_cohort_step'] == (
        f'Run: "{report["python_executable"]}" scripts/data/export_current.py'
    )


def test_environment_report_finds_downloaded_archives_in_raw_directory(tmp_path):
    data = tmp_path / 'data'
    raw = data / 'raw'
    raw.mkdir(parents=True)
    (raw / 'source-manifest.json').write_text(json.dumps({
        'files': [{'path': 'data/tle_2022.parquet', 'lfs': {'size': 3}}]
    }))
    (raw / 'tle_2022.parquet').write_bytes(b'abc')
    (raw / 'satcat.csv').write_text('catalog snapshot')
    (data / 'current_payload_orbit_history.parquet').touch()

    report = environment_report({'sensor_cohort': 'current_payload'}, root=tmp_path)

    assert report['data_ready']
    assert report['archive'][0]['path'] == 'data/raw/tle_2022.parquet'
    assert report['archive'][0]['actual_bytes'] == 3

    (raw / 'tle_2022.parquet').rename(data / 'tle_2022.parquet')
    assert not environment_report({'sensor_cohort': 'current_payload'}, root=tmp_path)['archive_ready']
