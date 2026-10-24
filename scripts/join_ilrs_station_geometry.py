"""Match ILRS normal points to dated SLRF2020 optical-station coordinates."""
import csv
import argparse
import datetime as dt
import json
import math
import pathlib
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / 'data/ground_sensor/ilrs_lageos1_npt'
ANC = DATA / 'ancillary'


def snx_epoch(value, open_end=False):
    if value == '00:000:00000':
        return None if open_end else dt.datetime(2000, 1, 1, tzinfo=dt.timezone.utc)
    yy, doy, seconds = (int(part) for part in value.split(':'))
    # SINEX two-digit years use the conventional 1950/2050 pivot.
    year = (2000 + yy) if yy < 50 else (1900 + yy)
    return dt.datetime(year, 1, 1, tzinfo=dt.timezone.utc) + dt.timedelta(days=doy - 1, seconds=seconds)


def parse_solutions(path):
    intervals = {}
    estimates = defaultdict(dict)
    reference_epochs = {}
    block = None
    for line in path.read_text(errors='replace').splitlines():
        if line.startswith('+'):
            block = line[1:].strip()
            continue
        if line.startswith('-'):
            block = None
            continue
        if not line or line[0] == '*' or block is None:
            continue
        fields = line.split()
        if block == 'SOLUTION/EPOCHS' and len(fields) >= 7:
            try:
                key = (fields[0].zfill(4), fields[1], int(fields[2]))
                intervals[key] = (snx_epoch(fields[4]), snx_epoch(fields[5], open_end=True))
            except (ValueError, IndexError):
                continue
        elif block == 'SOLUTION/ESTIMATE' and len(fields) >= 10:
            try:
                kind, code, point, solution = fields[1], fields[2].zfill(4), fields[3], int(fields[4])
                key = (code, point, solution)
                reference_epochs[key] = snx_epoch(fields[5])
                estimates[key][kind] = float(fields[8])
            except (ValueError, IndexError):
                continue
    result = []
    for key, values in estimates.items():
        if not all(name in values for name in ('STAX','STAY','STAZ','VELX','VELY','VELZ')):
            continue
        if key not in intervals or key not in reference_epochs:
            continue
        result.append({'key': key, 'start': intervals[key][0], 'end': intervals[key][1],
            'reference_epoch': reference_epochs[key],
            'xyz_m': [values['STAX'], values['STAY'], values['STAZ']],
            'velocity_m_per_year': [values['VELX'], values['VELY'], values['VELZ']]})
    return result


def parse_eccentricities(path):
    result = defaultdict(list)
    block = None
    for line in path.read_text(errors='replace').splitlines():
        if line.startswith('+'):
            block = line[1:].strip()
            continue
        if line.startswith('-'):
            block = None
            continue
        if block != 'SITE/ECCENTRICITY' or not line or line[0] in '*%':
            continue
        fields = line.split()
        if len(fields) < 11 or fields[6] != 'UNE':
            continue
        try:
            sod = fields[-1].zfill(8)
            result[sod].append({'start': snx_epoch(fields[4]),
                'end': snx_epoch(fields[5], open_end=True),
                'up_m': float(fields[7]), 'north_m': float(fields[8]), 'east_m': float(fields[9]),
                'site': fields[0].zfill(4), 'solution': int(fields[2])})
        except (ValueError, IndexError):
            continue
    return result


def active(items, when):
    candidates = [item for item in items if (item['start'] is None or item['start'] <= when)
        and (item['end'] is None or when <= item['end'])]
    return candidates[-1] if candidates else None


def ecef_geodetic(xyz):
    x, y, z = xyz
    lon = math.atan2(y, x)
    a, f = 6378137.0, 1 / 298.257223563
    e2 = f * (2 - f)
    p = math.hypot(x, y)
    lat = math.atan2(z, p * (1 - e2))
    for _ in range(8):
        n = a / math.sqrt(1 - e2 * math.sin(lat) ** 2)
        lat = math.atan2(z + e2 * n * math.sin(lat), p)
    return lat, lon


def une_to_ecef(up, north, east, lat, lon):
    sl, cl = math.sin(lat), math.cos(lat)
    so, co = math.sin(lon), math.cos(lon)
    return [-sl * co * north - so * east + cl * co * up,
            -sl * so * north + co * east + cl * so * up,
            cl * north + sl * up]


def dated_xyz(solution, when):
    years = (when - solution['reference_epoch']).total_seconds() / (365.25 * 86400)
    return [p + v * years for p, v in zip(solution['xyz_m'], solution['velocity_m_per_year'])]


