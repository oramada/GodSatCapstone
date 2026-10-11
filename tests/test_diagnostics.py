import json
from pathlib import Path

from godsat.diagnostics import environment_report


def test_environment_report_explains_missing_paper_inputs(tmp_path):
    data = tmp_path / 'data'
    (data / 'raw').mkdir(parents=True)
    source_root = Path(__file__).resolve().parents[1]
    manifest = json.loads((source_root / 'data/raw/source-manifest.json').read_text())
    (data / 'raw/source-manifest.json').write_text(json.dumps(manifest))

    report = environment_report({'sensor_cohort': 'current_payload'}, root=tmp_path)

    assert report['python_supported']
    assert not report['archive_ready']
    assert not report['catalog_snapshot_ready']
    assert not report['cohort_ready']
    assert not report['data_ready']
    assert report['next_data_step'] == (
        f'Run: "{report["python_executable"]}" scripts/fetch_four_year_data.py'
    )
    assert report['next_cohort_step'] == (
        f'Run: "{report["python_executable"]}" scripts/export_current.py'
    )
