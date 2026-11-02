#!/usr/bin/env python3
"""Independently compare compact CASSIOPE dropout masks with audited Parquet days."""
from __future__ import annotations

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))


import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data/attitude/cassiope_epop"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def audit(data: Path = DATA, masks_path: Path | None = None) -> dict:
    data = Path(data)
    audit_doc = json.loads((data / "independent_audit.json").read_text())
    profile_path = data / "dropout_profile_1minute.json"
    profile = json.loads(profile_path.read_text())
    sidecar_path = masks_path.with_suffix(".json") if masks_path else data / "dropout_masks_1minute.json"
    sidecar = json.loads(sidecar_path.read_text())
    if masks_path is None:
        masks_path = Path(sidecar["mask_archive_path"])
        if not masks_path.is_absolute():
            masks_path = ROOT / masks_path
    if audit_doc.get("status") != "passed_structural_and_statistical":
        raise ValueError("CASSIOPE source audit has not passed")
    if sidecar.get("status") != "completed":
        raise ValueError("Mask export has not completed")
    if sidecar.get("source_profile_sha256") != sha256(profile_path):
        raise ValueError("Mask export profile checksum differs from the current profile")
    if sidecar.get("mask_archive_sha256") != sha256(masks_path):
        raise ValueError("Mask archive checksum differs from its export manifest")
    with np.load(masks_path, allow_pickle=False) as archive:
        dates = archive["dates"].astype(str).tolist()
        masks = archive["dropout"]
    expected_dates = audit_doc.get("validated_dates", [])
    if dates != expected_dates or dates != [row["date"] for row in profile.get("per_day", [])]:
        raise ValueError("Mask dates differ from audited and profiled published dates")
    cadence = int(sidecar["cadence_seconds"])
    samples_per_day = 86_400 // cadence
    if (masks.shape != (len(expected_dates), samples_per_day)
            or sidecar.get("sample_count") != masks.size
            or sidecar.get("validated_days") != len(expected_dates)):
        raise ValueError("Mask archive dimensions or coverage metadata are inconsistent")
    mismatch_count = 0
    source_dropout_count = 0
    for index, day in enumerate(expected_dates):
        path = data / "processed" / day[:4] / f"{day}.parquet"
        table = pq.read_table(path, columns=["q1", "q2", "q3", "q4"])
        if table.num_rows != 86_400:
            raise ValueError(f"{day} source Parquet day has an incomplete time grid")
        q = np.column_stack([table[f"q{i}"].to_numpy(zero_copy_only=False)
                             for i in range(1, 5)])
        expected_mask = ~np.isfinite(q).all(axis=1)[::cadence]
        mismatch_count += int(np.count_nonzero(expected_mask != masks[index]))
        source_dropout_count += int(expected_mask.sum())
        if int(masks[index].sum()) != int(profile["per_day"][index]["dropout_minutes"]):
            raise ValueError(f"{day} mask disagrees with the profile's daily dropout count")
    if mismatch_count:
        raise ValueError(f"Mask differs from source Parquet at {mismatch_count} sampled minutes")
    if source_dropout_count != sidecar.get("dropout_count"):
        raise ValueError("Mask dropout total differs from source reaggregation")
    if not np.isclose(float(masks.mean()), profile["one_minute_attitude_solution_dropout_rate"], atol=0, rtol=0):
        raise ValueError("Mask stationary rate differs from measured profile")
    profile_statistics_verified = False
    if "date_cluster_bootstrap" in profile:
        transitions = np.zeros(4, dtype=np.int64)
        for row in masks:
            transitions += np.bincount(row[:-1].astype(np.int8)*2 + row[1:].astype(np.int8), minlength=4)
        if transitions.tolist() != profile.get("transition_counts_00_01_10_11"):
            raise ValueError("Profile transition counts differ from the source masks")
        n0, n1 = int(transitions[:2].sum()), int(transitions[2:].sum())
        entry = float(transitions[1]/n0) if n0 else 0.0
        persistence = float(transitions[3]/n1) if n1 else 0.0
        implied_entry = float(masks.mean()) * (1-persistence) / max(1-float(masks.mean()), 1e-12)
        for name, expected in (("empirical_dropout_entry_probability_per_minute", entry),
                               ("empirical_dropout_persistence_probability_per_minute", persistence),
                               ("simulator_markov_persistence_parameter", persistence),
                               ("simulator_entry_probability_implied_by_stationary_rate_and_persistence", implied_entry)):
            if not np.isclose(profile.get(name, np.nan), expected, atol=1e-14, rtol=0):
                raise ValueError(f"Profile parameter does not reproduce from masks: {name}")
        bootstrap = profile["date_cluster_bootstrap"]
        replicates = int(bootstrap["replicates"])
        if replicates < 1 or bootstrap.get("sampling_unit") != "published UTC day":
            raise ValueError("Invalid profile bootstrap design")
        rates = masks.mean(axis=1)
        draws = np.random.default_rng(int(bootstrap["seed"])).integers(0, len(rates), size=(replicates, len(rates)))
        interval = np.quantile(rates[draws].mean(axis=1), bootstrap["interval_quantiles"])
        if not np.allclose(interval, profile["one_minute_dropout_rate_date_cluster_bootstrap_ci95"], atol=1e-14, rtol=0):
            raise ValueError("Profile day-cluster bootstrap interval does not reproduce")
        profile_statistics_verified = True
    result = {
        "status": "passed_independent_source_replay",
        "source_audit_status": audit_doc["status"],
        "dates_checked": len(expected_dates),
        "dates": expected_dates,
        "sample_count_checked": int(masks.size),
        "dropout_count_recomputed": source_dropout_count,
        "mismatched_samples": mismatch_count,
        "cadence_seconds": cadence,
        "mask_archive_path": str(masks_path.relative_to(ROOT)) if masks_path.is_relative_to(ROOT) else str(masks_path),
        "source_profile_sha256": sidecar["source_profile_sha256"],
        "mask_archive_sha256": sha256(masks_path),
        "profile_transition_and_bootstrap_statistics_verified": profile_statistics_verified,
        "checks": {
            "date_grid_matches_both_audits": True,
            "every_sample_matches_source_quaternion_validity": True,
            "daily_counts_match_profile": True,
            "aggregate_rate_matches_profile": True,
            "archive_and_profile_hashes_match": True,
        },
    }
    output = sidecar_path.with_name("dropout_masks_independent_audit.json")
    output.write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DATA)
    parser.add_argument("--masks", type=Path, default=None)
    args = parser.parse_args()
    data = args.data if args.data.is_absolute() else ROOT / args.data
    masks = args.masks
    if masks is not None and not masks.is_absolute():
        masks = ROOT / masks
    result = audit(data, masks)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
