#!/usr/bin/env python3
"""Independently audit dense historical SGP4-to-ILRS-CPF comparisons."""
from __future__ import annotations

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))


import bisect
import csv
import datetime as dt
import hashlib
import json
import math
import pathlib
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.analysis.compare_sgp4_with_ilrs_cpf import load_history

TARGETS = {"lageos1": 8820, "lageos2": 22195, "lares": 38077, "starlette": 7646}
DATA = ROOT / "data/ground_sensor"
OUT = ROOT / "outputs/dense-sgp4-cpf-validation-2022-2026"
MAX_AGE_HOURS = 72.0


def sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def parse_utc(value: str) -> dt.datetime:
    instant = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    return instant if instant.tzinfo else instant.replace(tzinfo=dt.timezone.utc)


def audit() -> dict:
    target_results = []
    total_rows = 0
    for slug, norad in TARGETS.items():
        folder = DATA / f"ilrs_{slug}_npt"
        summary_path = folder / "orbit_model_comparison_summary.json"
        csv_path = folder / "orbit_model_comparison.csv"
        normal_points = folder / "normal_points.csv"
        cpf_manifest = folder / "cpf_manifest.json"
        summary = json.loads(summary_path.read_text())
        if summary.get("status") != "completed" or int(summary.get("target_norad_id", -1)) != norad:
            raise ValueError(f"Incomplete or mismatched dense comparison for {slug}")
        epochs, records, _, _ = load_history(norad)
        errors = []
        ages = []
        dates = set()
        seen = {}
        row_count = 0
        with csv_path.open(newline="") as stream:
            for row in csv.DictReader(stream):
                row_count += 1
                when = parse_utc(row["observation_time_utc"])
                epoch = parse_utc(row["historical_element_epoch_utc"])
                index = bisect.bisect_right(epochs, when) - 1
                if index < 0 or epochs[index] != epoch:
                    raise ValueError(f"TLE selection mismatch for {slug} row {row_count}")
                age_hours = (when - epoch).total_seconds() / 3600.0
                if age_hours > MAX_AGE_HOURS + 1e-10:
                    raise ValueError(f"Stale element in accepted {slug} row {row_count}")
                if not math.isclose(age_hours, float(row["historical_element_age_hours"]),
                                    rel_tol=0, abs_tol=2e-10):
                    raise ValueError(f"TLE age mismatch for {slug} row {row_count}")
                key = (row["observation_time_utc"], row["station_name"], row["station_sod"], row["cpf_file"])
                seen[key] = seen.get(key, 0) + 1
                sgp = np.asarray([float(row[f"sgp4_itrf_{axis}_km"]) for axis in "xyz"])
                cpf = np.asarray([float(row[f"cpf_itrf_{axis}_km"]) for axis in "xyz"])
                actual = float(np.linalg.norm(sgp - cpf))
                if not math.isclose(actual, float(row["position_separation_km"]),
                                    rel_tol=0, abs_tol=1e-9):
                    raise ValueError(f"Position error does not recompute for {slug} row {row_count}")
                errors.append(actual)
                ages.append(age_hours)
                dates.add(when.date().isoformat())
        if row_count != int(summary["compared_observations"]):
            raise ValueError(f"Dense row count differs from summary for {slug}")
        values = np.asarray(errors)
        ordered = np.sort(values)
        metrics = {
            "median_km": float(np.median(values)),
            "mean_km": float(np.mean(values)),
            "p95_km": float(ordered[int(.95 * len(ordered))]),
            "p99_km": float(ordered[int(.99 * len(ordered))]),
        }
        stored = summary["sgp4_minus_cpf_position_separation_km"]
        for key, value in metrics.items():
            if not math.isclose(value, float(stored[key.removesuffix("_km")]), rel_tol=0, abs_tol=1e-9):
                raise ValueError(f"Dense SGP4/CPF {key} mismatch for {slug}")
        target_results.append({
            "target": slug, "norad_id": norad, "rows_checked": row_count,
            "date_clusters": len(dates), "duplicate_source_keys": sum(n - 1 for n in seen.values()),
            "maximum_element_age_hours": float(max(ages)),
            "metrics": metrics,
            "source_sha256": {
                "normal_points.csv": sha256(normal_points),
                "cpf_manifest.json": sha256(cpf_manifest),
                "orbit_model_comparison.csv": sha256(csv_path),
                "orbit_model_comparison_summary.json": sha256(summary_path),
            },
        })
        total_rows += row_count
    result = {
        "status": "passed_dense_source_epoch_and_position_reproduction",
        "scope": "Four independently rerun full-available-coverage GP/TLE SGP4-to-ILRS CPF comparisons. The audit independently reselects the latest archived TLE at every observation time, verifies age and position-separation calculations, and recomputes summary metrics for every saved row.",
        "max_element_age_hours": MAX_AGE_HOURS,
        "target_count": len(target_results), "response_rows_checked": total_rows,
        "targets": target_results,
        "interpretation": "CPF operational prediction products are a strong external consistency reference but not independent orbit truth. Results cover these four laser-ranged objects and the available CRD/CPF overlap; they do not establish accuracy for the full satellite catalog or other orbit classes.",
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "independent_audit.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "response_rows_checked": total_rows,
                      "targets": [{"target": r["target"], "rows": r["rows_checked"],
                                   "metrics": r["metrics"]} for r in target_results]}, indent=2))
    return result


if __name__ == "__main__":
    audit()
