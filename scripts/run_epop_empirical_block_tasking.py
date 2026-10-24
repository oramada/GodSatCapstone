#!/usr/bin/env python3
"""Replay audited empirical CASSIOPE outage blocks over the weekly full catalog."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.audit_full_catalog_tasking import audit as audit_tasking
from scripts.run_full_catalog_tasking import run as run_tasking


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, default=ROOT / "data/attitude/cassiope_epop/dropout_profile_1minute.json")
    parser.add_argument("--masks", type=Path, default=ROOT / "data/attitude/cassiope_epop/dropout_masks_1minute.npz")
    parser.add_argument("--mask-audit", type=Path, default=ROOT / "data/attitude/cassiope_epop/dropout_masks_independent_audit.json")
    parser.add_argument("--weekly-reference", type=Path, default=ROOT / "outputs/full-catalog-tasking-weekly-2022-2026/summary.json")
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/full-catalog-tasking-epop-empirical-block-weekly-2022-2026")
    parser.add_argument("--max-date-regimes", type=int, help="pilot only; omit to run all weekly dates and regimes")
    parser.add_argument("--one-date-pilot", action="store_true", help="run and independently audit only the first weekly date")
    args = parser.parse_args()
    def resolve(path: Path) -> Path:
        return path if path.is_absolute() else ROOT / path
    profile_path, masks_path, mask_audit_path = map(resolve, (args.profile, args.masks, args.mask_audit))
    reference_path, output = map(resolve, (args.weekly_reference, args.output))
    profile = json.loads(profile_path.read_text())
    mask_audit = json.loads(mask_audit_path.read_text())
    if profile.get("status") != "completed" or profile.get("published_days_analyzed", 0) < 1:
        raise ValueError("A completed empirical CASSIOPE dropout profile is required")
    if (mask_audit.get("status") != "passed_independent_source_replay"
            or mask_audit.get("source_profile_sha256") != sha256(profile_path)
            or mask_audit.get("mask_archive_sha256") != sha256(masks_path)
            or mask_audit.get("cadence_seconds") != 60):
        raise ValueError("Mask archive has not passed its independent source-replay audit")
    with np.load(masks_path, allow_pickle=False) as archive:
        mask_dates = archive["dates"].astype(str).tolist()
        masks = archive["dropout"].astype(bool)
    if len(mask_dates) != mask_audit.get("dates_checked") or masks.shape != (len(mask_dates), 1440):
        raise ValueError("Empirical mask dimensions differ from the independent audit")
    if not np.isclose(masks.mean(), profile["one_minute_attitude_solution_dropout_rate"], atol=0, rtol=0):
        raise ValueError("Empirical mask outage rate differs from its source profile")
    telemetry_audit = json.loads((profile_path.parent / "independent_audit.json").read_text())
    if (telemetry_audit.get("status") != "passed_structural_and_statistical"
            or mask_dates != telemetry_audit.get("validated_dates")):
        raise ValueError("Mask dates differ from independently audited telemetry dates")
    reference = json.loads(reference_path.read_text())
    weekly_dates = reference.get("dates", [])
    if (reference.get("status") != "completed" or len(weekly_dates) != 208
            or weekly_dates[0] != "2022-10-15T00:00:00Z" or weekly_dates[-1] != "2026-10-03T00:00:00Z"):
        raise ValueError("Audited 208-date weekly full-catalog design is unavailable")
    reference_audit = json.loads((reference_path.parent / "independent_audit.json").read_text())
    if (reference_audit.get("status") != "passed_structural_and_statistical"
            or reference_audit.get("paired_date_regime_cells_checked") != 832
            or reference_audit.get("response_rows_checked") != 1664):
        raise ValueError("Weekly all-catalog source design did not pass its independent audit")
    dates = weekly_dates[:1] if args.one_date_pilot else weekly_dates
    rates = (0.0, float(profile["one_minute_attitude_solution_dropout_rate"]))
    result = run_tasking(
        output, dates, args.max_date_regimes, "all", rates, profile, sha256(profile_path),
        str(profile_path.relative_to(ROOT)) if profile_path.is_relative_to(ROOT) else str(profile_path),
        empirical_dropout_masks=masks, empirical_dropout_metadata=mask_audit)
    audit = audit_tasking(output) if result["status"] == "completed" else None
    print(json.dumps({
        "status": audit["status"] if audit else "partial_pilot_not_independently_audited",
        "output": str(output),
        "independent_audit": str(output / "independent_audit.json") if audit else None,
        "completed_date_regime_groups": result["completed_date_regime_groups"],
        "expected_date_regime_groups": result["expected_date_regime_groups"],
        "response_rows": len(result["rows"]),
        "mask_days": len(mask_dates),
        "mask_sha256": mask_audit["mask_archive_sha256"],
    }, indent=2))


if __name__ == "__main__":
    main()
