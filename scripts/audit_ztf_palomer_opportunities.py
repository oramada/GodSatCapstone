#!/usr/bin/env python3
"""Reproduce a small, image-backed ZTF satellite-opportunity audit at Palomar.

The result is an exploratory catalog-to-image association check. A blank predicted
track is not a hardware dropout label because TLE identity, magnitude, timing and
an attempt/outcome ledger are not available.
"""
from __future__ import annotations
import argparse
import csv
import datetime as dt
import hashlib
import json
import math
import pathlib
import re
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import astropy.units as u
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from astropy.coordinates import (AltAz, CartesianRepresentation, EarthLocation,
                                 SkyCoord, TEME, get_sun)
from astropy.io import fits
from astropy.time import Time
from astropy.wcs import WCS
from scipy.ndimage import map_coordinates
from sgp4.api import SatrecArray

from godsat.orbits import History, julian, satellite, utc

DATA = ROOT / 'data/ground_sensor/ztf_palomer_poc'
IMAGE_DIR = DATA / 'images'
OUT = ROOT / 'outputs/ztf-palomer-opportunity-poc'
# Four deterministic exposures sampled from 182 distinct on-sky exposures in a
# 2h20m public IRSA metadata query; two separate predicted catalog tracks land
# in distinct quadrants of the third exposure.
TARGETS = [
    ("274732031", 2, 4, 19165),
    ("274734733", 8, 4, 26407),
    ("274737422", 4, 3, 32711),
    ("274737422", 7, 4, 39984),
    ("274740114", 4, 1, 15738),
]
IMAGE_REVIEW = {
    19165: 'weak profile excess within 2.5 pixels of predicted path; rendered overlay is ambiguous, so not counted as a confirmed association',
    26407: 'clear elongated image streak follows predicted path at approximately 4-pixel cross-track offset; likely catalog association, without independent NORAD truth',
    32711: 'clear elongated image streak follows predicted path at approximately 4-pixel cross-track offset; likely catalog association, without independent NORAD truth',
    39984: 'predicted in Earth shadow through this exposure; exclude from optically observable opportunities',
    15738: 'no corresponding streak evident in reviewed image; cannot call a miss without calibrated object brightness and time/ephemeris uncertainty',
}
SITE = EarthLocation.from_geodetic(-116.865 * u.deg, 33.357 * u.deg, 1.7 * u.km)
EXPECTED_BYTES = 37_872_000


def parse_obsdate(value: str) -> dt.datetime:
    value = value.replace(' ', 'T')
    value = re.sub(r'\.(\d{1,6})(?=\+00$)', lambda m: '.' + m.group(1).ljust(6, '0'), value)
    value = value.replace('+00', '+00:00')
    return utc(value)


def sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def image_url(row: dict[str, str]) -> str:
    frac = row['filefracday']
    field = int(row['field'])
    ccd = int(row['ccdid'])
    qid = int(row['qid'])
    filename = (f"ztf_{frac}_{field:06d}_{row['filtercode']}_c{ccd:02d}_o_"
                f"q{qid}_sciimg.fits")
    return (f"https://irsa.ipac.caltech.edu/ibe/data/ztf/products/sci/"
            f"{frac[:4]}/{frac[4:8]}/{frac[-6:]}/{filename}")


