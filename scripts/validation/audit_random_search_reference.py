"""Independently verify the persisted random-search reference campaign."""

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))

import argparse
import csv
import hashlib
import json
import pathlib


def load(path):
    return json.loads(pathlib.Path(path).read_text())


def rows(path):
    with pathlib.Path(path).open(newline="") as stream:
        return list(csv.DictReader(stream))


def digest(path):
    h = hashlib.sha256()
    with pathlib.Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def audit(root):
    root = pathlib.Path(root).expanduser().resolve()
    config = load(root / "config.json")
    summary = load(root / "summary.json")
    budget = int(config["budget"])
    expected = {f"random_{i:02d}" for i in range(budget)}
    run_paths = {path.stem: path for path in (root / "runs").glob("random_*.json")}
    if set(run_paths) != expected:
        raise ValueError("Random-search treatment run files are missing, duplicated, or unexpected")
    design = rows(root / "random_search_design.csv")
    responses = rows(root / "responses.csv")
    if len(design) != budget or {row["name"] for row in design} != expected:
        raise ValueError("Random-search design is incomplete or duplicated")
    if len(responses) != budget or {row["name"] for row in responses} != expected:
        raise ValueError("Random-search response table is incomplete or duplicated")
    records = {name: load(path) for name, path in run_paths.items()}
    if any(record.get("status") == "failed" for record in records.values()):
        raise ValueError("A random-search treatment is marked failed")
    best_name = max(records, key=lambda name: float(records[name]["objective"]))
    if summary.get("selected_run") != best_name:
        raise ValueError("Selected run is not the validation-objective maximum")
    if not (root / "models" / f"{best_name}.pt").is_file():
        raise ValueError("Selected random-search checkpoint is missing")

    validation = rows(root / "validation.csv")
    seeds = list(map(int, config["config"]["validation_seeds"]))
    if len(validation) != len(seeds):
        raise ValueError("Held-out validation row count does not match configured seeds")
    pairs = [(row["configuration"], int(row["seed"])) for row in validation]
    expected_pairs = [("random_search_best", seed) for seed in seeds]
    if sorted(pairs) != sorted(expected_pairs):
        raise ValueError("Held-out policy/seed rows are missing or duplicated")
    if summary.get("selection_split") != "validation" or not summary.get("heldout_test_dates"):
        raise ValueError("Selection/test split provenance is incomplete")

    checkpoint_hashes = summary.get("checkpoint_sha256", {})
    expected_checkpoint_names = expected | {
        f"validate_random_search_best_{seed}" for seed in seeds
    }
    if set(checkpoint_hashes) != expected_checkpoint_names:
        raise ValueError("Checkpoint hash inventory does not exactly cover search and retrain runs")
    for name, expected_hash in checkpoint_hashes.items():
        path = root / "models" / f"{name}.pt"
        if not path.is_file() or digest(path) != expected_hash:
            raise ValueError(f"Checkpoint is missing or changed: {name}")

    result = {
        "status": "validated_complete",
        "output": str(root),
        "search_trials": budget,
        "retrained_heldout_seeds": len(validation),
        "selected_run": best_name,
        "checks": {
            "design_response_and_run_counts_match": True,
            "selection_uses_validation_objective_only": True,
            "heldout_seed_rows_complete": True,
            "checkpoint_hashes_match": True,
            "selected_checkpoint_exists": True,
        },
    }
    (root / "random_search_integrity_audit.json").write_text(
        json.dumps(result, indent=2) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(json.dumps(audit(args.output), indent=2))


if __name__ == "__main__":
    main()
