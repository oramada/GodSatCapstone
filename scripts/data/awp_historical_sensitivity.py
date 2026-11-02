"""Compare AWP propagation with historical SGP4 across four years and orbit regimes."""

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))

import argparse
import calendar
import csv
import datetime as dt
import hashlib
import json
import pathlib
import subprocess

import numpy as np

from godsat.orbits import (ROOT, History, awp_propagate, frame_transform_provenance,
    julian, satellite, teme_to_gcrs, utc)
from godsat.trajectory import source_revision


DEFAULT_OBJECTS = {'leo': 22, 'meo': 5, 'geo': 634, 'heo': 503}
LEAD_HOURS = (0, 1, 6, 24)
CSV_FIELDS = ['orbit_regime', 'norad_id', 'element_epoch_utc',
    'element_offset_from_month_anchor_hours', 'month_anchor_utc', 'model',
    'lead_hours', 'sgp4_error', 'position_separation_km',
    'velocity_separation_km_s']


def add_months(value, count):
    month_index = value.year * 12 + value.month - 1 + count
    year, month_zero = divmod(month_index, 12)
    month = month_zero + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def monthly_intervals(start, end):
    """Return monthly intervals anchored on start's day, clipped to end."""
    start, end = utc(start), utc(end)
    if start >= end:
        raise ValueError('start must be before end')
    intervals = []
    cursor = start
    while cursor < end:
        following = min(add_months(cursor, 1), end)
        intervals.append((cursor, following))
        cursor = following
    return intervals


def select_monthly_elements(records, object_ids, start, end):
    """Select the source element nearest each monthly interval midpoint."""
    intervals = monthly_intervals(start, end)
    grouped = {int(oid): [] for oid in object_ids.values()}
    for record in records:
        oid = int(record['norad_id'])
        if oid in grouped:
            grouped[oid].append(record)
    result = []
    missing = []
    for regime, oid in object_ids.items():
        rows = sorted(grouped[int(oid)], key=lambda row: utc(row['epoch']))
        for lower, upper in intervals:
            candidates = [row for row in rows if lower <= utc(row['epoch']) < upper]
            if not candidates:
                missing.append({'orbit_regime': regime, 'norad_id': int(oid),
                    'interval_start': lower.isoformat(), 'interval_end': upper.isoformat()})
                continue
            midpoint = lower + (upper - lower) / 2
            chosen = min(candidates, key=lambda row: (
                abs((utc(row['epoch']) - midpoint).total_seconds()), utc(row['epoch'])))
            result.append((regime, lower, upper, chosen))
    if missing:
        raise ValueError(f'Missing source elements in {len(missing)} object-month intervals: {missing[:8]}')
    return result


def compare_monthly_elements(selected, drag_area_mass=0.01, drag_coefficient=2.2):
    """Run AWP from each selected epoch and compare with same-element SGP4."""
    rows = []
    elapsed_seconds = np.asarray(LEAD_HOURS, dtype=float) * 3600.0
    for regime, anchor, _upper, element in selected:
        epoch = utc(element['epoch'])
        source = satellite(element)
        error, position, velocity = source.sgp4(*julian(epoch))
        if error or not np.isfinite(np.r_[position, velocity]).all():
            raise ValueError(f'Initial SGP4 failed for NORAD {element["norad_id"]} at {epoch}: {error}')
        initial_teme = np.r_[position, velocity]
        initial_gcrs = teme_to_gcrs(initial_teme, epoch)
        reference_gcrs = []
        for seconds in elapsed_seconds:
            instant = epoch + dt.timedelta(seconds=float(seconds))
            sgp4_error, pos, vel = source.sgp4(*julian(instant))
            if sgp4_error or not np.isfinite(np.r_[pos, vel]).all():
                reference_gcrs.append((sgp4_error, None))
            else:
                reference_gcrs.append((0, teme_to_gcrs(np.r_[pos, vel], instant)))

        models = [('awp_two_body_j2', False)]
        if regime == 'leo':
            models.append(('awp_two_body_j2_nominal_drag', True))
        for model_name, with_drag in models:
            awp_states = awp_propagate(initial_gcrs, elapsed_seconds[-1], elapsed_seconds,
                j2=True, drag=with_drag, area_mass_m2_kg=drag_area_mass,
                drag_coefficient=drag_coefficient)
            for lead, reference, awp_state in zip(LEAD_HOURS, reference_gcrs, awp_states):
                sgp4_error, ref_state = reference
                if ref_state is None:
                    pos_delta = vel_delta = None
                else:
                    pos_delta = float(np.linalg.norm(awp_state[:3] - ref_state[:3]))
                    vel_delta = float(np.linalg.norm(awp_state[3:] - ref_state[3:]))
                rows.append({
                    'orbit_regime': regime,
                    'norad_id': int(element['norad_id']),
                    'element_epoch_utc': epoch.isoformat(),
                    'element_offset_from_month_anchor_hours': (epoch - anchor).total_seconds() / 3600,
                    'month_anchor_utc': anchor.isoformat(),
                    'model': model_name,
                    'lead_hours': lead,
                    'sgp4_error': int(sgp4_error),
                    'position_separation_km': pos_delta,
                    'velocity_separation_km_s': vel_delta,
                })
    return rows


