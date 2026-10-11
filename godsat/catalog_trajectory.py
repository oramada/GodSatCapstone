"""Resumable bulk fixed-cadence trajectory export for the historical catalog."""
import csv
import concurrent.futures
import datetime as dt
import hashlib
import json
import math
import pathlib

import pyarrow as pa
import pyarrow.parquet as pq

from .orbits import ROOT, History, orbit_regime, utc
from .trajectory import source_revision, trajectory_rows


DAY = dt.timedelta(days=1)
BATCH_ROWS = 100_000
SCHEMA = pa.schema([
    ('norad_id', pa.int32()),
    ('time_utc', pa.string()),
    ('element_epoch', pa.string()),
    ('element_age_hours', pa.float64()),
    ('orbit_regime', pa.string()),
    ('sgp4_error', pa.int16()),
    ('x_teme_km', pa.float64()),
    ('y_teme_km', pa.float64()),
    ('z_teme_km', pa.float64()),
    ('vx_teme_km_s', pa.float64()),
    ('vy_teme_km_s', pa.float64()),
    ('vz_teme_km_s', pa.float64()),
])


def catalog_object_ids(root, start, end, max_age_hours=72):
    """Return IDs whose archived element coverage overlaps the requested span."""
    root = pathlib.Path(root)
    path = root / 'data/state_vector_object_coverage.csv'
    index = json.loads((root/'data/state_vector_object_coverage.json').read_text())
    manifest = json.loads((root/'data/historical_state_vectors_all/manifest.json').read_text())
    if (manifest.get('status')!='completed'
            or index.get('export_signature')!=manifest.get('signature')
            or index.get('parquet_records_scanned')!=manifest.get('records_written')
            or index.get('snapshot_matches_manifest') is not True):
        raise RuntimeError('Per-object index is incomplete or stale against the all-catalog export')
    lower, upper = utc(start) - dt.timedelta(hours=max_age_hours), utc(end)
    ids = []
    def parse_index_epoch(value):
        value = value.replace(' ', 'T')
        if value.endswith('+00'):
            value = value[:-3] + '+00:00'
        zone = '+00:00' if value.endswith('+00:00') else ''
        base = value[:-len(zone)] if zone else value
        if '.' in base:
            whole, fraction = base.split('.', 1)
            base = whole + '.' + (fraction + '000000')[:6]
        value = base + zone
        return utc(value)
    with path.open(newline='') as stream:
        for row in csv.DictReader(stream):
            if int(row['historical_element_rows']) == 0:
                continue
            first = parse_index_epoch(row['first_element_epoch'])
            last = parse_index_epoch(row['last_element_epoch'])
            if first < upper and last >= lower:
                ids.append(int(row['norad_id']))
    return sorted(set(ids))


def duration_samples(start, end, step_seconds):
    seconds = (utc(end) - utc(start)).total_seconds()
    if seconds <= 0:
        raise ValueError('start must be before end')
    if step_seconds <= 0:
        raise ValueError('step_seconds must be positive')
    return math.ceil(seconds / step_seconds)


def manifest_signature(start, end, step_seconds, max_age_hours, source, ids):
    settings = {
        'start': utc(start).isoformat(), 'end_exclusive': utc(end).isoformat(),
        'step_seconds': int(step_seconds), 'max_age_hours': float(max_age_hours),
        'source_revision': source, 'object_count': len(ids),
        'object_ids_sha256': hashlib.sha256(
            ','.join(map(str, ids)).encode()).hexdigest(),
    }
    signature = hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()
    return signature, settings


def write_manifest(path, manifest):
    temp = path.with_suffix('.json.tmp')
    temp.write_text(json.dumps(manifest, indent=2) + '\n')
    temp.replace(path)


def _verify_part(output, index, part):
    path = output / part['file']
    if (part.get('index') != index
            or path.name != f'part-{index:05d}.parquet'
            or not path.is_file()):
        raise RuntimeError(f'Committed part missing or out of order: {part}')
    if part.get('size_bytes') is not None and path.stat().st_size != part['size_bytes']:
        raise RuntimeError(f'Committed part size mismatch: {path}')
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(block)
    if digest.hexdigest() != part.get('sha256'):
        raise RuntimeError(f'Committed part checksum mismatch: {path}')
    rows = pq.ParquetFile(path).metadata.num_rows
    if rows != part.get('rows'):
        raise RuntimeError(f'Committed part row count mismatch: {path}')


def verify_committed_parts(output, parts, workers=8, progress=None):
    """Verify every committed part, streaming hashes with bounded parallel I/O."""
    output = pathlib.Path(output)
    if workers < 1:
        raise ValueError('workers must be positive')
    indices = [int(part.get('index', -1)) for part in parts]
    if indices != sorted(set(indices)):
        raise RuntimeError('Committed parts must have unique increasing manifest indices')
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_verify_part, output, index, part)
                   for index, part in zip(indices, parts)]
        for complete, future in enumerate(concurrent.futures.as_completed(futures), 1):
            future.result()
            if progress is not None:
                progress(complete, len(futures))


