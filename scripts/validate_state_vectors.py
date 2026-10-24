"""Audit exported historical state vectors against their source element archive."""
import argparse
import datetime as dt
import glob
import json
import pathlib

import duckdb
import numpy as np

from godsat.orbits import ROOT, satellite, julian


def parse_utc(value):
    parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Dates must include a UTC offset, for example 2022-10-09T00:00:00Z')
    return parsed.astimezone(dt.timezone.utc)


def validate_failure_codes(db, parts, source):
    """Confirm each distinct exported SGP4 failure against raw source elements."""
    output = db.execute('''SELECT DISTINCT norad_id,epoch,sgp4_error
        FROM read_parquet(?) WHERE sgp4_error<>0 ORDER BY norad_id,epoch,sgp4_error''',
        [parts]).fetchall()
    if not output:
        return {'unique_failed_keys_verified': 0, 'unique_failed_codes_verified': 0}
    source_rows = db.execute('''SELECT t.norad_id,t.epoch,t.inclination,t.raan,t.eccentricity,
        t.arg_perigee,t.mean_anomaly,t.mean_motion,t.mean_motion_dot,t.bstar
        FROM read_parquet(?) t JOIN
        (SELECT DISTINCT norad_id,epoch FROM read_parquet(?) WHERE sgp4_error<>0) f
        USING (norad_id,epoch)''', [str(source), parts]).fetchall()
    fields=('norad_id','epoch','inclination','raan','eccentricity','arg_perigee',
        'mean_anomaly','mean_motion','mean_motion_dot','bstar')
    codes={}
    for row in source_rows:
        element=dict(zip(fields,row))
        code=int(satellite(element).sgp4(*julian(element['epoch']))[0])
        codes.setdefault((int(element['norad_id']),element['epoch']),set()).add(code)
    for oid,epoch,expected in output:
        actual=codes.get((int(oid),epoch),set())
        if int(expected) not in actual:
            raise AssertionError(f'Source does not reproduce NORAD {oid} SGP4 error {expected} at {epoch}: {sorted(actual)}')
    return {'unique_failed_keys_verified':len({(int(row[0]),row[1]) for row in output}),
        'unique_failed_codes_verified':len(output)}


