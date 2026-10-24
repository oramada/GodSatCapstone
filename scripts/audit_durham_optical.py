"""Inventory the public Durham optical SSA detections without inflating them into outage labels."""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import hashlib
import io
import json
import math
import pathlib
import re
import statistics
import zipfile


DATASET_URL = "https://researchdata.durham.ac.uk/downloads/r1d504rk46w"
DOI = "10.15128/r1d504rk46w"


def quantiles(values):
    values = sorted(values)
    if not values:
        return {"count": 0}
    def at(p):
        return values[min(len(values) - 1, round(p * (len(values) - 1)))]
    return {"count": len(values), "median": statistics.median(values),
            "p90": at(.90), "p95": at(.95), "p99": at(.99)}


def audit(archive_path, output_path):
    archive_path = pathlib.Path(archive_path)
    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    nights = []
    total_rows = identified = unidentified = 0
    norad_ids = set()
    metric_names = ("ANG_ERR_ARCSEC", "CENTROID_ERR_ARCSEC", "SNR_APER",
                    "MAG_APER", "CONFIDENCE", "MATCH_SEP_R_DEG",
                    "SEPARATION_FIELD_ABS_DIFFERENCE_ARCSEC")
    metrics = {"all_rows": {key: [] for key in metric_names},
               "identified": {key: [] for key in metric_names},
               "unidentified_tracks": {key: [] for key in metric_names}}
    with zipfile.ZipFile(archive_path) as bundle:
        readme = bundle.read("README.md").decode("utf-8", "replace")
        top_level_names = bundle.namelist()
        nested_names = sorted(n for n in top_level_names if n.endswith("_rawDetect_output.zip"))
        nested_file_count = 0
        nested_extensions = collections.Counter()
        nested_names_lower = []
        for nested_name in nested_names:
            date_match = re.match(r"(\d{2})-(\d{2})-(\d{2})_", pathlib.PurePosixPath(nested_name).name)
            if not date_match:
                raise ValueError(f"Cannot derive observing date from {nested_name}")
            year, month, day = map(int, date_match.groups())
            observing_date = dt.date(2000 + year, month, day).isoformat()
            night_rows = night_identified = night_tracks = 0
            night_ids = set()
            night_metrics = {"identified": {key: [] for key in metric_names},
                             "unidentified_tracks": {key: [] for key in metric_names}}
            with zipfile.ZipFile(io.BytesIO(bundle.read(nested_name))) as night:
                night_names = night.namelist()
                nested_file_count += len(night_names)
                nested_extensions.update(pathlib.PurePosixPath(n).suffix.lower() or "[no extension]"
                                         for n in night_names)
                nested_names_lower.extend(pathlib.PurePosixPath(n).name.lower()
                                          for n in night_names)
                csv_names = [n for n in night_names if n.lower().endswith(".csv")]
                for csv_name in csv_names:
                    is_track = pathlib.PurePosixPath(csv_name).name.startswith("track_")
                    with night.open(csv_name) as source:
                        text = io.TextIOWrapper(source, encoding="utf-8-sig", newline="")
                        reader = csv.DictReader(text)
                        for row in reader:
                            night_rows += 1
                            total_rows += 1
                            object_id = (row.get("MATCH_NORAD") or "").strip()
                            if is_track or not object_id:
                                night_tracks += 1
                                unidentified += 1
                                category = "unidentified_tracks"
                            else:
                                night_identified += 1
                                identified += 1
                                night_ids.add(object_id)
                                norad_ids.add(object_id)
                            category = "identified"
                            if row.get("TIME_JD"):
                                # Julian dates are UTC in the supplied products.
                                pass
                            for key in metric_names:
                                try:
                                    if key == "SEPARATION_FIELD_ABS_DIFFERENCE_ARCSEC":
                                        az, alt, pred_az, pred_alt, reported = (
                                            float(row[name]) for name in
                                            ("AZ_DEG", "ALT_DEG", "MATCH_TLE_AZ_DEG",
                                             "MATCH_TLE_ALT_DEG", "MATCH_SEP_R_DEG"))
                                        alt, pred_alt = math.radians(alt), math.radians(pred_alt)
                                        delta_az = math.radians(az - pred_az)
                                        cosine = (math.sin(alt) * math.sin(pred_alt)
                                                  + math.cos(alt) * math.cos(pred_alt)
                                                  * math.cos(delta_az))
                                        computed = math.degrees(math.acos(max(-1., min(1., cosine))))
                                        value = abs(computed - reported) * 3600
                                    else:
                                        value = float(row[key])
                                except (KeyError, TypeError, ValueError):
                                    continue
                                if math.isfinite(value):
                                    metrics["all_rows"][key].append(value)
                                    metrics[category][key].append(value)
                                    night_metrics[category][key].append(value)
            nights.append({"archive": nested_name, "observing_date": observing_date,
                           "rows": night_rows, "identified_rows": night_identified,
                           "unidentified_track_rows": night_tracks,
                           "identified_norad_ids": sorted(night_ids),
                           "measurement_distributions": {
                               group: {key: quantiles(vals) for key, vals in fields.items()}
                               for group, fields in night_metrics.items()}})
    result = {
        "status": "completed",
        "dataset": "Nightly optical survey catalogues for resident space objects above LEO",
        "publisher": "Durham University Research Data Repository",
        "doi": DOI,
        "license": "CC BY 4.0",
        "download_url": DATASET_URL,
        "archive_sha256": digest,
        "archive_bytes": archive_path.stat().st_size,
        "archive_structure": {
            "top_level_files": len(top_level_names),
            "readme_files": sum(pathlib.PurePosixPath(n).name.lower() == "readme.md"
                                 for n in top_level_names),
            "nightly_detection_archives": len(nested_names),
            "nested_files": nested_file_count,
            "nested_file_extensions": dict(sorted(nested_extensions.items())),
            "raw_image_files": sum(pathlib.PurePosixPath(n).suffix.lower() in
                                    (".fit", ".fits", ".fts", ".png", ".jpg", ".jpeg", ".tif", ".tiff")
                                    for n in nested_names_lower),
            "opportunity_or_nondetection_named_files": sum(
                any(token in pathlib.PurePosixPath(n).name.lower()
                    for token in ("opportunity", "nondetect", "non_detect", "missed"))
                for n in nested_names_lower),
            "interpretation": "Archive contents are processed detection/track CSV outputs; file inventory does not establish a complete frame-level target-opportunity ledger.",
        },
        "observing_site": "Durham University, Durham, United Kingdom",
        "instrument": "ZWO ASI6200MM-Pro CMOS camera with William Optics RedCat 71 APO telescope",
        "nights": nights,
        "night_count": len(nights),
        "total_detection_rows": total_rows,
        "identified_detection_rows": identified,
        "unidentified_track_rows": unidentified,
        "distinct_identified_norad_ids": len(norad_ids),
        "measurement_distributions": {
            group: {key: quantiles(vals) for key, vals in fields.items()}
            for group, fields in metrics.items()},
        "validity_limits": [
            "Representative processed detections from ten nights, not continuous four-year coverage. The archive includes 2024-11-20, which is omitted from the README's listed collection dates.",
            "No complete frame-by-frame target opportunity ledger or explicit missed-acquisition labels are included; detection rows cannot estimate probability of detection or real sensor dropout rate.",
            "Measurements apply to one fixed-field optical site and mostly MEO/GEO objects; they do not represent all sensors, sites, spacecraft attitudes, or LEO targets.",
            "Use astrometric uncertainty and observed track-confidence distributions only for measurement-noise and association validation among recorded detections.",
        ],
        "readme_excerpt": readme[:1200],
    }
    output_path = pathlib.Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", nargs="?", default="data/ground_sensor/durham_optical_survey/all_data.zip")
    parser.add_argument("--output", default="data/ground_sensor/durham_optical_survey/audit.json")
    args = parser.parse_args()
    result = audit(args.archive, args.output)
    print(json.dumps({k: result[k] for k in ("status", "archive_sha256", "night_count",
          "total_detection_rows", "identified_detection_rows", "unidentified_track_rows",
          "distinct_identified_norad_ids", "measurement_distributions")}, indent=2))


if __name__ == "__main__":
    main()