def dense_track(row: dict, satrec, seconds: float = 0.5) -> dict:
    start = parse_obsdate(row['obsdate'])
    exptime = float(row['exptime'])
    elapsed = np.arange(0.0, exptime + seconds * .25, seconds)
    when = [start + dt.timedelta(seconds=float(s)) for s in elapsed]
    jd_fr = [julian(t) for t in when]
    jd = np.asarray([p[0] for p in jd_fr], dtype='float64')
    fr = np.asarray([p[1] for p in jd_fr], dtype='float64')
    err, pos, _ = SatrecArray([satrec]).sgp4(jd, fr)
    pos = np.asarray(pos)[0]
    err = np.asarray(err)[0]
    times = Time(when)
    site_teme = SITE.get_itrs(obstime=times).transform_to(TEME(obstime=times)).cartesian.xyz.to_value(u.km).T
    los = pos - site_teme
    ranges = np.linalg.norm(los, axis=1)
    directions = los / ranges[:, None]
    topocentric = SkyCoord(CartesianRepresentation(directions.T * u.one), frame=TEME(obstime=times))
    icrs = topocentric.icrs
    alt = topocentric.transform_to(AltAz(obstime=times, location=SITE, pressure=0 * u.hPa)).alt.to_value(u.deg)
    sun_vec = get_sun(times).transform_to(TEME(obstime=times)).cartesian.xyz.to_value(u.km).T
    along = np.einsum('ij,ij->i', pos, sun_vec)
    perpendicular = np.sqrt(np.maximum(0.0, np.einsum('ij,ij->i', pos, pos) - along * along / np.einsum('ij,ij->i', sun_vec, sun_vec)))
    sunlit = ~((along < 0) & (perpendicular < 6378.135))
    return {
        'elapsed_s': elapsed, 'when': when, 'ra': icrs.ra.to_value(u.deg),
        'dec': icrs.dec.to_value(u.deg), 'alt': alt, 'range_km': ranges,
        'valid': (err == 0) & np.isfinite(pos).all(axis=1), 'sunlit': sunlit,
    }


def track_pixels(wcs, track, shape):
    x, y = wcs.world_to_pixel_values(track['ra'], track['dec'])
    h, w = shape
    # Interpolate between 0.5 s propagated samples at 1-pixel intervals and
    # retain detector-interior points, including clipped entry/exit segments.
    px, py = [], []
    for i in range(len(x) - 1):
        if not np.isfinite([x[i], y[i], x[i + 1], y[i + 1]]).all():
            continue
        d = math.hypot(float(x[i + 1] - x[i]), float(y[i + 1] - y[i]))
        n = max(1, int(math.ceil(d)))
        t = np.arange(n, dtype=float) / n
        xs = x[i] + t * (x[i + 1] - x[i])
        ys = y[i] + t * (y[i + 1] - y[i])
        keep = (xs >= 14) & (xs < w - 14) & (ys >= 14) & (ys < h - 14)
        px.extend(xs[keep]); py.extend(ys[keep])
    x = np.where(track['valid'], x, np.nan); y = np.where(track['valid'], y, np.nan)
    return np.asarray(px), np.asarray(py), x, y