def write_day_part(output, index, lower, upper, ids, records, step_seconds,
                   max_age_hours):
    grouped = {oid: [] for oid in ids}
    for row in records:
        oid = int(row['norad_id'])
        if oid in grouped:
            grouped[oid].append(row)
    part_name = f'part-{index:05d}.parquet'
    final_path = output / part_name
    temp_path = output / (part_name + '.tmp')
    temp_path.unlink(missing_ok=True)
    counts = {'successful': 0, 'sgp4_errors': 0, 'stale_or_missing': 0}
    written = 0
    batch = []
    writer = pq.ParquetWriter(temp_path, SCHEMA, compression='zstd', compression_level=3,
                              use_dictionary=['orbit_regime'])
    try:
        for oid in ids:
            object_records = grouped[oid]
            regimes = {utc(item['epoch']).isoformat(): orbit_regime(item)
                       for item in object_records}
            for row in trajectory_rows(object_records, oid, lower, upper,
                                        step_seconds, max_age_hours):
                row['orbit_regime'] = regimes.get(row['element_epoch'], 'unknown')
                batch.append(row)
                written += 1
                if row['sgp4_error'] == -1:
                    counts['stale_or_missing'] += 1
                elif row['sgp4_error'] == 0:
                    counts['successful'] += 1
                else:
                    counts['sgp4_errors'] += 1
                if len(batch) >= BATCH_ROWS:
                    writer.write_table(pa.Table.from_pylist(batch, schema=SCHEMA),
                                       row_group_size=BATCH_ROWS)
                    batch.clear()
        if batch:
            writer.write_table(pa.Table.from_pylist(batch, schema=SCHEMA),
                               row_group_size=BATCH_ROWS)
            batch.clear()
    except BaseException:
        writer.close()
        temp_path.unlink(missing_ok=True)
        raise
    writer.close()
    samples = duration_samples(lower, upper, step_seconds)
    expected_rows = len(ids) * samples
    if written != expected_rows:
        temp_path.unlink(missing_ok=True)
        raise RuntimeError(f'Part {index} wrote {written} rows; expected {expected_rows}')
    temp_path.replace(final_path)
    digest = hashlib.sha256(final_path.read_bytes()).hexdigest()
    return {
        'index': index, 'file': part_name,
        'start_inclusive': lower.isoformat(), 'end_exclusive': upper.isoformat(),
        'samples_per_object': samples, 'objects': len(ids), 'rows': written,
        'size_bytes': final_path.stat().st_size,
        'successful': counts['successful'], 'sgp4_errors': counts['sgp4_errors'],
        'stale_or_missing': counts['stale_or_missing'], 'sha256': digest,
    }


def export_catalog_trajectory(start, end, output, step_seconds=3600,
                              max_age_hours=72, root=ROOT, progress=None):
    """Export the full overlapping historical object cohort in resumable day parts.

    Every cohort object has one row at every requested sample time. Objects
    without a fresh element set have explicit SGP4 status -1 and null states.
    Cadence must divide 24 hours so day-part boundaries preserve the global grid.
    """
    root, output = pathlib.Path(root).resolve(), pathlib.Path(output).expanduser().resolve()
    start, end = utc(start), utc(end)
    step_seconds, max_age_hours = int(step_seconds), float(max_age_hours)
    if start >= end:
        raise ValueError('start must be before end')
    if step_seconds <= 0 or 86_400 % step_seconds:
        raise ValueError('step_seconds must be a positive divisor of 86400')
    if max_age_hours < 0:
        raise ValueError('max_age_hours must be nonnegative')
    ids = catalog_object_ids(root, start, end, max_age_hours)
    if not ids:
        raise ValueError('No catalog objects overlap the requested interval')
    source = source_revision(root)
    signature, settings = manifest_signature(start, end, step_seconds,
                                             max_age_hours, source, ids)
    output.mkdir(parents=True, exist_ok=True)
    manifest_path = output / 'manifest.json'
    manifest = None
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text())
        if manifest.get('signature') != signature:
            raise ValueError('Output directory already contains a different export signature')
        verify_committed_parts(output, manifest.get('parts', []))
    else:
        manifest = {
            'status': 'running', 'signature': signature, **settings,
            'object_count': len(ids),
            'projected_samples_per_object': duration_samples(start, end, step_seconds),
            'projected_rows': len(ids) * duration_samples(start, end, step_seconds),
            'frame': 'TEME', 'position_units': 'km', 'velocity_units': 'km/s',
            'model': 'SGP4 WGS-72 using latest archived mean elements at or before each sample',
            'source_files': 'data/raw/tle_*.parquet', 'parts': [],
            'limitations': [
                'This is a reconstructed fixed-cadence ephemeris, not an observed or precision orbit product.',
                'The public mirror stores reduced-precision elements and omits original TLE lines and some fields.',
                'Maneuvers and unrecorded forces between source element updates are not independently modeled.',
                'The catalog cohort includes payloads, debris, and rocket bodies and is not universally complete.',
                'Rows before an object has a fresh element set are retained with sgp4_error=-1 and null states.',
            ],
        }
        write_manifest(manifest_path, manifest)

    parts = manifest.setdefault('parts', [])
    total_parts = math.ceil((end - start).total_seconds() / DAY.total_seconds())
    if len(parts) > total_parts:
        raise RuntimeError('Manifest contains more parts than this time interval')
    history = History(root, cohort='all', window=(start, end),
                      max_age_hours=max_age_hours)
    try:
        cursor = start + dt.timedelta(days=len(parts))
        while cursor < end:
            upper = min(cursor + DAY, end)
            records = history.records(cursor, upper, max_age_hours)
            part = write_day_part(output, len(parts), cursor, upper, ids,
                                  records, step_seconds, max_age_hours)
            parts.append(part)
            manifest['records_written'] = sum(item['rows'] for item in parts)
            manifest['parts_written'] = len(parts)
            write_manifest(manifest_path, manifest)
            if progress:
                progress(manifest)
            cursor = upper
    finally:
        history.db.close()
    manifest['status'] = 'completed'
    manifest['completed_rows'] = sum(item['rows'] for item in parts)
    manifest['successful'] = sum(item['successful'] for item in parts)
    manifest['sgp4_errors'] = sum(item['sgp4_errors'] for item in parts)
    manifest['stale_or_missing'] = sum(item['stale_or_missing'] for item in parts)
    write_manifest(manifest_path, manifest)
    return manifest
