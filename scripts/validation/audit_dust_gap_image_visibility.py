"""Compare raw-image signal at DUST internal label gaps with labeled RSOs.

The score is a local image-contrast diagnostic around linearly interpolated
track positions. It can identify gaps whose imagery resembles labeled detections
or background, but cannot establish hardware failure or recover uncatalogued
target opportunities.
"""
from __future__ import annotations

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))


import argparse
import csv
import hashlib
import io
import json
import math
import pathlib
import zipfile

import numpy as np
from PIL import Image

try:
    from .analyze_dust_dropout import DEFAULT_ARCHIVE, MD5, read_sessions
except ImportError:
    from scripts.analysis.analyze_dust_dropout import DEFAULT_ARCHIVE, MD5, read_sessions


def box_center(row):
    x, y, width, height = map(float, row[2:6])
    return x + width / 2, y + height / 2


def local_contrast(image, x, y, search_radius=2, patch_radius=1, background_radius=8):
    """Return max searched patch contrast, normalized by annulus MAD."""
    height, width = image.shape
    cx, cy = int(round(x)), int(round(y))
    y0, y1 = max(0, cy - background_radius), min(height, cy + background_radius + 1)
    x0, x1 = max(0, cx - background_radius), min(width, cx + background_radius + 1)
    neighborhood = image[y0:y1, x0:x1].astype(float)
    yy, xx = np.ogrid[y0 - cy:y1 - cy, x0 - cx:x1 - cx]
    annulus_mask = (xx * xx + yy * yy >= (patch_radius + 2) ** 2)
    background = neighborhood[annulus_mask]
    if not len(background):
        return None
    median = float(np.median(background))
    mad = float(np.median(np.abs(background - median))) * 1.4826
    noise = max(mad, 1.0)
    best = -math.inf
    for dy in range(-search_radius, search_radius + 1):
        for dx in range(-search_radius, search_radius + 1):
            py, px = cy + dy, cx + dx
            if (py - patch_radius < 0 or px - patch_radius < 0
                    or py + patch_radius >= height or px + patch_radius >= width):
                continue
            patch = image[py - patch_radius:py + patch_radius + 1,
                          px - patch_radius:px + patch_radius + 1].astype(float)
            contrast = float(np.quantile(patch, .90)) - median
            best = max(best, contrast / noise)
    return best if math.isfinite(best) else None


def auc(positive, negative):
    """Mann-Whitney estimate of how often positive signal exceeds background."""
    if not positive or not negative:
        return None
    combined = [(value, 1) for value in positive] + [(value, 0) for value in negative]
    combined.sort(key=lambda item: item[0])
    rank_sum = 0.0
    index = 0
    while index < len(combined):
        finish = index + 1
        while finish < len(combined) and combined[finish][0] == combined[index][0]:
            finish += 1
        average_rank = ((index + 1) + finish) / 2
        rank_sum += average_rank * sum(label for _, label in combined[index:finish])
        index = finish
    n_pos, n_neg = len(positive), len(negative)
    return (rank_sum - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)


def benjamini_hochberg(pvalues):
    """Return monotone BH-adjusted q-values in the input order."""
    values = np.asarray(pvalues, dtype=float)
    if np.any(~np.isfinite(values)) or np.any((values < 0) | (values > 1)):
        raise ValueError("p-values must be finite and in [0, 1]")
    if not len(values):
        return np.asarray([], dtype=float)
    order = np.argsort(values, kind="stable")
    ranked = values[order] * len(values) / np.arange(1, len(values) + 1)
    adjusted = np.minimum.accumulate(ranked[::-1])[::-1]
    result = np.empty_like(adjusted)
    result[order] = np.clip(adjusted, 0, 1)
    return result


