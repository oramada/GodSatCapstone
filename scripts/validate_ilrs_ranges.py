"""Compare a target's CRD normal-point ranges with their referenced ILRS CPF."""
import argparse
import csv
import datetime as dt
import json
import math
import pathlib
import statistics
from collections import Counter, defaultdict

from scripts.download_ilrs_cpf import parse_cpf, year_from_crd

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / 'data/ground_sensor/ilrs_lageos1_npt'
HANDLING_FILE = DATA / 'ancillary/ILRS_Data_Handling_File_2026-05-27.snx'
SPEED_OF_LIGHT_M_S = 299_792_458.0


def dhf_epoch(value, open_end=False):
    yy, doy, sod = (int(part) for part in value.split(':'))
    year = 2000 + yy if yy < 50 else 1900 + yy
    if open_end and yy == 0 and doy == 0 and sod == 0:
        return None
    return dt.datetime(year, 1, 1, tzinfo=dt.timezone.utc) + dt.timedelta(days=doy - 1, seconds=sod)


def parse_dhf_biases(path):
    """Parse the current ILRS DHF range and time bias blocks for 532-nm sites."""
    result = {'range': defaultdict(list), 'time': defaultdict(list)}
    block = None
    for line in path.read_text(errors='replace').splitlines():
        if line.startswith('+'):
            block = line[1:].strip()
            continue
        if line.startswith('-'):
            block = None
            continue
        if block not in {'MODEL/RANGE_BIAS', 'MODEL/TIME_BIAS'} or not line.strip() or line[0] in '*%':
            continue
        fields = line.split()
        if len(fields) < 8 or not fields[0].isdigit() or fields[1] not in {'51', '--'}:
            continue
        try:
            site = fields[0].zfill(4)
            if block == 'MODEL/RANGE_BIAS' and (len(fields) < 10 or fields[2] != '501'):
                continue
            if block == 'MODEL/TIME_BIAS' and fields[2] not in {'501', '----'}:
                continue
            start = dhf_epoch(fields[4])
            end = dhf_epoch(fields[5], open_end=True)
            value = float(fields[7])
            unit_idx = 9 if block == 'MODEL/RANGE_BIAS' else 10
            unit = fields[unit_idx].lower() if len(fields) > unit_idx else ''
            rate_idx = 9 if block == 'MODEL/TIME_BIAS' else -1
            try:
                rate = float(fields[rate_idx]) if rate_idx > 0 else 0.0
            except ValueError:
                rate = 0.0
            result['range' if block == 'MODEL/RANGE_BIAS' else 'time'][site].append(
                {'start': start, 'end': end, 'value': value, 'rate': rate, 'unit': unit})
        except (ValueError, IndexError):
            continue
    return result


def active_dhf_bias(items, when):
    active = [row for row in items if row['start'] <= when and (row['end'] is None or when <= row['end'])]
    if not active:
        return None
    return max(active, key=lambda row: row['start'])


def dhf_correction(biases, kind, site, when):
    item = active_dhf_bias(biases[kind].get(site, []), when)
    if item is None:
        return None
    if kind == 'range':
        # DHF range-bias entries use mm.
        return item['value'] / 1000.0
    # Time-bias entries are microseconds unless explicitly labelled ms.
    scale = 1e-3 if item['unit'] == 'ms' else 1e-6
    elapsed_days = (when - item['start']).total_seconds() / 86400.0
    value = item['value'] + item['rate'] * elapsed_days
    return value * scale * SPEED_OF_LIGHT_M_S / 2.0


def parse_ephemeris(path):
    meta = parse_cpf(path)
    times, xyz = [], []
    h5_correction = None
    frame = None
    com_applied = None
    for line in path.read_text(errors='replace').splitlines():
        fields = line.split()
        if not fields:
            continue
        if fields[0] == 'H2' and len(fields) >= 23:
            # CPF H2: reference frame at field 19, CoM correction flag at 21.
            frame, com_applied = int(fields[19]), int(fields[21])
        elif fields[0] == 'H5' and len(fields) > 1:
            try:
                h5_correction = float(fields[1])
            except ValueError:
                h5_correction = None
        elif fields[0] == '10' and len(fields) >= 8 and fields[1] == '0':
            mjd, sod = int(fields[2]), float(fields[3])
            times.append((mjd - 51544) * 86400.0 + (sod - 43200.0))  # seconds from J2000 UTC noon
            xyz.append((float(fields[5]), float(fields[6]), float(fields[7])))
    if len(times) < 10:
        raise ValueError('CPF contains fewer than ten common-epoch position records')
    if frame != 0:
        raise ValueError(f'CPF reference frame {frame} is not geocentric true body-fixed')
    return {'meta': meta, 'times': times, 'xyz_m': xyz,
            'h5_com_correction_m': h5_correction, 'com_applied': com_applied}


