"""Independently recompute DUST's timestamp-grid custody sensitivity outputs."""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import math
import pathlib
import random
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.analyze_dust_dropout import DEFAULT_ARCHIVE, MD5, read_sessions

STUDY = ROOT / "data/onboard_sensor/dust_star_tracker/dropout_study"
METADATA = STUDY / "spacecraft_attitude_ephemeris.csv"
CADENCE = STUDY / "capture_cadence_audit.json"
RESULT = STUDY / "capture_cadence_custody.json"
OUTPUT = STUDY / "capture_cadence_custody_audit.json"
GRACE = (1, 5, 10)
REPLICATES = 10_000
SEED = 7318


def digest(path: pathlib.Path, algorithm="sha256") -> str:
    hasher = hashlib.new(algorithm)
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def timestamp(value: str) -> dt.datetime:
    out = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    return out.replace(tzinfo=dt.timezone.utc) if out.tzinfo is None else out.astimezone(dt.timezone.utc)


def close(left, right, tol=1e-12):
    return math.isclose(float(left), float(right), rel_tol=0, abs_tol=tol)


def boot(values: list[float], seed: int) -> list[float]:
    rng = random.Random(seed)
    size = len(values)
    samples = sorted(sum(values[rng.randrange(size)] for _ in range(size)) / size
                     for _ in range(REPLICATES))
    return [samples[int(.025 * (REPLICATES - 1))], samples[int(.975 * (REPLICATES - 1))]]


