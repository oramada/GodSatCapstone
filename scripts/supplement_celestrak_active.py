"""Build a provenance-recorded state supplement from one saved CelesTrak GP snapshot.

This intentionally produces a separate dataset: the active-group snapshot is
not the complete historical catalog and must not be merged into the pinned
historical source archive without an explicit reconciliation step.
"""
import argparse
import datetime as dt
import hashlib
import json
import pathlib

import duckdb
import numpy as np

from export_state_vectors import state_batch
from godsat.orbits import julian, satellite


FIELDS = (
    'NORAD_CAT_ID', 'EPOCH', 'INCLINATION', 'RA_OF_ASC_NODE', 'ECCENTRICITY',
    'ARG_OF_PERICENTER', 'MEAN_ANOMALY', 'MEAN_MOTION', 'MEAN_MOTION_DOT', 'BSTAR',
)


def utc(value):
    parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def sha256(path):
    digest = hashlib.sha256()
    with pathlib.Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def supplement(snapshot, retrieved_at, start_exclusive, end_inclusive, output):
    snapshot = pathlib.Path(snapshot).expanduser().resolve()
    output = pathlib.Path(output).expanduser().resolve()
    if not snapshot.is_file():
        raise FileNotFoundError(snapshot)
    retrieved, lower, upper = map(utc, (retrieved_at, start_exclusive, end_inclusive))
    if lower >= upper or upper > retrieved:
        raise ValueError('Require start_exclusive < end_inclusive <= retrieved_at')

    records = json.loads(snapshot.read_text())
    if not isinstance(records, list):
        raise ValueError('CelesTrak JSON snapshot must contain a list of GP records')
    selected = []
    future_epochs = 0
    for record in records:
        missing = [name for name in FIELDS if name not in record]
        if missing:
            raise ValueError(f"Record {record.get('NORAD_CAT_ID')} lacks fields: {missing}")
        epoch = utc(str(record['EPOCH']))
        if epoch > retrieved:
            future_epochs += 1
        if lower < epoch <= upper:
            selected.append((
                int(record['NORAD_CAT_ID']), epoch,
                float(record['INCLINATION']), float(record['RA_OF_ASC_NODE']),
                float(record['ECCENTRICITY']), float(record['ARG_OF_PERICENTER']),
                float(record['MEAN_ANOMALY']), float(record['MEAN_MOTION']),
                float(record['MEAN_MOTION_DOT']), float(record['BSTAR']),
            ))
    if not selected:
        raise ValueError('No active-group records fall inside the requested supplement interval')
    old_manifest_path = output / 'manifest.json'
    output_parquet = output / 'active_gp_states.parquet'
    if old_manifest_path.exists():
        previous = json.loads(old_manifest_path.read_text())
        if (previous.get('source_snapshot_sha256') != sha256(snapshot)
                or previous.get('selected_epoch_start_exclusive') != lower.isoformat()
                or previous.get('selected_epoch_end_inclusive') != upper.isoformat()
                or not output_parquet.is_file()):
            raise FileExistsError(f'Existing supplement has different provenance or is incomplete: {output}')
    elif output_parquet.exists():
        raise FileExistsError(f'Unmanifested state file already exists: {output_parquet}')

    ids, epochs, errors, states = state_batch(selected)
    output.mkdir(parents=True, exist_ok=True)
    parquet = output_parquet
    temporary = parquet.with_suffix('.parquet.tmp')
    sql_path = str(temporary).replace("'", "''")
    db = duckdb.connect()
    db.execute("SET TimeZone='UTC'")
    db.execute('''COPY (SELECT unnest(?) AS norad_id,
        CAST(unnest(?) AS TIMESTAMPTZ) AS epoch,
        unnest(?) AS sgp4_error,
        unnest(?) AS x_teme_km, unnest(?) AS y_teme_km, unnest(?) AS z_teme_km,
        unnest(?) AS vx_teme_km_s, unnest(?) AS vy_teme_km_s, unnest(?) AS vz_teme_km_s)
        TO ''' + f"'{sql_path}'" + ''' (FORMAT PARQUET, COMPRESSION ZSTD)''',
        [ids, epochs, errors, *[states[:, i] for i in range(6)]])
    temporary.replace(parquet)
    error_counts = {str(int(code)): int(count) for code, count in
                    zip(*np.unique(errors, return_counts=True))}
    finite_rows = db.execute('''SELECT count(*) FROM read_parquet(?) WHERE
        isfinite(x_teme_km) AND isfinite(y_teme_km) AND isfinite(z_teme_km)
        AND isfinite(vx_teme_km_s) AND isfinite(vy_teme_km_s) AND isfinite(vz_teme_km_s)''',
        [str(parquet)]).fetchone()[0]
    produced, unique_ids, first_epoch, last_epoch, invalid_rows, outside_window = db.execute(
        '''SELECT count(*),count(DISTINCT norad_id),min(epoch),max(epoch),
            count(*) FILTER (WHERE sgp4_error != 0),
            count(*) FILTER (WHERE epoch <= ? OR epoch > ?)
           FROM read_parquet(?)''', [lower, upper, str(parquet)]).fetchone()
    if produced != len(selected) or unique_ids != len(selected) or invalid_rows != 0 or outside_window != 0:
        raise AssertionError('Supplement output count, uniqueness, error, or date-bound audit failed')
    source_by_id = {int(row[0]): row for row in selected}
    samples = db.execute('''SELECT norad_id,epoch,sgp4_error,x_teme_km,y_teme_km,z_teme_km,
        vx_teme_km_s,vy_teme_km_s,vz_teme_km_s FROM read_parquet(?)
        ORDER BY hash(norad_id,epoch) LIMIT 100''', [str(parquet)]).fetchall()
    max_position_error_km = 0.0
    max_velocity_error_km_s = 0.0
    for state in samples:
        row = source_by_id[int(state[0])]
        source = dict(zip(('norad_id','epoch','inclination','raan','eccentricity',
            'arg_perigee','mean_anomaly','mean_motion','mean_motion_dot','bstar'), row))
        error, position, velocity = satellite(source).sgp4(*julian(state[1]))
        if int(error) != int(state[2]):
            raise AssertionError(f'Independent sample SGP4 error code differs for NORAD {state[0]}')
        max_position_error_km = max(max_position_error_km,
            float(np.max(np.abs(np.asarray(position) - np.asarray(state[3:6])))))
        max_velocity_error_km_s = max(max_velocity_error_km_s,
            float(np.max(np.abs(np.asarray(velocity) - np.asarray(state[6:9])))))
    db.close()
    if finite_rows != len(selected):
        raise AssertionError(f'Only {finite_rows}/{len(selected)} generated states are finite')
    if max_position_error_km > 1e-9 or max_velocity_error_km_s > 1e-12:
        raise AssertionError('Independent sample SGP4 reproduction exceeded numerical tolerance')

    manifest = {
        'status': 'completed',
        'dataset_kind': 'supplemental active-group latest GP states',
        'source_url': 'https://celestrak.org/NORAD/elements/gp.php?GROUP=active&FORMAT=json',
        'retrieved_at_utc': retrieved.isoformat(),
        'source_snapshot': str(snapshot),
        'source_snapshot_sha256': sha256(snapshot),
        'source_snapshot_records': len(records),
        'future_epoch_records_excluded': future_epochs,
        'selected_epoch_start_exclusive': lower.isoformat(),
        'selected_epoch_end_inclusive': upper.isoformat(),
        'selected_records': len(selected),
        'distinct_norad_ids': len(set(int(x) for x in ids)),
        'first_selected_epoch': min(utc(str(r['EPOCH'])) for r in records
                                    if lower < utc(str(r['EPOCH'])) <= upper).isoformat(),
        'last_selected_epoch': max(utc(str(r['EPOCH'])) for r in records
                                   if lower < utc(str(r['EPOCH'])) <= upper).isoformat(),
        'state_output': parquet.name,
        'state_output_sha256': sha256(parquet),
        'frame': 'TEME',
        'units': {'position': 'km', 'velocity': 'km/s'},
        'model': 'SGP4 WGS-72 initialized from supplied OMM JSON mean elements',
        'sgp4_error_counts': error_counts,
        'finite_state_rows': finite_rows,
        'unique_output_norad_ids': unique_ids,
        'independent_sample_rows': len(samples),
        'independent_sample_max_abs_position_difference_km': max_position_error_km,
        'independent_sample_max_abs_velocity_difference_km_s': max_velocity_error_km_s,
        'output_first_epoch': first_epoch.isoformat(),
        'output_last_epoch': last_epoch.isoformat(),
        'limitations': [
            'This is a separate latest-element snapshot for CelesTrak GROUP=active, not the full historical catalog.',
            'Objects with no active-group element epoch in the selected interval are absent.',
            'No operational status or sensor-attitude/failure telemetry is inferred from membership in this group.',
            'States are reconstructed at irregular element epochs, not continuous fixed-cadence ephemerides.',
        ],
    }
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({k: v for k, v in manifest.items()
                      if k not in {'limitations', 'source_snapshot_sha256', 'state_output_sha256'}},
                     indent=2))
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', required=True)
    parser.add_argument('--retrieved-at', required=True)
    parser.add_argument('--start-exclusive', required=True)
    parser.add_argument('--end-inclusive', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    supplement(args.snapshot, args.retrieved_at, args.start_exclusive,
               args.end_inclusive, args.output)


if __name__ == '__main__':
    main()
