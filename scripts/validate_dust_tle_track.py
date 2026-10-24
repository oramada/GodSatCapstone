#!/usr/bin/env python3
"""Test whether one DUST annotated RSO track matches a historical TLE orbit.

Shortlist fresh catalog directions on the first frame, fit object identity on
the first few observations, and score the remaining frames as temporal
holdouts. DUST does not provide NORAD IDs, so this is a candidate association,
not truth-label validation.
"""
import argparse
import csv
import datetime as dt
import io
import json
import pathlib
import zipfile

import h5py
import numpy as np
import astropy.units as u
from astropy.coordinates import EarthLocation, SkyCoord, TEME
from astropy.io import fits
from astropy.time import Time
from astropy.wcs import WCS
from sgp4.api import SatrecArray

from godsat.orbits import History, julian, satellite

ROOT = pathlib.Path(__file__).resolve().parents[1]
DUST_ZIP = ROOT / "data/onboard_sensor/dust_star_tracker/DUST.zip"
OBSERVER_NORAD_ID = 39265  # CASSIOPE, the DUST host spacecraft


def read_observation(archive, base, h5_name, annotation, apply_star_correction=False,
                    has_corr=True):
    """Return observation timestamp, WCS ray, observer position, and pixel."""
    stem = pathlib.PurePosixPath(h5_name).stem
    h5 = h5py.File(io.BytesIO(archive.read(h5_name)), "r")
    # DUST's UTC attribute is an ISO timestamp without an explicit timezone.
    when = dt.datetime.fromisoformat(str(h5.attrs["UTC"])).replace(tzinfo=dt.timezone.utc)
    instant = Time(when)
    wcs_path = f"{base}/WCS/{stem}.fits"
    with fits.open(io.BytesIO(archive.read(wcs_path))) as hdus:
        wcs = WCS(hdus[0].header)
    x = annotation[2] + annotation[4] / 2
    y = annotation[3] + annotation[5] / 2
    sky = wcs.pixel_to_world(x, y)
    correction_east_arcsec = 0.0
    correction_north_arcsec = 0.0
    star_match_count = 0
    if has_corr:
        corr_path = f"{base}/Corr/{stem}.csv"
        corr_rows = list(csv.DictReader(io.StringIO(archive.read(corr_path).decode("utf-8-sig"))))
        corr_rows = [
            row for row in corr_rows
            if all(row.get(key) not in (None, "") for key in ("field_x", "field_y", "index_ra", "index_dec"))
        ]
        if corr_rows:
            # Corr uses one-based star pixels; MOT/YOLO RSO pixels are zero-based.
            star_x = np.asarray([float(row["field_x"]) - 1 for row in corr_rows])
            star_y = np.asarray([float(row["field_y"]) - 1 for row in corr_rows])
            predicted = wcs.pixel_to_world(star_x, star_y).icrs
            catalog = SkyCoord(
                np.asarray([float(row["index_ra"]) for row in corr_rows]) * u.deg,
                np.asarray([float(row["index_dec"]) for row in corr_rows]) * u.deg,
                frame="icrs",
            )
            delta_ra = (catalog.ra - predicted.ra).wrap_at(180 * u.deg)
            mean_dec = (catalog.dec.to_value(u.rad) + predicted.dec.to_value(u.rad)) / 2
            east_arcsec = delta_ra.to_value(u.arcsec) * np.cos(mean_dec)
            north_arcsec = (catalog.dec - predicted.dec).to_value(u.arcsec)
            correction_east_arcsec = float(np.median(east_arcsec))
            correction_north_arcsec = float(np.median(north_arcsec))
            star_match_count = len(corr_rows)
            if apply_star_correction:
                sky = sky.icrs.spherical_offsets_by(
                    correction_east_arcsec * u.arcsec,
                    correction_north_arcsec * u.arcsec,
                )
    ray = sky.transform_to(TEME(obstime=instant)).cartesian.xyz.value
    ray = ray / np.linalg.norm(ray)

    location = EarthLocation.from_geodetic(
        float(h5.attrs["S/C Longitude (°)"]) * u.deg,
        float(h5.attrs["S/C Latitude (°)"]) * u.deg,
        float(h5.attrs["S/C Altitude (km)"]) * u.km,
    )
    observer = location.get_itrs(obstime=instant).transform_to(
        TEME(obstime=instant)
    ).cartesian.xyz.to_value(u.km)
    return {
        "frame": int(annotation[0]),
        "when": when,
        "ray": ray,
        "observer_km": observer,
        "ra_deg": float(sky.ra.deg),
        "dec_deg": float(sky.dec.deg),
        "x_px": float(x),
        "y_px": float(y),
        "star_match_count": star_match_count,
        "star_correction_east_arcsec": correction_east_arcsec,
        "star_correction_north_arcsec": correction_north_arcsec,
        "star_correction_applied": bool(apply_star_correction and star_match_count),
        "tle_age_hours": None,
    }


