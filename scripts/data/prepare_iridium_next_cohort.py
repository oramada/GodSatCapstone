"""Extract historical elements for the committed, pinned NEXT membership."""
from __future__ import annotations

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))

import datetime as dt
import argparse
import hashlib
import json
from pathlib import Path

import duckdb
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[2]


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()


def run():
    membership_path = ROOT/'configs/iridium-next-membership.json'
    manifest = json.loads(membership_path.read_text())
    policy = json.loads((ROOT/'configs/active-study-scope.json').read_text())
    if sha(membership_path) != policy['iridium_next_membership_sha256']:
        raise ValueError('Committed NEXT membership differs from the active policy pin')
    members = manifest['members']
    ids = [r['norad_id'] for r in members]
    if len(set(ids)) != len(ids) or not ids or any(not r['name'].startswith('IRIDIUM ') for r in members):
        raise ValueError('Invalid dedicated Iridium NEXT source')
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    source = ROOT/'data/current_payload_orbit_history.parquet'
    output = ROOT/'data/iridium_next_orbit_history.parquet'
    with duckdb.connect() as db:
        db.execute("SET threads=2")
        db.execute("SET memory_limit='1GB'")
        table = db.execute('SELECT * FROM read_parquet(?) WHERE norad_id IN (SELECT unnest(?)) ORDER BY norad_id, epoch', [str(source), ids]).fetch_arrow_table()
    actual = set(map(int, table.column('norad_id').to_pylist()))
    if actual != set(ids):
        raise ValueError(f'NEXT history membership mismatch: missing={sorted(set(ids)-actual)}, unknown={sorted(actual-set(ids))}')
    pq.write_table(table, output, compression='zstd')
    receipt = {'status': 'exact_iridium_next_membership_extracted', 'generated_utc': now,
               'constellation_objects': len(ids), 'records': table.num_rows,
               'membership_sha256': sha(membership_path), 'source_sha256': sha(source),
               'output_sha256': sha(output), 'source': str(source.relative_to(ROOT)),
               'output': str(output.relative_to(ROOT)), 'only_allowlisted_ids': True,
               'ground_systems_included': False, 'meo_included': False,
               'limitations': manifest['scope']}
    output.with_suffix('.parquet.manifest.json').write_text(json.dumps(receipt, indent=2)+'\n')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    argparse.ArgumentParser(description=__doc__).parse_args()
    run()
