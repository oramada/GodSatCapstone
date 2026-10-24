"""Audit the public Durham nightly optical SSA detections and conditional gaps.

The source contains per-object detections, not raw images or commanded exposure
logs. The gap calculation is therefore a conservative, in-field target-frame
continuity proxy: a science-frame timestamp is evidenced by another RSO
detection, and the target's position is interpolated between adjacent positive
detections.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import random
import re
import statistics
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SOURCE_MD5 = "1a566e244a1b368730a24de0bc07d962"
SOURCE_SHA256 = "a17abbf503eedb373414a0068a99608c436448a177deb70e2b69fe20fd7705d1"
FIELD_FULL_WIDTH_DEG = 5.9
FIELD_FULL_HEIGHT_DEG = 3.9
INSCRIBED_RADIUS_DEG = FIELD_FULL_HEIGHT_DEG / 2


def hash_file(path: Path) -> tuple[str, str]:
    md5 = hashlib.md5()
    sha256 = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            md5.update(block)
            sha256.update(block)
    return md5.hexdigest(), sha256.hexdigest()


def angle_delta_deg(a: float, b: float) -> float:
    return (a - b + 180.0) % 360.0 - 180.0


def in_field(row: tuple[float, float, float, float, float], radius: float) -> bool:
    _, altitude, azimuth, center_altitude, center_azimuth = row
    da = altitude - center_altitude
    dz = angle_delta_deg(azimuth, center_azimuth) * math.cos(math.radians(center_altitude))
    return altitude > 0.0 and math.hypot(da, dz) <= radius


def parse_night(archive: zipfile.ZipFile, name: str) -> dict:
    nested_bytes = archive.read(name)
    with zipfile.ZipFile(io.BytesIO(nested_bytes)) as nested:
        corrupt_member = nested.testzip()
        if corrupt_member is not None:
            raise ValueError(f"Corrupt nested member {name}:{corrupt_member}")
        members = nested.namelist()
        csv_members = [member for member in members if member.lower().endswith(".csv")]
        tle_members = [member for member in members
                       if "tle" in member.lower() or member.lower().endswith(".txt")]
        raw_by_norad: dict[int, dict[float, tuple[float, float, float, float, float]]] = {}
        eligible_by_norad: dict[int, dict[float, tuple[float, float, float, float, float]]] = {}
        track_files = 0
        rows_total = 0
        headers: set[tuple[str, ...]] = set()

        for member in csv_members:
            base = Path(member).name
            match = re.fullmatch(r"norad_(\d+)_final\.csv", base)
            if not match:
                if base.startswith("track_"):
                    track_files += 1
                    with nested.open(member) as stream:
                        reader = csv.DictReader(io.TextIOWrapper(stream, encoding="utf-8-sig", newline=""))
                        if reader.fieldnames is not None:
                            headers.add(tuple(reader.fieldnames))
                            rows_total += sum(1 for _ in reader)
                continue
            norad_id = int(match.group(1))
            raw: dict[float, tuple[float, float, float, float, float]] = {}
            eligible: dict[float, tuple[float, float, float, float, float]] = {}
            with nested.open(member) as stream:
                reader = csv.DictReader(io.TextIOWrapper(stream, encoding="utf-8-sig", newline=""))
                if reader.fieldnames is None:
                    raise ValueError(f"No header in {name}:{member}")
                headers.add(tuple(reader.fieldnames))
                for row in reader:
                    rows_total += 1
                    try:
                        timestamp = float(row["TIME_JD"])
                        record = (timestamp, float(row["ALT_DEG"]), float(row["AZ_DEG"]),
                                  float(row["CENTER_ALT_DEG"]), float(row["CENTER_AZ_DEG"]))
                        confidence = float(row["CONFIDENCE"])
                        track_confidence = int(float(row["TRACK_CONFIDENCE_LEVEL"]))
                        match_id = int(row["MATCH_NORAD"])
                    except (KeyError, TypeError, ValueError):
                        continue
                    if match_id != norad_id or not all(math.isfinite(value) for value in record):
                        continue
                    raw[timestamp] = record
                    if confidence >= 0.8 and track_confidence > 0:
                        eligible[timestamp] = record
            raw_by_norad[norad_id] = raw
            eligible_by_norad[norad_id] = eligible

        frames = sorted({timestamp for detections in raw_by_norad.values()
                         for timestamp in detections})
        frame_index = {timestamp: index for index, timestamp in enumerate(frames)}
        frame_deltas_seconds = [(b - a) * 86400.0 for a, b in zip(frames, frames[1:])]
        frame_deltas_seconds = [delta for delta in frame_deltas_seconds if delta > 0.0]

        result = {
            "archive": name,
            "csv_files": len(csv_members),
            "norad_catalogues": len(raw_by_norad),
            "unidentified_track_catalogues": track_files,
            "detection_rows": rows_total,
            "unique_science_frame_timestamps_with_any_norad_detection": len(frames),
            "tle_or_text_files_present": tle_members,
            "header_variants": len(headers),
        }
        if frame_deltas_seconds:
            result["observed_frame_time_delta_seconds"] = {
                "median": statistics.median(frame_deltas_seconds),
                "p05": statistics.quantiles(frame_deltas_seconds, n=20)[0],
                "p95": statistics.quantiles(frame_deltas_seconds, n=20)[18],
                "fraction_at_most_15_seconds": sum(d <= 15.0 for d in frame_deltas_seconds)
                / len(frame_deltas_seconds),
            }

        for max_gap_seconds in (30.0, 60.0, 180.0):
            for radius_deg in (1.0, INSCRIBED_RADIUS_DEG, math.hypot(
                    FIELD_FULL_WIDTH_DEG / 2, FIELD_FULL_HEIGHT_DEG / 2)):
                detections_in_cohort = 0
                in_field_frame_opportunities = 0
                tracks_with_opportunities = 0
                missed_target_frames = 0
                missing_gap_run_count = 0
                missing_to_missing_transitions = 0
                missing_to_detected_transitions = 0
                missing_run_lengths: list[int] = []
                for norad_id, trusted in eligible_by_norad.items():
                    raw = raw_by_norad[norad_id]
                    trusted_times = sorted(trusted)
                    opportunity_times: set[float] = set()
                    for left, right in zip(trusted_times, trusted_times[1:]):
                        first, last = trusted[left], trusted[right]
                        span_seconds = (right - left) * 86400.0
                        if span_seconds > max_gap_seconds:
                            continue
                        left_index = frame_index[left]
                        right_index = frame_index[right]
                        for timestamp in frames[left_index:right_index + 1]:
                            fraction = (timestamp - left) / (right - left)
                            azimuth_delta = angle_delta_deg(first[2], last[2])
                            center_azimuth_delta = angle_delta_deg(first[4], last[4])
                            position = (
                                timestamp,
                                first[1] + fraction * (last[1] - first[1]),
                                (first[2] - fraction * azimuth_delta) % 360.0,
                                first[3] + fraction * (last[3] - first[3]),
                                (first[4] - fraction * center_azimuth_delta) % 360.0,
                            )
                            if in_field(position, radius_deg):
                                opportunity_times.add(timestamp)
                    if opportunity_times:
                        tracks_with_opportunities += 1
                        in_field_frame_opportunities += len(opportunity_times)
                        detections_in_cohort += sum(timestamp in raw for timestamp in opportunity_times)
                        missed_target_frames += sum(timestamp not in raw for timestamp in opportunity_times)
                        if max_gap_seconds == 60.0 and radius_deg == INSCRIBED_RADIUS_DEG:
                            prior_timestamp = None
                            prior_was_missing = False
                            current_missing_run = 0
                            for timestamp in sorted(opportunity_times):
                                if (prior_timestamp is not None
                                        and (timestamp - prior_timestamp) * 86400.0 > 15.0):
                                    if current_missing_run:
                                        missing_run_lengths.append(current_missing_run)
                                        current_missing_run = 0
                                    prior_was_missing = False
                                is_missing = timestamp not in raw
                                if prior_was_missing:
                                    if is_missing:
                                        missing_to_missing_transitions += 1
                                    else:
                                        missing_to_detected_transitions += 1
                                if is_missing:
                                    if not prior_was_missing:
                                        missing_gap_run_count += 1
                                    current_missing_run += 1
                                elif current_missing_run:
                                    missing_run_lengths.append(current_missing_run)
                                    current_missing_run = 0
                                prior_timestamp = timestamp
                                prior_was_missing = is_missing
                            if current_missing_run:
                                missing_run_lengths.append(current_missing_run)
                key = (f"gap_le_{int(max_gap_seconds)}s_radius_{radius_deg:.3f}deg")
                result[key] = {
                    "tracks_with_opportunities": tracks_with_opportunities,
                    "target_frame_opportunities": in_field_frame_opportunities,
                    "recorded_detections": detections_in_cohort,
                    "unrecorded_target_frames": missed_target_frames,
                    "conditional_unrecorded_fraction": (
                        missed_target_frames / in_field_frame_opportunities
                        if in_field_frame_opportunities else None),
                }
                if max_gap_seconds == 60.0 and radius_deg == INSCRIBED_RADIUS_DEG:
                    transition_denominator = (missing_to_missing_transitions
                                              + missing_to_detected_transitions)
                    result[key].update({
                        "consecutive_missing_frame_count": sum(missing_run_lengths),
                        "consecutive_missing_burst_count": missing_gap_run_count,
                        "missing_to_missing_transitions_at_le_15s_cadence": missing_to_missing_transitions,
                        "missing_to_detected_transitions_at_le_15s_cadence": missing_to_detected_transitions,
                        "missing_state_persistence_proxy": (
                            missing_to_missing_transitions / transition_denominator
                            if transition_denominator else None),
                        "mean_missing_run_length": (
                            statistics.mean(missing_run_lengths) if missing_run_lengths else None),
                        "maximum_missing_run_length": max(missing_run_lengths, default=0),
                    })
        # Keep the frame membership operation linear-time in subsequent analyses.
        result["_frame_timestamps_jd"] = frames
        result["_raw_by_norad"] = raw_by_norad
        result["_eligible_by_norad"] = eligible_by_norad
        return result


def audit(source: Path) -> dict:
    md5, sha256 = hash_file(source)
    if md5 != SOURCE_MD5 or sha256 != SOURCE_SHA256:
        raise ValueError(f"Durham source checksum mismatch: MD5={md5}, SHA-256={sha256}")
    nights = []
    with zipfile.ZipFile(source) as outer:
        outer.testzip()
        outer_names = outer.namelist()
        night_archives = sorted(name for name in outer_names if name.lower().endswith(".zip"))
        readmes = [name for name in outer_names if Path(name).name.lower() == "readme.md"]
        if len(night_archives) != 10 or len(readmes) != 1:
            raise ValueError(f"Unexpected outer archive inventory: {outer_names}")
        readme = outer.read(readmes[0]).decode("utf-8", errors="replace")
        for name in night_archives:
            item = parse_night(outer, name)
            item.pop("_frame_timestamps_jd")
            item.pop("_raw_by_norad")
            item.pop("_eligible_by_norad")
            nights.append(item)
    total_rows = sum(item["detection_rows"] for item in nights)
    total_frames = sum(item["unique_science_frame_timestamps_with_any_norad_detection"] for item in nights)
    total_opportunities = sum(item["gap_le_60s_radius_1.950deg"]["target_frame_opportunities"]
                              for item in nights)
    total_detections = sum(item["gap_le_60s_radius_1.950deg"]["recorded_detections"]
                           for item in nights)
    total_missed = sum(item["gap_le_60s_radius_1.950deg"]["unrecorded_target_frames"]
                       for item in nights)
    gap_persistence = sum(item["gap_le_60s_radius_1.950deg"][
        "missing_to_missing_transitions_at_le_15s_cadence"] for item in nights)
    gap_recovery = sum(item["gap_le_60s_radius_1.950deg"][
        "missing_to_detected_transitions_at_le_15s_cadence"] for item in nights)
    gap_frames = sum(item["gap_le_60s_radius_1.950deg"]["consecutive_missing_frame_count"]
                     for item in nights)
    gap_runs = sum(item["gap_le_60s_radius_1.950deg"]["consecutive_missing_burst_count"]
                   for item in nights)
    persistence_rng = random.Random(20261011)
    persistence_bootstrap = []
    for _ in range(10_000):
        sampled = [persistence_rng.choice(nights)["gap_le_60s_radius_1.950deg"]
                   for _ in nights]
        frames = sum(item["consecutive_missing_frame_count"] for item in sampled)
        runs = sum(item["consecutive_missing_burst_count"] for item in sampled)
        if frames:
            persistence_bootstrap.append((frames - runs) / frames)
    persistence_bootstrap.sort()
    sensitivity = []
    for max_gap_seconds in (30, 60, 180):
        for radius_deg in (1.0, INSCRIBED_RADIUS_DEG, math.hypot(
                FIELD_FULL_WIDTH_DEG / 2, FIELD_FULL_HEIGHT_DEG / 2)):
            key = f"gap_le_{max_gap_seconds}s_radius_{radius_deg:.3f}deg"
            opportunities = sum(item[key]["target_frame_opportunities"] for item in nights)
            missed = sum(item[key]["unrecorded_target_frames"] for item in nights)
            sensitivity.append({
                "gap_limit_seconds": max_gap_seconds,
                "field_radius_degrees": radius_deg,
                "target_frame_opportunities": opportunities,
                "unrecorded_target_frames": missed,
                "conditional_unrecorded_fraction": missed / opportunities if opportunities else None,
            })
    rng = random.Random(20261010)
    bootstrap_fractions = []
    for _ in range(10_000):
        sampled = [rng.choice(nights)["gap_le_60s_radius_1.950deg"] for _ in nights]
        sampled_opportunities = sum(item["target_frame_opportunities"] for item in sampled)
        sampled_missed = sum(item["unrecorded_target_frames"] for item in sampled)
        bootstrap_fractions.append(sampled_missed / sampled_opportunities)
    bootstrap_fractions.sort()
    equal_night_mean = statistics.mean(
        item["gap_le_60s_radius_1.950deg"]["conditional_unrecorded_fraction"] for item in nights)
    return {
        "status": "completed_conditional_on_sky_detection_gap_audit",
        "source": {
            "archive": str(source),
            "license": "Creative Commons Attribution 4.0 International (CC BY)",
            "repository_url": "https://researchdata.durham.ac.uk/files/r1d504rk46w",
            "doi": "10.15128/r1d504rk46w",
            "md5": md5,
            "sha256": sha256,
            "outer_archive_integrity": "passed",
            "readme_mentions_tle_files": "TLE text file records the orbital-element set used to predict objects entering the field of view" in readme,
            "tle_files_found_in_released_nightly_archives": sum(
                len(item["tle_or_text_files_present"]) for item in nights),
        },
        "coverage": {
            "night_count": len(nights),
            "nights": [item["archive"] for item in nights],
            "identified_norad_catalogue_files": sum(item["norad_catalogues"] for item in nights),
            "unidentified_track_catalogue_files": sum(item["unidentified_track_catalogues"] for item in nights),
            "reported_detection_rows": total_rows,
            "frame_timestamps_with_any_rso_detection": total_frames,
            "catalogue_row_semantics": "Each row is a processed positive RSO detection in a science frame; no rows encode failed detections.",
        },
        "conditional_in_field_detection_gap_proxy": {
            "status": "completed_interpolated_between_positive_tracks",
            "gap_limit_seconds": 60,
            "inscribed_field_radius_degrees": INSCRIBED_RADIUS_DEG,
            "target_frame_opportunities": total_opportunities,
            "recorded_detections": total_detections,
            "unrecorded_target_frames": total_missed,
            "conditional_unrecorded_fraction": total_missed / total_opportunities if total_opportunities else None,
            "equal_weight_night_mean_fraction": equal_night_mean,
            "night_cluster_bootstrap_ci95": [
                bootstrap_fractions[int(0.025 * len(bootstrap_fractions))],
                bootstrap_fractions[int(0.975 * len(bootstrap_fractions))],
            ],
            "night_cluster_bootstrap_replicates": len(bootstrap_fractions),
            "night_cluster_bootstrap_seed": 20261010,
            "interpretation": (
                "A missing catalogue detection at a timestamp with another RSO detection is treated as an "
                "unrecorded target frame only when that NORAD object's path, linearly interpolated between "
                "adjacent high-confidence detections no more than 60 seconds apart, remains inside a "
                "conservative inscribed field-of-view circle. This is conditional on targets already "
                "detected on both sides of the gap. It measures catalogue continuity/extraction gaps, "
                "not shutter failures or a population-wide probability of missed acquisition."
            ),
        },
        "conditional_missing_state_persistence_proxy": {
            "gap_limit_seconds": 60,
            "in_field_radius_degrees": INSCRIBED_RADIUS_DEG,
            "frame_adjacency_limit_seconds": 15,
            "unrecorded_target_frames": gap_frames,
            "consecutive_missing_bursts": gap_runs,
            "within_burst_missing_to_missing_transitions": gap_persistence,
            "within_burst_missing_to_detected_transitions": gap_recovery,
            "missing_state_persistence_proxy": (gap_frames - gap_runs) / gap_frames if gap_frames else None,
            "markov_missing_to_missing_transition_fraction": (
                gap_persistence / (gap_persistence + gap_recovery)
                if gap_persistence + gap_recovery else None),
            "mean_consecutive_missing_frames_per_burst": gap_frames / gap_runs if gap_runs else None,
            "maximum_single_night_burst_length_frames": max(
                item["gap_le_60s_radius_1.950deg"]["maximum_missing_run_length"]
                for item in nights),
            "night_cluster_bootstrap_ci95": [
                persistence_bootstrap[int(0.025 * len(persistence_bootstrap))],
                persistence_bootstrap[int(0.975 * len(persistence_bootstrap))],
            ],
            "night_cluster_bootstrap_replicates": len(persistence_bootstrap),
            "night_cluster_bootstrap_seed": 20261011,
            "interpretation": (
                "Persistence of consecutive missing catalogue detections within short-cadence frames for "
                "already observed, interpolated in-field tracks. It can parameterize a bounded burst "
                "sensitivity, but is not a sensor hardware failure-state persistence measurement."
            ),
        },
        "sensitivity_by_night": nights,
        "pooled_sensitivity": sensitivity,
        "limitations": [
            "The archive contains processed catalogues rather than raw science frames or exposure command/health logs.",
            "The accompanying README describes nightly TLE lists, but no TLE or text files are present in the released nightly ZIPs.",
            "No target opportunity is inferred outside a target's observed track brackets.",
            "The conservative circular field bound uses the published nominal 5.9 by 3.9 degree field size; exposure-level WCS is absent.",
            "This conditional observed-track gap rate is not sensor hardware dropout effectiveness or an unbiased detection probability.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path,
                        default=ROOT / "data/ground_sensor/durham_widefield_ssa/all_data.zip")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "data/ground_sensor/durham_widefield_ssa/dataset_audit.json")
    args = parser.parse_args()
    result = audit(args.source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "night_count": result["coverage"]["night_count"],
                      "detection_rows": result["coverage"]["reported_detection_rows"],
                      "conditional_gap": result["conditional_in_field_detection_gap_proxy"]}, indent=2))


if __name__ == "__main__":
    main()
