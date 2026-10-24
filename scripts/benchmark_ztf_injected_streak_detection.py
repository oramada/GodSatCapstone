#!/usr/bin/env python3
"""Measure path-profile sensitivity using held-out, photometrically scaled ZTF injections."""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys
import datetime as dt

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'scripts'))

import numpy as np
from astropy.io import fits
from astropy.wcs import WCS

from audit_ztf_palomer_opportunities import dense_track,parse_obsdate,pixel_profile,track_pixels

FULL=ROOT/'outputs/ztf-palomer-fullnight-2024-07-10'
SAMPLE=FULL/'image_sample_audit.json'
MAG_OFFSETS=(-8.0,-7.0,-6.0,-5.0,-4.0,-3.0,-2.0,-1.0,0.0,1.0)
CONTROL_QUANTILES=(0.90,0.95,0.99)
MAX_TLE_AGE_HOURS=72.0


def sha256(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()


def profile_score(profile):
    offsets=profile.get('offset_profile',[])
    matched=[row['median_excess_adu'] for row in offsets if abs(row['shift_px'])<=5]
    return max(matched) if matched else None


def control_scores(profile):
    offsets=profile.get('offset_profile',[])
    values={row['shift_px']:row['median_excess_adu'] for row in offsets}
    if not all(shift in values for shift in range(-15,16)):
        return []
    return [max(values[shift] for shift in range(8,16)),
            max(values[shift] for shift in range(-15,-7))]


def translated_path(px,py,image_shape,distance_px=20.0):
    if len(px)<2:return None
    dx=np.gradient(px);dy=np.gradient(py)
    norm=np.hypot(dx,dy)
    good=norm>1e-8
    if good.sum()<30:return None
    nx=np.zeros_like(dx);ny=np.zeros_like(dy)
    nx[good]=-dy[good]/norm[good];ny[good]=dx[good]/norm[good]
    height,width=image_shape
    options=[]
    for sign in (-1.0,1.0):
        x=px+sign*distance_px*nx;y=py+sign*distance_px*ny
        inside=(x>=75)&(x<width-75)&(y>=75)&(y<height-75)
        options.append((int(inside.sum()),x,y,inside))
    count,x,y,inside=max(options,key=lambda item:item[0])
    if count<30:return None
    return x[inside],y[inside],int(np.sign(np.nanmedian((x-px)*nx))) or 1


def inject_gaussian_trail(image,track,wcs,header,source_magnitude,exposure_seconds,rng,
                          cross_track_offset_px=0.0):
    """Add one rate-scaled Gaussian-PSF trail, respecting sunlight and detector dwell."""
    required=('MAGZP','SEEING','PIXSCALE','GAIN')
    missing=[key for key in required if header.get(key) is None]
    if missing:raise ValueError(f'Missing image calibration keywords: {missing}')
    x,y=wcs.world_to_pixel_values(track['ra'],track['dec'])
    x=np.asarray(x);y=np.asarray(y)
    if cross_track_offset_px:
        dx=np.gradient(x);dy=np.gradient(y);norm=np.hypot(dx,dy);good=norm>1e-8
        nx=np.zeros_like(dx);ny=np.zeros_like(dy)
        nx[good]=-dy[good]/norm[good];ny[good]=dx[good]/norm[good]
        x=x+cross_track_offset_px*nx;y=y+cross_track_offset_px*ny
    height,width=image.shape
    time_ok=(np.asarray(track['valid'])&np.asarray(track['sunlit'])&
             (np.asarray(track['alt'])>10.0)&np.isfinite(x)&np.isfinite(y)&
             (x>=0)&(x<width)&(y>=0)&(y<height))
    if time_ok.sum()<2:return None
    elapsed=np.asarray(track['elapsed_s'],dtype=float)
    sample_weights=np.empty_like(elapsed)
    sample_weights[0]=(elapsed[1]-elapsed[0])/2
    sample_weights[-1]=(elapsed[-1]-elapsed[-2])/2
    sample_weights[1:-1]=(elapsed[2:]-elapsed[:-2])/2
    sample_weights/=float(exposure_seconds)
    sample_weights*=time_ok
    dwell_fraction=float(sample_weights.sum())
    if dwell_fraction<=0:return None
    total_flux=10**((float(header['MAGZP'])-float(source_magnitude))/2.5)
    psf_sigma=float(header['SEEING'])/float(header['PIXSCALE'])/2.354820045
    radius=max(2,int(np.ceil(4*psf_sigma)))
    grid=np.arange(-radius,radius+1)
    gy,gx=np.meshgrid(grid,grid,indexing='ij')
    injected=np.zeros(image.shape,dtype=np.float32)
    for index in np.flatnonzero(time_ok):
        ix=int(np.floor(x[index]));iy=int(np.floor(y[index]))
        center_dx=float(x[index]-ix);center_dy=float(y[index]-iy)
        shifted_kernel=np.exp(-((gx-center_dx)**2+(gy-center_dy)**2)/(2*psf_sigma*psf_sigma))
        shifted_kernel/=shifted_kernel.sum()
        x0=ix-radius;y0=iy-radius;x1=ix+radius+1;y1=iy+radius+1
        kx0=max(0,-x0);ky0=max(0,-y0);kx1=len(grid)-max(0,x1-width);ky1=len(grid)-max(0,y1-height)
        sx0=max(0,x0);sy0=max(0,y0);sx1=min(width,x1);sy1=min(height,y1)
        if sx0>=sx1 or sy0>=sy1:continue
        weight=float(sample_weights[index])
        injected[sy0:sy1,sx0:sx1]+=np.float32(total_flux*weight)*shifted_kernel[ky0:ky1,kx0:kx1]
    gain=float(header['GAIN'])
    # Photon noise from the injected signal; the original CCD noise remains in the real image.
    expected_electrons=np.maximum(injected,0)*gain
    shot_noise=(rng.poisson(expected_electrons).astype(np.float32)-expected_electrons)/gain
    saturated=np.minimum(image+injected+shot_noise,float(header.get('SATURATE',np.inf)))
    return saturated,{
        'source_magnitude':float(source_magnitude),'zero_point_mag':float(header['MAGZP']),
        'injected_total_dn_if_visible_for_full_exposure':float(total_flux),
        'sunlit_above_10deg_detector_dwell_fraction':dwell_fraction,
        'injected_dn_after_dwell':float(total_flux*dwell_fraction),
        'gaussian_psf_sigma_px':psf_sigma,'gain_electron_per_dn':gain,
        'saturation_dn':float(header.get('SATURATE',np.inf)),
    }


def main():
    sample=json.loads(SAMPLE.read_text())
    if sample.get('status')!='completed_profile_audit':
        raise ValueError('A completed source-linked image profile sample is required')
    ordered=sorted(sample['image_results'],key=lambda row:row['obsdate_start_utc'])
    if len(ordered)<6:raise ValueError('Need at least six images for a time-held-out benchmark')
    if len(ordered)<6:raise ValueError('Need at least six images for an image-held-out benchmark')
    rng=np.random.default_rng(20261010)
    image_trials=[]
    no_injection_scores={str(q):[] for q in CONTROL_QUANTILES}
    thresholds_by_exposure={}
    training_count_totals=[]
    for image_row in ordered:
        training=[row for row in ordered if row['expid']!=image_row['expid']]
        training_ids={str(row['expid']) for row in training}
        if str(image_row['expid']) in training_ids:raise ValueError('Image-level train/test leakage')
        all_null=[]
        for train_image in training:
            for candidate in train_image['candidate_results']:
                sigma=float(candidate['global_robust_sigma_adu'])
                if sigma<=0:continue
                all_null.extend(value/sigma for value in control_scores(
                    candidate['pixel_profile_vs_parallel_controls']))
        if len(all_null)<20:raise ValueError('Insufficient training off-path controls')
        thresholds={str(q):float(np.quantile(all_null,q)) for q in CONTROL_QUANTILES}
        thresholds_by_exposure[str(image_row['expid'])]=thresholds
        training_count_totals.append(len(all_null))
        image_path=ROOT/image_row['image_path']
        if sha256(image_path)!=image_row['image_sha256']:
            raise ValueError(f'Image checksum mismatch: {image_row["image_path"]}')
        image_candidates=[]
        with fits.open(image_path,memmap=True) as hdus:
            hdu=next(h for h in hdus if h.data is not None and h.data.ndim==2)
            image=np.asarray(hdu.data,dtype=np.float32)
            wcs=WCS(hdu.header)
            for item in image_row['candidate_results']:
                # Recover exactly the historical element used for this opportunity from
                # the already-integrated profile source row; the audit stores its element epoch.
                from godsat.orbits import History,satellite,utc
                exposure=parse_obsdate(image_row['obsdate_start_utc'])
                exposure_end=exposure+dt.timedelta(seconds=image_row['exptime_s'])
                history=History(cohort='all',window=(exposure,exposure_end),
                                max_age_hours=MAX_TLE_AGE_HOURS)
                try:
                    records=history.records(exposure,exposure_end,
                                            MAX_TLE_AGE_HOURS,[int(item['norad_id'])])
                finally:
                    history.db.close()
                source_tle=next((row for row in records if utc(row['epoch']).isoformat()==item['tle_epoch_utc']),None)
                if source_tle is None:raise ValueError(f'Historical TLE is missing for {item["norad_id"]}')
                track=dense_track({**image_row,'obsdate':image_row['obsdate_start_utc'],
                                   'exptime':image_row['exptime_s']},
                                  satellite(source_tle),seconds=0.1)
                px,py,_,_=track_pixels(wcs,track,image.shape)
                translated=translated_path(px,py,image.shape)
                if translated is None:
                    image_candidates.append({'norad_id':item['norad_id'],'status':'insufficient_heldout_track_pixels'})
                    continue
                test_x,test_y,sign=translated
                baseline_profile=pixel_profile(image,test_x,test_y)
                baseline=profile_score(baseline_profile)
                sigma=float(image_row['global_robust_sigma_adu'])
                if baseline is not None:
                    for q,threshold in thresholds.items():
                        no_injection_scores[q].append(baseline/sigma>=threshold)
                track_result={'norad_id':item['norad_id'],'path_source':item['path_source'],
                    'profile_shift_px':20.0*sign,'no_injection_score_adu':baseline,
                    'no_injection_score_over_global_sigma':baseline/sigma if baseline is not None else None,
                    'training_null_thresholds':thresholds,
                    'injection_trials':[]}
                for offset in MAG_OFFSETS:
                    magnitude=float(image_row['maglimit'])+offset
                    injected,details=inject_gaussian_trail(image,track,wcs,hdu.header,
                        magnitude,float(image_row['exptime_s']),rng,
                        cross_track_offset_px=20.0*sign)
                    if injected is None:
                        track_result['injection_trials'].append({'maglimit_offset':offset,'status':'no_optically_visible_detector_dwell'})
                        continue
                    profile=pixel_profile(injected,test_x,test_y)
                    score=profile_score(profile)
                    normalized=score/sigma if score is not None and sigma>0 else None
                    track_result['injection_trials'].append({
                        'maglimit_offset':offset,'score_adu':score,
                        'score_over_global_sigma':normalized,
                        'above_training_thresholds':{q:(normalized>=threshold if normalized is not None else False)
                            for q,threshold in thresholds.items()},
                        'injection':details,
                    })
                image_candidates.append(track_result)
        image_trials.append({'expid':image_row['expid'],'ccdid':image_row['ccdid'],
            'qid':image_row['qid'],'obsdate_start_utc':image_row['obsdate_start_utc'],
            'image_sha256':image_row['image_sha256'],'maglimit':image_row['maglimit'],
            'seeing_arcsec':image_row['seeing_arcsec'],'training_exposure_ids':sorted(training_ids),
            'training_null_thresholds':thresholds,'training_off_path_control_count':len(all_null),
            'candidate_results':image_candidates})
    summary=[]
    for offset in MAG_OFFSETS:
        trials=[trial for image in image_trials for candidate in image['candidate_results']
            for trial in candidate.get('injection_trials',[]) if trial.get('maglimit_offset')==offset
            and trial.get('score_over_global_sigma') is not None]
        summary.append({'maglimit_offset':offset,'trials':len(trials),
            'detection_fraction_at_training_null_quantile':{
                q:sum(trial['above_training_thresholds'][q] for trial in trials)/len(trials)
                if trials else None for q in thresholds},
            'median_score_over_global_sigma':float(np.median([t['score_over_global_sigma'] for t in trials])) if trials else None})
    result={
        'status':'completed_image_level_injection_benchmark',
        'image_sample_sha256':sha256(SAMPLE),
        'selection_and_split':{
            'images':len(ordered),'heldout_predictions':len(ordered),
            'split_rule':'leave-one-exposure-out: for each image, empirical off-path thresholds are computed only from the other selected images',
        },
        'injection_model':{
            'calibration':'Total DN = 10**((FITS MAGZP - injected magnitude)/2.5), scaled by the sampled fraction of exposure time that is valid, sunlit, above 10 degrees, and inside the CCD quadrant.',
            'psf':'Circular Gaussian with sigma from FITS SEEING/PIXSCALE/2.35482; Poisson shot noise from FITS GAIN; original image background and detector noise retained.',
            'magnitude_offsets_from_image_maglimit':list(MAG_OFFSETS),
            'profile_statistic':'Maximum 3-pixel-core median excess over parallel controls for cross-track offsets within +/-5 pixels; normalized by image global robust pixel sigma.',
            'thresholds_by_heldout_exposure':thresholds_by_exposure,
            'training_off_path_controls_min_max':[min(training_count_totals),max(training_count_totals)],
            'heldout_no_injection_control_scores':len(next(iter(no_injection_scores.values()))),
        },
        'summary_by_magnitude':summary,'heldout_image_results':image_trials,
        'heldout_no_injection_control_false_alarm_fraction':{
            q:sum(flags)/len(flags) if flags else None for q,flags in no_injection_scores.items()},
        'interpretation_limit':'This is a controlled artificial-trail sensitivity test of the pixel-profile algorithm on held-out ZTF frames. It is not a satellite brightness model or independent truth label, and it does not measure natural satellite detection probability, observing-attempt completion, or hardware dropout effectiveness.',
    }
    output=FULL/'injected_streak_detection_benchmark.json'
    output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'output':str(output),'heldout_images':len(ordered),
        'no_injection_control_false_alarm_fraction':result['heldout_no_injection_control_false_alarm_fraction'],
        'summary_by_magnitude':summary},indent=2))


if __name__=='__main__':main()