def nearest_catalog_objects(when, ray, observer_km, limit=50, max_age_hours=72):
    rows = History(
        cohort="all", window=(when, when), max_age_hours=max_age_hours
    ).snapshot(when, max_age=max_age_hours)
    rows = [row for row in rows if int(row["norad_id"]) != OBSERVER_NORAD_ID]
    jd, fraction = julian(when)
    errors, positions, _ = SatrecArray([satellite(row) for row in rows]).sgp4(
        np.array([jd]), np.array([fraction])
    )
    positions = np.asarray(positions)[:, 0, :]
    errors = np.asarray(errors)[:, 0]
    line_of_sight = positions - observer_km
    ranges = np.linalg.norm(line_of_sight, axis=1)
    cosines = np.clip((line_of_sight @ ray) / ranges, -1, 1)
    separations = np.degrees(np.arccos(cosines))
    valid = (errors == 0) & np.isfinite(separations) & np.isfinite(ranges)
    order = np.argsort(np.where(valid, separations, np.inf))[:limit]
    result = []
    for i in order:
        if valid[i]:
            result.append({
                "norad_id": int(rows[i]["norad_id"]),
                "separation_deg": float(separations[i]),
                "range_km": float(ranges[i]),
                "tle_epoch": rows[i]["epoch"].isoformat(),
                "tle_age_hours": (when - rows[i]["epoch"]).total_seconds() / 3600,
            })
    return result


