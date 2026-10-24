"""Fetch exact CPF predictions referenced by one target's four-year CRD data."""
import argparse
import concurrent.futures
import csv
import datetime as dt
import hashlib
import html.parser
import json
import pathlib
import re
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / 'data/ground_sensor/ilrs_lageos1_npt'
OUT = DATA / 'cpf'
BASE = 'https://edc.dgfi.tum.de/pub/slr/cpf_predicts_v2'


class Links(html.parser.HTMLParser):
    def __init__(self, target='lageos1'):
        super().__init__()
        self.target = target
        self.values = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == 'a':
            href = dict(attrs).get('href', '')
            name = href.rsplit('/', 1)[-1]
            if re.fullmatch(re.escape(self.target)+r'_cpf_\d{6}_\d{5}\.[a-z0-9]{3}', name):
                self.values.append(name)


def year_from_crd(yy):
    yy = int(yy)
    return 1900 + yy if yy >= 50 else 2000 + yy


def parse_cpf(path):
    h1 = h2 = None
    for line in path.read_text(errors='replace').splitlines():
        fields = line.split()
        if not fields:
            continue
        if fields[0] == 'H1':
            h1 = fields
        elif fields[0] == 'H2':
            h2 = fields
        if h1 and h2:
            break
    if not h1 or not h2 or len(h1) < 10 or len(h2) < 16:
        raise ValueError('missing or incomplete CPF H1/H2 headers')
    production_year = int(h1[4])
    sequence = f'{int(h1[8]):03d}{int(h1[9]):02d}'
    # H2 contains ILRS ID, SIC, then NORAD ID.
    sat_id = str(int(h2[3]))
    start = dt.datetime(*(int(v) for v in h2[4:10]), tzinfo=dt.timezone.utc)
    end = dt.datetime(*(int(v) for v in h2[10:16]), tzinfo=dt.timezone.utc)
    return {'provider': h1[3].lower(), 'year': start.year,
            'production_year': production_year, 'sequence': sequence,
            'satellite_id': sat_id, 'start': start, 'end': end}


