"""Independently check the additional full-catalog random-seed campaign."""
from __future__ import annotations

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))


import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import sys

import numpy as np
from scipy.stats import t as student_t

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from godsat.dropout import monthly_dates
from godsat.scenario import cache_key
from scripts.experiments.run_full_catalog_tasking import REGIMES

PRIMARY = ROOT / "outputs/full-catalog-tasking-monthly-2022-2026"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def effects_by_regime(rows: list[dict], rates: tuple[float, float] = (0.0, 0.2)) -> list[dict]:
    indexed = {}
    for row in rows:
        key = (row["date"], row["orbit_regime_sensor_hosts"],
               int(row.get("simulation_seed", -1)), float(row["requested_outage_rate"]))
        if key in indexed:
            raise ValueError(f"Duplicate seed response row {key}")
        indexed[key] = row
    dates = monthly_dates()
    result = []
    for regime in REGIMES:
        date_effects = []
        for date in dates:
            a = indexed[(date, regime, 90210, rates[0])]
            b = indexed[(date, regime, 90210, rates[1])]
            date_effects.append({
                "date": date,
                "custody_change_20pct_minus_0": b["custody_continuity"] - a["custody_continuity"],
                "observable_custody_change_20pct_minus_0": b["observable_custody"] - a["observable_custody"],
                "slew_proxy_change_20pct_minus_0": b["mean_slew_energy_proxy"] - a["mean_slew_energy_proxy"],
            })
        metrics = {}
        for name in ("custody_change_20pct_minus_0", "observable_custody_change_20pct_minus_0",
                     "slew_proxy_change_20pct_minus_0"):
            sample = np.asarray([r[name] for r in date_effects])
            mean = float(sample.mean())
            half = float(student_t.ppf(.975, len(sample)-1) * sample.std(ddof=1) / math.sqrt(len(sample)))
            metrics[name] = {"n_date_clusters": len(sample), "mean": mean,
                             "ci95_date_clustered": [mean-half, mean+half]}
        result.append({"sensor_host_regime": regime, **metrics, "date_effects": date_effects})
    return result


def seed_comparison(rows: list[dict], primary_rows: list[dict]) -> list[dict]:
    from scipy.stats import t as student_t
    newer = {(r["date"], r["orbit_regime_sensor_hosts"], float(r["requested_outage_rate"])): r
             for r in rows}
    original = {(r["date"], r["orbit_regime_sensor_hosts"], float(r["requested_outage_rate"])): r
                for r in primary_rows}
    output = []
    for regime in REGIMES:
        changes = []
        for date in monthly_dates():
            old0, old1 = original[(date, regime, 0.0)], original[(date, regime, 0.2)]
            new0, new1 = newer[(date, regime, 0.0)], newer[(date, regime, 0.2)]
            for metric in ("custody_continuity", "observable_custody"):
                changes.append({"date": date, "metric": metric,
                    "primary_seed_dropout_effect": old1[metric]-old0[metric],
                    "replication_seed_dropout_effect": new1[metric]-new0[metric],
                    "seed_interaction": (new1[metric]-new0[metric])-(old1[metric]-old0[metric])})
        summary = {}
        for metric in ("custody_continuity", "observable_custody"):
            sample = np.asarray([r["seed_interaction"] for r in changes if r["metric"] == metric])
            mean = float(sample.mean())
            half = float(student_t.ppf(.975, len(sample)-1)*sample.std(ddof=1)/math.sqrt(len(sample)))
            summary[metric] = {"seed_interaction_mean": mean,
                "seed_interaction_ci95_date_clustered": [mean-half, mean+half]}
        output.append({"sensor_host_regime": regime, "metrics": summary, "date_effects": changes})
    return output


