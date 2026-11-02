"""Propagate the cached active-group OMM snapshot to one common UTC epoch.

The result is a separately versioned current-state supplement. It is never
merged into the historical element archive or presented as historical data.
"""
from __future__ import annotations

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))


import argparse
import csv
import datetime as dt
import hashlib
import json
from pathlib import Path
import sys

import duckdb
import numpy as np
import pyarrow as pa

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from godsat.orbits import History, julian, satellite, utc

FIELDS = (
    'NORAD_CAT_ID', 'EPOCH', 'INCLINATION', 'RA_OF_ASC_NODE', 'ECCENTRICITY',
    'ARG_OF_PERICENTER', 'MEAN_ANOMALY', 'MEAN_MOTION', 'MEAN_MOTION_DOT', 'BSTAR',
)
ACTIVE_STATUS = {'+', 'B', 'P', 'S', 'X'}
MAX_AGE_HOURS = 72.0
DEFAULT_SNAPSHOT = ROOT / 'data/raw/snapshots/celestrak_active_2026-10-10T09-11-18Z.json'
DEFAULT_OUTPUT = ROOT / 'data/current_active_catalog_snapshot_2026-10-10'


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def parse_omm_epoch(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def satcat_records(path: Path) -> dict[int, dict[str, str]]:
    rows: dict[int, dict[str, str]] = {}
    with path.open(newline='') as stream:
        for row in csv.DictReader(stream):
            try:
                norad = int(row['NORAD_CAT_ID'])
            except (KeyError, ValueError, TypeError):
                continue
            if norad in rows:
                raise ValueError(f'Duplicate SATCAT identifier: {norad}')
            rows[norad] = row
    return rows


def omm_row(record: dict) -> dict:
    return {
        'norad_id': int(record['NORAD_CAT_ID']),
        'epoch': parse_omm_epoch(str(record['EPOCH'])),
        'inclination': float(record['INCLINATION']),
        'raan': float(record['RA_OF_ASC_NODE']),
        'eccentricity': float(record['ECCENTRICITY']),
        'arg_perigee': float(record['ARG_OF_PERICENTER']),
        'mean_anomaly': float(record['MEAN_ANOMALY']),
        'mean_motion': float(record['MEAN_MOTION']),
        'mean_motion_dot': float(record['MEAN_MOTION_DOT']),
        'bstar': float(record['BSTAR']),
    }


def export(snapshot: Path, output: Path, satcat_path: Path | None = None,
           max_age_hours: float = MAX_AGE_HOURS) -> dict:
    snapshot = snapshot.expanduser().resolve()
    output = output.expanduser().resolve()
    satcat_path = (satcat_path or ROOT / 'data/raw/satcat.csv').resolve()
    snapshot_manifest_path = snapshot.with_name(snapshot.stem + '.manifest.json')
    if not snapshot.is_file() or not snapshot_manifest_path.is_file() or not satcat_path.is_file():
        raise FileNotFoundError('Snapshot JSON, its manifest, and SATCAT are all required')
    if not np.isfinite(max_age_hours) or max_age_hours <= 0:
        raise ValueError('max_age_hours must be positive and finite')

    snapshot_manifest = json.loads(snapshot_manifest_path.read_text())
    if snapshot_manifest.get('sha256') != sha256(snapshot):
        raise ValueError('Active-group source snapshot hash does not match its manifest')
    query_epoch = utc(snapshot_manifest['retrieved_at_utc'])
    source = json.loads(snapshot.read_text())
    if not isinstance(source, list) or len(source) != int(snapshot_manifest['records']):
        raise ValueError('Active-group source snapshot record count is invalid')
    by_id = {}
    for record in source:
        missing = [key for key in FIELDS if key not in record]
        if missing:
            raise ValueError(f"OMM record {record.get('NORAD_CAT_ID')} lacks {missing}")
        norad = int(record['NORAD_CAT_ID'])
        if norad in by_id:
            raise ValueError(f'Duplicate active-group OMM identifier: {norad}')
        by_id[norad] = record

    catalog = satcat_records(satcat_path)
    historical = History(ROOT, 'all')
    try:
        historical_ids = {int(row[0]) for row in historical.db.execute(
            'SELECT DISTINCT norad_id FROM read_parquet(?)',
            [[str(path) for path in historical.paths]]).fetchall()}
    finally:
        historical.db.close()

    selected = []
    excluded_types = {}
    excluded_status = {}
    excluded_decayed = 0
    for norad, record in by_id.items():
        metadata = catalog.get(norad)
        if metadata is None or metadata.get('OBJECT_TYPE') != 'PAY' or metadata.get('ORBIT_CENTER') != 'EA':
            kind = (metadata or {}).get('OBJECT_TYPE', 'missing_satcat')
            excluded_types[kind] = excluded_types.get(kind, 0) + 1
            continue
        if metadata.get('DECAY_DATE', '').strip():
            excluded_decayed += 1
            continue
        status = metadata.get('OPS_STATUS_CODE', '').strip()
        if status not in ACTIVE_STATUS:
            excluded_status[status or 'blank'] = excluded_status.get(status or 'blank', 0) + 1
            continue
        selected.append((record, metadata))
    selected.sort(key=lambda pair: int(pair[0]['NORAD_CAT_ID']))

    rows = []
    status_counts = {}
    successful_unarchived = 0
    for record, metadata in selected:
        source_epoch = parse_omm_epoch(str(record['EPOCH']))
        age_hours = (query_epoch - source_epoch).total_seconds() / 3600.0
        norad = int(record['NORAD_CAT_ID'])
        archived = norad in historical_ids
        state = [None] * 6
        error = None
        if age_hours < 0:
            state_status = 'future_element'
        elif age_hours > max_age_hours:
            state_status = 'stale_element'
        else:
            error, position, velocity = satellite(omm_row(record)).sgp4(*julian(query_epoch))
            if int(error) == 0 and np.isfinite(np.r_[position, velocity]).all():
                state_status = 'success'
                state = [float(value) for value in (*position, *velocity)]
                if not archived:
                    successful_unarchived += 1
            else:
                state_status = f'sgp4_error_{int(error)}'
            error = int(error)
        status_counts[state_status] = status_counts.get(state_status, 0) + 1
        rows.append({
            'norad_id': norad,
            'object_name': metadata.get('OBJECT_NAME', ''),
            'object_type': metadata.get('OBJECT_TYPE', ''),
            'ops_status_code': metadata.get('OPS_STATUS_CODE', ''),
            'launch_date': metadata.get('LAUNCH_DATE') or None,
            'query_epoch_utc': query_epoch,
            'source_element_epoch_utc': source_epoch,
            'element_age_hours': age_hours,
            'state_status': state_status,
            'sgp4_error': error,
            'had_historical_element_in_archive': archived,
            'x_teme_km': state[0], 'y_teme_km': state[1], 'z_teme_km': state[2],
            'vx_teme_km_s': state[3], 'vy_teme_km_s': state[4], 'vz_teme_km_s': state[5],
        })
    if not rows:
        raise ValueError('No current active payloads passed the SATCAT cohort filter')

    signature = hashlib.sha256(json.dumps({
        'source_snapshot_sha256': sha256(snapshot), 'satcat_sha256': sha256(satcat_path),
        'query_epoch_utc': query_epoch.isoformat(), 'max_age_hours': max_age_hours,
        'cohort': 'active GROUP=active OMM intersect SATCAT PAY, EA, no decay, active status',
    }, sort_keys=True).encode()).hexdigest()
    parquet = output / 'active_payload_common_epoch.parquet'
    manifest_path = output / 'manifest.json'
    if manifest_path.exists() or parquet.exists():
        if not manifest_path.is_file() or not parquet.is_file():
            raise FileExistsError(f'Existing snapshot output is incomplete: {output}')
        previous = json.loads(manifest_path.read_text())
        if previous.get('signature') != signature or previous.get('parquet_sha256') != sha256(parquet):
            raise FileExistsError(f'Existing snapshot output has different provenance: {output}')
        return previous

    output.mkdir(parents=True, exist_ok=True)
    temporary = parquet.with_suffix('.parquet.tmp')
    table = pa.Table.from_pylist(rows)
    db = duckdb.connect()
    db.register('snapshot_rows', table)
    db.execute('COPY snapshot_rows TO ? (FORMAT PARQUET, COMPRESSION ZSTD)', [str(temporary)])
    temporary.replace(parquet)
    output_rows, unique_ids, success_rows, null_state_rows, time_mismatches = db.execute(
        '''SELECT count(*),count(DISTINCT norad_id),
            count(*) FILTER (WHERE state_status='success'),
            count(*) FILTER (WHERE state_status!='success' AND x_teme_km IS NULL
                AND y_teme_km IS NULL AND z_teme_km IS NULL
                AND vx_teme_km_s IS NULL AND vy_teme_km_s IS NULL AND vz_teme_km_s IS NULL),
            count(*) FILTER (WHERE query_epoch_utc != CAST(? AS TIMESTAMPTZ))
           FROM read_parquet(?)''', [query_epoch, str(parquet)]).fetchone()
    if output_rows != len(selected) or unique_ids != len(selected) or success_rows != status_counts.get('success', 0):
        raise AssertionError('Snapshot output totals or state statuses do not reconcile')
    if null_state_rows != len(selected) - success_rows or time_mismatches != 0:
        raise AssertionError('Rejected state rows or common-epoch timestamps do not reconcile')

    # Deterministically reproduce 100 successful saved states from the original OMM records.
    sample_ids = sorted(
        (row['norad_id'] for row in rows if row['state_status'] == 'success'),
        key=lambda value: hashlib.sha256(str(value).encode()).hexdigest())[:100]
    saved = {int(row[0]): row[1:] for row in db.execute(
        '''SELECT norad_id,x_teme_km,y_teme_km,z_teme_km,vx_teme_km_s,vy_teme_km_s,vz_teme_km_s
           FROM read_parquet(?) WHERE norad_id IN (SELECT unnest(?))''',
        [str(parquet), sample_ids]).fetchall()}
    source_by_id = {int(record['NORAD_CAT_ID']): record for record, _ in selected}
    max_position_error = 0.0
    max_velocity_error = 0.0
    for norad in sample_ids:
        error, position, velocity = satellite(omm_row(source_by_id[norad])).sgp4(*julian(query_epoch))
        if error != 0:
            raise AssertionError(f'Independent SGP4 sample failed for NORAD {norad}: {error}')
        actual = np.asarray(saved[norad], dtype=float)
        max_position_error = max(max_position_error, float(np.max(np.abs(actual[:3] - position))))
        max_velocity_error = max(max_velocity_error, float(np.max(np.abs(actual[3:] - velocity))))
    db.close()

    counts = {}
    for record, metadata in selected:
        code = metadata.get('OPS_STATUS_CODE') or 'blank'
        counts[code] = counts.get(code, 0) + 1
    manifest = {
        'status': 'completed',
        'dataset_kind': 'separate common-epoch current active payload snapshot',
        'query_epoch_utc': query_epoch.isoformat(),
        'source_url': snapshot_manifest.get('source_url'),
        'source_snapshot': str(snapshot), 'source_snapshot_sha256': sha256(snapshot),
        'source_snapshot_record_count': len(source),
        'satcat_path': str(satcat_path), 'satcat_sha256': sha256(satcat_path),
        'signature': signature,
        'cohort_definition': 'CelesTrak GROUP=active records joined to SATCAT payloads in Earth orbit with no decay date and status +, B, P, S, or X',
        'max_element_age_hours': max_age_hours,
        'active_group_nonpayload_or_non_earth_excluded': excluded_types,
        'decayed_excluded': excluded_decayed,
        'inactive_or_unknown_status_excluded': excluded_status,
        'current_payload_candidates': len(selected),
        'ops_status_counts': counts,
        'state_status_counts': status_counts,
        'current_payload_states_written': output_rows,
        'unique_norad_ids': unique_ids,
        'historical_archive_ids': len(historical_ids),
        'current_payload_ids_with_archived_history': sum(row['had_historical_element_in_archive'] for row in rows),
        'current_payload_ids_without_archived_history': sum(not row['had_historical_element_in_archive'] for row in rows),
        'successful_current_states_without_archived_history': successful_unarchived,
        'independent_sample_rows': len(sample_ids),
        'independent_sample_max_abs_position_difference_km': max_position_error,
        'independent_sample_max_abs_velocity_difference_km_s': max_velocity_error,
        'state_output': parquet.name, 'parquet_sha256': sha256(parquet),
        'frame': 'TEME', 'units': {'position': 'km', 'velocity': 'km/s'},
        'model': 'SGP4 WGS-72 propagated from each OMM epoch to the one common snapshot retrieval epoch',
        'interpretation': 'Current snapshot extension only. It does not backfill history or establish operational status between archived element epochs.',
        'limitations': [
            'Current CelesTrak active-group membership and SATCAT status are snapshot classifications.',
            'Freshness cutoff is 72 hours; stale, future-dated, and SGP4-error rows are preserved without state vectors.',
            'The 704 fresh current payload IDs with no archived historical element are represented only at this common current epoch.',
            'This separate snapshot does not alter the pinned historical archive or four-year trajectory product.',
        ],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument('--satcat', type=Path, default=ROOT / 'data/raw/satcat.csv')
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--max-age-hours', type=float, default=MAX_AGE_HOURS)
    args = parser.parse_args()
    result = export(args.snapshot, args.output, args.satcat, args.max_age_hours)
    print(json.dumps({key: value for key, value in result.items()
                      if key not in {'limitations', 'source_snapshot_sha256', 'satcat_sha256', 'parquet_sha256'}}, indent=2))


if __name__ == '__main__':
    main()
