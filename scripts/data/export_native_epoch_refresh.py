"""Export and independently replay a nonoverlapping final-date orbital-history supplement."""
from __future__ import annotations

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))


import argparse
import csv
import hashlib
import json
from pathlib import Path

import duckdb
import numpy as np
import pyarrow.parquet as pq

from godsat.orbits import ROOT, julian, satellite, utc
from scripts.data.export_state_vectors import state_batch, write_state_part


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(source: Path, output: Path, start: str, end: str):
    source, output = source.resolve(), output.resolve()
    start, end = utc(start), utc(end)
    if start >= end:
        raise ValueError('Require start before exclusive end')
    receipt_path = source.with_suffix('.manifest.json')
    receipt = json.loads(receipt_path.read_text())
    if (receipt.get('sha256') != digest(source) or receipt.get('size_bytes') != source.stat().st_size
            or not receipt.get('source_revision')):
        raise ValueError('Snapshot checksum, size or immutable revision is unverified')
    con = duckdb.connect(); con.execute("SET TimeZone='UTC'")
    old_max = con.execute('select max(epoch) from read_parquet(?)',
                          [str(ROOT/'data/raw/tle_*.parquet')]).fetchone()[0]
    if utc(old_max) >= start:
        raise ValueError('Supplement interval overlaps the pinned native-epoch archive')
    fields = ['norad_id', 'epoch', 'inclination', 'raan', 'eccentricity', 'arg_perigee',
              'mean_anomaly', 'mean_motion', 'mean_motion_dot', 'bstar']
    query = 'select '+','.join(fields)+' from read_parquet(?) where epoch>=? and epoch<? order by '+','.join(fields)
    rows = con.execute(query, [str(source), start, end]).fetchall(); con.close()
    if not rows:
        raise ValueError('No source records in requested supplement interval')
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f'Refusing to overwrite a nonempty supplement: {output}')
    output.mkdir(parents=True, exist_ok=True)
    ids, _, errors, states = state_batch(rows)
    part = output/'native_epoch_states.parquet'
    write_state_part(part, rows, ids, errors, states)
    stored = pq.read_table(part).to_pydict()
    maximum_position_error = maximum_velocity_error = 0.
    # Replay every supplement row through the independent project element parser.
    for index, row in enumerate(rows):
        record = dict(zip(fields, row))
        error, position, velocity = satellite(record).sgp4(*julian(record['epoch']))
        if int(stored['sgp4_error'][index]) != error or stored['norad_id'][index] != row[0] or stored['epoch'][index] != row[1]:
            raise ValueError(f'Source key or SGP4 status mismatch at row {index}')
        value = np.array([stored[f'{axis}_teme_km'][index] for axis in 'xyz']+
                         [stored[f'v{axis}_teme_km_s'][index] for axis in 'xyz'])
        if error == 0:
            reference = np.r_[position, velocity]
            if not np.isfinite(value).all() or not np.allclose(value, reference, atol=1e-9, rtol=0):
                raise ValueError(f'Independent state replay mismatch at row {index}')
            maximum_position_error = max(maximum_position_error, float(np.max(np.abs(value[:3]-reference[:3]))))
            maximum_velocity_error = max(maximum_velocity_error, float(np.max(np.abs(value[3:]-reference[3:]))))
        elif np.isfinite(value).any():
            raise ValueError(f'Failed propagation retained a finite state at row {index}')
    with (ROOT/'data/state_vector_object_coverage.csv').open(newline='') as stream:
        prior_ids = {int(row['norad_id']) for row in csv.DictReader(stream) if int(row['historical_element_rows']) > 0}
    current_ids = set(map(int, ids))
    result = {'status': 'all_supplement_source_rows_independently_replayed',
              'start_inclusive': start.isoformat(), 'end_exclusive': end.isoformat(),
              'pinned_source_latest_epoch': utc(old_max).isoformat(), 'nonoverlap_verified': True,
              'source_path': str(source), 'source_revision': receipt['source_revision'],
              'source_sha256': receipt['sha256'], 'source_receipt_sha256': digest(receipt_path),
              'source_rows': len(rows), 'objects': len(current_ids),
              'objects_added_to_pinned_window': sorted(current_ids-prior_ids),
              'combined_window_object_count': len(prior_ids|current_ids),
              'successful': int((errors == 0).sum()), 'flagged_sgp4_failures': int((errors != 0).sum()),
              'independent_state_replays': len(rows), 'maximum_position_difference_km': maximum_position_error,
              'maximum_velocity_difference_km_s': maximum_velocity_error,
              'part': str(part), 'part_sha256': digest(part),
              'scope': 'One reconstructed SGP4 TEME state per refreshed source element record, including duplicate epochs; not measured precision orbit truth. Retained separately from the pinned study input.'}
    (output/'manifest.json').write_text(json.dumps(result, indent=2)+'\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--start', default='2026-10-09T00:00:00Z')
    parser.add_argument('--end', default='2026-10-10T00:00:00Z')
    args = parser.parse_args()
    print(json.dumps(run(args.source, args.output, args.start, args.end), indent=2))


if __name__ == '__main__':
    main()
