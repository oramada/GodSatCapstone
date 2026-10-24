"""Independently audit sampled AWP versus ILRS CPF comparison artifacts."""
from __future__ import annotations
import argparse,csv,json,math,sys
from pathlib import Path
import numpy as np
from scipy.stats import t as student_t
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from scripts.validate_awp_against_ilrs import TARGETS,EOP,DATA_ROOT,CADENCE_HOURS,sha256,load_comparison_sample
from godsat.orbits import AWP_EARTH_CONSTANTS

def close(a,b,tol=1e-9):
 if not math.isclose(float(a),float(b),rel_tol=0,abs_tol=tol):raise ValueError(f'Values differ: {a} != {b}')

def metrics(rows,key):
 x=np.asarray([float(r[key]) for r in rows]);return {'median_km':float(np.median(x)),'p95_km':float(np.quantile(x,.95)),'p99_km':float(np.quantile(x,.99)),'mean_km':float(np.mean(x))}

def audit(output:Path):
 summary=json.loads((output/'summary.json').read_text())
 if summary.get('status')!='completed' or summary.get('cadence_hours')!=CADENCE_HOURS or len(summary.get('targets',[]))!=4:
  raise ValueError('AWP/ILRS validation design is incomplete or unexpected')
 model_id=summary.get('model_id','awp_j2')
 if model_id not in {'awp_j2','awp_j2_drag'}:raise ValueError(f'Unsupported model id: {model_id}')
 earth_constants=summary.get('earth_constants')
 if earth_constants is not None and earth_constants.get('values')!=AWP_EARTH_CONSTANTS:
  raise ValueError('Saved AWP Earth force constants differ from the current model')
 difference_key='awp_j2_drag_minus_sgp4_separation_km' if model_id=='awp_j2_drag' else 'awp_minus_sgp4_separation_km'
 if model_id=='awp_j2_drag':
  assumptions=summary.get('drag_assumptions') or {}
  if assumptions.get('area_mass_m2_kg',0)<=0 or assumptions.get('drag_coefficient',0)<=0:
   raise ValueError('Drag validation is missing positive ballistic assumptions')
 checked=0; target_results=[]
 by_slug={item['design']['target']:item for item in summary['targets']}
 if set(by_slug)!=set(TARGETS):raise ValueError('Target inventory mismatch')
 for slug,norad in TARGETS.items():
  item=by_slug[slug];data=DATA_ROOT/f'ilrs_{slug}_npt';source=data/'orbit_model_comparison.csv';csv_path=output/f'{slug}_{model_id}_vs_cpf.csv'
  expected_hashes={'orbit_model_comparison.csv':sha256(source),'cpf_manifest.json':sha256(data/'cpf_manifest.json'),
   'global_tle_manifest.json':sha256(ROOT/'data/raw/manifest.json'),'eop':sha256(EOP)}
  if item.get('source_sha256')!=expected_hashes:raise ValueError(f'Source checksum mismatch for {slug}')
  if item.get('output_csv_sha256')!=sha256(csv_path):raise ValueError(f'Output checksum mismatch for {slug}')
  expected,_=load_comparison_sample(data,CADENCE_HOURS)
  with csv_path.open(newline='') as f:rows=list(csv.DictReader(f))
  if len(rows)!=len(expected) or len(rows)!=item['design']['sampled_rows']:raise ValueError(f'Sample size mismatch for {slug}')
  for actual,source_row in zip(rows,expected):
   if actual['observation_time_utc']!=source_row['_when'].isoformat() or actual['station_name']!=source_row['station_name'] or actual['cpf_file']!=source_row['cpf_file']:
    raise ValueError(f'Sampled source row mismatch for {slug}: {actual["observation_time_utc"]}')
   if int(actual['norad_id'])!=norad:raise ValueError('NORAD mismatch')
   if float(actual['historical_element_age_hours'])>72:raise ValueError('A stale source element entered the sample')
   awp=np.asarray([float(actual[f'{model_id}_itrf_{axis}_km']) for axis in 'xyz'])
   sgp=np.asarray([float(actual[f'sgp4_itrf_{axis}_km']) for axis in 'xyz'])
   cpf=np.asarray([float(actual[f'cpf_itrf_{axis}_km']) for axis in 'xyz'])
   close(np.linalg.norm(awp-cpf),actual[f'{model_id}_position_separation_km'])
   close(np.linalg.norm(sgp-cpf),actual['sgp4_position_separation_km'])
   close(float(actual[f'{model_id}_position_separation_km'])-float(actual['sgp4_position_separation_km']),actual[difference_key])
  date_values=sorted({r['date'] for r in rows})
  by_date=np.asarray([np.mean([float(r[difference_key]) for r in rows if r['date']==day]) for day in date_values])
  half=float(student_t.ppf(.975,len(by_date)-1)*by_date.std(ddof=1)/np.sqrt(len(by_date))) if len(by_date)>1 else None
  ci=[float(by_date.mean()-half),float(by_date.mean()+half)] if half is not None else None
  actual_metrics=item['metrics']
  if len(by_date)!=actual_metrics['date_clusters']:raise ValueError(f'Date cluster count mismatch {slug}')
  for k,n in [(f'{model_id}_position_separation_km',f'{model_id}_vs_cpf'),('sgp4_position_separation_km','sgp4_vs_cpf')]:
   recomputed=metrics(rows,k)
   for name,value in recomputed.items():close(value,actual_metrics[n][name])
  close(by_date.mean(),actual_metrics['awp_minus_sgp4_separation_mean_km'])
  if not np.allclose(ci,actual_metrics['awp_minus_sgp4_separation_ci95_date_clustered_km'],rtol=0,atol=1e-9):raise ValueError(f'Clustered interval mismatch {slug}')
  target_result={'target':slug,'rows_checked':len(rows),'date_clusters':len(by_date),'awp_minus_sgp4_ci95_km':ci}
  if earth_constants is not None:
   legacy_root=ROOT/'outputs/awp-ilrs-cpf-validation-2022-2026'
   legacy_summary=json.loads((legacy_root/'summary.json').read_text())
   legacy_item=next(x for x in legacy_summary['targets'] if x['design']['target']==slug)
   legacy_path=legacy_root/f'{slug}_awp_j2_vs_cpf.csv'
   if sha256(legacy_path)!=legacy_item['output_csv_sha256']:
    raise ValueError(f'Legacy AWP output checksum mismatch for {slug}')
   with legacy_path.open(newline='') as f:legacy_rows=list(csv.DictReader(f))
   if [r['observation_time_utc'] for r in legacy_rows]!=[r['observation_time_utc'] for r in rows]:
    raise ValueError(f'Corrected/legacy AWP sample membership mismatch for {slug}')
   displacement=[];legacy_residual=[];corrected_residual=[]
   for corrected,legacy in zip(rows,legacy_rows):
    delta=np.asarray([float(corrected[f'{model_id}_itrf_{axis}_km'])-
                      float(legacy[f'awp_j2_itrf_{axis}_km']) for axis in 'xyz'])
    displacement.append(float(np.linalg.norm(delta)))
    legacy_residual.append(float(legacy['awp_j2_position_separation_km']))
    corrected_residual.append(float(corrected[f'{model_id}_position_separation_km']))
   displacement=np.asarray(displacement);legacy_residual=np.asarray(legacy_residual)
   corrected_residual=np.asarray(corrected_residual)
   target_result['corrected_vs_legacy_awp']={
    'legacy_median_cpf_separation_km':float(np.median(legacy_residual)),
    'corrected_median_cpf_separation_km':float(np.median(corrected_residual)),
    'median_cpf_separation_change_km':float(np.median(corrected_residual)-np.median(legacy_residual)),
    'trajectory_displacement_km':{'median':float(np.median(displacement)),
      'p95':float(np.quantile(displacement,.95)),'maximum':float(np.max(displacement))}}
  if model_id=='awp_j2_drag':
   baseline_root=ROOT/'outputs/awp-ilrs-cpf-validation-2022-2026'
   baseline_summary=json.loads((baseline_root/'summary.json').read_text())
   baseline_item=next(x for x in baseline_summary['targets'] if x['design']['target']==slug)
   baseline_path=baseline_root/f'{slug}_awp_j2_vs_cpf.csv'
   if sha256(baseline_path)!=baseline_item['output_csv_sha256']:
    raise ValueError(f'Baseline AWP-J2 output checksum mismatch for {slug}')
   with baseline_path.open(newline='') as f:baseline_rows=list(csv.DictReader(f))
   if [r['observation_time_utc'] for r in baseline_rows]!=[r['observation_time_utc'] for r in rows]:
    raise ValueError(f'Drag/J2 sample membership mismatch for {slug}')
   delta=[];baseline_error=[];drag_error=[]
   for drag_row,j2_row in zip(rows,baseline_rows):
    vector=np.asarray([float(drag_row[f'{model_id}_itrf_{axis}_km'])-
                       float(j2_row[f'awp_j2_itrf_{axis}_km']) for axis in 'xyz'])
    delta.append(float(np.linalg.norm(vector)))
    baseline_error.append(float(j2_row['awp_j2_position_separation_km']))
    drag_error.append(float(drag_row[f'{model_id}_position_separation_km']))
   displacement=np.asarray(delta);baseline_error=np.asarray(baseline_error);drag_error=np.asarray(drag_error)
   target_result['drag_minus_j2_position_displacement_km']={
    'median':float(np.median(displacement)),'p95':float(np.quantile(displacement,.95)),
    'maximum':float(np.max(displacement))}
   target_result['drag_minus_j2_cpf_error_quantile_change_km']={
    'median':float(np.median(drag_error)-np.median(baseline_error)),
    'p95':float(np.quantile(drag_error,.95)-np.quantile(baseline_error,.95))}
  target_results.append(target_result)
  checked+=len(rows)
 result={'status':'passed_structural_and_statistical','model_id':model_id,
  'earth_constants':earth_constants,
  'scope':'Verifies source/output hashes, deterministic sample membership against saved SGP4/CPF comparison rows, vector-separation calculations, row counts, and independent date-cluster reaggregation. For drag, it also verifies identical row membership with the saved J2 baseline and recomputes drag-to-J2 trajectory displacement. It does not rerun AWP numerical integrations.',
  'targets_checked':len(target_results),'response_rows_checked':checked,'target_results':target_results}
 (output/'independent_audit.json').write_text(json.dumps(result,indent=2)+'\n');return result

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,default=ROOT/'outputs/awp-ilrs-cpf-validation-2022-2026');a=p.parse_args();out=a.output if a.output.is_absolute() else ROOT/a.output;print(json.dumps(audit(out),indent=2))
if __name__=='__main__':main()
