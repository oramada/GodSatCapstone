#!/usr/bin/env python3
"""Summarize CASSIOPE attitude-source quality at the tasking cadence.

The handbook's source codes distinguish star-tracker and coarse sun-sensor
solutions. This report does not convert those published nominal uncertainties
into a sensor error model; it reports their observed frequency and the spacing
of the definitive solutions used to form the 1 Hz spline.
"""
from __future__ import annotations

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))


import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data/attitude/cassiope_epop"
SOURCE_LABELS = {
    0: "dropout",
    1: "uncalibrated_coarse_sun_sensor_magnetometer",
    2: "coarse_sun_sensor_magnetometer",
    3: "onboard_fused_star_sensor",
    4: "star_sensor_a",
    5: "star_sensor_b",
    6: "star_sensor_a_plus_b",
}
SOURCE_UNCERTAINTY_DEG = {1: ">10", 2: "~8", 3: "~0.1", 4: "~0.06", 5: "~0.06", 6: "~0.01"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def analyze(data: Path = DATA, cadence_seconds: int = 60) -> dict:
    data = Path(data)
    if cadence_seconds <= 0 or 86_400 % cadence_seconds:
        raise ValueError("cadence_seconds must be a positive divisor of one day")
    audit = json.loads((data / "independent_audit.json").read_text())
    profile = json.loads((data / "dropout_profile_1minute.json").read_text())
    if audit.get("status") != "passed_structural_and_statistical":
        raise ValueError("Independent quaternion audit has not passed")
    if profile.get("status") != "completed":
        raise ValueError("Attitude dropout profile has not completed")

    source_counts = {"previous": {str(code): 0 for code in SOURCE_LABELS},
                     "next": {str(code): 0 for code in SOURCE_LABELS}}
    quality_counts = {"dropout": 0, "coarse_sun_magnetometer": 0, "star_tracker": 0,
                      "unknown": 0}
    near_solution_seconds = []
    sampled_days = 0
    sampled_rows = 0
    failures = []
    for day in audit.get("validated_dates", []):
        path = data / "processed" / day[:4] / f"{day}.parquet"
        try:
            table = pq.read_table(path, columns=[
                "q1", "q2", "q3", "q4", "data_source_previous", "data_source_next",
                "time_to_previous_s", "time_to_next_s"])
            if table.num_rows != 86_400:
                raise ValueError(f"expected 86400 samples, got {table.num_rows}")
            indexes = np.arange(0, table.num_rows, cadence_seconds)
            q = np.column_stack([table[f"q{i}"].to_numpy(zero_copy_only=False)[indexes]
                                 for i in range(1, 5)])
            valid = np.isfinite(q).all(axis=1)
            previous = table["data_source_previous"].to_numpy(zero_copy_only=False)[indexes]
            next_ = table["data_source_next"].to_numpy(zero_copy_only=False)[indexes]
            prev_time = table["time_to_previous_s"].to_numpy(zero_copy_only=False)[indexes]
            next_time = table["time_to_next_s"].to_numpy(zero_copy_only=False)[indexes]
            if np.any((previous == 0) != ~valid) or np.any((next_ == 0) != ~valid):
                raise ValueError("source dropout codes disagree with quaternion validity")
            for label, values in (("previous", previous), ("next", next_)):
                unique, counts = np.unique(values, return_counts=True)
                for code, count in zip(unique, counts):
                    if str(int(code)) not in source_counts[label]:
                        raise ValueError(f"unknown source code {code}")
                    source_counts[label][str(int(code))] += int(count)
            for index, (before, after) in enumerate(zip(previous, next_)):
                if not valid[index]:
                    quality_counts["dropout"] += 1
                elif before in (1, 2) or after in (1, 2):
                    quality_counts["coarse_sun_magnetometer"] += 1
                elif before in (3, 4, 5, 6) and after in (3, 4, 5, 6):
                    quality_counts["star_tracker"] += 1
                else:
                    quality_counts["unknown"] += 1
            usable = valid & np.isfinite(prev_time) & np.isfinite(next_time)
            nearest = np.minimum(np.abs(prev_time[usable]), np.abs(next_time[usable]))
            near_solution_seconds.extend(nearest.tolist())
            sampled_rows += len(indexes)
            sampled_days += 1
        except Exception as error:
            failures.append({"date": day, "error": f"{type(error).__name__}: {error}"})
    if failures:
        raise ValueError(f"Attitude quality sample failed validation: {failures[:5]}")
    expected_days = audit.get("downloaded_days")
    if sampled_days != expected_days or sampled_rows != profile.get("one_minute_samples"):
        raise ValueError("Attitude quality sample does not match audited one-minute coverage")
    ages = np.asarray(near_solution_seconds, dtype=np.float64)
    thresholds = [1, 10, 30, 60, 120]
    n_valid = sampled_rows - quality_counts["dropout"]
    return {
        "status": "completed",
        "source_audit_status": audit["status"],
        "source_profile_sha256": sha256(data / "dropout_profile_1minute.json"),
        "source_date_range": [audit["first_day"], audit["last_day"]],
        "sampled_days": sampled_days,
        "cadence_seconds": cadence_seconds,
        "sampled_minutes": sampled_rows,
        "quality_class_counts": quality_counts,
        "quality_class_fraction_of_all_samples": {
            name: count / sampled_rows for name, count in quality_counts.items()
        },
        "source_code_counts": source_counts,
        "source_code_labels": {str(code): label for code, label in SOURCE_LABELS.items()},
        "handbook_nominal_source_uncertainty_degrees": SOURCE_UNCERTAINTY_DEG,
        "nearest_definitive_solution_spacing_seconds_on_valid_quaternion_samples": {
            "sample_count": int(len(ages)),
            "quantiles_seconds": {
                str(q): float(value) for q, value in zip(
                    [0.5, 0.9, 0.95, 0.99], np.quantile(ages, [0.5, 0.9, 0.95, 0.99]))
            },
            "fractions_above_seconds": {
                str(t): float(np.mean(ages > t)) for t in thresholds
            },
            "note": "Minimum absolute Time_To_Previous/Next at the sampled epoch; this is a source-solution spacing proxy, not a quaternion error bound.",
        },
        "interpretation": (
            "One-minute CASSIOPE attitude quality classes and adjacent definitive-solution spacing. "
            "Codes 1/2 denote coarse solutions; codes 3-6 denote star-sensor solutions. "
            "Published nominal uncertainties are not applied as a simulator pointing-error model. "
            "This is one spacecraft and does not provide ground-sensor acquisition outcomes."
        ),
        "limitations": [
            "The one-minute sample is taken at the first second of each minute to match the tasking replay cadence.",
            "The handbook gives nominal source uncertainties, not per-sample covariance or pointing residuals.",
            "A valid quaternion or nearby definitive solution does not establish ground-sensor task success.",
            "Only one spacecraft has this open four-year telemetry stream.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DATA)
    parser.add_argument("--cadence-seconds", type=int, default=60)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    data = args.data if args.data.is_absolute() else ROOT / args.data
    result = analyze(data, args.cadence_seconds)
    output = args.output or data / "solution_quality_1minute.json"
    if not output.is_absolute():
        output = ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: result[key] for key in (
        "status", "sampled_days", "sampled_minutes", "quality_class_counts",
        "nearest_definitive_solution_spacing_seconds_on_valid_quaternion_samples")}, indent=2))


if __name__ == "__main__":
    main()
