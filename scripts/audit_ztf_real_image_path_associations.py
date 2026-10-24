#!/usr/bin/env python3
"""Quantify predicted-path versus parallel-lane signal in real ZTF images.

This is deliberately a descriptive association audit. Catalog paths are not
independent image truth labels, and the selected image sample is opportunity-
conditioned, so the results must not be called detection or dropout rates.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
FULL = ROOT / "outputs/ztf-palomer-fullnight-2024-07-10"
SAMPLE = FULL / "image_sample_audit.json"
OUTPUT = FULL / "real_image_path_association_audit.json"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def audit(sample: dict, sample_hash: str) -> dict:
    rows = []
    for image in sample["image_results"]:
        for candidate in image["candidate_results"]:
            profile = candidate["pixel_profile_vs_parallel_controls"]
            offsets = profile.get("offset_profile", [])
            if not offsets:
                rows.append({"expid": str(image["expid"]),
                             "norad_id": int(candidate["norad_id"]),
                             "status": "insufficient_profile_samples"})
                continue
            predicted = [r for r in offsets if abs(float(r["shift_px"])) <= 5.0]
            controls = [r for r in offsets if 8.0 <= abs(float(r["shift_px"])) <= 15.0]
            if not predicted or not controls:
                rows.append({"expid": str(image["expid"]),
                             "norad_id": int(candidate["norad_id"]),
                             "status": "insufficient_matched_lanes"})
                continue
            peak = max(predicted, key=lambda r: float(r["median_excess_adu"]))
            center = profile.get("centerline_median_excess_adu")
            control_median = float(np.median([r["median_excess_adu"] for r in controls]))
            control_peak = max(float(r["median_excess_adu"]) for r in controls)
            rows.append({
                "expid": str(image["expid"]), "norad_id": int(candidate["norad_id"]),
                "status": "profiled", "profile_samples": int(profile["samples"]),
                "centerline_median_excess_adu": center,
                "predicted_band_peak_shift_px": float(peak["shift_px"]),
                "predicted_band_peak_excess_adu": float(peak["median_excess_adu"]),
                "parallel_control_median_excess_adu": control_median,
                "parallel_control_peak_excess_adu": control_peak,
                "predicted_band_peak_exceeds_control_peak": bool(
                    float(peak["median_excess_adu"]) > control_peak),
                "peak_within_2px": bool(abs(float(peak["shift_px"])) <= 2.0),
                "peak_at_centerline": bool(float(peak["shift_px"]) == 0.0),
            })

    usable = [r for r in rows if r["status"] == "profiled"]
    exposure_ids = sorted({r["expid"] for r in usable})
    # Bootstrap at the image level to avoid treating tracks from the same frame
    # as independent. This interval is descriptive for this selected image set.
    by_image = {expid: [r for r in usable if r["expid"] == expid]
                for expid in exposure_ids}
    image_differences = [float(np.median([
        r["predicted_band_peak_excess_adu"] - r["parallel_control_peak_excess_adu"]
        for r in group])) for group in by_image.values()]
    rng = np.random.default_rng(20261010)
    if image_differences:
        samples = np.asarray(image_differences)
        draws = rng.choice(samples, size=(20000, len(samples)), replace=True).mean(axis=1)
        ci = [float(x) for x in np.quantile(draws, [0.025, 0.975])]
    else:
        ci = [None, None]
    return {
        "status": "completed_descriptive_real_image_path_association_audit",
        "image_sample_sha256": sample_hash,
        "selection_and_measurement": {
            "images": len(sample["image_results"]),
            "predicted_opportunities": int(sample["opportunity_count"]),
            "profiled_opportunities": len(usable),
            "profile_unavailable": len(rows) - len(usable),
            "predicted_band_px": [-5.0, 5.0],
            "parallel_control_bands_px": [[-15.0, -8.0], [8.0, 15.0]],
            "source_metric": "Existing image pixel-profile median excess values; no labels or thresholds were fitted in this audit.",
        },
        "summary": {
            "predicted_band_peak_exceeds_both_parallel_control_bands":
                sum(r["predicted_band_peak_exceeds_control_peak"] for r in usable),
            "peak_within_2px_of_predicted_path": sum(r["peak_within_2px"] for r in usable),
            "peak_exactly_on_predicted_centerline": sum(r["peak_at_centerline"] for r in usable),
            "median_centerline_excess_adu": float(np.median([
                r["centerline_median_excess_adu"] for r in usable
                if r["centerline_median_excess_adu"] is not None])) if any(
                    r["centerline_median_excess_adu"] is not None for r in usable) else None,
            "median_image_clustered_predicted_peak_minus_control_peak_adu":
                float(np.median(image_differences)) if image_differences else None,
            "image_cluster_bootstrap_95pct_interval_adu": ci,
            "image_clusters": len(image_differences),
            "bootstrap_seed": 20261010,
            "bootstrap_replicates": 20000,
        },
        "opportunity_results": rows,
        "interpretation_limit": (
            "Descriptive signal alignment against parallel lanes in 12 selected ZTF frames. "
            "Predicted catalog paths are not independent identity labels; image sample selection "
            "is conditioned on predicted opportunities; TLE errors and unrelated trails can create "
            "or hide alignment. This does not estimate satellite detection probability, planned "
            "attempt completion, or sensor dropout effectiveness."
        ),
    }


def main() -> None:
    sample = json.loads(SAMPLE.read_text())
    if sample.get("status") != "completed_profile_audit":
        raise ValueError("A completed ZTF real-image profile sample is required")
    result = audit(sample, sha256(SAMPLE))
    OUTPUT.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"output": str(OUTPUT), "summary": result["summary"],
                      "selection_and_measurement": result["selection_and_measurement"]}, indent=2))


if __name__ == "__main__":
    main()
