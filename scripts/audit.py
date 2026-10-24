import duckdb,json,pathlib
root=pathlib.Path(__file__).resolve().parents[1]
c=duckdb.connect();c.execute("SET TimeZone='UTC'")
c.execute("SET threads=2")
c.execute("SET memory_limit='1GB'")
files=str(root/'data/raw/tle_*.parquet')
report={'requested_start':'2022-10-09T00:00:00Z','requested_end_exclusive':'2026-10-10T00:00:00Z','files':[]}
for p in sorted((root/'data/raw').glob('tle_*.parquet')):
 row=c.execute('SELECT count(*),count(DISTINCT norad_id),min(epoch),max(epoch) FROM read_parquet(?)',[str(p)]).fetchone()
 report['files'].append(dict(file=p.name,records=row[0],objects=row[1],first_epoch=str(row[2]),last_epoch=str(row[3])))
c.read_parquet(files).filter("epoch >= TIMESTAMPTZ '2022-10-09' AND epoch < TIMESTAMPTZ '2026-10-10'").create_view("history")
c.read_csv(str(root/"data/raw/satcat.csv"), all_varchar=True).create_view("catalog")
# Current catalog status is a cohort definition, not evidence of historical operational status.
c.execute("CREATE VIEW current_payload_history AS SELECT h.* FROM history h JOIN catalog s ON h.norad_id=TRY_CAST(s.NORAD_CAT_ID AS BIGINT) WHERE s.OBJECT_TYPE='PAY' AND (s.DECAY_DATE IS NULL OR s.DECAY_DATE='') AND s.ORBIT_CENTER='EA'")
for name in ['history','current_payload_history']:
 row=c.execute(f'SELECT count(*),count(DISTINCT norad_id),min(epoch),max(epoch) FROM {name}').fetchone()
 report[name]=dict(records=row[0],objects=row[1],first_epoch=str(row[2]),last_epoch=str(row[3]))
 c.execute(f"COPY (SELECT norad_id,count(*) records,min(epoch) first_epoch,max(epoch) last_epoch FROM {name} GROUP BY norad_id ORDER BY norad_id) TO '{root}/data/{name}_coverage.csv' (HEADER)")
# Audit reconstructed propagation separately; successful element-epoch states
# are not continuous trajectories or independent accuracy validation.
state_manifest_path=root/'data/historical_state_vectors_all/manifest.json'
if state_manifest_path.exists():
 manifest=json.loads(state_manifest_path.read_text())
 rel=str(root/'data/historical_state_vectors_all/year=*/part-*.parquet')
 row=c.execute('''SELECT count(*),count(DISTINCT norad_id),min(epoch),max(epoch),
   count(*) FILTER (WHERE sgp4_error=0),count(*) FILTER (WHERE sgp4_error<>0)
   FROM read_parquet(?)''',[rel]).fetchone()
 yearly=c.execute('''SELECT year(epoch),count(*),count(DISTINCT norad_id),
   count(*) FILTER (WHERE sgp4_error=0),count(*) FILTER (WHERE sgp4_error<>0)
   FROM read_parquet(?) GROUP BY year(epoch) ORDER BY year(epoch)''',[rel]).fetchall()
 report['state_vector_export']={'manifest_status':manifest.get('status'),
   'records_written_manifest':manifest.get('records_written'),'parquet_records':row[0],
   'manifest_matches_parquet':manifest.get('records_written')==row[0],
   'objects_with_exported_states':row[1],'first_epoch':str(row[2]),'last_epoch':str(row[3]),
   'successful_sgp4_states':row[4],'failed_sgp4_states':row[5],
   'yearly_counts':[{'year':x[0],'state_rows':x[1],'object_ids':x[2],
     'successful':x[3],'failed':x[4]} for x in yearly],
   'frame':manifest.get('frame'),'model':manifest.get('model'),
   'limitations':manifest.get('limitations')}
 validation_path=root/'data/historical_state_vectors_all/validation.json'
 if validation_path.exists():
  validation=json.loads(validation_path.read_text())
  report['state_vector_export']['validation_snapshot']={'status':validation.get('status'),
    'records_validated':validation.get('records_validated'),
    'sample_size_per_year':validation.get('sample_size_per_year'),
    'validated_years':{k:{'complete':v.get('export_complete_for_year'),
      'source_count_matches':v.get('count_match'),
      'sgp4_error_counts':v.get('sgp4_error_counts'),
      'sample_max_position_delta_km':v.get('sample_max_abs_position_difference_km'),
      'sample_max_velocity_delta_km_s':v.get('sample_max_abs_velocity_difference_km_s')}
      for k,v in validation.get('years',{}).items()}}
(root/'data/state_vector_yearly_coverage.csv').write_text('calendar_year,state_rows,object_ids,successful,failed\n'+'\n'.join(','.join(map(str,x)) for x in yearly)+'\n')
(root/'data/coverage.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2))
