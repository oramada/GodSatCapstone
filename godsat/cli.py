import argparse
import datetime as dt
import json
import pathlib
import subprocess
import numpy as np
from .orbits import ROOT,History,satellite,julian,utc,EARTH_RADIUS,orbit_regime,awp_propagate,teme_to_gcrs,frame_transform_provenance
from .scenario import prepare,load
from .experiment import campaign,write_json
from .dropout import run_dropout_study,quarterly_dates,monthly_dates

def config(path,quick=False):
    c=json.loads(pathlib.Path(path).read_text())
    if quick:
        c.update(agents=4,targets=12,duration_minutes=20,training_episodes=4,study_kind='quick execution check')
    else:c.setdefault('study_kind','research training run')
    return c

def main():
    p=argparse.ArgumentParser(description='GoDSAT research system using historical orbit data and AWP')
    p.add_argument('--config',default=str(ROOT/'configs/default.json'))
    sub=p.add_subparsers(dest='command',required=True)
    prep=sub.add_parser('prepare');prep.add_argument('--quick',action='store_true');prep.add_argument('--date');prep.add_argument('--regime',choices=['leo','meo','geo','heo','all'],default='leo')
    run=sub.add_parser('campaign');run.add_argument('--quick',action='store_true');run.add_argument('--output',default=str(ROOT/'outputs/research'));run.add_argument('--center-replicates',type=int,default=1)
    awp=sub.add_parser('awp-check');awp.add_argument('--date',default='2026-10-01T00:00:00Z');awp.add_argument('--regime',choices=['leo','meo','geo','heo'],default='leo');awp.add_argument('--norad',type=int,help='propagate this payload ID instead of the scenario-selected first sensor');awp.add_argument('--drag',action='store_true',help='add AWP atmospheric drag with a documented nominal ballistic coefficient');awp.add_argument('--output')
    server=sub.add_parser('serve');server.add_argument('--output',default=str(ROOT/'outputs/quick'));server.add_argument('--port',type=int,default=8765)
    dropout=sub.add_parser('dropout-study');dropout.add_argument('--baseline-output',default=str(ROOT/'outputs/full-paper-study'));dropout.add_argument('--output',default=str(ROOT/'outputs/dropout-study'));dropout.add_argument('--replicates',type=int,default=20);dropout.add_argument('--dates',help='comma-separated UTC dates, or quarterly/monthly for a four-year historical grid')
    args=p.parse_args();c=config(args.config,getattr(args,'quick',False))
    if args.command=='prepare':
        dates=[args.date] if args.date else sum((c[split+'_dates'] for split in ['training','validation','test']),[])
        for date in dates:print(prepare(date,c,regime=args.regime),flush=True)
    elif args.command=='campaign':
        if args.center_replicates<1:p.error('center-replicates must be positive')
        result=campaign(c,args.output,args.center_replicates);print(json.dumps(result,indent=2))
    elif args.command=='awp-check':
        s=load(prepare(args.date,c,regime=args.regime));times=np.arange(len(s['times']))*c['step_seconds'];
        reference_states=s['states'][:,0,:]
        if args.norad is None:
            norad_id=int(s['ids'][0]);state=s['states'][0,0];epoch=s['source_epochs'][0,0]
        else:
            history=History(ROOT,'current_payload')
            try:
                matches=[r for r in history.snapshot(args.date,c['max_element_age_hours']) if int(r['norad_id'])==args.norad]
            finally:history.db.close()
            if not matches:raise ValueError(f'Payload {args.norad} has no element set within {c["max_element_age_hours"]} hours of {args.date}')
            row=matches[0];sat=satellite(row);err,pos,vel=sat.sgp4(*julian(utc(args.date)))
            if orbit_regime(row)!=args.regime:raise ValueError(f'Payload {args.norad} classifies as {orbit_regime(row)}, not requested {args.regime}')
            if err or not np.isfinite(pos+vel).all():raise ValueError(f'SGP4 failed for payload {args.norad}: code {err}')
            norad_id=int(args.norad);state=np.r_[pos,vel];epoch=row['epoch'].isoformat()
            sample_times=[utc(args.date)+dt.timedelta(seconds=float(v)) for v in times]
            states=[]
            for sample_time in sample_times:
                sample_error,sample_pos,sample_vel=sat.sgp4(*julian(sample_time))
                states.append([*sample_pos,*sample_vel] if sample_error==0 else [np.nan]*6)
            reference_states=np.asarray(states)
        sample_times=[utc(args.date)+dt.timedelta(seconds=float(v)) for v in times]
        inertial_initial=teme_to_gcrs(state, sample_times[0])
        inertial_reference=np.asarray([teme_to_gcrs(row, instant)
            for row,instant in zip(reference_states,sample_times)])
        numerical=awp_propagate(inertial_initial,times[-1],times,drag=args.drag)
        difference=np.linalg.norm(numerical[:,:3]-inertial_reference[:,:3],axis=1)
        drag_delta=None
        if args.drag:
            no_drag=awp_propagate(inertial_initial,times[-1],times,drag=False)
            drag_delta=float(np.max(np.linalg.norm(numerical[:,:3]-no_drag[:,:3],axis=1)))
        suffix='_drag' if args.drag else ''
        output=args.output or str(ROOT/'outputs'/(f'awp_check{suffix}.json' if args.regime=='leo' else f'awp_check_{args.regime}{suffix}.json'))
        model='AWP two-body + J2 + exponential-atmosphere drag' if args.drag else 'AWP Spacecraft two-body + J2'
        write_json(output,{'awp_revision':subprocess.check_output(['git','-C',str(ROOT/'vendor/AWP'),'rev-parse','HEAD'],text=True).strip(),
            'norad_id':norad_id,'element_epoch':epoch,'element_age_hours':(utc(args.date)-utc(epoch)).total_seconds()/3600,
            'initial_altitude_km':float(np.linalg.norm(state[:3])-EARTH_RADIUS),'orbit_regime':args.regime,'date':args.date,'model':model,
            'comparison_frame':'GCRS axes; SGP4 TEME states transformed with Astropy before comparison to AWP Earth-centered inertial propagation',
            'frame_transform_provenance':frame_transform_provenance(),
            'drag_assumptions':{'area_mass_m2_kg':0.01,'drag_coefficient':2.2,'density_model':'piecewise standard-atmosphere table, log-linear interpolation'} if args.drag else None,
            'max_separation_from_no_drag_awp_km':drag_delta,
            'times_seconds':times.tolist(),'separation_from_historical_sgp4_km':difference.tolist(),
            'max_separation_km':float(np.nanmax(difference)),
            'interpretation':'Model sensitivity, not ground-truth error. '+('Drag uses nominal ballistic properties and a simplified density model; no maneuvers or element resets are modeled.' if args.drag else 'AWP omits drag/maneuvers and element resets here.')})
        print(output)
    elif args.command=='serve':
        from .server import serve
        serve(pathlib.Path(args.output),args.port)
    elif args.command=='dropout-study':
        if args.replicates<2:p.error('dropout study needs at least two replicates')
        if args.dates:
            if args.dates=='quarterly':c['dropout_dates']=quarterly_dates()
            elif args.dates=='monthly':c['dropout_dates']=monthly_dates()
            else:c['dropout_dates']=[x.strip() for x in args.dates.split(',') if x.strip()]
        result=run_dropout_study(c,args.baseline_output,args.output,replicates=args.replicates)
        print(json.dumps(result,indent=2))

if __name__=='__main__':main()