def lagrange10(times, values, query):
    """Interpolate XYZ with the CPF standard 10-point Lagrange polynomial."""
    import bisect
    right = bisect.bisect_left(times, query)
    first = right - 5
    if first < 0 or first + 10 > len(times):
        raise ValueError('No centered 10-point CPF interpolation window')
    selected_t = times[first:first + 10]
    selected_v = values[first:first + 10]
    result = [0.0, 0.0, 0.0]
    for j, tj in enumerate(selected_t):
        weight = 1.0
        for k, tk in enumerate(selected_t):
            if k != j:
                weight *= (query - tk) / (tj - tk)
        for axis in range(3):
            result[axis] += weight * selected_v[j][axis]
    return result


def station_at(geometry, when):
    midpoint = dt.datetime.fromisoformat(geometry['position_epoch_utc'])
    years = (when - midpoint).total_seconds() / (365.25 * 86400.0)
    return [float(geometry[f'optical_reference_{axis}_m']) +
            float(geometry[f'velocity_{axis}_m_per_year']) * years
            for axis in ('x', 'y', 'z')]


def norm_delta(a, b):
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def predicted_range(ephemeris, transmit_time, station_xyz, crd_com_applied=0):
    origin = dt.datetime(2000, 1, 1, 12, tzinfo=dt.timezone.utc)
    query = (transmit_time - origin).total_seconds()
    light_time = 0.03
    for _ in range(6):
        satellite = lagrange10(ephemeris['times'], ephemeris['xyz_m'], query + light_time)
        new_light_time = norm_delta(satellite, station_xyz) / SPEED_OF_LIGHT_M_S
        if abs(new_light_time - light_time) < 1e-12:
            light_time = new_light_time
            break
        light_time = new_light_time
    one_way_range_m = light_time * SPEED_OF_LIGHT_M_S
    # CPF H5 is the radial CoM-to-reflector offset. CRD H4's 0 flag means
    # the observed range has not been shifted to the satellite CoM.
    correction = (ephemeris['h5_com_correction_m'] or 0.0) if (
        ephemeris['com_applied'] == 0 and int(crd_com_applied or 0) == 0) else 0.0
    return one_way_range_m - correction, 2.0 * light_time