def pixel_profile(image, x, y):
    h, w = image.shape
    safe = (x >= 75) & (x < w - 75) & (y >= 75) & (y < h - 75)
    x, y = x[safe], y[safe]
    if len(x) < 30:
        return {'samples': int(len(x)), 'centerline_median_excess_adu': None,
                'best_shift_px': None, 'best_median_excess_adu': None,
                'best_positive_fraction': None, 'offset_scan_half_range_px': 15}
    dx, dy = float(np.median(np.diff(x))), float(np.median(np.diff(y)))
    norm = math.hypot(dx, dy)
    # A degenerate/curved track can make median consecutive displacement tiny;
    # use endpoint direction as the stable local normal in that case.
    if norm < 1e-6:
        dx, dy = float(x[-1] - x[0]), float(y[-1] - y[0]); norm = math.hypot(dx, dy)
    nx, ny = -dy / norm, dx / norm
    offsets = np.arange(-15.0, 15.01, .5)
    controls = np.stack([map_coordinates(image, [y + ny * off, x + nx * off], order=1, mode='nearest')
                         for off in (-55, -45, 45, 55)])
    background = np.median(controls, axis=0)
    profile = []
    for shift in offsets:
        core = np.stack([map_coordinates(image, [y + ny * (shift + off),
                                                x + nx * (shift + off)],
                                         order=1, mode='nearest')
                         for off in (-1.0, 0.0, 1.0)]).mean(axis=0)
        profile.append(core - background)
    profile = np.asarray(profile)
    medians = np.median(profile, axis=1)
    best = int(np.argmax(medians))
    center = int(np.argmin(np.abs(offsets)))
    return {'samples': int(len(x)),
            'centerline_median_excess_adu': float(medians[center]),
            'best_shift_px': float(offsets[best]),
            'best_median_excess_adu': float(medians[best]),
            'best_positive_fraction': float(np.mean(profile[best] > 0)),
            'offset_scan_half_range_px': 15,
            'offset_scan_step_px': .5,
            'offset_profile': [{'shift_px': float(shift),
                                'median_excess_adu': float(medians[i]),
                                'positive_fraction': float(np.mean(profile[i] > 0))}
                               for i, shift in enumerate(offsets)]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--download-missing', action='store_true', help='download only these five explicitly selected public science images')
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True); IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    metadata = list(csv.DictReader((DATA / 'ztf_metadata_2024-07-10.csv').open()))
    exposure_rows = {}
    for r in metadata:
        exposure_rows.setdefault(r['expid'], []).append(r)
    chosen = []
    for expid, ccd, qid, norad in TARGETS:
        match = next(r for r in exposure_rows[expid] if int(r['ccdid']) == ccd and int(r['qid']) == qid)
        chosen.append((match, norad))
    obs_times = [parse_obsdate(r['obsdate']) for r, _ in chosen]
    history_start = min(obs_times)
    history_end = max(obs_times) + dt.timedelta(seconds=30)
    history = History(cohort='all', window=(history_start, history_end), max_age_hours=72)
    rows = history.snapshot(history_start, max_age=72)
    by_id = {int(r['norad_id']): r for r in rows}
    results = []
    for source_row, norad in chosen:
        item = dict(source_row)
        tle = by_id[norad]
        satrec = satellite(tle)
        track = dense_track(source_row, satrec)
        path = IMAGE_DIR / pathlib.Path(image_url(source_row)).name
        url = image_url(source_row)
        if not path.exists() and args.download_missing:
            urllib.request.urlretrieve(url, path)
        if not path.exists():
            raise FileNotFoundError(f"Missing image {path}; rerun with --download-missing")
        if path.stat().st_size != EXPECTED_BYTES:
            raise ValueError(f"Image size mismatch for {path}: {path.stat().st_size} != {EXPECTED_BYTES}")
        with fits.open(path, memmap=True) as hdus:
            hdu = next(h for h in hdus if h.data is not None and h.data.ndim == 2)
            image = np.asarray(hdu.data, dtype=np.float32)
            wcs = WCS(hdu.header)
            x, y, sample_x, sample_y = track_pixels(wcs, track, image.shape)
            profile = pixel_profile(image, x, y)
            global_med = float(np.median(image))
            global_sigma = float(1.4826 * np.median(np.abs(image - global_med)))
            entry = np.where((sample_x >= 0) & (sample_x < image.shape[1]) &
                             (sample_y >= 0) & (sample_y < image.shape[0]))[0]
            entry_fraction = len(entry) / len(sample_x)
            item.update({
                'norad_id': norad, 'tle_epoch_utc': utc(tle['epoch']).isoformat(),
                'tle_source_year_file': f"data/raw/tle_{utc(tle['epoch']).year}.parquet",
                'tle_elements': {k: tle[k] for k in ('inclination', 'raan', 'eccentricity',
                    'arg_perigee', 'mean_anomaly', 'mean_motion', 'mean_motion_dot', 'bstar')},
                'tle_age_at_midpoint_hours': (obs_times[TARGETS.index((str(source_row['expid']), int(source_row['ccdid']), int(source_row['qid']), norad))] - utc(tle['epoch'])).total_seconds() / 3600 + float(source_row['exptime']) / 7200,
                'predicted_altitude_midpoint_deg': float(np.interp(float(source_row['exptime']) / 2, track['elapsed_s'], track['alt'])),
                'predicted_range_midpoint_km': float(np.interp(float(source_row['exptime']) / 2, track['elapsed_s'], track['range_km'])),
                'predicted_track_valid_fraction': float(np.mean(track['valid'])),
                'predicted_track_sunlit_fraction': float(np.mean(track['sunlit'])),
                'predicted_track_detector_fraction': float(entry_fraction),
                'predicted_track_detector_pixels': int(len(x)),
                'pixel_profile_vs_parallel_controls': profile,
                'manual_image_review': IMAGE_REVIEW[norad],
                'image_global_robust_sigma_adu': global_sigma,
                'peak_profile_excess_over_global_robust_sigma': (
                    profile['best_median_excess_adu'] / global_sigma
                    if profile['best_median_excess_adu'] is not None and global_sigma > 0 else None),
                'image_path': str(path.relative_to(ROOT)), 'image_sha256': sha256(path),
                'image_url': url, 'fits_filter': hdu.header.get('FILTER'),
                'fits_ccdid': hdu.header.get('CCDID'), 'fits_qid': hdu.header.get('QID'),
                'fits_exptime_s': hdu.header.get('EXPTIME'),
            })
            if len(x):
                # Save image overlays so candidates can be reviewed against recorded pixels.
                    pad = 40; x0=max(0,int(x.min()-pad)); x1=min(image.shape[1],int(x.max()+pad)); y0=max(0,int(y.min()-pad)); y1=min(image.shape[0],int(y.max()+pad))
                    crop=image[y0:y1,x0:x1]; lo,hi=np.percentile(crop,[2,99.7])
                    fig,ax=plt.subplots(figsize=(8,8)); ax.imshow(crop,origin='lower',cmap='gray',vmin=lo,vmax=hi,interpolation='nearest'); ax.plot(x-x0,y-y0,color='red',lw=.7)
                    ax.set_title(f'ZTF exposure {source_row["expid"]}, CCD {source_row["ccdid"]} q{source_row["qid"]}\nred: predicted NORAD {norad} SGP4 track during 30 s'); ax.set_xlabel('pixel x'); ax.set_ylabel('pixel y'); fig.tight_layout()
                    fig.savefig(OUT/f'track_{norad}_{source_row["expid"]}.png',dpi=160); plt.close(fig)
        results.append(item)
    query = {
        'metadata_source': 'IRSA ZTF public science-exposure metadata API',
        'metadata_query': 'obsjd > 2460501.82 AND obsjd < 2460501.92 AND infobits < 33554432; on-sky object science images; 2024-07-10; 182 distinct exposure IDs in 2h24m sample',
        'metadata_file': str((DATA / 'ztf_metadata_2024-07-10.csv').relative_to(ROOT)),
        'metadata_sha256': sha256(DATA / 'ztf_metadata_2024-07-10.csv'),
        'selection': 'Deterministic every-50th exposure from query order, then all selected full-catalog SGP4 paths whose midpoint fell in a CCD quadrant and above 10 deg at Palomar; five candidate tracks across four exposure IDs.',
        'site': {'longitude_deg': -116.865, 'latitude_deg': 33.357, 'altitude_km': 1.7},
        'orbital_source': 'Local archived historical TLE parquet; one common freshest snapshot at earliest selected exposure time; SGP4/WGS-72; 72 h age cutoff.',
        'image_method': 'Official ZTF quadrant science FITS; WCS-transformed 0.5 s SGP4 path; compare a 3-pixel-wide path core to parallel controls while scanning cross-track offsets within +/-15 pixels. Descriptive image association only; no calibrated magnitude model or detection threshold.',
        'interpretation_limit': 'Track-offset scan and visual overlays are exploratory. Catalog association is plausible rather than independently truth-labeled; satellite magnitudes and per-object detection thresholds are unavailable. A blank path is not a confirmed missed attempt or hardware dropout, and this four-exposure subsample is not an attempted-target ledger.',
        'candidates': results,
    }
    output = OUT / 'audit.json'
    output.write_text(json.dumps(query, indent=2) + '\n')
    print(json.dumps({'output': str(output.relative_to(ROOT)), 'candidate_tracks': len(results),
                      'exposure_ids': len({r['expid'] for r in results}),
                      'detector_fractions': [r['predicted_track_detector_fraction'] for r in results]}, indent=2))

if __name__ == '__main__':
    main()
