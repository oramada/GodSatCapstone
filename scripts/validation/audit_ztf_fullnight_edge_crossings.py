#!/usr/bin/env python3
"""Find and replay ZTF crossings missed by midpoint-only footprint selection."""
from __future__ import annotations

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
import sys

ROOT=pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
import astropy.units as u
import numpy as np
from astropy.coordinates import AltAz, CartesianRepresentation, EarthLocation, SkyCoord, TEME, get_sun
from astropy.time import Time
from sgp4.api import SatrecArray

from scripts.validation.audit_ztf_fullnight_catalog_crossings import sha256, tangent_polygon, unit_radec
from scripts.validation.audit_ztf_palomer_opportunities import parse_obsdate
from godsat.orbits import EARTH_MU, History, julian, satellite

DATA=ROOT/'data/ground_sensor/ztf_palomer_poc'
OUT=ROOT/'outputs/ztf-palomer-fullnight-2024-07-10'
MIDPOINT=OUT/'midpoint_crossing_audit.json'
EXPOSURE_PATHS=OUT/'exposure_path_audit.json'
SITE=EarthLocation.from_geodetic(-116.865*u.deg,33.357*u.deg,1.7*u.km)
MAX_AGE_HOURS=72.0
ALTITUDE_CUTOFF_DEG=10.0
RELATIVE_SPEED_FLOOR_KM_S=12.0
ORBIT_SPEED_SAFETY_FACTOR=1.5
OBSERVER_SPEED_ALLOWANCE_KM_S=.5
SCREEN_ANGLE_ALLOWANCE_DEG=.05
PATH_STEP_S=.1
CHUNK_EXPOSURES=12


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def keplerian_relative_speed_bound(row):
    motion=float(row['mean_motion'])*2*np.pi/86400.0
    eccentricity=float(row['eccentricity'])
    if motion<=0 or not (0<=eccentricity<1):
        return float('inf')
    semimajor=(EARTH_MU/(motion*motion))**(1/3)
    perigee=semimajor*(1-eccentricity)
    if perigee<=0:
        return float('inf')
    perigee_speed=np.sqrt(EARTH_MU*(1+eccentricity)/perigee)
    return max(RELATIVE_SPEED_FLOOR_KM_S,
               ORBIT_SPEED_SAFETY_FACTOR*perigee_speed+OBSERVER_SPEED_ALLOWANCE_KM_S)


def atomic_checkpoint(path,payload):
    tmp=path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(payload,separators=(',',':'))+'\n')
    tmp.replace(path)