def main():
    global DATA, HANDLING_FILE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', default=str(DATA), help='target-specific ILRS data directory')
    parser.add_argument('--handling-file', help='ILRS Data Handling File; defaults to <data-dir>/ancillary')
    args = parser.parse_args()
    DATA = pathlib.Path(args.data_dir).resolve()
    HANDLING_FILE = (pathlib.Path(args.handling_file).resolve() if args.handling_file
        else DATA / 'ancillary/ILRS_Data_Handling_File_2026-05-27.snx')
    source = DATA / 'normal_points.csv'
    station_path = DATA / 'station_geometry.csv'
    manifest_path = DATA / 'cpf_manifest.json'
    for path in (source, station_path, manifest_path):
        if not path.is_file():
            raise SystemExit(f'Missing {path}; parse observations, join stations, and fetch CPF first')
    if not HANDLING_FILE.is_file():
        raise SystemExit(f'Missing current ILRS Data Handling File: {HANDLING_FILE}')
    dhf_biases = parse_dhf_biases(HANDLING_FILE)
    manifest = json.loads(manifest_path.read_text())
    cpf_paths = {}
    for entry in manifest['files']:
        path = ROOT / entry['path']
        if not path.exists():
            continue
        meta = parse_cpf(path)
        cpf_paths[(meta['year'], meta['provider'], meta['sequence'])] = path
    stations = {}
    with station_path.open(newline='') as stream:
        for row in csv.DictReader(stream):
            stations[row['station_sod']] = row

    grouped = defaultdict(list)
    unmatched = Counter()
    total = 0
    with source.open(newline='') as stream:
        for row in csv.DictReader(stream):
            total += 1
            try:
                if row['prediction_type'] != '1':
                    unmatched['no_cpf_prediction_reference'] += 1
                    continue
                year = year_from_crd(row['prediction_year'])
                key = (year, row['prediction_provider'].lower(), row['prediction_sequence'].zfill(5))
                if key not in cpf_paths:
                    unmatched['exact_cpf_not_available'] += 1
                    continue
                grouped[key].append(row)
            except (KeyError, ValueError):
                unmatched['invalid_reference_or_time'] += 1

    output = DATA / 'range_validation.csv'
    counts = Counter()
    residuals = []
    corrected_residuals = []
    station_residuals = defaultdict(list)
    with output.open('w', newline='') as stream:
        fields = ['source_file', 'observation_time_utc', 'station_sod', 'station_name',
            'norad_id', 'prediction_provider', 'prediction_sequence', 'cpf_file',
            'epoch_event', 'data_quality_alert', 'refraction_correction_applied',
            'center_of_mass_correction_applied', 'observed_one_way_equivalent_range_m',
            'predicted_one_way_equivalent_range_m', 'range_residual_m',
            'dhf_range_bias_correction_m', 'dhf_time_bias_range_equivalent_m',
            'crd_refraction_correction_applied', 'range_residual_with_dhf_biases_m',
            'cpf_position_epoch_frame', 'cpf_h5_center_of_mass_offset_m',
            'cpf_center_of_mass_correction_applied', 'cpf_time_coverage']
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for key, rows in grouped.items():
            path = cpf_paths[key]
            try:
                eph = parse_ephemeris(path)
            except (ValueError, OSError):
                unmatched['invalid_cpf_ephemeris'] += len(rows)
                continue
            cpf_time_start = eph['meta']['start']
            cpf_time_end = eph['meta']['end']
            base = dt.datetime(2000, 1, 1, 12, tzinfo=dt.timezone.utc)
            for row in rows:
                try:
                    when = dt.datetime.fromisoformat(row['observation_time_utc'])
                    if not cpf_time_start <= when <= cpf_time_end:
                        unmatched['observation_outside_cpf_validity'] += 1
                        continue
                    if row['epoch_event'] != '2':
                        unmatched['unsupported_epoch_event'] += 1
                        continue
                    if row['data_quality_alert'] not in ('0', ''):
                        unmatched['non_nominal_data_quality'] += 1
                        continue
                    sod = (f"{int(row['station_cdp_id']):04d}"
                           f"{int(row['station_system_number']):02d}"
                           f"{int(row['station_occupation']):02d}")
                    row['station_sod'] = sod
                    station = stations.get(sod)
                    if station is None:
                        unmatched['station_geometry_missing'] += 1
                        continue
                    site = station_at(station, when)
                    range_m, tof_s = predicted_range(eph, when, site,
                        row['center_of_mass_correction_applied'])
                    if (eph['h5_com_correction_m'] is None and eph['com_applied'] == 0
                            and row['center_of_mass_correction_applied'] == '0'):
                        counts['no_CPF_H5_reflector_offset'] += 1
                    observed_m = float(row['time_of_flight_seconds']) * SPEED_OF_LIGHT_M_S / 2.0
                    # These are CRD 532-nm observations. DHF states corrections
                    # are subtracted from the one-way observation; reverse that
                    # sign to correct measured-minus-predicted residuals.
                    rb = dhf_correction(dhf_biases, 'range', row['station_sod'][:4], when)
                    tb = dhf_correction(dhf_biases, 'time', row['station_sod'][:4], when)
                    residual = observed_m - range_m
                    corrected_residual = residual - (rb or 0.0) - (tb or 0.0)
                    counts['validated'] += 1
                    residuals.append(residual)
                    corrected_residuals.append(corrected_residual)
                    station_residuals[sod].append(corrected_residual)
                    writer.writerow({'source_file': row['source_file'],
                        'observation_time_utc': when.isoformat(), 'station_sod': sod,
                        'station_name': row['station_name'], 'norad_id': row['norad_id'],
                        'prediction_provider': row['prediction_provider'],
                        'prediction_sequence': row['prediction_sequence'], 'cpf_file': str(path.relative_to(ROOT)),
                        'epoch_event': row['epoch_event'], 'data_quality_alert': row['data_quality_alert'],
                        'refraction_correction_applied': row['refraction_correction_applied'],
                        'center_of_mass_correction_applied': row['center_of_mass_correction_applied'],
                        'observed_one_way_equivalent_range_m': observed_m,
                        'predicted_one_way_equivalent_range_m': range_m, 'range_residual_m': residual,
                        'dhf_range_bias_correction_m': rb if rb is not None else '',
                        'dhf_time_bias_range_equivalent_m': tb if tb is not None else '',
                        'crd_refraction_correction_applied': row['refraction_correction_applied'],
                        'range_residual_with_dhf_biases_m': corrected_residual,
                        'cpf_position_epoch_frame': 'ITRF/true-body-fixed; 10-point Lagrange',
                        'cpf_h5_center_of_mass_offset_m': eph['h5_com_correction_m'],
                        'cpf_center_of_mass_correction_applied': eph['com_applied'],
                        'cpf_time_coverage': f'{cpf_time_start.isoformat()}..{cpf_time_end.isoformat()}'})
                except (KeyError, ValueError, OverflowError):
                    unmatched['unusable_measurement_or_interpolation'] += 1

    trimmed = [x for x in residuals if abs(x) <= 100.0]
    corrected_trimmed = [x for x in corrected_residuals if abs(x) <= 100.0]
    summary = {'status': 'completed', 'source_observations': total,
        'range_residual_rows': counts['validated'], 'unmatched_observation_counts': dict(unmatched),
        'residual_m': ({'mean': statistics.mean(residuals), 'median': statistics.median(residuals),
            'mae': statistics.mean(abs(x) for x in residuals),
            'rms': math.sqrt(statistics.mean(x*x for x in residuals)),
            'p05': sorted(residuals)[int(.05 * len(residuals))],
            'p95': sorted(residuals)[int(.95 * len(residuals))]} if residuals else None),
        'robust_residual_m_within_abs_100m': ({'count': len(trimmed),
            'excluded_abs_over_100m': len(residuals) - len(trimmed),
            'median': statistics.median(trimmed), 'mae': statistics.mean(abs(x) for x in trimmed),
            'p95_abs': sorted(abs(x) for x in trimmed)[int(.95 * len(trimmed))],
            'p99_abs': sorted(abs(x) for x in trimmed)[int(.99 * len(trimmed))]} if trimmed else None),
        'robust_dhf_bias_corrected_residual_m_within_abs_100m': ({'count': len(corrected_trimmed),
            'excluded_abs_over_100m': len(corrected_residuals) - len(corrected_trimmed),
            'median': statistics.median(corrected_trimmed),
            'median_abs': statistics.median(abs(x) for x in corrected_trimmed),
            'mae': statistics.mean(abs(x) for x in corrected_trimmed),
            'p95_abs': sorted(abs(x) for x in corrected_trimmed)[int(.95 * len(corrected_trimmed))],
            'p99_abs': sorted(abs(x) for x in corrected_trimmed)[int(.99 * len(corrected_trimmed))]} if corrected_trimmed else None),
        'dhf_bias_corrected_residual_m_all_rows': {'median':
            statistics.median(corrected_residuals) if corrected_residuals else None,
            'median_abs': statistics.median(abs(x) for x in corrected_residuals) if corrected_residuals else None,
            'mae': statistics.mean(abs(x) for x in corrected_residuals) if corrected_residuals else None,
            'rows_over_100m_abs': sum(abs(x) > 100.0 for x in corrected_residuals)},
        'by_station': {sod: {'station_name': stations[sod]['station_name'], 'count': len(vals),
            'median_residual_m': statistics.median(vals),
            'mae_m': statistics.mean(abs(x) for x in vals)}
            for sod, vals in sorted(station_residuals.items())},
        'output_csv': str(output.relative_to(ROOT)),
        'interpretation': f"Observed-minus-predicted ILRS {DATA.name.removeprefix('ilrs_').removesuffix('_npt').upper()} one-way-equivalent geometric range residuals using the CPF named by CRD H5. This checks operational ephemeris/range consistency, not independent orbit truth or all-satellite sensor performance.",
        'limitations': ['The current DHF range/time biases are applied where a dated 532-nm entry exists; the DHF is a current recommendation and may not reproduce the historical processing version exactly.',
            'CRD H4 refraction correction flags are preserved but pass-specific atmospheric corrections are not modeled here.',
            'The robust summary excludes residuals above 100 m and is descriptive; it does not prove that those rows are bad data.',
            'Only nominal-quality, event-2 normal points with an exact archived CPF are included.',
            'The CPF was the operational prediction source named by the observations; this is not an independent orbit determination.',
            'Station coordinates use SLRF2020 and have not been explicitly transformed to a prediction-provider-specific terrestrial frame realization.',
            'The range model uses a static ITRF station during the millisecond light-time and neglects station-dependent calibration biases.']}
    (DATA / 'range_validation_summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
