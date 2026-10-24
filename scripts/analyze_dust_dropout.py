"""Audit DUST on-orbit RSO annotations and replay frame-level sensor outages."""
from __future__ import annotations

import argparse
import csv
import collections
import hashlib
import io
import json
import datetime as dt
import math
import pathlib
import random
import statistics
import zipfile

DATASET_URL = "https://zenodo.org/records/20255672"
DOI = "10.5281/zenodo.20255672"
MD5 = "a31b62290eface15e519ed954124d59c"
CODE_MD5 = "4b750568b73822aa99f7bd4655ba1efa"
DEFAULT_CODE_ARCHIVE = pathlib.Path("data/onboard_sensor/dust_star_tracker/DUST_code.zip")
DEFAULT_ARCHIVE = pathlib.Path("data/onboard_sensor/dust_star_tracker/DUST.zip")
DEFAULT_OUTPUT = pathlib.Path("data/onboard_sensor/dust_star_tracker/dropout_study")


def read_sessions(archive):
    sessions = {}
    with zipfile.ZipFile(archive) as bundle:
        file_names = [info.filename for info in bundle.infolist() if not info.is_dir()]
        for path in file_names:
            if "/Images/" in path and path.lower().endswith(".png"):
                key = path.split("/Images/", 1)[0]
                sessions.setdefault(key, {"images": [], "tracks": {}, "mot_path": None})
                sessions[key]["images"].append(path)
        for path in file_names:
            if not path.endswith("_MOT_gt.txt"):
                continue
            key = path.rsplit("/RSO_Annotations/", 1)[0]
            if key not in sessions:
                raise ValueError(f"MOT labels have no image session: {path}")
            session = sessions[key]
            session["mot_path"] = path
            with bundle.open(path) as stream:
                for row in csv.reader(io.TextIOWrapper(stream, encoding="utf-8")):
                    if not row:
                        continue
                    if len(row) != 9:
                        raise ValueError(f"Expected nine MOT fields in {path}; found {len(row)}")
                    frame, track_id = int(row[0]), int(row[1])
                    session["tracks"].setdefault(track_id, []).append(frame)
        h5_files = {path.rsplit("/", 1)[-1] for path in file_names
                    if "/H5/" in path and path.lower().endswith(".h5")}
        yolo_count = sum("/RSO_Annotations/YOLO/" in path and path.lower().endswith(".txt")
                         for path in file_names)
        frame_counts = {}
        for key, session in sessions.items():
            session["images"].sort()
            frame_count = len(session["images"])
            max_frame = max((frame for frames in session["tracks"].values() for frame in frames),
                            default=0)
            if max_frame > frame_count:
                raise ValueError(f"MOT frame index {max_frame} exceeds {frame_count} images in {key}")
            if session["mot_path"] is None:
                session["tracks"] = {}
            frame_counts[key] = {
                "image_frames": frame_count,
                "h5_metadata_files": sum(
                    "/H5/" in path and path.split("/H5/", 1)[0] == key
                    and path.lower().endswith(".h5") for path in file_names),
                "mot_rows": sum(len(frames) for frames in session["tracks"].values()),
                "annotated_transits": len(session["tracks"]),
                "max_annotated_frame": max_frame,
                "mot_annotation_file": session["mot_path"],
            }
    return sessions, frame_counts, h5_files, yolo_count, len(file_names)


