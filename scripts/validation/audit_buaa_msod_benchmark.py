#!/usr/bin/env python3
"""Independently reconcile BUAA-MSOD checkpoint benchmark rows and scores."""
from __future__ import annotations

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))


import argparse
import json
import math
import zipfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
ARCHIVE = ROOT / "data/ground_sensor/buaa_msod/MSOD.zip"
SOURCE_AUDIT = ROOT / "data/ground_sensor/buaa_msod/audit.json"
MODEL_COMMIT = "73581be1a4f9a234ed1586a2c11552a6711ddb56"


def counts(pred, truth, radius):
    matched = set()
    tp = fp = 0
    for x, y in pred:
        distances = [math.hypot(x - gx, y - gy) for gx, gy in truth]
        if distances and min(distances) <= radius:
            index = distances.index(min(distances))
            if index not in matched:
                tp += 1
                matched.add(index)
            else:
                fp += 1
        else:
            fp += 1
    return tp, fp, len(truth) - len(matched)


def audit(path: Path) -> dict:
    data = json.loads(path.read_text())
    source = json.loads(SOURCE_AUDIT.read_text())
    if data.get("status") != "completed" or data.get("source_archive_md5") != source.get("archive_md5"):
        raise ValueError("Benchmark/source archive provenance mismatch")
    if data.get("upstream_model_commit") != MODEL_COMMIT:
        raise ValueError("Unexpected upstream model revision")
    if (data.get("false_positives_against_released_labels") is None
            or "released annotations only" not in data.get("interpretation_limit", "")):
        raise ValueError("Annotation-only interpretation boundary missing")

    with zipfile.ZipFile(ARCHIVE) as zf:
        expected = {line.strip() for line in zf.read("MSOD/test.txt").decode().splitlines() if line.strip()}
        source_boxes = {}
        for item in expected:
            text = zf.read(f"MSOD/test/labels/{item}.txt").decode().splitlines()
            source_boxes[item] = [[float(line.split()[1]) * 512,
                                   float(line.split()[2]) * 512]
                                  for line in text if line.strip()]

    rows = data.get("frames", [])
    keys = [row.get("frame") for row in rows]
    if len(rows) != len(expected) or len(set(keys)) != len(keys) or set(keys) != expected:
        raise ValueError("Benchmark frames do not exactly cover the publisher test split")
    tp = fp = fn = pred_count = gt_count = 0
    group_counts = {}
    for row in rows:
        key = row["frame"]
        truths = row.get("ground_truth_centers_px")
        preds = row.get("predicted_centroids_px")
        if truths != source_boxes[key]:
            raise ValueError(f"Ground-truth labels differ from source: {key}")
        if row.get("gt") != len(truths) or row.get("pred") != len(preds):
            raise ValueError(f"Per-frame counts disagree with coordinate records: {key}")
        a, b, c = counts(preds, truths, float(data["centroid_match_radius_px"]))
        if (a, b, c) != (row["tp"], row["fp_vs_labels"], row["fn_vs_labels"]):
            raise ValueError(f"Per-frame match counts do not reproduce: {key}")
        tp += a; fp += b; fn += c; pred_count += len(preds); gt_count += len(truths)
        group = key.split("/")[0]
        group_total = group_counts.setdefault(group, [0, 0, 0])
        group_total[0] += a; group_total[1] += b; group_total[2] += c
    p = tp / max(1, tp + fp)
    r = tp / max(1, tp + fn)
    f = 2 * p * r / max(1e-12, p + r)
    expected_metrics = {
        "frame_count": len(rows), "sequence_groups": len({k.split("/")[0] for k in keys}),
        "ground_truth_boxes": gt_count, "predicted_components": pred_count,
        "true_positives": tp, "false_positives_against_released_labels": fp,
        "false_negatives_against_released_labels": fn,
        "precision_against_released_labels": p, "recall_against_released_labels": r,
        "f1_against_released_labels": f,
    }
    for key, value in expected_metrics.items():
        saved = data.get(key)
        if isinstance(value, float):
            if not math.isclose(float(saved), value, rel_tol=0, abs_tol=1e-12):
                raise ValueError(f"Aggregate metric does not reproduce: {key}")
        elif saved != value:
            raise ValueError(f"Aggregate count does not reproduce: {key}")
    groups = sorted(group_counts)
    rng = np.random.default_rng(20261011)
    counts_by_group = np.asarray([group_counts[group] for group in groups], dtype=np.int64)
    draws = rng.integers(0, len(groups), size=(10000, len(groups)))
    samples = np.empty((len(draws), 3), dtype=np.float64)
    for index, draw in enumerate(draws):
        boot_tp, boot_fp, boot_fn = counts_by_group[draw].sum(axis=0)
        boot_p = boot_tp / max(1, boot_tp + boot_fp)
        boot_r = boot_tp / max(1, boot_tp + boot_fn)
        samples[index] = (boot_p, boot_r, 2 * boot_p * boot_r / max(1e-12, boot_p + boot_r))
    bootstrap = {
        "status": "completed_sequence_cluster_percentile_bootstrap",
        "cluster_unit": "64 publisher sequence groups sampled with replacement",
        "seed": 20261011,
        "replicates": len(samples),
        "interval": "percentile 95%",
        "metrics": {
            name: {"point_estimate": point,
                   "ci95": [float(v) for v in np.quantile(samples[:, i], [.025, .975])],
                   "interpretation": "label-referenced benchmark uncertainty, not deployment probability"}
            for i, (name, point) in enumerate((
                ("precision_against_released_labels", p),
                ("recall_against_released_labels", r),
                ("f1_against_released_labels", f),
            ))
        },
    }
    result = {
        "status": "passed_source_and_metric_reproduction",
        "frames_checked": len(rows), "sequence_groups_checked": expected_metrics["sequence_groups"],
        "ground_truth_centers_reconciled_to_archive": gt_count,
        "predicted_centers_recounted": pred_count,
        "matching_rows_recomputed": len(rows), "aggregate_metrics_recomputed": True,
        "sequence_cluster_bootstrap": bootstrap,
        "interpretation_limit": "Reproduces object-detector scores against released annotations only; does not establish false detections on unlabeled imagery or natural sensor dropout.",
    }
    out = path.with_name("independent_audit.json")
    out.write_text(json.dumps(result, indent=2) + "\n")
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--benchmark", type=Path,
                   default=ROOT / "outputs/buaa-msod-msamnet-test/benchmark.json")
    a = p.parse_args()
    print(json.dumps(audit(a.benchmark), indent=2))


if __name__ == "__main__":
    main()
