#!/usr/bin/env python3
"""Independently reconcile the all-track DUST/TLE replay outputs."""
import argparse
import csv
import datetime as dt
import hashlib
import io
import json
import pathlib
import re
import zipfile
from collections import defaultdict

import h5py
import numpy as np

from validate_dust_tle_track import DUST_ZIP, ROOT


def hash_file(path):
    digest = hashlib.md5()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def percentile(values, q):
    return float(np.percentile(np.asarray(values, dtype=float), q)) if values else None


def median(values):
    return float(np.median(np.asarray(values, dtype=float))) if values else None


def expected_tracks():
    inventory = {}
    with zipfile.ZipFile(DUST_ZIP) as archive:
        names = set(archive.namelist())
        annotations = sorted(
            name for name in names
            if "/RSO_Annotations/" in name and name.endswith("_MOT_gt.txt")
        )
        for path in annotations:
            parts = pathlib.PurePosixPath(path).parts
            set_name, session = parts[1], parts[2]
            rows = [
                line for line in archive.read(path).decode("utf-8-sig").splitlines()
                if line.strip() and len(line.split(",")) >= 6
            ]
            for track_id in sorted({int(float(row.split(",")[1])) for row in rows}):
                inventory[(set_name, session, track_id)] = sum(
                    int(float(row.split(",")[1])) == track_id for row in rows
                )
    return inventory


def audit_frame_mapping():
    sessions = defaultdict(lambda: {"images": [], "h5": [], "wcs": set(), "mot": None})
    timestamp_offsets = []
    annotated_rows = 0
    annotated_rows_with_wcs = 0
    per_session = []
    with zipfile.ZipFile(DUST_ZIP) as archive:
        for name in archive.namelist():
            path = pathlib.PurePosixPath(name)
            if "/Images/" in name and path.suffix.lower() == ".png":
                sessions[name.split("/Images/", 1)[0]]["images"].append(name)
            elif "/H5/" in name and path.suffix.lower() == ".h5":
                sessions[name.split("/H5/", 1)[0]]["h5"].append(name)
            elif "/WCS/" in name and path.suffix.lower() == ".fits":
                sessions[name.split("/WCS/", 1)[0]]["wcs"].add(path.stem)
            elif name.endswith("_MOT_gt.txt"):
                sessions[name.rsplit("/RSO_Annotations/", 1)[0]]["mot"] = name

        for key, content in sorted(sessions.items()):
            images = sorted(content["images"])
            h5_names = sorted(content["h5"])
            image_stems = [pathlib.PurePosixPath(name).stem for name in images]
            h5_stems = [pathlib.PurePosixPath(name).stem for name in h5_names]
            if image_stems != h5_stems:
                raise AssertionError(f"DUST image/H5 frame order differs in {key}")
            frame_rows = []
            if content["mot"]:
                for line in archive.read(content["mot"]).decode("utf-8-sig").splitlines():
                    if line.strip():
                        fields = line.split(",")
                        if len(fields) != 9:
                            raise AssertionError(f"unexpected MOT schema in {content['mot']}")
                        frame_rows.append((int(fields[0]), int(fields[1])))
            if any(frame < 1 or frame > len(images) for frame, _ in frame_rows):
                raise AssertionError(f"MOT frame index is outside image sequence in {key}")
            usable = sum(image_stems[frame - 1] in content["wcs"] for frame, _ in frame_rows)
            annotated_rows += len(frame_rows)
            annotated_rows_with_wcs += usable
            per_session.append({
                "session_path": key,
                "image_frames": len(images),
                "h5_frames": len(h5_names),
                "wcs_frames": len(content["wcs"]),
                "image_h5_stem_order_matches": True,
                "mot_rows": len(frame_rows),
                "mot_rows_with_wcs": usable,
            })

        for session in sessions.values():
            for name in session["h5"]:
                match = re.search(r"(\d{8})_(\d{6})_", pathlib.PurePosixPath(name).stem)
                if not match:
                    raise AssertionError(f"frame timestamp is absent from {name}")
                with h5py.File(io.BytesIO(archive.read(name)), "r") as h5:
                    actual = dt.datetime.fromisoformat(str(h5.attrs["UTC"])).replace(tzinfo=dt.timezone.utc)
                expected = dt.datetime.strptime("".join(match.groups()), "%Y%m%d%H%M%S").replace(tzinfo=dt.timezone.utc)
                offset = (actual - expected).total_seconds()
                if not 0 <= offset < 1:
                    raise AssertionError(f"H5 UTC does not match frame filename second for {name}: {offset}")
                timestamp_offsets.append(offset)
    return {
        "session_count": len(sessions),
        "image_frame_count": sum(len(s["images"]) for s in sessions.values()),
        "h5_frame_count": sum(len(s["h5"]) for s in sessions.values()),
        "wcs_frame_count": sum(len(s["wcs"]) for s in sessions.values()),
        "mot_annotated_rows": annotated_rows,
        "mot_rows_with_wcs": annotated_rows_with_wcs,
        "h5_filename_utc_offsets_seconds": {
            "frames_checked": len(timestamp_offsets),
            "min": min(timestamp_offsets),
            "median": float(np.median(timestamp_offsets)),
            "max": max(timestamp_offsets),
            "all_within_filename_second": True,
        },
        "sessions": per_session,
    }