def propagate_exposure_candidates(candidates,exposure,grouped_records):
    mid,expid,quadrants=exposure
    by_id={}
    for candidate in candidates:
        norad=int(candidate['norad_id'])
        if norad in by_id:
            continue
        selected=None
        for row in grouped_records[norad]:
            if row['epoch']<=mid:
                selected=row
            else:
                break
        if selected is None or selected['epoch'].isoformat()!=candidate['tle_epoch_utc']:
            raise ValueError(f'Source element changed for screened NORAD {norad}')
        by_id[norad]=selected
    norads=list(by_id)
    satrecs=[satellite(by_id[norad]) for norad in norads]
    exptime=float(quadrants[0]['exptime'])
    elapsed=np.arange(0.0,exptime+PATH_STEP_S*.25,PATH_STEP_S)
    start=parse_obsdate(quadrants[0]['obsdate'])
    when=[start+dt.timedelta(seconds=float(seconds)) for seconds in elapsed]
    time=Time(when)
    jd_fr=[julian(instant) for instant in when]
    errors,positions,velocities=SatrecArray(satrecs).sgp4(
        np.asarray([item[0] for item in jd_fr],dtype=np.float64),
        np.asarray([item[1] for item in jd_fr],dtype=np.float64))
    observer=SITE.get_itrs(obstime=time).transform_to(TEME(obstime=time)).cartesian.xyz.to_value(u.km).T
    los=positions-observer[None,:,:]
    ranges=np.linalg.norm(los,axis=2)
    directions=los/ranges[:,:,None]
    coordinates=SkyCoord(CartesianRepresentation(directions.transpose(2,0,1)*u.one),
                         frame=TEME(obstime=time[None,:]))
    icrs=coordinates.icrs
    icrs_units=icrs.cartesian.xyz.to_value(u.one).transpose(1,2,0)
    alt=coordinates.transform_to(AltAz(obstime=time[None,:],location=SITE,
                                      pressure=0*u.hPa)).alt.to_value(u.deg)
    sun=get_sun(time).transform_to(TEME(obstime=time)).cartesian.xyz.to_value(u.km).T
    along=np.einsum('ntk,tk->nt',positions,sun)
    sun2=np.einsum('tk,tk->t',sun,sun)
    perpendicular=np.sqrt(np.maximum(0.0,np.einsum('ntk,ntk->nt',positions,positions)-along*along/sun2[None,:]))
    sunlit=~((along<0)&(perpendicular<6378.135))
    valid=(errors==0)&np.isfinite(positions).all(axis=2)&np.isfinite(icrs_units).all(axis=2)
    id_index={norad:index for index,norad in enumerate(norads)}
    metadata={(int(row['ccdid']),int(row['qid'])):row for row in quadrants}
    polygon_cache={}
    results=[]
    mid_index=int(round(exptime/2/PATH_STEP_S))
    for candidate in candidates:
        norad=int(candidate['norad_id']);sat_index=id_index[norad]
        key=(int(candidate['ccdid']),int(candidate['qid']))
        source_row=metadata[key]
        if key not in polygon_cache:
            corners=np.asarray([[float(source_row[f'ra{k}']),float(source_row[f'dec{k}'])]
                                for k in range(1,5)])
            polygon_cache[key]=tangent_polygon(corners)[:4]
        center,east,north,polygon=polygon_cache[key]
        units=icrs_units[sat_index]
        denominator=units@center
        safe_denominator=np.where(np.abs(denominator)>1e-8,denominator,1.0)
        xy=np.column_stack(((units@east)/safe_denominator,(units@north)/safe_denominator))
        inside=(denominator>0)&polygon.contains_points(xy,radius=.0003)
        inside&=valid[sat_index]
        observable=inside&(alt[sat_index]>ALTITUDE_CUTOFF_DEG)
        sunlit_observable=observable&sunlit[sat_index]
        expected=unit_radec(np.asarray([candidate['ra_mid_deg']]),
                            np.asarray([candidate['dec_mid_deg']]))[0]
        midpoint_error=float(np.rad2deg(np.arccos(np.clip(units[mid_index]@expected,-1,1)))*3600)
        results.append({
            **candidate,'sample_step_s':PATH_STEP_S,'sample_count':len(elapsed),
            'crosses_quadrant_during_exposure':bool(inside.any()),
            'observable_crossing_above_10deg':bool(observable.any()),
            'sunlit_observable_crossing':bool(sunlit_observable.any()),
            'sampled_path_seconds_inside':float(np.trapz(inside.astype(float),elapsed)),
            'sampled_path_seconds_observable':float(np.trapz(observable.astype(float),elapsed)),
            'sampled_path_seconds_sunlit_observable':float(np.trapz(sunlit_observable.astype(float),elapsed)),
            'midpoint_direction_error_arcsec':midpoint_error,
        })
    return results


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--max-exposures',type=int,default=None,
                        help='limit a diagnostic run; omit to audit the complete night')
    parser.add_argument('--output',type=pathlib.Path,default=OUT/'edge_crossing_audit.json')
    parser.add_argument('--checkpoint',type=pathlib.Path,default=OUT/'edge_crossing_audit.partial.json')
    args=parser.parse_args()
    source=DATA/'ztf_metadata_2024-07-10_fullnight.csv'
    metadata=list(csv.DictReader(source.open(newline='')))
    by_exposure={}
    for row in metadata:
        by_exposure.setdefault(row['expid'],[]).append(row)
    exposures=[]
    for expid,quadrants in by_exposure.items():
        start=parse_obsdate(quadrants[0]['obsdate'])
        exposures.append((start+dt.timedelta(seconds=float(quadrants[0]['exptime'])/2),expid,quadrants))
    exposures.sort()
    if args.max_exposures is not None:
        if args.max_exposures<1:
            raise ValueError('--max-exposures must be positive')
        exposures=exposures[:args.max_exposures]
    exposure_lookup={expid:(mid,quadrants) for mid,expid,quadrants in exposures}
    mid_audit=json.loads(MIDPOINT.read_text())
    path_audit=json.loads(EXPOSURE_PATHS.read_text())
    if mid_audit['metadata_sha256']!=sha256(source) or path_audit['metadata_sha256']!=sha256(source):
        raise ValueError('Saved ZTF opportunity audits do not match current metadata')
    midpoint_keys={(r['expid'],int(r['ccdid']),int(r['qid']),int(r['norad_id']))
                   for r in mid_audit['candidates']}
    scoped_midpoint_keys={key for key in midpoint_keys if key[0] in exposure_lookup}
    ids=[]
    with (ROOT/'data/history_coverage.csv').open(newline='') as stream:
        ids=[int(row['norad_id']) for row in csv.DictReader(stream)]
    metadata_hash=sha256(source)
    midpoint_hash=file_hash(MIDPOINT)
    paths_hash=file_hash(EXPOSURE_PATHS)
    ids_hash=hashlib.sha256(np.asarray(ids,dtype=np.int64).tobytes()).hexdigest()
    run_spec={
        'metadata_sha256':metadata_hash,'midpoint_audit_sha256':midpoint_hash,
        'exposure_path_audit_sha256':paths_hash,'catalog_ids_sha256':ids_hash,
        'exposure_count':len(exposures),'max_age_hours':MAX_AGE_HOURS,
        'altitude_cutoff_deg':ALTITUDE_CUTOFF_DEG,
        'speed_floor_km_s':RELATIVE_SPEED_FLOOR_KM_S,
        'perigee_speed_safety_factor':ORBIT_SPEED_SAFETY_FACTOR,
        'observer_speed_allowance_km_s':OBSERVER_SPEED_ALLOWANCE_KM_S,
        'screen_angle_allowance_deg':SCREEN_ANGLE_ALLOWANCE_DEG,
        'path_step_s':PATH_STEP_S,'max_exposures':args.max_exposures,
        'algorithm':'per-object-displacement-cap-and-batched-dense-edge-track-v2',
    }
    run_hash=hashlib.sha256(json.dumps(run_spec,sort_keys=True).encode()).hexdigest()
    state={'phase':'screening','completed_exposures':0,'edge_candidates':[],
           'exposure_summary':[],'covered_midpoint_keys':[],'completed_paths':0,'path_results':[]}
    if args.checkpoint.is_file():
        previous=json.loads(args.checkpoint.read_text())
        if previous.get('run_sha256')==run_hash:
            state.update({k:previous[k] for k in state if k in previous})
    first=exposures[0][0];last=exposures[-1][0]
    history=History(cohort='all',window=(first,last),max_age_hours=MAX_AGE_HOURS)
    try:
        rows=history.records(first,last,MAX_AGE_HOURS,ids)
        grouped={int(oid):[] for oid in ids}
        speed_by_id={int(oid):RELATIVE_SPEED_FLOOR_KM_S for oid in ids}
        for row in rows:
            grouped[row['norad_id']].append(row)
            speed_by_id[row['norad_id']]=max(speed_by_id[row['norad_id']],
                                               keplerian_relative_speed_bound(row))
        speed_bounds=np.asarray([speed_by_id[int(oid)] for oid in ids])
        if state['phase']=='screening':
            seen_midpoint=set(tuple(key) for key in state['covered_midpoint_keys'])
            for chunk_start in range(state['completed_exposures'],len(exposures),CHUNK_EXPOSURES):
                chunk=exposures[chunk_start:chunk_start+CHUNK_EXPOSURES]
                times=[item[0] for item in chunk]
                states,ages,errors,epochs=history.replay(
                    ids,times,max_age=MAX_AGE_HOURS,grouped_records=grouped)
                for time_index,(mid,expid,quadrants) in enumerate(chunk):
                    valid=(errors[time_index]==0)&np.isfinite(states[time_index]).all(axis=1)
                    valid&=(ages[time_index]>=0)&(ages[time_index]<=MAX_AGE_HOURS)
                    object_indices=np.flatnonzero(valid)
                    if not len(object_indices):
                        state['exposure_summary'].append({'expid':expid,'fresh_valid_objects':0,
                            'screen_candidates':0,'edge_path_checks':0})
                        continue
                    instant=Time(mid)
                    observer=SITE.get_itrs(obstime=instant).transform_to(
                        TEME(obstime=instant)).cartesian.xyz.to_value(u.km)
                    pos=states[time_index,valid,:3]
                    los=pos.T-observer[:,None]
                    ranges=np.linalg.norm(los,axis=0)
                    directions=(los/ranges[None,:]).T
                    top=SkyCoord(CartesianRepresentation(directions.T*u.one),
                                 frame=TEME(obstime=instant))
                    icrs=top.icrs
                    alt=top.transform_to(AltAz(obstime=instant,location=SITE,
                                               pressure=0*u.hPa)).alt.to_value(u.deg)
                    units=icrs.cartesian.xyz.to_value(u.one).T
                    quadrants_prepared=[]
                    for quadrant in quadrants:
                        corners=np.asarray([[float(quadrant[f'ra{k}']),float(quadrant[f'dec{k}'])]
                                             for k in range(1,5)])
                        center,east,north,polygon,chord_radius=tangent_polygon(corners)
                        quadrants_prepared.append((quadrant,center,east,north,polygon,chord_radius))
                    centers=np.asarray([item[1] for item in quadrants_prepared])
                    radii=np.asarray([item[5] for item in quadrants_prepared])
                    exposure_seconds=float(quadrants[0]['exptime'])
                    displacement=speed_bounds[object_indices]*(exposure_seconds/2)
                    ratio=displacement/ranges
                    margins=np.where(ratio>=1,np.pi,np.arcsin(np.clip(ratio,0,1)))
                    margins+=np.deg2rad(SCREEN_ANGLE_ALLOWANCE_DEG)
                    angular_separation=np.arccos(np.clip(units@centers.T,-1,1))
                    possible=(angular_separation<=radii[None,:]+margins[:,None])
                    possible&=(alt[:,None]>ALTITUDE_CUTOFF_DEG-np.rad2deg(margins)[:,None])
                    midpoint_candidates=0
                    screened_this_exposure=0
                    for qi,indices in enumerate(quadrants_prepared):
                        q=indices[0]
                        local=np.flatnonzero(possible[:,qi])
                        if not len(local):
                            continue
                        q,center,east,north,polygon,chord_radius=indices
                        denominator=units[local]@center
                        xy=np.column_stack(((units[local]@east)/denominator,
                                            (units[local]@north)/denominator))
                        midpoint_inside=(denominator>0)&polygon.contains_points(xy,radius=.0003)
                        for local_position,inside_mid in zip(local,midpoint_inside):
                            original_index=int(object_indices[local_position])
                            norad=int(ids[original_index])
                            key=(expid,int(q['ccdid']),int(q['qid']),norad)
                            if key in midpoint_keys:
                                seen_midpoint.add(key)
                                midpoint_candidates+=1
                                continue
                            if inside_mid and alt[local_position]>ALTITUDE_CUTOFF_DEG:
                                raise ValueError(f'Midpoint crossing missing from original ledger: {key}')
                            record_epoch=str(epochs[time_index,original_index])
                            candidate={
                                'expid':expid,'obsdate_start_utc':q['obsdate'],
                                'exptime_s':exposure_seconds,'field':int(q['field']),
                                'ccdid':int(q['ccdid']),'qid':int(q['qid']),
                                'filtercode':q['filtercode'],'filefracday':q['filefracday'],
                                'maglimit':float(q['maglimit']),'seeing_arcsec':float(q['seeing']),
                                'norad_id':norad,'tle_epoch_utc':record_epoch,
                                'tle_age_hours_at_midpoint':float(ages[time_index,original_index]),
                                'ra_mid_deg':float(icrs.ra.to_value(u.deg)[local_position]),
                                'dec_mid_deg':float(icrs.dec.to_value(u.deg)[local_position]),
                                'altitude_mid_deg':float(alt[local_position]),
                                'range_mid_km':float(ranges[local_position]),
                                'relative_speed_bound_km_s':float(speed_bounds[original_index]),
                                'angular_displacement_bound_deg':float(np.rad2deg(margins[local_position])),
                                'midpoint_inside_quadrant':bool(inside_mid),
                                'screen_reason':'outside_footprint_or_below_altitude_cutoff_at_midpoint',
                            }
                            state['edge_candidates'].append(candidate)
                            screened_this_exposure+=1
                    state['covered_midpoint_keys']=sorted(seen_midpoint)
                    state['exposure_summary'].append({
                        'expid':expid,'fresh_valid_objects':int(valid.sum()),
                        'screen_candidates':screened_this_exposure,
                        'midpoint_candidates_accounted':midpoint_candidates,
                        'edge_path_checks':screened_this_exposure,
                    })
                state['completed_exposures']=min(chunk_start+len(chunk),len(exposures))
                atomic_checkpoint(args.checkpoint,{'run_sha256':run_hash,'run_spec':run_spec,**state})
                print(f"screened {state['completed_exposures']}/{len(exposures)} exposures; "
                      f"{len(state['edge_candidates'])} edge/below-cutoff candidates",flush=True)
            if set(tuple(k) for k in state['covered_midpoint_keys'])!=scoped_midpoint_keys:
                missing=scoped_midpoint_keys-set(tuple(k) for k in state['covered_midpoint_keys'])
                raise ValueError(f'Midpoint candidates outside displacement screen: {len(missing)}')
            state['phase']='paths'
            atomic_checkpoint(args.checkpoint,{'run_sha256':run_hash,'run_spec':run_spec,**state})
        path_candidates=state['edge_candidates']
        path_results=state['path_results']
        path_exposures=list(dict.fromkeys(row['expid'] for row in path_candidates))
        for index in range(state['completed_paths'],len(path_exposures)):
            expid=path_exposures[index]
            candidates=[row for row in path_candidates if row['expid']==expid]
            path_results.extend(propagate_exposure_candidates(
                candidates,next(item for item in exposures if item[1]==expid),grouped))
            state['completed_paths']=index+1
            if state['completed_paths']%10==0 or state['completed_paths']==len(path_exposures):
                state['path_results']=path_results
                atomic_checkpoint(args.checkpoint,{'run_sha256':run_hash,'run_spec':run_spec,**state})
                print(f"replayed edge candidates in {state['completed_paths']}/{len(path_exposures)} exposures",flush=True)
        edge_hits=[r for r in path_results if r['crosses_quadrant_during_exposure']]
        observable_hits=[r for r in path_results if r['observable_crossing_above_10deg']]
        sunlit_hits=[r for r in path_results if r['sunlit_observable_crossing']]
        result={
            'status':'completed_screened_edge_crossing_replay',
            'metadata_sha256':metadata_hash,'midpoint_audit_sha256':midpoint_hash,
            'exposure_path_audit_sha256':paths_hash,'catalog_ids_sha256':ids_hash,
            'run_sha256':run_hash,'catalog_ids_considered':len(ids),
            'exposures_screened':len(exposures),'exposures_in_full_night':len(by_exposure),
            'midpoint_candidates':len(scoped_midpoint_keys),
            'screen_method':{
                'basis':'A relative-position displacement bound around each exposure midpoint, then expanded CCD circumradius and altitude cutoff.',
                'perigee_speed':'Keplerian perigee speed derived from historical mean motion/eccentricity; multiplied by the safety factor and augmented by a 0.5 km/s observer allowance.',
                'angular_displacement_bound':'asin(v_bound * exposure_half_duration / topocentric_range), or 180 degrees when the displacement bound reaches the range, plus the angular safety allowance.',
                'relative_speed_floor_km_s':RELATIVE_SPEED_FLOOR_KM_S,
                'perigee_speed_safety_factor':ORBIT_SPEED_SAFETY_FACTOR,
                'observer_speed_allowance_km_s':OBSERVER_SPEED_ALLOWANCE_KM_S,
                'additional_angle_allowance_deg':SCREEN_ANGLE_ALLOWANCE_DEG,
                'midpoint_altitude_screen':'Only objects whose midpoint altitude could reach 10 degrees within the same angular displacement bound are retained.',
                'catalog_freshness_hours':MAX_AGE_HOURS,
            },
            'path_method':f"Historical as-of-midpoint TLE, SGP4/WGS-72, {PATH_STEP_S:.2f}-second propagation samples; polygon containment, >{ALTITUDE_CUTOFF_DEG:.0f} degree altitude and cylindrical Earth-shadow sunlight check.",
            'limitations':'Only candidates inside the kinematic displacement screen receive dense path replay. The screen is an engineering bound based on two-body perigee speed, not a formal bound on every SGP4 perturbation or bad/stale catalog element. No image pixels, independent object identity, calibrated brightness, or planned-attempt ledger are included; this is not a dropout measurement.',
            'totals':{
                'screened_candidates':len(path_candidates),
                'exact_path_edge_crossings':len(edge_hits),
                'observable_edge_crossings_above_10deg':len(observable_hits),
                'sunlit_observable_edge_crossings':len(sunlit_hits),
                'exposures_with_edge_crossing':len({r['expid'] for r in edge_hits}),
                'exposures_with_sunlit_observable_edge_crossing':len({r['expid'] for r in sunlit_hits}),
                'screen_candidates_outside_altitude_and_field_at_midpoint':sum(not r['midpoint_inside_quadrant'] for r in path_candidates),
                'screen_candidates_inside_quadrant_below_10deg_at_midpoint':sum(r['midpoint_inside_quadrant'] for r in path_candidates),
            },
            'screening_summary':state['exposure_summary'],
            'candidates':path_results,
            'scope_complete':args.max_exposures is None,
        }
        args.output.parent.mkdir(parents=True,exist_ok=True)
        tmp=args.output.with_suffix(args.output.suffix+'.tmp')
        tmp.write_text(json.dumps(result,indent=2)+'\n')
        tmp.replace(args.output)
        args.checkpoint.unlink(missing_ok=True)
        print(json.dumps({'output':str(args.output),'totals':result['totals'],
                          'scope_complete':result['scope_complete']},indent=2))
    finally:
        history.db.close()


if __name__=='__main__':
    main()
