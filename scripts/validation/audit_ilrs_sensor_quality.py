"""Verify ILRS input bytes, range arithmetic, joins, and clustered contrasts."""
from __future__ import annotations

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))


import argparse
import collections
import csv
import datetime as dt
import json
import math
from pathlib import Path
import random
import statistics

from godsat.orbits import ROOT
from scripts.experiments.run_full_catalog_tasking import sha256

TARGETS = ('lageos1', 'lageos2', 'lares', 'starlette')


def number(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def close(actual, expected, label, tolerance=1e-9):
    if actual is None or expected is None or not math.isclose(float(actual), float(expected), abs_tol=tolerance, rel_tol=1e-11):
        raise ValueError(f'Unreproduced ILRS value: {label}')


def check_range_arithmetic(row):
    raw = float(row['observed_one_way_equivalent_range_m']) - float(row['predicted_one_way_equivalent_range_m'])
    close(float(row['range_residual_m']), raw, 'observed minus predicted range', 1e-6)
    corrected = raw - (number(row['dhf_range_bias_correction_m']) or 0.) - (number(row['dhf_time_bias_range_equivalent_m']) or 0.)
    close(float(row['range_residual_with_dhf_biases_m']), corrected, 'DHF-corrected range residual', 1e-6)
    return float(row['range_residual_with_dhf_biases_m'])


def quality_contrast(rows, replicates, seed):
    clusters = collections.OrderedDict()
    low_count = high_count = 0
    for station, day, rate, absolute in rows:
        if rate is None or not 0 <= rate <= 100 or absolute > 100:
            continue
        groups = clusters.setdefault((station, day), [[], []])
        if rate < 1:
            groups[0].append(absolute); low_count += 1
        elif rate >= 10:
            groups[1].append(absolute); high_count += 1
    differences = [statistics.fmean(low)-statistics.fmean(high)
                   for low, high in clusters.values() if low and high]
    if not differences:
        raise ValueError('No paired low/high station-day clusters')
    rng = random.Random(seed)
    draws = sorted(statistics.fmean(differences[rng.randrange(len(differences))]
                   for _ in differences) for _ in range(replicates))
    return {'clusters': len(differences), 'mean': statistics.fmean(differences),
            'ci95': [draws[int(.025*(replicates-1))], draws[int(.975*(replicates-1))]],
            'low_return_points': low_count, 'high_return_points': high_count}


def row_key(row):
    return (row['source_file'], row['observation_time_utc'].strip(),
            row['station_name'].strip(), row['epoch_event'].strip())


def audit_target(root, target):
    root = Path(root).resolve(); folder = root/f'data/ground_sensor/ilrs_{target}_npt'
    archive = json.loads((folder/'manifest.json').read_text())
    cpf = json.loads((folder/'cpf_manifest.json').read_text())
    quality = json.loads((folder/'return_quality_analysis.json').read_text())
    ranges = json.loads((folder/'range_validation_summary.json').read_text())
    if archive.get('files_with_errors') or cpf.get('download_errors'):
        raise ValueError(f'Unresolved download errors for {target}')
    paths = {}
    for kind, manifest in (('crd', archive), ('cpf', cpf)):
        known = set()
        for item in manifest['files']:
            path = (root/item['path']).resolve()
            if not path.is_relative_to(root) or path.stat().st_size != item['bytes'] or sha256(path) != item['sha256']:
                raise ValueError(f'{kind} source checksum or size differs: {path}')
            known.add(item['path'])
        paths[kind] = known
    for name, entry in quality['inputs'].items():
        path = Path(name).resolve() if Path(name).is_absolute() else (root/name).resolve()
        if not path.is_relative_to(root) or sha256(path) != entry['sha256']:
            raise ValueError(f'Return-quality source checksum differs: {name}')
    expected_id = int(cpf['target_norad_id'])
    normals = collections.defaultdict(list)
    normal_count = 0
    with (folder/'normal_points.csv').open(newline='') as stream:
        for row in csv.DictReader(stream):
            normal_count += 1
            if row['source_file'] not in paths['crd'] or int(row['norad_id']) != expected_id:
                raise ValueError('Normal point is not linked to the verified target/source archive')
            distance = number(row.get('two_way_range_km_from_time_of_flight'))
            flight = number(row.get('time_of_flight_seconds'))
            if distance is not None and flight is not None:
                close(distance*1000, flight*299792458/2, 'CRD time-of-flight range', 1e-5)
            if distance is not None and row['observation_time_utc'].strip():
                normals[row_key(row)].append([distance*1000, number(row.get('return_rate_percent')), False])
    if normal_count != archive['parsed_normal_points']['records'] or normal_count != ranges['source_observations']:
        raise ValueError('Parsed normal-point counts differ from source/range manifests')
    corrected, joined, valid = [], [], []
    range_count = 0
    with (folder/'range_validation.csv').open(newline='') as stream:
        for row in csv.DictReader(stream):
            range_count += 1
            if (row['cpf_file'] not in paths['cpf'] or row['source_file'] not in paths['crd']
                    or int(row['norad_id']) != expected_id or row['epoch_event'] != '2'
                    or row['data_quality_alert'] not in ('0', '')):
                raise ValueError('Range row violates source, target, or acquisition filters')
            residual = check_range_arithmetic(row); corrected.append(residual)
            available = [candidate for candidate in normals.get(row_key(row), []) if not candidate[2]]
            if not available:
                continue
            observed = float(row['observed_one_way_equivalent_range_m'])
            candidate = min(available, key=lambda item: abs(item[0]-observed))
            if abs(candidate[0]-observed) > 25:
                continue
            candidate[2] = True
            entry = (row['station_name'].strip(), row['observation_time_utc'][:10], candidate[1], abs(residual))
            joined.append(entry)
            if candidate[1] is not None and 0 <= candidate[1] <= 100 and abs(residual) <= 100:
                valid.append(entry)
    if range_count != ranges['range_residual_rows'] or len(joined) != quality['join']['joined_rows'] or len(valid) != quality['validity']['analyzed_rows']:
        raise ValueError('Range or return-quality row coverage does not reproduce')
    trimmed = sorted(abs(value) for value in corrected if abs(value) <= 100)
    robust = ranges['robust_dhf_bias_corrected_residual_m_within_abs_100m']
    if robust['count'] != len(trimmed) or robust['excluded_abs_over_100m'] != len(corrected)-len(trimmed):
        raise ValueError('Range residual screen counts do not reproduce')
    for label, value in (('median_abs', statistics.median(trimmed)), ('mae', statistics.fmean(trimmed)),
                          ('p95_abs', trimmed[int(.95*len(trimmed))]), ('p99_abs', trimmed[int(.99*len(trimmed))])):
        close(robust[label], value, label)
    recomputed = quality_contrast(joined, int(quality['bootstrap']['replicates']), int(quality['bootstrap']['seed']))
    saved = quality['paired_station_day_low_vs_high_return']
    for label in ('clusters', 'mean', 'low_return_points', 'high_return_points'):
        close(saved[label], recomputed[label], f'paired contrast {label}')
    for saved_value, value in zip(saved['ci95'], recomputed['ci95']):
        close(saved_value, value, 'paired station-day bootstrap interval')
    return {'target': target, 'status': 'source_hashes_and_numerics_verified',
        'raw_crd_files_verified': len(paths['crd']), 'cpf_files_verified': len(paths['cpf']),
        'normal_points_checked': normal_count, 'range_arithmetic_rows_checked': range_count,
        'return_quality_joined_rows_checked': len(joined), 'analyzed_rows_checked': len(valid),
        'station_day_contrast': recomputed,
        'unresolved_cpf_reference_count': len(cpf.get('not_found_or_ambiguous_references', [])),
        'scope': 'All retained CRD/CPF bytes and derived range arithmetic were checked. Return-quality joins and station-day bootstrap were independently recomputed. Operational CPF predictions are not independent orbital truth; unavailable CPF references and acquisition conditioning remain limitations.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--output', type=Path, default=Path('outputs/ilrs-cross-target-sensor-quality-20261024/independent_audit.json'))
    args = parser.parse_args()
    rows = []
    for target in TARGETS:
        rows.append(audit_target(args.root, target))
        print(f'Verified {target}: {rows[-1]["range_arithmetic_rows_checked"]:,} range rows', flush=True)
    output = args.output if args.output.is_absolute() else args.root/args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({'status': 'passed_source_and_numerical_reproduction',
        'audited_utc': dt.datetime.now(dt.timezone.utc).isoformat(), 'targets': rows}, indent=2, allow_nan=False)+'\n')


if __name__ == '__main__':
    main()
