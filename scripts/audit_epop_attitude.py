#!/usr/bin/env python3
"""Independently validate acquired CASSIOPE/e-POP attitude Parquet products."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/attitude/cassiope_epop"
SOURCES = {"0": "dropout", "1": "uncalibrated_css_magnetometer", "2": "css_magnetometer",
           "3": "onboard_fused_star_sensor", "4": "star_sensor_a", "5": "star_sensor_b",
           "6": "star_sensor_a_plus_b"}


def audit(data: Path = DATA) -> dict:
    manifest = json.loads((data / "manifest.json").read_text())
    day_statuses = manifest.get("per_day_status", {})
    validated_days = sorted(day for day, status in day_statuses.items()
                            if status in {"validated", "already_validated"})
    failures = []
    totals = {"samples": 0, "valid_quaternion_seconds": 0, "invalid_quaternion_seconds": 0,
              "dropout_events": 0, "dropout_source_previous_seconds": 0,
              "dropout_source_next_seconds": 0}
    source_counts = {key: {code: 0 for code in SOURCES} for key in ("previous", "next")}
    yearly = {}
    longest = 0
    first, last = None, None
    checked_days = 0

    for day in validated_days:
        try:
            audit_path = data / "audits" / day[:4] / f"{day}.json"
            saved = json.loads(audit_path.read_text())
            parquet_path = ROOT / saved["parquet_path"]
            table = pq.read_table(parquet_path, columns=[
                "timestamp_utc", "q1", "q2", "q3", "q4", "data_source_previous", "data_source_next"])
            if table.num_rows != 86_400 or saved.get("samples") != table.num_rows:
                raise ValueError(f"unexpected row count {table.num_rows}")
            timestamps = table["timestamp_utc"].to_numpy(zero_copy_only=False)
            if timestamps[0] != np.datetime64(day + "T00:00:00", "ns") or timestamps[-1] != np.datetime64(day + "T23:59:59", "ns"):
                raise ValueError("first/last timestamp does not match the complete UTC day")
            if np.any(np.diff(timestamps).astype("timedelta64[ns]") != np.timedelta64(1, "s")):
                raise ValueError("timestamp series is not exactly 1 Hz")
            q = np.column_stack([table[f"q{i}"].to_numpy(zero_copy_only=False) for i in range(1, 5)])
            valid = np.isfinite(q).all(axis=1)
            invalid_count = int((~valid).sum())
            if invalid_count + int(valid.sum()) != 86_400:
                raise ValueError("valid and invalid quaternion rows do not cover the day")
            norms = np.linalg.norm(q[valid], axis=1)
            if len(norms) and np.max(np.abs(norms - 1.0)) > 1e-9:
                raise ValueError("finite quaternion values are not unit norm")

            prev = table["data_source_previous"].to_numpy(zero_copy_only=False)
            next_ = table["data_source_next"].to_numpy(zero_copy_only=False)
            if int((prev == 0).sum()) != invalid_count or int((next_ == 0).sum()) != invalid_count:
                raise ValueError("source-code-0 counts do not match invalid quaternion rows")
            for label, values, saved_name in (("previous", prev, "source_previous_counts"),
                                               ("next", next_, "source_next_counts")):
                for code in SOURCES:
                    count = int((values == int(code)).sum())
                    if count != saved.get(saved_name, {}).get(code):
                        raise ValueError(f"saved {label} source count {code} does not match Parquet")
                    source_counts[label][code] += count

            invalid_indices = np.flatnonzero(~valid)
            breaks = np.flatnonzero(np.diff(invalid_indices) > 1) + 1
            runs = np.split(invalid_indices, breaks) if len(invalid_indices) else []
            if len(runs) != saved.get("attitude_solution_dropout_events"):
                raise ValueError("dropout event count does not match Parquet")
            day_longest = max((len(run) for run in runs), default=0)
            if day_longest != saved.get("longest_attitude_solution_dropout_seconds"):
                raise ValueError("longest dropout duration does not match Parquet")

            if saved.get("status") != "validated" or not re.fullmatch(r"[0-9a-f]{64}", saved.get("source_zip_sha256", "")):
                raise ValueError("source product status or checksum is invalid")
            raw_relative = saved.get("source_zip_path")
            if raw_relative:
                source_file = ROOT / raw_relative
                digest = hashlib.sha256(source_file.read_bytes()).hexdigest()
                if digest != saved["source_zip_sha256"]:
                    raise ValueError("retained source product checksum mismatch")

            totals["samples"] += table.num_rows
            totals["valid_quaternion_seconds"] += int(valid.sum())
            totals["invalid_quaternion_seconds"] += invalid_count
            totals["dropout_events"] += len(runs)
            totals["dropout_source_previous_seconds"] += int((prev == 0).sum())
            totals["dropout_source_next_seconds"] += int((next_ == 0).sum())
            longest = max(longest, day_longest)
            yearly.setdefault(day[:4], {"days": 0, "samples": 0, "invalid_quaternion_seconds": 0})
            yearly[day[:4]]["days"] += 1
            yearly[day[:4]]["samples"] += table.num_rows
            yearly[day[:4]]["invalid_quaternion_seconds"] += invalid_count
            first = first or day
            last = day
            checked_days += 1
        except Exception as error:
            failures.append({"date_utc": day, "error": f"{type(error).__name__}: {error}"})

    expected_days = manifest.get("requested_days")
    complete = manifest.get("status") in {"completed", "completed_with_errors"}
    status = "passed_structural_and_statistical" if not failures and checked_days else "failed"
    return {
        "status": status,
        "coverage_status": "fetch_finished" if complete else "fetch_in_progress_or_interrupted",
        "source": manifest.get("source"),
        "requested_start_utc": manifest.get("requested_start_utc"),
        "requested_end_exclusive_utc": manifest.get("requested_end_exclusive_utc"),
        "requested_days": expected_days,
        "manifest_status_at_audit": manifest.get("status"),
        "manifest_days_processed_at_audit": manifest.get("days_processed"),
        "manifest_products_validated_at_audit": manifest.get("products_validated"),
        "manifest_failures_at_audit": len(manifest.get("failures", [])),
        "downloaded_days": checked_days,
        "validated_dates": validated_days,
        "published_data_days_not_downloaded": sorted(set(day_statuses) - set(validated_days)),
        "not_published_days": sorted(manifest.get("not_published_dates", [])),
        "samples_per_validated_day": 86_400,
        "first_day": first,
        "last_day": last,
        "totals": totals,
        "longest_solution_dropout_seconds": longest,
        "sensor_source_code_counts": source_counts,
        "sensor_source_code_labels": SOURCES,
        "yearly": yearly,
        "failures": failures,
        "limitations": [
            "CASSIOPE/Swarm-E is one instrumented spacecraft, not attitude history for the whole satellite catalog.",
            "Code 0 identifies unavailable attitude solution intervals; it does not establish ground-sensor missed-task rates.",
            "The source handbook notes long dropouts are represented with NaN quaternions; source codes also distinguish star sensors and coarse sensor solutions.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DATA)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    data = args.data if args.data.is_absolute() else ROOT / args.data
    result = audit(data)
    output = args.output or data / "independent_audit.json"
    if not output.is_absolute():
        output = ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: result[key] for key in ("status", "coverage_status", "requested_days", "downloaded_days", "totals", "failures")}, indent=2))
    if result["status"] != "passed_structural_and_statistical":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
