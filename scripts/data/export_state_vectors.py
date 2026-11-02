"""Reconstruct SGP4 TEME state vectors at every archived element epoch.

Writes a resumable Parquet dataset in bounded chunks. One state vector is
generated for each source orbital-element record; this is a native-epoch
historical state series, not a uniform-cadence continuous ephemeris.
"""

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))

import argparse
import datetime as dt
import hashlib
import json
import math
import concurrent.futures
import pathlib
import time

import duckdb
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from sgp4.api import Satrec, WGS72, jday

ROOT=pathlib.Path(__file__).resolve().parents[2]
DEFAULT_START='2022-10-09T00:00:00Z'
DEFAULT_END='2026-10-10T00:00:00Z'
PARQUET_WRITER=f'PyArrow {pa.__version__} Parquet ZSTD level 3'

def utc(value):
    parsed=dt.datetime.fromisoformat(value.replace('Z','+00:00'))
    if parsed.tzinfo is None: raise ValueError('Use a timezone-qualified date, such as 2022-10-09T00:00:00Z')
    return parsed.astimezone(dt.timezone.utc)

def source_revision():
    path=ROOT/'data/raw/source-manifest.json'
    return json.loads(path.read_text()).get('revision') if path.exists() else None

def signature(cohort,start,end,batch_rows,revision):
    payload=json.dumps({'cohort':cohort,'start':start.isoformat(),'end':end.isoformat(),
                        'batch_rows':batch_rows,'source_revision':revision},sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()

def write_manifest(path,manifest):
    tmp=path.with_suffix('.json.tmp');tmp.write_text(json.dumps(manifest,indent=2)+'\n');tmp.replace(path)

def elements_for_year(db,cohort,year,start,end,offset=0):
    if cohort=='all':
        source=ROOT/f'data/raw/tle_{year}.parquet'
    else:
        source=ROOT/'data/current_payload_orbit_history.parquet'
    if not source.exists(): raise FileNotFoundError(source)
    db.execute('''SELECT norad_id,epoch,inclination,raan,eccentricity,arg_perigee,
        mean_anomaly,mean_motion,mean_motion_dot,bstar FROM read_parquet(?)
        WHERE epoch >= ? AND epoch < ? OFFSET ?''',[str(source),start,end,int(offset)])
    return db

def state_batch(rows):
    count=len(rows)
    ids=np.empty(count,dtype=np.int32);epochs=np.empty(count,dtype='U40')
    errors=np.full(count,-99,dtype=np.int16);states=np.full((count,6),np.nan,dtype=np.float64)
    for i,row in enumerate(rows):
        oid,epoch,inc,raan,e,argp,ma,mn,mndot,bstar=row
        ids[i]=oid;epochs[i]=epoch.isoformat()
        try:
            jd,fr=jday(epoch.year,epoch.month,epoch.day,epoch.hour,epoch.minute,
                       epoch.second+epoch.microsecond/1e6)
            sat=Satrec()
            sat.sgp4init(WGS72,'i',int(oid),jd+fr-2433281.5,float(bstar),
                float(mndot)*2*math.pi/1440**2,0.,float(e),math.radians(argp),
                math.radians(inc),math.radians(ma),float(mn)*2*math.pi/1440,
                math.radians(raan))
            err,pos,vel=sat.sgp4(jd,fr);errors[i]=int(err)
            if err==0 and np.isfinite(pos+vel).all(): states[i]=[*pos,*vel]
        except (ValueError,OverflowError,ZeroDivisionError):
            errors[i]=-99
    return ids,epochs,errors,states

def parallel_state_batch(rows,workers,executor=None):
    """Distribute independent element-to-state conversions over worker processes."""
    if workers<=1:return state_batch(rows)
    workers=min(int(workers),len(rows))
    chunk_size=math.ceil(len(rows)/workers)
    chunks=[rows[i:i+chunk_size] for i in range(0,len(rows),chunk_size)]
    if executor is None:
        with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as pool:
            parts=list(pool.map(state_batch,chunks))
    else:
        parts=list(executor.map(state_batch,chunks))
    return tuple(np.concatenate([part[i] for part in parts],axis=0) for i in range(4))

def write_state_part(path,rows,ids,errors,states):
    """Write one source batch directly as typed columnar Parquet arrays.

    DuckDB's Python-list ``unnest`` writer repeatedly converted each large
    array-valued parameter and dominated end-to-end export time. PyArrow keeps
    the already-computed numeric columns columnar and preserves the same
    schema and compression format.
    """
    table=pa.table({
        'norad_id':pa.array(ids,type=pa.int32()),
        'epoch':pa.array([row[1] for row in rows],type=pa.timestamp('us',tz='UTC')),
        'sgp4_error':pa.array(errors,type=pa.int16()),
        'x_teme_km':pa.array(states[:,0],type=pa.float64()),
        'y_teme_km':pa.array(states[:,1],type=pa.float64()),
        'z_teme_km':pa.array(states[:,2],type=pa.float64()),
        'vx_teme_km_s':pa.array(states[:,3],type=pa.float64()),
        'vy_teme_km_s':pa.array(states[:,4],type=pa.float64()),
        'vz_teme_km_s':pa.array(states[:,5],type=pa.float64()),
    })
    pq.write_table(table,path,compression='zstd',compression_level=3)

def export(cohort,start,end,output,batch_rows,limit=None,workers=1):
    output=pathlib.Path(output).expanduser().resolve();output.mkdir(parents=True,exist_ok=True)
    start_dt,end_dt=utc(start),utc(end)
    if start_dt>=end_dt: raise ValueError('start must be before end')
    if batch_rows<1000: raise ValueError('batch_rows must be at least 1000')
    if workers<1: raise ValueError('workers must be positive')
    revision=source_revision();sig=signature(cohort,start_dt,end_dt,batch_rows,revision)
    manifest_path=output/'manifest.json'
    if manifest_path.exists():
        manifest=json.loads(manifest_path.read_text())
        if manifest.get('signature')!=sig: raise ValueError('Output folder belongs to another export configuration')
        if manifest.get('status')=='completed' and limit is None:
            print(f"Already complete: {manifest['records_written']:,} states at {output}");return manifest
    else:
        existing=list(output.rglob('*.parquet'))
        if existing: raise ValueError('Parquet files exist without a manifest; use a new output folder')
        manifest={'status':'running','signature':sig,'cohort':cohort,'start':start_dt.isoformat(),
            'end_exclusive':end_dt.isoformat(),'frame':'TEME','units':{'position':'km','velocity':'km/s'},
            'model':'reconstructed SGP4 WGS-72 from archived mean elements at each source epoch',
            'source_revision':revision,'source_files':[],'records_written':0,'error_counts':{},
            'batch_rows':batch_rows,'years':{},'parquet_writer_history':[],
            'created_utc':dt.datetime.now(dt.timezone.utc).isoformat(),
            'limitations':['One state vector per orbital-element epoch; epochs are irregular and do not form a uniform-cadence ephemeris.',
                'The mirror omits original TLE lines and some precision; vectors are reconstructed, not lossless original propagations.',
                'Catalog history includes payloads, debris, and rocket bodies; public catalog coverage is incomplete.']}
        write_manifest(manifest_path,manifest)
    db=duckdb.connect();db.execute("SET TimeZone='UTC'");db.execute('SET threads=2');db.execute("SET memory_limit='1GB'")
    source_db=duckdb.connect();source_db.execute("SET TimeZone='UTC'");source_db.execute('SET threads=2');source_db.execute("SET memory_limit='1GB'")
    executor=concurrent.futures.ProcessPoolExecutor(max_workers=workers) if workers>1 else None
    years=range(start_dt.year,end_dt.year+1);total_this_run=0;began=time.perf_counter()
    total_committed=0
    for part in output.rglob('part-*.parquet'):
        total_committed+=int(db.execute('SELECT count(*) FROM read_parquet(?)',[str(part)]).fetchone()[0])
    manifest['records_written']=total_committed
    writer_history=manifest.setdefault('parquet_writer_history',[])
    if total_committed and not writer_history:
        writer_history.append({'writer':'DuckDB 1.4.5 Parquet ZSTD',
            'through_record_count':total_committed,
            'year_parts':{str(y):len(list((output/f'year={y}').glob('part-*.parquet'))) for y in years}})
    if not any(item.get('writer')==PARQUET_WRITER for item in writer_history):
        writer_history.append({'writer':PARQUET_WRITER,
            'starts_after_record_count':total_committed})
    write_manifest(manifest_path,manifest)
    for year in years:
        if cohort=='all': source=ROOT/f'data/raw/tle_{year}.parquet'
        else: source=ROOT/'data/current_payload_orbit_history.parquet'
        if not source.exists(): continue
        lower=max(start_dt,dt.datetime(year,1,1,tzinfo=dt.timezone.utc))
        upper=min(end_dt,dt.datetime(year+1,1,1,tzinfo=dt.timezone.utc))
        year_dir=output/f'year={year}';year_dir.mkdir(exist_ok=True)
        existing=sorted(year_dir.glob('part-*.parquet'))
        committed=sum(int(db.execute('SELECT count(*) FROM read_parquet(?)',[str(p)]).fetchone()[0]) for p in existing)
        year_errors={}
        for part in existing:
            for code,count in db.execute('SELECT sgp4_error,count(*) FROM read_parquet(?) GROUP BY 1',[str(part)]).fetchall():
                year_errors[str(int(code))]=year_errors.get(str(int(code)),0)+int(count)
        next_part=len(existing)
        if cohort=='current_payload' and year in manifest['years'] and manifest['years'][str(year)].get('complete'):
            continue
        # OFFSET advances inside DuckDB, avoiding conversion and recomputation of
        # already committed Python rows when a large export resumes.
        elements_for_year(source_db,cohort,year,lower,upper,committed)
        year_written=committed;year_started=time.perf_counter();stopped_by_limit=False
        while True:
            rows=source_db.fetchmany(batch_rows)
            if not rows: break
            if limit is not None:
                remaining=limit-total_this_run
                if remaining<=0: stopped_by_limit=True;break
                rows=rows[:remaining]
            ids,epochs,errors,states=parallel_state_batch(rows,workers,executor)
            part=year_dir/f'part-{next_part:05d}.parquet';tmp=part.with_suffix('.parquet.tmp')
            write_state_part(tmp,rows,ids,errors,states)
            tmp.replace(part);next_part+=1;year_written+=len(rows);total_this_run+=len(rows)
            total_committed+=len(rows);manifest['records_written']=total_committed
            for code,n in zip(*np.unique(errors,return_counts=True)):
                year_errors[str(int(code))]=year_errors.get(str(int(code)),0)+int(n)
            manifest['years'][str(year)]={'records':year_written,'complete':False,'parts':next_part,'error_counts':year_errors}
            write_manifest(manifest_path,manifest)
            if total_this_run%500000<len(rows):
                rate=total_this_run/max(time.perf_counter()-began,1e-9)
                print(f'{year}: {year_written:,} states; {rate:,.0f} states/s',flush=True)
            if limit is not None and total_this_run>=limit:
                stopped_by_limit=True;break
        complete=not stopped_by_limit
        manifest['years'][str(year)]={'records':year_written,'complete':complete,'parts':next_part,'error_counts':year_errors,
            'seconds':round(time.perf_counter()-year_started,3)}
        write_manifest(manifest_path,manifest)
        manifest['source_files']=sorted(set(manifest['source_files']+[source.name]))
        write_manifest(manifest_path,manifest)
        if limit is not None and total_this_run>=limit: break
    manifest['elapsed_seconds']=round(time.perf_counter()-began,3)
    manifest['status']='completed' if limit is None and all(manifest['years'].get(str(y),{}).get('complete') for y in years if (ROOT/f'data/raw/tle_{y}.parquet').exists()) else 'partial'
    manifest['completed_utc']=dt.datetime.now(dt.timezone.utc).isoformat() if manifest['status']=='completed' else None
    write_manifest(manifest_path,manifest);source_db.close();db.close()
    if executor is not None:executor.shutdown()
    print(json.dumps({'status':manifest['status'],'records_written':manifest['records_written'],
        'elapsed_seconds':manifest['elapsed_seconds'],'output':str(output)},indent=2))
    return manifest

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cohort',choices=['all','current_payload'],default='all')
    p.add_argument('--start',default=DEFAULT_START);p.add_argument('--end',default=DEFAULT_END)
    p.add_argument('--batch-rows',type=int,default=100000)
    p.add_argument('--output',default=str(ROOT/'data/historical_state_vectors_all'))
    p.add_argument('--workers',type=int,default=1,help='parallel CPU workers for SGP4 conversion; does not change output values')
    p.add_argument('--limit',type=int,help='write a bounded validation sample, leaving status partial')
    a=p.parse_args()
    export(a.cohort,a.start,a.end,a.output,a.batch_rows,a.limit,a.workers)

if __name__=='__main__':main()
