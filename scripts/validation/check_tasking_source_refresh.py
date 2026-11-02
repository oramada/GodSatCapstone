"""Paired final-two-date tasking sensitivity to the pinned orbital-source refresh."""

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


def project(inputs,chosen):
    ids,states,ages,valid,times=inputs
    ids,chosen=np.asarray(ids),np.asarray(chosen,dtype=np.int64)
    if np.any(np.diff(ids)<=0) or np.any(np.diff(chosen)<=0):raise ValueError('Cohort IDs must be unique and sorted')
    indices=np.searchsorted(ids,chosen)
    if np.any(indices>=len(ids)) or not np.array_equal(ids[indices],chosen):
        raise ValueError('Matched cohort contains an absent object ID')
    return chosen,states[:,indices],ages[:,indices],valid[:,indices],times


def id_hash(ids):
    return hashlib.sha256(np.asarray(ids,dtype='<i8').tobytes()).hexdigest()


def run(campaign,output,snapshot):
    campaign,output,snapshot=map(lambda p:Path(p).resolve(),(campaign,output,snapshot))
    source_document=json.loads(snapshot.with_suffix('.manifest.json').read_text())
    if source_document['status']!='downloaded_and_checksum_verified' or sha256(snapshot)!=source_document['sha256']:
        raise ValueError('Fresh source bytes do not match the pinned download receipt')
    design_path=campaign/'tasking_design.json';design=json.loads(design_path.read_text())
    if design['target_cohort']!='all' or design['outage_rates']!=[0.,.2] or design['dropout_design_sha256'] is not None:
        raise ValueError('Original fixed-rate all-catalogue design required')
    if sha256(ROOT/'data/raw/manifest.json')!=design['archive_sha256']:
        raise ValueError('Frozen archive manifest changed')
    output.mkdir(parents=True,exist_ok=True)
    if (output/'summary.json').exists():raise ValueError('Choose a new output for a fresh execution')
    alias=output/'source_view/data/raw/tle_2026.parquet';alias.parent.mkdir(parents=True,exist_ok=True)
    if alias.exists() and alias.resolve()!=snapshot:raise ValueError('Source view points to different data')
    if not alias.exists():alias.symlink_to(snapshot)
    source_root=output/'source_view'
    code={name:sha256(ROOT/name) for name in ('godsat/orbits.py','godsat/scenario.py',
        'scripts/experiments/run_full_catalog_tasking.py','scripts/validation/check_tasking_source_refresh.py')}
    document={'status':'executing','base_tasking_design_sha256':sha256(design_path),
        'frozen_2026_sha256':sha256(ROOT/'data/raw/tle_2026.parquet'),
        'fresh_2026_sha256':source_document['sha256'],'fresh_source_revision':source_document['source_revision'],
        'dates':design['dates'][-2:],'full_design_date_indices':[len(design['dates'])-2,len(design['dates'])-1],
        'seed':73129,'outage_rates':design['outage_rates'],'config':design['config'],'code_sha256':code,
        'scope':'Separate descriptive source-snapshot sensitivity for two final one-hour dates. Original host IDs, full-design seed/index mapping and primary campaign bytes are preserved. Full episode cohorts, shared IDs and shared IDs/validity masks are compared separately. Element ages and geometry can both change; neither source snapshot is orbital truth.'}
    (output/'design.json').write_text(json.dumps(document,indent=2)+'\n')
    original=History(ROOT,'all');fresh=History(source_root,'all')
    responses=[];diagnostics=[];base_replays=0;cell_sources={}
    try:
        for date in document['dates']:
            date_index=design['dates'].index(date)
            old=read_inputs(date,original,design['config']);new=read_inputs(date,fresh,design['config'])
            common=np.intersect1d(old[0],new[0]);old_common=project(old,common);new_common=project(new,common)
            shared_valid=old_common[3]&new_common[3]
            variants={'original_all':old,'refreshed_all':new,
                'original_common_ids':old_common,'refreshed_common_ids':new_common,
                'original_common_ids_shared_validity':(*old_common[:3],shared_valid,old_common[4]),
                'refreshed_common_ids_shared_validity':(*new_common[:3],shared_valid,new_common[4])}
            diagnostics.append({'date':date,'original_objects':len(old[0]),'refreshed_objects':len(new[0]),
                'common_objects':len(common),'original_ids_sha256':id_hash(old[0]),
                'refreshed_ids_sha256':id_hash(new[0]),'common_ids_sha256':id_hash(common),
                'original_valid_target_source_slots_including_hosts':int(old[3][:-1].sum()),
                'refreshed_valid_target_source_slots_including_hosts':int(new[3][:-1].sum()),
                'shared_valid_slots_including_hosts':int(shared_valid[:-1].sum())})
            for regime_index,regime in enumerate(REGIMES):
                path=campaign/'cells'/date[:10]/f'{regime}.json';saved=json.loads(path.read_text())
                cell_sources[str(path.relative_to(ROOT))]=sha256(path)
                reference={row['requested_outage_rate']:row for row in saved['rows']};hosts=reference[0.]['sensor_host_ids']
                if not set(hosts)<=set(common.tolist()):raise ValueError('Frozen host missing from shared source cohort')
                for variant,inputs in variants.items():
                    ids,states,ages,valid,times=inputs
                    for rate in design['outage_rates']:
                        row=simulate_condition(date_index,regime_index,rate,ids,states,ages,valid,times,
                            hosts,design['config'],seed=73129)
                        if variant=='original_all':compare_response(reference[rate],row);base_replays+=1
                        responses.append({'source_variant':variant,**row})
                print(f'Source-refresh tasking complete: {date} {regime}',flush=True)
    finally:original.db.close();fresh.db.close()
    indexed={(r['date'],r['orbit_regime_sensor_hosts'],r['source_variant'],r['requested_outage_rate']):r for r in responses}
    contrasts=[];interactions=[]
    for date in document['dates']:
        for regime in REGIMES:
            for cohort in ('all','common_ids','common_ids_shared_validity'):
                for rate in design['outage_rates']:
                    a=indexed[date,regime,'original_'+cohort,rate];b=indexed[date,regime,'refreshed_'+cohort,rate]
                    if cohort!='all' and a['catalog_objects_in_episode']!=b['catalog_objects_in_episode']:
                        raise ValueError('Shared-ID cohort cardinality mismatch')
                    if cohort.endswith('shared_validity') and a['target_valid_step_count']!=b['target_valid_step_count']:
                        raise ValueError('Shared validity denominator differs')
                    contrasts.append({'date':date,'regime':regime,'cohort':cohort,'outage_rate':rate,
                        'refreshed_minus_original':{m:b[m]-a[m] for m in METRICS}})
                values={label:{rate:indexed[date,regime,label+'_'+cohort,rate] for rate in (0.,.2)}
                        for label in ('original','refreshed')}
                interactions.append({'date':date,'regime':regime,'cohort':cohort,
                    'change_in_20pct_minus_zero_effect':{m:(values['refreshed'][.2][m]-values['refreshed'][0.][m])
                        -(values['original'][.2][m]-values['original'][0.][m]) for m in METRICS}})
    result={'status':'completed_descriptive_source_refresh_sensitivity','design':document,
        'canonical_baseline_responses_exactly_replayed':base_replays,'response_rows':len(responses),
        'source_diagnostics':diagnostics,'snapshot_contrasts':contrasts,'outage_interactions':interactions,
        'source_cell_sha256':cell_sources,'responses':responses,
        'limits':'Two dates, one common simulation seed per paired condition, no confidence intervals or population-level significance claim. Full-cohort contrasts include membership/freshness changes; common-ID contrasts still include validity changes. Shared-validity contrasts retain changes in source geometry and element-age-dependent detection probabilities. This is not evidence that the refreshed source is more accurate.'}
    (output/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    lines=['# Final-date orbital-source tasking sensitivity','',document['scope'],'',result['limits'],'',
        f'{len(responses)} responses across two dates, four host regimes, two outage conditions and six source/cohort variants. All {base_replays} original full-cohort responses exactly match the frozen campaign.', '',
        '| Date | Original episode objects | Refreshed episode objects | Shared IDs |','|---|---:|---:|---:|']
    for d in diagnostics:lines.append(f'| {d["date"][:10]} | {d["original_objects"]:,} | {d["refreshed_objects"]:,} | {d["common_objects"]:,} |')
    lines.extend(['','Change in the injected 20%-minus-zero custody effect after source refresh, in percentage points. These are paired difference-of-differences, not uncertainty intervals.','',
        '| Date | Hosts | Cohort control | All-target custody interaction (pp) | Observable-custody interaction (pp) |',
        '|---|---|---|---:|---:|'])
    for row in interactions:
        v=row['change_in_20pct_minus_zero_effect'];lines.append(f'| {row["date"][:10]} | {row["regime"].upper()} | {row["cohort"]} | {100*v["custody_continuity"]:+.6f} | {100*v["observable_custody"]:+.6f} |')
    (output/'report.md').write_text('\n'.join(lines)+'\n');return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--snapshot',type=Path,default=ROOT/'data/raw/snapshots/2026-10-24/tle_2026.parquet')
    args=parser.parse_args();r=run(args.campaign,args.output,args.snapshot);print(json.dumps({'status':r['status'],'responses':r['response_rows']}))