def file_md5(path):
    digest = hashlib.md5()
    with pathlib.Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def export_spacecraft_metadata(code_archive, h5_files, sessions, output):
    code_archive = pathlib.Path(code_archive)
    code_hash = file_md5(code_archive)
    if code_hash != CODE_MD5:
        raise ValueError(f"DUST code archive MD5 mismatch: expected {CODE_MD5}, found {code_hash}")
    filename_to_frame = {}
    filename_to_session = {}
    for session_name, session in sessions.items():
        for index, image_path in enumerate(session["images"], 1):
            h5_name = pathlib.PurePosixPath(image_path).with_suffix(".h5").name
            filename_to_frame[h5_name] = index
            filename_to_session[h5_name] = session_name
    fields = ["norad_id", "platform", "session", "frame_index", "epoch_utc",
              "h5_filename", "attitude_determination_mode", "pitch_deg", "roll_deg", "yaw_deg",
              "sc_altitude_km", "sc_latitude_deg", "sc_longitude_deg", "exposure_seconds",
              "ccd_temperature_c", "camera_mode", "camera_source", "image_projection_available",
              "magnetic_latitude_deg", "magnetic_local_time", "magnetic_longitude_deg"]
    rows = []
    with zipfile.ZipFile(code_archive) as bundle:
        summary_files = sorted(name for name in bundle.namelist()
                               if "/Summary Files/H5/" in name and name.endswith(".csv"))
        for summary_path in summary_files:
            with bundle.open(summary_path) as stream:
                for row in csv.DictReader(io.TextIOWrapper(stream, encoding="utf-8-sig")):
                    filename = row["filename"]
                    if filename not in h5_files:
                        raise ValueError(f"Metadata row references H5 file missing from DUST.zip: {filename}")
                    epoch = dt.datetime.fromisoformat(row["UTC"].replace("Z", "+00:00"))
                    if epoch.tzinfo is None:
                        epoch = epoch.replace(tzinfo=dt.timezone.utc)
                    else:
                        epoch = epoch.astimezone(dt.timezone.utc)
                    rows.append({
                        "norad_id": 39265, "platform": "CASSIOPE", "session": filename_to_session[filename],
                        "frame_index": filename_to_frame[filename], "epoch_utc": epoch.isoformat().replace("+00:00", "Z"),
                        "h5_filename": filename, "attitude_determination_mode": row["Attitude Determination Mode"],
                        "pitch_deg": row["Pitch (°)"], "roll_deg": row["Roll (°)"], "yaw_deg": row["Yaw (°)"],
                        "sc_altitude_km": row["S/C Altitude (km)"],
                        "sc_latitude_deg": row["S/C Latitude (°)"], "sc_longitude_deg": row["S/C Longitude (°)"],
                        "exposure_seconds": row["Exposure Time (s)"], "ccd_temperature_c": row["CCD Temperature (°C)"],
                        "camera_mode": row["Camera Mode"], "camera_source": row["Camera Source"],
                        "image_projection_available": row["Image Projection Available"],
                        "magnetic_latitude_deg": row["Magnetic Latitude (°)"],
                        "magnetic_local_time": row["Magnetic Local Time"],
                        "magnetic_longitude_deg": row["Magnetic Longitude (°)"],
                    })
    if len(rows) != len(h5_files) or len({row["h5_filename"] for row in rows}) != len(h5_files):
        raise ValueError(f"H5 attitude metadata coverage mismatch: {len(rows)} rows vs {len(h5_files)} files")
    output.mkdir(parents=True, exist_ok=True)
    csv_path = output / "spacecraft_attitude_ephemeris.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(sorted(rows, key=lambda row: (row["session"], int(row["frame_index"]))))

    def numbers(key):
        return [float(row[key]) for row in rows if row[key] not in ("", None)]
    def range_summary(key):
        values = sorted(numbers(key))
        return {"count": len(values), "min": values[0], "median": statistics.median(values), "max": values[-1]}
    return {
        "status": "completed", "metadata_source_archive": str(code_archive),
        "metadata_source_md5": code_hash, "metadata_csv": str(csv_path),
        "matched_metadata_rows": len(rows), "matched_h5_files": len(h5_files),
        "spacecraft": "CASSIOPE (NORAD 39265)",
        "utc_start": min(row["epoch_utc"] for row in rows),
        "utc_end": max(row["epoch_utc"] for row in rows),
        "altitude_km": range_summary("sc_altitude_km"),
        "pitch_deg": range_summary("pitch_deg"), "roll_deg": range_summary("roll_deg"),
        "yaw_deg": range_summary("yaw_deg"),
        "exposure_seconds": sorted({float(row["exposure_seconds"]) for row in rows}),
        "attitude_mode_counts": dict(collections.Counter(
            row["attitude_determination_mode"] for row in rows)),
        "limitations": [
            "These are per-frame Euler angle fields in the published summary metadata; no quaternion or frame convention is asserted here.",
            "Coordinate columns with ambiguous source frame conventions are preserved only when their meaning and units are explicit in the field name.",
            "Samples cover 22 2023 observation sessions, not continuous four-year attitude telemetry.",
        ],
    }