def audit(archive=DEFAULT_ARCHIVE, metadata=METADATA, cadence_path=CADENCE,
          result_path=RESULT, output=OUTPUT) -> dict:
    archive, metadata, cadence_path, result_path, output = map(pathlib.Path,
        (archive, metadata, cadence_path, result_path, output))
    actual_md5 = digest(archive, "md5")
    if actual_md5 != MD5:
        raise ValueError("DUST archive does not match the pinned publisher checksum")
    cadence = json.loads(cadence_path.read_text())
    result = json.loads(result_path.read_text())
    if cadence.get("status") != "completed" or result.get("status") != "completed_conditional_cadence_custody_sensitivity":
        raise ValueError("Cadence inventory or custody replay is incomplete")

    frame_times: dict[str, dict[int, dt.datetime]] = {}
    with metadata.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            session, frame = row["session"], int(row["frame_index"])
            if frame in frame_times.setdefault(session, {}):
                raise ValueError(f"Duplicate frame timestamp: {session} {frame}")
            frame_times[session][frame] = timestamp(row["epoch_utc"])
    sessions, inventory, *_ = read_sessions(archive)
    if set(sessions) != set(frame_times):
        raise ValueError("Image and metadata session inventories differ")

    per_session = []
    track_count = expected_total = missing_image_total = unlabeled_total = 0
    for name, source_session in sorted(sessions.items()):
        times = frame_times[name]
        if set(times) != set(range(1, inventory[name]["image_frames"] + 1)):
            raise ValueError(f"Incomplete image timestamps for {name}")
        totals = {grace: [0, 0, 0, 0] for grace in GRACE}  # slots, observed, fill-capture, perfect
        session_tracks = 0
        session_missing = session_unlabeled = 0
        for frame_list in source_session["tracks"].values():
            labels = set(map(int, frame_list))
            if not labels:
                continue
            session_tracks += 1
            first, last = min(labels), max(labels)
            begin, finish = times[first], times[last]
            duration = (finish - begin).total_seconds()
            n_slots = round(duration) + 1
            if abs(duration - round(duration)) > .01:
                raise ValueError(f"Non-1Hz transit duration in {name}")
            image_slots = set()
            for idx, instant in times.items():
                if begin <= instant <= finish:
                    offset = (instant - begin).total_seconds()
                    slot = round(offset)
                    if abs(offset - slot) > .01 or slot not in range(n_slots):
                        raise ValueError(f"Image timestamp falls outside nominal transit grid in {name}")
                    image_slots.add(slot)
            label_slots = set()
            for idx in labels:
                offset = (times[idx] - begin).total_seconds()
                slot = round(offset)
                if abs(offset - slot) > .01 or slot not in image_slots:
                    raise ValueError(f"MOT label does not map to an image slot in {name}")
                label_slots.add(slot)
            expected = set(range(n_slots))
            missing_images = expected - image_slots
            unlabeled_images = image_slots - label_slots
            if not label_slots <= image_slots:
                raise ValueError(f"Labels exceed captured frame set in {name}")
            session_missing += len(missing_images)
            session_unlabeled += len(unlabeled_images)
            capture_filled = label_slots | missing_images
            for grace in GRACE:
                last_label = last_filled = None
                observed_custody = filled_custody = 0
                for slot in range(n_slots):
                    if slot in label_slots:
                        last_label = slot
                    if slot in capture_filled:
                        last_filled = slot
                    observed_custody += last_label is not None and slot - last_label <= grace
                    filled_custody += last_filled is not None and slot - last_filled <= grace
                totals[grace][0] += n_slots
                totals[grace][1] += observed_custody
                totals[grace][2] += filled_custody
                totals[grace][3] += n_slots
        metrics = {grace: {
            "expected_target_slots": values[0],
            "annotated_detection_custody": values[1] / values[0] if values[0] else None,
            "missing_capture_slots_filled_custody": values[2] / values[0] if values[0] else None,
            "perfectly_labeled_custody": values[3] / values[0] if values[0] else None,
        } for grace, values in totals.items()}
        per_session.append({"session": name, "tracks": session_tracks,
                            "expected_transit_slots": totals[GRACE[0]][0],
                            "missing_capture_slots": session_missing,
                            "capture_gap_fraction": (session_missing / totals[GRACE[0]][0]
                                if totals[GRACE[0]][0] else None),
                            "captured_unlabeled_slots": session_unlabeled,
                            "metrics": metrics})
        track_count += session_tracks
        missing_image_total += session_missing
        unlabeled_total += session_unlabeled
        expected_total += totals[GRACE[0]][0]

    if track_count != result["annotated_transits"] or expected_total != result["transit_weighted_expected_1hz_slots"]:
        raise ValueError("Transit counts/denominators do not reproduce")
    if missing_image_total != result["missing_capture_slots_inside_annotated_transits"]:
        raise ValueError("Target-weighted missing-image slot count does not reproduce")
    if unlabeled_total != result["captured_but_unlabeled_slots_inside_annotated_transits"]:
        raise ValueError("Captured-but-unlabeled slot count does not reproduce")
    if missing_image_total != cadence["annotated_transit_windows"]["missing_nominal_capture_slots_inside_transit_windows"]:
        raise ValueError("Transit missing-image count disagrees with cadence audit")

    treatment_checks = 0
    for item in result["results"]:
        grace = int(item["grace_seconds"])
        rows = [session["metrics"][grace] for session in per_session]
        observed = [row["annotated_detection_custody"] for row in rows]
        filled = [row["missing_capture_slots_filled_custody"] for row in rows]
        perfect = [row["perfectly_labeled_custody"] for row in rows]
        means = item["equal_weight_session_mean_custody"]
        for key, values in (("observed_manual_labels", observed),
                            ("fill_missing_capture_slots_with_perfect_detections", filled),
                            ("perfect_detection_at_every_transit_slot", perfect)):
            if not close(means[key], sum(values) / len(values)):
                raise ValueError(f"Session mean does not reproduce for grace={grace} {key}")
            treatment_checks += 1
        effects = item["paired_custody_effect_percentage_points"]
        for name, values, offset in (
            ("capture_gap_fill_minus_observed", [b-a for a,b in zip(observed, filled)], 0),
            ("all_remaining_label_gaps_filled_minus_capture_gap_fill", [c-b for b,c in zip(filled, perfect)], 100),
            ("perfect_detection_minus_observed", [c-a for a,c in zip(observed, perfect)], 200),
        ):
            saved = effects[name]
            expected_mean = 100 * sum(values) / len(values)
            expected_ci = [100*x for x in boot(values, SEED + offset + grace)]
            if not close(saved["mean"], expected_mean):
                raise ValueError(f"Paired custody effect does not reproduce: {name} grace={grace}")
            if any(not close(a, b) for a, b in zip(saved["ci95_session_cluster_bootstrap"], expected_ci)):
                raise ValueError(f"Cluster bootstrap does not reproduce: {name} grace={grace}")
            treatment_checks += 1

    session_capture_gap_rates = [row["capture_gap_fraction"] for row in per_session
                                 if row["capture_gap_fraction"] is not None]
    pooled_capture_gap_fraction = missing_image_total / expected_total if expected_total else None
    audit_result = {
        "status": "passed_independent_source_and_statistical_reproduction",
        "scope": "Rebuilds session/transit nominal grids from publisher images, MOT labels, and per-frame timestamps; independently recomputes custody, paired effects, and session bootstrap intervals.",
        "archive_md5": actual_md5,
        "metadata_csv_sha256": digest(metadata),
        "cadence_audit_sha256": digest(cadence_path),
        "custody_result_sha256": digest(result_path),
        "sessions_checked": len(per_session), "transits_checked": track_count,
        "transit_weighted_expected_slots": expected_total,
        "missing_capture_slots_reproduced": missing_image_total,
        "captured_but_unlabeled_slots_reproduced": unlabeled_total,
        "empirical_capture_gap_proxy": {
            "estimand": "missing nominal 1 Hz image slots divided by expected slots inside annotated RSO transit windows; not confirmed failed commanded captures",
            "missing_capture_slots": missing_image_total,
            "expected_transit_slots": expected_total,
            "pooled_fraction": pooled_capture_gap_fraction,
            "pooled_percent": 100 * pooled_capture_gap_fraction if pooled_capture_gap_fraction is not None else None,
            "session_cluster_count": len(session_capture_gap_rates),
            "equal_weight_session_mean_fraction": sum(session_capture_gap_rates) / len(session_capture_gap_rates),
            "equal_weight_session_bootstrap_ci95_fraction": boot(session_capture_gap_rates, SEED + 900),
            "bootstrap_replicates": REPLICATES,
            "bootstrap_seed": SEED + 900,
            "interpretation_limit": "Captures missing from the released timestamp/image record may reflect archive selection, scheduling, downlink, or acquisition; this is not a hardware failure probability. The annotated transit windows are selected on positive tracks.",
        },
        "session_mean_checks": 9,
        "paired_effect_and_bootstrap_checks": treatment_checks - 9,
        "bootstrap_replicates_recomputed": REPLICATES,
        "zero_mismatches": True,
        "interpretation": "The custody sensitivity is reproducible for the sampled annotated transit windows. It remains a conditional upper-bound counterfactual, not proof of failed commanded exposures or an estimated hardware dropout rate.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(audit_result, indent=2) + "\n")
    return audit_result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=pathlib.Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--metadata", type=pathlib.Path, default=METADATA)
    parser.add_argument("--cadence-audit", type=pathlib.Path, default=CADENCE)
    parser.add_argument("--result", type=pathlib.Path, default=RESULT)
    parser.add_argument("--output", type=pathlib.Path, default=OUTPUT)
    args = parser.parse_args()
    result = audit(args.archive, args.metadata, args.cadence_audit, args.result, args.output)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
