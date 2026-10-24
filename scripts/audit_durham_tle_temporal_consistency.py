"""Audit whether Durham optical detections use TLE epochs after observation time."""
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
import statistics
import zipfile


DOI = "10.15128/r1d504rk46w"
FUTURE_TOLERANCE_SECONDS = 60


def _quantile(values, fraction):
    values = sorted(values)
    if not values:
        return None
    return values[min(len(values) - 1, round(fraction * (len(values) - 1)))]


def audit(archive_path, output_path):
    archive_path = pathlib.Path(archive_path)
    archive_bytes = archive_path.read_bytes()
    archive_hash = hashlib.sha256(archive_bytes).hexdigest()
    archive_md5 = hashlib.md5(archive_bytes).hexdigest()
    total_rows = identified_rows = unidentified_rows = 0
    ages_by_night = collections.defaultdict(list)
    nested_extensions = collections.Counter()
    nested_files = 0
    separate_tle_files = 0

    with zipfile.ZipFile(archive_path) as bundle:
        outer_names = bundle.namelist()
        nightly_names = sorted(
            name for name in outer_names if name.endswith("_rawDetect_output.zip"))
        for nightly_name in nightly_names:
            with zipfile.ZipFile(io.BytesIO(bundle.read(nightly_name))) as nightly:
                names = nightly.namelist()
                nested_files += len(names)
                nested_extensions.update(
                    pathlib.PurePosixPath(name).suffix.lower() or "[no extension]"
                    for name in names)
                separate_tle_files += sum(
                    pathlib.PurePosixPath(name).suffix.lower() in {".tle", ".txt"}
                    for name in names)
                for member in names:
                    if not member.lower().endswith(".csv"):
                        continue
                    is_unidentified_track = pathlib.PurePosixPath(member).name.startswith("track_")
                    with nightly.open(member) as stream:
                        reader = csv.DictReader(io.TextIOWrapper(
                            stream, encoding="utf-8-sig", newline=""))
                        for row in reader:
                            total_rows += 1
                            norad = (row.get("MATCH_NORAD") or "").strip()
                            if is_unidentified_track or not norad:
                                unidentified_rows += 1
                                continue
                            identified_rows += 1
                            try:
                                observed_jd = float(row["TIME_JD"])
                                element_jd = float(row["MATCH_TLE_EPOCH_JD"])
                                age_days = observed_jd - element_jd
                            except (KeyError, TypeError, ValueError):
                                continue
                            if math.isfinite(age_days):
                                ages_by_night[nightly_name].append(age_days)

    all_ages = [age for values in ages_by_night.values() for age in values]
    future_cutoff_days = FUTURE_TOLERANCE_SECONDS / 86400
    future = [age for age in all_ages if age < -future_cutoff_days]
    result = {
        "status": "completed",
        "dataset_doi": DOI,
        "archive": str(archive_path),
        "archive_sha256": archive_hash,
        "archive_md5": archive_md5,
        "archive_bytes": archive_path.stat().st_size,
        "top_level_file_count": len(outer_names),
        "nightly_archives": len(nightly_names),
        "nested_file_count": nested_files,
        "nested_file_extensions": dict(sorted(nested_extensions.items())),
        "separate_tle_files_in_nested_archives": separate_tle_files,
        "rows": {
            "total": total_rows,
            "identified_norad_rows": identified_rows,
            "unidentified_track_rows": unidentified_rows,
            "identified_rows_with_finite_observation_and_tle_epochs": len(all_ages),
        },
        "matched_tle_epoch_age_days": {
            "definition": "TIME_JD minus MATCH_TLE_EPOCH_JD; positive means element epoch precedes the observation timestamp",
            "median": statistics.median(all_ages) if all_ages else None,
            "p05": _quantile(all_ages, 0.05),
            "p95": _quantile(all_ages, 0.95),
            "minimum": min(all_ages) if all_ages else None,
            "maximum": max(all_ages) if all_ages else None,
            "future_by_more_than_60_seconds": len(future),
            "future_by_more_than_60_seconds_fraction": len(future) / len(all_ages) if all_ages else None,
            "future_by_more_than_6_hours": sum(age < -0.25 for age in all_ages),
        },
        "nightly": [],
        "interpretation": (
            "A negative age means the element epoch recorded for an association is later than the row's observation timestamp. "
            "Such rows are retrospective associations with respect to those timestamps and must not be treated as as-of-time predictions. "
            "This audit does not establish when the TLE was retrieved or used operationally."
        ),
        "limitations": [
            "The downloaded nightly archives contain processed CSVs but no separate TLE text files, so the exact publisher element sets cannot be independently re-propagated from this bundle.",
            "The age comparison uses the dataset's TIME_JD and MATCH_TLE_EPOCH_JD fields as published; timestamp semantics were not independently instrument-verified.",
            "The audit evaluates association chronology only; it does not create missed-observation labels or estimate sensor dropout probability.",
        ],
    }
    for name in nightly_names:
        values = ages_by_night[name]
        night_future = sum(age < -future_cutoff_days for age in values)
        result["nightly"].append({
            "archive": name,
            "finite_epoch_rows": len(values),
            "future_epoch_rows_over_60_seconds": night_future,
            "future_epoch_fraction_over_60_seconds": night_future / len(values) if values else None,
            "median_element_age_days": statistics.median(values) if values else None,
            "minimum_element_age_days": min(values) if values else None,
            "maximum_element_age_days": max(values) if values else None,
        })

    output_path = pathlib.Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", nargs="?", default=(
        "data/ground_sensor/durham_optical_survey/all_data.zip"))
    parser.add_argument("--output", default=(
        "data/ground_sensor/durham_optical_survey/tle_temporal_audit.json"))
    args = parser.parse_args()
    result = audit(args.archive, args.output)
    print(json.dumps({key: result[key] for key in (
        "status", "archive_sha256", "rows", "matched_tle_epoch_age_days",
        "separate_tle_files_in_nested_archives", "nightly")}, indent=2))


if __name__ == "__main__":
    main()
