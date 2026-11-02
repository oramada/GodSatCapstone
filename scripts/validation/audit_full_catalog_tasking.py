"""Audit completeness, source hashes, row invariants, and date-cluster estimates."""
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
from pathlib import Path
import sys

import numpy as np
from scipy.stats import t as student_t

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from godsat.dropout import monthly_dates
from godsat.orbits import EARTH_RADIUS, History, utc
from godsat.scenario import cache_key
from scripts.experiments.run_full_catalog_tasking import cohort_id_count, cohort_id_sha256, configuration_signature

REGIMES = ("leo", "meo", "geo", "heo")
RATES = (0.0, 0.2)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_rows(rows, expected_dates, rates=RATES):
    expected = {(date, regime, rate) for date in expected_dates
                for regime in REGIMES for rate in rates}
    indexed = {}
    for row in rows:
        key = (row["date"], row["orbit_regime_sensor_hosts"], float(row["requested_outage_rate"]))
        if key in indexed:
            raise ValueError(f"Duplicate tasking response row: {key}")
        indexed[key] = row
        if key not in expected:
            raise ValueError(f"Unexpected tasking response row: {key}")
        if len(row["sensor_host_ids"]) != 6 or len(set(row["sensor_host_ids"])) != 6:
            raise ValueError(f"Invalid host list in response row: {key}")
        if row["step_count"] != 60 or row["step_seconds"] != 60:
            raise ValueError(f"Episode time grid differs from planned design: {key}")
        if not 0 <= row["sensor_actions"] <= 360 or not 0 <= row["detections"] <= row["sensor_actions"]:
            raise ValueError(f"Impossible action/detection counts: {key}")
        if not 0 <= row["dropout_misses"] <= row["dropout_trials"] <= row["sensor_actions"]:
            raise ValueError(f"Impossible dropout counts: {key}")
        for metric in ("custody_continuity", "observable_custody", "valid_target_fraction",
                       "observed_dropout_rate", "mean_slew_energy_proxy"):
            value = float(row[metric])
            if not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"Metric outside [0, 1] or non-finite ({metric}): {key}")
        if float(row["requested_outage_rate"]) == 0 and row["dropout_misses"] != 0:
            raise ValueError(f"Zero-outage reference has injected misses: {key}")
    if set(indexed) != expected:
        missing = sorted(expected - set(indexed))
        raise ValueError(f"Tasking response design is incomplete: {len(missing)} rows missing")
    return indexed


def recompute_effects(indexed, dates=None, rates=RATES):
    dates = dates or monthly_dates()
    baseline_rate, comparison_rate = rates
    suffix = "20pct" if math.isclose(comparison_rate, 0.2, abs_tol=1e-12) else "dropout_profile"
    result = []
    for regime in REGIMES:
        date_effects = []
        for date in dates:
            baseline = indexed[(date, regime, baseline_rate)]
            outage = indexed[(date, regime, comparison_rate)]
            date_effects.append({"date": date,
                f"custody_change_{suffix}_minus_0": outage["custody_continuity"] - baseline["custody_continuity"],
                f"observable_custody_change_{suffix}_minus_0": outage["observable_custody"] - baseline["observable_custody"],
                f"slew_proxy_change_{suffix}_minus_0": outage["mean_slew_energy_proxy"] - baseline["mean_slew_energy_proxy"]})
        metrics = {}
        for name in (f"custody_change_{suffix}_minus_0", f"observable_custody_change_{suffix}_minus_0",
                     f"slew_proxy_change_{suffix}_minus_0"):
            values = np.asarray([row[name] for row in date_effects], dtype=float)
            half = (float(student_t.ppf(.975, len(values)-1) * values.std(ddof=1) / np.sqrt(len(values)))
                    if len(values) > 1 else None)
            metrics[name] = {"n_date_clusters": len(values), "mean": float(values.mean()),
                "ci95_date_clustered": ([float(values.mean()-half), float(values.mean()+half)]
                                         if half is not None else None)}
        result.append({"sensor_host_regime": regime, **metrics, "date_effects": date_effects})
    return result