def outage_masks(frame_count, rate, mode, seed, persistence=0.8):
    rng = random.Random(seed)
    if mode == "independent":
        uniforms = [rng.random() for _ in range(frame_count)]
        return [value < rate for value in uniforms]
    if mode != "burst":
        raise ValueError(mode)
    initial = rng.random()
    transitions = [rng.random() for _ in range(max(0, frame_count - 1))]
    entry_probability = rate * (1 - persistence) / max(1 - rate, 1e-12)
    state = initial < rate
    mask = [state]
    for draw in transitions:
        state = draw < persistence if state else draw < entry_probability
        mask.append(state)
    return mask


def measure(session, mask, grace_frames):
    opportunities = kept = injected_losses = custody = fragments = tracks_with_any = 0
    for frames in session["tracks"].values():
        observed_frames = set(frames)
        if not observed_frames:
            continue
        kept_frames = []
        last_seen = None
        for frame in range(min(observed_frames), max(observed_frames) + 1):
            opportunities += 1
            lost = mask[frame - 1]
            injected_losses += int(lost)
            detected = frame in observed_frames and not lost
            if detected:
                kept += 1
                last_seen = frame
                kept_frames.append(frame)
            if last_seen is not None and (detected or frame - last_seen <= grace_frames):
                custody += 1
        if kept_frames:
            tracks_with_any += 1
            fragments += sum((b - a) > grace_frames + 1
                             for a, b in zip(kept_frames, kept_frames[1:]))
    return {
        "internal_transit_frame_opportunities": opportunities,
        "detections_retained": kept,
        "detection_retention": kept / opportunities if opportunities else None,
        "injected_loss_rate_observed": injected_losses / opportunities if opportunities else None,
        "tracks": len(session["tracks"]),
        "tracks_with_any_retained_detection": tracks_with_any,
        "track_survival": tracks_with_any / len(session["tracks"]) if session["tracks"] else None,
        "custody_continuity": custody / opportunities if opportunities else None,
        "track_gap_fragments": fragments,
    }