def main():
    global DATA, ANC
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', default=str(DATA), help='target-specific ILRS data directory')
    parser.add_argument('--ancillary-dir', help='shared ILRS station solution directory; defaults to <data-dir>/ancillary')
    args = parser.parse_args()
    DATA = pathlib.Path(args.data_dir).resolve()
    ANC = pathlib.Path(args.ancillary_dir).resolve() if args.ancillary_dir else DATA / 'ancillary'
    solution_path = ANC / 'SLRF2020_POS_VEL_2026-02-05.snx'
    eccentricity_path = ANC / 'ILRS_station_eccentricities_UNE_2026-05-27.snx'
    source = DATA / 'normal_points.csv'
    for path in (solution_path, eccentricity_path, source):
        if not path.is_file():
            raise SystemExit(f'Missing {path}; run scripts/download_ilrs_ancillary.py first')
    solutions = parse_solutions(solution_path)
    eccentricities = parse_eccentricities(eccentricity_path)
    by_site = defaultdict(list)
    for solution in solutions:
        by_site[solution['key'][0]].append(solution)

    station_windows = {}
    normal_points = 0
    with source.open(newline='') as stream:
        for row in csv.DictReader(stream):
            normal_points += 1
            try:
                cdp = f"{int(row['station_cdp_id']):04d}"
                system = f"{int(row['station_system_number']):02d}"
                occupation = f"{int(row['station_occupation']):02d}"
                sod = cdp + system + occupation
                when = dt.datetime.fromisoformat(row['observation_time_utc'] or row['session_start_utc'])
                if when.tzinfo is None:
                    when = when.replace(tzinfo=dt.timezone.utc)
                when = when.astimezone(dt.timezone.utc)
            except (ValueError, TypeError):
                continue
            item = station_windows.setdefault(sod, {'cdp': cdp, 'system': system, 'occupation': occupation,
                'name': row['station_name'], 'records': 0, 'first': when, 'last': when})
            item['records'] += 1
            item['first'] = min(item['first'], when)
            item['last'] = max(item['last'], when)

    rows = []
    matched_coordinates = matched_ecc = matched_both = 0
    missing_coordinates = []
    missing_eccentricities = []
    for sod, window in sorted(station_windows.items()):
        when = window['first'] + (window['last'] - window['first']) / 2
        solution = active(by_site.get(window['cdp'], []), when)
        ecc = active(eccentricities.get(sod, []), when)
        if solution:
            matched_coordinates += 1
        else:
            missing_coordinates.append(sod)
        if ecc:
            matched_ecc += 1
        else:
            missing_eccentricities.append(sod)
        if not solution:
            continue
        monument_xyz = dated_xyz(solution, when)
        offset_xyz = [0.0, 0.0, 0.0]
        if ecc:
            lat, lon = ecef_geodetic(monument_xyz)
            offset_xyz = une_to_ecef(ecc['up_m'], ecc['north_m'], ecc['east_m'], lat, lon)
            matched_both += 1
        optical_xyz = [a + b for a, b in zip(monument_xyz, offset_xyz)]
        rows.append({'station_sod': sod, 'station_name': window['name'], 'cdp_id': window['cdp'],
            'system_number': window['system'], 'occupation': window['occupation'],
            'normal_points': window['records'], 'first_observation_utc': window['first'].isoformat(),
            'last_observation_utc': window['last'].isoformat(), 'coordinate_solution': solution['key'][2],
            'coordinate_reference_epoch': solution['reference_epoch'].isoformat(),
            'coordinate_position_frame': 'ITRF2020', 'position_epoch_utc': when.isoformat(),
            'monument_x_m': monument_xyz[0], 'monument_y_m': monument_xyz[1], 'monument_z_m': monument_xyz[2],
            'velocity_x_m_per_year': solution['velocity_m_per_year'][0],
            'velocity_y_m_per_year': solution['velocity_m_per_year'][1],
            'velocity_z_m_per_year': solution['velocity_m_per_year'][2],
            'eccentricity_start_utc': ecc['start'].isoformat() if ecc and ecc['start'] else '',
            'eccentricity_end_utc': ecc['end'].isoformat() if ecc and ecc['end'] else '',
            'eccentricity_up_m': ecc['up_m'] if ecc else None,
            'eccentricity_north_m': ecc['north_m'] if ecc else None,
            'eccentricity_east_m': ecc['east_m'] if ecc else None,
            'optical_reference_x_m': optical_xyz[0], 'optical_reference_y_m': optical_xyz[1],
            'optical_reference_z_m': optical_xyz[2], 'eccentricity_matched': bool(ecc)})

    output_csv = DATA / 'station_geometry.csv'
    if rows:
        with output_csv.open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    ancillary = json.loads((ANC / 'ancillary_manifest.json').read_text()) if (ANC / 'ancillary_manifest.json').exists() else {}
    summary = {'status': 'completed', 'source_normal_points': str(source.relative_to(ROOT)),
        'source_normal_point_count': normal_points, 'observed_station_sod_count': len(station_windows),
        'station_coordinate_solutions': len(solutions), 'station_eccentricity_sod_records': sum(map(len, eccentricities.values())),
        'station_sods_with_dated_coordinate_solution': matched_coordinates,
        'station_sods_with_dated_eccentricity': matched_ecc,
        'station_sods_with_both': matched_both,
        'normal_points_by_station_sod': sum(item['records'] for item in station_windows.values()),
        'station_geometry_csv': str(output_csv.relative_to(ROOT)),
        'missing_coordinate_sods': missing_coordinates, 'missing_eccentricity_sods': missing_eccentricities,
        'ancillary_manifest': str((ANC / 'ancillary_manifest.json').relative_to(ROOT)),
        'corrections_not_applied': ['TEME-to-ITRF transformation using UT1-UTC and polar motion.',
            'ILRS Data Handling File range/time corrections.',
            'LAGEOS station- and time-dependent center-of-mass model (package unavailable).',
            'CRD supplementary range corrections and calibration records.'],
        'interpretation': 'This joins measured ground observations to time-propagated ITRF2020 station optical-reference-point coordinates. It is station geometry metadata, not yet a measured-versus-predicted range validation.'}
    (DATA / 'station_geometry_summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