def recompute_host_state_availability(indexed, host_ids_by_date, config, dates=None, rates=RATES):
    """Recompute active-host state coverage from the historical GP archive."""
    dates = dates or monthly_dates()
    history = History(ROOT, "all")
    missing_by_regime = {regime: 0 for regime in REGIMES}
    checked = 0
    try:
        for date in dates:
            start = utc(date)
            steps = int(config.get("duration_minutes", 60) * 60 / config["step_seconds"])
            times = [start + dt.timedelta(seconds=index * int(config["step_seconds"]))
                     for index in range(steps + 1)]
            by_regime = host_ids_by_date[date]
            union_ids = sorted({int(oid) for values in by_regime.values() for oid in values})
            states, ages, errors, _ = history.replay(
                np.asarray(union_ids, dtype=np.int64), times,
                float(config["max_element_age_hours"]))
            altitude = np.linalg.norm(np.nan_to_num(states[:, :, :3]), axis=2) - EARTH_RADIUS
            valid = (np.isfinite(states[:, :, :3]).all(axis=2)
                     & np.isfinite(ages) & (ages <= float(config["max_element_age_hours"]))
                     & (errors == 0) & (altitude > 150) & (altitude < 60_000))
            union_index = {object_id: index for index, object_id in enumerate(union_ids)}
            for regime in REGIMES:
                indexes = [union_index[int(object_id)] for object_id in by_regime[regime]]
                missing = int((~valid[:steps, indexes]).sum())
                for rate in rates:
                    row = indexed[(date.replace("+00:00", "Z"), regime, rate)]
                    if int(row.get("host_state_missing_agent_steps", -1)) != missing:
                        raise ValueError(
                            f"Host-state availability differs from source replay at {date} {regime} rate={rate}: "
                            f"saved={row.get('host_state_missing_agent_steps')} source={missing}")
                missing_by_regime[regime] += missing
                checked += 1
    finally:
        history.db.close()
    return {"cells_recomputed": checked, "missing_agent_steps_by_host_regime": missing_by_regime,
            "missing_agent_steps_total": sum(missing_by_regime.values())}


