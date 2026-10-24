#!/usr/bin/env python3
"""Export compact, task-cadence CASSIOPE outage masks from audited daily products."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/attitude/cassiope_epop"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def export(data: Path = DATA, cadence_seconds: int = 60,
           output: Path | None = None) -> dict:
    data = Path(data)
    if cadence_seconds <= 0 or 86_400 % cadence_seconds:
        raise ValueError("cadence_seconds must be a positive divisor of one day")
    audit = json.loads((data / "independent_audit.json").read_text())
    profile_path = data / "dropout_profile_1minute.json"
    profile = json.loads(profile_path.read_text())
    if audit.get("status") != "passed_structural_and_statistical" or profile.get("status") != "completed":
        raise ValueError("An independently audited attitude archive and profile are required")
    dates = audit.get("validated_dates", [])
    if dates != [row.get("date") for row in profile.get("per_day", [])]:
        raise ValueError("Attitude dropout profile dates differ from validated source dates")
    masks = np.empty((len(dates), 86_400 // cadence_seconds), dtype=np.bool_)
    for index, day in enumerate(dates):
        path = data / "processed" / day[:4] / f"{day}.parquet"
        table = pq.read_table(path, columns=["q1", "q2", "q3", "q4"])
        if table.num_rows != 86_400:
            raise ValueError(f"{day} has {table.num_rows} rows, expected 86400")
        q = np.column_stack([table[f"q{i}"].to_numpy(zero_copy_only=False)
                             for i in range(1, 5)])
        masks[index] = ~np.isfinite(q).all(axis=1)[::cadence_seconds]
        if int(masks[index].sum()) != int(profile["per_day"][index]["dropout_minutes"]):
            raise ValueError(f"{day} mask count differs from analyzed dropout profile")
    if len(dates) != len(profile.get("per_day", [])):
        raise ValueError("Attitude profile dates differ from validated products")
    if int(masks.sum()) != int(profile["one_minute_attitude_solution_dropout_rate"] * masks.size + 0.5):
        raise ValueError("Exported mask rate differs from the measured profile")
    output = Path(output) if output else data / "dropout_masks_1minute.npz"
    if not output.is_absolute():
        output = ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(output, dates=np.asarray(dates), dropout=masks)
    result = {
        "status": "completed",
        "source_audit_status": audit["status"],
        "source_profile_path": str(profile_path.relative_to(ROOT)),
        "source_profile_sha256": sha256(profile_path),
        "mask_archive_sha256": sha256(output),
        "mask_archive_path": str(output.relative_to(ROOT)) if output.is_relative_to(ROOT) else str(output),
        "validated_days": len(dates),
        "cadence_seconds": cadence_seconds,
        "minutes_per_day": int(masks.shape[1]),
        "sample_count": int(masks.size),
        "dropout_count": int(masks.sum()),
        "dropout_rate": float(masks.mean()),
        "dates": dates,
        "per_day_dropout_counts": [int(row.sum()) for row in masks],
        "interpretation": "Compact minute-sampled CASSIOPE onboard attitude-solution availability sequences. Not ground-sensor missed acquisitions or fleet-wide failure samples.",
    }
    sidecar = output.with_suffix(".json")
    sidecar.write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DATA)
    parser.add_argument("--cadence-seconds", type=int, default=60)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    result = export(args.data if args.data.is_absolute() else ROOT / args.data,
                    args.cadence_seconds, args.output)
    print(json.dumps({key: result[key] for key in (
        "status", "mask_archive_path", "validated_days", "sample_count",
        "dropout_count", "dropout_rate", "mask_archive_sha256")}, indent=2))


if __name__ == "__main__":
    main()
