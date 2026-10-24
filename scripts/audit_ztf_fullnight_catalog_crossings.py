#!/usr/bin/env python3
"""Replay the full public ZTF Palomar night against as-of-time catalog TLEs."""
from __future__ import annotations
import csv
import datetime as dt
import hashlib
import json
import pathlib
import re
import sys

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import astropy.units as u
import numpy as np
from astropy.coordinates import AltAz, CartesianRepresentation, EarthLocation, SkyCoord, TEME, get_sun
from astropy.time import Time
from matplotlib.path import Path
from scipy.spatial import cKDTree
from godsat.orbits import History, utc

DATA=ROOT/'data/ground_sensor/ztf_palomer_poc'
OUT=ROOT/'outputs/ztf-palomer-fullnight-2024-07-10'
SITE=EarthLocation.from_geodetic(-116.865*u.deg,33.357*u.deg,1.7*u.km)
MAX_AGE_HOURS=72.0
CHUNK_TIMES=24


def parse_obsdate(value):
    value=value.replace(' ','T')
    value=re.sub(r'\.(\d{1,6})(?=\+00$)',lambda m:'.'+m.group(1).ljust(6,'0'),value)
    return utc(value.replace('+00','+00:00'))


def sha256(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()


def unit_radec(ra,dec):
    ra=np.deg2rad(ra);dec=np.deg2rad(dec)
    return np.column_stack((np.cos(dec)*np.cos(ra),np.cos(dec)*np.sin(ra),np.sin(dec)))


def tangent_polygon(corners):
    vec=unit_radec(corners[:,0],corners[:,1])
    center=vec.sum(axis=0);center/=np.linalg.norm(center)
    east=np.cross(np.array([0.0,0.0,1.0]),center);east/=np.linalg.norm(east)
    north=np.cross(center,east)
    denominator=vec@center
    poly=np.column_stack(((vec@east)/denominator,(vec@north)/denominator))
    radius=float(np.max(np.arccos(np.clip(denominator,-1,1))))+np.deg2rad(.03)
    return center,east,north,Path(poly),2*np.sin(radius/2)


def main():
    source=DATA/'ztf_metadata_2024-07-10_fullnight.csv'
    rows=list(csv.DictReader(source.open(newline='')))
    by_exposure={}
    for row in rows:by_exposure.setdefault(row['expid'],[]).append(row)
    exposures=[]
    for expid,quadrants in by_exposure.items():
        start=parse_obsdate(quadrants[0]['obsdate'])
        mid=start+dt.timedelta(seconds=float(quadrants[0]['exptime'])/2)
        exposures.append((mid,expid,quadrants))
    exposures.sort()
    start=exposures[0][0];end=exposures[-1][0]
    ids=[]
    with (ROOT/'data/history_coverage.csv').open(newline='') as f:
        ids=[int(row['norad_id']) for row in csv.DictReader(f)]
    history=History(cohort='all',window=(start,end),max_age_hours=MAX_AGE_HOURS)
    OUT.mkdir(parents=True,exist_ok=True)
    metadata_hash=sha256(source)
    ids_hash=hashlib.sha256(np.asarray(ids,dtype=np.int64).tobytes()).hexdigest()
    run_hash=hashlib.sha256(json.dumps({
        'metadata_sha256':metadata_hash,'catalog_ids_sha256':ids_hash,
        'max_age_hours':MAX_AGE_HOURS,'site_lon_deg':-116.865,
        'site_lat_deg':33.357,'site_altitude_km':1.7,
        'altitude_cutoff_deg':10.0,'algorithm':'midpoint-footprint-sgp4-v1'
    },sort_keys=True).encode()).hexdigest()
    partial_path=OUT/'midpoint_crossing_audit.partial.json'
    candidates=[];summary=[]
    completed_exposures=0
    if partial_path.is_file():
        previous=json.loads(partial_path.read_text())
        if previous.get('run_sha256')==run_hash:
            prior_candidates=previous.get('candidates',[])
            prior_summary=previous.get('exposure_summary',[])
            prior_completed=int(previous.get('completed_exposures',-1))
            if 0<=prior_completed<=len(exposures) and len(prior_summary)==prior_completed:
                candidates=prior_candidates
                summary=prior_summary
                completed_exposures=prior_completed
    try:
        rows=history.records(start,end,MAX_AGE_HOURS,ids)
        grouped_records={int(oid):[] for oid in ids}
        for row in rows:
            grouped_records[row['norad_id']].append(row)
        for chunk_start in range(completed_exposures,len(exposures),CHUNK_TIMES):
            chunk=exposures[chunk_start:chunk_start+CHUNK_TIMES]
            times=[item[0] for item in chunk]
            states,ages,errors,epochs=history.replay(
                ids,times,max_age=MAX_AGE_HOURS,grouped_records=grouped_records)
            for j,(mid,expid,quadrants) in enumerate(chunk):
                state=states[j];age=ages[j];error=errors[j]
                valid=(error==0)&np.isfinite(state).all(axis=1)&(age>=0)&(age<=MAX_AGE_HOURS)
                if not np.any(valid):
                    summary.append({'expid':expid,'utc_midpoint':mid.isoformat(),'fresh_valid_objects':0,'above_10deg_objects':0,'footprint_tracks':0,'sunlit_footprint_tracks':0});continue
                pos=state[valid,:3]
                object_indices=np.flatnonzero(valid)
                instant=Time(mid)
                observer=SITE.get_itrs(obstime=instant).transform_to(TEME(obstime=instant)).cartesian.xyz.to_value(u.km)
                los=pos-observer
                ranges=np.linalg.norm(los,axis=1)
                directions=los/ranges[:,None]
                top=SkyCoord(CartesianRepresentation(directions.T*u.one),frame=TEME(obstime=instant))
                icrs=top.icrs
                alt=top.transform_to(AltAz(obstime=instant,location=SITE,pressure=0*u.hPa)).alt.to_value(u.deg)
                observable=alt>10.0
                sun=get_sun(instant).transform_to(TEME(obstime=instant)).cartesian.xyz.to_value(u.km)
                along=pos@sun;sun2=float(sun@sun)
                perpendicular=np.sqrt(np.maximum(0.0,np.einsum('ij,ij->i',pos,pos)-along*along/sun2))
                sunlit=~((along<0)&(perpendicular<6378.135))
                icrs_units=icrs.cartesian.xyz.to_value(u.one).T
                sky_tree=cKDTree(icrs_units[observable])
                visible_indices=np.flatnonzero(observable)
                ra=icrs.ra.to_value(u.deg);dec=icrs.dec.to_value(u.deg)
                age_valid=age[valid]
                epoch_valid=epochs[j,valid]
                exposure_candidates=[];seen=set()
                prepared=[]
                for q in quadrants:
                    corners=np.asarray([[float(q[f'ra{k}']),float(q[f'dec{k}'])] for k in range(1,5)])
                    center,east,north,polygon,chord_radius=tangent_polygon(corners)
                    prepared.append((q,center,east,north,polygon,chord_radius))
                centers=np.asarray([p[1] for p in prepared]);radii=np.asarray([p[5] for p in prepared])
                broad=sky_tree.query_ball_point(centers,radii)
                for qi,indices in enumerate(broad):
                    if not indices:continue
                    q,center,east,north,polygon,_=prepared[qi]
                    local=np.asarray(indices,dtype=int)
                    original=visible_indices[local]
                    unit=icrs_units[original]
                    den=unit@center
                    xy=np.column_stack(((unit@east)/den,(unit@north)/den))
                    inside=polygon.contains_points(xy,radius=.0003)
                    for local_i in np.flatnonzero(inside):
                        k=int(original[local_i]);sat_index=int(object_indices[k]);norad=int(ids[sat_index])
                        key=(norad,int(q['ccdid']),int(q['qid']))
                        if key in seen:continue
                        seen.add(key)
                        item={'expid':expid,'obsdate_start_utc':q['obsdate'],'exptime_s':float(q['exptime']),
                              'field':int(q['field']),'ccdid':int(q['ccdid']),'qid':int(q['qid']),
                              'filtercode':q['filtercode'],'filefracday':q['filefracday'],'seeing_arcsec':float(q['seeing']),
                              'maglimit':float(q['maglimit']),'norad_id':norad,
                              'tle_epoch_utc':str(epoch_valid[k]),'tle_age_hours_at_midpoint':float(age_valid[k]),
                              'ra_mid_deg':float(ra[k]),'dec_mid_deg':float(dec[k]),
                              'altitude_mid_deg':float(alt[k]),'range_mid_km':float(ranges[k]),
                              'sunlit_midpoint':bool(sunlit[k]),'midpoint_inside_quadrant':True}
                        candidates.append(item);exposure_candidates.append(item)
                summary.append({'expid':expid,'utc_midpoint':mid.isoformat(),
                    'fresh_valid_objects':int(valid.sum()),'above_10deg_objects':int(observable.sum()),
                    'footprint_tracks':len(exposure_candidates),
                    'sunlit_footprint_tracks':sum(x['sunlit_midpoint'] for x in exposure_candidates)})
            completed_exposures=min(chunk_start+len(chunk),len(exposures))
            checkpoint={'status':'partial','run_sha256':run_hash,
                'metadata_sha256':metadata_hash,'catalog_ids_sha256':ids_hash,
                'catalog_ids_considered':len(ids),'completed_exposures':completed_exposures,
                'total_exposures':len(exposures),'candidates':candidates,
                'exposure_summary':summary}
            tmp=partial_path.with_suffix('.json.tmp')
            tmp.write_text(json.dumps(checkpoint,separators=(',',':'))+'\n')
            tmp.replace(partial_path)
            print(f"processed {completed_exposures}/{len(exposures)} exposures; {len(candidates)} midpoint footprint tracks",flush=True)
    finally:
        history.db.close()
    result={'source_metadata_file':str(source.relative_to(ROOT)),'metadata_sha256':metadata_hash,
        'run_sha256':run_hash,'catalog_ids_sha256':ids_hash,
        'metadata_rows':len(rows),'exposures':len(exposures),'first_exposure_midpoint_utc':start.isoformat(),
        'last_exposure_midpoint_utc':end.isoformat(),'catalog_ids_considered':len(ids),
        'site':{'longitude_deg':-116.865,'latitude_deg':33.357,'altitude_km':1.7},
        'orbit_method':'Historical element selection independently as of each exposure midpoint, 72-hour freshness limit, SGP4/WGS-72; topocentric TEME line of sight transformed to ICRS and AltAz; spherical CCD-footprint prefilter and tangent-plane polygon check.',
        'history_query':'The full night and 72-hour lookback were selected once from the annual archive, then replayed in bounded time chunks to avoid rescanning the Parquet source for every chunk.',
        'selection_method':'Every available ZTF CCD-quadrant science footprint at each exposure midpoint, altitude >10 deg. A track crossing between midpoint and exposure edges can be missed and will be screened separately.',
        'limitations':'Catalog-to-frame midpoint opportunities are not target-level sensor attempts. Object brightness, full exposure-time path intersections, independent identity truth, and a planned-observation/nondetection ledger are not represented.',
        'totals':{'candidate_footprint_tracks':len(candidates),'sunlit_candidate_footprint_tracks':sum(x['sunlit_midpoint'] for x in candidates),'exposures_with_midpoint_tracks':sum(x['footprint_tracks']>0 for x in summary)},
        'exposure_summary':summary,'candidates':candidates}
    (OUT/'midpoint_crossing_audit.json').write_text(json.dumps(result,indent=2)+'\n')
    partial_path.unlink(missing_ok=True)
    print(json.dumps(result['totals'],indent=2))

if __name__=='__main__':main()
