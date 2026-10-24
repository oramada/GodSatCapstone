#!/usr/bin/env python3
"""Compare raw-WCS and star-corrected DUST orbit-match batches."""
import argparse
import csv
import json
import pathlib
from collections import defaultdict

import numpy as np

from validate_dust_tle_track import ROOT


def key_for(result):
    return result["dataset_set"], result["session"], int(result["track_id"])


def load_tracks(folder):
    results = {}
    for path in sorted(folder.glob("SET[12]_*_track_*.json")):
        result = json.loads(path.read_text())
        key = key_for(result)
        if key in results:
            raise AssertionError(f"duplicate track output in {folder}: {key}")
        results[key] = result
    return results


def metric(record, name):
    return record["track_temporal_validation"][name]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=pathlib.Path, default=ROOT / "outputs/dust-tle-track-validation/all-sets-trackfit-v2")
    parser.add_argument("--corrected-dir", type=pathlib.Path, default=ROOT / "outputs/dust-tle-track-validation/all-sets-star-corrected-v1")
    parser.add_argument("--output-dir", type=pathlib.Path, default=ROOT / "outputs/dust-tle-track-validation/star-correction-comparison")
    args = parser.parse_args()
    raw, corrected = load_tracks(args.raw_dir), load_tracks(args.corrected_dir)
    if raw.keys() != corrected.keys():
        raise AssertionError(f"track coverage differs: raw={len(raw)} corrected={len(corrected)}")
    details = []
    session_rows = defaultdict(list)
    same_id_frame_deltas = []
    for key in sorted(raw):
        r, c = raw[key], corrected[key]
        rm, cm = metric(r, "median_separation_deg"), metric(c, "median_separation_deg")
        delta = None if rm is None or cm is None else cm - rm
        details.append({
            "dataset_set": key[0],
            "session": key[1],
            "track_id": key[2],
            "raw_norad_id": r["selected_norad_id"],
            "corrected_norad_id": c["selected_norad_id"],
            "candidate_changed": r["selected_norad_id"] != c["selected_norad_id"],
            "raw_training_median_deg": r["track_candidate_ranking"][0]["training_median_separation_deg"],
            "corrected_training_median_deg": c["track_candidate_ranking"][0]["training_median_separation_deg"],
            "raw_heldout_frames": metric(r, "evaluated_frames"),
            "corrected_heldout_frames": metric(c, "evaluated_frames"),
            "raw_heldout_median_deg": rm,
            "corrected_heldout_median_deg": cm,
            "heldout_median_delta_deg": delta,
            "raw_fraction_under_0_15_deg": metric(r, "under_0_15_deg_fraction"),
            "corrected_fraction_under_0_15_deg": metric(c, "under_0_15_deg_fraction"),
        })
        if delta is not None:
            session_rows[key[:2]].append(delta)
        if r["selected_norad_id"] == c["selected_norad_id"]:
            raw_frames = {frame["frame"]: frame for frame in r["frame_results"] if frame["role"] == "held_out"}
            corrected_frames = {frame["frame"]: frame for frame in c["frame_results"] if frame["role"] == "held_out"}
            for frame in raw_frames.keys() & corrected_frames.keys():
                a, b = raw_frames[frame]["separation_deg"], corrected_frames[frame]["separation_deg"]
                if a is not None and b is not None:
                    same_id_frame_deltas.append(b - a)

    track_deltas = [row["heldout_median_delta_deg"] for row in details if row["heldout_median_delta_deg"] is not None]
    improved = sum(delta < -0.01 for delta in track_deltas)
    degraded = sum(delta > 0.01 for delta in track_deltas)
    stable = len(track_deltas) - improved - degraded
    raw_summary = json.loads((args.raw_dir / "all_tracks_summary.json").read_text())
    corrected_summary = json.loads((args.corrected_dir / "all_tracks_summary.json").read_text())
    sessions = []
    for (dataset_set, session), values in sorted(session_rows.items()):
        sessions.append({
            "dataset_set": dataset_set,
            "session": session,
            "comparable_tracks": len(values),
            "median_track_holdout_delta_deg": float(np.median(values)),
            "p95_track_holdout_delta_deg": float(np.percentile(values, 95)),
        })
    result = {
        "raw_mode": raw_summary.get("pointing_correction", "raw DUST WCS"),
        "corrected_mode": corrected_summary.get("pointing_correction"),
        "track_count": len(details),
        "candidate_identity_changed_tracks": sum(row["candidate_changed"] for row in details),
        "comparable_tracks_with_holdout": len(track_deltas),
        "tracks_improved_by_more_than_0_01_deg": improved,
        "tracks_degraded_by_more_than_0_01_deg": degraded,
        "tracks_within_0_01_deg": stable,
        "median_track_holdout_delta_deg": float(np.median(track_deltas)) if track_deltas else None,
        "p95_track_holdout_delta_deg": float(np.percentile(track_deltas, 95)) if track_deltas else None,
        "same_candidate_frame_count": len(same_id_frame_deltas),
        "median_same_candidate_frame_delta_deg": float(np.median(same_id_frame_deltas)) if same_id_frame_deltas else None,
        "raw_pooled_frame_metrics": raw_summary["held_out_residual_summary_deg"],
        "corrected_pooled_frame_metrics": corrected_summary["held_out_residual_summary_deg"],
        "raw_track_fit_and_holdout_under_0_15_count": json.loads((args.raw_dir / "independent_audit.json").read_text())["tracks_with_training_and_holdout_median_under_0_15_deg"],
        "corrected_track_fit_and_holdout_under_0_15_count": json.loads((args.corrected_dir / "independent_audit.json").read_text())["tracks_with_training_and_holdout_median_under_0_15_deg"],
        "per_session_delta": sessions,
        "interpretation": "Star-derived WCS correction sensitivity is not NORAD identity validation; DUST provides no NORAD labels.",
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "summary.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    with (args.output_dir / "per_track_comparison.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(details[0]))
        writer.writeheader()
        writer.writerows(details)
    print(json.dumps({
        "output": str(args.output_dir / "summary.json"),
        "candidate_identity_changed_tracks": result["candidate_identity_changed_tracks"],
        "improved": improved,
        "degraded": degraded,
        "stable": stable,
        "median_track_holdout_delta_deg": result["median_track_holdout_delta_deg"],
        "raw_pooled_frame_metrics": result["raw_pooled_frame_metrics"],
        "corrected_pooled_frame_metrics": result["corrected_pooled_frame_metrics"],
    }, indent=2))


if __name__ == "__main__":
    main()
