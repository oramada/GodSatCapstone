#!/usr/bin/env python3
"""Download and profile a deterministic, time-spread sample of ZTF opportunities."""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import hashlib
import json
import pathlib
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'scripts'))

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from astropy.io import fits
from astropy.wcs import WCS

from audit_ztf_palomer_opportunities import (DATA, IMAGE_DIR, OUT, EXPECTED_BYTES,
    dense_track, image_url, parse_obsdate, pixel_profile, sha256, track_pixels)
from godsat.orbits import History, satellite, utc

FULL=ROOT/'outputs/ztf-palomer-fullnight-2024-07-10'
MAX_AGE_HOURS=72.0


def choose_image_groups(midpoint,path_audit,edge_audit,metadata,max_images,min_separation_minutes):
    path_by_key={(r['expid'],int(r['ccdid']),int(r['qid']),int(r['norad_id'])):r
                 for r in path_audit['candidates']}
    candidates=[]
    for row in midpoint['candidates']:
        key=(row['expid'],int(row['ccdid']),int(row['qid']),int(row['norad_id']))
        result=path_by_key[key]
        if result.get('any_path_sunlit_observable_inside'):
            candidates.append({**row,'path_source':'midpoint_candidate',
                               'sunlit_observable_crossing':True})
    candidates.extend({**r,'path_source':'midpoint_outside_edge_candidate'}
                      for r in edge_audit['candidates'] if r.get('sunlit_observable_crossing'))
    by_image=collections.defaultdict(list)
    for row in candidates:
        key=(str(row['expid']),int(row['ccdid']),int(row['qid']))
        by_image[key].append(row)
    metadata_by_key={(str(r['expid']),int(r['ccdid']),int(r['qid'])):r for r in metadata}
    ranked=[]
    for key,rows in by_image.items():
        source=metadata_by_key[key]
        ranked.append((len(rows),parse_obsdate(source['obsdate']),key,source,rows))
    ranked.sort(key=lambda x:(-x[0],x[1],x[2]))
    selected=[]
    separation=dt.timedelta(minutes=min_separation_minutes)
    for item in ranked:
        if all(abs(item[1]-prior[1])>=separation for prior in selected):
            selected.append(item)
            if len(selected)>=max_images:
                break
    return candidates,selected


