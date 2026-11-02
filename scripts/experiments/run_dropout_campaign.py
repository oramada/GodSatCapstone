"""Run paired dropout with checkpoint, scenario, data, and software binding."""
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

import torch

from godsat.dropout import monthly_dates, quarterly_dates, run_dropout_study
from godsat.experiment import runtime_provenance, write_json
from godsat.orbits import ROOT
from godsat.scenario import prepare
from scripts.validation.audit_dropout_results import audit


def sha256(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def input_provenance(config, campaign, dates, regimes, model_seeds):
    """Bind resumption to actual input bytes rather than checkpoint filenames."""
    campaign = Path(campaign)
    scenarios = {}
    for date in dates:
        for regime in regimes:
            path = prepare(date, config, regime=regime)
            scenarios[f"{date}:{regime}"] = {
                "arrays_sha256": sha256(path),
                "metadata_sha256": sha256(path.with_suffix(".json")),
            }
        print(f"Bound dropout scenario inputs for {date}", flush=True)
    cohort = config.get("sensor_cohort", "current_payload")
    cohort_manifest = ROOT / "data" / f"{cohort}_orbit_history.parquet.manifest.json"
    if cohort == "current_payload":
        cohort_manifest = ROOT / "data/current_payload_orbit_history.manifest.json"
    return {
        "schema": 1,
        "campaign_config_sha256": sha256(campaign / "config.json"),
        "campaign_summary_sha256": sha256(campaign / "summary.json"),
        "checkpoints_sha256": {str(seed): sha256(campaign / "models" / f"validate_doe_recommended_{seed}.pt")
                               for seed in model_seeds},
        "raw_archive_receipt_sha256": sha256(ROOT / "data/raw/manifest.json"),
        "sensor_cohort_manifest_sha256": sha256(cohort_manifest) if cohort_manifest.exists() else None,
        "scenarios": scenarios,
        "runtime": runtime_provenance(),
        "orchestration_script_sha256": sha256(Path(__file__)),
        "inference_device": "cpu", "inference_threads": 1,
    }


def run(campaign, output, date_grid="quarterly", replicates=20):
    campaign, output = Path(campaign).resolve(), Path(output).resolve()
    config = json.loads((campaign / "config.json").read_text())
    summary = json.loads((campaign / "summary.json").read_text())
    if summary.get("status") != "completed":
        raise ValueError("The source campaign must finish before frozen-policy dropout")
    if replicates < 2:
        raise ValueError("At least two paired simulation replicates are required")
    dates = quarterly_dates() if date_grid == "quarterly" else monthly_dates()
    regimes = config.get("dropout_regimes", ["leo", "meo", "geo", "heo"])
    seeds = list(map(int, config["validation_seeds"]))
    config.update(dropout_dates=dates, dropout_model_seeds=seeds,
                  compute_device="cpu")
    config["dropout_input_provenance"] = input_provenance(config, campaign, dates, regimes, seeds)
    output.mkdir(parents=True, exist_ok=True)
    if (output / "dropout_responses.csv").exists():
        integrity = audit(output)
        if integrity["status"] not in {"completed_valid", "partial_checkpoint",
                                      "all_rows_present_summary_pending"}:
            raise ValueError(f"Cannot resume inconsistent dropout responses: {integrity['status']}")
    torch.set_num_threads(1)
    result = run_dropout_study(config, campaign, output, replicates=replicates)
    integrity = audit(output)
    if integrity["status"] != "completed_valid":
        raise ValueError(f"Completed dropout failed design integrity: {integrity['status']}")
    write_json(output / "bound_input_provenance.json", config["dropout_input_provenance"])
    return {"status": result["status"], "date_count": len(dates),
            "checkpoint_count": len(seeds), "regime_count": len(regimes),
            "response_rows": integrity["rows_read"], "output": str(output)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dates", choices=("quarterly", "monthly"), default="quarterly")
    parser.add_argument("--replicates", type=int, default=20)
    args = parser.parse_args()
    print(json.dumps(run(args.campaign, args.output, args.dates, args.replicates), indent=2))


if __name__ == "__main__":
    main()
