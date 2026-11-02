#!/usr/bin/env python3
"""Evaluate the public MSAMNet checkpoint on BUAA-MSOD's held-out frame labels.

This evaluates optical image detection against publisher boxes. It is not a
planned-attempt denominator, NORAD identity test, or sensor-hardware dropout
measurement. Upstream model source/checkpoint are supplied with --model-root
and --checkpoint because the upstream code repository declares no license.
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
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

import numpy as np
import sep
import torch
from PIL import Image
from scipy import ndimage

ROOT = Path(__file__).resolve().parents[2]
ARCHIVE = ROOT / "data/ground_sensor/buaa_msod/MSOD.zip"
DATA_AUDIT = ROOT / "data/ground_sensor/buaa_msod/audit.json"
MODEL_COMMIT = "73581be1a4f9a234ed1586a2c11552a6711ddb56"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_label(zf: zipfile.ZipFile, name: str) -> list[tuple[int, float, float]]:
    content = zf.read(name).decode("utf-8").splitlines()
    out = []
    for line in content:
        if not line.strip():
            continue
        cls, x, y, _w, _h = line.split()
        out.append((int(cls), float(x) * 512, float(y) * 512))
    return out


def preprocess(zf: zipfile.ZipFile, name: str) -> np.ndarray:
    raw = np.asarray(Image.open(io.BytesIO(zf.read(name))), dtype=np.float32)
    background = sep.Background(raw).back()
    image = raw - background
    image[image < 0] = 0
    std = float(image.std())
    if std <= 0 or not np.isfinite(std):
        raise ValueError(f"Invalid image standard deviation: {name}")
    image = (image - image.mean()) / std
    return image


def centroids(logit: np.ndarray, threshold: float) -> list[tuple[float, float]]:
    binary = np.asarray(logit > threshold, dtype=bool)
    labels, count = ndimage.label(binary, structure=np.ones((3, 3), dtype=np.uint8))
    if not count:
        return []
    centers = ndimage.center_of_mass(binary, labels, range(1, count + 1))
    return [(float(col) - 0.5, float(row) - 0.5) for row, col in centers]


def match_counts(pred: list[tuple[float, float]], truth: list[tuple[int, float, float]],
                 radius_px: float) -> tuple[int, int, int]:
    matched = set()
    tp = fp = 0
    for x, y in pred:
        choices = [(np.hypot(x - item[1], y - item[2]), i)
                   for i, item in enumerate(truth)]
        if choices:
            distance, index = min(choices)
            if distance <= radius_px:
                if index not in matched:
                    tp += 1
                    matched.add(index)
                else:
                    fp += 1
                continue
        fp += 1
    return tp, fp, len(truth) - len(matched)


def evaluate(model_root: Path, checkpoint: Path, output: Path, device: str,
             batch_size: int, threshold: float, match_radius: float,
             max_groups: int | None) -> dict:
    sys.path.insert(0, str(model_root))
    from model.MSAMNet import AAFE, MSAMNet

    dataset_audit = json.loads(DATA_AUDIT.read_text())
    if (ARCHIVE.stat().st_size != dataset_audit["archive_size_bytes"]
            or not dataset_audit.get("md5_matches_publisher")
            or dataset_audit.get("archive_summary", {}).get("crc_check") != "passed"):
        raise ValueError("BUAA-MSOD source archive does not match its verified publisher audit")
    model = MSAMNet(frame_length=3, fusionBlock=AAFE, input_channels=1)
    saved = torch.load(checkpoint, map_location="cpu", weights_only=False)
    model.load_state_dict(saved["state_dict"], strict=True)
    model = model.to(device).eval()

    frames: dict[str, list[str]] = defaultdict(list)
    with zipfile.ZipFile(ARCHIVE) as zf:
        ids = [line.strip() for line in zf.read("MSOD/test.txt").decode().splitlines() if line.strip()]
        for item in ids:
            group, frame = item.split("/")
            frames[group].append(frame)
        groups = sorted(frames)
        if max_groups is not None:
            groups = groups[:max_groups]

        per_frame = []
        for group_index, group in enumerate(groups, start=1):
            names = sorted(frames[group], key=lambda n: int(n))
            cache: dict[int, np.ndarray] = {}
            pending_x: list[np.ndarray] = []
            pending_truth: list[list[tuple[int, float, float]]] = []
            pending_names: list[str] = []
            for item in names:
                frame_n = int(item)
                # Match the published MSOD loader: use current and two prior
                # frames, repeating frame 1 at the beginning of a sequence.
                cur_name = f"MSOD/test/images/{group}/{frame_n:05d}.tif"
                current = preprocess(zf, cur_name)
                cache[frame_n] = current
                seq = [cache[max(1, frame_n - 2)].copy(),
                       cache[max(1, frame_n - 1)].copy(), current.copy()]
                # The upstream loader divides only the current channel by 255
                # after SEP background subtraction and per-frame standardization.
                seq[2] = seq[2] / 255.0
                pending_x.append(np.stack(seq).astype(np.float32, copy=False))
                label_name = f"MSOD/test/labels/{group}/{item}.txt"
                pending_truth.append(read_label(zf, label_name))
                pending_names.append(f"{group}/{item}")
                # Keep only the two prior frames needed by the next input.
                for old in list(cache):
                    if old < frame_n - 1:
                        del cache[old]
                if len(pending_x) == batch_size or item == names[-1]:
                    x = torch.from_numpy(np.stack(pending_x)).to(device)
                    with torch.inference_mode():
                        logits = model(x)[:, 0].detach().cpu().numpy()
                    for name, logit, truth in zip(pending_names, logits, pending_truth):
                        pred = centroids(logit, threshold)
                        tp, fp, fn = match_counts(pred, truth, match_radius)
                        per_frame.append({"frame": name, "gt": len(truth),
                                          "pred": len(pred), "tp": tp, "fp_vs_labels": fp,
                                          "fn_vs_labels": fn,
                                          "ground_truth_centers_px": [[v[1], v[2]] for v in truth],
                                          "predicted_centroids_px": [[v[0], v[1]] for v in pred]})
                    pending_x.clear(); pending_truth.clear(); pending_names.clear()
            print(f"completed sequence {group_index}/{len(groups)}: {group} ({len(names)} frames)",
                  flush=True)

    tp = sum(r["tp"] for r in per_frame)
    fp = sum(r["fp_vs_labels"] for r in per_frame)
    fn = sum(r["fn_vs_labels"] for r in per_frame)
    precision = tp / max(1, tp + fp)
    recall = tp / max(1, tp + fn)
    f1 = 2 * precision * recall / max(1e-12, precision + recall)
    result = {
        "status": "completed",
        "dataset": "BUAA-MSOD",
        "split": "publisher test split, sequence-grouped, no train/test group overlap",
        "frame_count": len(per_frame),
        "sequence_groups": len(groups),
        "ground_truth_boxes": sum(r["gt"] for r in per_frame),
        "predicted_components": sum(r["pred"] for r in per_frame),
        "true_positives": tp,
        "false_positives_against_released_labels": fp,
        "false_negatives_against_released_labels": fn,
        "precision_against_released_labels": precision,
        "recall_against_released_labels": recall,
        "f1_against_released_labels": f1,
        "device": device,
        "threshold_on_foreground_logit": threshold,
        "centroid_match_radius_px": match_radius,
        "checkpoint_epoch": saved.get("epoch"),
        "checkpoint_recorded_f1": saved.get("f1"),
        "checkpoint_sha256": sha256(checkpoint),
        "upstream_model_repository": "https://github.com/yx-gg/MSAMNet",
        "upstream_model_commit": MODEL_COMMIT,
        "upstream_checkpoint_path": "result/MSOD_MSAMNet_17_12_2024_22_54_47_wDS/f1_best_MSAMNet_MSOD_epoch.pth.tar",
        "upstream_software_license": "not declared in repository metadata; model source/checkpoint retained only in temporary storage",
        "source_archive_md5": dataset_audit["archive_md5"],
        "preprocessing": "SEP background subtraction; per-frame standardization; three-frame input matching published MSOD loader, including its current-frame /255 scaling",
        "method": "Foreground output channel thresholded at logit > threshold; 8-connected components reduced to centroids; one-to-one greedy match to publisher box centers within radius",
        "interpretation_limit": "Benchmark metrics against released annotations only. They do not estimate planned-observation success, catalog-wide detectability, NORAD identity accuracy, hardware outages, or real dropout effectiveness. Empty/unmatched annotation frames are not verified negatives.",
        "frames": per_frame,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--model-root", type=Path, required=True)
    p.add_argument("--checkpoint", type=Path, required=True)
    p.add_argument("--output", type=Path, default=ROOT / "outputs/buaa-msod-msamnet-test/benchmark.json")
    p.add_argument("--device", choices=("mps", "cpu"), default="mps")
    p.add_argument("--batch-size", type=int, default=2)
    p.add_argument("--threshold", type=float, default=0.0)
    p.add_argument("--match-radius", type=float, default=3.0)
    p.add_argument("--max-groups", type=int)
    a = p.parse_args()
    result = evaluate(a.model_root, a.checkpoint, a.output, a.device,
                      a.batch_size, a.threshold, a.match_radius, a.max_groups)
    print(json.dumps({k: v for k, v in result.items() if k != "frames"}, indent=2))


if __name__ == "__main__":
    main()
