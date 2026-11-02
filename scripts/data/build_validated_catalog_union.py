"""Combine audited historical grid parts with a final-date refresh and verify every cohort ID."""
from __future__ import annotations

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))


import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path

import duckdb

from godsat.catalog_trajectory import catalog_object_ids
from godsat.orbits import ROOT, utc


def sha256(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(8*1024*1024), b''):value.update(chunk)
    return value.hexdigest()


def verify_membership(connection, paths, expected_ids):
    connection.execute('CREATE OR REPLACE TEMP TABLE expected_ids AS SELECT unnest(?) AS norad_id', [expected_ids])
    rows = connection.execute('''SELECT filename, count(*) AS rows,
        count(DISTINCT r.norad_id) AS objects,
        sum(CASE WHEN e.norad_id IS NULL THEN 1 ELSE 0 END) AS unknown_ids
        FROM read_parquet(?,filename=true,hive_partitioning=false) r
        LEFT JOIN expected_ids e ON r.norad_id=e.norad_id GROUP BY filename''', [paths]).fetchall()
    result = []
    for path, count, objects, unknown in rows:
        if unknown or objects != len(expected_ids):
            raise ValueError(f'Catalog membership differs from the declared cohort: {path}, unknown={unknown}, objects={objects}')
        result.append({'path': path, 'rows': int(count), 'objects': int(objects), 'unknown_id_rows': int(unknown)})
    return result


def build(base, refresh, output):
    base, refresh, output = map(lambda p: p.resolve(), [base, refresh, output])
    source_paths = [base/'manifest.json', base/'validation.json', refresh/'manifest.json', refresh/'independent_audit.json']
    manifest, validation, overlay, overlay_audit = [json.loads(path.read_text()) for path in source_paths]
    if (manifest.get('status') != 'completed' or validation.get('status') != 'validated_complete'
            or validation.get('signature') != manifest.get('signature')
            or validation.get('parts_validated') != len(manifest['parts'])
            or overlay.get('status') != 'completed'
            or overlay_audit.get('status') != 'passed_source_and_baseline_reconciliation'):
        raise ValueError('Completed full-export and final-date source audits are required')
    if (overlay['end_exclusive'] != manifest['end_exclusive']
            or overlay['step_seconds'] != manifest['step_seconds']
            or overlay['objects'] != manifest['object_count']):
        raise ValueError('Final-date refresh changes the declared time/object axes')
    prefix = [part for part in manifest['parts'] if utc(part['start_inclusive']) < utc(overlay['start_inclusive'])]
    replaced = [part for part in manifest['parts'] if part not in prefix]
    if ([{'file': p['file'], 'sha256': p['sha256']} for p in replaced] != overlay['pinned_baseline_parts']
            or not prefix or prefix[-1]['end_exclusive'] != overlay['start_inclusive']):
        raise ValueError('Refreshed interval does not exactly replace a contiguous baseline suffix')
    pieces = [dict(part, path=str(base/part['file'])) for part in prefix]
    pieces.append({'path': str(refresh/overlay['part']['file']),
        'start_inclusive': overlay['start_inclusive'], 'end_exclusive': overlay['end_exclusive'],
        'rows': overlay['rows'], 'sha256': overlay['part']['sha256'],
        'size_bytes': overlay['part']['size_bytes']})
    if (pieces[0]['start_inclusive'] != manifest['start']
            or any(a['end_exclusive'] != b['start_inclusive'] for a,b in zip(pieces,pieces[1:]))
            or sum(piece['rows'] for piece in pieces) != manifest['projected_rows']):
        raise ValueError('Combined part layout contains a gap, overlap or row-count change')
    for index, piece in enumerate(pieces, 1):
        path = Path(piece['path'])
        if path.stat().st_size != piece['size_bytes'] or sha256(path) != piece['sha256']:
            raise ValueError(f'Part bytes differ from their audited source receipt: {path}')
        if index%100 == 0 or index == len(pieces):
            print(json.dumps({'phase': 'combined_source_hashes', 'done': index, 'total': len(pieces)}), flush=True)
    ids = catalog_object_ids(ROOT, utc(manifest['start']), utc(manifest['end_exclusive']), manifest['max_age_hours'])
    cohort_hash = hashlib.sha256(','.join(map(str, ids)).encode()).hexdigest()
    if cohort_hash != manifest['object_ids_sha256']:
        raise ValueError('Current cohort differs from the pinned historical grid')
    connection = duckdb.connect();connection.execute('SET threads=2');connection.execute("SET memory_limit='1GB'")
    try:
        membership = verify_membership(connection, [piece['path'] for piece in pieces], ids)
    finally:
        connection.close()
    by_path = {item['path']: item for item in membership}
    if len(by_path) != len(pieces) or any(by_path[piece['path']]['rows'] != piece['rows'] for piece in pieces):
        raise ValueError('Combined physical row counts do not match the exact audited parts')
    counts = {key: sum(part[key] for part in prefix)+overlay['status_counts'][key]
              for key in ['successful', 'sgp4_errors', 'stale_or_missing']}
    result = {'status': 'validated_complete_refreshed_grid_union',
        'start_inclusive': manifest['start'], 'end_exclusive': manifest['end_exclusive'],
        'step_seconds': manifest['step_seconds'], 'samples_per_object': manifest['projected_samples_per_object'],
        'objects': len(ids), 'object_ids_sha256': cohort_hash, 'rows': sum(p['rows'] for p in pieces),
        'status_counts': counts, 'read_paths': [piece['path'] for piece in pieces],
        'reader_options': {'hive_partitioning': False}, 'part_count': len(pieces),
        'cohort_membership_checked_over_every_row': True, 'parts': pieces,
        'part_membership': membership,
        'source_receipts': [{'path': str(path), 'sha256': sha256(path)} for path in source_paths],
        'source_revisions': [manifest['source_revision'], overlay['source_revision']],
        'validated_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'scope': 'A contiguous, nonoverlapping uniform-cadence union: audited pinned prefix plus audited refreshed suffix. Every included part is rehashed and all row IDs are checked against the exact catalog cohort. Existing full grid-key/state/status checks and source propagation replays are inherited through byte-identical audited parts. Reconstructed SGP4 states, not precision orbit truth.'}
    output.mkdir(parents=True, exist_ok=True)
    (output/'manifest.json').write_text(json.dumps(result, indent=2)+'\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', type=Path, required=True)
    parser.add_argument('--refresh', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args();result = build(args.base,args.refresh,args.output)
    print(json.dumps({key:result[key] for key in ['status','rows','objects','part_count','status_counts']}, indent=2))


if __name__ == '__main__':
    main()