def summarize_internal_track_gaps(sessions):
    """Summarize observed labels inside each track's annotated span.

    Inclusive first-to-last frame spans are a conditional opportunity proxy.
    Frames before first or after last annotation are censored and excluded;
    internal gaps are not assumed to be sensor-caused misses.
    """
    expected = observed = transits = transits_with_gaps = 0
    by_session = {}
    gap_lengths = collections.Counter()
    for session_name, session in sessions.items():
        session_expected = session_observed = 0
        for frames in session["tracks"].values():
            ordered = sorted(frames)
            unique = sorted(set(ordered))
            if len(unique) != len(ordered):
                raise ValueError("Duplicate MOT label for a track/frame pair")
            if not unique:
                continue
            transits += 1
            expected += unique[-1] - unique[0] + 1
            observed += len(unique)
            session_expected += unique[-1] - unique[0] + 1
            session_observed += len(unique)
            gaps = [b - a - 1 for a, b in zip(unique, unique[1:]) if b - a > 1]
            if gaps:
                transits_with_gaps += 1
                gap_lengths.update(gaps)
        by_session[session_name] = (session_observed, session_expected)
    # Sessions are the independent clusters; resample them with replacement.
    rng = random.Random(7317)
    names = list(by_session)
    bootstrap = []
    for _ in range(5000):
        sampled = rng.choices(names, k=len(names))
        denominator = sum(by_session[name][1] for name in sampled)
        numerator = sum(by_session[name][0] for name in sampled)
        if denominator:
            bootstrap.append(numerator / denominator)
    bootstrap.sort()
    missing = expected - observed
    return {
        "estimand": "recorded track detections / inclusive frames from each transit's first to last annotated detection",
        "expected_internal_transit_frames": expected,
        "recorded_track_detections": observed,
        "unannotated_internal_frames": missing,
        "recorded_frame_fraction": observed / expected if expected else None,
        "session_cluster_count": len(by_session),
        "recorded_frame_fraction_session_bootstrap_ci95": [
            bootstrap[int(.025 * len(bootstrap))],
            bootstrap[min(len(bootstrap) - 1, int(.975 * len(bootstrap)))],
        ] if bootstrap else [None, None],
        "transits": transits,
        "transits_with_internal_gaps": transits_with_gaps,
        "internal_gap_runs": sum(gap_lengths.values()),
        "internal_gap_length_frames": {str(size): count for size, count in sorted(gap_lengths.items())},
        "limitations": [
            "Frames before the first and after the last label are edge-censored and excluded.",
            "An internal unlabeled frame may reflect a missed detection, obscuration, annotation omission, or track behavior; it is not labeled as hardware dropout.",
            "The denominator is conditional on manually annotated transits and is not a complete sensor target-opportunity ledger.",
        ],
    }


def bootstrap_mean(values, seed, draws=5000):
    values = list(values)
    if not values:
        return {"mean": None, "ci95": [None, None]}
    mean = statistics.mean(values)
    rng = random.Random(seed)
    samples = sorted(statistics.mean(rng.choices(values, k=len(values))) for _ in range(draws))
    return {"mean": mean, "ci95": [samples[int(.025 * draws)], samples[min(draws - 1, int(.975 * draws))]]}


def summarize_gap_custody_sensitivity(sessions, grace_seconds=(1, 5, 10),
                                      bootstrap_seed=7321, draws=5000):
    """Bound custody loss if every internal annotation gap were a missed frame.

    Compare observed labels with a counterfactual that fills each track's
    first-to-last span perfectly. This is not a causal estimate of detector or
    hardware failure; it quantifies the custody effect under that assumption.
    """
    names = sorted(sessions)
    filled_sessions = {}
    for name, session in sessions.items():
        tracks = {track_id: (list(range(min(frames), max(frames) + 1)) if frames else [])
                  for track_id, frames in session["tracks"].items()}
        filled_sessions[name] = {"tracks": tracks}

    results = []
    for grace in grace_seconds:
        observed_values, filled_values = [], []
        observed_fragments = filled_fragments = 0
        for name in names:
            max_frame = max((frame for frames in sessions[name]["tracks"].values()
                             for frame in frames), default=0)
            mask = [False] * max_frame
            observed = measure(sessions[name], mask, int(grace))
            filled = measure(filled_sessions[name], mask, int(grace))
            observed_values.append(observed["custody_continuity"] or 0.0)
            filled_values.append(filled["custody_continuity"] or 0.0)
            observed_fragments += observed["track_gap_fragments"]
            filled_fragments += filled["track_gap_fragments"]
        paired = [observed - filled for observed, filled in zip(observed_values, filled_values)]
        estimate = bootstrap_mean(paired, bootstrap_seed + int(grace), draws)
        results.append({
            "grace_seconds": int(grace),
            "session_cluster_count": len(names),
            "observed_custody_equal_session_mean": statistics.fmean(observed_values) if names else None,
            "gap_filled_custody_equal_session_mean": statistics.fmean(filled_values) if names else None,
            "observed_minus_gap_filled_custody_percentage_points": 100.0 * estimate["mean"] if names else None,
            "paired_session_cluster_bootstrap_ci95_percentage_points": [
                100.0 * value for value in estimate["ci95"]],
            "observed_track_gap_fragments": observed_fragments,
            "gap_filled_track_gap_fragments": filled_fragments,
        })
    return {
        "estimand": "observed custody minus perfectly gap-filled custody within annotated first-to-last transit spans",
        "assumption": "Every internal unlabeled frame is treated as a missed detection and every labeled frame is retained; this is a sensitivity bound, not natural dropout attribution.",
        "cluster_unit": "observing session",
        "bootstrap_draws": draws,
        "bootstrap_seed": bootstrap_seed,
        "results": results,
        "limitations": [
            "A frame without an annotation may reflect obscuration, annotation omission, or track behavior rather than a sensor miss.",
            "Track entry and exit outside the first-to-last labeled frames remain censored.",
            "The effect applies only to the 160 annotated positive transits in this single-spacecraft benchmark.",
        ],
    }


