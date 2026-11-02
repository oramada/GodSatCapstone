#!/usr/bin/env python3
"""Audit whether cached ILRS LAGEOS-1 CRD NPT files encode missed-pass opportunities.

Normal-point rows describe formed range observations. This audit checks the raw
CRD file/session structure and verifies whether a scheduled-pass or no-acquisition
ledger is present before treating the archive as a dropout denominator.
"""

from __future__ import annotations

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))


import argparse
import csv
import datetime as dt
import hashlib
import json
import math
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "data/ground_sensor/ilrs_lageos1_npt"


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def audit(base: Path = BASE, output: Path | None = None) -> dict:
    base = base.resolve()
    manifest = json.loads((base / "manifest.json").read_text())
    expected = {item["path"]: item for item in manifest["files"]}
    raw_paths = sorted(base.glob("[0-9][0-9][0-9][0-9]/*.np2"))
    if len(raw_paths) != len(expected):
        raise ValueError(f"raw file count {len(raw_paths)} != manifest count {len(expected)}")

    record_types = Counter()
    per_file = []
    hash_mismatches = []
    malformed_h4 = malformed_npt = 0
    sessions = sessions_with_npt = sessions_without_npt = 0
    npt_rows = positive_raw_range_rows = zero_raw_range_rows = 0
    exact_zero_return_rate_rows = missing_return_rate_rows = invalid_return_rate_rows = 0
    npt_outside_session_rows = 0
    raw_range_total = 0
    return_rates = []
    for path in raw_paths:
        relative = path.relative_to(ROOT).as_posix()
        item = expected.get(relative)
        if item is None:
            raise ValueError(f"unmanifested CRD file: {relative}")
        if path.stat().st_size != int(item["bytes"]) or digest(path) != item["sha256"]:
            hash_mismatches.append(relative)

        local = Counter()
        h4_start = h4_end = None
        h4_data_type = None
        h4_points = 0
        first_time = last_time = None
        first_session_start = last_session_end = None
        for line in path.read_text(errors="replace").splitlines():
            fields = line.split()
            if not fields:
                continue
            kind = fields[0].upper()
            local[kind] += 1
            record_types[kind] += 1
            if kind == "H4":
                if h4_start is not None:
                    raise ValueError(f"new H4 session began before previous H8: {relative}")
                sessions += 1
                h4_points = 0
                try:
                    h4_data_type = int(fields[1])
                    h4_start = dt.datetime(*(int(v) for v in fields[2:8]), tzinfo=dt.timezone.utc)
                    h4_end = dt.datetime(*(int(v) for v in fields[8:14]), tzinfo=dt.timezone.utc)
                    if h4_data_type != 1 or h4_end < h4_start:
                        raise ValueError
                    first_session_start = h4_start if first_session_start is None else first_session_start
                    last_session_end = h4_end
                except (ValueError, TypeError):
                    malformed_h4 += 1
                    h4_start = h4_end = None
            elif kind == "11":
                npt_rows += 1
                try:
                    if h4_start is None or len(fields) < 13:
                        raise ValueError
                    seconds = float(fields[1])
                    window = float(fields[5])
                    raw_ranges = int(fields[6])
                    rate = float(fields[11]) if fields[11].lower() != "na" else None
                    when = dt.datetime.combine(h4_start.date(), dt.time(), tzinfo=dt.timezone.utc) + dt.timedelta(seconds=seconds)
                    while when < h4_start:
                        when += dt.timedelta(days=1)
                    if when > h4_end + dt.timedelta(minutes=1):
                        npt_outside_session_rows += 1
                    if window <= 0 or raw_ranges < 0 or not math.isfinite(seconds):
                        raise ValueError
                    if raw_ranges > 0:
                        positive_raw_range_rows += 1
                    else:
                        zero_raw_range_rows += 1
                    raw_range_total += raw_ranges
                    if rate is None:
                        missing_return_rate_rows += 1
                    elif not math.isfinite(rate) or not 0 <= rate <= 100:
                        invalid_return_rate_rows += 1
                    else:
                        return_rates.append(rate)
                        exact_zero_return_rate_rows += rate == 0
                    h4_points += 1
                    first_time = when if first_time is None else min(first_time, when)
                    last_time = when if last_time is None else max(last_time, when)
                except (ValueError, OverflowError):
                    malformed_npt += 1
            elif kind == "H8":
                if h4_start is None:
                    raise ValueError(f"H8 end-of-session without an open H4 session: {relative}")
                sessions_with_npt += h4_points > 0
                sessions_without_npt += h4_points == 0
                h4_start = h4_end = None
                h4_points = 0

        if (h4_start is not None or local["H4"] != local["H8"]
                or local["H1"] != local["H4"] or local["H9"] != 1):
            raise ValueError(f"unexpected CRD pass/file structure in {relative}: {dict(local)}")
        if local["10"]:
            raise ValueError(f"normal-point file unexpectedly contains full-rate records: {relative}")
        per_file.append({"file": relative, "h4_session_headers": local["H4"],
                         "normal_point_rows": local["11"],
                         "session_start_utc": first_session_start.isoformat() if first_session_start else None,
                         "session_end_utc": last_session_end.isoformat() if last_session_end else None,
                         "first_normal_point_utc": first_time.isoformat() if first_time else None,
                         "last_normal_point_utc": last_time.isoformat() if last_time else None})

    # Check how zero-rate points are represented in the normalized source table.
    zero_rows_with_range = 0
    with (base / "normal_points.csv").open(newline="", encoding="utf-8-sig") as stream:
        for row in csv.DictReader(stream):
            try:
                rate = float(row["return_rate_percent"])
                tof = float(row["time_of_flight_seconds"])
                raw_ranges = int(row["number_of_raw_ranges"])
            except (TypeError, ValueError):
                continue
            if rate == 0.0 and tof > 0 and raw_ranges > 0:
                zero_rows_with_range += 1

    if malformed_h4 or malformed_npt or hash_mismatches:
        raise ValueError(
            "raw ILRS audit found integrity failures: "
            f"malformed_h4={malformed_h4}, malformed_npt={malformed_npt}, "
            f"hash_mismatches={len(hash_mismatches)}"
        )
    if npt_rows != sum(item["normal_point_rows"] for item in per_file):
        raise ValueError("normal-point rows do not reconcile to per-file counts")
    if sessions_with_npt != sessions or sessions_without_npt != 0:
        raise ValueError("not every encoded pass session contains a normal-point row")
    if zero_raw_range_rows or zero_rows_with_range != exact_zero_return_rate_rows:
        raise ValueError("normal-point range counts or exact-zero return-rate representation failed validation")

    rates_sorted = sorted(return_rates)
    report = {
        "status": "completed_valid",
        "audited_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source": "raw ILRS/EUROLAS LAGEOS-1 CRD v2 .np2 archive",
        "manifest_files": len(expected),
        "raw_files_scanned": len(raw_paths),
        "raw_file_hash_or_size_mismatches": hash_mismatches,
        "record_type_counts": dict(sorted(record_types.items())),
        "pass_sessions": sessions,
        "pass_sessions_with_normal_points": sessions_with_npt,
        "pass_sessions_without_normal_points": sessions_without_npt,
        "normal_point_rows": npt_rows,
        "normal_point_rows_with_positive_raw_range_count": positive_raw_range_rows,
        "normal_point_rows_with_zero_raw_range_count": zero_raw_range_rows,
        "normal_point_rows_with_missing_return_rate": missing_return_rate_rows,
        "normal_point_rows_with_invalid_return_rate": invalid_return_rate_rows,
        "normal_point_rows_outside_h4_session_bounds": npt_outside_session_rows,
        "normal_point_rows_with_exact_zero_return_rate": exact_zero_return_rate_rows,
        "exact_zero_rate_rows_also_have_positive_range_count_and_tof": zero_rows_with_range,
        "total_raw_ranges_after_editing": raw_range_total,
        "valid_return_rate_observations": len(rates_sorted),
        "return_rate_percent_quantiles": {
            "p10": rates_sorted[round(.10*(len(rates_sorted)-1))] if rates_sorted else None,
            "median": rates_sorted[round(.50*(len(rates_sorted)-1))] if rates_sorted else None,
            "p90": rates_sorted[round(.90*(len(rates_sorted)-1))] if rates_sorted else None,
        },
        "missed_acquisition_denominator_available": False,
        "denominator_finding": (
            "The archive contains only CRD normal-point records inside pass sessions that were reported. "
            "Every encoded H4 pass session contains at least one type-11 range record; every normal point "
            "has a positive accepted raw-range count. No planned-pass, scheduled-shot, zero-return-bin, "
            "or no-acquisition status ledger is present. Exact-zero return-rate normal points still have "
            "a measured time of flight and positive accepted range count, so they are low-yield measurements, "
            "not missed acquisitions."
        ),
        "limitations": [
            "H4 pass/session bounds describe reported observation sessions and do not enumerate all geometric or planned passes.",
            "Some CRD normal-point seconds-of-day fall outside their associated H4 bounds and need source/session reconciliation before timing-sensitive sensor analyses.",
            "Return rate measures photon yield during acquired measurements; it is not the probability of acquiring a pass.",
            "The LAGEOS-1 ground-laser result does not calibrate onboard optical sensors or all satellites.",
        ],
        "files": per_file,
    }
    if output is None:
        output = base / "opportunity_coverage_audit.json"
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_suffix(output.suffix + ".tmp")
    temp.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    temp.replace(output)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=BASE)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = audit(args.data, args.output)
    print(json.dumps({key: value for key, value in report.items() if key != "files"}, indent=2))


if __name__ == "__main__":
    main()