def summarize(rows):
    groups = {}
    for row in rows:
        key = (row['orbit_regime'], row['model'], str(row['lead_hours']))
        groups.setdefault(key, []).append(row)
    result = []
    for (regime, model, lead), group in sorted(groups.items()):
        valid = [row for row in group if row['position_separation_km'] is not None]
        positions = np.asarray([row['position_separation_km'] for row in valid], dtype=float)
        velocities = np.asarray([row['velocity_separation_km_s'] for row in valid], dtype=float)
        result.append({
            'orbit_regime': regime, 'model': model, 'lead_hours': int(lead),
            'n_monthly_cases': len(group), 'n_valid_sgp4_comparisons': len(valid),
            'position_separation_median_km': float(np.median(positions)) if len(positions) else None,
            'position_separation_p95_km': float(np.quantile(positions, .95)) if len(positions) else None,
            'position_separation_max_km': float(np.max(positions)) if len(positions) else None,
            'velocity_separation_median_km_s': float(np.median(velocities)) if len(velocities) else None,
            'velocity_separation_p95_km_s': float(np.quantile(velocities, .95)) if len(velocities) else None,
        })
    return result


def run(output, start, end, object_ids=None, root=ROOT):
    root, output = pathlib.Path(root).resolve(), pathlib.Path(output).resolve()
    object_ids = object_ids or DEFAULT_OBJECTS
    start, end = utc(start), utc(end)
    history = History(root, cohort='all', window=(start, end), max_age_hours=0)
    try:
        records = history.records(start, end, max_age=0, ids=list(object_ids.values()))
    finally:
        history.db.close()
    selected = select_monthly_elements(records, object_ids, start, end)
    rows = compare_monthly_elements(selected)
    output.mkdir(parents=True, exist_ok=True)
    csv_path = output / 'awp_sgp4_monthly_comparisons.csv'
    with csv_path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    csv_hash = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    source_manifest_path = root / 'data/raw/manifest.json'
    source_manifest_hash = (hashlib.sha256(source_manifest_path.read_bytes()).hexdigest()
        if source_manifest_path.is_file() else None)
    summary = {
        'status': 'completed',
        'source_revision': source_revision(root),
        'awp_revision': subprocess.check_output(['git', '-C', str(root / 'vendor/AWP'),
            'rev-parse', 'HEAD'], text=True).strip(),
        'comparison_period_start_inclusive': start.isoformat(),
        'comparison_period_end_exclusive': end.isoformat(),
        'monthly_intervals': len(monthly_intervals(start, end)),
        'objects_by_regime': {key: int(value) for key, value in object_ids.items()},
        'selected_source_element_epochs': len(selected),
        'comparison_rows': len(rows),
        'csv_sha256': csv_hash,
        'source_manifest_sha256': source_manifest_hash,
        'lead_hours': list(LEAD_HOURS),
        'awp_models': ['two-body + J2', 'two-body + J2 + nominal drag for LEO'],
        'drag_assumptions': {'area_mass_m2_kg': 0.01, 'drag_coefficient': 2.2,
            'density_model': 'piecewise standard-atmosphere table with log-linear interpolation'},
        'frame': 'GCRS axes; source and reference SGP4 TEME states transformed with Astropy',
        'frame_transform_provenance': frame_transform_provenance(),
        'summary_by_regime_model_and_lead': summarize(rows),
        'limitations': [
            'This is a four-object model-to-model sensitivity analysis, not validation against independent orbit truth.',
            'Each monthly comparison starts from a source element epoch selected near the interval midpoint; the element is held fixed for the following 24 hours.',
            'AWP uses two-body gravity plus J2; the LEO drag case uses nominal ballistic properties and a simplified atmosphere.',
            'No maneuvers, covariance propagation, or element updates are applied during each 24-hour comparison.',
            'The historical element archive is reduced precision and omits original TLE lines and some fields.',
        ],
        'csv': csv_path.name,
    }
    (output / 'summary.json').write_text(json.dumps(summary, indent=2, allow_nan=False) + '\n')
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start', default='2022-10-09T00:00:00Z')
    parser.add_argument('--end', default='2026-10-09T00:00:00Z')
    parser.add_argument('--output', default=str(ROOT / 'outputs/awp-historical-sensitivity-2022-2026'))
    parser.add_argument('--objects', nargs=4, type=int, metavar=('LEO', 'MEO', 'GEO', 'HEO'),
        default=[DEFAULT_OBJECTS[key] for key in ('leo', 'meo', 'geo', 'heo')])
    args = parser.parse_args()
    object_ids = dict(zip(('leo', 'meo', 'geo', 'heo'), args.objects))
    print(json.dumps(run(args.output, args.start, args.end, object_ids), indent=2))


if __name__ == '__main__':
    main()
