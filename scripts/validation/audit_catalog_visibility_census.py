"""Recompute and verify the 48-date all-catalog visibility census."""
from __future__ import annotations

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))


import argparse
import hashlib
import json
import sys
from pathlib import Path

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


def audit(summary_path: Path, output_path: Path) -> dict:
    summary = json.loads(summary_path.read_text())
    if summary.get("date_count") != 48 or summary.get("host_group_count") != 192:
        raise ValueError("Census design does not contain all 48 dates and 192 host-regime groups")
    dates = monthly_dates()
    if summary.get("study_dates") != dates:
        raise ValueError("Census dates do not match the registered monthly study grid")
    campaign = ROOT / "outputs/all-orbits-paper-exact-active-hosts"
    config = json.loads((campaign / "config.json").read_text())
    config.update(duration_minutes=60, step_seconds=60, propagation_model="sgp4")
    history = History(ROOT, "all")
    date_results = []
    cache_count = 0
    try:
        for date in dates:
            instant = utc(date)
            rows = history.snapshot(instant, config["max_element_age_hours"])
            ids: list[int] = []
            positions: list[list[float]] = []
            object_regimes: list[str] = []
            errors = 0
            for row in rows:
                err, pos, vel = satellite(row).sgp4(*julian(instant))
                if err or not np.isfinite(pos + vel).all():
                    errors += 1
                    continue
                if not 150 < np.linalg.norm(pos) - EARTH_RADIUS < 60_000:
                    continue
                ids.append(int(row["norad_id"]))
                positions.append(list(pos))
                object_regimes.append(orbit_regime(row))
            ids_array = np.asarray(ids, dtype=np.int64)
            positions_array = np.asarray(positions, dtype=float)
            regime_array = np.asarray(object_regimes, dtype="U8")
            regime_by_id = {int(object_id): str(regime_array[index])
                            for index, object_id in enumerate(ids_array)}
            all_group_visible = set()
            group_checks = []
            host_ids_by_group: dict[str, list[int]] = {}
            for regime in REGIMES:
                scenario_path = ROOT / "data/scenarios" / f"{cache_key(date, config, regime)}.npz"
                recorded_hash = summary["scenario_cache_sha256"].get(f"{date}|{regime}")
                actual_hash = sha256(scenario_path)
                if recorded_hash != actual_hash:
                    raise ValueError(f"Scenario cache hash mismatch for {date} {regime}")
                cache_count += 1
                metadata = json.loads(scenario_path.with_suffix(".json").read_text())
                host_ids = list(map(int, metadata["agents"]))
                with np.load(scenario_path, allow_pickle=False) as cache:
                    cached_ids = cache["ids"].astype(np.int64)
                    host_pos = cache["states"][0, :len(host_ids), :3]
                if not np.array_equal(cached_ids[:len(host_ids)], host_ids):
                    raise ValueError(f"Host ID/cache mismatch for {date} {regime}")
                if not np.isfinite(host_pos).all():
                    raise ValueError(f"Invalid host state for {date} {regime}")
                host_ids_by_group[regime] = host_ids
                eligible = ~np.isin(ids_array, np.asarray(host_ids, dtype=np.int64))
                target_ids = ids_array[eligible]
                target_pos = positions_array[eligible]
                if len(target_ids):
                    ranges = np.linalg.norm(target_pos[None, :, :] - host_pos[:, None, :], axis=2)
                    visible = line_of_sight(host_pos[:, None, :], target_pos[None, :, :])
                    visible &= (ranges > 1) & (ranges <= float(config["max_range_km"]))
                    visible_ids = set(map(int, target_ids[np.any(visible, axis=0)]))
                else:
                    visible_ids = set()
                all_group_visible.update(visible_ids)
                count_by_regime = {name: sum(regime_by_id.get(oid) == name for oid in visible_ids)
                                   for name in REGIME_BINS}
                group_checks.append({"host_regime": regime,
                                     "visible_ids": visible_ids,
                                     "count_by_regime": count_by_regime,
                                     "host_ids": host_ids})
            recorded_date = next(row for row in summary["dates"] if row["date"] == date)
            fresh_count = len(ids_array)
            visible_by_regime = {name: sum(regime_by_id.get(oid) == name for oid in all_group_visible)
                                 for name in REGIME_BINS}
            if recorded_date["propagatable_objects"] != fresh_count:
                raise ValueError(f"Propagatable object total differs for {date}")
            if recorded_date["distinct_targets_observable_from_any_selected_host_set"] != len(all_group_visible):
                raise ValueError(f"All-host visibility total differs for {date}")
            if recorded_date["observable_by_target_regime"] != visible_by_regime:
                raise ValueError(f"All-host target-regime counts differ for {date}")
            for check in group_checks:
                recorded = next(row for row in summary["host_regime_groups"]
                                if row["date"] == date and row["host_regime"] == check["host_regime"])
                if recorded["distinct_observable_targets"] != len(check["visible_ids"]):
                    raise ValueError(f"Host-group visibility total differs for {date} {check['host_regime']}")
                if recorded["observable_by_target_regime"] != check["count_by_regime"]:
                    raise ValueError(f"Host-group regime counts differ for {date} {check['host_regime']}")
            date_results.append({"date": date, "propagatable_objects": fresh_count,
                                 "observable_targets": len(all_group_visible),
                                 "sgp4_errors": errors})
            print(f"Verified {date}: {fresh_count:,} propagated, {len(all_group_visible):,} visible", flush=True)
    finally:
        history.db.close()

    result = {"status": "passed", "dates_checked": len(date_results),
              "host_regime_groups_checked": cache_count,
              "source_recomputed_dates": len(date_results),
              "all_catalog_visibility_recomputed": True,
              "scenario_cache_hashes_verified": cache_count,
              "checks": {"monthly_date_grid": True, "fresh_source_states_recomputed": True,
                         "host_sets_match_cached_scenarios": True,
                         "per_group_visible_totals_and_regimes_match": True,
                         "per_date_union_totals_and_regimes_match": True},
              "dates": date_results}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    default_root = ROOT / "outputs/all-catalog-visibility-census-2022-2026"
    parser.add_argument("--summary", type=Path, default=default_root / "summary.json")
    parser.add_argument("--output", type=Path, default=default_root / "independent_audit.json")
    args = parser.parse_args()
    summary = args.summary if args.summary.is_absolute() else ROOT / args.summary
    output = args.output if args.output.is_absolute() else ROOT / args.output
    result = audit(summary, output)
    print(json.dumps({"status": result["status"], "dates_checked": result["dates_checked"],
                      "host_regime_groups_checked": result["host_regime_groups_checked"],
                      "output": str(output)}, indent=2))


if __name__ == "__main__":
    main()
