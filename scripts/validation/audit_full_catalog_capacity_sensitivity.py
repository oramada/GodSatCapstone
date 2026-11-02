"""Independently audit quarterly or monthly all-catalog capacity sensitivity."""
from __future__ import annotations

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))

import argparse, csv, hashlib, json, math, sys
from pathlib import Path
import numpy as np
from scipy.stats import t as student_t
ROOT=Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from godsat.dropout import monthly_dates, quarterly_dates
from scripts.experiments.run_full_catalog_tasking import REGIMES, OUTAGE_RATES
from scripts.experiments.run_full_catalog_capacity_sensitivity import CAPACITY_LEVELS
from godsat.scenario import cache_key

def sha256(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
 return h.hexdigest()

def audit(output:Path):
 summary=json.loads((output/'summary.json').read_text())
 dates=summary['dates']; date_grid=summary.get('date_grid','quarterly')
 if date_grid not in {'quarterly','monthly'}: raise ValueError('Unknown capacity date grid')
 registered=monthly_dates() if date_grid=='monthly' else quarterly_dates()
 expected_groups=summary.get('expected_date_regime_capacity_groups')
 if dates!=registered or summary.get('status')!='completed' or summary.get('simulator_version')!=2:
  raise ValueError('Incomplete or unsupported capacity-sensitivity design')
 if (not isinstance(expected_groups,int) or expected_groups < len(dates)*len(REGIMES)*2
     or summary.get('completed_date_regime_capacity_groups')!=expected_groups
     or len(summary.get('rows',[]))!=2*expected_groups):
  raise ValueError('Capacity response design is incomplete')
 if summary.get('raw_archive_manifest_sha256')!=sha256(ROOT/'data/raw/manifest.json'):
  raise ValueError('Raw archive manifest checksum changed')
 base=json.loads((ROOT/'outputs/all-orbits-paper-exact-active-hosts/config.json').read_text())
 base.update(duration_minutes=60,step_seconds=60,propagation_model='sgp4')
 if summary['config']!=base or summary['config_sha256']!=sha256(ROOT/'outputs/all-orbits-paper-exact-active-hosts/config.json'):
  raise ValueError('Capacity study config provenance mismatch')
 indexed={}; all_hosts={}; cells=0; scenario_count=0
 for date in dates:
  for regime in REGIMES:
   choices=[]
   for nominal in CAPACITY_LEVELS:
    p=output/'cells'/date[:10]/f'{regime}_hosts{nominal}.json'
    if p.is_file(): choices.append(nominal)
   # HEO sometimes cannot provide 24; the final available cohort is represented by a custom max.
   if not choices:
    extras=[p for p in (output/'cells'/date[:10]).glob(f'{regime}_hosts*.json')]
    choices=sorted(int(p.stem.rsplit('hosts',1)[1]) for p in extras)
   elif choices[-1] < 24:
    extras=[p for p in (output/'cells'/date[:10]).glob(f'{regime}_hosts*.json')]
    choices=sorted(int(p.stem.rsplit('hosts',1)[1]) for p in extras)
   if not choices or choices[0]!=6 or (len(choices)<2 or choices[1]!=12):
    raise ValueError(f'Unexpected capacity ladder at {date} {regime}: {choices}')
   maxcap=max(choices); candidates=list((output/'cells'/date[:10]).glob(f'{regime}_hosts{maxcap}.json'))
   if len(candidates)!=1: raise ValueError(f'Missing maximum-capacity cell {date} {regime}')
   cell=candidates[0]; saved=json.loads(cell.read_text()); hosts=saved['host_ids']
   if len(hosts)!=maxcap or len(set(hosts))!=maxcap: raise ValueError(f'Invalid max host list: {date} {regime}')
   meta_hash=summary['scenario_metadata_sha256'][date][regime]
   scenario_config={**base,'agents':maxcap}
   npz=ROOT/'data/scenarios'/f'{cache_key(date,scenario_config,regime)}.npz'
   meta=npz.with_suffix('.json')
   if not meta.is_file() or sha256(meta)!=meta_hash or json.loads(meta.read_text()).get('agents')!=hosts:
    raise ValueError(f'Scenario metadata/hash mismatch: {date} {regime}')
   if not npz.is_file() or sha256(npz)!=summary['scenario_cache_sha256'][date][regime]:
    raise ValueError(f'Scenario cache hash mismatch: {date} {regime}')
   scenario_count+=1
   for cap in choices:
    cp=output/'cells'/date[:10]/f'{regime}_hosts{cap}.json'
    if cap==maxcap: cp=cell
    if not cp.is_file(): raise ValueError(f'Missing capacity {cap}: {date} {regime}')
    item=json.loads(cp.read_text())
    if item.get('simulator_version')!=2 or item.get('source_signature')!=hashlib.sha256((summary['scenario_cache_sha256'][date][regime]+meta_hash+str(cap)).encode()).hexdigest():
     raise ValueError(f'Cell provenance mismatch {date} {regime} {cap}')
    cellhosts=item['host_ids']
    if cellhosts!=hosts[:cap]: raise ValueError(f'Host sets are not nested at {date} {regime} {cap}')
    for row in item['rows']:
     key=(row['date'],regime,cap,float(row['requested_outage_rate']))
     if key in indexed: raise ValueError(f'Duplicate row {key}')
     indexed[key]=row
     if row['date']!=date or row['step_count']!=60 or row['step_seconds']!=60: raise ValueError(f'Design mismatch {key}')
     if row['sensor_host_ids']!=cellhosts or row['sensor_count']!=cap: raise ValueError(f'Host mismatch {key}')
     if float(row['requested_outage_rate']) not in OUTAGE_RATES: raise ValueError(f'Unexpected outage rate {key}')
     if not 0<=row['detections']<=row['sensor_actions']<=60*cap: raise ValueError(f'Impossible action counts {key}')
     if row['target_valid_step_count'] != round(row['valid_target_fraction']*60*(row['catalog_objects_in_episode']-maxcap)):
      if not math.isclose(row['valid_target_fraction'],row['target_valid_step_count']/max(1,60*(row['catalog_objects_in_episode']-maxcap)),rel_tol=0,abs_tol=1e-12): raise ValueError(f'Target denominator varies or is inconsistent {key}')
     for metric in ('custody_continuity','observable_custody','valid_target_fraction','observed_dropout_rate','mean_slew_energy_proxy'):
      if not math.isfinite(float(row[metric])) or not 0<=float(row[metric])<=1: raise ValueError(f'Invalid metric {key} {metric}')
    cells+=1
 if cells!=expected_groups or len(indexed)!=2*expected_groups:
  raise ValueError(f'Expected {expected_groups} cells/{2*expected_groups} rows; found {cells}/{len(indexed)}')
 # All capacities at a date/regime must use the same target denominator.
 for date in dates:
  for regime in REGIMES:
   rows=[r for k,r in indexed.items() if k[0]==date and k[1]==regime]
   if len({r['catalog_objects_in_episode'] for r in rows})!=1 or len({r['target_valid_step_count'] for r in rows if float(r['requested_outage_rate'])==0})!=1:
    raise ValueError(f'Target cohort varies with capacity: {date} {regime}')
 csvrows=list(csv.DictReader((output/'responses.csv').open(newline='')))
 if len(csvrows)!=2*expected_groups: raise ValueError('CSV row count mismatch')
 csvkeys=set()
 for row in csvrows:
  key=(row['date'],row['orbit_regime_sensor_hosts'],int(row['sensor_count']),float(row['requested_outage_rate']))
  if key in csvkeys: raise ValueError(f'Duplicate CSV row {key}')
  csvkeys.add(key)
  target=indexed[(key[0],key[1],key[2],key[3])]
  for name,value in row.items():
   expected=target.get(name)
   if isinstance(expected,(int,float)):
    if not math.isclose(float(value),float(expected),rel_tol=0,abs_tol=1e-12): raise ValueError(f'CSV mismatch {key} {name}')
   elif str(expected)!=value: raise ValueError(f'CSV mismatch {key} {name}')
 if len(csvkeys)!=len(indexed): raise ValueError('CSV keys mismatch')
 effects=[]
 for regime in REGIMES:
  for cap in sorted({k[2] for k in indexed if k[1]==regime}):
   diffs=[]; paired=0
   for date in dates:
    zero=indexed.get((date,regime,cap,0.0)); loss=indexed.get((date,regime,cap,0.2))
    if zero and loss: diffs.append(loss['custody_continuity']-zero['custody_continuity']); paired+=1
   if paired != len(dates): continue
   x=np.asarray(diffs); h=float(student_t.ppf(.975,len(x)-1)*x.std(ddof=1)/np.sqrt(len(x))) if len(x)>1 else 0
   effects.append({'regime':regime,'hosts':cap,'n_dates':paired,'zero_loss_custody':float(np.mean([indexed[(d,regime,cap,0.0)]['custody_continuity'] for d in dates if (d,regime,cap,0.0) in indexed])),'burst_loss_custody':float(np.mean([indexed[(d,regime,cap,0.2)]['custody_continuity'] for d in dates if (d,regime,cap,0.2) in indexed])),'burst_minus_zero_mean':float(x.mean()),'ci95':[float(x.mean()-h),float(x.mean()+h)]})
 # Independently compare the reported effects.
 if len(effects)!=len(summary['capacity_effects']): raise ValueError('Effect table size mismatch')
 for actual,saved in zip(effects,summary['capacity_effects']):
  if not math.isclose(actual['burst_minus_zero_mean'],saved['burst_minus_zero_custody_mean'],rel_tol=0,abs_tol=1e-12) or not np.allclose(actual['ci95'],saved['burst_minus_zero_custody_ci95'],rtol=0,atol=1e-12):
   raise ValueError('Clustered capacity effect does not reproduce')
 result={'status':'passed_structural_and_statistical','scope':f"Checks complete {date_grid} date/regime/capacity cells, source scenario hashes, nested host sets, fixed target denominator, paired treatments, response invariants, CSV agreement, and independently recomputed date-clustered intervals. Does not rerun SGP4 episodes.",'date_grid':date_grid,'dates_checked':len(dates),'capacity_cells_checked':cells,'response_rows_checked':len(indexed),'scenario_cache_hashes_verified':scenario_count,'target_denominator_fixed_across_capacities':True,'clustered_effects_recomputed':len(effects)}
 (output/'independent_audit.json').write_text(json.dumps(result,indent=2)+'\n')
 return result

def main():
 p=argparse.ArgumentParser(); p.add_argument('--output',type=Path); p.add_argument('--date-grid',choices=('quarterly','monthly')); a=p.parse_args(); out=a.output if a.output else ROOT/f"outputs/full-catalog-capacity-sensitivity-{a.date_grid or 'quarterly'}-2022-2026"; out=out if out.is_absolute() else ROOT/out; result=audit(out)
 if a.date_grid and result['date_grid']!=a.date_grid: raise ValueError('Requested date grid differs from saved study')
 print(json.dumps(result,indent=2))
if __name__=='__main__': main()