def audit_replay_csv(path, session_opportunities, replicates, rates, modes, grace_seconds):
    """Check the persisted Monte Carlo design and metric domains."""
    expected = {(replicate, session, mode, float(rate), int(grace))
                for replicate in range(replicates)
                for session in session_opportunities
                for mode in modes for rate in rates for grace in grace_seconds}
    seen = set()
    duplicates = malformed = out_of_design = invalid_metrics = opportunity_mismatches = 0
    rows = 0
    with pathlib.Path(path).open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            rows += 1
            try:
                key = (int(row["replicate"]), row["session"], row["mode"],
                       float(row["requested_dropout_rate"]), int(row["grace_seconds"]))
                opportunities = int(row["internal_transit_frame_opportunities"])
                metrics = [float(row[name]) for name in
                    ("detection_retention", "injected_loss_rate_observed",
                     "track_survival", "custody_continuity")]
                tracks = int(row["tracks"])
                if any(not math.isfinite(value) or value < 0 or value > 1 for value in metrics) or tracks < 1:
                    invalid_metrics += 1
                if session_opportunities.get(key[1]) != opportunities:
                    opportunity_mismatches += 1
            except (KeyError, TypeError, ValueError):
                malformed += 1
                continue
            if key not in expected:
                out_of_design += 1
            if key in seen:
                duplicates += 1
            seen.add(key)
    missing = len(expected - seen)
    status = "completed" if not any((missing, duplicates, malformed, out_of_design,
                                     invalid_metrics, opportunity_mismatches)) and rows == len(expected) else "invalid"
    return {
        "status": status,
        "expected_rows": len(expected), "observed_rows": rows,
        "missing_rows": missing, "duplicate_rows": duplicates,
        "malformed_rows": malformed, "out_of_design_rows": out_of_design,
        "invalid_metric_rows": invalid_metrics,
        "session_opportunity_mismatches": opportunity_mismatches,
        "session_opportunities": session_opportunities,
    }