def file_sha256(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()


def download_image(source_row,path):
    if path.exists() and path.stat().st_size==EXPECTED_BYTES:
        return
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.download')
    if temp.exists() and temp.stat().st_size==EXPECTED_BYTES:
        temp.replace(path)
        return
    url=image_url(source_row)
    for attempt in range(6):
        offset=temp.stat().st_size if temp.exists() else 0
        headers={'User-Agent':'GoDSAT research audit'}
        if offset:headers['Range']=f'bytes={offset}-'
        request=urllib.request.Request(url,headers=headers)
        try:
            with urllib.request.urlopen(request,timeout=180) as response:
                append=offset>0 and response.status==206
                if offset and not append:
                    offset=0
                with temp.open('ab' if append else 'wb') as target:
                    while True:
                        block=response.read(1024*1024)
                        if not block:break
                        target.write(block)
            if temp.stat().st_size==EXPECTED_BYTES:break
            if temp.stat().st_size>EXPECTED_BYTES:
                temp.unlink();raise ValueError(f'Unexpected oversized FITS transfer for {path.name}')
        except (OSError,TimeoutError):
            if attempt==5:raise
            time.sleep(min(2**attempt,20))
    else:
        raise ConnectionError(f'Incomplete FITS transfer for {path.name}: {temp.stat().st_size} bytes')
    if temp.stat().st_size!=EXPECTED_BYTES:
        temp.unlink(missing_ok=True)
        raise ValueError(f'Unexpected FITS size for {path.name}: {temp.stat().st_size}')
    temp.replace(path)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--max-images',type=int,default=12)
    parser.add_argument('--minimum-separation-minutes',type=float,default=15.0)
    parser.add_argument('--no-download',action='store_true')
    parser.add_argument('--output',type=pathlib.Path,default=FULL/'image_sample_audit.json')
    args=parser.parse_args()
    midpoint=json.loads((FULL/'midpoint_crossing_audit.json').read_text())
    paths=json.loads((FULL/'exposure_path_audit.json').read_text())
    edges=json.loads((FULL/'edge_crossing_audit.json').read_text())
    metadata=list(csv.DictReader((DATA/'ztf_metadata_2024-07-10_fullnight.csv').open(newline='')))
    candidates,selected=choose_image_groups(midpoint,paths,edges,metadata,
        args.max_images,args.minimum_separation_minutes)
    selected_keys={item[2] for item in selected}
    selected_candidates=[r for r in candidates if
        (str(r['expid']),int(r['ccdid']),int(r['qid'])) in selected_keys]
    selected_images=[(item[3],IMAGE_DIR/pathlib.Path(image_url(item[3])).name) for item in selected]
    if not args.no_download:
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda pair:download_image(pair[0],pair[1]),selected_images))
    object_ids=sorted({int(r['norad_id']) for r in selected_candidates})
    starts=[item[1] for item in selected]
    ends=[item[1]+dt.timedelta(seconds=float(item[3]['exptime'])) for item in selected]
    history=History(cohort='all',window=(min(starts),max(ends)),max_age_hours=MAX_AGE_HOURS)
    try:
        records=history.records(min(starts),max(ends),MAX_AGE_HOURS,object_ids)
        grouped=collections.defaultdict(list)
        for row in records:grouped[int(row['norad_id'])].append(row)
        image_results=[]
        for score,mid,group_key,source_row,rows in selected:
            expid,ccdid,qid=group_key
            image_path=IMAGE_DIR/pathlib.Path(image_url(source_row)).name
            if args.no_download and not image_path.is_file():
                image_results.append({'expid':expid,'ccdid':ccdid,'qid':qid,
                    'status':'image_not_downloaded','candidate_count':len(rows),
                    'image_url':image_url(source_row)})
                continue
            if not args.no_download:
                download_image(source_row,image_path)
            item_results=[]
            with fits.open(image_path,memmap=True) as hdus:
                hdu=next(h for h in hdus if h.data is not None and h.data.ndim==2)
                image=np.asarray(hdu.data,dtype=np.float32)
                global_median=float(np.median(image))
                global_sigma=float(1.4826*np.median(np.abs(image-global_median)))
                wcs=WCS(hdu.header)
                start=parse_obsdate(source_row['obsdate'])
                midpoint_time=start+dt.timedelta(seconds=float(source_row['exptime'])/2)
                for candidate in rows:
                    norad=int(candidate['norad_id'])
                    selected_tle=None
                    for tle in grouped.get(norad,[]):
                        if tle['epoch']<=midpoint_time:selected_tle=tle
                        else:break
                    if selected_tle is None or utc(selected_tle['epoch']).isoformat()!=candidate['tle_epoch_utc']:
                        raise ValueError(f'Historical element mismatch for {expid}/{ccdid}/{qid}/{norad}')
                    track=dense_track(source_row,satellite(selected_tle))
                    x,y,sample_x,sample_y=track_pixels(wcs,track,image.shape)
                    profile=pixel_profile(image,x,y)
                    near_predicted=[point for point in profile.get('offset_profile',[])
                                    if abs(point['shift_px'])<=5.0]
                    near_peak=max(near_predicted,key=lambda point:point['median_excess_adu']) if near_predicted else None
                    detector=(np.isfinite(sample_x)&np.isfinite(sample_y)&
                        (sample_x>=0)&(sample_x<image.shape[1])&
                        (sample_y>=0)&(sample_y<image.shape[0]))
                    finite=np.isfinite(x)&np.isfinite(y)&(x>=0)&(x<image.shape[1])&(y>=0)&(y<image.shape[0])
                    overlay_path=FULL/'image_profiles'/f'track_{norad}_{expid}_c{ccdid}_q{qid}.png'
                    if finite.any():
                        px=x[finite];py=y[finite];padding=40
                        x0=max(0,int(px.min()-padding));x1=min(image.shape[1],int(px.max()+padding+1))
                        y0=max(0,int(py.min()-padding));y1=min(image.shape[0],int(py.max()+padding+1))
                        crop=image[y0:y1,x0:x1]
                        low,high=np.percentile(crop,[2,99.7])
                        fig,ax=plt.subplots(figsize=(7,7))
                        ax.imshow(crop,origin='lower',cmap='gray',vmin=low,vmax=high,interpolation='nearest')
                        ax.plot(px-x0,py-y0,color='red',lw=.8)
                        ax.set_title(f'Exp {expid}, CCD {ccdid} q{qid}: NORAD {norad} predicted path')
                        ax.set_xlabel('pixel x');ax.set_ylabel('pixel y');fig.tight_layout()
                        overlay_path.parent.mkdir(parents=True,exist_ok=True)
                        fig.savefig(overlay_path,dpi=140);plt.close(fig)
                    item_results.append({
                        'expid':expid,'ccdid':ccdid,'qid':qid,'norad_id':norad,
                        'path_source':candidate['path_source'],
                        'tle_epoch_utc':candidate['tle_epoch_utc'],
                        'tle_age_hours_at_midpoint':candidate['tle_age_hours_at_midpoint'],
                        'maglimit':candidate.get('maglimit',source_row.get('maglimit')),
                        'seeing_arcsec':candidate.get('seeing_arcsec',source_row.get('seeing')),
                        'sunlit_observable_crossing':True,
                        'samples_in_detector':int(detector.sum()),
                        'detector_sample_fraction':float(detector.mean()) if len(detector) else 0.0,
                        'global_robust_sigma_adu':global_sigma,
                        'profile_peak_within_5px_adu':near_peak['median_excess_adu'] if near_peak else None,
                        'profile_peak_within_5px_offset_px':near_peak['shift_px'] if near_peak else None,
                        'profile_peak_within_5px_over_global_sigma':(near_peak['median_excess_adu']/global_sigma
                            if near_peak and global_sigma>0 else None),
                        'overlay_path':str(overlay_path.relative_to(ROOT)) if finite.any() else None,
                        'pixel_profile_vs_parallel_controls':profile,
                        'image_level_assessment':'unreviewed_profile_measurement',
                    })
            image_results.append({
                'expid':expid,'ccdid':ccdid,'qid':qid,'candidate_count':len(rows),
                'candidate_count_edge_only':sum(r['path_source']=='midpoint_outside_edge_candidate' for r in rows),
                'obsdate_start_utc':source_row['obsdate'],'exptime_s':float(source_row['exptime']),
                'filtercode':source_row['filtercode'],'maglimit':float(source_row['maglimit']),
                'seeing_arcsec':float(source_row['seeing']),'image_path':str(image_path.relative_to(ROOT)),
                'global_robust_sigma_adu':global_sigma,
                'image_bytes':image_path.stat().st_size,'image_sha256':file_sha256(image_path),
                'image_url':image_url(source_row),'candidate_results':item_results,
            })
        output={
            'status':'completed_profile_audit' if all(r.get('candidate_results') for r in image_results) else 'incomplete_image_downloads',
            'metadata_sha256':midpoint['metadata_sha256'],
            'midpoint_audit_sha256':hashlib.sha256((FULL/'midpoint_crossing_audit.json').read_bytes()).hexdigest(),
            'exposure_path_audit_sha256':hashlib.sha256((FULL/'exposure_path_audit.json').read_bytes()).hexdigest(),
            'edge_crossing_audit_sha256':hashlib.sha256((FULL/'edge_crossing_audit.json').read_bytes()).hexdigest(),
            'selection_method':'Rank CCD-quadrant science images by count of catalog tracks with predicted sunlit, >10-degree full-exposure intersection; greedily require the configured time separation; include all such tracks in each selected image.',
            'images_requested':args.max_images,'minimum_separation_minutes':args.minimum_separation_minutes,
            'images_completed':sum(bool(r.get('candidate_results')) for r in image_results),
            'opportunity_count':len(selected_candidates),'image_results':image_results,
            'interpretation_limit':'Profile measurements are image-level signal evidence only. They are not blinded independently truth-labeled detections, and the sample is selected on predicted catalog opportunities rather than a planned sensor attempt list. Do not report hardware dropout effectiveness from this audit.',
        }
        args.output.parent.mkdir(parents=True,exist_ok=True)
        temp=args.output.with_suffix(args.output.suffix+'.tmp')
        temp.write_text(json.dumps(output,indent=2)+'\n');temp.replace(args.output)
        print(json.dumps({'output':str(args.output),'status':output['status'],
            'images_completed':output['images_completed'],'images_requested':args.max_images,
            'opportunities':output['opportunity_count'],
            'image_ids':[f"{r['expid']}/c{r['ccdid']}q{r['qid']}" for r in image_results]},indent=2))
    finally:
        history.db.close()


if __name__=='__main__':main()