def audit_set2_mot_yolo_coordinates():
    total_rows = 0
    exact_box_matches = 0
    with zipfile.ZipFile(DUST_ZIP) as archive:
        names = set(archive.namelist())
        mot_paths = sorted(
            name for name in names
            if "/SET 2/" in name and name.endswith("_MOT_gt.txt")
        )
        for mot_path in mot_paths:
            base = mot_path.rsplit("/RSO_Annotations/", 1)[0]
            images = sorted(
                name for name in names
                if name.startswith(f"{base}/Images/") and name.lower().endswith(".png")
            )
            annotations = [
                [float(value) for value in row]
                for row in csv.reader(io.StringIO(archive.read(mot_path).decode("utf-8-sig")))
                if row
            ]
            by_frame = defaultdict(list)
            for row in annotations:
                by_frame[int(row[0])].append(row)
            yolo_by_frame = {}
            for frame in by_frame:
                if not 1 <= frame <= len(images):
                    raise AssertionError(f"Set 2 MOT frame is outside image range: {mot_path} frame {frame}")
                stem = pathlib.PurePosixPath(images[frame - 1]).stem
                yolo_path = f"{base}/RSO_Annotations/YOLO/{stem}.txt"
                if yolo_path not in names:
                    raise AssertionError(f"Set 2 MOT frame has no YOLO file: {yolo_path}")
                objects = []
                for line in archive.read(yolo_path).decode("utf-8-sig").splitlines():
                    fields = [float(value) for value in line.split()]
                    if len(fields) >= 5 and int(fields[0]) == 1:
                        objects.append(np.asarray(fields[1:5]) * 256)
                yolo_by_frame[frame] = objects
            for frame, rows in by_frame.items():
                for row in rows:
                    total_rows += 1
                    box = np.asarray([row[2] + row[4] / 2, row[3] + row[5] / 2, row[4], row[5]])
                    errors = [float(np.max(np.abs(box - yolo))) for yolo in yolo_by_frame[frame]]
                    if errors and min(errors) < 0.001:
                        exact_box_matches += 1
        if exact_box_matches != total_rows:
            raise AssertionError(f"Set 2 MOT/YOLO box mismatch: {exact_box_matches}/{total_rows}")
    return {
        "mot_rows": total_rows,
        "exact_rso_yolo_box_matches": exact_box_matches,
        "coordinate_tolerance_pixels": 0.001,
        "interpretation": "MOT bounding boxes reproduce the normalized YOLO centers/sizes after conversion to 256-pixel coordinates; the camera pixels should use the annotation coordinate convention.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=pathlib.Path, required=True)
    parser.add_argument("--output", type=pathlib.Path)
    args = parser.parse_args()
    source_inventory = expected_tracks()
    frame_mapping = audit_frame_mapping()
    set2_boxes = audit_set2_mot_yolo_coordinates()
    archive_md5 = hash_file(DUST_ZIP)
    sidecar_md5 = (ROOT / "data/onboard_sensor/dust_star_tracker/DUST.zip.md5").read_text().strip()
    summary_path = args.output_dir / "all_tracks_summary.json"
    saved_summary = json.loads(summary_path.read_text())
    completed = []
    output_hashes = {}
    failures = saved_summary["failures"]
    file_tracks = set()
    for path in sorted(args.output_dir.glob("SET[12]_*_track_*.json")):
        result = json.loads(path.read_text())
        key = (result["dataset_set"], result["session"], int(result["track_id"]))
        if key in file_tracks:
            raise AssertionError(f"duplicate saved result for {key}")
        file_tracks.add(key)
        if key not in source_inventory:
            raise AssertionError(f"saved result is absent from source annotation inventory: {key}")
        if result["frames_total"] != source_inventory[key]:
            raise AssertionError(f"annotation row count mismatch for {key}")
        if result["dust_archive_md5"] != archive_md5:
            raise AssertionError(f"track provenance MD5 mismatch for {key}")
        if not result["track_candidate_ranking"] or result["track_candidate_ranking"][0]["norad_id"] != result["selected_norad_id"]:
            raise AssertionError(f"selected object does not match the recorded trajectory ranking for {key}")
        rows = result["frame_results"]
        if len(rows) != result["frames_with_wcs_and_ephemeris"]:
            raise AssertionError(f"saved frame count mismatch for {key}")
        training = [row for row in rows if row["role"] == "training"]
        held_out = [row for row in rows if row["role"] == "held_out"]
        if len(training) != result["training_frame_count"]:
            raise AssertionError(f"training frame count mismatch for {key}")
        residuals = [row["separation_deg"] for row in held_out if row["separation_deg"] is not None]
        if any(not np.isfinite(value) or value < 0 for value in residuals):
            raise AssertionError(f"invalid held-out residual for {key}")
        expected = {
            "evaluated_frames": len(residuals),
            "median_separation_deg": float(np.median(residuals)) if residuals else None,
            "p95_separation_deg": float(np.percentile(residuals, 95)) if residuals else None,
            "max_separation_deg": max(residuals) if residuals else None,
            "under_0_15_deg_fraction": float(np.mean(np.asarray(residuals) < 0.15)) if residuals else None,
        }
        actual = result["track_temporal_validation"]
        for field, value in expected.items():
            if actual[field] != value:
                raise AssertionError(f"saved track statistic does not reproduce for {key}: {field}")
        completed.append(result)
        output_hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()

    failed_keys = {
        (item["dataset_set"], item["session"], int(item["track_id"]))
        for item in failures
    }
    if file_tracks & failed_keys:
        raise AssertionError("a track is both marked completed and failed")
    if file_tracks | failed_keys != set(source_inventory):
        raise AssertionError("completed plus failed tracks do not cover the source inventory")
    if len(failures) != len(failed_keys):
        raise AssertionError("duplicate failure entries")
    failed_availability = []
    with zipfile.ZipFile(DUST_ZIP) as archive:
        names = set(archive.namelist())
        for item in failures:
            base = f"DUST/{item['dataset_set']}/{item['session']}"
            annotation_path = f"{base}/RSO_Annotations/{item['session']}_MOT_gt.txt"
            annotations = [
                line.split(",") for line in archive.read(annotation_path).decode("utf-8-sig").splitlines()
                if line.strip()
            ]
            frame_ids = [
                int(float(fields[0])) for fields in annotations
                if len(fields) >= 6 and int(float(fields[1])) == int(item["track_id"])
            ]
            h5_names = sorted(
                name for name in names
                if name.startswith(f"{base}/H5/") and name.endswith(".h5")
            )
            usable = 0
            for frame in frame_ids:
                if 1 <= frame <= len(h5_names):
                    stem = pathlib.PurePosixPath(h5_names[frame - 1]).stem
                    usable += f"{base}/WCS/{stem}.fits" in names
            if usable:
                raise AssertionError(f"failed track has {usable} WCS frames available: {item}")
            failed_availability.append({
                "dataset_set": item["dataset_set"],
                "session": item["session"],
                "track_id": item["track_id"],
                "annotated_frames": len(frame_ids),
                "frames_with_wcs_and_ephemeris": usable,
            })
    if archive_md5 != sidecar_md5:
        raise AssertionError("DUST archive bytes do not match checked-in MD5 sidecar")

    heldout_values = []
    first_residuals = []
    training_fits = []
    selected_counts = {}
    pointing_modes = {result.get("pointing_correction", "raw DUST WCS") for result in completed}
    if len(pointing_modes) > 1:
        raise AssertionError("mixed pointing-correction modes in one batch")
    pointing_mode = next(iter(pointing_modes), "unknown")
    pointing_offsets = []
    pointing_corrected_frames = 0
    reconstructed_tracks = []
    for result in completed:
        rows = result["frame_results"]
        for row in rows:
            if "star_correction_applied" in row:
                if row["star_correction_applied"]:
                    pointing_corrected_frames += 1
                    pointing_offsets.append((
                        row["star_correction_east_arcsec"],
                        row["star_correction_north_arcsec"],
                    ))
        heldout = [
            row["separation_deg"] for row in rows
            if row["role"] == "held_out" and row["separation_deg"] is not None
        ]
        heldout_values.extend(heldout)
        candidates = result["first_frame_candidates"]
        ranking = result["track_candidate_ranking"]
        first_residuals.append(candidates[0]["separation_deg"])
        training_fits.append(ranking[0]["training_median_separation_deg"])
        norad = str(result["selected_norad_id"])
        selected_counts[norad] = selected_counts.get(norad, 0) + 1
        reconstructed_tracks.append({
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
            "annotated_frames": len(rows),
            "held_out_frames": len(heldout),
            "held_out_median_residual_deg": median(heldout),
            "held_out_p95_residual_deg": percentile(heldout, 95),
            "held_out_max_residual_deg": max(heldout) if heldout else None,
            "held_out_fraction_under_0_15_deg": float(np.mean(np.asarray(heldout) < 0.15)) if heldout else None,
        })
    reconstructed_tracks.sort(key=lambda t: (t["dataset_set"], t["session"], t["track_id"]))
    selected_counts = dict(sorted(selected_counts.items(), key=lambda item: (-item[1], int(item[0]))))
    reproduced = {
        "pointing_correction": pointing_mode,
        "track_count": len(completed),
        "held_out_frame_count": len(heldout_values),
        "held_out_residual_summary_deg": {
            "median": median(heldout_values),
            "p95": percentile(heldout_values, 95),
            "max": max(heldout_values) if heldout_values else None,
            "fraction_under_0_15_deg": float(np.mean(np.asarray(heldout_values) < 0.15)) if heldout_values else None,
        },
        "candidate_selection_residual_summary_deg": {
            "median": median(first_residuals),
            "p95": percentile(first_residuals, 95),
            "fraction_under_0_15_deg": float(np.mean(np.asarray(first_residuals) < 0.15)) if first_residuals else None,
        },
        "track_training_fit_summary_deg": {
            "median": median(training_fits),
            "p95": percentile(training_fits, 95),
            "fraction_under_0_15_deg": float(np.mean(np.asarray(training_fits) < 0.15)) if training_fits else None,
        },
        "selected_norad_track_counts": selected_counts,
        "tracks": reconstructed_tracks,
    }
    for field in (
        "pointing_correction", "track_count", "held_out_frame_count", "held_out_residual_summary_deg",
        "candidate_selection_residual_summary_deg", "track_training_fit_summary_deg",
        "selected_norad_track_counts", "tracks",
    ):
        if field == "tracks":
            saved_tracks = sorted(saved_summary[field], key=lambda t: (t["dataset_set"], t["session"], t["track_id"]))
            if reproduced[field] == saved_tracks:
                continue
        if reproduced[field] != saved_summary[field]:
            raise AssertionError(f"batch summary fails independent reconstruction: {field}")
    tracks_with_holdout = [t for t in reproduced["tracks"] if t["held_out_frames"] >= 3]
    track_fit_and_holdout_under_0_15 = [
        t for t in tracks_with_holdout
        if t["training_selection_residual_deg"] < 0.15
        and t["held_out_median_residual_deg"] is not None
        and t["held_out_median_residual_deg"] < 0.15
    ]
    result = {
        "status": "passed",
        "archive_md5": archive_md5,
        "source_track_inventory": len(source_inventory),
        "source_frame_mapping": frame_mapping,
        "set2_mot_yolo_coordinate_audit": set2_boxes,
        "completed_track_outputs": len(completed),
        "pointing_correction": pointing_mode,
        "star_corrected_frame_count": pointing_corrected_frames,
        "median_star_pointing_offset_arcsec": {
            "east": float(np.median([p[0] for p in pointing_offsets])) if pointing_offsets else None,
            "north": float(np.median([p[1] for p in pointing_offsets])) if pointing_offsets else None,
        },
        "failed_track_count": len(failures),
        "failed_track_source_availability": failed_availability,
        "held_out_frame_count": reproduced["held_out_frame_count"],
        "held_out_residual_summary_deg": reproduced["held_out_residual_summary_deg"],
        "candidate_selection_residual_summary_deg": reproduced["candidate_selection_residual_summary_deg"],
        "track_training_fit_summary_deg": reproduced["track_training_fit_summary_deg"],
        "tracks_with_at_least_3_holdout_frames": len(tracks_with_holdout),
        "tracks_with_training_and_holdout_median_under_0_15_deg": len(track_fit_and_holdout_under_0_15),
        "track_fit_and_holdout_under_threshold_ids": [
            {"dataset_set": t["dataset_set"], "session": t["session"], "track_id": t["track_id"], "norad_id": t["selected_norad_id"]}
            for t in track_fit_and_holdout_under_0_15
        ],
        "failures": failures,
        "track_json_sha256": output_hashes,
        "limitations": [
            "The audit verifies annotation inventory, archive checksum, saved-object provenance, residual arithmetic, and aggregate reconciliation.",
            "It does not supply NORAD ground-truth IDs or establish true association accuracy.",
            "The 0.15-degree summary threshold is descriptive and is not a calibrated pass criterion.",
        ],
    }
    destination = args.output or args.output_dir / "independent_audit.json"
    destination.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key not in {"track_fit_and_holdout_under_threshold_ids", "track_json_sha256", "failures"}}, indent=2))


if __name__ == "__main__":
    main()
