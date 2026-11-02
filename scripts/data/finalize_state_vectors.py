"""Run final full-catalog state-vector audits after the export is complete."""

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))

import argparse
import json
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUTPUT = pathlib.Path('data/historical_state_vectors_all')


def read_json(path):
    return json.loads(pathlib.Path(path).read_text())


def require_complete_export(root=ROOT):
    root = pathlib.Path(root).resolve()
    manifest = read_json(root / OUTPUT / 'manifest.json')
    archive_manifest = read_json(root / 'data/raw/manifest.json')
    start_year = int(manifest['start'][:4])
    end_year = int(manifest['end_exclusive'][:4])
    expected_sources = {
        pathlib.Path(item['path']).name
        for item in archive_manifest.get('files', [])
        if pathlib.Path(item['path']).name.startswith('tle_')
    }
    actual_sources = {path.name for path in (root / 'data/raw').glob('tle_*.parquet')}
    missing_sources = sorted(expected_sources - actual_sources)
    if missing_sources:
        raise RuntimeError(f'Historical source archives are missing: {missing_sources}')
    source_years = {int(name[4:8]) for name in expected_sources}
    required_years = [year for year in range(start_year, end_year + 1)
                      if year in source_years]
    incomplete = [year for year in required_years
                  if not manifest.get('years', {}).get(str(year), {}).get('complete')]
    if manifest.get('status') != 'completed' or incomplete:
        raise RuntimeError(
            f"Export is not complete (status={manifest.get('status')}, "
            f"incomplete source years={incomplete})")
    year_rows = sum(manifest['years'][str(year)]['records'] for year in required_years)
    if year_rows != manifest.get('records_written'):
        raise RuntimeError(
            f"Manifest total {manifest.get('records_written')} disagrees with "
            f"complete yearly totals {year_rows}")
    return manifest


def run(script, *args, root=ROOT):
    root = pathlib.Path(root).resolve()
    env = os.environ.copy()
    env['PYTHONPATH'] = str(root) + os.pathsep + env.get('PYTHONPATH', '')
    from importlib.util import find_spec
    category = 'data' if script == 'index_state_vector_coverage.py' else ('archive' if script == 'audit.py' else 'validation')
    module = f'scripts.{category}.{pathlib.Path(script).stem}'
    if find_spec(module) is None:
        raise ValueError(f'Unknown finalization tool: {module}')
    subprocess.run([sys.executable, '-m', module, *args],
                   cwd=root, env=env, check=True)


def verify_final_artifacts(root, initial_manifest):
    root = pathlib.Path(root).resolve()
    final_manifest = require_complete_export(root)
    if (final_manifest.get('signature') != initial_manifest.get('signature')
            or final_manifest.get('records_written') != initial_manifest.get('records_written')):
        raise RuntimeError('Export manifest changed while final audits were running')

    index = read_json(root / 'data/state_vector_object_coverage.json')
    validation = read_json(root / OUTPUT / 'validation.json')
    audit = read_json(root / 'data/coverage.json')
    declared_errors={}
    for year,summary in final_manifest.get('years',{}).items():
        for code,count in summary.get('error_counts',{}).items():
            declared_errors[(str(year),str(int(code)))]=int(count)
    validated_errors={}
    validation_years=validation.get('years',{})
    for year,summary in validation_years.items():
        for code,count in summary.get('sgp4_error_counts',{}).items():
            validated_errors[(str(year),str(int(code)))]=int(count)
    expected_failed=sum(count for (_,code),count in declared_errors.items() if code!='0')
    validation_failed=sum(int(summary.get('failed_state_rows',0)) for summary in validation_years.values())
    successful_rows=sum(int(summary.get('successful_state_rows',0)) for summary in validation_years.values())
    validation_finite_checks=all(
        summary.get('successful_state_rows_all_finite') is True
        and summary.get('failed_state_rows_all_nonfinite') is True
        and summary.get('manifest_error_counts_match') is True
        for summary in validation_years.values())
    source_failure_checks=all(
        int(summary.get('source_failure_status_validation',{}).get('unique_failed_codes_verified',0))
        >= len([key for key,count in declared_errors.items() if key[0]==str(year) and key[1]!='0' and count>0])
        for year,summary in validation_years.items())
    checks = {
        'index_status': index.get('status') == 'completed',
        'index_matches_manifest': index.get('snapshot_matches_manifest') is True,
        'index_rows_match_export': index.get('parquet_records_scanned') == final_manifest['records_written'],
        'index_source_rows_match_archive': index.get('historical_element_rows_indexed') == audit.get('history', {}).get('records'),
        'all_source_rows_have_reconstructed_states': index.get('historical_element_rows_indexed') == final_manifest['records_written'],
        'index_object_count_matches_archive': index.get('historical_objects_indexed') == audit.get('history', {}).get('objects'),
        'validation_status': validation.get('status') == 'validated_complete',
        'validation_snapshot_current': validation.get('snapshot_matches_current_export_at_validation_completion') is True,
        'validation_rows_match_export': validation.get('records_validated') == final_manifest['records_written'],
        'validation_error_counts_match_manifest': validated_errors == declared_errors,
        'failed_rows_match_manifest': validation_failed == expected_failed,
        'successful_and_failed_rows_cover_export': successful_rows + validation_failed == final_manifest['records_written'],
        'successful_rows_finite_and_failed_rows_flagged': validation_finite_checks,
        'source_reproduces_failed_error_codes': source_failure_checks,
        'audit_parquet_matches_manifest': audit.get('state_vector_export', {}).get('manifest_matches_parquet') is True,
        'audit_rows_match_export': audit.get('state_vector_export', {}).get('parquet_records') == final_manifest['records_written'],
        'audit_success_and_failure_counts_match_manifest': audit.get('state_vector_export', {}).get('successful_sgp4_states') == final_manifest['records_written'] - expected_failed and audit.get('state_vector_export', {}).get('failed_sgp4_states') == expected_failed,
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise RuntimeError(f'Final export audit failed checks: {failed}')
    return {'status': 'finalized', 'records': final_manifest['records_written'],
            'source_years': sorted(final_manifest['years'], key=int),
            'checks': checks}


def finalize(root=ROOT, samples_per_year=100):
    root = pathlib.Path(root).resolve()
    initial_manifest = require_complete_export(root)
    run('validate_state_vectors.py', '--samples-per-year', str(samples_per_year), root=root)
    # The object index joins history_coverage.csv, which audit.py generates.
    # Run that prerequisite first so a fresh clone can finalize its first export.
    run('audit.py', root=root)
    run('index_state_vector_coverage.py', root=root)
    return verify_final_artifacts(root, initial_manifest)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', default=str(ROOT))
    parser.add_argument('--samples-per-year', type=int, default=100)
    args = parser.parse_args()
    if args.samples_per_year < 1:
        parser.error('--samples-per-year must be positive')
    print(json.dumps(finalize(args.root, args.samples_per_year), indent=2))


if __name__ == '__main__':
    main()
