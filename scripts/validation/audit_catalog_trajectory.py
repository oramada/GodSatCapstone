"""Independently validate a bulk catalog ephemeris export and source samples."""

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))

import argparse
import collections
import datetime as dt
import hashlib
import json
import math
import pathlib

import duckdb

from godsat.orbits import ROOT, History, orbit_regime, satellite, julian, utc
from godsat.catalog_trajectory import (catalog_object_ids, manifest_signature,
    verify_committed_parts)
from godsat.trajectory import source_revision


STATE_COLUMNS = ('x_teme_km','y_teme_km','z_teme_km',
                 'vx_teme_km_s','vy_teme_km_s','vz_teme_km_s')


def source_check(root, part, rows, max_age_hours):
    start,end=utc(part['start_inclusive']),utc(part['end_exclusive'])
    ids=sorted({int(row['norad_id']) for row in rows})
    history=History(root,cohort='all',window=(start,end),
                    max_age_hours=max_age_hours)
    try:
        elements=history.records(start,end,max_age_hours,ids=ids)
    finally:
        history.db.close()
    grouped={oid:[] for oid in ids}
    for item in elements:
        grouped[int(item['norad_id'])].append(item)
    max_position_delta=0.0
    max_velocity_delta=0.0
    for output in rows:
        oid=int(output['norad_id']); instant=utc(output['time_utc'])
        candidates=[item for item in grouped[oid] if utc(item['epoch'])<=instant]
        element=candidates[-1] if candidates else None
        age=(instant-utc(element['epoch'])).total_seconds()/3600 if element else None
        if element is None or age>max_age_hours:
            if int(output['sgp4_error'])!=-1 or any(output[c] is not None for c in STATE_COLUMNS):
                raise AssertionError(f'NORAD {oid} {instant}: stale source status is not represented explicitly')
            continue
        expected_error,position,velocity=satellite(element).sgp4(*julian(instant))
        if int(output['sgp4_error'])!=int(expected_error):
            raise AssertionError(f'NORAD {oid} {instant}: exported SGP4 code {output["sgp4_error"]}, source gives {expected_error}')
        if output['element_epoch']!=utc(element['epoch']).isoformat():
            raise AssertionError(f'NORAD {oid} {instant}: selected source epoch differs')
        if output['orbit_regime']!=orbit_regime(element):
            raise AssertionError(f'NORAD {oid} {instant}: orbit regime differs from selected element')
        if expected_error==0:
            expected=[*position,*velocity]
            actual=[float(output[c]) for c in STATE_COLUMNS]
            if not all(math.isfinite(value) for value in actual):
                raise AssertionError(f'NORAD {oid} {instant}: successful exported state is non-finite')
            max_position_delta=max(max_position_delta,max(abs(a-b) for a,b in zip(actual[:3],expected[:3])))
            max_velocity_delta=max(max_velocity_delta,max(abs(a-b) for a,b in zip(actual[3:],expected[3:])))
            if max_position_delta>1e-9 or max_velocity_delta>1e-12:
                raise AssertionError(f'NORAD {oid} {instant}: SGP4 state differs from source')
        elif any(output[c] is not None for c in STATE_COLUMNS):
            raise AssertionError(f'NORAD {oid} {instant}: failed SGP4 state must be null')
    return {'sample_rows':len(rows),'max_abs_position_delta_km':max_position_delta,
            'max_abs_velocity_delta_km_s':max_velocity_delta}