def audit(output: Path) -> dict:
    summary_path = output / "summary.json"
    summary = json.loads(summary_path.read_text())
    dates = summary.get("dates", [])
    rates = tuple(map(float, summary.get("outage_rates", RATES)))
    if len(rates) != 2 or rates[0] != 0 or not 0 < rates[1] < 1:
        raise ValueError("Tasking outage-rate pair is invalid")
    suffix = "20pct" if math.isclose(rates[1], 0.2, abs_tol=1e-12) else "dropout_profile"
    if (not dates or len(set(dates)) != len(dates)
            or dates != sorted(dates)):
        raise ValueError("Tasking dates must be non-empty, unique, and chronological")
    expected_groups = len(dates) * len(REGIMES)
    expected_rows = expected_groups * len(rates)
    if summary.get("status") != "completed" or summary.get("simulator_version") != 2:
        raise ValueError("Full catalog tasking run is incomplete or has an unknown simulator version")
    if summary.get("expected_date_regime_groups") != expected_groups:
        raise ValueError("Full catalog tasking date/regime design is incomplete")
    if summary.get("completed_date_regime_groups") != expected_groups or len(summary.get("rows", [])) != expected_rows:
        raise ValueError(f"Full catalog tasking does not contain {expected_groups} paired cells / {expected_rows} responses")
    cohort = summary.get("target_cohort", "all")
    if cohort not in {"all", "current_active_payload"}:
        raise ValueError(f"Unknown target cohort: {cohort}")
    if cohort == "current_active_payload":
        manifest_path = ROOT / "data/current_active_payload_orbit_history.parquet.manifest.json"
        if summary.get("target_cohort_manifest_sha256") != sha256(manifest_path):
            raise ValueError("Target cohort history manifest checksum differs")
        cohort_path = ROOT / "data/current_active_payload_orbit_history.parquet"
        cohort_count = cohort_id_count(cohort_path)
        cohort_hash = cohort_id_sha256(cohort_path)
        if cohort_count <= 0:
            raise ValueError("Current active-payload history contains no objects")
        if summary.get("target_cohort_id_count") != cohort_count or summary.get("target_cohort_id_sha256") != cohort_hash:
            raise ValueError("Current active-payload target IDs do not match the historical archive")
        if not summary.get("target_cohort_note", "").startswith("Target IDs are selected using the current active-GP/SATCAT snapshot"):
            raise ValueError("Backcast limitation is missing from the active-payload cohort run")
    indexed = verify_rows(summary["rows"], dates, rates)
    config = summary["config"]
    campaign = Path(summary.get("source_campaign", ROOT / "outputs/all-orbits-paper-exact-active-hosts"))
    if not campaign.is_absolute():
        campaign = ROOT / campaign
    base_config = json.loads((campaign / "config.json").read_text())
    base_config.update(duration_minutes=60, step_seconds=60, propagation_model="sgp4")
    profile_summary = summary.get("dropout_profile")
    expected_design_sha256 = None
    empirical_masks = None
    empirical_mask_dates = None
    if profile_summary is not None:
        profile_path = Path(profile_summary["source_profile_path"])
        if not profile_path.is_absolute():
            profile_path = ROOT / profile_path
        profile = json.loads(profile_path.read_text())
        actual_profile_sha256 = sha256(profile_path)
        if (actual_profile_sha256 != profile_summary.get("source_profile_sha256")
                or not math.isclose(rates[1], profile.get("one_minute_attitude_solution_dropout_rate", -1), abs_tol=1e-12)):
            raise ValueError("Empirical dropout-profile source hash or rate differs")
        profile_mode = profile_summary.get("mode", "markov")
        if profile_mode == "empirical_block":
            masks_path = Path(profile_summary["mask_archive_path"])
            if not masks_path.is_absolute():
                masks_path = ROOT / masks_path
            mask_audit_path = masks_path.with_name("dropout_masks_independent_audit.json")
            mask_audit = json.loads(mask_audit_path.read_text())
            if (sha256(masks_path) != profile_summary.get("mask_archive_sha256")
                    or mask_audit.get("status") != "passed_independent_source_replay"
                    or mask_audit.get("mask_archive_sha256") != profile_summary.get("mask_archive_sha256")
                    or mask_audit.get("source_profile_sha256") != actual_profile_sha256
                    or profile_summary.get("mask_audit_status") != mask_audit.get("status")):
                raise ValueError("Empirical dropout block masks or their independent audit differ")
            with np.load(masks_path, allow_pickle=False) as archive:
                empirical_mask_dates = archive["dates"].astype(str).tolist()
                empirical_masks = archive["dropout"].astype(bool)
            if (mask_audit.get("dates") != empirical_mask_dates
                    or mask_audit.get("dates_checked") != len(empirical_mask_dates)
                    or mask_audit.get("cadence_seconds") != config.get("step_seconds")):
                raise ValueError("Empirical mask date/cadence grid differs from its independent audit")
            design = {"outage_rates": list(rates),
                      "dropout_profile_sha256": actual_profile_sha256,
                      "mask_archive_sha256": profile_summary.get("mask_archive_sha256"),
                      "mask_audit_status": mask_audit["status"],
                      "replay_method": "seeded_independent_per_host_daily_block_bootstrap",
                      "replay_trace_schema": 1,
                      "cadence_seconds": config["step_seconds"]}
        else:
            if not math.isclose(profile_summary.get("persistence_per_minute", -1),
                                profile.get("simulator_markov_persistence_parameter", -2), abs_tol=1e-12):
                raise ValueError("Empirical dropout-profile persistence differs")
            profile_persistence = float(profile["simulator_markov_persistence_parameter"])
            base_config["dropout_burst_persistence"] = profile_persistence
            base_config["dropout_burst_reference_step_seconds"] = 60
            design = {"outage_rates": list(rates), "dropout_profile_sha256": actual_profile_sha256,
                      "dropout_burst_persistence": profile_persistence, "reference_step_seconds": 60}
        expected_design_sha256 = hashlib.sha256(json.dumps(design, sort_keys=True).encode()).hexdigest()
        if profile_summary.get("design_sha256") != expected_design_sha256:
            raise ValueError("Tasking dropout design hash differs from its source profile")
    if summary.get("config_sha256") != sha256(campaign / "config.json"):
        raise ValueError("Tasking configuration checksum differs from the DOE source config")
    if summary.get("raw_archive_manifest_sha256") != sha256(ROOT / "data/raw/manifest.json"):
        raise ValueError("Tasking source archive manifest checksum differs")
    if config != base_config:
        raise ValueError("Effective tasking config does not match the documented scenario config")
    cell_signature = summary.get("configuration_signature")
    if cell_signature is not None:
        expected_signature = configuration_signature(
            base_config, dates, cohort, rates,
            sha256(ROOT / "data/raw/manifest.json"), expected_design_sha256)
        if cell_signature != expected_signature:
            raise ValueError("Tasking cell configuration signature differs from the complete design")
    scenario_hashes = summary.get("scenario_cache_sha256", {})
    metadata_hashes = summary.get("scenario_metadata_sha256", {})
    if len(scenario_hashes) != len(dates) or len(metadata_hashes) != len(dates):
        raise ValueError("Scenario hash map does not contain all declared study dates")
    scenario_hash_count = 0
    cell_count = 0
    metadata_hash_mismatches = []
    host_ids_by_date: dict[str, dict[str, list[int]]] = {date: {} for date in dates}
    for date in dates:
        if date not in scenario_hashes:
            raise ValueError(f"Missing scenario source hashes for {date}")
        for regime in REGIMES:
            expected_hash = scenario_hashes[date].get(regime)
            scenario_configs = [base_config]
            if int(base_config.get("targets", 1)) > 1:
                scenario_configs.append({**base_config, "targets": 1})
            scenario_path = next((ROOT / "data/scenarios" / f"{cache_key(date, candidate, regime)}.npz"
                                  for candidate in scenario_configs
                                  if (ROOT / "data/scenarios" / f"{cache_key(date, candidate, regime)}.npz").is_file()
                                  and sha256(ROOT / "data/scenarios" / f"{cache_key(date, candidate, regime)}.npz")
                                  == expected_hash), None)
            cell_path = output / "cells" / date[:10] / f"{regime}.json"
            if scenario_path is None:
                raise ValueError(f"Sensor-host scenario source hash mismatch for {date} {regime}")
            metadata_path = scenario_path.with_suffix(".json")
            metadata_hash = metadata_hashes[date].get(regime)
            if not metadata_path.is_file():
                raise FileNotFoundError(f"Sensor-host metadata missing for {date} {regime}")
            actual_metadata_hash = sha256(metadata_path)
            if actual_metadata_hash != metadata_hash:
                metadata_hash_mismatches.append({"date": date, "regime": regime,
                    "recorded_sha256": metadata_hash, "current_sha256": actual_metadata_hash})
            host_ids = list(map(int, json.loads(metadata_path.read_text()).get("agents", [])))
            if len(host_ids) != 6 or len(set(host_ids)) != 6:
                raise ValueError(f"Invalid sensor-host metadata for {date} {regime}")
            host_ids_by_date[date][regime] = host_ids
            target_row = indexed[(date.replace("+00:00", "Z"), regime, rates[0])]
            outage_row = indexed[(date.replace("+00:00", "Z"), regime, rates[1])]
            if cohort == "current_active_payload" and max(target_row["catalog_objects_in_episode"], outage_row["catalog_objects_in_episode"]) > cohort_count:
                raise ValueError(f"Episode target population exceeds archived active-payload cohort for {date} {regime}")
            if target_row["catalog_objects_in_episode"] != outage_row["catalog_objects_in_episode"]:
                raise ValueError(f"Paired dropout conditions used different target populations for {date} {regime}")
            cell = json.loads(cell_path.read_text())
            if cell.get("simulator_version") != 2 or cell.get("source_sha256") != expected_hash:
                raise ValueError(f"Saved cell provenance mismatch for {date} {regime}")
            if len(cell.get("rows", [])) != 2:
                raise ValueError(f"Saved cell lacks paired outage conditions for {date} {regime}")
            cell_rows = {(row["date"], row["orbit_regime_sensor_hosts"], float(row["requested_outage_rate"]))
                         for row in cell["rows"]}
            if cell_rows != {(date.replace("+00:00", "Z"), regime, rate) for rate in rates}:
                raise ValueError(f"Cell response keys differ from design for {date} {regime}")
            if expected_design_sha256 is not None and cell.get("design_sha256") != expected_design_sha256:
                raise ValueError(f"Cell dropout profile design hash differs for {date} {regime}")
            if cell_signature is not None and cell.get("configuration_signature") != cell_signature:
                raise ValueError(f"Cell configuration signature differs for {date} {regime}")
            if any(row.get("sensor_host_ids") != host_ids for row in cell["rows"]):
                raise ValueError(f"Tasking response hosts differ from the source scenario for {date} {regime}")
            expected_mode = "empirical_block" if profile_summary and profile_summary.get("mode") == "empirical_block" else "burst"
            if any(row.get("outage_mode") != expected_mode for row in cell["rows"]):
                raise ValueError(f"Tasking outage source mode differs from the declared design for {date} {regime}")
            if expected_mode == "empirical_block":
                for row in cell["rows"]:
                    if float(row["requested_outage_rate"]) == rates[0]:
                        if row.get("empirical_block_replay") is not None or row.get("dropout_misses") != 0:
                            raise ValueError(f"Zero-loss reference unexpectedly consumes empirical masks: {date} {regime}")
                        continue
                    replay = row.get("empirical_block_replay")
                    miss_steps = row.get("dropout_miss_steps_by_host")
                    if (len(replay or []) != len(host_ids) or len(miss_steps or []) != len(host_ids)
                            or row.get("dropout_trials") != row.get("sensor_actions")):
                        raise ValueError(f"Empirical block trace is incomplete for {date} {regime}")
                    replay_misses = 0
                    for agent, item in enumerate(replay):
                        if int(item.get("sensor_host_id", -1)) != host_ids[agent]:
                            raise ValueError(f"Empirical mask trace host identity differs for {date} {regime}")
                        source_day = item.get("source_date")
                        if source_day not in empirical_mask_dates:
                            raise ValueError(f"Empirical mask trace references unpublished date {source_day}")
                        source_index = empirical_mask_dates.index(source_day)
                        start = int(item.get("start_minute", -1))
                        steps = int(row["step_count"])
                        if start < 0 or start + steps > empirical_masks.shape[1]:
                            raise ValueError(f"Empirical mask trace is outside its source day for {date} {regime}")
                        block = empirical_masks[source_index, start:start + steps]
                        saved_misses = list(map(int, miss_steps[agent]))
                        if (saved_misses != sorted(set(saved_misses))
                                or any(step < 0 or step >= steps or not block[step] for step in saved_misses)):
                            raise ValueError(f"Recorded miss step does not coincide with an audited dropout for {date} {regime}")
                        replay_misses += len(saved_misses)
                    if replay_misses != int(row["dropout_misses"]):
                        raise ValueError(f"Empirical replay misses do not reconcile for {date} {regime}")
            scenario_hash_count += 1
            cell_count += 1
    csv_path = output / "responses.csv"
    with csv_path.open(newline="") as stream:
        csv_rows = list(csv.DictReader(stream))
    if len(csv_rows) != expected_rows:
        raise ValueError(f"responses.csv does not contain {expected_rows} rows")
    csv_keys = set()
    for csv_row in csv_rows:
        key = (csv_row["date"], csv_row["orbit_regime_sensor_hosts"],
               float(csv_row["requested_outage_rate"]))
        if key in csv_keys or key not in indexed:
            raise ValueError(f"responses.csv has a duplicate or unexpected row: {key}")
        csv_keys.add(key)
        for name, value in csv_row.items():
            expected = indexed[key].get(name)
            if isinstance(expected, (int, float)):
                if not math.isclose(float(value), float(expected), rel_tol=0, abs_tol=1e-12):
                    raise ValueError(f"responses.csv disagrees with saved JSON for {key} field {name}")
            elif str(expected) != value:
                raise ValueError(f"responses.csv disagrees with saved JSON for {key} field {name}")
    if csv_keys != set(indexed):
        raise ValueError("responses.csv keys do not match saved JSON response rows")
    recalculated = recompute_effects(indexed, dates, rates)
    for actual, expected in zip(recalculated, summary["paired_effects"]):
        for metric in (f"custody_change_{suffix}_minus_0", f"observable_custody_change_{suffix}_minus_0",
                       f"slew_proxy_change_{suffix}_minus_0"):
            actual_ci = actual[metric]["ci95_date_clustered"]
            expected_ci = expected[metric]["ci95_date_clustered"]
            if not np.isclose(actual[metric]["mean"], expected[metric]["mean"], rtol=0, atol=1e-12):
                raise ValueError(f"Saved date-clustered result does not reproduce for {actual['sensor_host_regime']} {metric}")
            if ((actual_ci is None) != (expected_ci is None)
                    or actual_ci is not None and not np.allclose(actual_ci, expected_ci, rtol=0, atol=1e-12)):
                raise ValueError(f"Saved date-clustered interval does not reproduce for {actual['sensor_host_regime']} {metric}")
    host_availability = recompute_host_state_availability(indexed, host_ids_by_date, config, dates, rates)
    result = {"status": "passed_structural_and_statistical",
        "scope": "Checks design completeness, immutable scenario-array hashes, host-ID identity against the saved responses, source/checkpoint provenance, response invariants, CSV rows, historical host-state availability recomputed from source SGP4 data, and date-clustered effects. Empirical-block mode also verifies the independently audited mask archive provenance, but does not rerun task assignment. Metadata JSON checksums are retained and any later drift is reported; only the host IDs consumed by this simulator are accepted when unchanged.",
        "simulator_version": 2, "target_cohort": cohort, "dates_checked": len(dates),
        "outage_rates": list(rates),
        "dropout_profile_design_sha256": expected_design_sha256,
        "paired_date_regime_cells_checked": cell_count,
        "response_rows_checked": len(indexed),
        "sensor_host_scenario_hashes_verified": scenario_hash_count,
        "date_cluster_effects_independently_recomputed": True,
        "date_cluster_intervals_estimable": len(dates) > 1,
        "historical_host_state_availability": host_availability,
        "scenario_metadata_checksum_mismatches": metadata_hash_mismatches,
        "checks": {"complete_declared_date_grid": True, "paired_zero_and_burst_conditions": True,
                   "source_config_and_archive_hashes": True, "scenario_hashes": True,
                   "per_cell_response_invariants": True, "responses_csv_row_count": True,
                   "date_clustered_intervals_recomputed": True,
                   "historical_host_state_availability_recomputed": True}}
    if profile_summary and profile_summary.get("mode") == "empirical_block":
        result["checks"]["empirical_mask_archive_hash_and_source_audit"] = True
    path = output / "independent_audit.json"
    path.write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/full-catalog-tasking-monthly-2022-2026")
    args = parser.parse_args()
    output = args.output if args.output.is_absolute() else ROOT / args.output
    result = audit(output)
    print(json.dumps({"status": result["status"], "output": str(output / "independent_audit.json"),
                      "response_rows_checked": result["response_rows_checked"],
                      "scenario_hashes_verified": result["sensor_host_scenario_hashes_verified"]}, indent=2))


if __name__ == "__main__":
    main()
