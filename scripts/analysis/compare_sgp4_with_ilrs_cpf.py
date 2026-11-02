"""Compare reconstructed LAGEOS SGP4 states with the ILRS CPF named by CRD."""

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))

import bisect
import argparse
import csv
import datetime as dt
import json
import math
import pathlib
import statistics
from collections import Counter, defaultdict

import duckdb
import numpy as np
from astropy import units as u
from astropy.coordinates import ITRS, TEME, CartesianRepresentation
from astropy.time import Time
from astropy.utils import iers

from godsat.orbits import ROOT, satellite, julian
from scripts.data.download_ilrs_cpf import parse_cpf, year_from_crd
from scripts.validation.validate_ilrs_ranges import lagrange10, parse_ephemeris

DATA = ROOT / 'data/ground_sensor/ilrs_lageos1_npt'
EOP = DATA / 'ancillary/finals2000A.all'
SAT_ID = 8820


def teme_to_itrf(times, positions_km, eop_table):
    """Transform TEME positions to ITRS with the supplied IERS EOP table."""
    obstime = Time(times)
    teme = TEME(CartesianRepresentation(np.asarray(positions_km, dtype=float).T * u.km),
                obstime=obstime)
    with iers.earth_orientation_table.set(eop_table):
        fixed = teme.transform_to(ITRS(obstime=obstime))
    return fixed.cartesian.xyz.to_value(u.km).T