def run(session, track_id, set_name="SET 1", candidate_limit=50, max_age_hours=72,
        pointing_correction=False):
    base = f"DUST/{set_name}/{session}"
    with zipfile.ZipFile(DUST_ZIP) as archive:
        names = archive.namelist()
        annotation_name = f"{base}/RSO_Annotations/{session}_MOT_gt.txt"
        annotations = []
        for line in archive.read(annotation_name).decode("utf-8-sig").splitlines():
            fields = [float(value.strip()) for value in line.split(",")]
            if len(fields) >= 6 and int(fields[1]) == track_id:
                annotations.append(fields)
        annotations.sort(key=lambda row: int(row[0]))
        h5_names = sorted(
            name for name in names
            if name.startswith(f"{base}/H5/") and name.endswith(".h5")
        )
        by_frame = {int(row[0]): row for row in annotations}
        usable = []
        for frame, annotation in by_frame.items():
            if frame < 1 or frame > len(h5_names):
                continue
            h5_name = h5_names[frame - 1]
            stem = pathlib.PurePosixPath(h5_name).stem
            if f"{base}/WCS/{stem}.fits" not in names:
                continue
            corr_name = f"{base}/Corr/{stem}.csv"
            usable.append(read_observation(
                archive, base, h5_name, annotation,
                apply_star_correction=pointing_correction,
                has_corr=corr_name in names,
            ))

    if not usable:
        raise RuntimeError(f"No usable annotated frames for {session}, track {track_id}")
    first = usable[0]
    candidates = nearest_catalog_objects(
        first["when"], first["ray"], first["observer_km"],
        limit=candidate_limit, max_age_hours=max_age_hours,
    )
    if not candidates:
        raise RuntimeError("No valid catalog candidates at the first annotated frame")
    candidate_ids = [candidate["norad_id"] for candidate in candidates]
    times = [obs["when"] for obs in usable]
    training_count = min(len(usable), min(5, max(3, int(np.ceil(len(usable) * 0.2)))))
    history = History(
        cohort="all", window=(times[0], times[-1]), max_age_hours=max_age_hours
    )
    states, ages, errors, _source_epochs = history.replay(
        candidate_ids, times, max_age=max_age_hours
    )
    rays = np.asarray([obs["ray"] for obs in usable])
    observers = np.asarray([obs["observer_km"] for obs in usable])
    deltas = states[:, :, :3] - observers[:, None, :]
    ranges = np.linalg.norm(deltas, axis=2)
    cosine = np.clip(np.einsum("tci,ti->tc", deltas, rays) / ranges, -1, 1)
    separations = np.degrees(np.arccos(cosine))
    valid = (errors == 0) & np.isfinite(separations) & np.isfinite(ranges)
    candidate_scores = []
    for index, candidate in enumerate(candidates):
        train_values = separations[:training_count, index][valid[:training_count, index]]
        required = max(1, int(np.ceil(training_count * 0.8)))
        if len(train_values) < required:
            continue
        candidate_scores.append({
            "norad_id": candidate["norad_id"],
            "first_frame_separation_deg": candidate["separation_deg"],
            "training_median_separation_deg": float(np.median(train_values)),
            "training_p95_separation_deg": float(np.percentile(train_values, 95)),
            "training_frames_available": int(len(train_values)),
        })
    candidate_scores.sort(key=lambda item: (
        item["training_median_separation_deg"],
        item["training_p95_separation_deg"],
        item["norad_id"],
    ))
    if not candidate_scores:
        raise RuntimeError("No catalog candidate propagated successfully across training frames")
    selected_id = candidate_scores[0]["norad_id"]
    selected_index = candidate_ids.index(selected_id)
    records = []
    for index, obs in enumerate(usable):
        out = {key: value for key, value in obs.items() if key not in {"ray", "observer_km"}}
        out["when"] = obs["when"].isoformat()
        out["role"] = "training" if index < training_count else "held_out"
        out["tle_age_hours"] = float(ages[index, selected_index])
        if not valid[index, selected_index]:
            out.update({"separation_deg": None, "range_km": None})
        else:
            out.update({
                "separation_deg": float(separations[index, selected_index]),
                "range_km": float(ranges[index, selected_index]),
            })
        records.append(out)

    residuals = np.array([
        row["separation_deg"] for row in records
        if row["role"] == "held_out" and row["separation_deg"] is not None
    ])
    return {
        "session": session,
        "dataset_set": set_name,
        "track_id": track_id,
        "dust_archive": str(DUST_ZIP.relative_to(ROOT)),
        "dust_archive_md5": (ROOT / "data/onboard_sensor/dust_star_tracker/DUST.zip.md5").read_text().strip(),
        "catalog_scope": f"all archived GP/TLE IDs with <={max_age_hours:g}-hour element age",
        "max_element_age_hours": max_age_hours,
        "observer_norad_excluded": OBSERVER_NORAD_ID,
        "candidate_selection": f"among {candidate_limit} closest first-frame catalog candidates, minimize median angular residual on the first up-to-five training frames",
        "pointing_correction": "per-frame median Corr star-to-catalog east/north offset" if pointing_correction else "raw DUST WCS",
        "candidate_shortlist_size": len(candidates),
        "selected_norad_id": selected_id,
        "first_frame_candidates": candidates,
        "training_frame_count": training_count,
        "track_candidate_ranking": candidate_scores[:10],
        "frames_total": len(annotations),
        "frames_with_wcs_and_ephemeris": len(usable),
        "track_temporal_validation": {
            "evaluated_frames": int(len(residuals)),
            "median_separation_deg": float(np.median(residuals)) if len(residuals) else None,
            "p95_separation_deg": float(np.percentile(residuals, 95)) if len(residuals) else None,
            "max_separation_deg": float(np.max(residuals)) if len(residuals) else None,
            "under_0_15_deg_fraction": float(np.mean(residuals < 0.15)) if len(residuals) else None,
        },
        "limitations": [
            "DUST annotations do not carry NORAD IDs; the identity is a candidate association.",
            "The first up-to-five annotated frames select among 50 first-frame angular candidates; later frames are temporal holdouts.",
            "TLEs are approximate orbit estimates, not independently measured truth.",
            "The DUST WCS and spacecraft pose metadata share one dataset and can share systematic errors.",
        ],
        "frame_results": records,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--set", dest="set_name", default="SET 1", choices=("SET 1", "SET 2"))
    parser.add_argument("--session", default="2023_01_16")
    parser.add_argument("--track", type=int, default=1)
    parser.add_argument("--candidate-limit", type=int, default=50)
    parser.add_argument("--max-age-hours", type=float, default=72)
    parser.add_argument("--star-pointing-correction", action="store_true")
    parser.add_argument("--output", type=pathlib.Path)
    args = parser.parse_args()
    result = run(
        args.session, args.track, args.set_name,
        args.candidate_limit, args.max_age_hours, args.star_pointing_correction,
    )
    rendered = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n")
    print(json.dumps({
        "session": result["session"],
        "track_id": result["track_id"],
        "selected_norad_id": result["selected_norad_id"],
        "first_frame_candidates": result["first_frame_candidates"],
        "track_candidate_ranking": result["track_candidate_ranking"],
        "temporal_validation": result["track_temporal_validation"],
        "output": str(args.output) if args.output else None,
    }, indent=2))


if __name__ == "__main__":
    main()