def validate(output, samples_per_year=50):
    output = pathlib.Path(output).resolve()
    manifest_path = output / 'manifest.json'
    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)
    manifest = json.loads(manifest_path.read_text())
    if manifest.get('cohort') != 'all':
        raise ValueError('This validator currently expects the all-catalog history export')
    start, end = parse_utc(manifest['start']), parse_utc(manifest['end_exclusive'])
    db = duckdb.connect()
    db.execute("SET TimeZone='UTC'")
    db.execute('SET threads=2')
    db.execute("SET memory_limit='1GB'")

    years = {}
    sample_errors = []
    total = 0
    for year in range(start.year, end.year + 1):
        parts = sorted(glob.glob(str(output / f'year={year}' / 'part-*.parquet')))
        if not parts:
            continue
        source = ROOT / f'data/raw/tle_{year}.parquet'
        lower = max(start, dt.datetime(year, 1, 1, tzinfo=dt.timezone.utc))
        upper = min(end, dt.datetime(year + 1, 1, 1, tzinfo=dt.timezone.utc))
        produced, ids, first, last, invalid, nonfinite, success_nonfinite, failure_finite = db.execute(
            """WITH states AS (SELECT *,
                      (isfinite(x_teme_km) AND isfinite(y_teme_km) AND isfinite(z_teme_km)
                       AND isfinite(vx_teme_km_s) AND isfinite(vy_teme_km_s)
                       AND isfinite(vz_teme_km_s)) AS state_finite
               FROM read_parquet(?))
               SELECT count(*), count(DISTINCT norad_id), min(epoch), max(epoch),
                      count(*) FILTER (WHERE sgp4_error != 0),
                      count(*) FILTER (WHERE NOT state_finite),
                      count(*) FILTER (WHERE sgp4_error=0 AND NOT state_finite),
                      count(*) FILTER (WHERE sgp4_error<>0 AND state_finite)
               FROM states""", [parts]).fetchone()
        # A partial run may not have produced later source-year files. Validate
        # every state already written, and compare counts whenever its source
        # archive is present. Missing source is only acceptable for an empty,
        # unstarted year; it cannot certify complete coverage.
        expected = None
        if source.is_file():
            expected = db.execute(
                'SELECT count(*) FROM read_parquet(?) WHERE epoch >= ? AND epoch < ?',
                [str(source), lower, upper]).fetchone()[0]
        error_counts = {str(int(code)): int(count) for code, count in db.execute(
            'SELECT sgp4_error,count(*) FROM read_parquet(?) GROUP BY 1', [parts]).fetchall()}
        year_manifest=manifest.get('years', {}).get(str(year), {})
        manifest_error_counts={str(int(code)):int(count) for code,count in
            year_manifest.get('error_counts',{}).items()}
        error_counts_match=('error_counts' in year_manifest and error_counts==manifest_error_counts)
        declared_complete = bool(year_manifest.get('complete'))
        count_matches = (expected is not None and produced == expected) if declared_complete else None
        if ((expected is not None and produced > expected) or
                (declared_complete and (expected is None or produced != expected))):
            raise AssertionError(f'Year {year} failed count/status checks: output={produced}, source={expected}, errors={invalid}, nonfinite={nonfinite}, manifest_error_counts_match={error_counts_match}, successful_nonfinite={success_nonfinite}, failed_finite={failure_finite}')
        if not error_counts_match or nonfinite!=invalid or success_nonfinite or failure_finite:
            raise AssertionError(f'Year {year} has inconsistent SGP4 failure/status counts: output={error_counts}, manifest={manifest_error_counts}, nonfinite={nonfinite}, errors={invalid}, successful_nonfinite={success_nonfinite}, failed_finite={failure_finite}')
        failure_validation=validate_failure_codes(db,parts,source)

        # Deterministically sample the output and join those exact catalog/epoch
        # keys back to the source elements, then independently run the same SGP4.
        db.execute('DROP TABLE IF EXISTS state_sample')
        db.execute("""CREATE TEMP TABLE state_sample AS
            SELECT norad_id,epoch,sgp4_error,x_teme_km,y_teme_km,z_teme_km,
                   vx_teme_km_s,vy_teme_km_s,vz_teme_km_s
            FROM read_parquet(?) WHERE sgp4_error=0
            ORDER BY hash(norad_id,epoch) LIMIT ?""", [parts, samples_per_year])
        db.execute('DROP TABLE IF EXISTS source_sample')
        db.execute("""CREATE TEMP TABLE source_sample AS
            SELECT t.norad_id,t.epoch,t.inclination,t.raan,t.eccentricity,t.arg_perigee,
                   t.mean_anomaly,t.mean_motion,t.mean_motion_dot,t.bstar
            FROM read_parquet(?) t JOIN state_sample s USING (norad_id,epoch)""", [str(source)])
        sample_count, source_sample_count = db.execute(
            'SELECT (SELECT count(*) FROM state_sample),(SELECT count(*) FROM source_sample)').fetchone()
        if source_sample_count < sample_count:
            raise AssertionError(f'Year {year} source lookup found only {source_sample_count}/{sample_count} sample keys')
        states = db.execute('SELECT * FROM state_sample ORDER BY norad_id,epoch').fetchall()
        elements = db.execute('SELECT * FROM source_sample ORDER BY norad_id,epoch').fetchall()
        source_by_key = {}
        for row in elements:
            source_by_key.setdefault((int(row[0]), row[1]), []).append(row)
        max_position_error_km = 0.0
        max_velocity_error_km_s = 0.0
        for state in states:
            oid, epoch = int(state[0]), state[1]
            position_differences=[];velocity_differences=[]
            for source_row in source_by_key[(oid, epoch)]:
                element = dict(zip(('norad_id','epoch','inclination','raan','eccentricity',
                    'arg_perigee','mean_anomaly','mean_motion','mean_motion_dot','bstar'), source_row))
                error, position, velocity = satellite(element).sgp4(*julian(epoch))
                if int(error) != int(state[2]):
                    continue
                position_differences.append(float(np.max(np.abs(np.asarray(position) - np.asarray(state[3:6])))))
                velocity_differences.append(float(np.max(np.abs(np.asarray(velocity) - np.asarray(state[6:9])))))
            if not position_differences:
                raise AssertionError(f'Year {year} NORAD {oid}: no duplicate source record reproduces SGP4 status')
            max_position_error_km=max(max_position_error_km,min(position_differences))
            max_velocity_error_km_s=max(max_velocity_error_km_s,min(velocity_differences))
        total += int(produced)
        years[str(year)] = {
            'output_records': int(produced), 'source_records_in_requested_interval': int(expected) if expected is not None else None,
            'distinct_catalog_ids': int(ids), 'first_epoch': first.isoformat(), 'last_epoch': last.isoformat(),
            'export_complete_for_year': declared_complete, 'count_match': count_matches,
            'sgp4_error_counts': error_counts, 'nonfinite_state_rows': int(nonfinite),
            'successful_state_rows':int(produced-invalid),'failed_state_rows':int(invalid),
            'successful_state_rows_all_finite':int(success_nonfinite)==0,
            'failed_state_rows_all_nonfinite':int(nonfinite)==int(invalid),
            'manifest_error_counts_match':error_counts_match,
            'source_failure_status_validation':failure_validation,
            'independent_sample_records': int(sample_count),
            'sample_max_abs_position_difference_km': max_position_error_km,
            'sample_max_abs_velocity_difference_km_s': max_velocity_error_km_s}
        if max_position_error_km > 1e-9 or max_velocity_error_km_s > 1e-12:
            sample_errors.append(year)

    db.close()
    manifest_at_completion = json.loads(manifest_path.read_text())
    snapshot_matches_current_export = (
        manifest_at_completion.get('signature') == manifest.get('signature')
        and manifest_at_completion.get('records_written') == total)
    report = {
        'status': 'failed' if sample_errors else 'validated_partial' if manifest.get('status') != 'completed' else 'validated_complete',
        'cohort': manifest['cohort'], 'source_revision': manifest.get('source_revision'),
        'requested_start': manifest['start'], 'requested_end_exclusive': manifest['end_exclusive'],
        'validated_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'export_records_written_at_validation_start': manifest.get('records_written'),
        'export_records_written_at_validation_completion': manifest_at_completion.get('records_written'),
        'snapshot_matches_current_export_at_validation_completion': snapshot_matches_current_export,
        'export_signature': manifest.get('signature'),
        'records_validated': total, 'export_status_at_validation': manifest.get('status'),
        'sample_size_per_year': samples_per_year, 'years': years,
        'criteria': ['Completed yearly partitions exactly match filtered source counts.',
            'Per-year SGP4 error counts exactly match the export manifest.',
            'Every successful state is finite; every failed state is explicitly non-finite and its error code reproduces from source elements.',
            'Deterministic samples of successful states reproduce from the source elements within numerical tolerance.'],
        'limitations': manifest.get('limitations', [])}
    report_path = output / 'validation.json'
    report_path.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'status': report['status'], 'records_validated': total,
        'years': {year: {'output_records': item['output_records'],
            'count_match': item['count_match'],
            'sample_max_abs_position_difference_km': item['sample_max_abs_position_difference_km'],
            'sample_max_abs_velocity_difference_km_s': item['sample_max_abs_velocity_difference_km_s']}
            for year,item in years.items()}, 'report': str(report_path)}, indent=2))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default=str(ROOT / 'data/historical_state_vectors_all'))
    parser.add_argument('--samples-per-year', type=int, default=50)
    args = parser.parse_args()
    if args.samples_per_year < 1:
        parser.error('--samples-per-year must be positive')
    validate(args.output, args.samples_per_year)


if __name__ == '__main__':
    main()