def analyze(archive, code_archive, output, replicates=100, seed=7311, rates=None,
            grace_seconds=(1, 5, 10), burst_persistence=0.8):
    archive, code_archive, output = (pathlib.Path(archive), pathlib.Path(code_archive), pathlib.Path(output))
    if replicates < 1:
        raise ValueError("replicates must be positive")
    rates = rates or (0.0, 0.05, 0.1, 0.2, 0.4, 0.6)
    sessions, inventory, h5_files, yolo_count, archive_file_count = read_sessions(archive)
    archive_hash = file_md5(archive)
    if archive_hash != MD5:
        raise ValueError(f"DUST archive MD5 mismatch: expected {MD5}, found {archive_hash}")
    total_frames = sum(v["image_frames"] for v in inventory.values())
    total_detections = sum(v["mot_rows"] for v in inventory.values())
    total_tracks = sum(v["annotated_transits"] for v in inventory.values())
    internal_gaps = summarize_internal_track_gaps(sessions)
    internal_gaps["custody_sensitivity_if_internal_gaps_are_misses"] = \
        summarize_gap_custody_sensitivity(sessions, grace_seconds)
    metadata = export_spacecraft_metadata(code_archive, h5_files, sessions, output)
    if total_frames != 1378 or total_detections != 4237 or total_tracks != 160:
        raise ValueError(f"Unexpected DUST inventory: {total_frames=} {total_detections=} {total_tracks=}")

    output.mkdir(parents=True, exist_ok=True)
    audit = {
        "status": "completed",
        "dataset": "DUST: An On-Orbit Star-Tracker Benchmark for RSO Detection and Attitude Estimation",
        "doi": DOI,
        "record_url": DATASET_URL,
        "license": "CC BY 4.0",
        "archive_md5": archive_hash,
        "archive_bytes": archive.stat().st_size,
        "archive_file_count": archive_file_count,
        "observation_sessions": len(sessions),
        "image_frames": total_frames,
        "frame_rate_hz": 1,
        "h5_session_count": len({key for key, value in inventory.items() if value["h5_metadata_files"]}),
        "h5_frame_metadata_files": sum(v["h5_metadata_files"] for v in inventory.values()),
        "yolo_annotation_files": yolo_count,
        "annotated_detection_rows": total_detections,
        "annotated_transits": total_tracks,
        "internal_transit_frame_coverage": internal_gaps,
        "spacecraft_attitude_ephemeris": metadata,
        "session_inventory": inventory,
        "limitations": [
            "On-orbit optical observations from CASSIOPE/FAI in 22 sessions during 2023, not four-year catalog coverage.",
            "Frame dropout is injected into captured and annotated frames; this is a paired missing-data replay, not a log of naturally failed hardware acquisitions.",
            "Continuity metrics are conditional on the manually annotated positive RSO instances and do not infer labels for unannotated frames.",
            "This is a single spacecraft camera benchmark; its dropout response does not calibrate the paper's hypothetical constellation-wide sensors.",
            "The Euler-angle and altitude samples come from the companion published H5 summary CSVs and match each raw HDF5 file by filename; the raw HDF5 binaries are not decoded by this script.",
        ],
    }
    (output / "dataset_audit.json").write_text(json.dumps(audit, indent=2) + "\n")

    csv_path = output / "frame_dropout_replays.csv"
    fields = ["replicate", "session", "mode", "requested_dropout_rate", "grace_seconds",
              "internal_transit_frame_opportunities", "detections_retained", "detection_retention",
              "injected_loss_rate_observed", "tracks",
              "tracks_with_any_retained_detection", "track_survival", "custody_continuity",
              "track_gap_fragments"]
    results = []
    session_names = sorted(sessions)
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for replicate in range(replicates):
            for session_index, name in enumerate(session_names):
                session = sessions[name]
                frame_count = inventory[name]["image_frames"]
                # The same uniforms across rates provide paired dose-response replays.
                independent_rng = random.Random(seed + replicate * 1_000_003 + session_index * 97_409)
                independent_uniforms = [independent_rng.random() for _ in range(frame_count)]
                burst_rng = random.Random(seed + replicate * 1_000_033 + session_index * 97_433)
                burst_initial = burst_rng.random()
                burst_transitions = [burst_rng.random() for _ in range(max(0, frame_count - 1))]
                for mode in ("independent", "burst"):
                    for rate in rates:
                        if mode == "independent":
                            mask = [u < rate for u in independent_uniforms]
                        elif rate == 0:
                            mask = [False] * frame_count
                        else:
                            entry = rate * (1 - burst_persistence) / max(1 - rate, 1e-12)
                            state = burst_initial < rate
                            mask = [state]
                            for draw in burst_transitions:
                                state = draw < burst_persistence if state else draw < entry
                                mask.append(state)
                        for grace in grace_seconds:
                            values = measure(session, mask, int(grace))
                            row = {"replicate": replicate, "session": name, "mode": mode,
                                   "requested_dropout_rate": rate, "grace_seconds": grace,
                                   **values}
                            writer.writerow(row)
                            results.append(row)

    session_opportunities = {
        name: sum(max(frames) - min(frames) + 1 for frames in session["tracks"].values() if frames)
        for name, session in sessions.items()
    }
    modes = ("independent", "burst")
    integrity = audit_replay_csv(csv_path, session_opportunities, replicates, rates, modes, grace_seconds)
    (output / "frame_dropout_integrity_audit.json").write_text(json.dumps(integrity, indent=2) + "\n")
    if integrity["status"] != "completed":
        raise RuntimeError(f"DUST frame replay integrity audit failed: {integrity}")

    summary = {"status": "completed", "replicates": replicates,
               "requested_rates": list(rates), "modes": list(modes),
               "burst_persistence": burst_persistence,
               "grace_seconds": list(grace_seconds), "session_cluster_count": len(sessions),
               "bootstrap_seed": seed + 7, "integrity_audit": integrity, "results": []}
    for mode in summary["modes"]:
        for rate in rates:
            for grace in grace_seconds:
                by_session = {}
                for row in results:
                    if (row["mode"] == mode and row["requested_dropout_rate"] == rate
                            and row["grace_seconds"] == grace):
                        by_session.setdefault(row["session"], []).append(row["custody_continuity"])
                condition = {key: statistics.mean(values) for key, values in by_session.items()}
                baseline_values = []
                for name in session_names:
                    values = [row["custody_continuity"] for row in results
                              if row["mode"] == mode and row["requested_dropout_rate"] == 0
                              and row["grace_seconds"] == grace and row["session"] == name]
                    baseline_values.append((name, statistics.mean(values)))
                effects = [condition[name] - baseline for name, baseline in baseline_values]
                result = {"mode": mode, "requested_dropout_rate": rate,
                          "grace_seconds": grace,
                          "mean_custody_continuity": statistics.mean(condition.values()),
                          "paired_change_vs_zero_dropout": bootstrap_mean(effects, seed + int(rate*1000) + grace),
                          "mean_detection_retention": statistics.mean(
                              row["detection_retention"] for row in results
                              if row["mode"] == mode and row["requested_dropout_rate"] == rate),
                          "mean_injected_loss_rate_observed": statistics.mean(
                              row["injected_loss_rate_observed"] for row in results
                              if row["mode"] == mode and row["requested_dropout_rate"] == rate),
                          "mean_track_survival": statistics.mean(
                              row["track_survival"] for row in results
                              if row["mode"] == mode and row["requested_dropout_rate"] == rate)}
                summary["results"].append(result)
    (output / "frame_dropout_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    report = [
        "# DUST frame-level dropout replay",
        "",
        f"This replay uses {total_frames:,} 1 Hz CASSIOPE/FAI image frames from {len(sessions)} sessions, "
        f"with {total_detections:,} manually annotated RSO detections across {total_tracks} transits. "
        f"It uses {replicates} paired Monte Carlo replicates, dropout seed {seed}, and burst persistence {burst_persistence:.2f}.",
        "",
        f"In the inclusive first-to-last labeled span of each transit, {internal_gaps['recorded_track_detections']:,} detections occupy "
        f"{internal_gaps['expected_internal_transit_frames']:,} possible 1 Hz frames ({internal_gaps['recorded_frame_fraction']:.2%}); "
        f"{internal_gaps['unannotated_internal_frames']} internal frames are unlabeled across {internal_gaps['transits_with_internal_gaps']} transits "
        f"(session-cluster bootstrap 95% CI for coverage {internal_gaps['recorded_frame_fraction_session_bootstrap_ci95'][0]:.2%}–{internal_gaps['recorded_frame_fraction_session_bootstrap_ci95'][1]:.2%}). "
        "This is an observed within-transit coverage proxy: entry/exit frames outside each labeled span are censored, and internal gaps are not attributed to hardware failure.",
        "",
        "Custody continuity is the share of frames inside each annotated first-to-last transit span whose latest retained detection "
        "is within the stated grace period. Confidence intervals are percentile bootstrap intervals over the "
        "22 observing sessions, paired against zero dropout within each outage mode. Each session is one cluster. "
        "Condition table values are equal-weight means over sessions and replicates; the dataset audit reports the pooled annotation-frame fraction.",
        "",
        "This is an injected missing-frame replay over actual on-orbit imagery and tracks. It measures how gaps "
        "affect custody of the annotated tracks; it does not estimate naturally occurring hardware failure rates "
        "or cover unannotated object opportunities. The persisted-CSV design audit verified "
        f"{integrity['observed_rows']:,} planned rows exactly once with no malformed or out-of-design rows.",
        "",
    ]
    gap_sensitivity = internal_gaps["custody_sensitivity_if_internal_gaps_are_misses"]
    report.extend([
        "## Observed internal annotation gaps: conditional custody sensitivity",
        "",
        "This table treats every unlabeled frame inside a labeled transit as a missed detection, then compares observed custody with a counterfactual that fills every such gap perfectly. This is an assumption-based sensitivity bound; the archive does not establish that these gaps were hardware failures.",
        "",
        "| Custody grace | Observed-label custody | Perfectly gap-filled custody | Difference (percentage points, 95% session-bootstrap CI) |",
        "|---:|---:|---:|---:|",
    ])
    for item in gap_sensitivity["results"]:
        ci = item["paired_session_cluster_bootstrap_ci95_percentage_points"]
        report.append(
            f"| {item['grace_seconds']} s | {item['observed_custody_equal_session_mean']:.2%} | "
            f"{item['gap_filled_custody_equal_session_mean']:.2%} | "
            f"{item['observed_minus_gap_filled_custody_percentage_points']:+.2f} "
            f"[{ci[0]:+.2f}, {ci[1]:+.2f}] |")
    report.extend(["", "Track-gap fragments observed / after perfect gap filling: " +
                   "; ".join(f"{item['grace_seconds']} s: {item['observed_track_gap_fragments']} / {item['gap_filled_track_gap_fragments']}"
                             for item in gap_sensitivity["results"]), ""])
    for grace in grace_seconds:
        report.extend([f"## {grace}-second custody grace", "",
                       "| Requested added loss | Outage process | Observed added loss | Detected fraction of internal frames | Custody continuity | Paired custody change (95% session-bootstrap CI) |",
                       "|---:|---|---:|---:|---:|---:|"])
        for mode in summary["modes"]:
            for rate in rates:
                item = next(x for x in summary["results"]
                            if x["mode"] == mode and x["requested_dropout_rate"] == rate
                            and x["grace_seconds"] == grace)
                estimate = item["paired_change_vs_zero_dropout"]
                interval = estimate["ci95"]
                report.append(
                    f"| {rate:.0%} | {mode} | {item['mean_injected_loss_rate_observed']:.1%} | "
                    f"{item['mean_detection_retention']:.1%} | "
                    f"{item['mean_custody_continuity']:.1%} | "
                    f"{estimate['mean']:+.1%} [{interval[0]:+.1%}, {interval[1]:+.1%}] |")
        report.append("")
    (output / "frame_dropout_report.md").write_text("\n".join(report) + "\n")
    return audit, summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", default=str(DEFAULT_ARCHIVE))
    parser.add_argument("--code-archive", default=str(DEFAULT_CODE_ARCHIVE))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--replicates", type=int, default=100)
    parser.add_argument("--seed", type=int, default=7311)
    args = parser.parse_args()
    audit, summary = analyze(args.archive, args.code_archive, args.output, args.replicates, args.seed)
    print(json.dumps({"audit": {k: audit[k] for k in
        ("status", "observation_sessions", "image_frames", "annotated_detection_rows", "annotated_transits")},
        "summary_cells": len(summary["results"]), "output": args.output}, indent=2))


if __name__ == "__main__":
    main()
