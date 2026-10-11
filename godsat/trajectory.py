"""Reconstruct fixed-cadence trajectories from historical orbital elements."""
import csv
import datetime as dt
import hashlib
import json
import pathlib
from bisect import bisect_right

from .orbits import ROOT, History, satellite, julian, utc


CSV_COLUMNS = [
    'norad_id', 'time_utc', 'element_epoch', 'element_age_hours',
    'sgp4_error', 'x_teme_km', 'y_teme_km', 'z_teme_km',
    'vx_teme_km_s', 'vy_teme_km_s', 'vz_teme_km_s',
]


def trajectory_rows(records, norad_id, start, end, step_seconds=60,
                    max_age_hours=72):
    """Yield one TEME state per cadence step, refreshing from the latest TLE.

    The interval is start-inclusive and end-exclusive. Samples without a recent
    source element remain explicit rows with ``sgp4_error=-1`` and null states.
    """
    start, end = utc(start), utc(end)
    if start >= end:
        raise ValueError('start must be before end')
    if step_seconds <= 0:
        raise ValueError('step_seconds must be positive')
    if max_age_hours < 0:
        raise ValueError('max_age_hours must be nonnegative')
    records = sorted(records, key=lambda row: row['epoch'])
    epochs = [utc(row['epoch']) for row in records]
    t = start
    selected_index = None
    sat = None
    while t < end:
        index = bisect_right(epochs, t) - 1
        age = ((t - epochs[index]).total_seconds() / 3600) if index >= 0 else None
        base = {
            'norad_id': int(norad_id), 'time_utc': t.isoformat(),
            'element_epoch': epochs[index].isoformat() if index >= 0 else None,
            'element_age_hours': age,
        }
        if index < 0 or age > max_age_hours:
            yield {**base, 'sgp4_error': -1, **{column: None for column in CSV_COLUMNS[5:]}}
        else:
            if index != selected_index:
                sat = satellite(records[index])
                selected_index = index
            error, position, velocity = sat.sgp4(*julian(t))
            state = [*position, *velocity] if error == 0 else [None] * 6
            yield {**base, 'sgp4_error': int(error), **dict(zip(CSV_COLUMNS[5:], state))}
        t += dt.timedelta(seconds=step_seconds)


def export_trajectory(norad_id, start, end, output, step_seconds=60,
                      max_age_hours=72, root=ROOT):
    """Write a reproducible CSV trajectory and JSON provenance sidecar."""
    root = pathlib.Path(root).resolve()
    output = pathlib.Path(output).expanduser().resolve()
    start_utc, end_utc = utc(start), utc(end)
    if step_seconds <= 0:
        raise ValueError('step_seconds must be positive')
    if max_age_hours < 0:
        raise ValueError('max_age_hours must be nonnegative')
    output.parent.mkdir(parents=True, exist_ok=True)
    history = History(root, cohort='all', window=(start_utc, end_utc),
                      max_age_hours=max_age_hours)
    try:
        records = history.records(start_utc, end_utc, max_age_hours, ids=[norad_id])
    finally:
        history.db.close()
    if not records:
        raise ValueError(f'No orbital elements for NORAD {norad_id} near the requested interval')

    digest = hashlib.sha256()
    counts = {'successful': 0, 'sgp4_errors': 0, 'stale_or_missing': 0}
    temp = output.with_suffix(output.suffix + '.tmp')
    try:
        with temp.open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=CSV_COLUMNS)
            writer.writeheader()
            for row in trajectory_rows(records, norad_id, start_utc, end_utc,
                                       step_seconds, max_age_hours):
                writer.writerow(row)
                if row['sgp4_error'] == -1:
                    counts['stale_or_missing'] += 1
                elif row['sgp4_error'] == 0:
                    counts['successful'] += 1
                else:
                    counts['sgp4_errors'] += 1
        temp.replace(output)
        with output.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise

    manifest = {
        'status': 'completed', 'norad_id': int(norad_id),
        'start_inclusive': start_utc.isoformat(), 'end_exclusive': end_utc.isoformat(),
        'step_seconds': int(step_seconds), 'max_element_age_hours': float(max_age_hours),
        'source': 'data/raw/tle_*.parquet', 'source_revision': source_revision(root),
        'model': 'SGP4 WGS-72, refreshed from the latest historical element at or before each sample',
        'frame': 'TEME', 'position_units': 'km', 'velocity_units': 'km/s',
        'source_element_records_used': len(records), 'sample_counts': counts,
        'csv_sha256': digest.hexdigest(),
        'limitations': [
            'This is a reconstructed trajectory, not precision ephemeris or independent orbit truth.',
            'Accuracy degrades with element age and is bounded by max_element_age_hours.',
            'Maneuvers and unrecorded forces between element updates are not independently modeled.',
        ],
    }
    manifest_path = output.with_suffix(output.suffix + '.json')
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
    return manifest


def source_revision(root):
    path = pathlib.Path(root) / 'data/raw/manifest.json'
    if not path.is_file():
        return None
    return json.loads(path.read_text()).get('revision')