def audit(output: Path) -> dict:
    path = output / "seed_sensitivity.json"
    data = json.loads(path.read_text())
    dates = monthly_dates()
    if data.get("status") != "completed" or data.get("seed") != 90210 or data.get("dates") != dates:
        raise ValueError("Seed sensitivity campaign is incomplete or has wrong design")
    primary_path = PRIMARY / "summary.json"
    primary_audit_path = PRIMARY / "independent_audit.json"
    if (data.get("primary_summary_sha256") != sha256(primary_path)
            or data.get("primary_integrity_audit_sha256") != sha256(primary_audit_path)):
        raise ValueError("Seed campaign primary-run provenance is stale")
    primary_audit = json.loads(primary_audit_path.read_text())
    if primary_audit.get("status") != "passed_structural_and_statistical":
        raise ValueError("Primary full-catalog run lacks its passing independent audit")
    config_path = ROOT / "outputs/all-orbits-paper-exact-active-hosts/config.json"
    config = json.loads(config_path.read_text())
    config.update(duration_minutes=60, step_seconds=60, propagation_model="sgp4")
    if data.get("config") != config or data.get("config_sha256") != sha256(config_path):
        raise ValueError("Seed campaign configuration differs from the primary campaign")
    if data.get("raw_archive_manifest_sha256") != sha256(ROOT / "data/raw/manifest.json"):
        raise ValueError("Raw orbit-history archive manifest hash mismatch")
    rows = data.get("response_rows", [])
    expected = {(date, regime, rate) for date in dates for regime in REGIMES for rate in (0.0, 0.2)}
    indexed = {}
    for row in rows:
        key = (row["date"], row["orbit_regime_sensor_hosts"], float(row["requested_outage_rate"]))
        if key not in expected or key in indexed or row.get("simulation_seed") != 90210:
            raise ValueError(f"Unexpected, duplicate, or mis-seeded response row: {key}")
        if row.get("step_count") != 60 or row.get("step_seconds") != 60:
            raise ValueError(f"Unexpected episode grid: {key}")
        if len(row.get("sensor_host_ids", [])) != 6 or len(set(row["sensor_host_ids"])) != 6:
            raise ValueError(f"Invalid host list: {key}")
        if not (0 <= row["detections"] <= row["sensor_actions"] <= 360):
            raise ValueError(f"Invalid action and detection counts: {key}")
        if not (0 <= row["dropout_misses"] <= row["dropout_trials"] <= row["sensor_actions"]):
            raise ValueError(f"Invalid dropout accounting: {key}")
        for name in ("custody_continuity", "observable_custody", "valid_target_fraction",
                     "observed_dropout_rate", "mean_slew_energy_proxy"):
            val = float(row[name])
            if not math.isfinite(val) or not 0 <= val <= 1:
                if name != "mean_slew_energy_proxy" or not math.isfinite(val) or val < 0:
                    raise ValueError(f"Invalid metric {name}: {key}")
        indexed[key] = row
    if set(indexed) != expected:
        raise ValueError(f"Seed response design incomplete: {len(indexed)}/{len(expected)}")

    primary = json.loads(primary_path.read_text())
    primary_rows = {(r["date"], r["orbit_regime_sensor_hosts"], float(r["requested_outage_rate"])): r
                    for r in primary["rows"]}
    for date in dates:
        for regime in REGIMES:
            cache_hash = data["scenario_cache_sha256"].get(date, {}).get(regime)
            metadata_hash = data["scenario_metadata_sha256"].get(date, {}).get(regime)
            scenario = ROOT / "data/scenarios" / f"{cache_key(date, config, regime)}.npz"
            metadata = scenario.with_suffix(".json")
            if not scenario.is_file() or sha256(scenario) != cache_hash:
                raise ValueError(f"Scenario cache provenance failed for {date} {regime}")
            if not metadata.is_file() or sha256(metadata) != metadata_hash:
                raise ValueError(f"Scenario metadata provenance failed for {date} {regime}")
            host_ids = list(map(int, json.loads(metadata.read_text()).get("agents", [])))
            for rate in (0.0, 0.2):
                key = (date, regime, rate)
                if indexed[key]["sensor_host_ids"] != host_ids:
                    raise ValueError(f"Response hosts disagree with source scenario for {key}")
                baseline = primary_rows[key]
                if baseline["sensor_host_ids"] != host_ids:
                    raise ValueError(f"Primary hosts disagree with source scenario for {key}")

    csv_path = output / "seed_sensitivity.csv"
    with csv_path.open(newline="") as stream:
        csv_rows = list(csv.DictReader(stream))
    if len(csv_rows) != len(rows):
        raise ValueError("CSV response row count differs from JSON")
    for csv_row in csv_rows:
        key = (csv_row["date"], csv_row["orbit_regime_sensor_hosts"], float(csv_row["requested_outage_rate"]))
        if key not in indexed:
            raise ValueError(f"Unexpected CSV row {key}")
        for name, value in csv_row.items():
            expected_value = indexed[key].get(name)
            if isinstance(expected_value, (int, float)):
                if not math.isclose(float(value), float(expected_value), rel_tol=0, abs_tol=1e-12):
                    raise ValueError(f"CSV/JSON mismatch for {key} {name}")
            elif str(expected_value) != value:
                raise ValueError(f"CSV/JSON mismatch for {key} {name}")

    effects = effects_by_regime(rows)
    interactions = seed_comparison(rows, primary["rows"])
    report = {
        "status": "passed_source_design_and_statistical_reproduction",
        "scope": "Independent structural, hash, and aggregation audit. It does not rerun orbit propagation or task assignment.",
        "seed": 90210,
        "dates_checked": len(dates),
        "regimes_checked": len(REGIMES),
        "paired_date_regime_cells_checked": len(dates) * len(REGIMES),
        "response_rows_checked": len(rows),
        "scenario_cache_hashes_verified": len(dates) * len(REGIMES),
        "date_clustered_effects": effects,
        "seed_by_outage_interaction": interactions,
        "checks": {"complete_monthly_grid": True, "paired_outage_conditions": True,
                   "matches_primary_source_and_hosts": True, "scenario_hashes": True,
                   "response_invariants": True, "CSV_JSON_reconciliation": True,
                   "date_clustered_intervals_recomputed": True,
                   "paired_seed_by_outage_interactions_recomputed": True},
    }
    (output / "independent_audit.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/full-catalog-tasking-seed-sensitivity-2022-2026")
    args = parser.parse_args()
    output = args.output if args.output.is_absolute() else ROOT / args.output
    result = audit(output)
    print(json.dumps({"status": result["status"], "response_rows": result["response_rows_checked"],
                      "dates": result["dates_checked"]}, indent=2))
