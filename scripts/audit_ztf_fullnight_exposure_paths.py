#!/usr/bin/env python3
"""Check midpoint-selected ZTF candidates over each complete exposure."""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import pathlib
import sys

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'scripts'))

import numpy as np

from audit_ztf_fullnight_catalog_crossings import sha256, tangent_polygon, unit_radec
from audit_ztf_palomer_opportunities import dense_track, parse_obsdate
from godsat.orbits import History, satellite, utc

DATA=ROOT/'data/ground_sensor/ztf_palomer_poc'
MIDPOINT=ROOT/'outputs/ztf-palomer-fullnight-2024-07-10/midpoint_crossing_audit.json'
OUT=ROOT/'outputs/ztf-palomer-fullnight-2024-07-10/exposure_path_audit.json'
MAX_AGE_HOURS=72.0
ALTITUDE_CUTOFF_DEG=10.0


def main():
    source=DATA/'ztf_metadata_2024-07-10_fullnight.csv'
    metadata=list(csv.DictReader(source.open(newline='')))
    by_exposure={}
    for row in metadata:
        by_exposure.setdefault(row['expid'],[]).append(row)
    midpoint=json.loads(MIDPOINT.read_text())
    if midpoint.get('metadata_sha256')!=sha256(source):
        raise ValueError('Midpoint audit does not match the current ZTF metadata source')
    candidates=midpoint['candidates']
    exposures=[]
    for expid,quadrants in by_exposure.items():
        start=parse_obsdate(quadrants[0]['obsdate'])
        exposures.append((start+dt.timedelta(seconds=float(quadrants[0]['exptime'])/2),expid,quadrants))
    exposures.sort()
    exposure_lookup={expid:(mid,quadrants) for mid,expid,quadrants in exposures}
    times=[exposure_lookup[row['expid']][0] for row in candidates]
    first=min(times);last=max(times)
    ids=sorted({int(row['norad_id']) for row in candidates})
    history=History(cohort='all',window=(first,last),max_age_hours=MAX_AGE_HOURS)
    try:
        rows=history.records(first,last,MAX_AGE_HOURS,ids)
        grouped={oid:[] for oid in ids}
        for row in rows:
            grouped[row['norad_id']].append(row)
        satellite_cache={}
        tracks={}
        results=[]
        for index,candidate in enumerate(candidates,1):
            midpoint_time,quadrants=exposure_lookup[candidate['expid']]
            source_row=next(row for row in quadrants
                if int(row['ccdid'])==candidate['ccdid'] and int(row['qid'])==candidate['qid'])
            norad=int(candidate['norad_id'])
            selected=None
            for row in grouped[norad]:
                if row['epoch']<=midpoint_time:
                    selected=row
                else:
                    break
            if selected is None:
                raise ValueError(f'No as-of-midpoint source element for NORAD {norad}')
            age=(midpoint_time-selected['epoch']).total_seconds()/3600
            if age<0 or age>MAX_AGE_HOURS:
                raise ValueError(f'Unfresh source element for NORAD {norad} at {candidate["expid"]}')
            if selected['epoch'].isoformat()!=candidate['tle_epoch_utc']:
                raise ValueError(f'Source epoch mismatch for NORAD {norad} at {candidate["expid"]}')
            sat_key=(norad,candidate['tle_epoch_utc'])
            if sat_key not in satellite_cache:
                satellite_cache[sat_key]=satellite(selected)
            track_key=(candidate['expid'],norad)
            if track_key not in tracks:
                tracks[track_key]=dense_track(source_row,satellite_cache[sat_key],seconds=.5)
            track=tracks[track_key]
            corners=np.asarray([[float(source_row[f'ra{k}']),float(source_row[f'dec{k}'])]
                                for k in range(1,5)])
            center,east,north,polygon,_=tangent_polygon(corners)
            units=unit_radec(track['ra'],track['dec'])
            denominator=units@center
            xy=np.column_stack(((units@east)/denominator,(units@north)/denominator))
            inside=(denominator>0)&polygon.contains_points(xy,radius=.0003)
            inside_observable=inside&track['valid']&(track['alt']>ALTITUDE_CUTOFF_DEG)
            inside_sunlit=inside_observable&track['sunlit']
            mid_index=int(np.argmin(np.abs(track['elapsed_s']-float(candidate['exptime_s'])/2)))
            observed_unit=unit_radec(np.asarray([candidate['ra_mid_deg']]),np.asarray([candidate['dec_mid_deg']]))[0]
            midpoint_error=float(np.rad2deg(np.arccos(np.clip(units[mid_index]@observed_unit,-1,1)))*3600)
            sampled_step=float(track['elapsed_s'][1]-track['elapsed_s'][0]) if len(track['elapsed_s'])>1 else None
            results.append({
                'expid':candidate['expid'],'ccdid':candidate['ccdid'],'qid':candidate['qid'],
                'norad_id':norad,'tle_epoch_utc':candidate['tle_epoch_utc'],
                'tle_age_hours_at_midpoint':age,'exptime_s':float(candidate['exptime_s']),
                'sample_step_s':sampled_step,'sample_count':int(len(track['elapsed_s'])),
                'midpoint_direction_error_arcsec':midpoint_error,
                'midpoint_inside_quadrant':bool(inside[mid_index]),
                'any_path_inside_quadrant':bool(inside.any()),
                'any_path_observable_inside':bool(inside_observable.any()),
                'any_path_sunlit_observable_inside':bool(inside_sunlit.any()),
                'sampled_seconds_inside_quadrant':float(np.trapz(inside.astype(float),track['elapsed_s'])),
                'sampled_seconds_sunlit_observable_inside':float(np.trapz(inside_sunlit.astype(float),track['elapsed_s'])),
                'altitude_min_inside_deg':float(np.min(track['alt'][inside])) if inside.any() else None,
                'altitude_max_inside_deg':float(np.max(track['alt'][inside])) if inside.any() else None,
                'sunlit_sample_fraction_inside':float(track['sunlit'][inside].mean()) if inside.any() else None,
            })
            if index%100==0:
                print(f'propagated full exposure paths for {index}/{len(candidates)} midpoint candidates',flush=True)
    finally:
        history.db.close()
    inside=[row for row in results if row['any_path_inside_quadrant']]
    observable=[row for row in results if row['any_path_observable_inside']]
    sunlit=[row for row in results if row['any_path_sunlit_observable_inside']]
    result={
        'status':'completed_full_exposure_paths_for_midpoint_candidates',
        'metadata_sha256':sha256(source),'midpoint_audit_sha256':sha256(MIDPOINT),
        'metadata_rows':len(metadata),'exposures':len(exposures),
        'midpoint_candidates':len(candidates),'candidate_catalog_ids':len(ids),
        'site':midpoint['site'],'max_element_age_hours':MAX_AGE_HOURS,
        'propagation':'Historical as-of-midpoint TLE; SGP4/WGS-72; full nominal exposure sampled every 0.5 seconds; topocentric TEME paths transformed to ICRS and AltAz.',
        'footprint_test':'The saved midpoint candidate CCD/quadrant polygon, tangent-plane point-in-polygon check with the same angular edge tolerance as the midpoint census.',
        'limitations':'This refines only candidates selected because they were inside the field at exposure midpoint. It does not search for additional objects that crossed a field edge while the midpoint was outside, and it does not inspect image pixels or estimate a detection probability/dropout rate.',
        'totals':{
            'midpoint_candidates_replayed':len(results),
            'candidates_with_path_inside':len(inside),
            'candidates_with_observable_path_inside':len(observable),
            'candidates_with_sunlit_observable_path_inside':len(sunlit),
            'exposures_with_any_sunlit_observable_path_inside':len({r['expid'] for r in sunlit}),
            'minimum_midpoint_direction_error_arcsec':min(r['midpoint_direction_error_arcsec'] for r in results),
            'maximum_midpoint_direction_error_arcsec':max(r['midpoint_direction_error_arcsec'] for r in results),
        },
        'candidates':results,
    }
    tmp=OUT.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(result,indent=2)+'\n')
    tmp.replace(OUT)
    print(json.dumps({'output':str(OUT.relative_to(ROOT)),'totals':result['totals']},indent=2))


if __name__=='__main__':
    main()