def audit(output, root=ROOT, samples_per_status=10, files_per_batch=7,
          progress=None, sample_parts=0):
    auditor_source_hash=hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest()
    root,output=pathlib.Path(root).resolve(),pathlib.Path(output).resolve()
    manifest=json.loads((output/'manifest.json').read_text())
    if manifest.get('status')!='completed':
        raise RuntimeError(f'Catalog ephemeris export is not complete: {manifest.get("status")}')
    if manifest.get('source_revision')!=source_revision(root):
        raise RuntimeError('Export source revision differs from the current raw-data manifest')
    ids=catalog_object_ids(root,manifest['start'],manifest['end_exclusive'],
                           manifest['max_age_hours'])
    signature,_=manifest_signature(manifest['start'],manifest['end_exclusive'],
        manifest['step_seconds'],manifest['max_age_hours'],manifest['source_revision'],ids)
    if signature!=manifest.get('signature') or len(ids)!=manifest.get('object_count'):
        raise RuntimeError('Export signature does not match the current complete catalog cohort')
    manifest_parts=manifest.get('parts',[])
    if sample_parts<0:
        raise ValueError('sample_parts must be nonnegative')
    if sample_parts>len(manifest_parts):
        raise ValueError(f'sample_parts exceeds available parts ({len(manifest_parts)})')
    if sample_parts:
        if sample_parts==1:
            sampled_indices=[len(manifest_parts)//2]
        else:
            sampled_indices=sorted({round(i*(len(manifest_parts)-1)/(sample_parts-1))
                                    for i in range(sample_parts)})
        parts=[manifest_parts[index] for index in sampled_indices]
    else:
        parts=manifest_parts
    if progress is None:
        verify_committed_parts(output,parts)
    else:
        verify_committed_parts(output,parts,progress=lambda done,total:
            progress('checksums',done,total))
    db=duckdb.connect()
    db.execute("SET TimeZone='UTC'");db.execute('SET threads=2');db.execute("SET memory_limit='1GB'")
    part_reports=[]
    samples_by_month=collections.defaultdict(list)
    parts_by_file={str(output/part['file']):part for part in parts}
    aggregate_columns=('rows_n','objects_n','times_n','first_time','last_time',
        'times_list','successful_n','errors_n','stale_n','invalid_success_n',
        'flagged_state_n','unique_pairs_n')
    try:
        # Weekly batches keep distinct-pair state bounded while cutting the
        # original four Parquet scans per daily part down to one scan per week.
        for offset in range(0,len(parts),files_per_batch):
            batch=parts[offset:offset+files_per_batch]
            paths=[str(output/part['file']) for part in batch]
            query='''WITH input AS MATERIALIZED (
                SELECT filename, norad_id, time_utc, element_epoch,
                    element_age_hours, orbit_regime, sgp4_error,
                    x_teme_km,y_teme_km,z_teme_km,
                    vx_teme_km_s,vy_teme_km_s,vz_teme_km_s
                FROM read_parquet(?, filename=true)
                ), stats AS (
                SELECT filename, count(*) AS rows_n,
                    count(DISTINCT norad_id) AS objects_n,
                    count(DISTINCT time_utc) AS times_n,
                    min(time_utc) AS first_time,
                    max(time_utc) AS last_time,
                    list(DISTINCT time_utc) AS times_list,
                    sum(CASE WHEN sgp4_error=0 THEN 1 ELSE 0 END) AS successful_n,
                    sum(CASE WHEN sgp4_error NOT IN (0,-1) THEN 1 ELSE 0 END) AS errors_n,
                    sum(CASE WHEN sgp4_error=-1 THEN 1 ELSE 0 END) AS stale_n,
                    sum(CASE WHEN sgp4_error=0 AND
                        (x_teme_km IS NULL OR y_teme_km IS NULL OR z_teme_km IS NULL OR
                         vx_teme_km_s IS NULL OR vy_teme_km_s IS NULL OR vz_teme_km_s IS NULL OR
                         NOT isfinite(x_teme_km) OR NOT isfinite(y_teme_km) OR NOT isfinite(z_teme_km) OR
                         NOT isfinite(vx_teme_km_s) OR NOT isfinite(vy_teme_km_s) OR NOT isfinite(vz_teme_km_s))
                        THEN 1 ELSE 0 END) AS invalid_success_n,
                    sum(CASE WHEN sgp4_error<>0 AND
                        (x_teme_km IS NOT NULL OR y_teme_km IS NOT NULL OR z_teme_km IS NOT NULL OR
                         vx_teme_km_s IS NOT NULL OR vy_teme_km_s IS NOT NULL OR vz_teme_km_s IS NOT NULL)
                        THEN 1 ELSE 0 END) AS flagged_state_n,
                    count(DISTINCT (norad_id,time_utc)) AS unique_pairs_n
                FROM input GROUP BY filename
                ), samples AS (
                SELECT *,
                    row_number() OVER (PARTITION BY filename,
                        CASE WHEN sgp4_error=0 THEN 'success'
                             WHEN sgp4_error=-1 THEN 'stale' ELSE 'error' END
                        ORDER BY hash(norad_id,time_utc)) AS sample_rank
                FROM input QUALIFY sample_rank <= ?
                ) SELECT samples.*, stats.* EXCLUDE(filename)
                FROM samples JOIN stats USING(filename)'''
            sampled=db.execute(query,[paths,max(1,samples_per_status)]).fetchall()
            columns=[item[0] for item in db.description]
            for values in sampled:
                record=dict(zip(columns,values))
                filename=record.pop('filename')
                part=parts_by_file.get(filename)
                if part is None:
                    raise AssertionError(f'Parquet reader returned an unknown part: {filename}')
                if not part.get('_audit_seen'):
                    part['_audit_seen']=True
                    actual_times=sorted(str(value) for value in record['times_list'])
                    expected_samples=int(part['samples_per_object'])
                    expected_times=[(utc(part['start_inclusive'])+
                        dt.timedelta(seconds=i*int(manifest['step_seconds']))).isoformat()
                        for i in range(expected_samples)]
                    stats={key:record[key] for key in aggregate_columns}
                    if (stats['rows_n']!=part['rows']
                            or stats['objects_n']!=part['objects']
                            or stats['times_n']!=expected_samples
                            or actual_times!=expected_times
                            or str(stats['first_time'])!=expected_times[0]
                            or str(stats['last_time'])!=expected_times[-1]
                            or stats['successful_n']!=part['successful']
                            or stats['errors_n']!=part['sgp4_errors']
                            or stats['stale_n']!=part['stale_or_missing']
                            or stats['invalid_success_n'] or stats['flagged_state_n']
                            or stats['unique_pairs_n']!=stats['rows_n']
                            or stats['rows_n']!=stats['objects_n']*stats['times_n']):
                        raise AssertionError(f'Part integrity/grid/status check failed: {part["file"]}')
                    part_reports.append({'manifest_index':int(part['index']),
                        'file':part['file'],'rows':int(stats['rows_n']),
                        'objects':int(stats['objects_n']),'sample_times':int(stats['times_n']),
                        'successful':int(stats['successful_n']),
                        'sgp4_errors':int(stats['errors_n']),
                        'stale_or_missing':int(stats['stale_n']),
                        'unique_object_time_pairs':int(stats['unique_pairs_n'])})
                if samples_per_status>0:
                    month=utc(record['time_utc']).strftime('%Y-%m')
                    samples_by_month[month].append({key:record[key] for key in (
                        'norad_id','time_utc','element_epoch','element_age_hours',
                        'orbit_regime','sgp4_error',*STATE_COLUMNS)})
            if progress is not None:
                progress('parquet',min(offset+len(batch),len(parts)),len(parts))
        if len(part_reports)!=len(parts):
            raise AssertionError(f'Only {len(part_reports)} of {len(parts)} parts were audited')
    finally:
        db.close()
    for part in parts:
        part.pop('_audit_seen',None)

    # Reproduce source elements by month rather than opening the same five-year
    # Parquet archives once for every daily part.
    source_batches=[]
    monthly_samples=sorted(samples_by_month.items())
    for month_index,(month,rows) in enumerate(monthly_samples,1):
        year,month_number=map(int,month.split('-'))
        start=dt.datetime(year,month_number,1,tzinfo=dt.timezone.utc)
        if month_number==12:
            end=dt.datetime(year+1,1,1,tzinfo=dt.timezone.utc)
        else:
            end=dt.datetime(year,month_number+1,1,tzinfo=dt.timezone.utc)
        result=source_check(root,{'start_inclusive':start.isoformat(),
            'end_exclusive':end.isoformat()},rows,manifest['max_age_hours'])
        source_batches.append({'month':month,'source_validation':result})
        if progress is not None:
            progress('source samples',month_index,len(monthly_samples))

    totals={key:sum(int(part.get(key,0)) for part in parts)
        for key in ('rows','successful','sgp4_errors','stale_or_missing')}
    if not sample_parts and (totals['rows']!=manifest.get('projected_rows')
            or totals['rows']!=manifest.get('completed_rows')
            or len(parts)!=manifest.get('parts_written')
            or totals['successful']!=manifest.get('successful')
            or totals['sgp4_errors']!=manifest.get('sgp4_errors')
            or totals['stale_or_missing']!=manifest.get('stale_or_missing')):
        raise AssertionError('Part totals do not reconcile with the completed manifest')
    if hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest()!=auditor_source_hash:
        raise RuntimeError('Auditor source changed during execution; rerun with stable code')
    report={'status':'validated_sampled' if sample_parts else 'validated_complete',
        'auditor_source_sha256':auditor_source_hash,
        'parquet_aggregation_method':'Grouped per-file aggregates over every row, joined with stratified propagation samples',
        'verification_scope':'stratified manifest part sample' if sample_parts else 'complete export',
        'signature':manifest['signature'],
        'source_revision':manifest['source_revision'],'parts_validated':len(parts),
        'manifest_parts':len(manifest_parts),
        'sampled_part_indices':[part['index'] for part in parts] if sample_parts else None,
        'objects':manifest['object_count'],'rows':totals['rows'],
        'successful':totals['successful'],'sgp4_errors':totals['sgp4_errors'],
        'stale_or_missing':totals['stale_or_missing'],
        'source_samples_per_status_per_part':samples_per_status,
        'source_validation_batches':source_batches,
        'parts':part_reports,'validated_utc':dt.datetime.now(dt.timezone.utc).isoformat(),
        'criteria':[f"Every {'selected ' if sample_parts else ''}Parquet part matches its recorded SHA-256, size, and row count.",
            'Each object has exactly one row at each expected cadence time in each part.',
            'Successful states are finite; failed or stale states have null vectors.',
            'Deterministic samples of success, failure, and stale statuses reproduce from raw source elements.']}
    report_path=output/('validation-sampled.json' if sample_parts else 'validation.json')
    report_path.write_text(json.dumps(report,indent=2)+'\n')
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True)
    parser.add_argument('--root',default=str(ROOT))
    parser.add_argument('--samples-per-status',type=int,default=10)
    parser.add_argument('--files-per-batch',type=int,default=7,
        help='Parquet parts scanned together; lower this if memory is constrained')
    parser.add_argument('--sample-parts',type=int,default=0,
        help='Audit this many deterministically spaced manifest parts instead of the full export; writes validation-sampled.json')
    args=parser.parse_args()
    if args.samples_per_status<0:
        parser.error('--samples-per-status must be nonnegative')
    if args.files_per_batch<1:
        parser.error('--files-per-batch must be positive')
    if args.sample_parts<0:
        parser.error('--sample-parts must be nonnegative')
    def progress(phase,done,total):
        interval=50 if phase=='checksums' else 100 if phase=='parquet' else 1
        if done!=total and done%interval:
            return
        print(json.dumps({'phase':phase,'completed':done,'total':total}),flush=True)
    report=audit(args.output,args.root,args.samples_per_status,args.files_per_batch,
                 progress=progress,sample_parts=args.sample_parts)
    print(json.dumps({key:report[key] for key in ('status','parts_validated','objects',
        'rows','successful','sgp4_errors','stale_or_missing')},indent=2))


if __name__=='__main__':
    main()
