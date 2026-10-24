"""Run a streaming greedy tasking reference against the full fresh catalog.

This scale-extension benchmark is not the paper's learned policy. It uses the
same six active-payload sensor hosts, orbit regimes, range, slew and detection
assumptions, but considers every fresh valid catalog object as a target at each
simulation step. Paired outage rates and burst persistence are configurable.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from godsat.dropout import monthly_dates, sample_empirical_dropout_blocks
from godsat.orbits import EARTH_RADIUS, History, utc
from godsat.scenario import cache_key, line_of_sight, prepare as prepare_scenario

REGIMES = ("leo", "meo", "geo", "heo")
OUTAGE_RATES = (0.0, 0.2)
SIMULATOR_VERSION = 2


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def cohort_id_sha256(path: Path) -> str:
    import duckdb
    connection = duckdb.connect()
    connection.execute("SET threads=2")
    connection.execute("SET memory_limit='1GB'")
    ids = [int(row[0]) for row in connection.execute(
        "SELECT DISTINCT norad_id FROM read_parquet(?) ORDER BY norad_id", [str(path)]).fetchall()]
    connection.close()
    return hashlib.sha256(",".join(map(str, ids)).encode()).hexdigest()


def cohort_id_count(path: Path) -> int:
    import duckdb
    connection = duckdb.connect()
    value = connection.execute(
        "SELECT count(DISTINCT norad_id) FROM read_parquet(?)", [str(path)]).fetchone()[0]
    connection.close()
    return int(value)


def read_inputs(date: str, history: History, config: dict[str, Any]):
    instant = utc(date)
    end = instant + dt.timedelta(minutes=int(config["duration_minutes"]))
    rows = history.records(instant, end, config["max_element_age_hours"])
    grouped: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(int(row["norad_id"]), []).append(row)
    ids = np.asarray(sorted(grouped), dtype=np.int64)
    if not len(ids):
        raise ValueError(f"No catalog elements in the requested window at {date}")
    del rows
    times = [instant + dt.timedelta(seconds=i * int(config["step_seconds"]))
             for i in range(int(config["duration_minutes"] * 60 / config["step_seconds"]) + 1)]
    states, ages, errors, _ = history.replay(
        ids, times, config["max_element_age_hours"], grouped_records=grouped)
    valid = (np.isfinite(states[:, :, :3]).all(axis=2)
             & np.isfinite(ages) & (ages <= config["max_element_age_hours"])
             & (errors == 0))
    valid &= ((np.linalg.norm(np.nan_to_num(states[:, :, :3]), axis=2) - EARTH_RADIUS) > 150)
    valid &= ((np.linalg.norm(np.nan_to_num(states[:, :, :3]), axis=2) - EARTH_RADIUS) < 60_000)
    return ids, states, ages, valid, times


def host_ids_by_regime(date: str, config: dict[str, Any]):
    hosts = {}
    hashes = {}
    metadata_hashes = {}
    for regime in REGIMES:
        candidates = [config]
        if int(config.get("targets", 1)) > 1:
            # The full-catalog reference tasks every fresh catalog object; the
            # fixed DOE target count is only needed to build the host scenario.
            # Some dates have fewer than 18 geometrically observable targets,
            # while still having a valid six-host group.
            candidates.append({**config, "targets": 1})
        selected_config = None
        path = metadata_path = None
        for candidate_config in candidates:
            candidate_path = ROOT / "data/scenarios" / f"{cache_key(date, candidate_config, regime)}.npz"
            candidate_metadata = candidate_path.with_suffix(".json")
            if candidate_path.is_file() and candidate_metadata.is_file():
                selected_config, path, metadata_path = candidate_config, candidate_path, candidate_metadata
                break
            try:
                prepare_scenario(date, candidate_config, root=ROOT, regime=regime)
            except ValueError as error:
                if (candidate_config is config and "observable" in str(error)
                        and "need" in str(error) and len(candidates) > 1):
                    continue
                raise
            selected_config, path, metadata_path = candidate_config, candidate_path, candidate_metadata
            break
        if selected_config is None or path is None or metadata_path is None:
            raise ValueError(f"Could not prepare a valid sensor-host scenario for {date} {regime}")
        metadata = json.loads(metadata_path.read_text())
        ids = list(map(int, metadata.get("agents", [])))
        if len(ids) != int(config["agents"]) or len(set(ids)) != len(ids):
            raise ValueError(f"Invalid sensor-host list for {date} {regime}")
        hosts[regime] = ids
        hashes[regime] = sha256(path)
        metadata_hashes[regime] = sha256(metadata_path)
    return hosts, hashes, metadata_hashes


def load_cached_cell(path: Path, expected_hash: str, expected_host_ids: list[int],
                     expected_design_sha256: str | None = None):
    if not path.is_file():
        return None
    saved = json.loads(path.read_text())
    if saved.get("source_sha256") != expected_hash:
        return None
    if expected_design_sha256 is not None and saved.get("design_sha256") != expected_design_sha256:
        return None
    version = int(saved.get("simulator_version", 1))
    if version > SIMULATOR_VERSION:
        return None
    if any(row.get("sensor_host_ids") != expected_host_ids for row in saved.get("rows", [])):
        return None
    if version < SIMULATOR_VERSION:
        # Version 1 stopped with an exception whenever a host state became
        # invalid, so every completed v1 cell necessarily had zero such steps.
        for row in saved.get("rows", []):
            row.setdefault("host_state_missing_agent_steps", 0)
        saved["simulator_version"] = SIMULATOR_VERSION
        path.write_text(json.dumps(saved, indent=2) + "\n")
    return saved


def simulate_condition(date_index: int, regime_index: int, rate: float,
                       ids: np.ndarray, states: np.ndarray, ages: np.ndarray,
                       valid: np.ndarray, times: list[dt.datetime], host_ids: list[int],
                       config: dict[str, Any], seed: int,
                       target_exclude_ids: list[int] | None = None,
                       empirical_dropout_masks: np.ndarray | None = None,
                       empirical_dropout_dates: list[str] | None = None) -> dict[str, Any]:
    steps = len(times) - 1
    agents = int(config["agents"])
    index_by_id = {int(oid): index for index, oid in enumerate(ids)}
    try:
        host_indices = np.asarray([index_by_id[oid] for oid in host_ids], dtype=int)
    except KeyError as error:
        raise ValueError(f"Selected host {error.args[0]} lacks state history for {times[0]}") from error
    target_mask = np.ones(len(ids), dtype=bool)
    excluded = host_ids if target_exclude_ids is None else target_exclude_ids
    try:
        target_mask[[index_by_id[oid] for oid in excluded]] = False
    except KeyError as error:
        raise ValueError(f"Excluded host {error.args[0]} lacks state history for {times[0]}") from error

    ss = np.random.SeedSequence([seed, date_index, regime_index])
    action_ss, detect_ss, outage_ss, burst_ss = ss.spawn(4)
    priority_rng = np.random.default_rng(action_ss)
    detection = np.random.default_rng(detect_ss).random((steps, agents))
    outage_draws = np.random.default_rng(outage_ss).random((steps, agents))
    burst_initial = np.random.default_rng(burst_ss).random(agents)
    transition_ss = np.random.SeedSequence([seed, date_index, regime_index, 1])
    burst_transitions = np.random.default_rng(transition_ss).random((steps, agents))
    burst_state = burst_initial < rate
    empirical_dropout = None
    empirical_block_selection = None
    if empirical_dropout_masks is not None and rate:
        replay_seed = int(np.random.SeedSequence([seed, date_index, regime_index, 3]).generate_state(1)[0])
        empirical_dropout, selected_days, starts = sample_empirical_dropout_blocks(
            empirical_dropout_masks, steps, agents, replay_seed, return_indices=True)
        if empirical_dropout_dates is None or len(empirical_dropout_dates) != np.asarray(empirical_dropout_masks).shape[0]:
            raise ValueError("Empirical block replay requires dates corresponding to every mask row")
        empirical_block_selection = [{
            "sensor_host_id": int(host_ids[agent]),
            "source_date": str(empirical_dropout_dates[int(selected_days[agent])]),
            "start_minute": int(starts[agent]),
        } for agent in range(agents)]

    last_seen = np.full(len(ids), -np.inf)
    initial_host_pos = states[0, host_indices, :3]
    if not np.isfinite(initial_host_pos).all():
        raise ValueError(f"A selected sensor host has no valid state at episode start {times[0]}")
    pointing = initial_host_pos / np.maximum(np.linalg.norm(initial_host_pos, axis=1)[:, None], 1.0)
    custody_sum = observable_sum = 0.0
    custody_count = observable_count = valid_count = opportunities_count = 0
    attempts = dropout_trials = dropout_misses = detections = conflicts = 0
    dropout_miss_steps_by_host = [[] for _ in range(agents)]
    host_state_missing_steps = 0
    slew_values: list[float] = []
    dt_seconds = int(config["step_seconds"])
    for step in range(steps):
        elapsed = float(step * dt_seconds)
        if step and rate and empirical_dropout is None:
            persistence = float(config.get("dropout_burst_persistence", .8))
            entry = rate * (1 - persistence) / max(1 - rate, 1e-12)
            burst_state = np.where(burst_state, burst_transitions[step] < persistence,
                                   burst_transitions[step] < entry)

        step_valid = valid[step] & target_mask
        host_pos = states[step, host_indices, :3]
        host_active = valid[step, host_indices] & np.isfinite(host_pos).all(axis=1)
        host_state_missing_steps += int((~host_active).sum())
        safe_host_pos = np.nan_to_num(host_pos, nan=0.0, posinf=0.0, neginf=0.0)
        positions = states[step, :, :3]
        delta = positions[None, :, :] - safe_host_pos[:, None, :]
        ranges = np.linalg.norm(delta, axis=2)
        directions = delta / np.maximum(ranges[:, :, None], 1e-9)
        visible = np.isfinite(directions).all(axis=2)
        visible &= line_of_sight(safe_host_pos[:, None, :], positions[None, :, :])
        visible &= host_active[:, None]
        visible &= (ranges > 1.0) & (ranges <= float(config["max_range_km"]))
        visible &= step_valid[None, :]
        outward = safe_host_pos / np.maximum(np.linalg.norm(safe_host_pos, axis=1)[:, None], 1.0)
        field_angle = np.arccos(np.clip(np.sum(directions * outward[:, None, :], axis=2), -1, 1))
        visible &= field_angle <= math.radians(float(config["field_of_regard_deg"]))

        angles = np.arccos(np.clip(np.sum(directions * pointing[:, None, :], axis=2), -1, 1))
        allowed = visible & (angles <= math.radians(float(config["slew_rate_deg_s"]) * dt_seconds))
        urgency = np.clip((elapsed - last_seen) / float(config["custody_seconds"]), 0, 5)
        scores = urgency[None, :] - float(config["slew_penalty"]) * angles**2
        scores[~allowed] = -np.inf
        claimed = np.zeros(len(ids), dtype=bool)
        energies = np.zeros(agents, dtype=float)
        opportunity = visible.any(axis=0) & step_valid
        order = priority_rng.permutation(agents)
        for agent in order:
            scores[agent, claimed] = -np.inf
            if not np.isfinite(scores[agent]).any():
                continue
            target = int(np.argmax(scores[agent]))
            claimed[target] = True
            attempts += 1
            dropout_trials += 1
            energies[agent] = (angles[agent, target] / math.pi) ** 2
            pointing[agent] = directions[agent, target]
            probability = (float(config["detection_probability"])
                - float(config["range_detection_penalty"]) * ranges[agent, target] / float(config["max_range_km"])
                - float(config["stale_detection_penalty"]) * ages[step, target] / float(config["max_element_age_hours"]))
            probability = float(np.clip(probability, 0, 1))
            dropped = (bool(empirical_dropout[step, agent]) if empirical_dropout is not None
                       else bool(burst_state[agent]) if rate else False)
            if detection[step, agent] < probability and not dropped:
                detections += 1
                last_seen[target] = elapsed
            elif dropped:
                dropout_misses += 1
                dropout_miss_steps_by_host[agent].append(step)

        valid_count += int(step_valid.sum())
        custody = ((elapsed - last_seen) <= float(config["custody_seconds"])) & step_valid
        custody_sum += float(custody.sum())
        custody_count += int(step_valid.sum())
        observable_sum += float(custody[opportunity].sum())
        opportunities_count += int(opportunity.sum())
        observable_count += int(opportunity.sum())
        conflicts += max(0, int(claimed.sum()) - len(set(np.flatnonzero(claimed))))
        slew_values.append(float(energies.mean()))

    return {
        "date": times[0].isoformat().replace("+00:00", "Z"),
        "orbit_regime_sensor_hosts": REGIMES[regime_index],
        "sensor_host_ids": host_ids,
        "catalog_objects_in_episode": int(len(ids)),
        "step_count": steps,
        "step_seconds": dt_seconds,
        "outage_mode": "empirical_block" if empirical_dropout_masks is not None else "burst",
        "requested_outage_rate": rate,
        "observed_dropout_rate": dropout_misses / max(1, dropout_trials),
        "dropout_trials": dropout_trials,
        "dropout_misses": dropout_misses,
        "host_state_missing_agent_steps": host_state_missing_steps,
        "sensor_actions": attempts,
        "detections": detections,
        "custody_continuity": custody_sum / max(1, custody_count),
        "observable_custody": observable_sum / max(1, observable_count),
        "valid_target_fraction": valid_count / max(1, steps * int(target_mask.sum())),
        "mean_slew_energy_proxy": float(np.mean(slew_values)),
        "target_valid_step_count": valid_count,
        "target_observable_step_count": opportunities_count,
        "interpretation": "Greedy full-catalog tasking reference under synthetic sensor probabilities; not the trained 18-target DOE policy or a measured outage rate.",
        **({"empirical_block_replay": empirical_block_selection,
            "dropout_miss_steps_by_host": dropout_miss_steps_by_host}
           if empirical_dropout_masks is not None else {}),
    }


def run(output: Path, selected_dates: list[str] | None = None, max_date_regimes: int | None = None,
        target_cohort: str = "all", outage_rates=OUTAGE_RATES,
        dropout_profile: dict[str, Any] | None = None,
        dropout_profile_sha256: str | None = None,
        dropout_profile_path: str | None = None,
        empirical_dropout_masks: np.ndarray | None = None,
        empirical_dropout_metadata: dict[str, Any] | None = None):
    if target_cohort not in {"all", "current_active_payload"}:
        raise ValueError("target_cohort must be all or current_active_payload")
    campaign = ROOT / "outputs/all-orbits-paper-exact-active-hosts"
    config_path = campaign / "config.json"
    config = json.loads(config_path.read_text())
    config.update(duration_minutes=60, step_seconds=60, propagation_model="sgp4")
    outage_rates = tuple(map(float, outage_rates))
    if len(outage_rates) != 2 or outage_rates[0] != 0 or not 0 < outage_rates[1] < 1:
        raise ValueError("Tasking comparisons require (0, measured outage rate) with rate in (0, 1)")
    design_sha256 = None
    if dropout_profile is not None:
        profile_rate = float(dropout_profile["one_minute_attitude_solution_dropout_rate"])
        if not 0 < profile_rate < 1:
            raise ValueError("Dropout profile rate is outside the supported range")
        if not math.isclose(outage_rates[1], profile_rate, rel_tol=0, abs_tol=1e-12):
            raise ValueError("Paired outage rate must match the empirical dropout profile")
        if empirical_dropout_masks is not None:
            if empirical_dropout_metadata is None or empirical_dropout_metadata.get("status") != "passed_independent_source_replay":
                raise ValueError("Empirical block replay requires its independent source-mask audit")
            if empirical_dropout_metadata.get("source_profile_sha256") != dropout_profile_sha256:
                raise ValueError("Empirical block replay mask audit references a different dropout profile")
            if empirical_dropout_metadata.get("cadence_seconds") != config["step_seconds"]:
                raise ValueError("Empirical mask cadence must match the tasking step")
            if len(empirical_dropout_masks) != empirical_dropout_metadata.get("dates_checked"):
                raise ValueError("Empirical mask archive day count differs from its audit")
            design = {"outage_rates": list(outage_rates),
                      "dropout_profile_sha256": dropout_profile_sha256,
                      "mask_archive_sha256": empirical_dropout_metadata.get("mask_archive_sha256"),
                      "mask_audit_status": empirical_dropout_metadata.get("status"),
                      "replay_method": "seeded_independent_per_host_daily_block_bootstrap",
                      "replay_trace_schema": 1,
                      "cadence_seconds": config["step_seconds"]}
        else:
            profile_persistence = float(dropout_profile["simulator_markov_persistence_parameter"])
            if not 0 <= profile_persistence < 1:
                raise ValueError("Dropout profile persistence is outside the supported range")
            config["dropout_burst_persistence"] = profile_persistence
            config["dropout_burst_reference_step_seconds"] = 60
            design = {"outage_rates": list(outage_rates),
                      "dropout_profile_sha256": dropout_profile_sha256,
                      "dropout_burst_persistence": profile_persistence,
                      "reference_step_seconds": 60}
        design_sha256 = hashlib.sha256(json.dumps(design, sort_keys=True).encode()).hexdigest()
    dates = selected_dates or monthly_dates()
    if not dates or len(set(dates)) != len(dates):
        raise ValueError("Dates must be a non-empty list without duplicates")
    parsed_dates = [utc(date) for date in dates]
    if any(value < utc("2022-10-09T00:00:00Z")
           or value + dt.timedelta(minutes=60) >= utc("2026-10-10T00:00:00Z")
           for value in parsed_dates):
        raise ValueError("Every one-hour episode must fit inside the archived history interval")
    output.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    scenario_hashes: dict[str, dict[str, str]] = {}
    scenario_metadata_hashes: dict[str, dict[str, str]] = {}
    history = History(ROOT, target_cohort)
    try:
        processed = 0
        for date_index, date in enumerate(dates):
            hosts_by_regime, hashes, metadata_hashes = host_ids_by_regime(date, config)
            scenario_hashes[date] = hashes
            scenario_metadata_hashes[date] = metadata_hashes
            cached_rows = []
            all_cached = True
            for regime in REGIMES:
                cell = output / "cells" / date[:10] / f"{regime}.json"
                saved = load_cached_cell(cell, hashes[regime], hosts_by_regime[regime], design_sha256)
                if saved is None:
                    all_cached = False
                    break
                cached_rows.extend(saved["rows"])
            if all_cached:
                rows.extend(cached_rows)
                processed += len(REGIMES)
                print(f"{date}: reused four completed, hash-matched tasking groups ({processed}/{expected_group_count(dates)})", flush=True)
                write_progress(output, dates, processed, outage_rates, design_sha256,
                               scenario_hashes, scenario_metadata_hashes)
                if max_date_regimes is not None and processed >= max_date_regimes:
                    break
                continue
            print(f"Preparing full-catalog episode inputs for {date}", flush=True)
            ids, states, ages, valid, times = read_inputs(date, history, config)
            for regime_index, regime in enumerate(REGIMES):
                cell = output / "cells" / date[:10] / f"{regime}.json"
                saved = load_cached_cell(cell, hashes[regime], hosts_by_regime[regime], design_sha256)
                if saved is not None:
                    rows.extend(saved["rows"])
                    processed += 1
                    continue
                cell_rows = [simulate_condition(date_index, regime_index, rate, ids, states,
                    ages, valid, times, hosts_by_regime[regime], config, seed=73129,
                    empirical_dropout_masks=empirical_dropout_masks,
                    empirical_dropout_dates=empirical_dropout_metadata.get("dates")
                        if empirical_dropout_metadata else None)
                    for rate in outage_rates]
                cell.parent.mkdir(parents=True, exist_ok=True)
                tmp = cell.with_suffix(".json.tmp")
                cache_payload = {"simulator_version": SIMULATOR_VERSION,
                    "source_sha256": hashes[regime], "rows": cell_rows}
                if design_sha256 is not None:
                    cache_payload["design_sha256"] = design_sha256
                tmp.write_text(json.dumps(cache_payload, indent=2) + "\n")
                tmp.replace(cell)
                rows.extend(cell_rows)
                processed += 1
                replay_label = "empirical-block" if empirical_dropout_masks is not None else "burst"
                print(f"{date} {regime}: {len(ids):,} catalog IDs, paired {outage_rates[0]:.1%}/{outage_rates[1]:.1%} {replay_label} replay complete ({processed} groups)", flush=True)
                write_progress(output, dates, processed, outage_rates, design_sha256,
                               scenario_hashes, scenario_metadata_hashes)
                if max_date_regimes is not None and processed >= max_date_regimes:
                    break
            if max_date_regimes is not None and processed >= max_date_regimes:
                break
    finally:
        history.db.close()
    expected_groups = expected_group_count(dates)
    complete = processed == expected_groups
    result = {
        "status": "completed" if complete else "partial",
        "scope": f"Fresh and valid {target_cohort} targets at {len(dates)} explicitly sampled UTC epochs, 60-minute episodes, 60-second steps, four six-host regime groups, and paired {outage_rates[0]:.3%}/{outage_rates[1]:.3%} burst-loss conditions.",
        "method": ("SGP4 WGS-72 historical elements; streaming greedy urgency-minus-slew task assignment; paired treatment replays seeded, independently resampled per-host 60-minute blocks from audited CASSIOPE attitude-availability sequences."
            if empirical_dropout_masks is not None else "SGP4 WGS-72 historical elements; streaming greedy urgency-minus-slew task assignment; shared seeded detection and outage random streams for paired conditions."),
        "paper_policy_relation": "A separate all-target greedy reference. The trained DOE policy's fixed 18-target action space is unchanged.",
        "simulator_version": SIMULATOR_VERSION,
        "target_cohort": target_cohort,
        "target_cohort_manifest_sha256": (sha256(ROOT / "data/current_active_payload_orbit_history.parquet.manifest.json")
            if target_cohort == "current_active_payload" else None),
        "target_cohort_id_count": (cohort_id_count(ROOT / "data/current_active_payload_orbit_history.parquet")
            if target_cohort == "current_active_payload" else None),
        "target_cohort_id_sha256": (cohort_id_sha256(ROOT / "data/current_active_payload_orbit_history.parquet")
            if target_cohort == "current_active_payload" else None),
        "target_cohort_note": ("Target IDs are selected using the current active-GP/SATCAT snapshot and backcast through archived historical elements; this does not establish historical operational status."
            if target_cohort == "current_active_payload" else "All catalog objects with archived elements, subject to episode freshness and propagation filters."),
        "cohort_note": "Current active-GP/SATCAT sensor hosts are selected by the original study and backcast through history; this does not prove historical operations.",
        "config": config,
        "config_sha256": sha256(config_path),
        "raw_archive_manifest_sha256": sha256(ROOT / "data/raw/manifest.json"),
        "expected_date_regime_groups": expected_groups,
        "completed_date_regime_groups": processed,
        "dates": dates,
        "regimes": list(REGIMES),
        "outage_rates": list(outage_rates),
        "dropout_profile": ({
            "source": dropout_profile.get("interpretation"),
            "source_profile_path": dropout_profile_path,
            "source_profile_sha256": dropout_profile_sha256,
            "rate": float(dropout_profile["one_minute_attitude_solution_dropout_rate"]),
            "persistence_per_minute": float(dropout_profile["simulator_markov_persistence_parameter"]),
            "mode": "empirical_block" if empirical_dropout_masks is not None else "markov",
            "mask_archive_path": empirical_dropout_metadata.get("mask_archive_path") if empirical_dropout_metadata else None,
            "mask_archive_sha256": empirical_dropout_metadata.get("mask_archive_sha256") if empirical_dropout_metadata else None,
            "mask_audit_status": empirical_dropout_metadata.get("status") if empirical_dropout_metadata else None,
            "design_sha256": design_sha256,
        } if dropout_profile is not None else None),
        "scenario_cache_sha256": scenario_hashes,
        "scenario_metadata_sha256": scenario_metadata_hashes,
        "rows": rows,
        "paired_effects": summarize_effects(rows, outage_rates[1]),
        "limits": [
            "The scheduler is a deterministic greedy reference, not a learned GoDSAT policy.",
            "Sensor hosts come from today's active snapshot backcast to historical dates.",
            ("Dropout is injected from a one-spacecraft attitude-availability profile; it is not a ground-sensor failure probability."
                if dropout_profile is not None else "Dropout is injected; sensor-attempt logs and natural failure probabilities are unavailable."),
            f"This evaluates one sampled hour at each of {len(dates)} explicitly listed UTC epochs, not continuous operations over four years.",
            "Slew is a normalized angular proxy, not electrical energy; orbital trajectories use historical GP/TLE SGP4 states.",
        ],
    }
    summary = output / "summary.json"
    summary.write_text(json.dumps(result, indent=2) + "\n")
    write_csv(output / "responses.csv", rows)
    progress_path = output / "progress.json"
    if progress_path.exists():
        progress_path.unlink()
    return result


def summarize_effects(rows, comparison_rate: float = 0.2):
    from scipy.stats import t as student_t
    paired: dict[tuple[str, str], dict[float, dict[str, float]]] = {}
    for row in rows:
        key = (row["date"], row["orbit_regime_sensor_hosts"])
        paired.setdefault(key, {})[float(row["requested_outage_rate"])] = row
    result = []
    for regime in REGIMES:
        by_date = []
        for (date, host_regime), values in paired.items():
            if host_regime != regime or 0.0 not in values or comparison_rate not in values:
                continue
            suffix = "20pct" if math.isclose(comparison_rate, 0.2, abs_tol=1e-12) else "dropout_profile"
            by_date.append({"date": date,
                f"custody_change_{suffix}_minus_0": values[comparison_rate]["custody_continuity"] - values[0.0]["custody_continuity"],
                f"observable_custody_change_{suffix}_minus_0": values[comparison_rate]["observable_custody"] - values[0.0]["observable_custody"],
                f"slew_proxy_change_{suffix}_minus_0": values[comparison_rate]["mean_slew_energy_proxy"] - values[0.0]["mean_slew_energy_proxy"]})
        effects = {}
        suffix = "20pct" if math.isclose(comparison_rate, 0.2, abs_tol=1e-12) else "dropout_profile"
        for metric in (f"custody_change_{suffix}_minus_0", f"observable_custody_change_{suffix}_minus_0",
                       f"slew_proxy_change_{suffix}_minus_0"):
            sample = np.asarray([row[metric] for row in by_date], dtype=float)
            half = (float(student_t.ppf(.975, len(sample) - 1) * sample.std(ddof=1) / np.sqrt(len(sample)))
                    if len(sample) > 1 else None)
            effects[metric] = {"n_date_clusters": int(len(sample)),
                "mean": float(sample.mean()) if len(sample) else None,
                "ci95_date_clustered": ([float(sample.mean() - half), float(sample.mean() + half)]
                                         if half is not None else None)}
        result.append({"sensor_host_regime": regime, **effects, "date_effects": by_date})
    return result


def expected_group_count(dates):
    return len(dates) * len(REGIMES)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    columns = [key for key, value in rows[0].items()
               if all(not isinstance(row.get(key), (list, dict)) for row in rows)]
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows([{key: row.get(key) for key in columns} for row in rows])


def write_progress(output: Path, dates: list[str], processed: int,
                   outage_rates: tuple[float, float], design_sha256: str | None,
                   scenarios: dict[str, dict[str, str]],
                   metadata: dict[str, dict[str, str]]) -> None:
    """Atomically record checkpoint progress, never as final results."""
    completed_dates = []
    for date in dates:
        paths = [output / "cells" / date[:10] / f"{regime}.json" for regime in REGIMES]
        if not all(path.is_file() for path in paths):
            break
        for regime, path in zip(REGIMES, paths):
            try:
                cell = json.loads(path.read_text())
                rows = cell.get("rows", [])
                valid = (cell.get("simulator_version") == SIMULATOR_VERSION
                         and cell.get("source_sha256") == scenarios.get(date, {}).get(regime)
                         and len(rows) == len(outage_rates)
                         and {float(row["requested_outage_rate"]) for row in rows}
                             == set(outage_rates)
                         and (design_sha256 is None
                              or cell.get("design_sha256") == design_sha256))
            except (OSError, ValueError, KeyError, TypeError):
                valid = False
            if not valid:
                break
        if not valid:
            break
        completed_dates.append(date)
    progress = {
        "status": "running_checkpointed", "final_results": False,
        "simulator_version": SIMULATOR_VERSION,
        "expected_date_regime_groups": expected_group_count(dates),
        "completed_date_regime_groups": processed,
        "expected_date_count": len(dates), "complete_date_count": len(completed_dates),
        "completed_date_range": ([completed_dates[0], completed_dates[-1]]
                                  if completed_dates else None),
        "outage_rates": list(outage_rates), "dropout_design_sha256": design_sha256,
        "scenario_cache_sha256": scenarios, "scenario_metadata_sha256": metadata,
        "updated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "interpretation": "Progress checkpoint only; not an audited or final result.",
    }
    target = output / "progress.json"
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(progress, indent=2) + "\n")
    temporary.replace(target)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/full-catalog-tasking-monthly-2022-2026")
    parser.add_argument("--dates", help="comma-separated UTC episode starts inside the archive; default is the registered 48 monthly dates")
    parser.add_argument("--max-date-regimes", type=int, help="stop after this many date/regime groups (smoke testing)")
    parser.add_argument("--target-cohort", choices=("all", "current_active_payload"), default="all")
    args = parser.parse_args()
    output = args.output if args.output.is_absolute() else ROOT / args.output
    dates = [value.strip() for value in args.dates.split(",") if value.strip()] if args.dates else None
    result = run(output, dates, args.max_date_regimes, args.target_cohort)
    print(json.dumps({"status": result["status"], "output": str(output),
                      "completed_groups": result["completed_date_regime_groups"],
                      "response_rows": len(result["rows"])}, indent=2))


if __name__ == "__main__":
    main()
