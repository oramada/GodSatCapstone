"""Audit every historical dropout scenario's selected sensor-host metadata."""
from __future__ import annotations

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))


import argparse
import datetime as dt
import hashlib
import json
import pathlib

from godsat.dropout import monthly_dates, quarterly_dates
from godsat.orbits import ROOT
from godsat.scenario import cache_key

ACTIVE_STATUSES = {"+", "B", "P", "S", "X"}
REGIMES = ("leo", "meo", "geo", "heo")


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def audit(root=ROOT, config_path=None, output=None):
    root = pathlib.Path(root).resolve()
    config_path = pathlib.Path(config_path or root / "configs/archive/all-orbits-paper-exact-active-hosts-dropout5.json")
    if not config_path.is_absolute():
        config_path = root / config_path
    config = json.loads(config_path.read_text())
    if config.get("sensor_cohort") != "current_active_payload":
        raise ValueError("The scenario audit requires sensor_cohort=current_active_payload")
    expected_agents = int(config["agents"])
    allowed_types = {"PAY"}
    findings = []
    design_counts = {}
    for name, dates in (("quarterly", quarterly_dates()), ("monthly", monthly_dates())):
        checked = 0
        for date in dates:
            for regime in REGIMES:
                key = cache_key(date, config, regime)
                data_path = root / "data/scenarios" / f"{key}.npz"
                metadata_path = data_path.with_suffix(".json")
                if not data_path.is_file() or not metadata_path.is_file():
                    findings.append({"date": date, "regime": regime, "error": "scenario cache or metadata missing"})
                    continue
                metadata = json.loads(metadata_path.read_text())
                sensor_ids = metadata.get("agents", [])
                types = metadata.get("object_types", [])[:expected_agents]
                statuses = metadata.get("ops_status_codes", [])[:expected_agents]
                errors = []
                if metadata.get("sensor_cohort") != "current_active_payload":
                    errors.append("metadata cohort differs from requested active-payload cohort")
                if len(sensor_ids) != expected_agents:
                    errors.append(f"expected {expected_agents} hosts; found {len(sensor_ids)}")
                if len(types) != expected_agents or not set(types) <= allowed_types:
                    errors.append(f"sensor hosts include unexpected or unknown object types: {types}")
                if len(statuses) != expected_agents or not set(statuses) <= ACTIVE_STATUSES:
                    errors.append(f"sensor hosts include inactive or unknown SATCAT statuses: {statuses}")
                if errors:
                    findings.append({"date": date, "regime": regime, "errors": errors})
                checked += 1
        design_counts[name] = {"dates": len(dates), "regimes": len(REGIMES), "scenarios_checked": checked}
    if findings:
        raise RuntimeError(json.dumps({"status": "failed", "findings": findings}, indent=2))

    output = pathlib.Path(output or root / "outputs/active-host-scenario-audit-2022-2026.json")
    if not output.is_absolute():
        output = root / output
    output.parent.mkdir(parents=True, exist_ok=True)
    history_path = root / "data/current_active_payload_orbit_history.parquet"
    history_manifest_path = history_path.with_suffix(history_path.suffix + ".manifest.json")
    status_audit_path = root / "data/current_payload_status_audit.json"
    result = {
        "status": "completed",
        "audited_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "sensor_host_cohort": "current_active_payload",
        "expected_sensor_host_count_per_scenario": expected_agents,
        "allowed_object_types": sorted(allowed_types),
        "allowed_satcat_ops_statuses": sorted(ACTIVE_STATUSES),
        "cohort_history_sha256": sha256(history_path),
        "cohort_history_manifest_sha256": sha256(history_manifest_path),
        "status_audit_sha256": sha256(status_audit_path),
        "designs": design_counts,
        "scenarios_checked": sum(item["scenarios_checked"] for item in design_counts.values()),
        "invalid_scenarios": 0,
        "interpretation": "Current active-GP/SATCAT snapshot backcast through archived elements; it does not establish that hosts were operational at each historical epoch.",
    }
    output.write_text(json.dumps(result, indent=2) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=pathlib.Path)
    parser.add_argument("--output", type=pathlib.Path)
    args = parser.parse_args()
    print(json.dumps(audit(config_path=args.config, output=args.output), indent=2))


if __name__ == "__main__":
    main()
