"""Compare AWP's two-body/J2 and SPICE solar-lunar gravity models by regime."""

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))

import argparse
import csv
import datetime as dt
import hashlib
import json
import pathlib
import subprocess

import numpy as np

from godsat.orbits import (ROOT, History, awp_propagate,
    frame_transform_provenance, julian, satellite, teme_to_gcrs, utc)
from godsat.trajectory import source_revision
from scripts.data.awp_historical_sensitivity import DEFAULT_OBJECTS, LEAD_HOURS


def run(output, date='2026-10-01T00:00:00Z', root=ROOT):
    root=pathlib.Path(root).resolve();output=pathlib.Path(output).resolve()
    target_date=utc(date)
    start=target_date-dt.timedelta(hours=72)
    history=History(root,cohort='all',window=(target_date,target_date),max_age_hours=72)
    try:
        records=history.records(start,target_date,max_age=0,ids=list(DEFAULT_OBJECTS.values()))
    finally:
        history.db.close()
    selected=[]
    missing=[]
    for regime,norad_id in DEFAULT_OBJECTS.items():
        options=[row for row in records if int(row['norad_id'])==norad_id]
        if not options:
            missing.append((regime,norad_id));continue
        element=min(options,key=lambda row:abs((utc(row['epoch'])-target_date).total_seconds()))
        selected.append((regime,norad_id,element))
    if missing:
        raise ValueError(f'No fresh source elements for requested regimes: {missing}')

    seconds=np.asarray(LEAD_HOURS,dtype=float)*3600
    rows=[]
    for regime,norad_id,element in selected:
        epoch=utc(element['epoch']);record=satellite(element)
        error,pos,vel=record.sgp4(*julian(epoch))
        if error or not np.isfinite(np.r_[pos,vel]).all():
            raise ValueError(f'Initial SGP4 error {error} for NORAD {norad_id}')
        initial=teme_to_gcrs(np.r_[pos,vel],epoch)
        reference=[]
        for lead in seconds:
            instant=epoch+dt.timedelta(seconds=float(lead))
            code,r,v=record.sgp4(*julian(instant))
            reference.append(None if code or not np.isfinite(np.r_[r,v]).all()
                             else teme_to_gcrs(np.r_[r,v],instant))
        propagations={
            'awp_two_body_j2':awp_propagate(initial,seconds[-1],seconds,j2=True),
            'awp_j2_sun_moon_third_body':awp_propagate(
                initial,seconds[-1],seconds,j2=True,third_bodies=True,epoch=epoch),
        }
        for model,states in propagations.items():
            for lead,state,ref in zip(LEAD_HOURS,states,reference):
                rows.append({
                    'orbit_regime':regime,'norad_id':norad_id,
                    'source_element_epoch_utc':epoch.isoformat(),
                    'element_age_hours_at_requested_date':(target_date-epoch).total_seconds()/3600,
                    'requested_date_utc':target_date.isoformat(),'model':model,
                    'lead_hours':lead,'sgp4_error':0 if ref is not None else 1,
                    'position_separation_km':None if ref is None else float(np.linalg.norm(state[:3]-ref[:3])),
                    'velocity_separation_km_s':None if ref is None else float(np.linalg.norm(state[3:]-ref[3:])),
                })

    output.mkdir(parents=True,exist_ok=True)
    csv_path=output/'awp_nbody_comparisons.csv'
    with csv_path.open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]))
        writer.writeheader();writer.writerows(rows)
    groups={}
    for row in rows:
        key=(row['orbit_regime'],row['model'],str(row['lead_hours']))
        groups.setdefault(key,[]).append(row)
    summary=[]
    for (regime,model,lead),group in sorted(groups.items()):
        values=np.asarray([row['position_separation_km'] for row in group
                           if row['position_separation_km'] is not None])
        summary.append({'orbit_regime':regime,'model':model,'lead_hours':int(lead),
            'n_cases':len(group),'n_valid_comparisons':len(values),
            'position_separation_median_km':float(np.median(values)) if len(values) else None,
            'position_separation_p95_km':float(np.quantile(values,.95)) if len(values) else None})
    manifest={
        'status':'completed','requested_date_utc':target_date.isoformat(),
        'source_revision':source_revision(root),
        'awp_revision':subprocess.check_output(['git','-C',str(root/'vendor/AWP'),
            'rev-parse','HEAD'],text=True).strip(),
        'spice_spk':'vendor/AWP/data/spice/spk/de432s.bsp',
        'spice_lsk':'vendor/AWP/data/spice/lsk/naif0012.tls',
        'ephemeris_sha256':hashlib.sha256((root/'vendor/AWP/data/spice/spk/de432s.bsp').read_bytes()).hexdigest(),
        'frame':'GCRS states compared in AWP J2000-like inertial force frame',
        'frame_transform_provenance':frame_transform_provenance(),
        'objects_by_regime':DEFAULT_OBJECTS,'selected_cases':len(selected),
        'comparison_rows':len(rows),'lead_hours':list(LEAD_HOURS),
        'models':['AWP two-body + J2','AWP two-body + J2 + solar/lunar point-mass gravity'],
        'gravity_parameters':{'sun_mu_km3_s2':1.3271244004193938e11,
            'moon_mu_km3_s2':4.902800066e3,
            'source':'AWP upstream Spacecraft.calc_n_bodies with DE432s SPICE positions'},
        'summary_by_regime_model_and_lead':summary,
        'interpretation':'Model-to-model sensitivity against same-element SGP4, not orbit truth.',
        'limitations':['One representative source epoch per regime and one requested date.',
            'SGP4 mean-element propagation is not independent truth.',
            'The model includes Earth central gravity, J2, and solar/lunar point-mass terms; it omits drag, higher geopotential, SRP, maneuvers, covariance, and data assimilation.',
            'AWP J2000 and Astropy GCRS are treated as aligned inertial axes for this sensitivity comparison.'],
        'csv':csv_path.name,
        'csv_sha256':hashlib.sha256(csv_path.read_bytes()).hexdigest(),
        'source_manifest_sha256':hashlib.sha256((root/'data/raw/manifest.json').read_bytes()).hexdigest(),
    }
    (output/'summary.json').write_text(json.dumps(manifest,indent=2,allow_nan=False)+'\n')
    return manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--date',default='2026-10-01T00:00:00Z')
    parser.add_argument('--output',default=str(ROOT/'outputs/awp-nbody-sensitivity-2026-10-01'))
    args=parser.parse_args()
    print(json.dumps(run(args.output,args.date),indent=2))


if __name__=='__main__':
    main()
