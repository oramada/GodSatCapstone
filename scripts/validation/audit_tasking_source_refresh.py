"""Audit the final-date source refresh, cohort controls and descriptive tasking contrasts."""

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from godsat.orbits import ROOT,History
from scripts.validation.replay_catalog_tasking_sample import compare_response
from scripts.experiments.run_full_catalog_tasking import REGIMES,read_inputs,sha256,simulate_condition

METRICS=('custody_continuity','observable_custody','mean_slew_energy_proxy')
VARIANTS=('original_all','refreshed_all','original_common_ids','refreshed_common_ids',
          'original_common_ids_shared_validity','refreshed_common_ids_shared_validity')


def audit(folder,campaign):
    folder,campaign=Path(folder).resolve(),Path(campaign).resolve()
    s=json.loads((folder/'summary.json').read_text());d=s['design']
    if s['status']!='completed_descriptive_source_refresh_sensitivity':raise ValueError('Completed source check required')
    if sha256(campaign/'tasking_design.json')!=d['base_tasking_design_sha256']:raise ValueError('Primary design changed')
    if sha256(ROOT/'data/raw/tle_2026.parquet')!=d['frozen_2026_sha256']:raise ValueError('Frozen orbital source changed')
    if sha256(folder/'source_view/data/raw/tle_2026.parquet')!=d['fresh_2026_sha256']:raise ValueError('Fresh source bytes changed')
    for name,digest in d['code_sha256'].items():
        if sha256(ROOT/name)!=digest:raise ValueError('Source-sensitivity code changed')
    for name,digest in s['source_cell_sha256'].items():
        if sha256(ROOT/name)!=digest:raise ValueError('Canonical source cells changed')
    rows={}
    for row in s['responses']:
        key=(row['date'],row['orbit_regime_sensor_hosts'],row['source_variant'],row['requested_outage_rate'])
        if key in rows:raise ValueError('Duplicate source-sensitivity condition')
        for metric in METRICS:
            if not np.isfinite(row[metric]) or not 0<=row[metric]<=1:raise ValueError('Invalid response metric')
        rows[key]=row
    expected={(date,regime,variant,rate) for date in d['dates'] for regime in REGIMES
              for variant in VARIANTS for rate in (0.,.2)}
    if set(rows)!=expected or s['response_rows']!=96:raise ValueError('Incomplete response grid')
    def raw(row):return {key:value for key,value in row.items() if key!='source_variant'}
    baseline_count=0
    for date in d['dates']:
        for regime in REGIMES:
            saved=json.loads((campaign/'cells'/date[:10]/f'{regime}.json').read_text())
            for expected_row in saved['rows']:
                compare_response(expected_row,raw(rows[date,regime,'original_all',expected_row['requested_outage_rate']]))
                baseline_count+=1
            for variant in VARIANTS:
                for rate in (0.,.2):
                    if rows[date,regime,variant,rate]['sensor_host_ids']!=rows[date,regime,'original_all',0.]['sensor_host_ids']:
                        raise ValueError('Host identity changed across snapshots')
    contrasts={(r['date'],r['regime'],r['cohort'],r['outage_rate']):r for r in s['snapshot_contrasts']}
    interactions={(r['date'],r['regime'],r['cohort']):r for r in s['outage_interactions']}
    if len(contrasts)!=48 or len(s['snapshot_contrasts'])!=48 or len(interactions)!=24 or len(s['outage_interactions'])!=24:
        raise ValueError('Incomplete or duplicate contrast grid')
    for date in d['dates']:
        for regime in REGIMES:
            for cohort in ('all','common_ids','common_ids_shared_validity'):
                for metric in METRICS:
                    changes=[]
                    for rate in (0.,.2):
                        a=rows[date,regime,'original_'+cohort,rate];b=rows[date,regime,'refreshed_'+cohort,rate]
                        value=b[metric]-a[metric];changes.append(value)
                        np.testing.assert_allclose(contrasts[date,regime,cohort,rate]['refreshed_minus_original'][metric],value,rtol=0,atol=1e-12)
                        if cohort.endswith('shared_validity') and a['target_valid_step_count']!=b['target_valid_step_count']:
                            raise ValueError('Shared-validity target denominator differs')
                    np.testing.assert_allclose(interactions[date,regime,cohort]['change_in_20pct_minus_zero_effect'][metric],changes[1]-changes[0],rtol=0,atol=1e-12)
    original,fresh=History(ROOT,'all'),History(folder/'source_view','all')
    design=json.loads((campaign/'tasking_design.json').read_text());replayed=0
    try:
        for date in d['dates']:
            old=read_inputs(date,original,d['config']);new=read_inputs(date,fresh,d['config'])
            ids=np.asarray(sorted(set(map(int,old[0]))&set(map(int,new[0]))),dtype=np.int64)
            diagnostics=next(item for item in s['source_diagnostics'] if item['date']==date)
            digest=hashlib.sha256(np.asarray(ids,dtype='<i8').tobytes()).hexdigest()
            if len(ids)!=diagnostics['common_objects'] or digest!=diagnostics['common_ids_sha256']:
                raise ValueError('Independently rebuilt ID intersection differs')
            projected=[]
            for inputs in (old,new):
                lookup={int(oid):index for index,oid in enumerate(inputs[0])};indices=[lookup[int(oid)] for oid in ids]
                projected.append((ids,inputs[1][:,indices],inputs[2][:,indices],inputs[3][:,indices],inputs[4]))
            shared=projected[0][3]&projected[1][3]
            if int(shared[:-1].sum())!=diagnostics['shared_valid_slots_including_hosts']:
                raise ValueError('Independently rebuilt shared-validity mask differs')
            variants={'refreshed_all':new,
                'original_common_ids_shared_validity':(*projected[0][:3],shared,projected[0][4]),
                'refreshed_common_ids_shared_validity':(*projected[1][:3],shared,projected[1][4])}
            regime=REGIMES[0];hosts=rows[date,regime,'original_all',0.]['sensor_host_ids']
            for variant,inputs in variants.items():
                for rate in (0.,.2):
                    actual=simulate_condition(design['dates'].index(date),0,rate,*inputs[:4],inputs[4],hosts,d['config'],seed=d['seed'])
                    compare_response(raw(rows[date,regime,variant,rate]),actual);replayed+=1
            print(f'Source refresh identity/validity and sampled tasking replay passed: {date}',flush=True)
    finally:original.db.close();fresh.db.close()
    result={'status':'passed_source_controls_statistics_and_sampled_tasking_replay',
        'summary_sha256':sha256(folder/'summary.json'),'auditor_sha256':sha256(Path(__file__)),
        'response_rows_checked':96,'canonical_baseline_rows_checked':baseline_count,
        'snapshot_contrasts_checked':48,'outage_interactions_checked':24,
        'source_id_and_validity_rebuild_dates':2,'sampled_tasking_responses_replayed':replayed,
        'limits':'Complete condition/contrast/host/source bindings checked. Shared IDs and validity independently reconstructed on both dates. Numerical source replay samples only LEO across three variants and both conditions; it reuses the same tasking kernel and does not validate either snapshot against orbit truth.'}
    (folder/'independent_audit.json').write_text(json.dumps(result,indent=2)+'\n');return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--input',type=Path,required=True);parser.add_argument('--campaign',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(audit(args.input,args.campaign),indent=2))