def download(item):
    name, url, path, expected = item
    if path.is_file():
        try:
            parsed = parse_cpf(path)
            if (parsed['provider'], parsed['year'], parsed['sequence'], parsed['satellite_id']) == expected:
                raw = path.read_bytes()
                return {'name': name, 'path': str(path.relative_to(ROOT)), 'bytes': len(raw),
                        'sha256': hashlib.sha256(raw).hexdigest(), 'status': 'cached',
                        'cpf_start_utc': parsed['start'].isoformat(), 'cpf_end_utc': parsed['end'].isoformat()}
        except (OSError, ValueError):
            pass
    request = urllib.request.Request(url, headers={'User-Agent': 'GoDSAT-research/1.0'})
    with urllib.request.urlopen(request, timeout=60) as response:
        raw = response.read()
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_bytes(raw)
    parsed = parse_cpf(tmp)
    if (parsed['provider'], parsed['year'], parsed['sequence'], parsed['satellite_id']) != expected:
        tmp.unlink(missing_ok=True)
        raise ValueError(f'CPF header does not match H5 reference: {name}')
    tmp.replace(path)
    return {'name': name, 'path': str(path.relative_to(ROOT)), 'bytes': len(raw),
            'sha256': hashlib.sha256(raw).hexdigest(), 'status': 'downloaded',
            'cpf_start_utc': parsed['start'].isoformat(), 'cpf_end_utc': parsed['end'].isoformat()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', default='lageos1', help='lowercase ILRS archive target slug')
    parser.add_argument('--norad', type=int, default=8820, help='NORAD catalog ID for target validation')
    parser.add_argument('--data-dir', default=str(DATA), help='target-specific ILRS data directory')
    args = parser.parse_args()
    if not re.fullmatch(r'[a-z0-9]+', args.target):
        raise SystemExit('Target slug must contain lowercase letters and digits only')
    data = pathlib.Path(args.data_dir).resolve()
    out = data / 'cpf'
    source = data / 'normal_points.csv'
    if not source.exists():
        raise SystemExit('Run scripts/parse_ilrs_lageos.py first')
    references = {}
    with source.open(newline='') as stream:
        for row in csv.DictReader(stream):
            if row.get('prediction_type') != '1' or not row.get('prediction_provider'):
                continue
            year = year_from_crd(row['prediction_year'])
            provider = row['prediction_provider'].lower()
            sequence = row['prediction_sequence'].zfill(5)
            key = (year, provider, sequence)
            references[key] = references.get(key, 0) + 1

    indexes = {}
    for year in sorted({key[0] for key in references}):
        url = f'{BASE}/{year}/{args.target}/'
        request = urllib.request.Request(url, headers={'User-Agent': 'GoDSAT-research/1.0'})
        with urllib.request.urlopen(request, timeout=60) as response:
            page = response.read().decode('utf-8', 'replace')
        links = Links(args.target)
        links.feed(page)
        indexes[year] = links.values

    requested = []
    reference_names = {}
    missing = []
    for (year, provider, sequence), observations in sorted(references.items()):
        candidates = [name for name in indexes[year]
                      if name.endswith(f'_{sequence}.{provider}')]
        if len(candidates) != 1:
            missing.append({'year': year, 'provider': provider, 'sequence': sequence,
                            'observations': observations, 'reason': 'no exact unique archive filename',
                            'candidates': candidates})
            continue
        name = candidates[0]
        path = out / str(year) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        requested.append((name, f'{BASE}/{year}/{args.target}/{name}', path,
                          (provider, year, sequence, str(args.norad))))
        reference_names[(year, provider, sequence)] = name

    results = []
    errors = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(download, item): item for item in requested}
        for future in concurrent.futures.as_completed(futures):
            try:
                results.append(future.result())
            except (OSError, urllib.error.URLError, ValueError) as exc:
                name = futures[future][0]
                errors.append({'name': name, 'error': str(exc)})
            if len(results) % 100 == 0 and results:
                print(f'cached/downloaded {len(results)}/{len(requested)} exact CPF files', flush=True)

    obs_coverage = []
    index_by_file = {r['name']: r for r in results}
    # Match only observations whose reported event epoch is covered by the exact CPF H2 interval.
    covered = 0
    outside = 0
    with source.open(newline='') as stream:
        for row in csv.DictReader(stream):
            if row.get('prediction_type') != '1' or not row.get('observation_time_utc'):
                continue
            year = year_from_crd(row['prediction_year'])
            key = (year, row['prediction_provider'].lower(), row['prediction_sequence'].zfill(5))
            name = reference_names.get(key)
            result = index_by_file.get(name)
            if not result:
                continue
            when = dt.datetime.fromisoformat(row['observation_time_utc'])
            start = dt.datetime.fromisoformat(result['cpf_start_utc'])
            end = dt.datetime.fromisoformat(result['cpf_end_utc'])
            if start <= when <= end:
                covered += 1
            else:
                outside += 1
    manifest = {'status': 'completed' if not errors else 'partial',
        'reference_resolution_status': 'complete' if not missing else 'partial',
        'source': f'EUROLAS Data Center ILRS CPF v2 {args.target} prediction archive',
        'target_archive_slug': args.target, 'target_norad_id': args.norad,
        'base_url': BASE, 'unique_crd_references': len(references),
        'unique_exact_cpf_files_requested': len(requested),
        'cpf_files_downloaded_or_cached': len(results), 'covered_observation_rows': covered,
        'observation_rows_outside_cpf_interval': outside,
        'not_found_or_ambiguous_references': missing, 'download_errors': errors,
        'files': sorted(results, key=lambda r: r['name']),
        'limitations': ['Only CRD-referenced CPF files are fetched; this is not an all-target CPF archive.',
            'CPF predictions are operational tracking predictions, not independent truth or a calibrated orbit determination product.']}
    (data / 'cpf_manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({'status': manifest['status'],
        'reference_resolution_status': manifest['reference_resolution_status'],
        'unique_crd_references': manifest['unique_crd_references'],
        'unique_exact_cpf_files_requested': manifest['unique_exact_cpf_files_requested'],
        'cpf_files_downloaded_or_cached': manifest['cpf_files_downloaded_or_cached'],
        'covered_observation_rows': manifest['covered_observation_rows'],
        'observation_rows_outside_cpf_interval': manifest['observation_rows_outside_cpf_interval'],
        'unresolved_reference_count': len(manifest['not_found_or_ambiguous_references']),
        'download_error_count': len(manifest['download_errors'])}, indent=2))


if __name__ == '__main__':
    main()
