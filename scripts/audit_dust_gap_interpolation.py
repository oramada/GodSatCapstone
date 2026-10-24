#!/usr/bin/env python3
"""Cross-validate DUST linear track interpolation at held-out labeled frames."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import pathlib
import zipfile
from typing import Optional

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.analyze_dust_dropout import DEFAULT_ARCHIVE, MD5, read_sessions
from scripts.audit_dust_gap_image_visibility import box_center

OUTPUT_DIR = ROOT / "data/onboard_sensor/dust_star_tracker/dropout_study"
GAP_LENGTHS = (1, 2, 3, 13)
SEED = 20261010


def sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def summarize(errors: list[dict], gap_length: int, replicates: int = 20000) -> dict:
    rows = [r for r in errors if r["gap_length_frames"] == gap_length]
    if not rows:
        return {"gap_length_frames": gap_length, "validated_hidden_frames": 0}
    per_session = {}
    for row in rows:
        per_session.setdefault(row["session"], []).append(row)
    session_ids = sorted(per_session)
    # Equal weight per observing session; the CI resamples independent sessions,
    # not highly overlapping hidden-frame windows.
    session_error = np.asarray([np.mean([r["error_px"] for r in per_session[s]]) for s in session_ids])
    session_within2 = np.asarray([np.mean([r["error_px"] <= 2 for r in per_session[s]]) for s in session_ids])
    rng = np.random.default_rng(SEED + gap_length)
    indexes = rng.integers(0, len(session_ids), size=(replicates, len(session_ids)))
    mean_error_ci = np.quantile(session_error[indexes].mean(axis=1), [.025, .975])
    within2_ci = np.quantile(session_within2[indexes].mean(axis=1), [.025, .975])
    values = np.asarray([r["error_px"] for r in rows])
    return {
        "gap_length_frames": gap_length,
        "validated_hidden_frames": len(rows),
        "tracks": len({(r["session"], r["track_id"]) for r in rows}),
        "sessions": len(session_ids),
        "pixel_error_median": float(np.median(values)),
        "pixel_error_p90": float(np.quantile(values, .90)),
        "pixel_error_p95": float(np.quantile(values, .95)),
        "fraction_within_2px": float(np.mean(values <= 2)),
        "fraction_within_5px": float(np.mean(values <= 5)),
        "equal_session_mean_pixel_error": float(session_error.mean()),
        "equal_session_mean_pixel_error_95pct_ci": [float(x) for x in mean_error_ci],
        "equal_session_fraction_within_2px": float(session_within2.mean()),
        "equal_session_fraction_within_2px_95pct_ci": [float(x) for x in within2_ci],
        "session_bootstrap_replicates": replicates,
        "bootstrap_seed": SEED + gap_length,
    }


def audit(archive: pathlib.Path = DEFAULT_ARCHIVE, output_dir: Optional[pathlib.Path] = None) -> dict:
    archive = pathlib.Path(archive)
    digest = hashlib.md5(archive.read_bytes()).hexdigest()
    if digest != MD5:
        raise ValueError(f"DUST archive MD5 mismatch: expected {MD5}, got {digest}")
    sessions, _, *_ = read_sessions(archive)
    errors = []
    with zipfile.ZipFile(archive) as bundle:
        for session_name, session in sorted(sessions.items()):
            labels = csv.reader(io.TextIOWrapper(bundle.open(session["mot_path"]), encoding="utf-8"))
            tracks = {}
            for row in labels:
                if len(row) != 9:
                    continue
                frame, track_id = int(row[0]), int(row[1])
                tracks.setdefault(track_id, {})[frame] = box_center(row)
            for track_id, observations in tracks.items():
                frames = sorted(observations)
                if not frames:
                    continue
                frame_set = set(frames)
                for gap in GAP_LENGTHS:
                    span = gap + 1
                    for left in frames:
                        right = left + span
                        if right not in frame_set or not all(f in frame_set for f in range(left, right + 1)):
                            continue
                        x0, y0 = observations[left]
                        x1, y1 = observations[right]
                        for frame in range(left + 1, right):
                            alpha = (frame - left) / span
                            predicted = (x0 + alpha * (x1 - x0), y0 + alpha * (y1 - y0))
                            truth = observations[frame]
                            errors.append({
                                "session": session_name, "track_id": track_id,
                                "left_frame": left, "right_frame": right,
                                "hidden_frame": frame, "gap_length_frames": gap,
                                "predicted_x": predicted[0], "predicted_y": predicted[1],
                                "labeled_x": truth[0], "labeled_y": truth[1],
                                "error_px": float(np.hypot(predicted[0] - truth[0], predicted[1] - truth[1])),
                            })
    summaries = [summarize(errors, gap) for gap in GAP_LENGTHS]
    output = {
        "status": "completed_labeled_track_interpolation_cross_validation",
        "dataset": "DUST CASSIOPE/FAI on-orbit imagery, 2023",
        "archive_md5": digest,
        "archive_sha256": sha256(archive),
        "validation_design": {
            "gap_lengths_matching_observed_internal_gaps": list(GAP_LENGTHS),
            "method": "Hide contiguous interior labels from already-labeled transits and linearly interpolate pixel centers from the two endpoint labels.",
            "heldout_frames": len(errors),
            "unique_tracks": len({(r["session"], r["track_id"]) for r in errors}),
            "sessions": len({r["session"] for r in errors}),
            "label_source": "Publisher MOT boxes; this measures interpolation error against labels, not absolute astrometric error.",
        },
        "by_gap_length": summaries,
        "interpretation_limit": (
            "This cross-validation estimates how well linear pixel interpolation recovers labeled positions "
            "when annotations are synthetically hidden. It does not identify an unlabeled source, validate "
            "catalog identity, prove an imaging attempt, or attribute gaps to sensor or algorithm dropout."
        ),
    }
    outdir = pathlib.Path(output_dir) if output_dir is not None else OUTPUT_DIR
    outdir.mkdir(parents=True, exist_ok=True)
    with (outdir / "gap_interpolation_cross_validation.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(errors[0]) if errors else ["session"])
        writer.writeheader()
        writer.writerows(errors)
    output["validation_design"]["csv_sha256"] = sha256(outdir / "gap_interpolation_cross_validation.csv")
    (outdir / "gap_interpolation_cross_validation.json").write_text(json.dumps(output, indent=2) + "\n")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=pathlib.Path, default=DEFAULT_ARCHIVE)
    args = parser.parse_args()
    result = audit(args.archive)
    print(json.dumps({"status": result["status"], "validation_design": result["validation_design"],
                      "by_gap_length": result["by_gap_length"]}, indent=2))


if __name__ == "__main__":
    main()
