"""Reconstruct unavailable/corrupt committed Parquet parts from raw orbit elements."""
import argparse
import concurrent.futures
import datetime as dt
import hashlib
import json
import math
import pathlib
import time

import duckdb
import numpy as np
import pyarrow.parquet as pq

from export_state_vectors import ROOT, elements_for_year
from export_state_vectors import parallel_state_batch, utc, write_state_part


def unavailable_parts(output):
    """Return committed parts with no local data blocks.

    The current failure mode is File Provider eviction. Probing every valid
    cloud-managed Parquet footer is both slow and can itself fail to materialize
    an evicted file; the preceding full footer audit confirmed all unreadable
    committed parts have zero local blocks.
    """
    found=[]
    for path in sorted(pathlib.Path(output).glob('year=*/part-*.parquet')):
        if path.stat().st_blocks==0:
            found.append((path,'File Provider dataless placeholder (zero local blocks)'))
    return found


def atomic_json(path,value):
    path=pathlib.Path(path);temporary=path.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(value,indent=2)+'\n');temporary.replace(path)


def sha256(path):
    digest=hashlib.sha256()
    with pathlib.Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):
            digest.update(chunk)
    return digest.hexdigest()


def repair(output, batch_rows=100000, workers=4, limit=None):
    output=pathlib.Path(output).expanduser().resolve()
    manifest=json.loads((output/'manifest.json').read_text())
    if manifest.get('cohort')!='all':
        raise ValueError('Only the all-catalog export is supported')
    start,end=utc(manifest['start']),utc(manifest['end_exclusive'])
    if batch_rows!=manifest.get('batch_rows'):
        raise ValueError('Repair batch size must match the export manifest')
    initially_unavailable=unavailable_parts(output)
    targets={int(path.parent.name.split('=')[1]):{} for path,_ in initially_unavailable}
    for path,error in initially_unavailable:
        year=int(path.parent.name.split('=')[1]);index=int(path.stem.split('-')[1])
        targets[year][index]={'path':path,'error':error,'local_blocks':path.stat().st_blocks}
    audit_path=output/'repair_audit.json'
    previous=json.loads(audit_path.read_text()) if audit_path.exists() else {}
    if previous and (previous.get('source_revision')!=manifest.get('source_revision')
            or previous.get('batch_rows')!=batch_rows):
        raise ValueError('Existing repair audit belongs to another source or batch size')
    audit={'status':'running','started_utc':previous.get('started_utc',dt.datetime.now(dt.timezone.utc).isoformat()),
        'source_revision':manifest.get('source_revision'),'batch_rows':batch_rows,
        'unavailable_parts_detected':previous.get('unavailable_parts_detected',len(initially_unavailable)),
        'repaired_parts':previous.get('repaired_parts',[])}
    atomic_json(audit_path,audit)
    db=duckdb.connect();db.execute("SET TimeZone='UTC'");db.execute('SET threads=2')
    executor=concurrent.futures.ProcessPoolExecutor(max_workers=workers) if workers>1 else None
    repaired_count=0;began=time.perf_counter()
    for year in sorted(targets):
        year_targets=targets[year]
        year_manifest=manifest.get('years',{}).get(str(year),{})
        if not year_manifest:
            raise ValueError(f'No committed manifest row count for year {year}')
        total_rows=int(year_manifest['records'])
        expected_parts=math.ceil(total_rows/batch_rows)
        unexpected=sorted(i for i in year_targets if i>=expected_parts)
        if unexpected:
            raise ValueError(f'Unavailable parts beyond committed rows in {year}: {unexpected}')
        lower=max(start,dt.datetime(year,1,1,tzinfo=dt.timezone.utc))
        upper=min(end,dt.datetime(year+1,1,1,tzinfo=dt.timezone.utc))
        elements_for_year(db,'all',year,lower,upper,0)
        year_rows=0;year_repaired=0
        for index in range(expected_parts):
            rows=db.fetchmany(batch_rows)
            expected_rows=min(batch_rows,total_rows-index*batch_rows)
            if len(rows)!=expected_rows:
                raise RuntimeError(f'{year} part {index}: source returned {len(rows)} rows, expected {expected_rows}')
            year_rows+=len(rows)
            if index not in year_targets:
                continue
            info=year_targets[index];target=info['path']
            ids,epochs,errors,states=parallel_state_batch(rows,workers,executor)
            temporary=target.with_suffix('.parquet.repairing')
            try:
                write_state_part(temporary,rows,ids,errors,states)
                parquet=pq.ParquetFile(temporary)
                if parquet.metadata.num_rows!=expected_rows:
                    raise RuntimeError(f'{target}: rebuilt Parquet row count mismatch')
                rebuilt=parquet.read()
                if not np.array_equal(rebuilt['norad_id'].to_numpy(),ids):
                    raise RuntimeError(f'{target}: rebuilt object ids differ from source batch')
                if rebuilt['epoch'].to_pylist()!=[row[1] for row in rows]:
                    raise RuntimeError(f'{target}: rebuilt epochs differ from source batch')
                if not np.array_equal(rebuilt['sgp4_error'].to_numpy(),errors):
                    raise RuntimeError(f'{target}: rebuilt SGP4 codes differ')
                values=np.column_stack([rebuilt[name].to_numpy() for name in
                    ('x_teme_km','y_teme_km','z_teme_km','vx_teme_km_s','vy_teme_km_s','vz_teme_km_s')])
                if not np.array_equal(values,states,equal_nan=True):
                    raise RuntimeError(f'{target}: rebuilt state components differ')
                file_hash=sha256(temporary);temporary.replace(target)
                metadata=pq.read_metadata(target)
                if metadata.num_rows!=expected_rows:
                    raise RuntimeError(f'{target}: final replacement is unreadable or incomplete')
                if target.stat().st_blocks==0:
                    raise RuntimeError(f'{target}: file provider immediately evicted the repaired part')
            finally:
                if temporary.exists():temporary.unlink()
            record={'path':str(target.relative_to(ROOT)),'part_index':index,
                'source_row_offset':index*batch_rows,'rows':expected_rows,
                'sha256':file_hash,'source_error_counts':{
                    str(int(code)):int(count) for code,count in zip(*np.unique(errors,return_counts=True))},
                'former_local_blocks':int(info['local_blocks']),
                'former_error':info['error']}
            audit['repaired_parts'].append(record);repaired_count+=1;year_repaired+=1
            atomic_json(audit_path,audit)
            print(f'{year}: repaired part {index:05d} ({expected_rows:,} rows)',flush=True)
            if limit is not None and repaired_count>=limit:
                db.close()
                if executor is not None:executor.shutdown()
                audit['status']='partial';audit['completed_utc']=dt.datetime.now(dt.timezone.utc).isoformat()
                atomic_json(audit_path,audit);return audit
        if year_rows!=total_rows:
            raise RuntimeError(f'{year}: source yielded {year_rows} rows, manifest expects {total_rows}')
        print(f'{year}: scanned {year_rows:,} source rows; repaired {year_repaired} parts',flush=True)
    db.close()
    if executor is not None:executor.shutdown()
    remaining=unavailable_parts(output)
    audit['remaining_unavailable_parts']=[{'path':str(p.relative_to(ROOT)),'error':e} for p,e in remaining]
    audit['status']='completed' if not remaining else 'incomplete'
    audit['elapsed_seconds']=round(time.perf_counter()-began,3)
    audit['completed_utc']=dt.datetime.now(dt.timezone.utc).isoformat()
    atomic_json(audit_path,audit)
    if remaining:raise RuntimeError(f'{len(remaining)} unavailable parts remain')
    return audit


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',default=str(ROOT/'data/historical_state_vectors_all'))
    parser.add_argument('--batch-rows',type=int,default=100000)
    parser.add_argument('--workers',type=int,default=4)
    parser.add_argument('--limit',type=int,help='repair at most this many parts, for validation')
    args=parser.parse_args()
    print(json.dumps(repair(args.output,args.batch_rows,args.workers,args.limit),indent=2))


if __name__=='__main__':main()
