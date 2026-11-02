"""Compare saved AWP J2 and J2+Sun/Moon trajectory states on the monthly grid."""
from __future__ import annotations

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))


import argparse
import hashlib
import json
import pathlib
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from godsat.dropout import monthly_dates
from godsat.scenario import cache_key

REGIMES = ("leo", "meo", "geo", "heo")


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run(output: pathlib.Path) -> dict:
    j2_dir = ROOT / "outputs/awp-policy-monthly-validation-2022-2026"
    third_dir = ROOT / "outputs/awp-sun-moon-monthly-validation-2022-2026"
    j2_summary_path = j2_dir / "summary.json"
    third_summary_path = third_dir / "summary.json"
    j2_summary = json.loads(j2_summary_path.read_text())
    third_summary = json.loads(third_summary_path.read_text())
    dates = monthly_dates()
    failures = []
    for label, summary, model in (("J2", j2_summary, "awp_j2"),
                                  ("Sun/Moon", third_summary, "awp_j2_sun_moon")):
        if summary.get("status") != "completed" or summary.get("dates") != dates:
            failures.append(f"{label} comparison summary is incomplete or has a different date grid")
        if summary.get("comparison_model", "awp_j2") != model:
            failures.append(f"{label} comparison model metadata mismatch")
    if j2_summary.get("config") != third_summary.get("config"):
        failures.append("J2 and Sun/Moon comparison configs differ")

    config = third_summary["config"]
    all_deltas = []
    by_regime = {regime: [] for regime in REGIMES}
    cache_checks = 0
    for date in dates:
        for regime in REGIMES:
            key = f"{date}|{regime}"
            states = {}
            for model, summary, summary_dir, hash_key in (
                ("awp_j2", j2_summary, j2_dir, "awp_scenario_sha256"),
                ("awp_j2_sun_moon", third_summary, third_dir,
                 "awp_j2_sun_moon_scenario_sha256"),
            ):
                scenario_config = {**config, "propagation_model": model}
                path = ROOT / "data/scenarios" / (cache_key(date, scenario_config, regime) + ".npz")
                metadata_path = path.with_suffix(".json")
                if not path.is_file() or not metadata_path.is_file():
                    failures.append(f"missing {model} scenario cache for {date} {regime}")
                    continue
                expected_hash = summary.get("scenario_cache_sha256", {}).get(key, {}).get(hash_key)
                if expected_hash is None or sha256(path) != expected_hash:
                    failures.append(f"{model} cache hash mismatch for {date} {regime}")
                metadata = json.loads(metadata_path.read_text())
                if metadata.get("date") != date or metadata.get("orbit_regime") != regime:
                    failures.append(f"{model} cache metadata mismatch for {date} {regime}")
                if metadata.get("frame") != "GCRS":
                    failures.append(f"{model} cache is not in GCRS for {date} {regime}")
                description = metadata.get("propagation_model", "")
                if model == "awp_j2_sun_moon" and "solar/lunar point-mass gravity" not in description:
                    failures.append(f"Sun/Moon force description missing for {date} {regime}")
                with np.load(path, allow_pickle=False) as data:
                    states[model] = {name: data[name] for name in ("states", "ids", "times")}
                cache_checks += 1
            if set(states) != {"awp_j2", "awp_j2_sun_moon"}:
                continue
            j2, third = states["awp_j2"], states["awp_j2_sun_moon"]
            if not np.array_equal(j2["ids"], third["ids"]):
                failures.append(f"selected object IDs differ for {date} {regime}")
                continue
            if not np.array_equal(j2["times"], third["times"]):
                failures.append(f"time grids differ for {date} {regime}")
                continue
            a, b = j2["states"], third["states"]
            if a.shape != b.shape or a.ndim != 3 or a.shape[2] != 6:
                failures.append(f"state dimensions differ for {date} {regime}")
                continue
            valid = np.isfinite(a[:, :, :3]).all(axis=2) & np.isfinite(b[:, :, :3]).all(axis=2)
            if not valid.any():
                failures.append(f"no matched finite states for {date} {regime}")
                continue
            delta = np.linalg.norm(a[:, :, :3][valid] - b[:, :, :3][valid], axis=1)
            all_deltas.extend(delta.tolist())
            by_regime[regime].extend(delta.tolist())

    def describe(values):
        array = np.asarray(values, dtype=float)
        return {"matched_states": int(len(array)),
                "median_position_separation_km": float(np.median(array)),
                "p95_position_separation_km": float(np.quantile(array, 0.95)),
                "maximum_position_separation_km": float(np.max(array))}

    expected_cache_count = len(dates) * len(REGIMES) * 2
    if cache_checks != expected_cache_count:
        failures.append(f"checked {cache_checks} of {expected_cache_count} scenario caches")
    result = {
        "status": "passed" if not failures else "failed",
        "comparison": "AWP two-body + J2 versus AWP two-body + J2 + Sun/Moon point-mass gravity",
        "date_count": len(dates),
        "dates": dates,
        "regimes": list(REGIMES),
        "scenario_cache_hashes_checked": cache_checks,
        "source_summaries": {
            "awp_j2_sha256": sha256(j2_summary_path),
            "awp_j2_sun_moon_sha256": sha256(third_summary_path),
        },
        "all_regimes": describe(all_deltas) if all_deltas else None,
        "by_regime": {regime: describe(values) for regime, values in by_regime.items()},
        "interpretation": "Force-model separation over the same one-hour GCRS arcs; neither model is independent orbit truth.",
        "failures": failures,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=pathlib.Path,
        default=ROOT / "outputs/awp-sun-moon-monthly-validation-2022-2026/force_model_separation_audit.json")
    args = parser.parse_args()
    result = run(args.output)
    print(json.dumps({key: result[key] for key in
        ("status", "date_count", "scenario_cache_hashes_checked", "all_regimes", "by_regime", "failures")}, indent=2))
    if result["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
