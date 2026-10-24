"""Compare sampled historical AWP predictions with ILRS CPF orbit products."""
from __future__ import annotations
import argparse, csv, datetime as dt, hashlib, json, math
from collections import defaultdict
from pathlib import Path
import sys
import numpy as np
from astropy import units as u
from astropy.coordinates import CartesianRepresentation, GCRS, ITRS
from astropy.time import Time
from astropy.utils import iers
from scipy.stats import t as student_t
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from godsat.orbits import AWP_EARTH_CONSTANTS, awp_propagate, julian, satellite, teme_to_gcrs
from scripts.compare_sgp4_with_ilrs_cpf import load_history, teme_to_itrf

TARGETS={'lageos1':8820,'lageos2':22195,'lares':38077,'starlette':7646}
DATA_ROOT=ROOT/'data/ground_sensor'
EOP=DATA_ROOT/'ilrs_lageos1_npt/ancillary/finals2000A.all'
CADENCE_HOURS=72

def sha256(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
 return h.hexdigest()

def gcrs_to_itrf(times,positions_km,eop_table):
 obstime=Time(times)
 state=GCRS(CartesianRepresentation(np.asarray(positions_km,float).T*u.km),obstime=obstime)
 with iers.earth_orientation_table.set(eop_table):
  fixed=state.transform_to(ITRS(obstime=obstime))
 return fixed.cartesian.xyz.to_value(u.km).T

def load_comparison_sample(data_dir,cadence_hours=CADENCE_HOURS):
 source=data_dir/'orbit_model_comparison.csv';rows=[];seen=set()
 step=int(cadence_hours*3600)
 with source.open(newline='') as stream:
  for row in csv.DictReader(stream):
   when=dt.datetime.fromisoformat(row['observation_time_utc'])
   if when.tzinfo is None:when=when.replace(tzinfo=dt.timezone.utc)
   else:when=when.astimezone(dt.timezone.utc)
   slot=int(when.timestamp()//step)
   if slot in seen:continue
   seen.add(slot)
   row['_when']=when
   row['_element_epoch']=dt.datetime.fromisoformat(row['historical_element_epoch_utc'])
   row['_age']=float(row['historical_element_age_hours'])
   row['_cpf']=np.asarray([float(row[f'cpf_itrf_{axis}_km']) for axis in 'xyz'])
   row['_sgp4']=np.asarray([float(row[f'sgp4_itrf_{axis}_km']) for axis in 'xyz'])
   rows.append(row)
 rows.sort(key=lambda r:r['_when'])
 return rows,source

def evaluate_target(slug,sat_id,eop_table,cadence_hours=CADENCE_HOURS,drag=False,area_mass_m2_kg=0.01):
 data=DATA_ROOT/f'ilrs_{slug}_npt';epochs,records,dup,conflicts=load_history(sat_id)
 record_by_epoch={epoch.isoformat():record for epoch,record in zip(epochs,records)}
 candidates,comparison_path=load_comparison_sample(data,cadence_hours)
 grouped=defaultdict(list);missing_epoch=0
 for row in candidates:
  key=row['historical_element_epoch_utc']
  tle=record_by_epoch.get(key)
  if tle is None:
   # Preserve a clear diagnostic if source timestamps differ only in UTC spelling.
   try: tle=record_by_epoch.get(dt.datetime.fromisoformat(key).astimezone(dt.timezone.utc).isoformat())
   except ValueError: pass
  if tle is None:missing_epoch+=1;continue
  grouped[tle['epoch']].append((row,tle))
 output=[];processed_groups=0
 for epoch,items in grouped.items():
  tle=items[0][1];sat=satellite(tle);error,pos,vel=sat.sgp4(*julian(epoch))
  if error or not np.isfinite(np.r_[pos,vel]).all():continue
  initial=teme_to_gcrs(np.r_[pos,vel],epoch)
  offsets=np.asarray([(row['_when']-epoch).total_seconds() for row,_ in items],float)
  eval_offsets=np.unique(np.r_[0.,offsets])
  awp=awp_propagate(initial,float(eval_offsets[-1]),eval_offsets,j2=True,drag=drag,
   area_mass_m2_kg=area_mass_m2_kg) if eval_offsets[-1]>0 else initial[None,:]
  gcrs_positions=awp[np.searchsorted(eval_offsets,offsets),:3]
  obs_times=[row['_when'] for row,_ in items]
  awp_itrf=gcrs_to_itrf(obs_times,gcrs_positions,eop_table)
  model_id='awp_j2_drag' if drag else 'awp_j2'
  difference_key='awp_j2_drag_minus_sgp4_separation_km' if drag else 'awp_minus_sgp4_separation_km'
  for (row,_),ap in zip(items,awp_itrf):
   cpf=row['_cpf'];sgp=row['_sgp4'];a=float(np.linalg.norm(ap-cpf));s=float(np.linalg.norm(sgp-cpf))
   output.append({'observation_time_utc':row['_when'].isoformat(),'date':row['_when'].date().isoformat(),
    'norad_id':sat_id,'station_name':row['station_name'],'station_sod':row['station_sod'],
    'historical_element_epoch_utc':epoch.isoformat(),'historical_element_age_hours':row['_age'],
    'cpf_file':row['cpf_file'],f'{model_id}_position_separation_km':a,'sgp4_position_separation_km':s,
    difference_key:a-s,
    f'{model_id}_itrf_x_km':float(ap[0]),f'{model_id}_itrf_y_km':float(ap[1]),f'{model_id}_itrf_z_km':float(ap[2]),
    'sgp4_itrf_x_km':float(sgp[0]),'sgp4_itrf_y_km':float(sgp[1]),'sgp4_itrf_z_km':float(sgp[2]),
    'cpf_itrf_x_km':float(cpf[0]),'cpf_itrf_y_km':float(cpf[1]),'cpf_itrf_z_km':float(cpf[2])})
  processed_groups+=1
  if processed_groups%100==0:print(f'  {slug}: propagated {processed_groups}/{len(grouped)} source-element arcs',flush=True)
 output.sort(key=lambda r:r['observation_time_utc'])
 if not output:raise ValueError(f'No successful AWP arcs for {slug}')
 return output,{'status':'completed','target':slug,'norad_id':sat_id,'comparison_rows_available':sum(1 for _ in comparison_path.open())-1,
  'sampled_rows':len(output),'source_element_arcs':processed_groups,'missing_historical_element_keys':missing_epoch,
  'sampling_cadence_hours':cadence_hours,'source_duplicate_epoch_rows':dup,
  'source_epochs_with_conflicting_orbital_elements':conflicts}

def summarize(rows,model_id='awp_j2'):
 dates=sorted({r['date'] for r in rows})
 difference_key='awp_j2_drag_minus_sgp4_separation_km' if model_id=='awp_j2_drag' else 'awp_minus_sgp4_separation_km'
 by_date=np.asarray([np.mean([r[difference_key] for r in rows if r['date']==d]) for d in dates])
 half=float(student_t.ppf(.975,len(by_date)-1)*by_date.std(ddof=1)/np.sqrt(len(by_date))) if len(by_date)>1 else None
 def metrics(key):
  vals=np.asarray([r[key] for r in rows]);return {'median_km':float(np.median(vals)),'p95_km':float(np.quantile(vals,.95)),'p99_km':float(np.quantile(vals,.99)),'mean_km':float(np.mean(vals))}
 return {'sample_count':len(rows),'date_clusters':len(dates),f'{model_id}_vs_cpf':metrics(f'{model_id}_position_separation_km'),
  'sgp4_vs_cpf':metrics('sgp4_position_separation_km'),'awp_minus_sgp4_separation_mean_km':float(by_date.mean()),
  'awp_minus_sgp4_separation_ci95_date_clustered_km':[float(by_date.mean()-half),float(by_date.mean()+half)] if half is not None else None,
  'date_cluster_mean_difference_km':{d:float(v) for d,v in zip(dates,by_date)}}

def run(output,drag=False,area_mass_m2_kg=0.01):
 model_id='awp_j2_drag' if drag else 'awp_j2'
 output.mkdir(parents=True,exist_ok=True);eop_table=iers.IERS_A.open(str(EOP));results=[]
 for slug,norad in TARGETS.items():
  print(f'Validating {model_id} against ILRS CPF for {slug}',flush=True)
  rows,design=evaluate_target(slug,norad,eop_table,drag=drag,area_mass_m2_kg=area_mass_m2_kg)
  data=DATA_ROOT/f'ilrs_{slug}_npt';csv_path=output/f'{slug}_{model_id}_vs_cpf.csv'
  with csv_path.open('w',newline='') as f:
   w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
  summary={'design':design,'metrics':summarize(rows,model_id),'output_csv':str(csv_path.relative_to(ROOT)),
   'model_id':model_id,'earth_constants':{'model':'IERS Conventions 2010',
    'values':AWP_EARTH_CONSTANTS,'units':{'mu':'km^3/s^2','radius':'km','J2':'dimensionless'},
    'source':'https://iers-conventions.obspm.fr/content/tn36.pdf'},
   'drag_assumptions':({'area_mass_m2_kg':area_mass_m2_kg,'drag_coefficient':2.2,
    'density_model':'piecewise quiet-atmosphere table with log-linear interpolation'} if drag else None),
   'output_csv_sha256':sha256(csv_path),'source_sha256':{'orbit_model_comparison.csv':sha256(data/'orbit_model_comparison.csv'),
    'cpf_manifest.json':sha256(data/'cpf_manifest.json'),'global_tle_manifest.json':sha256(ROOT/'data/raw/manifest.json'),'eop':sha256(EOP)}}
  results.append(summary)
  output.joinpath(f'{slug}_summary.json').write_text(json.dumps(summary,indent=2)+'\n')
  print(json.dumps({'target':slug,'n':design['sampled_rows'],
   'awp_median_km':summary['metrics'][f'{model_id}_vs_cpf']['median_km'],
   'sgp4_median_km':summary['metrics']['sgp4_vs_cpf']['median_km'],
   'awp_minus_sgp4_ci95_km':summary['metrics']['awp_minus_sgp4_separation_ci95_date_clustered_km']},indent=2),flush=True)
 model_description='AWP two-body plus J2 and simplified exponential-atmosphere drag' if drag else 'AWP two-body plus J2 without drag'
 manifest={'status':'completed','model_id':model_id,'scope':'Four years of ILRS CPF comparisons, deterministically sampled at one normal point per nonoverlapping 72-hour UTC bin for four retroreflector targets.',
  'model':f'Archived GP/TLE state at its epoch transformed TEME-to-GCRS, propagated with the vendored AWP Spacecraft Earth {model_description}, then transformed to ITRF and compared with operational CPF position at the observation epoch.',
  'drag_assumptions':({'area_mass_m2_kg':area_mass_m2_kg,'drag_coefficient':2.2,
   'density_model':'piecewise quiet-atmosphere table with log-linear interpolation'} if drag else None),
  'interpretation':'CPF is an operational reference product, not independent orbit truth. This is a model-to-operational-product consistency comparison and does not calibrate sensor dropout.',
  'earth_constants':{'model':'IERS Conventions 2010','values':AWP_EARTH_CONSTANTS,
   'units':{'mu':'km^3/s^2','radius':'km','J2':'dimensionless'},
   'source':'https://iers-conventions.obspm.fr/content/tn36.pdf'},
  'cadence_hours':CADENCE_HOURS,'targets':results,'limits':['The one-per-72-hour sample is not an all-observation validation.','The underlying SGP4/CPF comparison excludes unresolved CPF references, non-nominal CRD rows, stale elements, and invalid CPF coverage.','TLE histories are GP representations; SGP4 state at TLE epoch initializes AWP.','CPF is an operational reference product, not independent orbit truth.','The drag model uses nominal area-to-mass and drag coefficient with a simplified atmosphere; it omits solar/geomagnetic weather, maneuvers, covariance, and assimilation.']}
 output.joinpath('summary.json').write_text(json.dumps(manifest,indent=2)+'\n');return manifest

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path);p.add_argument('--drag',action='store_true');p.add_argument('--area-mass-m2-kg',type=float,default=0.01);a=p.parse_args()
 if a.area_mass_m2_kg<=0:p.error('--area-mass-m2-kg must be positive')
 default_name='awp-ilrs-cpf-drag-validation-2022-2026' if a.drag else 'awp-ilrs-cpf-validation-2022-2026'
 out=a.output or ROOT/'outputs'/default_name;out=out if out.is_absolute() else ROOT/out
 result=run(out,drag=a.drag,area_mass_m2_kg=a.area_mass_m2_kg);print(json.dumps({'status':result['status'],'targets':len(result['targets']),'model_id':result['model_id'],'output':str(out)},indent=2))
if __name__=='__main__':main()