def load_history(sat_id=SAT_ID):
    db = duckdb.connect()
    db.execute("SET TimeZone='UTC'")
    query = '''SELECT norad_id, epoch, inclination, raan, eccentricity, arg_perigee,
        mean_anomaly, mean_motion, mean_motion_dot, bstar
        FROM read_parquet(?) WHERE norad_id = ?
        ORDER BY epoch, inclination, raan, eccentricity, arg_perigee, mean_anomaly,
            mean_motion, mean_motion_dot, bstar'''
    rows = db.execute(query, [str(ROOT / 'data/raw/tle_*.parquet'), int(sat_id)]).fetchall()
    epochs = [row[1] for row in rows]
    records = []
    for row in rows:
        records.append({'norad_id': row[0], 'epoch': row[1], 'inclination': row[2],
            'raan': row[3], 'eccentricity': row[4], 'arg_perigee': row[5],
            'mean_anomaly': row[6], 'mean_motion': row[7],
            'mean_motion_dot': row[8], 'bstar': row[9]})
    grouped = defaultdict(set)
    for row in rows:
        grouped[row[1]].add(tuple(row[2:]))
    duplicate_epoch_rows = len(rows) - len(grouped)
    conflicting_duplicate_epochs = sum(len(values) > 1 for values in grouped.values())
    return epochs, records, duplicate_epoch_rows, conflicting_duplicate_epochs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', default=str(DATA), help='target-specific ILRS data directory')
    parser.add_argument('--norad', type=int, default=SAT_ID, help='target NORAD catalog ID')
    parser.add_argument('--eop', default=str(EOP), help='IERS Earth-orientation data file')
    args = parser.parse_args()
    data = pathlib.Path(args.data_dir).resolve()
    eop_path = pathlib.Path(args.eop).resolve()
    sat_id = int(args.norad)
    for path in (eop_path, data / 'normal_points.csv', data / 'cpf_manifest.json'):
        if not path.is_file():
            raise SystemExit(f'Missing {path}; fetch IERS EOP, parse CRD, and download CPF first')
    eop_table = iers.IERS_A.open(str(eop_path))
    epochs, records, duplicate_epoch_rows, conflicting_duplicate_epochs = load_history(sat_id)
    sats = {}
    manifest = json.loads((data / 'cpf_manifest.json').read_text())
    cpf_paths = {}
    for entry in manifest['files']:
        path = ROOT / entry['path']
        if not path.exists():
            continue
        meta = parse_cpf(path)
        cpf_paths[(meta['year'], meta['provider'], meta['sequence'])] = path

    grouped_rows = defaultdict(list)
    unmatched = Counter()
    with (data / 'normal_points.csv').open(newline='') as stream:
        for row in csv.DictReader(stream):
            if row.get('prediction_type') != '1':
                continue
            if row.get('epoch_event') != '2':
                unmatched['unsupported_crd_epoch_event'] += 1
                continue
            if row.get('data_quality_alert') not in ('0', ''):
                unmatched['non_nominal_crd_quality'] += 1
                continue
            try:
                when = dt.datetime.fromisoformat(row['observation_time_utc'])
                year = year_from_crd(row['prediction_year'])
                key = (year, row['prediction_provider'].lower(), row['prediction_sequence'].zfill(5))
                if key not in cpf_paths:
                    unmatched['exact_cpf_not_available'] += 1
                    continue
                grouped_rows[key].append((when, row))
            except (KeyError, ValueError):
                unmatched['invalid_reference_or_time'] += 1
    candidates = []
    for key, observations in grouped_rows.items():
        path = cpf_paths[key]
        cpf = parse_cpf(path)
        if cpf['start'] > cpf['end']:
            unmatched['invalid_cpf_interval'] += 1
            continue
        eph = parse_ephemeris(path)
        for when, row in observations:
            if not cpf['start'] <= when <= cpf['end']:
                unmatched['outside_cpf_interval'] += 1
                continue
            index = bisect.bisect_right(epochs, when) - 1
            if index < 0:
                unmatched['no_prior_historical_element'] += 1
                continue
            age_hours = (when - epochs[index]).total_seconds() / 3600.0
            if age_hours > 72:
                unmatched['historical_element_older_than_72h'] += 1
                continue
            tle = records[index]
            sat_key = tle['epoch']
            if sat_key not in sats:
                sats[sat_key] = satellite(tle)
            error, pos, _ = sats[sat_key].sgp4(*julian(when))
            if error:
                unmatched[f'sgp4_error_{error}'] += 1
                continue
            query = (when - dt.datetime(2000, 1, 1, 12, tzinfo=dt.timezone.utc)).total_seconds()
            try:
                cpf_xyz = lagrange10(eph['times'], eph['xyz_m'], query)
            except ValueError:
                unmatched['no_centered_cpf_interpolation_window'] += 1
                continue
            candidates.append({'when': when, 'cpf_xyz_km': [x / 1000.0 for x in cpf_xyz],
                'teme_xyz_km': list(pos), 'element_epoch': tle['epoch'],
                'element_age_hours': age_hours, 'cpf_file': str(path.relative_to(ROOT)),
                'provider': key[1], 'station': row['station_name'], 'station_sod':
                    f"{int(row['station_cdp_id']):04d}{int(row['station_system_number']):02d}{int(row['station_occupation']):02d}"})

    if not candidates:
        raise SystemExit(f'No comparable observations; exclusions={dict(unmatched)}')
    fixed = teme_to_itrf([x['when'] for x in candidates],
                         [x['teme_xyz_km'] for x in candidates], eop_table)
    separations = []
    by_age = defaultdict(list)
    with (data / 'orbit_model_comparison.csv').open('w', newline='') as stream:
        fields = ['observation_time_utc', 'station_name', 'station_sod', 'cpf_file',
            'cpf_provider', 'historical_element_epoch_utc', 'historical_element_age_hours',
            'sgp4_itrf_x_km', 'sgp4_itrf_y_km', 'sgp4_itrf_z_km',
            'cpf_itrf_x_km', 'cpf_itrf_y_km', 'cpf_itrf_z_km', 'position_separation_km']
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row, state_itrf in zip(candidates, fixed):
            distance = math.sqrt(sum((a-b)**2 for a, b in zip(state_itrf, row['cpf_xyz_km'])))
            separations.append(distance)
            by_age[min(72, int(row['element_age_hours']))].append(distance)
            writer.writerow({'observation_time_utc': row['when'].isoformat(),
                'station_name': row['station'], 'station_sod': row['station_sod'],
                'cpf_file': row['cpf_file'], 'cpf_provider': row['provider'],
                'historical_element_epoch_utc': row['element_epoch'].isoformat(),
                'historical_element_age_hours': row['element_age_hours'],
                'sgp4_itrf_x_km': state_itrf[0], 'sgp4_itrf_y_km': state_itrf[1],
                'sgp4_itrf_z_km': state_itrf[2], 'cpf_itrf_x_km': row['cpf_xyz_km'][0],
                'cpf_itrf_y_km': row['cpf_xyz_km'][1], 'cpf_itrf_z_km': row['cpf_xyz_km'][2],
                'position_separation_km': distance})
    ordered = sorted(separations)
    summary = {'status': 'completed', 'target_norad_id': sat_id,
        'compared_observations': len(separations), 'excluded_observations': dict(unmatched),
        'source_duplicate_epoch_rows': duplicate_epoch_rows,
        'source_epochs_with_conflicting_orbital_elements': conflicting_duplicate_epochs,
        'duplicate_resolution': 'Sort by epoch and every orbital element; when epochs tie, select the lexicographically greatest element tuple.',
        'historical_element_age_hours': {'median': statistics.median(x['element_age_hours'] for x in candidates),
            'p95': sorted(x['element_age_hours'] for x in candidates)[int(.95*len(candidates))]},
        'sgp4_minus_cpf_position_separation_km': {'median': statistics.median(separations),
            'mean': statistics.mean(separations), 'p95': ordered[int(.95*len(ordered))],
            'p99': ordered[int(.99*len(ordered))]},
        'median_separation_km_by_element_age_hour': {str(k): statistics.median(v)
            for k, v in sorted(by_age.items())},
        'eop_source': str(eop_path.relative_to(ROOT)),
        'output_csv': str((data / 'orbit_model_comparison.csv').relative_to(ROOT)),
        'interpretation': 'Reconstructed archived GP-element SGP4 TEME positions transformed to ITRF compared with CPF operational positions at CRD observation epochs. This is a model-to-model diagnostic, not independent truth; the result applies only to the specified target and available comparison sample.'}
    (data / 'orbit_model_comparison_summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
