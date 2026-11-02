"""Measure 1 Hz capture-cadence gaps in the DUST on-orbit image sessions.

This is empirical evidence of missing nominal image timestamps, not proof that
the camera attempted and failed to acquire those exposures. Session and transit
boundaries are censored, and cadence gaps can also reflect archive selection or
intentional instrument scheduling.
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
import pathlib
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.analysis.analyze_dust_dropout import DEFAULT_ARCHIVE, MD5, read_sessions

METADATA = ROOT / "data/onboard_sensor/dust_star_tracker/dropout_study/spacecraft_attitude_ephemeris.csv"
OUTPUT = ROOT / "data/onboard_sensor/dust_star_tracker/dropout_study/capture_cadence_audit.json"
NOMINAL_PERIOD_SECONDS = 1.0
GRID_TOLERANCE_SECONDS = 0.01


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_time(value: str) -> dt.datetime:
    instant = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if instant.tzinfo is None:
        return instant.replace(tzinfo=dt.timezone.utc)
    return instant.astimezone(dt.timezone.utc)


def audit(archive: pathlib.Path = DEFAULT_ARCHIVE, metadata: pathlib.Path = METADATA,
          output: pathlib.Path = OUTPUT) -> dict:
    archive, metadata, output = map(pathlib.Path, (archive, metadata, output))
    md5 = hashlib.md5(archive.read_bytes()).hexdigest()
    if md5 != MD5:
        raise ValueError(f"DUST archive MD5 mismatch: expected {MD5}, got {md5}")

    sessions, inventory, *_ = read_sessions(archive)
    timestamps: dict[str, dict[int, dt.datetime]] = {}
    rows_read = 0
    with metadata.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            rows_read += 1
            session = row["session"]
            frame = int(row["frame_index"])
            if session not in sessions or frame in timestamps.setdefault(session, {}):
                raise ValueError(f"Unknown session or duplicate frame in metadata: {session} frame {frame}")
            image_name = pathlib.PurePosixPath(sessions[session]["images"][frame - 1]).name
            if row["h5_filename"] != pathlib.Path(image_name).with_suffix(".h5").name:
                raise ValueError(f"H5 metadata does not match image index: {session} frame {frame}")
            timestamps[session][frame] = parse_time(row["epoch_utc"])

    gaps = []
    session_results = []
    total_expected = total_observed = total_missing = 0
    transit_expected = transit_captured = transit_missing = transit_labelled = 0
    transit_label_gaps = 0
    for session_name, session in sorted(sessions.items()):
        frame_times = timestamps.get(session_name, {})
        image_count = len(session["images"])
        if set(frame_times) != set(range(1, image_count + 1)):
            raise ValueError(f"Timestamp coverage differs from images in {session_name}")
        ordered = sorted(frame_times.items())
        session_start = ordered[0][1]
        for frame, when in ordered:
            elapsed = (when - session_start).total_seconds()
            if abs(elapsed - round(elapsed / NOMINAL_PERIOD_SECONDS) * NOMINAL_PERIOD_SECONDS) > GRID_TOLERANCE_SECONDS:
                raise ValueError(f"Frame timestamp falls off the nominal 1 Hz grid: {session_name} frame {frame}")

        session_gaps = []
        for (before_frame, before_time), (after_frame, after_time) in zip(ordered, ordered[1:]):
            elapsed = (after_time - before_time).total_seconds()
            ticks = round(elapsed / NOMINAL_PERIOD_SECONDS)
            if ticks < 1 or abs(elapsed - ticks * NOMINAL_PERIOD_SECONDS) > GRID_TOLERANCE_SECONDS:
                raise ValueError(f"Non-integral or non-monotonic cadence interval in {session_name}")
            missing = max(0, ticks - 1)
            if missing:
                gap = {"session": session_name, "before_frame": before_frame,
                       "after_frame": after_frame, "elapsed_seconds": elapsed,
                       "missing_nominal_1hz_slots": missing,
                       "start_utc": before_time.isoformat().replace("+00:00", "Z"),
                       "end_utc": after_time.isoformat().replace("+00:00", "Z")}
                session_gaps.append(gap)
                gaps.append(gap)

        expected = round((ordered[-1][1] - ordered[0][1]).total_seconds() / NOMINAL_PERIOD_SECONDS) + 1
        observed = len(ordered)
        missing = expected - observed
        if missing != sum(gap["missing_nominal_1hz_slots"] for gap in session_gaps):
            raise ValueError(f"Session expected-slot count does not reconcile in {session_name}")
        if missing < 0:
            raise ValueError(f"Observed frames exceed nominal grid slots in {session_name}")

        frame_seconds = {frame: (when - session_start).total_seconds()
                         for frame, when in ordered}
        track_expected = track_captured = track_missing = track_labels = track_label_gaps = 0
        for labels in session["tracks"].values():
            frames = sorted(set(labels))
            if not frames:
                continue
            start_time, end_time = frame_times[frames[0]], frame_times[frames[-1]]
            expected_track = round((end_time - start_time).total_seconds() / NOMINAL_PERIOD_SECONDS) + 1
            captured_track = sum(start_time <= when <= end_time for when in frame_times.values())
            missing_track = expected_track - captured_track
            if missing_track < 0:
                raise ValueError(f"Transit captured-frame count exceeds 1 Hz opportunities in {session_name}")
            span_frames = round((end_time - start_time).total_seconds() / NOMINAL_PERIOD_SECONDS) + 1
            label_gaps = span_frames - len(frames)
            track_expected += expected_track
            track_captured += captured_track
            track_missing += missing_track
            track_labels += len(frames)
            track_label_gaps += label_gaps

        total_expected += expected
        total_observed += observed
        total_missing += missing
        transit_expected += track_expected
        transit_captured += track_captured
        transit_missing += track_missing
        transit_labelled += track_labels
        transit_label_gaps += track_label_gaps
        session_results.append({
            "session": session_name,
            "image_frames": image_count,
            "nominal_1hz_slots_between_first_and_last_image": expected,
            "observed_images": observed,
            "missing_nominal_capture_slots": missing,
            "cadence_gap_intervals": len(session_gaps),
            "rso_transits": len(session["tracks"]),
            "transit_weighted_nominal_slots": track_expected,
            "transit_weighted_captured_images": track_captured,
            "transit_weighted_missing_capture_slots": track_missing,
            "transit_weighted_manual_labels": track_labels,
            "transit_weighted_captured_but_unlabeled_slots": track_captured - track_labels,
            "transit_weighted_nominal_slots_without_manual_label": track_label_gaps,
        })

    if rows_read != sum(item["image_frames"] for item in inventory.values()):
        raise ValueError("Ephemeris metadata row count does not match the image inventory")
    output.parent.mkdir(parents=True, exist_ok=True)
    result = {
        "status": "completed",
        "source": "DUST CASSIOPE/FAI per-image ephemeris timestamps matched to the published 1 Hz imaging cadence",
        "cadence_reference": {
            "title": "University of Calgary e-POP FAI processed data handbook",
            "url": "https://epop.phys.ucalgary.ca/data-handbook/fai-png-image/",
        },
        "archive_md5": md5,
        "metadata_csv_sha256": sha256(metadata),
        "nominal_period_seconds": NOMINAL_PERIOD_SECONDS,
        "grid_tolerance_seconds": GRID_TOLERANCE_SECONDS,
        "session_count": len(session_results),
        "metadata_image_rows_checked": rows_read,
        "image_frames_checked": total_observed,
        "session_cadence": {
            "nominal_slots_between_first_and_last_images": total_expected,
            "observed_images": total_observed,
            "missing_nominal_capture_slots": total_missing,
            "observed_capture_fraction": total_observed / total_expected if total_expected else None,
            "multi_second_gap_intervals": len(gaps),
            "gap_duration_seconds": sorted({gap["elapsed_seconds"] for gap in gaps}),
        },
        "annotated_transit_windows": {
            "transit_weighted_nominal_slots": transit_expected,
            "captured_images_inside_transit_windows": transit_captured,
            "missing_nominal_capture_slots_inside_transit_windows": transit_missing,
            "capture_fraction_inside_transit_windows": transit_captured / transit_expected if transit_expected else None,
            "manual_rso_labels": transit_labelled,
            "captured_but_unlabeled_slots": transit_captured - transit_labelled,
            "nominal_slots_without_manual_rso_label": transit_label_gaps,
        },
        "cadence_gaps": gaps,
        "sessions": session_results,
        "interpretation": "The timestamps contain gaps relative to the published 1 Hz cadence, including gaps inside annotated RSO transit windows. These are missing nominal image slots in the released record; without instrument command, power, downlink, or acquisition logs they cannot be attributed to hardware dropout or confirmed as attempted exposures. Unlabeled captured images also combine detector misses and annotation omissions.",
        "limitations": [
            "Observation sessions are selected intervals; session boundaries are censored and excluded from gap rates.",
            "Nominal 1 Hz cadence establishes a schedule expectation, not proof an exposure was commanded during each missing slot.",
            "Transit-window counts weight an image slot once per annotated target transit and are not independent sensor attempts.",
            "The 22 sessions cover 2023 and do not estimate four-year or constellation-wide sensor reliability.",
        ],
    }
    output.write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=pathlib.Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--metadata", type=pathlib.Path, default=METADATA)
    parser.add_argument("--output", type=pathlib.Path, default=OUTPUT)
    args = parser.parse_args()
    result = audit(args.archive, args.metadata, args.output)
    print(json.dumps({key: result[key] for key in (
        "status", "session_count", "image_frames_checked", "session_cadence",
        "annotated_transit_windows", "cadence_gaps")}, indent=2))


if __name__ == "__main__":
    main()
