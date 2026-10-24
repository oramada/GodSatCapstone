#!/usr/bin/env python3
"""Test catalog shortlist and element-age sensitivity for a high-residual DUST track."""
import argparse
import json
import pathlib

from validate_dust_tle_track import DUST_ZIP, ROOT, run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--set", dest="set_name", default="SET 1", choices=("SET 1", "SET 2"))
    parser.add_argument("--session", default="2023_06_03")
    parser.add_argument("--track", type=int, default=2)
    parser.add_argument("--output", type=pathlib.Path, default=ROOT / "outputs/dust-tle-track-validation/outlier-sensitivity/2023_06_03_track_2.json")
    args = parser.parse_args()
    cases = []
    for max_age_hours, candidate_limit in (
        (72, 50), (168, 50), (720, 50), (72, 500), (72, 23087), (720, 23087),
    ):
        result = run(
            args.session, args.track, args.set_name,
            candidate_limit=candidate_limit,
            max_age_hours=max_age_hours,
        )
        score = result["track_candidate_ranking"][0]
        cases.append({
            "max_element_age_hours": max_age_hours,
            "candidate_limit": candidate_limit,
            "candidates_available_in_shortlist": result["candidate_shortlist_size"],
            "selected_norad_id": result["selected_norad_id"],
            "selected_first_frame_residual_deg": score["first_frame_separation_deg"],
            "training_median_residual_deg": score["training_median_separation_deg"],
            "training_p95_residual_deg": score["training_p95_separation_deg"],
            "held_out_frames": result["track_temporal_validation"]["evaluated_frames"],
            "held_out_median_residual_deg": result["track_temporal_validation"]["median_separation_deg"],
            "held_out_p95_residual_deg": result["track_temporal_validation"]["p95_separation_deg"],
            "held_out_max_residual_deg": result["track_temporal_validation"]["max_separation_deg"],
            "held_out_fraction_under_0_15_deg": result["track_temporal_validation"]["under_0_15_deg_fraction"],
            "selected_tle_max_age_hours": max(row["tle_age_hours"] for row in result["frame_results"]),
        })
        print(
            f"age={max_age_hours}h candidates={candidate_limit} "
            f"NORAD={result['selected_norad_id']} "
            f"fit={score['training_median_separation_deg']:.3f}deg "
            f"holdout={result['track_temporal_validation']['median_separation_deg']:.3f}deg",
            flush=True,
        )
    payload = {
        "session": args.session,
        "dataset_set": args.set_name,
        "track_id": args.track,
        "dust_archive_md5": (ROOT / "data/onboard_sensor/dust_star_tracker/DUST.zip.md5").read_text().strip(),
        "purpose": "diagnostic sensitivity only; the DUST track has no NORAD identity label",
        "cases": cases,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(args.output), "case_count": len(cases), "selected_ids": sorted({c["selected_norad_id"] for c in cases})}, indent=2))


if __name__ == "__main__":
    main()