def distribution(values):
    values = np.asarray(values, dtype=float)
    if not len(values):
        return {"n": 0}
    return {"n": int(len(values)), "median": float(np.median(values)),
            "p10": float(np.quantile(values, .10)), "p90": float(np.quantile(values, .90)),
            "p95": float(np.quantile(values, .95)), "max": float(np.max(values))}


def session_bootstrap_mean_ci(values, seed=8218, replicates=10_000):
    """Percentile interval with whole observing sessions as the resampling unit."""
    values = np.asarray(values, dtype=float)
    if not len(values):
        return None
    rng = np.random.default_rng(seed)
    sampled = rng.integers(0, len(values), size=(replicates, len(values)))
    means = np.sort(values[sampled].mean(axis=1))
    return [float(means[int(.025 * (replicates - 1))]),
            float(means[int(.975 * (replicates - 1))])]


def audit(archive=DEFAULT_ARCHIVE, output=None):
    archive = pathlib.Path(archive)
    digest = hashlib.md5(archive.read_bytes()).hexdigest()
    if digest != MD5:
        raise ValueError(f"DUST archive MD5 mismatch: expected {MD5}, got {digest}")
    sessions, inventory, *_ = read_sessions(archive)
    frame_cache = {}
    positives, negatives, gaps = [], [], []
    positives_by_session = {}
    negatives_by_session = {}
    negatives_by_frame = {}
    annotations_by_frame = {}
    annotation_sets = {}
    with zipfile.ZipFile(archive) as bundle:
        for session_name, session in sessions.items():
            set_name = session_name.split("/")[1] if "/" in session_name else "unknown"
            set_summary = annotation_sets.setdefault(set_name, {
                "frames": 0, "labeled_rso_instances": 0, "annotated_transits": 0,
                "internal_transit_frame_opportunities": 0, "internal_unlabeled_frames": 0,
            })
            set_summary["frames"] += inventory[session_name]["image_frames"]
            labels = list(csv.reader(io.TextIOWrapper(bundle.open(session["mot_path"]), encoding="utf-8")))
            for row in labels:
                if len(row) != 9:
                    continue
                frame, track_id = int(row[0]), int(row[1])
                x, y = box_center(row)
                annotations_by_frame.setdefault((session_name, frame), []).append(
                    (track_id, x, y, float(row[4]), float(row[5])))
                set_summary["labeled_rso_instances"] += 1
                key = (session_name, frame)
                image_path = session["images"][frame - 1]
                if key not in frame_cache:
                    frame_cache[key] = np.asarray(
                        Image.open(io.BytesIO(bundle.read(image_path))).convert("L"))
                score = local_contrast(frame_cache[key], x, y)
                if score is not None:
                    positives.append(score)
                    positives_by_session.setdefault(session_name, []).append(score)

            by_track = {}
            for row in labels:
                if len(row) == 9:
                    by_track.setdefault(int(row[1]), {})[int(row[0])] = row
            for track_id, observations in by_track.items():
                ordered = sorted(observations)
                if ordered:
                    opportunities = ordered[-1] - ordered[0] + 1
                    set_summary["annotated_transits"] += 1
                    set_summary["internal_transit_frame_opportunities"] += opportunities
                    set_summary["internal_unlabeled_frames"] += opportunities - len(ordered)
                for before, after in zip(ordered, ordered[1:]):
                    missing = after - before - 1
                    if missing <= 0:
                        continue
                    start_x, start_y = box_center(observations[before])
                    end_x, end_y = box_center(observations[after])
                    for frame in range(before + 1, after):
                        fraction = (frame - before) / (after - before)
                        x = start_x + fraction * (end_x - start_x)
                        y = start_y + fraction * (end_y - start_y)
                        image_path = session["images"][frame - 1]
                        key = (session_name, frame)
                        if key not in frame_cache:
                            frame_cache[key] = np.asarray(
                                Image.open(io.BytesIO(bundle.read(image_path))).convert("L"))
                        score = local_contrast(frame_cache[key], x, y)
                        if score is not None:
                            gaps.append({"session": session_name, "track_id": track_id,
                                "frame": frame, "interpolated_x": x, "interpolated_y": y,
                                "score": score, "gap_length_frames": missing})

        # Background controls are taken from a regular spatial grid on frames
        # containing internal annotation gaps, excluding labeled RSO boxes.
        gap_frames = {(g["session"], g["frame"]) for g in gaps}
        for session_name, frame in gap_frames:
            image = frame_cache[(session_name, frame)]
            occupied = annotations_by_frame.get((session_name, frame), [])
            height, width = image.shape
            for cy in range(12, height - 12, 16):
                for cx in range(12, width - 12, 16):
                    if any(abs(cx - x) <= max(7, box_w) and abs(cy - y) <= max(7, box_h)
                           for _, x, y, box_w, box_h in occupied):
                        continue
                    score = local_contrast(image, cx, cy, search_radius=2)
                    if score is not None:
                        negatives.append(score)
                        negatives_by_session.setdefault(session_name, []).append(score)
                        negatives_by_frame.setdefault((session_name, frame), []).append(score)

    # Match each gap to background locations from the same image. The empirical
    # p-value is a local-brightness diagnostic; it cannot identify the source.
    for gap in gaps:
        controls = negatives_by_frame.get((gap["session"], gap["frame"]), [])
        if not controls:
            gap["same_frame_control_positions"] = 0
            gap["same_frame_empirical_pvalue"] = None
            continue
        gap["same_frame_control_positions"] = len(controls)
        gap["same_frame_empirical_pvalue"] = (
            1 + sum(value >= gap["score"] for value in controls)) / (1 + len(controls))
    tested_gaps = [gap for gap in gaps if gap["same_frame_empirical_pvalue"] is not None]
    qvalues = benjamini_hochberg([gap["same_frame_empirical_pvalue"] for gap in tested_gaps])
    for gap, qvalue in zip(tested_gaps, qvalues):
        gap["same_frame_bh_qvalue"] = float(qvalue)
    for gap in gaps:
        gap.setdefault("same_frame_bh_qvalue", None)

    # Leave one whole observation session out. The decision threshold is the
    # 95th percentile of background controls from all other sessions, so each
    # scored positive/control/gap is held out from threshold fitting.
    heldout = {}
    session_names = sorted(sessions)
    for session_name in session_names:
        training_controls = [value for other, values in negatives_by_session.items()
                             if other != session_name for value in values]
        if not training_controls:
            raise ValueError(f"No background controls outside held-out session {session_name}")
        threshold = float(np.quantile(training_controls, .95))
        positive_values = positives_by_session.get(session_name, [])
        negative_values = negatives_by_session.get(session_name, [])
        session_gaps = [gap for gap in gaps if gap["session"] == session_name]
        positive_detected = sum(value >= threshold for value in positive_values)
        false_alarms = sum(value >= threshold for value in negative_values)
        gap_signal_like = sum(gap["score"] >= threshold for gap in session_gaps)
        heldout[session_name] = {
            "threshold": threshold,
            "positive_detected": positive_detected,
            "positive_count": len(positive_values),
            "false_alarms": false_alarms,
            "background_control_count": len(negative_values),
            "gap_signal_like": gap_signal_like,
            "gap_count": len(session_gaps),
        }
        for gap in session_gaps:
            gap["leave_one_session_out_background_p95_threshold"] = threshold
            gap["leave_one_session_out_signal_like"] = bool(gap["score"] >= threshold)

    positive_session_recall = [row["positive_detected"] / row["positive_count"]
        for row in heldout.values() if row["positive_count"]]
    negative_session_fpr = [row["false_alarms"] / row["background_control_count"]
        for row in heldout.values() if row["background_control_count"]]
    gap_session_rate = [row["gap_signal_like"] / row["gap_count"]
        for row in heldout.values() if row["gap_count"]]
    positive_detected_total = sum(row["positive_detected"] for row in heldout.values())
    positive_total = sum(row["positive_count"] for row in heldout.values())
    false_alarms_total = sum(row["false_alarms"] for row in heldout.values())
    controls_total = sum(row["background_control_count"] for row in heldout.values())
    gap_signal_like_total = sum(row["gap_signal_like"] for row in heldout.values())
    gap_total = sum(row["gap_count"] for row in heldout.values())
    gap_cv_by_length = {}
    for length in sorted({int(gap["gap_length_frames"]) for gap in gaps}):
        selected = [gap for gap in gaps if int(gap["gap_length_frames"]) == length]
        gap_cv_by_length[str(length)] = {
            "signal_like": sum(gap["leave_one_session_out_signal_like"] for gap in selected),
            "total": len(selected),
            "fraction": (sum(gap["leave_one_session_out_signal_like"] for gap in selected) / len(selected)
                         if selected else None),
        }
    heldout_detection = {
        "status": "completed_leave_one_session_out_threshold_replay",
        "method": "For each held-out session, threshold at the 95th percentile of local-contrast background controls from all other sessions; score labeled positions, held-out background controls, and interpolated internal annotation gaps.",
        "session_folds": len(heldout),
        "target_signal_threshold_quantile": 0.95,
        "positive_labeled_positions": {
            "detected": positive_detected_total, "total": positive_total,
            "micro_recall": positive_detected_total / positive_total if positive_total else None,
            "equal_weight_session_mean_recall": float(np.mean(positive_session_recall)) if positive_session_recall else None,
            "equal_weight_session_bootstrap_ci95": session_bootstrap_mean_ci(positive_session_recall, 8218),
        },
        "background_controls": {
            "false_alarms": false_alarms_total, "total": controls_total,
            "micro_false_alarm_rate": false_alarms_total / controls_total if controls_total else None,
            "equal_weight_session_mean_rate": float(np.mean(negative_session_fpr)) if negative_session_fpr else None,
            "equal_weight_session_bootstrap_ci95": session_bootstrap_mean_ci(negative_session_fpr, 8219),
        },
        "interpolated_annotation_gaps": {
            "signal_like": gap_signal_like_total, "total": gap_total,
            "micro_fraction_signal_like": gap_signal_like_total / gap_total if gap_total else None,
            "equal_weight_session_mean_fraction": float(np.mean(gap_session_rate)) if gap_session_rate else None,
            "equal_weight_session_bootstrap_ci95": session_bootstrap_mean_ci(gap_session_rate, 8220),
            "by_gap_length_frames": gap_cv_by_length,
        },
        "interpretation_limit": "A gap score above threshold shows local image contrast similar to held-out positive detections, not confirmed identity or proof the published detector would have registered it. Interpolated positions, selected annotated transits, semi-automated labels, and background contamination limit causal interpretation.",
        "bootstrap_replicates": 10_000,
        "bootstrap_seeds": {"positive_recall": 8218, "background_false_alarm": 8219, "gap_signal_like": 8220},
    }

    output = pathlib.Path(output or archive.parent / "dropout_study")
    output.mkdir(parents=True, exist_ok=True)
    csv_path = output / "internal_gap_image_signal.csv"
    with csv_path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["session", "track_id", "frame",
            "interpolated_x", "interpolated_y", "score", "gap_length_frames",
            "same_frame_control_positions", "same_frame_empirical_pvalue",
            "same_frame_bh_qvalue", "leave_one_session_out_background_p95_threshold",
            "leave_one_session_out_signal_like"])
        writer.writeheader()
        writer.writerows(gaps)
    csv_hash = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    gap_counts_by_set = {}
    gap_scores_by_set = {}
    for row in gaps:
        set_name = row["session"].split("/")[1] if "/" in row["session"] else "unknown"
        gap_counts_by_set[set_name] = gap_counts_by_set.get(set_name, 0) + 1
        gap_scores_by_set.setdefault(set_name, []).append(row["score"])
    annotation_method = {"SET 1": "manual annotations",
                         "SET 2": "semi-automated annotations"}
    for set_name, values in annotation_sets.items():
        values["annotation_method"] = annotation_method.get(set_name, "not specified")
        values["gap_frames_scored"] = gap_counts_by_set.get(set_name, 0)
        values["gap_image_signal_distribution"] = distribution(gap_scores_by_set.get(set_name, []))
    report = {
        "status": "completed", "dataset_doi": "10.5281/zenodo.20255672",
        "archive_md5": digest, "image_frames": sum(v["image_frames"] for v in inventory.values()),
        "labeled_rso_instances_scored": len(positives),
        "internal_gap_frames_scored": len(gaps),
        "background_control_positions_scored": len(negatives),
        "annotation_set_summary": annotation_sets,
        "background_sampling": "16-pixel grid within frames containing internal gaps; grid positions within 7 pixels of labeled RSO box centers are excluded; same 5x5 position search as positive and gap scores",
        "local_contrast_score": "maximum searched 3x3-patch 90th-percentile excess over the local 8px annulus median, divided by robust annulus noise; gap locations interpolated between adjacent labels; neighborhoods clip at image edges",
        "positive_labeled_distribution": distribution(positives),
        "gap_interpolated_distribution": distribution([row["score"] for row in gaps]),
        "background_control_distribution": distribution(negatives),
        "positive_vs_background_auc": auc(positives, negatives),
        "gap_score_fraction_at_or_above_positive_p10": (
            sum(row["score"] >= float(np.quantile(positives, .10)) for row in gaps) / len(gaps)
            if positives and gaps else None),
        "gap_score_fraction_at_or_above_background_p95": (
            sum(row["score"] >= float(np.quantile(negatives, .95)) for row in gaps) / len(gaps)
            if negatives and gaps else None),
        "same_frame_background_test": {
            "tested_gaps": len(tested_gaps),
            "control_positions_per_gap": distribution([gap["same_frame_control_positions"] for gap in tested_gaps]),
            "median_empirical_pvalue": (float(np.median([gap["same_frame_empirical_pvalue"] for gap in tested_gaps]))
                                         if tested_gaps else None),
            "gaps_p_below_0_05": sum(gap["same_frame_empirical_pvalue"] < .05 for gap in tested_gaps),
            "gaps_bh_q_below_0_05": sum(gap["same_frame_bh_qvalue"] < .05 for gap in tested_gaps),
            "interpretation": "Within-frame image-brightness evidence at the interpolated track position; it does not establish object identity, detector opportunity, annotation correctness, or hardware dropout.",
        },
        "heldout_threshold_detection": heldout_detection,
        "csv": csv_path.name, "csv_sha256": csv_hash,
        "limitations": [
            "The local brightness score is an image diagnostic, not a validated RSO detector or visibility classifier.",
            "Track positions inside gaps are linearly interpolated, and non-linear image motion can misplace the search window.",
            "Unannotated sources may be stars, artifacts, or other RSOs; brightness cannot prove target identity.",
            "This cannot distinguish annotation omissions from actual optical non-detections or hardware dropout without independent target truth and acquisition logs.",
        ],
    }
    (output / "internal_gap_image_signal_audit.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", default=str(DEFAULT_ARCHIVE))
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    report = audit(args.archive, args.output)
    print(json.dumps({key: report[key] for key in (
        "status", "labeled_rso_instances_scored", "internal_gap_frames_scored",
        "background_control_positions_scored", "positive_labeled_distribution",
        "gap_interpolated_distribution", "background_control_distribution",
        "positive_vs_background_auc", "gap_score_fraction_at_or_above_positive_p10",
        "gap_score_fraction_at_or_above_background_p95", "same_frame_background_test")}, indent=2))


if __name__ == "__main__":
    main()
