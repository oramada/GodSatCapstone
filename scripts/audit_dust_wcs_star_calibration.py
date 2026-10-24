#!/usr/bin/env python3
"""Measure DUST per-frame WCS residuals against its matched star catalog."""
import argparse
import csv
import io
import json
import pathlib
import zipfile
from collections import defaultdict

import numpy as np
import astropy.units as u
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.wcs import WCS

from validate_dust_tle_track import DUST_ZIP, ROOT

PIXEL_OFFSETS = (-1, 0, 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=pathlib.Path, default=ROOT / "outputs/dust-tle-track-validation/wcs-star-calibration")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    per_frame = []
    by_session = defaultdict(lambda: defaultdict(list))
    file_names = []
    with zipfile.ZipFile(DUST_ZIP) as archive:
        files = set(archive.namelist())
        file_names = sorted(
            name for name in files
            if "/Corr/" in name and name.endswith(".csv")
            and name.rsplit("/", 1)[0].replace("/Corr", "/WCS") + "/"
                + pathlib.PurePosixPath(name).stem + ".fits" in files
        )
        if not file_names:
            raise RuntimeError("No DUST Corr/WCS frame pairs were found")
        for corr_path in file_names:
            wcs_path = corr_path.rsplit("/", 1)[0].replace("/Corr", "/WCS") + "/" + pathlib.PurePosixPath(corr_path).stem + ".fits"
            base_parts = pathlib.PurePosixPath(corr_path).parts
            dataset_set, session = base_parts[1], base_parts[2]
            rows = list(csv.DictReader(io.StringIO(archive.read(corr_path).decode("utf-8-sig"))))
            rows = [
                row for row in rows
                if all(row.get(key) not in (None, "") for key in ("field_x", "field_y", "index_ra", "index_dec"))
            ]
            if not rows:
                continue
            x = np.asarray([float(row["field_x"]) for row in rows])
            y = np.asarray([float(row["field_y"]) for row in rows])
            reference = SkyCoord(
                np.asarray([float(row["index_ra"]) for row in rows]) * u.deg,
                np.asarray([float(row["index_dec"]) for row in rows]) * u.deg,
                frame="icrs",
            )
            with fits.open(io.BytesIO(archive.read(wcs_path))) as hdus:
                wcs = WCS(hdus[0].header)
            stem = pathlib.PurePosixPath(corr_path).stem
            result = {
                "dataset_set": dataset_set,
                "session": session,
                "frame": stem,
                "star_matches": len(rows),
            }
            for dx in PIXEL_OFFSETS:
                for dy in PIXEL_OFFSETS:
                    sky = wcs.pixel_to_world(x + dx, y + dy)
                    residuals = sky.separation(reference).arcsec
                    key = f"dx{dx:+d}_dy{dy:+d}"
                    values = np.asarray(residuals, dtype=float)
                    result[f"{key}_median_arcsec"] = float(np.median(values))
                    result[f"{key}_p95_arcsec"] = float(np.percentile(values, 95))
                    by_session[(dataset_set, session)][key].extend(values.tolist())
            per_frame.append(result)

    keys = [f"dx{dx:+d}_dy{dy:+d}" for dx in PIXEL_OFFSETS for dy in PIXEL_OFFSETS]
    pooled = {}
    for key in keys:
        pooled[key] = {
            "median_arcsec": float(np.median([row[f"{key}_median_arcsec"] for row in per_frame])),
            "p95_frame_median_arcsec": float(np.percentile([row[f"{key}_median_arcsec"] for row in per_frame], 95)),
            "pooled_star_median_arcsec": float(np.median(np.concatenate([
                np.asarray(by_session[session][key], dtype=float) for session in by_session
            ]))),
        }
    session_summary = []
    for (dataset_set, session), offsets in sorted(by_session.items()):
        session_summary.append({
            "dataset_set": dataset_set,
            "session": session,
            "frame_count": sum(row["dataset_set"] == dataset_set and row["session"] == session for row in per_frame),
            "star_match_count": sum(row["star_matches"] for row in per_frame if row["dataset_set"] == dataset_set and row["session"] == session),
            "median_residual_arcsec_by_pixel_offset": {
                key: float(np.median(values)) for key, values in offsets.items()
            },
        })
    best = min(keys, key=lambda key: pooled[key]["pooled_star_median_arcsec"])
    summary = {
        "archive_md5": (ROOT / "data/onboard_sensor/dust_star_tracker/DUST.zip.md5").read_text().strip(),
        "frame_count": len(per_frame),
        "star_match_count": sum(row["star_matches"] for row in per_frame),
        "reference": "DUST Corr index_ra/index_dec catalog matches",
        "pixel_convention_test": "evaluate WCS transforms at x/y shifts -1, 0, and +1 pixels relative to Corr field_x/field_y",
        "best_global_shift_for_corr_field_coordinates": best,
        "pooled_offset_comparison": pooled,
        "per_session": session_summary,
        "per_frame_csv": "per_frame_wcs_star_residuals.csv",
        "interpretation_limit": "This validates WCS against matched stars for the Corr coordinate convention; it does not establish the pixel origin used by MOT RSO labels or provide NORAD identities.",
    }
    csv_path = args.output_dir / "per_frame_wcs_star_residuals.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(per_frame[0]))
        writer.writeheader()
        writer.writerows(per_frame)
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "frame_count": summary["frame_count"],
        "star_match_count": summary["star_match_count"],
        "best_global_shift_for_corr_field_coordinates": best,
        "pooled_offset_comparison": pooled,
    }, indent=2))


if __name__ == "__main__":
    main()
