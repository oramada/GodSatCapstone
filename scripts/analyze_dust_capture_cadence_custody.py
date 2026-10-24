"""Estimate DUST track-custody sensitivity on its observed 1 Hz time grid.

The primary result replays manually annotated detections. Counterfactuals fill
missing image timestamps, then all missing transit labels, with perfect target
detections. They bound the possible custody effect of cadence gaps but do not
identify camera failure or calibrated detection probability.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import pathlib
import random
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.analyze_dust_dropout import DEFAULT_ARCHIVE, MD5, read_sessions

STUDY = ROOT / "data/onboard_sensor/dust_star_tracker/dropout_study"
METADATA = STUDY / "spacecraft_attitude_ephemeris.csv"
CADENCE_AUDIT = STUDY / "capture_cadence_audit.json"
OUTPUT = STUDY / "capture_cadence_custody.json"
GRACE_SECONDS = (1, 5, 10)
BOOTSTRAP_REPLICATES = 10_000
BOOTSTRAP_SEED = 7318


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_time(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def session_custody(session: dict, frame_times: dict[int, dt.datetime]) -> tuple[int, int, int, dict[int, dict[str, float]]]:
    totals = {grace: {"expected": 0, "observed": 0, "capture_filled": 0, "perfect": 0}
              for grace in GRACE_SECONDS}
    count_tracks = 0
    missing_capture_slots = captured_unlabeled_slots = 0
    for labels in session["tracks"].values():
        label_frames = sorted(set(map(int, labels)))
        if not label_frames:
            continue
        count_tracks += 1
        first, last = label_frames[0], label_frames[-1]
        start_time, end_time = frame_times[first], frame_times[last]
        duration = (end_time - start_time).total_seconds()
        slot_count = round(duration) + 1
        if abs(duration - round(duration)) > 0.01 or slot_count < 1:
            raise ValueError("Annotated transit does not align with the nominal 1 Hz time grid")

        captured_slots = set()
        for frame, when in frame_times.items():
            if start_time <= when <= end_time:
                offset = (when - start_time).total_seconds()
                slot = round(offset)
                if abs(offset - slot) > 0.01:
                    raise ValueError("Captured frame is off the annotated transit's 1 Hz grid")
                captured_slots.add(slot)
        label_slots = set()
        for frame in label_frames:
            offset = (frame_times[frame] - start_time).total_seconds()
            slot = round(offset)
            if abs(offset - slot) > 0.01:
                raise ValueError("MOT label timestamp is off the nominal 1 Hz grid")
            label_slots.add(slot)
        expected_slots = set(range(slot_count))
        if not label_slots <= captured_slots or not captured_slots <= expected_slots:
            raise ValueError("Transit labels/images do not reconcile to nominal time slots")
        absent_image_slots = expected_slots - captured_slots
        captured_unlabeled = captured_slots - label_slots
        missing_capture_slots += len(absent_image_slots)
        captured_unlabeled_slots += len(captured_unlabeled)

        for grace in GRACE_SECONDS:
            last_observed = -10**12
            last_capture_filled = -10**12
            observed_custody = capture_filled_custody = 0
            capture_filled_labels = label_slots | absent_image_slots
            for slot in range(slot_count):
                if slot in label_slots:
                    last_observed = slot
                if slot in capture_filled_labels:
                    last_capture_filled = slot
                observed_custody += slot - last_observed <= grace
                capture_filled_custody += slot - last_capture_filled <= grace
            totals[grace]["expected"] += slot_count
            totals[grace]["observed"] += observed_custody
            totals[grace]["capture_filled"] += capture_filled_custody
            totals[grace]["perfect"] += slot_count

    metrics = {}
    for grace in GRACE_SECONDS:
        row = totals[grace]
        denominator = row["expected"]
        metrics[grace] = {
            "expected_target_slots": denominator,
            "annotated_detection_custody": row["observed"] / denominator if denominator else None,
            "missing_capture_slots_filled_custody": row["capture_filled"] / denominator if denominator else None,
            "perfectly_labeled_custody": row["perfect"] / denominator if denominator else None,
        }
    return count_tracks, missing_capture_slots, captured_unlabeled_slots, metrics


def bootstrap_ci(values: list[float], seed: int) -> list[float]:
    rng = random.Random(seed)
    n = len(values)
    samples = []
    for _ in range(BOOTSTRAP_REPLICATES):
        samples.append(sum(values[rng.randrange(n)] for _ in range(n)) / n)
    samples.sort()
    return [samples[int(0.025 * (BOOTSTRAP_REPLICATES - 1))],
            samples[int(0.975 * (BOOTSTRAP_REPLICATES - 1))]]


def analyze(archive: pathlib.Path = DEFAULT_ARCHIVE, metadata: pathlib.Path = METADATA,
            cadence_audit: pathlib.Path = CADENCE_AUDIT,
            output: pathlib.Path = OUTPUT) -> dict:
    archive, metadata, cadence_audit, output = map(pathlib.Path,
        (archive, metadata, cadence_audit, output))
    archive_md5 = hashlib.md5(archive.read_bytes()).hexdigest()
    if archive_md5 != MD5:
        raise ValueError(f"DUST archive MD5 mismatch: expected {MD5}, got {archive_md5}")
    cadence = json.loads(cadence_audit.read_text())
    if cadence.get("status") != "completed":
        raise ValueError("Run the validated DUST capture-cadence audit first")

    timestamps: dict[str, dict[int, dt.datetime]] = {}
    with metadata.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            session, frame = row["session"], int(row["frame_index"])
            if frame in timestamps.setdefault(session, {}):
                raise ValueError(f"Duplicate spacecraft ephemeris frame: {session} {frame}")
            timestamps[session][frame] = parse_time(row["epoch_utc"])
    sessions, inventory, *_ = read_sessions(archive)
    if set(sessions) != set(timestamps):
        raise ValueError("DUST image and timestamp session sets differ")

    session_rows = []
    by_grace: dict[int, list[dict[str, float]]] = {grace: [] for grace in GRACE_SECONDS}
    track_count = expected_slots = total_missing = total_unlabeled = 0
    for name, session in sorted(sessions.items()):
        times = timestamps[name]
        if set(times) != set(range(1, int(inventory[name]["image_frames"]) + 1)):
            raise ValueError(f"Image timestamp inventory is incomplete for {name}")
        n_tracks, n_missing, n_unlabeled, metrics = session_custody(session, times)
        track_count += n_tracks
        total_missing += n_missing
        total_unlabeled += n_unlabeled
        for grace in GRACE_SECONDS:
            row = metrics[grace]
            by_grace[grace].append(row)
            expected_slots += row["expected_target_slots"] if grace == GRACE_SECONDS[0] else 0
        session_rows.append({"session": name, "annotated_transits": n_tracks,
                             "missing_capture_slots_in_transit_windows": n_missing,
                             "captured_but_unlabeled_slots_in_transit_windows": n_unlabeled,
                             "custody_by_grace_seconds": {str(k): v for k, v in metrics.items()}})

    if track_count != 160 or total_missing != cadence["annotated_transit_windows"]["missing_nominal_capture_slots_inside_transit_windows"]:
        raise ValueError("Transit-window totals disagree with the independent cadence audit")
    if total_unlabeled != cadence["annotated_transit_windows"]["captured_but_unlabeled_slots"]:
        raise ValueError("Captured-but-unlabeled total disagrees with the independent cadence audit")

    results = []
    for grace in GRACE_SECONDS:
        sessions_for_grace = by_grace[grace]
        actual = [row["annotated_detection_custody"] for row in sessions_for_grace]
        capture_filled = [row["missing_capture_slots_filled_custody"] for row in sessions_for_grace]
        perfect = [row["perfectly_labeled_custody"] for row in sessions_for_grace]
        capture_fill_effect = [b - a for a, b in zip(actual, capture_filled)]
        all_label_gap_effect = [c - b for b, c in zip(capture_filled, perfect)]
        total_gap_effect = [c - a for a, c in zip(actual, perfect)]
        results.append({
            "grace_seconds": grace,
            "equal_weight_session_mean_custody": {
                "observed_manual_labels": sum(actual) / len(actual),
                "fill_missing_capture_slots_with_perfect_detections": sum(capture_filled) / len(capture_filled),
                "perfect_detection_at_every_transit_slot": sum(perfect) / len(perfect),
            },
            "paired_custody_effect_percentage_points": {
                "capture_gap_fill_minus_observed": {
                    "mean": 100 * sum(capture_fill_effect) / len(capture_fill_effect),
                    "ci95_session_cluster_bootstrap": [100 * x for x in bootstrap_ci(capture_fill_effect, BOOTSTRAP_SEED + grace)],
                },
                "all_remaining_label_gaps_filled_minus_capture_gap_fill": {
                    "mean": 100 * sum(all_label_gap_effect) / len(all_label_gap_effect),
                    "ci95_session_cluster_bootstrap": [100 * x for x in bootstrap_ci(all_label_gap_effect, BOOTSTRAP_SEED + 100 + grace)],
                },
                "perfect_detection_minus_observed": {
                    "mean": 100 * sum(total_gap_effect) / len(total_gap_effect),
                    "ci95_session_cluster_bootstrap": [100 * x for x in bootstrap_ci(total_gap_effect, BOOTSTRAP_SEED + 200 + grace)],
                },
            },
        })

    result = {
        "status": "completed_conditional_cadence_custody_sensitivity",
        "dataset": "DUST CASSIOPE/FAI on-orbit imagery, 2023",
        "archive_md5": archive_md5,
        "metadata_csv_sha256": sha256(metadata),
        "cadence_audit_sha256": sha256(cadence_audit),
        "cadence_reference": cadence["cadence_reference"],
        "sessions": len(session_rows), "annotated_transits": track_count,
        "transit_weighted_expected_1hz_slots": expected_slots,
        "missing_capture_slots_inside_annotated_transits": total_missing,
        "captured_but_unlabeled_slots_inside_annotated_transits": total_unlabeled,
        "manual_label_coverage_of_transit_slots": (expected_slots - total_missing - total_unlabeled) / expected_slots,
        "bootstrap": {"unit": "session", "replicates": BOOTSTRAP_REPLICATES,
                      "seed": BOOTSTRAP_SEED, "interval": "percentile 95%"},
        "results": results,
        "sessions_detail": session_rows,
        "interpretation": "This compares observed manual labels to optimistic counterfactuals on the nominal 1 Hz grid inside annotated first-to-last transit spans. Filling missing capture timestamps assumes a perfect RSO detection at each absent exposure; filling other unlabelled slots also assumes perfect annotation/detection. It quantifies conditional custody sensitivity in these 22 selected 2023 sessions, not sensor hardware failure probability or catalog-wide dropout effectiveness.",
        "limitations": [
            "Transit entry and exit outside first and last manual labels are censored.",
            "A nominal missing timestamp is not proof an exposure was commanded; scheduling and archive selection can also create gaps.",
            "Manual labels are not independent detector outputs, and missing labels on captured images can be annotation or detection gaps.",
            "Session-cluster inference applies only to the selected DUST sessions and does not generalize to other sensors or four-year operations.",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=pathlib.Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--metadata", type=pathlib.Path, default=METADATA)
    parser.add_argument("--cadence-audit", type=pathlib.Path, default=CADENCE_AUDIT)
    parser.add_argument("--output", type=pathlib.Path, default=OUTPUT)
    args = parser.parse_args()
    result = analyze(args.archive, args.metadata, args.cadence_audit, args.output)
    print(json.dumps({key: result[key] for key in (
        "status", "sessions", "annotated_transits", "transit_weighted_expected_1hz_slots",
        "missing_capture_slots_inside_annotated_transits",
        "captured_but_unlabeled_slots_inside_annotated_transits",
        "manual_label_coverage_of_transit_slots", "results")}, indent=2))


if __name__ == "__main__":
    main()
