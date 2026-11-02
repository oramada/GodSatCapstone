"""Relate ILRS-measured LAGEOS return rates to CPF range residual quality.

This is a conditional sensor-quality analysis of normal points recorded during
acquired passes. A CRD return-rate value is not a missed-acquisition label.
"""

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
import pathlib
import random
import statistics


ROOT = pathlib.Path(__file__).resolve().parents[2]
BASE = ROOT / "data/ground_sensor/ilrs_lageos1_npt"
DEFAULT_NORMAL_POINTS = BASE / "normal_points.csv"
DEFAULT_RANGE_VALIDATION = BASE / "range_validation.csv"
DEFAULT_OUTPUT = BASE / "return_quality_analysis.json"
RETURN_RATE_VALID_RANGE = (0.0, 100.0)
MAX_RANGE_MATCH_DIFFERENCE_M = 25.0


def _digest(path):
    h = hashlib.sha256()
    with pathlib.Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _key(row):
    timestamp = (row.get("observation_time_utc") or "").strip()
    if not timestamp:
        return None
    return (row.get("source_file", ""), timestamp,
            (row.get("station_name") or "").strip(),
            (row.get("epoch_event") or "").strip())


def _float(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _quantiles(values):
    ordered = sorted(values)
    if not ordered:
        return {"count": 0}
    return {"count": len(ordered), "median": statistics.median(ordered),
            "p95": ordered[min(len(ordered)-1, round(.95*(len(ordered)-1)))],
            "mean": statistics.fmean(ordered)}


def _bootstrap_cluster_mean(values_by_cluster, replicates, seed):
    """Cluster-bootstrap the equally weighted mean of paired station-day effects."""
    values = [float(v) for v in values_by_cluster if math.isfinite(float(v))]
    if not values:
        return {"clusters": 0, "mean": None, "ci95": [None, None]}
    rng = random.Random(seed)
    n = len(values)
    draws = [statistics.fmean(values[rng.randrange(n)] for _ in range(n))
             for _ in range(replicates)]
    draws.sort()
    return {"clusters": n, "mean": statistics.fmean(values),
            "ci95": [draws[int(.025*(replicates-1))],
                     draws[int(.975*(replicates-1))]],
            "unit": "m"}


def analyze(normal_points_path=DEFAULT_NORMAL_POINTS,
            range_validation_path=DEFAULT_RANGE_VALIDATION,
            output_path=DEFAULT_OUTPUT, replicates=5000, seed=26010):
    normal_points_path = pathlib.Path(normal_points_path)
    range_validation_path = pathlib.Path(range_validation_path)
    output_path = pathlib.Path(output_path)
    target = normal_points_path.parent.name.removeprefix("ilrs_").removesuffix("_npt").upper()
    if replicates < 100:
        raise ValueError("replicates must be at least 100")

    normals = {}
    normal_rows = blank_time_rows = 0
    with normal_points_path.open(newline="", encoding="utf-8-sig") as stream:
        for row in csv.DictReader(stream):
            normal_rows += 1
            key = _key(row)
            if key is None:
                blank_time_rows += 1
                continue
            range_km = _float(row.get("two_way_range_km_from_time_of_flight"))
            rate = _float(row.get("return_rate_percent"))
            if range_km is None:
                continue
            normals.setdefault(key, []).append({
                "range_m": range_km * 1000.0,
                "return_rate_percent": rate,
                "used": False,
            })

    joined = []
    range_rows = no_exact_key = no_range_match = 0
    duplicate_candidates = duplicate_pairs_resolved = 0
    with range_validation_path.open(newline="", encoding="utf-8-sig") as stream:
        for row in csv.DictReader(stream):
            range_rows += 1
            key = _key(row)
            candidates = normals.get(key, []) if key else []
            if not candidates:
                no_exact_key += 1
                continue
            observed = _float(row.get("observed_one_way_equivalent_range_m"))
            residual = _float(row.get("range_residual_with_dhf_biases_m"))
            if observed is None or residual is None:
                continue
            available = [candidate for candidate in candidates if not candidate["used"]]
            if len(candidates) > 1:
                duplicate_candidates += 1
            if not available:
                no_range_match += 1
                continue
            closest = min(available,
                          key=lambda item: abs(item["range_m"] - observed))
            difference = abs(closest["range_m"] - observed)
            if difference > MAX_RANGE_MATCH_DIFFERENCE_M:
                no_range_match += 1
                continue
            closest["used"] = True
            if len(candidates) > 1:
                duplicate_pairs_resolved += 1
            timestamp = row["observation_time_utc"]
            joined.append({
                "station": row["station_name"].strip(),
                "date": timestamp[:10],
                "return_rate_percent": closest["return_rate_percent"],
                "absolute_range_residual_m": abs(residual),
                "range_residual_m": residual,
                "match_difference_m": difference,
                "data_quality_alert": (row.get("data_quality_alert") or "").strip(),
            })

    invalid_rate_rows = [row for row in joined
        if row["return_rate_percent"] is not None
        and not (RETURN_RATE_VALID_RANGE[0] <= row["return_rate_percent"]
                 <= RETURN_RATE_VALID_RANGE[1])]
    valid = [row for row in joined
        if row["return_rate_percent"] is not None
        and RETURN_RATE_VALID_RANGE[0] <= row["return_rate_percent"]
        <= RETURN_RATE_VALID_RANGE[1]
        and row["absolute_range_residual_m"] <= 100.0]

    bands = [("0_to_lt_1", 0.0, 1.0), ("1_to_lt_5", 1.0, 5.0),
             ("5_to_lt_10", 5.0, 10.0), ("10_to_lt_25", 10.0, 25.0),
             ("25_to_lt_50", 25.0, 50.0), ("50_to_100", 50.0, 100.0000001)]
    band_summary = []
    for name, lower, upper in bands:
        group = [row for row in valid
                 if lower <= row["return_rate_percent"] < upper]
        band_summary.append({"return_rate_band_percent": name,
            "normal_points": len(group),
            "absolute_range_residual_m": _quantiles(
                [row["absolute_range_residual_m"] for row in group]),
            "signed_range_residual_m": _quantiles(
                [row["range_residual_m"] for row in group])})

    # Paired station-day comparison controls for persistent site differences
    # and broad nightly conditions. It remains observational and not causal.
    cluster_values = {}
    low_rate = []
    high_rate = []
    for row in valid:
        cluster = (row["station"], row["date"])
        values = cluster_values.setdefault(cluster, {"low": [], "high": []})
        if row["return_rate_percent"] < 1.0:
            values["low"].append(row["absolute_range_residual_m"])
            low_rate.append(row["absolute_range_residual_m"])
        elif row["return_rate_percent"] >= 10.0:
            values["high"].append(row["absolute_range_residual_m"])
            high_rate.append(row["absolute_range_residual_m"])
    paired_differences = [statistics.fmean(item["low"])-statistics.fmean(item["high"])
        for item in cluster_values.values() if item["low"] and item["high"]]
    paired = _bootstrap_cluster_mean(paired_differences, replicates, seed)
    paired["contrast"] = "within station-day mean absolute residual: <1% minus >=10% return rate"
    paired["low_return_points"] = len(low_rate)
    paired["high_return_points"] = len(high_rate)
    paired["low_return_overall_mean_absolute_residual_m"] = (
        statistics.fmean(low_rate) if low_rate else None)
    paired["high_return_overall_mean_absolute_residual_m"] = (
        statistics.fmean(high_rate) if high_rate else None)

    result = {
        "status": "completed",
        "study": f"Observed ILRS {target} return-rate and CPF range-residual association",
        "inputs": {
            str(normal_points_path): {"rows": normal_rows,
                "sha256": _digest(normal_points_path)},
            str(range_validation_path): {"rows": range_rows,
                "sha256": _digest(range_validation_path)},
        },
        "join": {
            "key": ["source_file", "observation_time_utc", "station_name", "epoch_event"],
            "range_value_tie_break": "nearest two-way-range-derived one-way range to the CPF-validation observed range",
            "maximum_range_difference_m": MAX_RANGE_MATCH_DIFFERENCE_M,
            "normal_point_rows_without_timestamp": blank_time_rows,
            "range_rows_without_exact_key": no_exact_key,
            "range_rows_without_unique_range_match": no_range_match,
            "range_rows_with_duplicate_normal_point_candidates": duplicate_candidates,
            "duplicate_pairs_resolved_by_range": duplicate_pairs_resolved,
            "joined_rows": len(joined),
        },
        "validity": {
            "crd_v2_return_rate_range_percent": [0, 100],
            "return_rates_outside_spec_excluded": len(invalid_rate_rows),
            "return_rate_missing_or_invalid_rows_excluded": len(joined)-sum(
                row["return_rate_percent"] is not None
                and 0.0 <= row["return_rate_percent"] <= 100.0 for row in joined),
            "absolute_range_residual_over_100m_excluded": sum(
                row["return_rate_percent"] is not None
                and 0.0 <= row["return_rate_percent"] <= 100.0
                and row["absolute_range_residual_m"] > 100.0 for row in joined),
            "analyzed_rows": len(valid),
        },
        "return_rate_bands": band_summary,
        "paired_station_day_low_vs_high_return": paired,
        "bootstrap": {"replicates": replicates, "seed": seed,
            "unit": "station-day cluster; equal cluster weighting"},
        "interpretation_limits": [
            "CRD return rate measures valid signal returns within reported normal-point bins during acquired passes; this is not a complete ledger of attempted acquisitions.",
            f"Rows are restricted to recorded {target} normal points with CPF range residuals and CRD return rate within the specification range.",
            "The paired station-day contrast is observational, not causal; pass elevation, range, atmosphere, and other changing conditions may confound it.",
            "CPF residuals are an operational model-consistency reference, not independent orbit truth.",
            "These results do not estimate constellation-wide detection probability, natural sensor outage rates, or GoDSAT custody effectiveness.",
        ],
        "source_documentation": "https://edc.dgfi.tum.de/en/oc/crd/v2/",
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, allow_nan=False)+"\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--normal-points", default=str(DEFAULT_NORMAL_POINTS))
    parser.add_argument("--range-validation", default=str(DEFAULT_RANGE_VALIDATION))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--replicates", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=26010)
    args = parser.parse_args()
    result = analyze(args.normal_points, args.range_validation, args.output,
                     args.replicates, args.seed)
    print(json.dumps({"status": result["status"],
        "joined_rows": result["join"]["joined_rows"],
        "analyzed_rows": result["validity"]["analyzed_rows"],
        "paired_station_days": result["paired_station_day_low_vs_high_return"]["clusters"],
        "low_minus_high_abs_residual_m": result["paired_station_day_low_vs_high_return"]["mean"],
        "ci95": result["paired_station_day_low_vs_high_return"]["ci95"]}, indent=2))


if __name__ == "__main__":
    main()
