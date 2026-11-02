"""Measure monthly visibility from study-selected active hosts to all fresh targets.

This is a catalog-scale geometric census, not learned-policy tasking: the current
policy was trained with 18 target actions and cannot be applied to the full
catalog without a new action-space design and training campaign.
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
from pathlib import Path
from typing import Any
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from godsat.dropout import monthly_dates
from godsat.orbits import EARTH_RADIUS, History, julian, orbit_regime, satellite, utc
from godsat.scenario import cache_key, line_of_sight

REGIMES = ("leo", "meo", "geo", "heo")
REGIME_BINS = REGIMES + ("other", "unknown")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_study_config() -> tuple[dict[str, Any], Path]:
    campaign = ROOT / "outputs/all-orbits-paper-exact-active-hosts"
    config = json.loads((campaign / "config.json").read_text())
    config.update(duration_minutes=60, step_seconds=60, propagation_model="sgp4")
    return config, campaign


def catalog_ids() -> set[int]:
    path = ROOT / "data/history_coverage.csv"
    with path.open(newline="") as stream:
        reader = csv.DictReader(stream)
        field = next((name for name in ("norad_id", "NORAD_CAT_ID") if name in (reader.fieldnames or [])), None)
        if field is None:
            raise ValueError("data/history_coverage.csv has no recognized catalog ID column")
        return {int(row[field]) for row in reader}


def propagate_snapshot(rows: list[dict[str, Any]], when: dt.datetime):
    """Return one successful source-epoch SGP4 state and regime per catalog ID."""
    states: list[list[float]] = []
    ids: list[int] = []
    regimes: list[str] = []
    errors = 0
    for row in rows:
        try:
            error, position, velocity = satellite(row).sgp4(*julian(when))
            if error or not np.isfinite(position + velocity).all():
                errors += 1
                continue
            altitude = float(np.linalg.norm(position) - EARTH_RADIUS)
            if not 150 < altitude < 60_000:
                continue
            ids.append(int(row["norad_id"]))
            states.append([*position, *velocity])
            regimes.append(orbit_regime(row))
        except (KeyError, TypeError, ValueError, OverflowError):
            errors += 1
    return (np.asarray(ids, dtype=np.int64), np.asarray(states, dtype=float),
            np.asarray(regimes, dtype="U8"), errors)


def census(output: Path) -> dict[str, Any]:
    config, campaign = load_study_config()
    history = History(ROOT, "all")
    all_ids = catalog_ids()
    date_rows: list[dict[str, Any]] = []
    groups: list[dict[str, Any]] = []
    cache_hashes: dict[str, str] = {}
    try:
        dates = monthly_dates()
        for date_index, date in enumerate(dates):
            instant = utc(date)
            source_rows = history.snapshot(instant, config["max_element_age_hours"])
            target_ids, target_states, target_regimes, propagation_errors = propagate_snapshot(source_rows, instant)
            state_by_id = {int(object_id): target_states[index, :3]
                           for index, object_id in enumerate(target_ids)}
            regime_by_id = {int(object_id): str(target_regimes[index])
                            for index, object_id in enumerate(target_ids)}
            fresh_host_ids: set[int] = set()
            group_observable: dict[int, set[int]] = {}
            for host_regime in REGIMES:
                path = ROOT / "data/scenarios" / f"{cache_key(date, config, host_regime)}.npz"
                meta_path = path.with_suffix(".json")
                if not path.is_file() or not meta_path.is_file():
                    raise FileNotFoundError(f"Missing cached study scenario for {date} {host_regime}: {path}")
                metadata = json.loads(meta_path.read_text())
                expected_hosts = list(map(int, metadata.get("agents", [])))
                if len(expected_hosts) != int(config["agents"]):
                    raise ValueError(f"Expected {config['agents']} sensor hosts in {date} {host_regime}")
                with np.load(path, allow_pickle=False) as scenario:
                    scenario_ids = scenario["ids"].astype(np.int64)
                    scenario_states = scenario["states"]
                    if not np.array_equal(scenario_ids[:len(expected_hosts)], expected_hosts):
                        raise ValueError(f"Cached scenario host IDs disagree with metadata for {date} {host_regime}")
                    host_positions = scenario_states[0, :len(expected_hosts), :3]
                if not np.isfinite(host_positions).all():
                    raise ValueError(f"Non-finite selected active host position for {date} {host_regime}")
                fresh_host_ids.update(expected_hosts)
                host_observable: set[int] = set()
                if len(target_ids):
                    mask = ~np.isin(target_ids, np.asarray(expected_hosts, dtype=np.int64))
                    ids = target_ids[mask]
                    positions = target_states[mask, :3]
                    delta = positions[None, :, :] - host_positions[:, None, :]
                    ranges = np.linalg.norm(delta, axis=2)
                    visible = line_of_sight(host_positions[:, None, :], positions[None, :, :])
                    visible &= (ranges > 1.0) & (ranges <= float(config["max_range_km"]))
                    host_observable.update(map(int, ids[np.any(visible, axis=0)]))
                group_observable[host_regime] = host_observable
                by_regime: dict[str, int] = {}
                for regime in REGIME_BINS:
                    regime_ids = [oid for oid in host_observable if regime_by_id.get(oid) == regime]
                    by_regime[regime] = len(regime_ids)
                groups.append({
                    "date": date,
                    "host_regime": host_regime,
                    "selected_host_count": len(expected_hosts),
                    "distinct_observable_targets": len(host_observable),
                    "observable_by_target_regime": by_regime,
                    "geometry": "TEME frame, Earth occultation, 6000 km maximum range; full 180 degree field-of-regard approximation; no slew, weather, daylight, or detector model",
                })
                cache_hashes[f"{date}|{host_regime}"] = sha256(path)
            union_observable = set().union(*group_observable.values()) if group_observable else set()
            eligible_ids = set(map(int, target_ids))
            date_rows.append({
                "date": date,
                "archived_catalog_ids": len(all_ids),
                "snapshot_rows_within_freshness_limit": len(source_rows),
                "propagatable_objects": len(target_ids),
                "sgp4_error_or_malformed_rows": propagation_errors,
                "stale_missing_or_out_of_altitude_objects": max(0, len(all_ids) - len(target_ids) - propagation_errors),
                "selected_unique_active_hosts": len(fresh_host_ids),
                "distinct_targets_observable_from_any_selected_host_set": len(union_observable),
                "observable_by_target_regime": {
                    regime: sum(regime_by_id.get(oid) == regime for oid in union_observable)
                    for regime in REGIME_BINS
                },
                "observable_share_of_propagatable_catalog": len(union_observable) / max(1, len(target_ids)),
            })
            print(f"{date}: {len(target_ids):,} propagatable objects; {len(union_observable):,} observable from union of selected hosts", flush=True)
    finally:
        history.db.close()

    manifest_path = ROOT / "data/raw/manifest.json"
    result = {
        "status": "completed" if len(date_rows) == 48 and len(groups) == 192 else "partial",
        "study_dates": dates,
        "date_count": len(date_rows),
        "host_group_count": len(groups),
        "target_cohort": "all archived catalog IDs with a source element no older than the configured 72 hours and a successful SGP4 state at each monthly epoch",
        "host_cohort": "six current-active-payload hosts selected per orbit-regime scenario by the executed DOE study; current status backcast through history",
        "measure": "instantaneous catalog-wide geometric visibility coverage; it is not a time-continuous replay or learned tasking result",
        "study_config_sha256": sha256(campaign / "config.json"),
        "raw_archive_manifest_sha256": sha256(manifest_path),
        "scenario_cache_sha256": cache_hashes,
        "dates": date_rows,
        "host_regime_groups": groups,
        "limits": [
            "Does not extend the policy action space beyond its trained 18 targets.",
            "Uses one monthly snapshot per date and 24 selected hosts at most; does not represent continuous four-year sensor operations.",
            "Uses SGP4 TEME source states and a 6000 km geometric range; no weather, daylight, acquisition schedule, or calibrated sensor probability is available.",
            "A current active-host snapshot backcast through earlier years does not establish historical operations.",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/all-catalog-visibility-census-2022-2026/summary.json")
    args = parser.parse_args()
    output = args.output if args.output.is_absolute() else ROOT / args.output
    result = census(output)
    print(json.dumps({"status": result["status"], "output": str(output),
                      "dates": result["date_count"], "host_regime_groups": result["host_group_count"],
                      "catalog_ids": result["dates"][0]["archived_catalog_ids"] if result["dates"] else 0}, indent=2))


if __name__ == "__main__":
    main()
