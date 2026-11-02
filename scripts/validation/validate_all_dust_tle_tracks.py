#!/usr/bin/env python3
"""Run historical-TLE directional/temporal checks on every annotated DUST track."""

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))

import argparse
import collections
import hashlib
import json
import pathlib
import zipfile

import numpy as np

from scripts.validation.validate_dust_tle_track import DUST_ZIP, ROOT, run


def all_tracks():
    with zipfile.ZipFile(DUST_ZIP) as archive:
        annotation_paths = sorted(
            name for name in archive.namelist()
            if "/RSO_Annotations/" in name and name.endswith("_MOT_gt.txt")
        )
        for name in annotation_paths:
            session_path = pathlib.PurePosixPath(name).parent.parent
            set_name = session_path.parent.name
            session = session_path.name
            text = archive.read(name).decode("utf-8-sig")
            track_ids = sorted({
                int(float(line.split(",")[1]))
                for line in text.splitlines()
                if line.strip() and len(line.split(",")) >= 6
            })
            for track_id in track_ids:
                yield set_name, session, track_id


def aggregate(results):
    held_out = []
    track_rows = []
    selected_ids = collections.Counter()
    for result in results:
        selected_ids[str(result["selected_norad_id"])] += 1
        frames = result["frame_results"]
        residuals = [
            row["separation_deg"] for row in frames
            if row["role"] == "held_out"
            and row["separation_deg"] is not None
        ]
        held_out.extend(residuals)
        candidates = result["first_frame_candidates"]
        ranking = result["track_candidate_ranking"]
        track_rows.append({
            "session": result["session"],
            "dataset_set": result["dataset_set"],
            "track_id": result["track_id"],
            "selected_norad_id": result["selected_norad_id"],
            "selection_residual_deg": candidates[0]["separation_deg"],
            "training_selection_residual_deg": ranking[0]["training_median_separation_deg"],
            "training_selection_margin_deg": (
                ranking[1]["training_median_separation_deg"] - ranking[0]["training_median_separation_deg"]
                if len(ranking) > 1 else None
            ),
            "runner_up_residual_deg": candidates[1]["separation_deg"] if len(candidates) > 1 else None,
            "candidate_margin_deg": (
                candidates[1]["separation_deg"] - candidates[0]["separation_deg"]
                if len(candidates) > 1 else None
            ),
            "annotated_frames": len(frames),
            "held_out_frames": len(residuals),
            "held_out_median_residual_deg": float(np.median(residuals)) if residuals else None,
            "held_out_p95_residual_deg": float(np.percentile(residuals, 95)) if residuals else None,
            "held_out_max_residual_deg": max(residuals) if residuals else None,
            "held_out_fraction_under_0_15_deg": float(np.mean(np.asarray(residuals) < 0.15)) if residuals else None,
        })
    return {
        "method": "rank the 50 nearest fresh all-catalog GP/TLE objects by median residual on the first up-to-five annotated frames; report remaining frames as temporal holdout",
        "pointing_correction": results[0].get("pointing_correction", "raw DUST WCS") if results else "unknown",
        "truth_label_status": "DUST has no NORAD identity labels; associations are candidates, not truth matches",
        "track_count": len(results),
        "held_out_frame_count": len(held_out),
        "held_out_residual_summary_deg": {
            "median": float(np.median(held_out)) if held_out else None,
            "p95": float(np.percentile(held_out, 95)) if held_out else None,
            "max": max(held_out) if held_out else None,
            "fraction_under_0_15_deg": float(np.mean(np.asarray(held_out) < 0.15)) if held_out else None,
        },
        "candidate_selection_residual_summary_deg": {
            "median": float(np.median([r["selection_residual_deg"] for r in track_rows])) if track_rows else None,
            "p95": float(np.percentile([r["selection_residual_deg"] for r in track_rows], 95)) if track_rows else None,
            "fraction_under_0_15_deg": float(np.mean(np.asarray([r["selection_residual_deg"] for r in track_rows]) < 0.15)) if track_rows else None,
        },
        "track_training_fit_summary_deg": {
            "median": float(np.median([r["training_selection_residual_deg"] for r in track_rows])) if track_rows else None,
            "p95": float(np.percentile([r["training_selection_residual_deg"] for r in track_rows], 95)) if track_rows else None,
            "fraction_under_0_15_deg": float(np.mean(np.asarray([r["training_selection_residual_deg"] for r in track_rows]) < 0.15)) if track_rows else None,
        },
        "selected_norad_track_counts": dict(selected_ids.most_common()),
        "tracks": track_rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=pathlib.Path, default=ROOT / "outputs/dust-tle-track-validation/all")
    parser.add_argument("--star-pointing-correction", action="store_true")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    results = []
    tracks = list(all_tracks())
    print(f"tracks={len(tracks)}", flush=True)
    failures = []
    for index, (set_name, session, track_id) in enumerate(tracks, start=1):
        try:
            result = run(session, track_id, set_name, pointing_correction=args.star_pointing_correction)
            set_prefix = set_name.replace(" ", "")
            path = args.output_dir / f"{set_prefix}_{session}_track_{track_id}.json"
            path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
            results.append(result)
            heldout_median = result["track_temporal_validation"]["median_separation_deg"]
            heldout_label = "n/a" if heldout_median is None else f"{heldout_median:.5f}deg"
            print(
                f"{index}/{len(tracks)} {set_name}/{session} track={track_id} "
                f"NORAD={result['selected_norad_id']} "
                f"frames={result['frames_with_wcs_and_ephemeris']} "
                f"heldout_median={heldout_label}",
                flush=True,
            )
        except Exception as exc:  # retain coverage and error provenance instead of stopping the batch
            failures.append({"dataset_set": set_name, "session": session, "track_id": track_id, "error": f"{type(exc).__name__}: {exc}"})
            print(f"{index}/{len(tracks)} {set_name}/{session} track={track_id} ERROR {failures[-1]['error']}", flush=True)
    summary = aggregate(results)
    summary["attempted_track_count"] = len(tracks)
    summary["failures"] = failures
    summary["dust_archive_md5"] = DUST_ZIP.with_suffix('.zip.md5').read_text().strip()
    summary["source_archive_path"] = str(DUST_ZIP.relative_to(ROOT))
    source_manifest = ROOT / 'data/raw/manifest.json'
    summary["historical_orbit_source_manifest_sha256"] = hashlib.sha256(source_manifest.read_bytes()).hexdigest()
    summary["sensor_location"] = 'Onboard CASSIOPE star-tracker imagery; legacy storage directory name does not imply a ground sensor.'
    summary_path = args.output_dir / "all_tracks_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "output": str(summary_path),
        "attempted_tracks": len(tracks),
        "completed_tracks": len(results),
        "failures": len(failures),
        "held_out_frame_count": summary["held_out_frame_count"],
        "held_out_residual_summary_deg": summary["held_out_residual_summary_deg"],
        "candidate_selection_residual_summary_deg": summary["candidate_selection_residual_summary_deg"],
        "track_training_fit_summary_deg": summary["track_training_fit_summary_deg"],
    }, indent=2), flush=True)


if __name__ == "__main__":
    main()
