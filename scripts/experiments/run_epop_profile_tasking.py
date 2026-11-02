#!/usr/bin/env python3
"""Run weekly all-catalog tasking with a dropout profile estimated from CASSIOPE telemetry."""
from __future__ import annotations

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))


import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.validation.audit_full_catalog_tasking import audit as audit_tasking
from scripts.experiments.run_full_catalog_tasking import run as run_tasking


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, default=ROOT / "data/attitude/cassiope_epop/dropout_profile_1minute.json")
    parser.add_argument("--weekly-reference", type=Path, default=ROOT / "outputs/full-catalog-tasking-weekly-2022-2026/summary.json")
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/full-catalog-tasking-epop-profile-weekly-2022-2026")
    parser.add_argument("--max-date-regimes", type=int, help="pilot only; omit to run all weekly dates and regimes")
    args = parser.parse_args()
    profile_path = args.profile if args.profile.is_absolute() else ROOT / args.profile
    reference_path = args.weekly_reference if args.weekly_reference.is_absolute() else ROOT / args.weekly_reference
    output = args.output if args.output.is_absolute() else ROOT / args.output
    profile = json.loads(profile_path.read_text())
    if profile.get("status") != "completed" or profile.get("published_days_analyzed", 0) < 1:
        raise ValueError("A completed empirical CASSIOPE dropout profile is required")
    rates = (0.0, float(profile["one_minute_attitude_solution_dropout_rate"]))
    persistence = float(profile["simulator_markov_persistence_parameter"])
    if not 0 < rates[1] < 1 or not 0 <= persistence < 1:
        raise ValueError("Empirical dropout rate or persistence is invalid")
    telemetry_audit = json.loads((profile_path.parent / "independent_audit.json").read_text())
    audited_dates = set(telemetry_audit.get("validated_dates", []))
    profile_dates = {row.get("date") for row in profile.get("per_day", [])}
    if (telemetry_audit.get("status") != "passed_structural_and_statistical"
            or not profile_dates or not profile_dates.issubset(audited_dates)
            or len(profile_dates) != profile.get("published_days_analyzed")):
        raise ValueError("The empirical dropout profile does not match an independent attitude-data audit")
    reference = json.loads(reference_path.read_text())
    dates = reference.get("dates", [])
    if (reference.get("status") != "completed" or len(dates) != 208
            or dates[0] != "2022-10-15T00:00:00Z" or dates[-1] != "2026-10-03T00:00:00Z"):
        raise ValueError("The audited 208-date weekly full-catalog design is unavailable")
    reference_audit = json.loads((reference_path.parent / "independent_audit.json").read_text())
    if (reference_audit.get("status") != "passed_structural_and_statistical"
            or reference_audit.get("dates_checked") != 208
            or reference_audit.get("paired_date_regime_cells_checked") != 832
            or reference_audit.get("response_rows_checked") != 1664):
        raise ValueError("Weekly all-catalog source design did not pass its independent audit")

    result = run_tasking(output, dates, args.max_date_regimes, "all", rates, profile,
                         sha256(profile_path), str(profile_path.relative_to(ROOT))
                         if profile_path.is_relative_to(ROOT) else str(profile_path))
    audit = audit_tasking(output) if result["status"] == "completed" else None
    print(json.dumps({
        "status": audit["status"] if audit else "partial_pilot_not_independently_audited",
        "output": str(output),
        "independent_audit": str(output / "independent_audit.json") if audit else None,
        "profile_source_sha256": sha256(profile_path),
        "outage_rate": rates[1],
        "persistence_per_minute": persistence,
        "date_regime_groups": result["completed_date_regime_groups"],
        "response_rows": len(result["rows"]),
    }, indent=2))


if __name__ == "__main__":
    main()
