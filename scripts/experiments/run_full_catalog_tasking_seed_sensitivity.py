"""Run an independent random-seed sensitivity over the full monthly catalog grid.

The primary full-catalog tasking run remains immutable. This adds a second
paired random stream at each of its 48 historical dates and four host regimes.
"""
from __future__ import annotations

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))


import csv
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from godsat.dropout import monthly_dates
from godsat.orbits import History
from scripts.experiments.run_full_catalog_tasking import (
    OUTAGE_RATES, REGIMES, host_ids_by_regime, read_inputs, sha256,
    simulate_condition,
)

PRIMARY = ROOT / "outputs/full-catalog-tasking-monthly-2022-2026"
OUTPUT = ROOT / "outputs/full-catalog-tasking-seed-sensitivity-2022-2026"
SEED = 90210


def write_csv(path: Path, rows: list[dict]) -> None:
    columns = [k for k, v in rows[0].items() if not isinstance(v, (dict, list))]
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows([{k: row.get(k) for k in columns} for row in rows])


def run() -> dict:
    primary_path = PRIMARY / "summary.json"
    primary = json.loads(primary_path.read_text())
    dates = monthly_dates()
    if primary.get("status") != "completed" or primary.get("dates") != dates:
        raise ValueError("Primary full-catalog run is not complete on the monthly grid")
    config_path = ROOT / "outputs/all-orbits-paper-exact-active-hosts/config.json"
    config = json.loads(config_path.read_text())
    config.update(duration_minutes=60, step_seconds=60, propagation_model="sgp4")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    scenario_hashes: dict[str, dict[str, str]] = {}
    metadata_hashes: dict[str, dict[str, str]] = {}
    history = History(ROOT, "all")
    try:
        for date_index, date in enumerate(dates):
            print(f"Loading full-catalog states for {date}", flush=True)
            ids, states, ages, valid, times = read_inputs(date, history, config)
            hosts, hashes, meta_hashes = host_ids_by_regime(date, config)
            scenario_hashes[date] = hashes
            metadata_hashes[date] = meta_hashes
            for regime_index, regime in enumerate(REGIMES):
                for rate in OUTAGE_RATES:
                    row = simulate_condition(date_index, regime_index, rate, ids,
                        states, ages, valid, times, hosts[regime], config, seed=SEED)
                    row["simulation_seed"] = SEED
                    rows.append(row)
                print(f"{date} {regime}: paired 0/20% burst episodes complete", flush=True)
    finally:
        history.db.close()
    result = {
        "status": "completed",
        "scope": "Independent-seed replication of all fresh/valid catalog targets on the complete 48-date monthly grid; four host regimes; paired zero and 20% burst-loss one-hour episodes.",
        "seed": SEED,
        "dates": dates,
        "regimes": list(REGIMES),
        "outage_rates": list(OUTAGE_RATES),
        "config": config,
        "config_sha256": sha256(config_path),
        "raw_archive_manifest_sha256": sha256(ROOT / "data/raw/manifest.json"),
        "primary_summary_sha256": sha256(primary_path),
        "primary_integrity_audit_sha256": sha256(PRIMARY / "independent_audit.json"),
        "scenario_cache_sha256": scenario_hashes,
        "scenario_metadata_sha256": metadata_hashes,
        "response_rows": rows,
        "limits": [
            "This seed sensitivity does not alter the original study results.",
            "Sensor hosts are current active payloads backcast through the historical period.",
            "Outages are injected; natural sensor-attempt and failure logs are unavailable.",
            "Episodes sample one hour per month rather than continuous operations.",
        ],
    }
    (OUTPUT / "seed_sensitivity.json").write_text(json.dumps(result, indent=2) + "\n")
    write_csv(OUTPUT / "seed_sensitivity.csv", rows)
    return result


if __name__ == "__main__":
    data = run()
    print(json.dumps({"status": data["status"], "output": str(OUTPUT),
        "dates": len(data["dates"]), "rows": len(data["response_rows"]),
        "seed": data["seed"]}, indent=2))
