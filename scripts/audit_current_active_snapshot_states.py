"""Independently audit the current common-epoch active-payload snapshot."""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
from pathlib import Path
import sys

import duckdb
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from godsat.orbits import julian, satellite, utc
from scripts.export_current_active_snapshot_states import ACTIVE_STATUS, MAX_AGE_HOURS, omm_row

DEFAULT_OUTPUT = ROOT / 'data/current_active_catalog_snapshot_2026-10-10'


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def audit(output: Path) -> dict:
    output = output.expanduser().resolve()
    manifest = json.loads((output / 'manifest.json').read_text())
    parquet = output / manifest['state_output']
    snapshot = Path(manifest['source_snapshot'])
    satcat_path = Path(manifest['satcat_path'])
    if manifest.get('status') != 'completed' or not parquet.is_file():
        raise ValueError('Current active snapshot is not complete')
    if sha256(parquet) != manifest.get('parquet_sha256'):
        raise ValueError('Current active snapshot Parquet checksum mismatch')
    if sha256(snapshot) != manifest.get('source_snapshot_sha256'):
        raise ValueError('Current active OMM source checksum mismatch')
    if sha256(satcat_path) != manifest.get('satcat_sha256'):
        raise ValueError('Current active SATCAT checksum mismatch')
    query_epoch = utc(manifest['query_epoch_utc'])
    max_age = float(manifest['max_element_age_hours'])
    if max_age <= 0 or max_age > MAX_AGE_HOURS:
        raise ValueError('Unexpected freshness threshold')

    source_records = json.loads(snapshot.read_text())
    satcat = {}
    with satcat_path.open(newline='') as stream:
        for row in csv.DictReader(stream):
            try:
                satcat[int(row['NORAD_CAT_ID'])] = row
            except (ValueError, TypeError, KeyError):
                continue
    candidates = {}
    for record in source_records:
        norad = int(record['NORAD_CAT_ID'])
        metadata = satcat.get(norad)
        if (metadata and metadata.get('OBJECT_TYPE') == 'PAY'
                and metadata.get('ORBIT_CENTER') == 'EA'
                and not metadata.get('DECAY_DATE', '').strip()
                and metadata.get('OPS_STATUS_CODE', '').strip() in ACTIVE_STATUS):
            if norad in candidates:
                raise ValueError(f'Duplicate source OMM for NORAD {norad}')
            candidates[norad] = (record, metadata)

    db = duckdb.connect()
    db.execute("SET TimeZone='UTC'")
    history_paths = sorted((ROOT / 'data/raw').glob('tle_*.parquet'))
    historical_ids = {int(row[0]) for row in db.execute(
        'SELECT DISTINCT norad_id FROM read_parquet(?)',
        [[str(path) for path in history_paths]]).fetchall()}
    rows = db.execute('''SELECT norad_id,object_name,object_type,ops_status_code,
        query_epoch_utc,source_element_epoch_utc,element_age_hours,state_status,sgp4_error,
        had_historical_element_in_archive,x_teme_km,y_teme_km,z_teme_km,
        vx_teme_km_s,vy_teme_km_s,vz_teme_km_s
        FROM read_parquet(?) ORDER BY norad_id''', [str(parquet)]).fetchall()
    if len(rows) != len(candidates) or len({int(row[0]) for row in rows}) != len(rows):
        raise ValueError('Snapshot row count or identifier uniqueness mismatch')
    state_counts: dict[str, int] = {}
    max_age_difference = 0.0
    success_ids = []
    missing_history = 0
    for row in rows:
        (norad, object_name, object_type, status, saved_query, saved_source_epoch,
         age, state_status, error, has_history, *state) = row
        norad = int(norad)
        if norad not in candidates:
            raise ValueError(f'Unexpected NORAD ID {norad} in current snapshot')
        record, metadata = candidates[norad]
        if (object_name != metadata.get('OBJECT_NAME', '') or object_type != 'PAY'
                or status != metadata.get('OPS_STATUS_CODE', '')):
            raise ValueError(f'SATCAT metadata mismatch for NORAD {norad}')
        source_epoch = dt.datetime.fromisoformat(str(record['EPOCH']).replace('Z', '+00:00'))
        if source_epoch.tzinfo is None:
            source_epoch = source_epoch.replace(tzinfo=dt.timezone.utc)
        source_epoch = source_epoch.astimezone(dt.timezone.utc)
        if saved_query != query_epoch or saved_source_epoch != source_epoch:
            raise ValueError(f'Element or query epoch mismatch for NORAD {norad}')
        expected_age = (query_epoch - source_epoch).total_seconds() / 3600.0
        max_age_difference = max(max_age_difference, abs(float(age) - expected_age))
        if abs(float(age) - expected_age) > 1e-10:
            raise ValueError(f'Element age mismatch for NORAD {norad}')
        actual_history = norad in historical_ids
        if bool(has_history) != actual_history:
            raise ValueError(f'Historical membership mismatch for NORAD {norad}')
        if not actual_history:
            missing_history += 1
        expected_status = ('future_element' if expected_age < 0 else
                           'stale_element' if expected_age > max_age else 'success')
        if state_status != expected_status:
            raise ValueError(f'Freshness status mismatch for NORAD {norad}')
        state_counts[state_status] = state_counts.get(state_status, 0) + 1
        if state_status == 'success':
            if int(error) != 0 or not np.isfinite(np.asarray(state, dtype=float)).all():
                raise ValueError(f'Successful state is invalid for NORAD {norad}')
            success_ids.append(norad)
        elif error is not None or any(value is not None for value in state):
            raise ValueError(f'Rejected state has numeric output for NORAD {norad}')

    if state_counts != manifest.get('state_status_counts'):
        raise ValueError('Per-status row counts do not match the manifest')
    if missing_history != manifest.get('current_payload_ids_without_archived_history'):
        raise ValueError('Historical source-membership totals do not match the manifest')
    if len(historical_ids) != manifest.get('historical_archive_ids'):
        raise ValueError('Historical catalog total does not match the manifest')

    sample_ids = sorted(success_ids, key=lambda value: hashlib.sha256(str(value).encode()).hexdigest())[:100]
    saved = {int(row[0]): np.asarray(row[1:], dtype=float) for row in db.execute(
        '''SELECT norad_id,x_teme_km,y_teme_km,z_teme_km,vx_teme_km_s,vy_teme_km_s,vz_teme_km_s
           FROM read_parquet(?) WHERE norad_id IN (SELECT unnest(?))''',
        [str(parquet), sample_ids]).fetchall()}
    db.close()
    max_position_error = 0.0
    max_velocity_error = 0.0
    for norad in sample_ids:
        record = candidates[norad][0]
        error, position, velocity = satellite(omm_row(record)).sgp4(*julian(query_epoch))
        if error != 0:
            raise ValueError(f'Independent SGP4 sample failed for NORAD {norad}: {error}')
        max_position_error = max(max_position_error,
            float(np.max(np.abs(saved[norad][:3] - np.asarray(position)))))
        max_velocity_error = max(max_velocity_error,
            float(np.max(np.abs(saved[norad][3:] - np.asarray(velocity)))))
    if max_position_error > 1e-9 or max_velocity_error > 1e-12:
        raise ValueError('Independent common-epoch SGP4 samples exceed tolerance')

    result = {
        'status': 'passed_structural_and_sampled_state_reproduction',
        'source_rows_checked': len(candidates),
        'output_rows_checked': len(rows),
        'unique_norad_ids_checked': len(rows),
        'query_epoch_utc': query_epoch.isoformat(),
        'state_status_counts': state_counts,
        'historical_archive_ids': len(historical_ids),
        'current_payload_ids_without_historical_elements': missing_history,
        'successful_current_states_without_historical_elements': sum(
            norad not in historical_ids for norad in success_ids),
        'max_element_age_recalculation_difference_hours': max_age_difference,
        'independent_sample_rows': len(sample_ids),
        'independent_sample_max_abs_position_difference_km': max_position_error,
        'independent_sample_max_abs_velocity_difference_km_s': max_velocity_error,
        'source_snapshot_sha256': sha256(snapshot),
        'satcat_sha256': sha256(satcat_path),
        'output_sha256': sha256(parquet),
    }
    (output / 'independent_audit.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print(json.dumps(audit(args.output), indent=2))


if __name__ == '__main__':
    main()
